#!/usr/bin/env python3
"""Tracker-vs-live-app reconciliation in ONE audited command.

Done by hand this is ad-hoc python snippets per player and manual
res/tr/prod corrections — with sign-errors that need a
correction-of-a-correction. This script is the whole ritual:

    python3 scripts/verify.py           # drift table, no changes
    python3 scripts/verify.py --sync    # adopt the app's values (logged)

The live app is AUTHORITATIVE for every app-mode game (it enforces the
real rules); the tracker is the advisor's derived view. Run after every
generation turnover (produce.py) and before any scoring claim.

Four checks per run: resources/production/TR/tableau drift, globals, tile
COUNTERS vs the tracker's own board record, and tile LOCATIONS vs the
app's board (`TILE LOCATION` rows — a tile on the wrong hex keeps every
counter right and still poisons `apply.py spaces`, greenery legality and
city-adjacency VP). `--sync` refuses to adopt resource values while the
app is a generation ahead of the tracker (run `listen.py once` first) —
those numbers are post-production and produce.py would add the income
twice.

The sync machinery is a library, not just a CLI: `from_view` turns ONE
/api/player payload into every player's mat (players[] carries the whole
public table), `sync_player` adopts one player's drifted values, and
`sync_table` is the full adoption — mats, my hand, my tableau, everyone's
card resources, globals, tile positions and counters. scripts/listen.py
ends every drain with it and scripts/execute.py adopts the app view after
every send: in app modes the APP is the rules engine and the tracker is
its shadow (the sandbox simulation stays for planning and physical mode).
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tmlib
from appapi import TILE_TYPES, AppClient
from tmlib import Engine, EventError, Store

FIELDS = ("mc", "steel", "titanium", "plants", "energy", "heat")
LABELS = {"mc": "MC", "tr": "TR"}


class ViewClient(AppClient):
    """An AppClient that serves ONE captured /api/player payload — lets
    `_fetch_app` parse a view a caller already holds (the listener's
    drain, the executor's post-send view) without a second HTTP round
    trip."""

    def __init__(self, view: dict):
        super().__init__("http://cached.invalid")
        self._view = view

    def player(self, pid: str = "") -> dict:
        return self._view


def _tile_name(n: int) -> str:
    """App TileType enum → the tracker's tile vocabulary ('Natural
    Preserve' → 'naturalpreserve', the form apply.py place records)."""
    if isinstance(n, int) and 0 <= n < len(TILE_TYPES):
        return TILE_TYPES[n].lower().replace(" ", "")
    return f"tile{n}"


# The tracker's own placement vocabulary (`apply.py place`): four GENERIC
# terms, each standing for a CLASS of tiles rather than one specific tile.
GENERIC_TILES = ("city", "greenery", "ocean", "special")


def _tile_class(tile: str) -> str:
    """Any tile name — a generic tracker term or the app's specific one —
    reduced to the class the tracker records.

    This is `tmlib.tile_counts`' own rule, the counter that has to agree
    with the board, so no tile list lives here: whatever is not a city
    tile, a greenery or a non-scoring tile is a special tile.
    """
    if tile in tmlib.CITY_TILES:            # city, capital
        return "city"
    if tile == "greenery":
        return "greenery"
    if tile in tmlib.NON_SCORING_TILES:     # ocean, land claim: own class
        return tile
    return "special"


def tiles_agree(tracker: str, app: str) -> bool:
    """Do the tracker's tile and the app's tile describe the same tile?

    P9 #6: `place` records `special` while the app's board names the exact
    tile, so comparing the raw strings printed a `TILE LOCATION` row for
    every special tile of the game against state that was byte-exact. A
    generic term matches any app tile of ITS OWN class and nothing else —
    a class change (special vs capital, city vs ocean) and two DIFFERENT
    specific names still disagree.
    """
    if tracker == app:
        return True
    if tracker in GENERIC_TILES and _tile_class(app) == tracker:
        return True
    if app in GENERIC_TILES and _tile_class(tracker) == app:
        return True
    return False


def _mat(p: dict) -> dict:
    """The resource / production / TR block of a player model. thisPlayer
    and every entry of players[] carry the SAME field names (the public
    model omits only the hidden information), so one parser serves both."""
    return {"mc": p["megacredits"], "steel": p["steel"],
            "titanium": p["titanium"], "plants": p["plants"],
            "energy": p["energy"], "heat": p["heat"],
            "tr": p["terraformRating"],
            "prod": {"mc": p["megacreditProduction"],
                     "steel": p["steelProduction"],
                     "titanium": p["titaniumProduction"],
                     "plants": p.get("plantProduction") or 0,
                     "energy": p["energyProduction"],
                     "heat": p["heatProduction"]}}


def _hand_names(data: dict) -> list[str] | None:
    """The app's hand for the player this view belongs to. The real
    PlayerViewModel carries it at the TOP level (thisPlayer only has
    cardsInHandNbr); older fakes nest it."""
    src = data.get("cardsInHand")
    if not isinstance(src, list):
        src = (data.get("thisPlayer") or {}).get("cardsInHand")
    if not isinstance(src, list):
        return None
    return [c.get("name") if isinstance(c, dict) else str(c) for c in src]


def _fetch_app(base, pid: str) -> dict:
    """`base` = app URL string or an AppClient (scripts/appapi.py)."""
    client = base if isinstance(base, AppClient) else AppClient(base)
    data = client.player(pid)
    tp = data["thisPlayer"]
    out = _mat(tp)
    hand = _hand_names(data)
    if hand is not None:
        out["hand"] = hand
    g = data.get("game")
    if g:  # globals + the whole table's public info ride along
        if "temperature" in g:
            out["globals"] = {"temperature": g["temperature"],
                              "oxygen": g["oxygenLevel"], "oceans": g["oceans"]}
        if "milestones" in g:
            out["milestones"] = {m["name"]: m["playerName"]
                                 for m in g["milestones"] if m.get("playerName")}
        if "awards" in g:
            out["awards"] = {a["name"]: a["playerName"]
                             for a in g["awards"] if a.get("playerName")}
        if data.get("players") and all("tableau" in p for p in data["players"]):
            out["tableau"] = {p["name"]: [c["name"] for c in p["tableau"][1:]]
                              for p in data["players"]}   # [0] = corporation
            # accumulators (animals, microbes, science, floaters …): the
            # app counts them per tableau card, the tracker keys them by
            # card name (pool["cardResources"]). Corporations can hold
            # them too, so [0] is NOT skipped here.
            out["cardResources"] = {
                p["name"]: {c["name"]: int(c["resources"])
                            for c in p["tableau"]
                            if isinstance(c, dict)
                            and isinstance(c.get("resources"), int)}
                for p in data["players"]}
        # the app's own clock: `--sync` must not adopt post-production
        # values while the tracker is still a generation behind (#17)
        out["generation"] = g.get("generation")
        out["phase"] = g.get("phase")
        # tile LOCATIONS, not just counters (#13): id → tile + owner name.
        # Oceans carry no colour (they belong to nobody); colony spaces are
        # off-Mars and never appear in the tracker's board record.
        if g.get("spaces") is not None:
            colors = {p.get("color"): p.get("name")
                      for p in data.get("players", [])}
            out["spaces"] = {
                str(s["id"]): {"tile": _tile_name(s.get("tileType")),
                               "player": colors.get(s.get("color"))}
                for s in g["spaces"]
                if s.get("tileType") is not None
                and s.get("spaceType") != "colony"}
    return out


def from_view(view: dict) -> dict:
    """{player name: the same dict `_fetch_app` returns} for EVERY player
    in ONE /api/player payload.

    players[] carries every public mat (resources, production, TR,
    tableau) plus the table-wide blocks (globals, milestones, awards,
    spaces), so one view is the whole table — no per-opponent HTTP call.
    Only the hand is private: it rides on the view's own player.
    """
    shared = _fetch_app(ViewClient(view), "")
    hand = shared.pop("hand", None)
    out: dict[str, dict] = {}
    me = (view.get("thisPlayer") or {}).get("name")
    if me:
        out[me] = dict(shared, **({"hand": hand} if hand is not None else {}))
    for p in view.get("players") or []:
        name = p.get("name")
        if not name or name in out or "megacredits" not in p:
            continue                      # a stub entry: no public mat
        out[name] = dict(shared, **_mat(p))
    return out


def _public_drift(eng: Engine, name: str, app: dict) -> dict:
    """Cards / milestones / awards the app shows for an OPPONENT
    that the tracker lacks. Values are name lists (numeric drift = tuples)."""
    game = eng.store.load_game()
    have = {c["name"] for c in game["opponents"][name]["playedCards"]}
    cards = []
    for c in app["tableau"].get(name, []):
        info = eng.card(c)
        if info is None:
            print(f"  ⚠ {name}: {c!r} not in cards/db.json — skipped", file=sys.stderr)
        elif info["name"] not in have:
            cards.append(info["name"])
    ms = [m for m, who in app["milestones"].items()
          if who == name and m not in game["milestonesClaimed"]]
    aw = [a for a, who in app["awards"].items()
          if who == name and a not in game.get("awardsFunded", {})]
    return {k: v for k, v in (("tableau", cards), ("milestone", ms), ("award", aw)) if v}


def _tracker_view(eng: Engine, name: str) -> dict:
    game = eng.store.load_game()
    pool = game["me"] if eng._is_me(name) else game["opponents"][name]
    return {"res": pool["resources"], "prod": pool["production"],
            "tr": pool["tr"]}


def diff(eng: Engine, names: list[str], fetch) -> list[dict]:
    """Per player: {'player', 'drift': {field: (tracker, app)}} — empty
    drift dict = byte-exact match."""
    rows = []
    for name in names:
        app = fetch(name)
        if not rows and app.get("globals"):   # globals row first
            cur = eng.store.load_game()["globals"]
            rows.append({"player": "globals", "drift": {
                p: (cur[p], v) for p, v in app["globals"].items() if cur[p] != v}})
        t = _tracker_view(eng, name)
        d = {}
        for f in FIELDS:
            if t["res"][f] != app[f]:
                d[f] = (t["res"][f], app[f])
        if t["tr"] != app["tr"]:
            d["tr"] = (t["tr"], app["tr"])
        for f in FIELDS:
            if t["prod"][f] != app["prod"][f]:
                d[f"prod.{f}"] = (t["prod"][f], app["prod"][f])
        if app.get("tableau") and not eng._is_me(name):   # opponents only
            d.update(_public_drift(eng, name, app))
        rows.append({"player": name, "drift": d})
    return rows


def board_counts(game: dict, name: str) -> dict:
    """Tile counts derived from `game["board"]` — the authoritative record
    of what is physically on the map. Oceans (and land-claim markers) are
    excluded on purpose: they belong to no player and never score.

    The counting itself is THE tile counter (`tmlib.tile_counts`), read
    with NO cache floor: this function's whole job is to say what the board
    alone knows, so board_drift can compare it against the counters."""
    counts = tmlib.tile_counts({"board": game.get("board") or {},
                                "me": {"name": name}}, name,
                               pool={"tiles": {}})
    return {"cities": counts["citiesOnMars"], "greeneries": counts["greeneries"],
            "special": counts["special"]}


def board_drift(eng: Engine, names: list[str]) -> list[dict]:
    """INTERNAL consistency: each player's derived tile counters vs the
    tracker's own board record. Needs no app, so it is the only tile check
    available in physical mode — where there is nothing to diff against.

    Added after P7 (the first full-autopilot game): the counters drifted all game
    and verify.py could not see it, because it compared only MC / TR /
    production / hand. The drift inverted the Landlord race, fired a false
    Mayor alert and corrupted Greenhouses' per-city arithmetic.
    """
    game = eng.store.load_game()
    rows = []
    for name in names:
        pool = game["me"] if eng._is_me(name) else game["opponents"][name]
        tiles = pool.get("tiles") or {}
        truth = board_counts(game, name)
        # reserved-area cities are off-Mars and never appear on the board
        truth["cities"] += tiles.get("citiesOffMars", 0)
        d = {f"tiles.{k}": (tiles.get(k, 0), v)
             for k, v in truth.items() if tiles.get(k, 0) != v}
        if d:
            rows.append({"player": name, "drift": d})
    return rows


def ocean_track_drift(eng: Engine) -> tuple[int, int] | None:
    """(track, tiles on the board) when the oceans PARAMETER and the board
    disagree — otherwise None.

    Nine oceans end the game and every ocean is +1 TR, so the two must never
    part. They do: a bonus ocean (the 0 °C temperature step) and a card that
    places one on a land hex hand the parameter raise back to the human as a
    "→ TABLE" step, and a replay of three practice games finished at oceans
    8 against a board of 9 — the placer a TR light, and a Terraformer claim
    refused behind it. Like board_drift() this needs no app, so it is a
    check that works at the physical table too.
    """
    game = eng.store.load_game()
    on_board = sum(1 for v in (game.get("board") or {}).values()
                   if v.get("tile") == "ocean")
    track = game["globals"]["oceans"]
    return None if track == on_board else (track, on_board)


def sync_ocean_track(eng: Engine) -> list[str]:
    """Raise the oceans track to the board (never lower it: a track AHEAD of
    the board means a placed tile was not recorded, and the fix for that is
    `apply.py place`, not a smaller parameter)."""
    d = ocean_track_drift(eng)
    if d is None or d[1] <= d[0]:
        return []
    return [eng.sync_global("oceans", d[1]) + "  [oceans track vs board]"]


def location_drift(eng: Engine, app_spaces: dict) -> list[dict]:
    """Tile LOCATIONS: the app's occupied spaces vs `game["board"]`.

    board_drift() above reconciles tile COUNTERS; a tile recorded on the
    WRONG HEX keeps every counter right and still corrupts everything
    positional — `apply.py spaces` offers an occupied hex as free, city
    adjacency VP is computed against tiles that are not there, and greenery
    legality is judged off a fiction (P8 #13: six of an opponent's
    greeneries were missing from the record and nothing could see it).

    Rows: {'space', 'kind', 'app', 'tracker'} where kind is
    missing (app has a tile the tracker lacks) | phantom (the tracker has
    one the app lacks) | mismatch (same hex, different tile or owner).
    Oceans carry no owner in the app view, so only their tile type is
    compared, and the tracker's generic tile vocabulary is matched by
    CLASS against the app's specific tile name (`tiles_agree`).
    """
    board = eng.store.load_game().get("board") or {}
    rows = []
    for sid in sorted(set(board) | set(app_spaces)):
        app = app_spaces.get(sid)
        cur = board.get(sid)
        tracker = {"tile": cur["tile"], "player": cur["player"]} if cur else None
        if app is None:
            rows.append({"space": sid, "kind": "phantom",
                         "app": None, "tracker": tracker})
        elif tracker is None:
            rows.append({"space": sid, "kind": "missing",
                         "app": app, "tracker": None})
        elif not tiles_agree(tracker["tile"], app["tile"]) or (
                app["player"] is not None
                and app["player"] != tracker["player"]):
            rows.append({"space": sid, "kind": "mismatch",
                         "app": app, "tracker": tracker})
    return rows


def _occ(entry: dict | None) -> str:
    if not entry:
        return "(empty)"
    return f"{entry.get('player') or 'nobody'} {entry['tile']}"


def location_lines(rows: list[dict]) -> list[str]:
    return [f"  TILE LOCATION  {r['space']}  app: {_occ(r['app'])}  "
            f"tracker: {_occ(r['tracker'])}  [{r['kind']}]" for r in rows]


def sync_locations(eng: Engine, app_spaces: dict) -> list[str]:
    """Adopt the app's tile positions (logged, no placement bonuses).

    A tile recorded on the wrong hex is MOVED — the same tile/owner pair
    missing here and phantom there is one placement, not two. Bonuses,
    adjacency MC and legality were settled by the app when the tile was
    actually placed, so this records position only; the tile COUNTERS are
    then reconciled to the repaired board by sync_board().
    """
    rows = location_drift(eng, app_spaces)
    if not rows:
        return []
    phantoms = [r for r in rows if r["kind"] == "phantom"]
    game = eng.store.load_game()
    board = game.setdefault("board", {})
    out = []
    for r in rows:
        if r["kind"] == "phantom":
            continue
        sid, app = r["space"], dict(r["app"])
        if r["kind"] == "missing":
            src = next((p for p in phantoms
                        if tiles_agree(p["tracker"]["tile"], app["tile"])
                        and (app["player"] is None
                             or p["tracker"]["player"] == app["player"])), None)
            if src is not None:
                phantoms.remove(src)
                board.pop(src["space"], None)
                if app["player"] is None:      # oceans: keep who placed it
                    app["player"] = src["tracker"]["player"]
                out.append(f"TILE LOCATION: {app['player']} {app['tile']} "
                           f"moved {src['space']} → {sid} [app]")
            else:
                out.append(f"TILE LOCATION: {_occ(app)} added on {sid} [app]")
        else:                                   # mismatch: the app rules
            if app["player"] is None:
                app["player"] = board[sid]["player"]
            out.append(f"TILE LOCATION: {sid} {_occ(r['tracker'])} → "
                       f"{_occ(app)} [app]")
        board[sid] = {"tile": app["tile"], "player": app["player"]}
    for p in phantoms:                          # nothing to move it to
        board.pop(p["space"], None)
        out.append(f"TILE LOCATION: {_occ(p['tracker'])} on {p['space']} "
                   f"removed (not on the app board)")
    for msg in out:
        eng._commit(game, msg)                  # save + log, one line each
    return out


def generation_guard(eng: Engine, fetch, names: list[str]) -> str | None:
    """P8 #17: `--sync` run in the window between the generation-closing
    pass and `listen.py once` ingesting "Generation N" adopted the app's
    POST-production resources; produce.py then added the same income again
    (an opponent's simulated MC ran to 100 against the app's 53). While the
    app's generation is AHEAD of the tracker's, resource adoption is
    refused — the listener has to close the generation first.

    A finished game (phase 'end') is exempt: no production can follow, and
    end-game reconciliation before scoring must keep working.
    """
    if not names:
        return None
    app = fetch(names[0])
    if app.get("phase") == "end":
        return None
    live = app.get("generation")
    tracked = eng.store.load_game()["generation"]
    if live is None or live <= tracked:
        return None
    return (f"run listen.py once first (the app is at generation {live}, "
            f"the tracker at {tracked}) — refusing to adopt resource values "
            "(they are post-production; produce.py would add the income "
            "twice). Globals and tiles still sync.")


def sync_board(eng: Engine, names: list[str]) -> list[str]:
    """Reconcile drifted tile counters to the board record (logged)."""
    out = []
    for row in board_drift(eng, names):
        for field, (_, truth) in row["drift"].items():
            out.append(eng.tiles_fix(row["player"], field.split(".", 1)[1], truth))
    return out


def sync_globals(eng: Engine, drift: dict) -> list[str]:
    """The globals row of a drift table (the app rules, downward too)."""
    return [eng.sync_global(param, live, force=True) + "  [verify --sync vs app]"
            for param, (_, live) in drift.items()]


def sync_player(eng: Engine, name: str, drift: dict, app: dict) -> list[str]:
    """Adopt ONE player's drifted values (the unit shared by `--sync`, the
    listener's table sync and the executor's post-send adoption).

    Mine goes through the res/tr/prod events a table sync would use
    (observe() is opponents-only by design); an opponent's public plays,
    milestones and awards are recorded FIRST — bookkeeping only — and the
    numeric observe() then adopts the app's cost/production/TR result, so
    nothing is counted twice.
    """
    out = []
    if eng._is_me(name):
        for field, (tracked, live) in drift.items():
            if not isinstance(live, int):
                continue
            d = live - tracked
            if field == "tr":
                msg = eng.tr(name, d)
            elif field.startswith("prod."):
                msg = eng.prod(name, field[5:], d)
            else:
                msg = eng.res(name, field, d)
            out.append(msg + "  [verify --sync vs app]")
        return out
    for card in drift.get("tableau", []):
        out.append(eng.observe_play(name, card))
    for kind, method in (("milestone", eng.milestone), ("award", eng.award)):
        for item in drift.get(kind, []):
            try:
                out.append(method(name, item) + "  [observed from app]")
            except EventError as e:
                out.append(f"⚠ {name} {kind} {item} not recorded: {e}")
    out.append(eng.observe(
        name, tr=app["tr"], mc=app["mc"], steel=app["steel"],
        titanium=app["titanium"], plants=app["plants"],
        energy=app["energy"], heat=app["heat"],
        prod_mc=app["prod"]["mc"], prod_steel=app["prod"]["steel"],
        prod_titanium=app["prod"]["titanium"],
        prod_plants=app["prod"]["plants"],
        prod_energy=app["prod"]["energy"],
        prod_heat=app["prod"]["heat"]))
    return out


def sync(eng: Engine, names: list[str], fetch) -> list[str]:
    """Adopt the app's values for every drifted field, through the
    engine's observe() (provenance-tagged, logged) — never hand-edits."""
    out = []
    blocked = generation_guard(eng, fetch, names)
    if blocked:
        out.append(f"⚠ {blocked}")
    for row in diff(eng, names, fetch):
        if not row["drift"]:
            continue
        if row["player"] == "globals":   # app is authoritative, downward too
            out += sync_globals(eng, row["drift"])
            continue
        if blocked:                      # resources stay untouched (#17)
            continue
        out += sync_player(eng, row["player"], row["drift"], fetch(row["player"]))
    return out


# ── full adoption: the app IS the rules engine in app modes ──────────

def sync_own_hand(eng: Engine, app_hand) -> list[str]:
    """Adopt the app's hand for the isMe player (names, with duplicates)."""
    if not isinstance(app_hand, list):
        return []
    hand = list(eng.store.load_game()["me"]["hand"])
    extra = list((Counter(hand) - Counter(app_hand)).elements())
    missing = list((Counter(app_hand) - Counter(hand)).elements())
    for c in extra:
        eng.hand_remove(c)
    if missing:
        eng.hand_add(missing)
    if not (extra or missing):
        return []
    return ["hand " + " ".join([f"+{c}" for c in missing]
                               + [f"−{c}" for c in extra])]


def sync_own_tableau(eng: Engine, app: dict) -> list[str]:
    """Cards the app shows in MY tableau that the tracker lacks.

    Bookkeeping ONLY — the same contract as observe_play for an opponent:
    no cost, production, global or TR side effects, because the app
    already applied them and the numeric adoption above took the result.
    Card effects the engine does not model (a blue-card action, an
    or-choice, an ocean bonus) are exactly why this exists.
    """
    game = eng.store.load_game()
    me = game["me"]
    names = (app.get("tableau") or {}).get(me["name"])
    if not names:
        return []
    have = {c["name"] for c in me["playedCards"]}
    added = []
    for c in names:
        info = eng.card(c)
        if info is None:
            print(f"  ⚠ {c!r} not in cards/db.json — not recorded", file=sys.stderr)
            continue
        canon = info["name"]
        if canon in have or canon == me.get("corporation"):
            continue
        # audited verb (iron rule 2): observe_play logs it and registers a
        # blue action in the ledger; allow_me marks it as bookkeeping.
        eng.observe_play(me["name"], canon, allow_me=True)
        have.add(canon)
        added.append(canon)
    return [f"tableau +{c}" for c in added]


def sync_card_resources(eng: Engine, names: list[str], app: dict) -> list[str]:
    """Adopt the app's per-card accumulators (animals, microbes, science,
    floaters). The tracker's own counters drift on every effect the engine
    does not model, and they are VP at scoring time."""
    counts = app.get("cardResources")
    if not counts:
        return []
    parts = []
    for name in names:
        seen = counts.get(name)
        if seen is None:
            continue
        game = eng.store.load_game()
        pool = game["me"] if eng._is_me(name) else game["opponents"].get(name)
        if pool is None:
            continue
        cur = pool.get("cardResources") or {}
        changed = {card: n for card, n in seen.items()
                   if int(cur.get(card, 0)) != n}
        if not changed:
            continue
        # audited verb (iron rule 2): the adoption is logged, not hand-written
        eng.sync_card_resources(name, changed)
        parts += [f"{name} {card} {int(cur.get(card, 0))}→{n}"
                  for card, n in changed.items()]
    return parts


def _drift_parts(name: str, drift: dict) -> list[str]:
    out = []
    for field, v in drift.items():
        if isinstance(v, tuple):
            out.append(f"{name} {_label(field)} {v[0]}→{v[1]}")
        elif v:                          # tableau / milestone / award lists
            out.append(f"{name} {field} +" + ", +".join(v))
    return out


def _label(field: str) -> str:
    if field.startswith("prod."):
        return "prod " + _label(field[5:])
    return LABELS.get(field, field)


def sync_table(eng: Engine, names: list[str], fetch,
               tile_names: list[str] | None = None) -> list[str]:
    """FULL adoption of the app view — the app is the rules engine in app
    modes, the tracker is its shadow.

    `sync()` plus the three things it deliberately leaves alone (they are
    not "drift" the advisor should reason about, they are state the app
    owns): my hand, my tableau, everyone's card resources — and then the
    tile positions and counters. The generation guard still applies: while
    the app is a generation ahead, RESOURCE values are refused (they are
    post-production; produce.py would pay the income twice) while
    hand/tableau/card resources/globals/tiles still land.

    Returns short "who what before→after" parts for a one-line summary;
    every change is logged by the engine call that made it.
    """
    parts: list[str] = []
    if not names:
        return parts
    blocked = generation_guard(eng, fetch, names)
    for row in diff(eng, names, fetch):
        name, drift = row["player"], row["drift"]
        if name == "globals":
            sync_globals(eng, drift)
            parts += _drift_parts("globals", drift)
            continue
        if not drift or blocked:
            continue
        parts += _drift_parts(name, drift)
        sync_player(eng, name, drift, fetch(name))
    app = fetch(names[0])
    game = eng.store.load_game()
    me = game["me"]["name"]
    if me in names:
        parts += sync_own_tableau(eng, app)
        parts += sync_own_hand(eng, fetch(me).get("hand"))
    all_names = tile_names or [game["me"]["name"], *game["opponents"]]
    parts += sync_card_resources(eng, all_names, app)
    spaces = app.get("spaces")
    if spaces is not None:
        parts += sync_locations(eng, spaces)
    parts += sync_board(eng, all_names)
    parts += sync_ocean_track(eng)
    if blocked:
        parts.append(f"⚠ {blocked}")
    return parts


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sync", action="store_true",
                   help="adopt the app's values for drifted fields (logged)")
    a = p.parse_args()
    root = Path(__file__).resolve().parent.parent
    setup = json.loads((root / "state" / "setup.json").read_text())
    client = AppClient.from_setup(setup)
    linked = {pl["name"]: pl["playerId"]
              for pl in setup["players"] if pl.get("playerId")}
    if not linked:
        print("No app playerIds in state/setup.json (session.py link-player)")
        return 1
    eng = Engine(Store())
    fetch = lambda name: _fetch_app(client, linked[name])
    rows = diff(eng, list(linked), fetch)
    clean = True
    for r in rows:
        if r["drift"]:
            clean = False
            ds = ", ".join(
                f"{k}: " + (", ".join("+" + x for x in v) if isinstance(v, list)
                            else f"{v[0]}→{v[1]}")
                for k, v in r["drift"].items())
            print(f"  {r['player']:<10} DRIFT  {ds}")
        else:
            print(f"  {r['player']:<10} exact")
    # tile counters vs the board record — an internal check the app cannot
    # answer, and the one class that was invisible before P7
    all_names = sorted({eng.store.load_game()["me"]["name"], *linked})
    tile_rows = board_drift(eng, all_names)
    for r in tile_rows:
        clean = False
        ds = ", ".join(f"{k}: {v[0]}→{v[1]}" for k, v in r["drift"].items())
        print(f"  {r['player']:<10} TILE DRIFT  {ds}  [counters vs board]")
    ocean_d = ocean_track_drift(eng)
    if ocean_d is not None:
        clean = False
        print(f"  {'globals':<10} OCEAN TRACK DRIFT  track {ocean_d[0]} vs "
              f"{ocean_d[1]} ocean tile(s) on the board")
    # tile LOCATIONS vs the app's own board — counters can match while a
    # tile sits on the wrong hex (P8 #13)
    spaces = _fetch_app(client, linked[next(iter(linked))]).get("spaces")
    loc_rows = location_drift(eng, spaces) if spaces is not None else []
    for line in location_lines(loc_rows):
        clean = False
        print(line)
    if clean:
        print("All players byte-exact vs live app; tile counters and "
              "positions match the board.")
        return 0
    if a.sync:
        blocked = generation_guard(eng, fetch, list(linked))
        for msg in sync(eng, list(linked), fetch):
            print(msg)
        if spaces is not None:
            for msg in sync_locations(eng, spaces):
                print(msg)
        for msg in sync_board(eng, all_names):
            print(msg)
        for msg in sync_ocean_track(eng):
            print(msg)
        if blocked:
            print("Synced globals/tiles only — resource values NOT adopted.")
            return 2
        print("Synced — re-run to confirm exact.")
        return 0
    print("Drift found — re-run with --sync to adopt the app's values.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
