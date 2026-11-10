#!/usr/bin/env python3
"""THE REGRESSION GATE: do today's scripts still reproduce REAL games?

    replay_gate.py --all
    replay_gate.py --game games/2026-08-28-game2
    replay_gate.py --app-log <log.txt> --final <final.json> --setup <setup.json>

Two kinds of target, both discovered by --all:

  APP-LOG REPLAY (the app is the truth). The app's own log export is fed to
  `replay_applog.Replayer` from a fresh session and the resulting state is
  compared, per player, with the app's own final state: TR, every tile
  position, greenery/city counts, known card VP, milestones/awards, MC.
  BOARD and TR must match EXACTLY — a difference there means the tracker
  would have shown a wrong board at the table, so the gate exits non-zero.
  MC is reported as a delta, never enforced: the export never prints what a
  card COST, so the replay's MC drifts by exactly the discounts/rebates and
  unlogged action costs it cannot see (they are listed as the replay's own
  `topup` / `emulated` gaps).

    - the online game night (private/game10-applog.txt + the app's
      /api/player final state), and its committed alias
      (tests/fixtures/replay-4p-wgt);
    - every session played against the LOCAL server — the autopilot games
      in games/<date>-gameN and the practice games in private/games/ —
      whose log AND final state are rebuilt from the vendor server's own
      database, vendor/terraforming-mars/db/game.db, matched to the game by
      the playerIds in setup.json (never by a hard-coded game id).

  EVENT-LOG REPLAY (the advisor's own log is the truth). The physical and
  early practice games have no app log — only state/log.md, the messages
  the engine itself printed for every apply.py call. Each top-level line is
  read back into the `{"method", "args", "kwargs"}` event shape
  `apply.py batch` takes and re-applied to a fresh session from that game's
  setup.json. What matters is that TODAY's engine still ACCEPTS every event
  shape that was written then: the gate counts REFUSALS (EventError) per
  game and compares the replayed standings with the log's end note. Lines
  with no machine form (plan notes, per-generation summaries) are counted
  as `narrative` and skipped.

Private data: every real-game log lives under private/ (git-ignored). The
gate reads them from there and SKIPS cleanly when they are absent — nothing
is ever copied into the repository.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import applog_parser as P                        # noqa: E402
import replay_applog as R                        # noqa: E402
import score                                     # noqa: E402
import tmlib                                            # noqa: E402
from tmlib import Engine, EventError, RESOURCES, Store   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DB = ROOT / "vendor" / "terraforming-mars" / "db" / "game.db"
TILETYPE_TS = (ROOT / "vendor" / "terraforming-mars" / "src" / "common"
               / "TileType.ts")

# The vendor stores a tile as its TileType ENUM NUMBER (TileType.ts says so
# in a comment: "There might be a temptation to rename or reorder these …
# TileType is stored in the database as its number"). The engine's own tile
# label is the card/tile name squashed to lowercase alphanumerics, which is
# exactly the enum name lowercased without underscores — so the mapping is
# derived, never a table of card names. The vendor file wins when the
# checkout is present (tests/test_replay_gate.py pins the two against each
# other); this list is the offline fallback and covers base + Corporate Era.
TILE_ENUM_FALLBACK = (
    "GREENERY", "OCEAN", "CITY", "CAPITAL", "COMMERCIAL_DISTRICT",
    "ECOLOGICAL_ZONE", "INDUSTRIAL_CENTER", "LAVA_FLOWS", "MINING_AREA",
    "MINING_RIGHTS", "MOHOLE_AREA", "NATURAL_PRESERVE", "NUCLEAR_ZONE",
    "RESTRICTED_AREA", "DEIMOS_DOWN", "GREAT_DAM", "MAGNETIC_FIELD_GENERATORS",
)


def tile_enum_names() -> tuple[str, ...]:
    """TileType enum member names in declaration order (index = stored id)."""
    if TILETYPE_TS.exists():
        body = TILETYPE_TS.read_text()
        body = body[body.index("enum TileType"):]
        body = body[body.index("{") + 1: body.index("}")]
        body = re.sub(r"//[^\n]*", "", body)
        names = [n.strip() for n in body.split(",")]
        return tuple(n for n in names if n)
    return TILE_ENUM_FALLBACK


def tile_label(type_id: int) -> str:
    names = tile_enum_names()
    if 0 <= type_id < len(names):
        return names[type_id].lower().replace("_", "")
    return f"tiletype{type_id}"


# ── the normalised "what the app says" record ────────────────────

def _res_block(src: dict, keys: dict) -> dict:
    return {r: int(src.get(keys[r], 0) or 0) for r in RESOURCES}


VIEW_RES = {"mc": "megacredits", "steel": "steel", "titanium": "titanium",
            "plants": "plants", "energy": "energy", "heat": "heat"}
VIEW_PROD = {"mc": "megacreditProduction", "steel": "steelProduction",
             "titanium": "titaniumProduction", "plants": "plantProduction",
             "energy": "energyProduction", "heat": "heatProduction"}
DB_RES = {"mc": "megaCredits", "steel": "steel", "titanium": "titanium",
          "plants": "plants", "energy": "energy", "heat": "heat"}
DB_PROD = {"mc": "megaCreditProduction", "steel": "steelProduction",
           "titanium": "titaniumProduction", "plants": "plantProduction",
           "energy": "energyProduction", "heat": "heatProduction"}


def final_from_viewmodel(data: dict) -> dict:
    """The app's /api/player response (private/game10-api-final.json) →
    the gate's normalised final-state record."""
    g = data["game"]
    players = {}
    for p in data["players"]:
        vpb = p.get("victoryPointsBreakdown") or {}
        tableau = [c["name"] if isinstance(c, dict) else c
                   for c in (p.get("tableau") or [])]
        players[p["name"]] = {
            "corp": tableau[0] if tableau else None,
            "tr": p["terraformRating"],
            "resources": _res_block(p, VIEW_RES),
            "production": _res_block(p, VIEW_PROD),
            "tableau": tableau[1:],
            "vp": {k: vpb.get(k, 0) for k in
                   ("terraformRating", "milestones", "awards", "greenery",
                    "city", "victoryPoints", "total")},
            "citiesCount": p.get("citiesCount"),
        }
    tiles = []
    for sp in g["spaces"]:
        if sp.get("tileType") is None:
            continue
        tiles.append([sp["id"], int(sp["tileType"]), sp.get("color")])
    by_color = {p["color"]: p["name"] for p in data["players"]}
    tiles = [[sid, t, by_color.get(c)] for sid, t, c in tiles]
    return {"globals": {"temperature": g["temperature"], "oxygen": g["oxygenLevel"],
                        "oceans": g["oceans"], "generation": g["generation"]},
            "players": players, "tiles": tiles,
            "colors": {p["name"]: p["color"] for p in data["players"]},
            "milestones": {m["name"]: m["playerName"]
                           for m in (g.get("milestones") or []) if m.get("playerName")},
            "awards": {a["name"]: a["playerName"]
                       for a in (g.get("awards") or []) if a.get("playerName")},
            "source": "app /api/player final state"}


def final_from_committed(data: dict) -> dict:
    """tests/fixtures/*/final-state.json — already normalised, with the
    app's victoryPointsBreakdown under each player's "vp"."""
    out = json.loads(json.dumps(data))
    out.setdefault("source", "committed fixture final state")
    for p in out["players"].values():
        tab = p.get("tableau") or []
        if tab and tab[0] == p.get("corp"):
            p["tableau"] = tab[1:]          # [0] is the corporation
    return out


def conform_names(applog: str, setup: dict, final: dict) -> tuple[str, dict]:
    """Rename the app's players to the names setup.json uses, matched by
    COLOUR. The game-night session was tracked under table aliases while the
    app (and its log export) carries the real names — this keeps every
    replay, and every line the gate prints, on the alias side. A no-op when
    the names already agree.
    """
    by_color = final.get("colors") or {}
    if not by_color:
        return applog, final
    want = {p["color"]: p["name"] for p in setup["players"]}
    rename = {app_name: want[color] for app_name, color in by_color.items()
              if color in want and want[color] != app_name}
    if not rename:
        return applog, final
    for old, new in rename.items():
        applog = re.sub(rf"\b{re.escape(old)}\b", new, applog)
    final = json.loads(json.dumps(final))
    final["players"] = {rename.get(k, k): v for k, v in final["players"].items()}
    final["colors"] = {rename.get(k, k): v for k, v in final["colors"].items()}
    final["tiles"] = [[s, t, rename.get(o, o)] for s, t, o in final["tiles"]]
    for key in ("milestones", "awards"):
        if final.get(key):
            final[key] = {k: rename.get(v, v) for k, v in final[key].items()}
    return applog, final


def _db_game(conn: sqlite3.Connection, game_id: str) -> dict:
    save = conn.execute("select max(save_id) from games where game_id = ?",
                        (game_id,)).fetchone()[0]
    row = conn.execute("select game from games where game_id = ? and save_id = ?",
                       (game_id, save)).fetchone()
    return json.loads(row[0])


def db_game_id_for(conn: sqlite3.Connection, player_ids: set[str]) -> str | None:
    """The vendor game whose participants contain exactly these playerIds
    (setup.json carries them) — so the gate never hard-codes a game id."""
    best = None
    for (gid,) in conn.execute("select distinct game_id from participants"):
        have = {p for (p,) in conn.execute(
            "select participant from participants where game_id = ?", (gid,))}
        if player_ids and player_ids <= have:
            row = conn.execute(
                "select max(save_id) from games where game_id = ?", (gid,)).fetchone()
            if row and row[0] is not None and (best is None or row[0] > best[1]):
                best = (gid, row[0])
    return best[0] if best else None


def render_db_log(game: dict) -> str:
    """The saved game's own gameLog → the text the app's log export prints.

    A log entry is a template ("${0} played ${1}") plus typed data; only
    LogMessageDataType.PLAYER (2) needs translating (it stores the colour)
    and CARDS (14) is a list. Everything else prints its value.
    """
    names = {p["color"]: p["name"] for p in game["players"]}

    def render(entry: dict) -> str:
        def sub(m):
            d = entry["data"][int(m.group(1))]
            v = d["value"]
            if d["type"] == 2:
                return names.get(v, v)
            if isinstance(v, list):
                return ",".join(v)
            return str(v)
        return re.sub(r"\$\{(\d+)\}", sub, entry["message"])

    return "\n".join(render(e) for e in game.get("gameLog", []))


def final_from_db(game: dict) -> dict:
    """A vendor-saved finished game → the gate's normalised final state."""
    ids = {p["id"]: p["name"] for p in game["players"]}
    players = {}
    for p in game["players"]:
        tableau = [c["name"] for c in (p.get("playedCards") or [])]
        corp = p.get("pickedCorporationCard")
        players[p["name"]] = {
            "corp": corp,
            "tr": p["terraformRating"],
            "resources": _res_block(p, DB_RES),
            "production": _res_block(p, DB_PROD),
            "tableau": [c for c in tableau if c != corp],
            "vp": None,
            "citiesCount": None,
        }
    tiles = []
    for sp in game["board"]["spaces"]:
        t = sp.get("tile")
        if not t:
            continue
        tiles.append([sp["id"], int(t["tileType"]), ids.get(sp.get("player"))])
    return {"globals": {"temperature": game["temperature"],
                        "oxygen": game["oxygenLevel"],
                        "oceans": sum(1 for _, t, _ in tiles
                                      if tile_label(t) == "ocean"),
                        "generation": game["generation"]},
            "players": players, "tiles": tiles,
            "colors": {p["name"]: p["color"] for p in game["players"]},
            "milestones": {m["name"]: ids.get(m["playerId"])
                           for m in game.get("claimedMilestones") or []},
            "awards": {a["name"]: ids.get(a["playerId"])
                       for a in game.get("fundedAwards") or []},
            "source": f"vendor db game {game['id']} save {game['lastSaveId']}"}


# ── result rows ──────────────────────────────────────────────────

@dataclass
class GameResult:
    name: str
    kind: str                       # "app" | "events"
    players: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    problems: list = field(default_factory=list)     # board / TR / globals — GATE
    refusals: list = field(default_factory=list)     # EventError, event replay
    notes: list = field(default_factory=list)
    skipped: str | None = None
    state: dict | None = None       # the replayed game.json (score smoke test)
    final: dict | None = None       # the app's own final table

    @property
    def ok(self) -> bool:
        return self.skipped is not None or not self.problems


# ── app-log replay ───────────────────────────────────────────────

# gap kinds that EXPLAIN an MC delta: the export prints no card cost, so the
# replay tops a stock up when the app accepted a payment the tracker could
# not afford, and emulates the costs of blue-card actions it has no data for
MC_GAP_KINDS = ("topup", "emulated", "unmodelled-action", "requirement",
                "unknown-card", "or-choice")


def replay_app_game(name: str, applog_text: str, setup: dict,
                    final: dict) -> GameResult:
    res = GameResult(name=name, kind="app")
    applog_text, final = conform_names(applog_text, setup, final)
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        store.init(json.loads(json.dumps(setup)))
        eng = Engine(store)
        rep = R.Report()
        players = [p["name"] for p in setup["players"]]
        events = P.parse_log(applog_text, players)
        rep.lines_seen = len(applog_text.splitlines())
        R.Replayer(eng, rep, verbose=False).run(P.group_blocks(events))
        game = rep.game
        scored = {r["name"]: r for r in score.compute(game, "full")["players"]}
    res.state, res.final = game, final

    res.players = players
    res.notes.append(f"{rep.lines_seen} log lines, {len(rep.gaps)} gaps, "
                     f"{len(rep.unknown_lines)} unrecognised")
    for kind in ("unknown", "refused"):
        bad = [g for g in rep.gaps if g["kind"] == kind]
        for g in bad:
            res.notes.append(f"{kind} L{g['line']} {g['label']}: {g['what']}")

    # globals
    for k in ("temperature", "oxygen", "oceans"):
        if game["globals"][k] != final["globals"][k]:
            res.problems.append(
                f"global {k}: engine {game['globals'][k]} app {final['globals'][k]}")

    # tiles — position AND type AND owner, all of them
    exp_tiles, off_map = {}, {}
    for sid, tid, owner in final["tiles"]:
        label = tile_label(tid)
        # an off-Mars city (Ganymede Colony / Phobos Space Haven) has no hex
        # in board.json: the engine holds it as the card in the tableau plus
        # the owner's citiesOffMars counter
        space = Engine._board().get(sid) or {}
        target = off_map if space.get("offMap") or not space else exp_tiles
        target[sid] = (label, None if label == "ocean" else owner)
    # a land claim is a reservation marker, never a tile: the app's final
    # board has nothing on a hex that was claimed and never built on
    got = {sid: (t["tile"], None if t["tile"] == "ocean" else t["player"])
           for sid, t in (game.get("board") or {}).items()
           if t["tile"] != tmlib.LAND_CLAIM}
    missing = sorted(set(exp_tiles) - set(got))
    extra = sorted(set(got) - set(exp_tiles))
    wrong = sorted(sid for sid in set(got) & set(exp_tiles)
                   if got[sid] != exp_tiles[sid])
    tiles_ok = not (missing or extra or wrong)
    if not tiles_ok:
        for sid in missing:
            res.problems.append(f"tile {sid} {exp_tiles[sid]} missing from the board")
        for sid in extra:
            res.problems.append(f"tile {sid} {got[sid]} on the board, not in the app")
        for sid in wrong:
            res.problems.append(
                f"tile {sid}: engine {got[sid]} app {exp_tiles[sid]}")
    if off_map:
        res.notes.append("off-map tiles (no hex in board.json): "
                         + ", ".join(f"{s}={v[0]}/{v[1]}" for s, v in off_map.items()))

    # milestones / awards
    for what, key in (("milestones", "milestonesClaimed"), ("awards", "awardsFunded")):
        exp = final.get(what)
        if exp is None:
            continue
        gotm = game.get(key) or {}
        if gotm != exp:
            res.problems.append(f"{what}: engine {gotm} app {exp}")

    for p in players:
        ep = final["players"][p]
        pool = game["me"] if game["me"]["name"] == p else game["opponents"][p]
        tr_ok = pool["tr"] == ep["tr"]
        if not tr_ok:
            res.problems.append(f"{p} TR: engine {pool['tr']} app {ep['tr']}")
        board = game.get("board") or {}
        owned = [v["tile"] for v in board.values() if v["player"] == p]
        greens = sum(1 for t in owned if t == "greenery")
        cities = sum(1 for t in owned if t == "city")
        exp_green = sum(1 for sid, tid, o in final["tiles"]
                        if o == p and tile_label(tid) == "greenery")
        exp_city = sum(1 for sid, tid, o in final["tiles"]
                       if o == p and tile_label(tid) == "city")
        tile_ok = (greens == exp_green
                   and cities + pool["tiles"].get("citiesOffMars", 0) == exp_city
                   and pool["tiles"]["greeneries"] == exp_green)
        if not tile_ok:
            res.problems.append(
                f"{p} tiles: engine {greens}G/{cities}C "
                f"(+{pool['tiles'].get('citiesOffMars', 0)} off-Mars, counter "
                f"{pool['tiles']['greeneries']}G/{pool['tiles']['cities']}C) "
                f"app {exp_green}G/{exp_city}C")
        tab_ok = sorted(c["name"] for c in pool["playedCards"]) == sorted(ep["tableau"])
        if not tab_ok:
            got_t = {c["name"] for c in pool["playedCards"]}
            res.notes.append(f"{p} tableau differs: missing "
                             f"{sorted(set(ep['tableau']) - got_t)} extra "
                             f"{sorted(got_t - set(ep['tableau']))}")
        sc = scored[p]
        vp = ep.get("vp")
        if vp:
            vp_card_delta = sc["cardVP"] - vp["victoryPoints"]
            vp_total_delta = sc["total"] - vp["total"]
            vp_txt = (f"cards {sc['cardVP']}/{vp['victoryPoints']} "
                      f"total {sc['total']}/{vp['total']}")
        else:
            vp_card_delta, vp_total_delta, vp_txt = None, None, f"total {sc['total']}/?"
        mc_delta = pool["resources"]["mc"] - ep["resources"]["mc"]
        drift = []
        for kind, key in (("res", "resources"), ("prod", "production")):
            for r in RESOURCES:
                a, b = pool[key][r], ep[key][r]
                if a != b and not (kind == "res" and r == "mc"):
                    drift.append(f"{r} {kind} {a}/{b}")
        if drift:
            res.notes.append(f"{p} stock/production drift (engine/app): "
                             + ", ".join(drift))
        res.rows.append({
            "player": p, "tr": pool["tr"], "tr_app": ep["tr"], "tr_ok": tr_ok,
            "tiles_ok": tile_ok and tiles_ok, "tableau_ok": tab_ok,
            "vp": vp_txt, "vp_card_delta": vp_card_delta,
            "vp_total_delta": vp_total_delta,
            "mc": pool["resources"]["mc"], "mc_app": ep["resources"]["mc"],
            "mc_delta": mc_delta,
            "topups": dict(rep.topups.get(p, {})),
        })
    kinds = {}
    for g in rep.gaps:
        kinds[g["kind"]] = kinds.get(g["kind"], 0) + 1
    res.notes.append("gaps by kind: "
                     + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    res.notes.append("MC deltas are explained by these gap kinds: "
                     + ", ".join(k for k in MC_GAP_KINDS if k in kinds))
    return res


# ── event-log (log.md) replay ────────────────────────────────────

RES_WORDS = {r.upper(): r for r in RESOURCES}
RES_WORDS["MC"] = "mc"
_STD = ("power_plant", "asteroid", "aquifer", "greenery", "city",
        "sell_patents")


def _cards_list(text: str) -> list[str]:
    try:
        v = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else []


def logmd_events(line: str, players: list[str]) -> list[dict] | None:
    """One top-level log.md message → the `apply.py batch` events that
    produced it, or None when the line has no machine form (narrative).

    The messages are the engine's own return strings (Engine._commit), so
    this is their inverse. Only the shapes that CHANGE state are inverted;
    plan bookkeeping, generation summaries and free-text notes are
    narrative by construction.
    """
    p = "(?P<p>" + "|".join(re.escape(n) for n in
                            sorted(players, key=len, reverse=True)) + ")"
    m = re.match(rf"^{p}: (?P<d>[+-]?\d+) (?P<r>[A-Z€]+) production → -?\d+$", line)
    if m and m["r"] in RES_WORDS:
        return [{"method": "prod", "args": [m["p"], RES_WORDS[m["r"]], int(m["d"])]}]
    m = re.match(rf"^{p}: (?P<d>[+-]?\d+) (?P<r>[A-Z€]+) → -?\d+$", line)
    if m and m["r"] in RES_WORDS:
        return [{"method": "res", "args": [m["p"], RES_WORDS[m["r"]], int(m["d"])]}]
    m = re.match(rf"^{p}: TR (?P<d>[+-]?\d+) → -?\d+$", line)
    if m:
        return [{"method": "tr", "args": [m["p"], int(m["d"])]}]
    m = re.match(rf"^{p} is (?P<c>.+?) \(start (?P<mc>\d+) MC → \d+\)", line)
    if m:
        return [{"method": "corp", "args": [m["p"], m["c"]],
                 "kwargs": {"mc": int(m["mc"])}}]
    m = re.match(rf"^{p} played (?P<c>.+?) \(paid .*", line)
    if m:
        return [{"method": "play", "args": [m["p"], m["c"]]}]
    m = re.match(rf"^{p} played (?P<c>.+?) \(~?[−-]\d+ MC → ~?-?\d+\)$", line)
    if m:
        return [{"method": "play", "args": [m["p"], m["c"]]}]
    m = re.match(rf"^{p} placed (?P<t>\w+) on (?P<hex>\w+)", line)
    if m:
        return [{"method": "place", "args": [m["p"], m["t"], m["hex"]]}]
    m = re.match(rf"^{p}: spent \d+ plants → greenery", line)
    if m:
        return [{"method": "convert", "args": [m["p"], "plants"]}]
    m = re.match(rf"^{p}: spent \d+ heat, temperature", line)
    if m:
        return [{"method": "convert", "args": [m["p"], "heat"]}]
    m = re.match(r"^Research: dealt (?P<d>\[.*?\]), kept (?P<k>\[.*?\])", line)
    if m:
        return [{"method": "dealt", "args": [_cards_list(m["d"])],
                 "kwargs": {"kept": _cards_list(m["k"])}}]
    m = re.match(rf"^{p}: research kept (?P<n>\d+) cards", line)
    if m:
        return [{"method": "research", "args": [m["p"]],
                 "kwargs": {"kept": int(m["n"])}}]
    m = re.match(rf"^{p}: standard project (?P<s>\w+),", line)
    if m and m["s"] in _STD:
        return [{"method": "standard", "args": [m["p"], m["s"]]}]
    m = re.match(r"^Sync: (?P<param>\w+) = (?P<v>-?\d+)", line)
    if m:
        return [{"method": "sync_global", "args": [m["param"], int(m["v"])]}]
    m = re.match(rf"^{p}: (?P<param>temperature|oxygen|oceans) .*TR → -?\d+$", line)
    if m:
        return [{"method": "raise_param", "args": [m["param"]],
                 "kwargs": {"by": m["p"]}}]
    m = re.match(rf"^{p} funded award (?P<a>.+?) \(", line)
    if m:
        return [{"method": "award", "args": [m["p"], m["a"]]}]
    m = re.match(rf"^{p} claimed milestone (?P<a>.+?) \(", line)
    if m:
        return [{"method": "milestone", "args": [m["p"], m["a"]]}]
    m = re.match(r"^Action used: (?P<c>.+?) ✓", line)
    if m:
        return [{"method": "use_action", "args": [m["c"]]}]
    m = re.match(rf"^{p} used action (?P<c>.+?)(?::|$)", line)
    if m:
        return [{"method": "use_action", "args": [m["c"]],
                 "kwargs": {"player": m["p"]}}]
    m = re.match(r"^Hand \+(?P<c>\[.*?\])", line)
    if m:
        return [{"method": "hand_add", "args": [_cards_list(m["c"])]}]
    m = re.match(r"^WGT \([^)]*\), (?P<what>.+)$", line)
    if m:
        what = m["what"]
        if what.startswith("temperature"):
            return [{"method": "wgt", "args": ["temperature"]}]
        if what.startswith("oxygen"):
            return [{"method": "wgt", "args": ["oxygen"]}]
        mo = re.match(r"^ocean placed on (?P<hex>\w+)", what)
        if mo:
            return [{"method": "wgt", "args": ["oceans"],
                     "kwargs": {"space_id": mo["hex"]}}]
        return None
    m = re.match(r"^Production \(end of gen \d+\)", line)
    if m:
        return [{"method": "produce", "args": []}]
    return None


LOG_LINE = re.compile(r"^- G(?P<gen>\d+) — (?P<msg>.*)$")
# produce() prints this line itself when it was told to skip the World
# Government step, one line BEFORE the production summary — so it is not an
# event of its own, it is an argument of the produce that follows.
SKIP_WGT = re.compile(r"^WGT step skipped: (?P<why>.+)$")

# Why a re-fed event was refused. Only "shape" is an engine regression: the
# verb, the resource, the project or the card no longer exists, so an event
# the advisor once wrote can never be applied again. The other two are
# properties of the LOG, not of the engine — a log.md message is a human
# sentence, and the interactive argument the original apply.py call carried
# (--card, --target, --choice, --copy, --cost) is simply not in it, so the
# replay's state then drifts and every later affordability, adjacency,
# ledger or eligibility check fails behind it.
REFUSAL_ARG = ("needs a victim", "needs its victim", "--choice", "--copy",
               "pass card=", "give its cost explicitly", "or-choice card",
               "name the card", "register it first")
REFUSAL_SHAPE = ("unknown engine method", "Unknown resource",
                 "Unknown player reference", "Unknown standard project",
                 "Unknown conversion", "Unknown global parameter",
                 "not in cards/db.json", "Unknown milestone", "Unknown award")


def refusal_class(msg: str) -> str:
    if any(k in msg for k in REFUSAL_ARG):
        return "arg-not-in-log"
    if any(k in msg for k in REFUSAL_SHAPE):
        return "shape"
    return "state-drift"


def replay_event_log(name: str, setup: dict, logmd: str) -> GameResult:
    res = GameResult(name=name, kind="events")
    players = [p["name"] for p in setup["players"]]
    res.players = players
    applied = narrative = refused = 0
    pending_skip_wgt: str | None = None
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp))
        store.init(json.loads(json.dumps(setup)))
        eng = Engine(store)
        for n, raw in enumerate(logmd.splitlines(), 1):
            m = LOG_LINE.match(raw.rstrip())
            if not m:
                continue
            skip = SKIP_WGT.match(m["msg"])
            if skip:
                pending_skip_wgt = skip["why"]
                narrative += 1
                continue
            evs = logmd_events(m["msg"], players)
            if evs is None:
                narrative += 1
                continue
            for ev in evs:
                if ev["method"] == "produce" and pending_skip_wgt:
                    ev = dict(ev, kwargs={**ev.get("kwargs", {}),
                                          "skip_wgt": pending_skip_wgt})
                    pending_skip_wgt = None
                fn = getattr(eng, ev["method"])
                try:
                    fn(*ev.get("args", []), **ev.get("kwargs", {}))
                    applied += 1
                except EventError as e:
                    refused += 1
                    res.refusals.append(
                        (refusal_class(str(e)),
                         f"L{n} {ev['method']}{ev.get('args', [])}: {e}"))
                except Exception as e:                 # noqa: BLE001
                    refused += 1
                    res.refusals.append(
                        ("shape", f"L{n} {ev['method']}{ev.get('args', [])}: "
                                  f"{type(e).__name__}: {e}"))
        game = store.load_game()
        rows = score.compute(game, "full")["players"]
    buckets: dict[str, int] = {}
    for cls, _ in res.refusals:
        buckets[cls] = buckets.get(cls, 0) + 1
    res.notes.append(f"{applied} events applied, {narrative} narrative lines "
                     f"skipped, {refused} refusals "
                     + (f"({', '.join(f'{k} {v}' for k, v in sorted(buckets.items()))})"
                        if buckets else ""))
    for cls, msg in res.refusals:
        if cls == "shape":
            res.problems.append(f"engine no longer accepts this event: {msg}")
    res.notes.append("replayed standings: "
                     + " · ".join(f"{r['name']} {r['total']}" for r in rows))
    note = end_note(logmd)
    if note:
        res.notes.append(f"log end note: {note}")
    for r in rows:
        pool = game["me"] if game["me"]["name"] == r["name"] else \
            game["opponents"][r["name"]]
        res.rows.append({"player": r["name"], "tr": pool["tr"], "tr_app": None,
                         "tr_ok": None, "tiles_ok": None, "tableau_ok": None,
                         "vp": f"total {r['total']}", "vp_card_delta": None,
                         "vp_total_delta": None, "mc": pool["resources"]["mc"],
                         "mc_app": None, "mc_delta": None, "topups": {}})
    return res


def end_note(logmd: str) -> str | None:
    for line in reversed(logmd.splitlines()):
        s = line.strip()
        if s.startswith("- Game ended"):
            return s[2:].split(" — ", 1)[-1][:160]
    return None


# ── target discovery ─────────────────────────────────────────────

def app_targets(paths: dict) -> list:
    """[(name, loader)] — loader() returns (applog_text, setup, final) or
    raises FileNotFoundError so the caller can SKIP."""
    out = []

    fixture = ROOT / "tests" / "fixtures" / "replay-4p-wgt"
    out.append(("fixture:replay-4p-wgt", lambda d=fixture: (
        (d / "applog.txt").read_text(),
        json.loads((d / "setup.json").read_text()),
        final_from_committed(json.loads((d / "final-state.json").read_text())))))

    log10 = ROOT / "private" / "game10-applog.txt"
    fin10 = ROOT / "private" / "game10-api-final.json"
    set10 = ROOT / "private" / "games" / "2026-08-27-game1" / "setup.json"
    out.append(("private:game10-online", lambda: (
        log10.read_text(),
        json.loads(set10.read_text()),
        final_from_viewmodel(json.loads(fin10.read_text())))))

    # Every session played against the LOCAL server — the autopilot games in
    # games/ and the practice games in private/games/ — can be replayed the
    # same way: the vendor's own database still holds the finished game, so
    # both the log and the final state come from the app itself.
    for base in (ROOT / "games", ROOT / "private" / "games"):
        for d in sorted(base.glob("*")):
            if not (d / "setup.json").exists():
                continue
            label = (f"games/{d.name}" if base == ROOT / "games"
                     else f"private:{d.name}")
            out.append((label, lambda d=d: db_target(d)))
    return out


def db_target(game_dir: Path):
    setup = json.loads((game_dir / "setup.json").read_text())
    pids = {p["playerId"] for p in setup["players"] if p.get("playerId")}
    if not pids or not VENDOR_DB.exists():
        raise FileNotFoundError(f"{game_dir.name}: no playerIds or no vendor db")
    conn = sqlite3.connect(f"file:{VENDOR_DB}?mode=ro", uri=True)
    try:
        gid = db_game_id_for(conn, pids)
        if gid is None:
            raise FileNotFoundError(f"{game_dir.name}: no vendor game for {pids}")
        game = _db_game(conn, gid)
    finally:
        conn.close()
    if game.get("phase") != "end":
        raise FileNotFoundError(f"{game_dir.name}: vendor game {gid} is not finished")
    return render_db_log(game), setup, final_from_db(game)


def event_targets() -> list:
    out = []
    base = ROOT / "private" / "games"
    for d in sorted(base.glob("*")):
        out.append((f"private/{d.name}", d))
    return out


# ── rendering ────────────────────────────────────────────────────

def render(results: list[GameResult]) -> str:
    out = []
    head = (f"{'game':28} {'player':9} {'TR':>9} {'tiles':>6} {'VP (mine/app)':>22} "
            f"{'MC Δ':>8} {'refusals':>8}")
    out.append(head)
    out.append("-" * len(head))
    for r in results:
        if r.skipped:
            out.append(f"{r.name:28} SKIPPED — {r.skipped}")
            continue
        first = True
        for row in r.rows:
            tr = (f"{row['tr']}/{row['tr_app']}" if row["tr_app"] is not None
                  else str(row["tr"]))
            mark = "" if row["tr_ok"] in (True, None) else " ✗"
            tiles = {True: "ok", False: "✗", None: "—"}[row["tiles_ok"]]
            mc = ("—" if row["mc_delta"] is None
                  else f"{row['mc_delta']:+d}")
            ref = "" if r.kind == "app" else str(len(r.refusals))
            out.append(f"{(r.name if first else ''):28} {row['player']:9} "
                       f"{tr + mark:>9} {tiles:>6} {row['vp']:>22} {mc:>8} "
                       f"{ref:>8}")
            first = False
        for n in r.notes:
            out.append(f"{'':28} · {n}")
        for cls, msg in r.refusals:
            out.append(f"{'':28} ⟲ [{cls}] {msg}")
        for pr in r.problems:
            out.append(f"{'':28} ✗ {pr}")
    return "\n".join(out)


def run_all(only: str | None = None) -> tuple[list[GameResult], int]:
    results = []
    for name, loader in app_targets({}):
        if only and only not in name:
            continue
        try:
            applog, setup, final = loader()
        except (FileNotFoundError, OSError) as e:
            results.append(GameResult(name=name, kind="app", skipped=str(e)))
            continue
        results.append(replay_app_game(name, applog, setup, final))
    for name, d in event_targets():
        if only and only not in name:
            continue
        try:
            setup = json.loads((d / "setup.json").read_text())
            logmd = (d / "log.md").read_text()
        except (FileNotFoundError, OSError) as e:
            results.append(GameResult(name=name, kind="events", skipped=str(e)))
            continue
        results.append(replay_event_log(name, setup, logmd))
    bad = sum(1 for r in results if not r.ok)
    return results, bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="every discoverable game")
    ap.add_argument("--game", help="a game directory (games/… or private/games/…)")
    ap.add_argument("--app-log", help="an app log export to replay")
    ap.add_argument("--final", help="the app's final state for --app-log")
    ap.add_argument("--setup", help="setup.json for --app-log")
    a = ap.parse_args(argv)

    if a.app_log:
        if not (a.final and a.setup):
            print("--app-log needs --final and --setup", file=sys.stderr)
            return 2
        raw = json.loads(Path(a.final).read_text())
        final = (final_from_viewmodel(raw) if "players" in raw and
                 isinstance(raw.get("players"), list) else final_from_committed(raw))
        results = [replay_app_game(Path(a.app_log).name,
                                   Path(a.app_log).read_text(),
                                   json.loads(Path(a.setup).read_text()), final)]
        bad = sum(1 for r in results if not r.ok)
    elif a.game:
        d = Path(a.game)
        name = f"{d.parent.name}/{d.name}"
        results = []
        try:
            applog, setup, final = db_target(d)
            results.append(replay_app_game(name, applog, setup, final))
        except (FileNotFoundError, OSError, KeyError) as e:
            results.append(GameResult(name=name, kind="app", skipped=str(e)))
        if (d / "log.md").exists() and (d / "setup.json").exists():
            results.append(replay_event_log(
                name, json.loads((d / "setup.json").read_text()),
                (d / "log.md").read_text()))
        bad = sum(1 for r in results if not r.ok)
    else:
        results, bad = run_all()

    print(render(results))
    print()
    ran = [r for r in results if not r.skipped]
    print(f"{len(ran)} game(s) replayed, {len(results) - len(ran)} skipped "
          f"(files absent), {bad} FAILING (board / TR / globals / milestones "
          f"/ awards, or an event shape the engine no longer accepts)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
