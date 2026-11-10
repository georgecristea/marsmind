#!/usr/bin/env python3
"""Scoring: full end-game and "abort mode" (rank everyone right now).

Full: TR + card VP (numeric from db.json; formula VP from tracked counts,
tags, cities and board adjacency) + tile VP (greeneries 1 each; 1 per
greenery adjacent to any of the player's cities, opponents included) +
milestones (5 VP) + awards (5/2 VP by metric).
Abort: TR + card VP + tile VP only (skip unclaimed milestones/awards — the
claimed/funded ones still count for nothing in abort per house definition);
what those WOULD be worth is printed under the ranking, so the omission is
visible instead of silently inverting the standing.

BOUND RULE (the reference failure: "2 cards with formula VP not countable"
was relayed as a 5-point lead that was really a 5-point deficit — the
winner's Capital +3 and Commercial District +1 were invisible). Every
component that cannot be computed exactly produces an explicit bound on
that player's TOTAL instead of a silent zero:
- min (the row's `total`) = the known floor — an unknown component
  contributes nothing to it;
- max (`vpMax`) = floor + a cap derived from db.json + the tracked board,
  per unknown component:
  * adjacency-formula tile (Capital: 1 VP/adjacent ocean; Commercial
    District: 1 VP/adjacent city — ADJACENCY_VP, keyed on the db's
    behavior.tile.type) whose hex is NOT on the tracked board:
    cap = min(6, qualifying tiles on the board) — a hex has 6 neighbours
    and only tiles already on the board can be adjacent;
  * a city tile without a recorded position: cap = 6 per such city,
    tightened to min(6, greeneries on the board) each;
  * a per-resource formula whose count was never observed: NO sane cap
    exists (the db puts no ceiling on accumulators), so `vpMax` is None
    ("unbounded") — the card keeps its manual flag and is excluded from
    the floor; the same applies to a VP prose the db cannot express and
    to a card missing from the db entirely.
`vpMax` == `total` means the total is exact. Whenever a bound exists the
standings line carries the bound (e.g. "Anna 61–64", "Diana ≥38"), never
the bare floor. Rows are ranked by the floor.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards as cardlib
from planlib import APP_MODES, _fetch_app
import tmlib
from tmlib import AWARDS  # noqa: F401  (validated at funding time)

MILESTONE_VP = 5
AWARD_VP = (5, 2)  # 1st, 2nd (2nd not awarded in 2p)
VP_COLS = ("terraformRating", "milestones", "awards", "greenery", "city",
           "victoryPoints", "total")
VP_HEAD = ("TR", "miles", "awards", "green", "city", "cards", "total")


def app_final_table(data: dict) -> list[dict] | None:
    """The app's own victoryPointsBreakdown per player, sorted by
    total — exact, zero manual items. None unless game.phase == 'end'."""
    if (data.get("game") or {}).get("phase") != "end":
        return None
    rows = [{"name": p["name"],
             **{k: p.get("victoryPointsBreakdown", {}).get(k, 0) for k in VP_COLS}}
            for p in data.get("players", [])]
    return sorted(rows, key=lambda r: -r["total"])


def _print_app_table(setup: dict) -> None:
    pid = next((p.get("playerId") for p in setup.get("players", [])
                if p.get("isMe")), None)
    try:
        data = _fetch_app(str(setup.get("appUrl", "")).rstrip("/"), pid)
    except Exception as e:                       # app down: estimate only
        print(f"⚠ app unreachable ({e}) — tracker estimate only")
        return
    rows = app_final_table(data)
    if rows is None:
        print(f"app phase is {(data.get('game') or {}).get('phase')!r}, "
              "not 'end' — tracker estimate only")
        return
    print("=== FINAL (app victoryPointsBreakdown — authoritative) ===")
    print(f"{'':3}{'player':10}" + "".join(f"{h:>7}" for h in VP_HEAD))
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['name']:10}" + "".join(f"{r[c]:>7}" for c in VP_COLS))
    print("\nTracker estimate (cross-check):")


# City tiles that score adjacency: the plain city plus the card tiles that
# ARE cities on the map (base/CE). Capital is the one that bit us — an
# opponent's Capital scored 0 adjacency in the tracker's estimate (P8 #20).
CITY_TILES = ("city", "capital")


def _is_city(tile: str) -> bool:
    return tile in CITY_TILES


def city_adjacency_vp(game: dict, player: str) -> int:
    """1 VP per greenery tile adjacent to each of the player's cities
    (official rule: any greenery counts, regardless of owner).

    Counted for EVERY player, not just me: the threat block ranks
    opponents on these numbers, and an uncounted opponent city reads as a
    player who is behind.
    """
    board = game.get("board", {})
    from tmlib import Engine
    spaces = Engine._board()
    vp = 0
    for sid, occ in board.items():
        if _is_city(occ["tile"]) and occ["player"] == player:
            vp += sum(1 for a in spaces[sid].get("adjacent", [])
                      if board.get(a, {}).get("tile") == "greenery")
    return vp


# Formula VP comes from the db's structured `vpData` (the vendor's own
# victoryPoints object), never from parsing the prose:
#   {"resourcesHere": {}}              1 VP per resource on the card
#   {"resourcesHere": {}, "each": 2}   2 VP per resource
#   {"resourcesHere": {}, "per": 2}    1 VP per 2 resources
#   {"tag": "jovian"}                  1 VP per own persisting tag
#   {"cities": {}, "all": true, "per": 3}  1 VP per 3 cities in play
# vpData null with prose VP = a BOARD formula. The two adjacency tiles are
# rules facts keyed on the db's behavior.tile.type (never a card-name
# branch): the tile scores 1 VP per adjacent tile of the target kind. A
# card whose tile is not on the tracked board is BOUNDED, never guessed —
# an unreconciled tile must not silently invent VP.
ADJACENCY_VP = {"capital": "ocean", "commercialdistrict": "city"}


def _adjacency_target(occ_tile: str, target: str) -> bool:
    return _is_city(occ_tile) if target == "city" else occ_tile == target


def adjacency_vp(info: dict, game: dict, player: str):
    """Board-adjacency formula for one played card.

    Returns None when the card is not an adjacency-formula card;
    otherwise (exact, cap, note): exact is the VP when the player's tile
    is on the tracked board (cap/note None), else exact is None and cap
    is the honest maximum — min(6, target tiles on the board) — with a
    note naming the gap."""
    tile_type = ((info.get("behavior") or {}).get("tile") or {}).get("type")
    target = ADJACENCY_VP.get(tile_type or "")
    if target is None:
        return None
    board = game.get("board", {})
    from tmlib import Engine
    spaces = Engine._board()
    hexes = [sid for sid, occ in board.items()
             if occ.get("tile") == tile_type and occ.get("player") == player]
    if hexes:
        vp = sum(1 for sid in hexes for a in spaces[sid].get("adjacent", [])
                 if _adjacency_target(board.get(a, {}).get("tile", ""), target))
        return vp, None, None
    targets = sum(1 for occ in board.values()
                  if _adjacency_target(occ.get("tile", ""), target))
    cap = min(6, targets)
    note = (f"{info['name']}: {info.get('vp')} — tile hex not on the "
            f"tracked board, ≤{cap} ({targets} {target} tile(s) on the "
            "board; apply.py place records it)")
    return None, cap, note


def formula_vp(vp_data, count: int | None) -> int | None:
    """VP of a `resourcesHere` formula at `count` resources on the card, or
    None when it cannot be scored (unknown count, not a resource formula).

    The engine tracks resources on cards it has seen played
    (pool["cardResources"]), so my own accumulators — and any opponent
    card whose count was observed — score exactly instead of landing in
    the "count it on the card" pile.
    """
    if count is None or not isinstance(vp_data, dict):
        return None
    if "resourcesHere" not in vp_data:
        return None
    per = vp_data.get("per", 1)
    each = vp_data.get("each", 1)
    if not isinstance(per, int) or not isinstance(each, int) or per < 1:
        return None
    return count // per * each


def tag_vp(vp_data, tags: dict) -> int | None:
    """VP of a per-tag formula ({"tag": "jovian"}) at this player's
    persisting tag counts."""
    if not isinstance(vp_data, dict) or "tag" not in vp_data:
        return None
    per = vp_data.get("per", 1)
    each = vp_data.get("each", 1)
    if not isinstance(per, int) or not isinstance(each, int) or per < 1:
        return None
    return tags.get(vp_data["tag"], 0) // per * each


def cities_vp(vp_data, game: dict) -> int | None:
    """VP of a per-city formula ({"cities": {}, "all": true, "per": 3}) —
    counted from the board, the record of what is physically on the map."""
    if not isinstance(vp_data, dict) or "cities" not in vp_data:
        return None
    per = vp_data.get("per", 1)
    each = vp_data.get("each", 1)
    if not isinstance(per, int) or not isinstance(each, int) or per < 1:
        return None
    # THE tile counter: cities IN PLAY, reserved-area ones included
    return tmlib.cities_in_play(game) // per * each


def bound_str(row: dict) -> str | None:
    """The bound on this row's total, or None when the total is exact.
    '≥N' when an unknown component has no sane cap (unbounded above);
    'N–M' when every unknown component has a db/board-derived cap."""
    if not row.get("unknownVP"):
        return None
    if row.get("vpMax") is None:
        return f"≥{row['total']}"
    if row["vpMax"] == row["total"]:
        return None                       # caps collapse: the total is exact
    return f"{row['total']}–{row['vpMax']}"


def card_vp_line(row: dict) -> str:
    """The card-VP FLOOR for one player, with the honest bound on every
    component that is not in it. An uncounted component NEVER appears
    without its bound (the reference failure: 'not countable' relayed as
    a lead that was really a deficit)."""
    unknown = row.get("unknownVP") or []
    if not unknown:
        return f"card VP known {row['cardVP']} (all card VP counted)"
    parts = [f"{u['card']} ≤{u['cap']}" if u["cap"] is not None
             else f"{u['card']} unbounded" for u in unknown]
    return (f"card VP known {row['cardVP']} (floor — {len(unknown)} "
            f"component(s) not exactly counted, bound: {', '.join(parts)})")


def _tag_counts(game: dict, p: dict, is_me: bool, db: dict) -> dict:
    """THE tag counter (tmlib.persisting_tags): played cards minus events,
    PLUS the corporation's own tags — which this function used to drop, so
    the Scientist award and every tag-VP card were short at a table with
    Inventrix, Saturn Systems or Mining Guild in it while menu.py counted
    them. Same table, two answers."""
    name = p.get("name") if is_me else next(
        (n for n, o in (game.get("opponents") or {}).items() if o is p), None)
    return tmlib.persisting_tags(game, name or "", db, pool=p)


def _players(game: dict):
    yield game["me"]["name"], game["me"], True
    for name, o in game["opponents"].items():
        yield name, o, False


def compute(game: dict, mode: str = "full") -> dict:
    db = cardlib.load_db()
    rows = []
    for name, p, is_me in _players(game):
        card_vp, manual, formula = 0, [], []
        unknown = []             # [{"card", "cap" (int|None), "note"}]

        def miss(card, cap, note):
            manual.append(note)
            formula.append(card)
            unknown.append({"card": card, "cap": cap, "note": note})

        counts = p.get("cardResources") or {}
        player_tags = _tag_counts(game, p, is_me, db)
        for entry in p["playedCards"]:
            info = cardlib.find(entry["name"], db)
            if info is None:
                miss(entry["name"], None,
                     f"{entry['name']}: unknown card — count VP manually")
                continue
            vp, vp_data = info.get("vp"), info.get("vpData")
            if isinstance(vp_data, (int, float)):
                card_vp += int(vp_data)
            elif isinstance(vp, (int, float)):
                card_vp += int(vp)
            elif (n := cities_vp(vp_data, game)) is not None:
                card_vp += n
            elif (n := tag_vp(vp_data, player_tags)) is not None:
                card_vp += n
            elif (n := formula_vp(vp_data,
                                  counts.get(entry["name"]))) is not None:
                # resources on the card are tracked → exact, not "manual"
                card_vp += n
            elif (adj := adjacency_vp(info, game, name)) is not None:
                exact, cap, note = adj
                if exact is not None:      # tile on the tracked board
                    card_vp += exact
                else:
                    miss(entry["name"], cap, note)
            elif vp:
                if isinstance(vp_data, dict) and "resourcesHere" in vp_data:
                    res_word = info.get("resourceType") or "resource"
                    miss(entry["name"], None,
                         f"{entry['name']}: {vp} — {res_word} count never "
                         "observed (unbounded; apply.py snap "
                         f"card:{entry['name']} records it)")
                else:
                    miss(entry["name"], None,
                         f"{entry['name']}: {vp} — count on the card")
        # THE tile counter: the board is the record of what is on the map
        counts = tmlib.tile_counts(game, name, p)
        tile_vp = counts["greeneries"] + city_adjacency_vp(game, name)
        placed_cities = sum(1 for occ in game.get("board", {}).values()
                            if _is_city(occ["tile"]) and occ["player"] == name)
        # reserved-area cities (Ganymede Colony, Phobos Space Haven) are off
        # Mars: they have no hex and score no adjacency — never "unplaced"
        unplaced = counts["citiesOnMars"] - placed_cities
        if unplaced > 0:
            greens = sum(1 for occ in game.get("board", {}).values()
                         if occ.get("tile") == "greenery")
            cap = unplaced * min(6, greens)
            note = (f"{unplaced} city tile(s) without recorded position: "
                    f"+1 VP per adjacent greenery, ≤{cap} — count on the "
                    "board (or log apply.py place)")
            manual.append(note)
            unknown.append({"card": f"{unplaced} unplaced city(s)",
                            "cap": cap, "note": note})
        row = {"name": name, "tr": p["tr"], "cardVP": card_vp,
               "tileVP": tile_vp, "manualVP": manual, "formulaVPCards": formula,
               "unknownVP": unknown,
               "milestoneVP": 0, "awardVP": 0, "vpNotes": []}
        rows.append(row)

    if mode == "full":
        for m, owner in game.get("milestonesClaimed", {}).items():
            for r in rows:
                if r["name"] == owner:
                    r["milestoneVP"] += MILESTONE_VP
                    r["vpNotes"].append(f"{m} +{MILESTONE_VP}")
        for award in game.get("awardsFunded", {}):
            # THE award metric (tmlib): the menu and the race table read
            # the same one, and Landlord can no longer count a reserved-area
            # city twice — `sum(tiles.values())` added `citiesOffMars` on
            # top of `cities`, which already includes it.
            scored = sorted(
                ((tmlib.award_metric(game, r["name"], award, db), r)
                 for r in rows),
                key=lambda t: -(t[0] or 0))
            metrics = [m for m, _ in scored]
            if scored[0][0]:
                best = scored[0][0]
                for m, r in scored:
                    if m == best:
                        r["awardVP"] += AWARD_VP[0]
                        r["vpNotes"].append(f"{award} 1st +{AWARD_VP[0]}")
                if len(game["opponents"]) + 1 > 2:  # 2nd place only in 3p+
                    seconds = [m for m in metrics if m is not None and m < best]
                    if seconds:
                        second = max(seconds)
                        if second > 0:
                            for m, r in scored:
                                if m == second:
                                    r["awardVP"] += AWARD_VP[1]
                                    r["vpNotes"].append(
                                        f"{award} 2nd +{AWARD_VP[1]}")

    for r in rows:
        r["total"] = (r["tr"] + r["cardVP"] + r["tileVP"]
                      + r["milestoneVP"] + r["awardVP"])
        # the honest ceiling: floor + every unknown component's cap;
        # None (unbounded) as soon as one component has no sane cap
        caps = [u["cap"] for u in r["unknownVP"]]
        r["vpMax"] = (None if any(c is None for c in caps)
                      else r["total"] + sum(caps))
    rows.sort(key=lambda r: -r["total"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"mode": mode, "players": rows}


def excluded_lines(game: dict, abort_rows: list[dict]) -> list[str]:
    """What the abort total leaves out, per player. Abort ranks TR + card VP
    + tile VP only (house definition) — silence about a claimed milestone
    reads as "nobody holds one" and inverts the standing. The maths is
    untouched; the omission is printed. Award places are today's metric
    leaders and still move."""
    full = {r["name"]: r for r in compute(game, "full")["players"]}
    out = []
    for row in abort_rows:
        f = full.get(row["name"]) or {}
        extra = (f.get("milestoneVP") or 0) + (f.get("awardVP") or 0)
        if not extra:
            continue
        out.append(f"   {row['name']}: {', '.join(f['vpNotes'])} = +{extra} VP"
                   f" → {row['total'] + extra} VP if counted now")
    if out:
        out.insert(0, "⚠ EXCLUDED from the totals above (abort = TR + cards + "
                      "tiles): claimed milestones and funded awards — award "
                      "places are today's metric leaders and can still move")
    return out


def standings_line(game: dict, mode: str = "full") -> str:
    """One-line standings for the generation turnover: the
    physical table has no VP column, so every produce.py prints this.
    Format: 'Standings (full): Zed 55 (TR 45 +7 cards +3 tiles) · Carl 44 …'
    A player with an uncounted component carries the BOUND ('Anna 61–64',
    'Diana ≥38'), never the bare floor; manual-count flags are summarised
    as '+?' so nothing hides."""
    r = compute(game, mode)
    parts = []
    for row in r["players"]:
        extra = []
        if row["cardVP"]:
            extra.append(f"{row['cardVP']:+d} cards")
        if row["tileVP"]:
            extra.append(f"+{row['tileVP']} tiles")
        if row["milestoneVP"]:
            extra.append(f"+{row['milestoneVP']} ms")
        if row["awardVP"]:
            extra.append(f"+{row['awardVP']} aw")
        if row["manualVP"]:
            extra.append("+?")
        detail = f" (TR {row['tr']} {' '.join(extra)})" if extra else f" (TR {row['tr']})"
        shown = bound_str(row) or str(row["total"])
        parts.append(f"{row['name']} {shown}{detail}")
    return f"Standings ({mode}): " + " · ".join(parts)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default="state/game.json")
    p.add_argument("--abort", action="store_true",
                   help="rank now: TR + card VP + tile VP only")
    p.add_argument("--app", action="store_true",
                   help="print the app's final victoryPointsBreakdown table "
                        "(default in app modes with a linked playerId)")
    a = p.parse_args()
    game = json.loads(Path(a.state).read_text())
    setup_path = Path(a.state).parent / "setup.json"
    setup = json.loads(setup_path.read_text()) if setup_path.exists() else {}
    linked = any(p.get("playerId") for p in setup.get("players", [])
                 if p.get("isMe"))
    if not a.abort and (a.app or (setup.get("gameMode") in APP_MODES and linked)):
        _print_app_table(setup)
    r = compute(game, mode="abort" if a.abort else "full")
    print(f"=== Scoring ({r['mode']}) ===")
    # At real-table relay bandwidth opponents' tableaus
    # are usually empty in the tracker — say so, or the ranking lies.
    bare = [n for n, o in game.get("opponents", {}).items()
            if not o.get("playedCards")]
    if bare:
        print(f"⚠ card VP UNTRACKED for: {', '.join(sorted(bare))} — "
              "their totals are TR+tiles only; walk their tableaus "
              "before trusting this ranking")
    for row in r["players"]:
        shown = bound_str(row)
        head = (f"{shown} VP (floor {row['total']}: " if shown
                else f"{row['total']} VP (")
        print(f"{row['rank']}. {row['name']}: {head}"
              f"TR {row['tr']} + cards {row['cardVP']} + tiles {row['tileVP']}"
              f" + milestones {row['milestoneVP']} + awards {row['awardVP']})")
        print(f"   {card_vp_line(row)}")
        for m in row["manualVP"]:
            print(f"   ⚠ manual: {m}")
    if r["mode"] == "abort":
        for line in excluded_lines(game, r["players"]):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
