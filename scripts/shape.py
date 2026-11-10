#!/usr/bin/env python3
"""Position-shape metrics: deterministic FACTS about how the position is
developing, with FLAGS when a threshold trips. Never a recommendation —
the model decides what to do with a flag (fix-plan DOCTRINE: scripts
compute facts, gates interrupt, the model decides).

The reference failure is games/2026-08-29-game5: the advisor bought ONE
project card in generations 2-9, finished MC production 5 vs the table
max 18, and ran a tiles+milestones plan with no repeatable VP/TR source
after gen 3 — every one of those was knowable at generation 5 and nothing
surfaced it. This module surfaces it:

  (a) cards bought per generation — me vs each opponent and the field
      median, parsed from the research/dealt lines of state/log.md;
  (b) my MC production vs the table median, from state/game.json;
  (c) VP slope over the last generations, from the produce.py standings
      lines in state/log.md when present ("insufficient data" otherwise);
  (d) an inventory of my REPEATABLE VP/TR sources: blue-card actions
      with TR/VP effects, positive plant production, positive heat
      production while temperature is unmaxed.

Flags (each a FACT + evidence string, never advice):
  cardsBought — two consecutive generations of 0 buys by me (×2 evidence:
                game5 and the KB hard trigger);
  mcProd      — my MC production below the table median after gen 4;
  sources     — zero repeatable sources with ≥3 generations left on the
                clock's RANGE TOP (the planning horizon, clock.py).

Library: compute(store) -> dict, render(metrics) -> str.
Consumers: advise.py (the mandatory ## SHAPE brief section), the
zero-buy research gate (tmlib.Engine.dealt), planlib's exit gate.
"""
import argparse
import ast
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clock
import tmlib
from tmlib import PARAM_SCALE, Store

# my research lines, as tmlib.Engine.dealt logs them
_DEALT = re.compile(
    r"^- G(?P<gen>\d+) — Research: dealt \[(?P<cards>.*?)\], "
    r"kept \[(?P<kept>.*?)\]")
_DRAFTED = re.compile(
    r"^- G(?P<gen>\d+) — Research: drafted .*? → kept (?P<kept>.*?) \(")
# opponent research lines, as tmlib.Engine.research logs them
_OPP = re.compile(
    r"^- G(?P<gen>\d+) — (?P<who>.+?): research kept (?P<n>\d+) cards?")
# produce.py standings lines (score.standings_line), when logged.
# A row with an uncounted component carries a BOUND ("Anna 61–64",
# "Diana ≥38"); the slope reads the FLOOR — the only number every
# form guarantees.
_STANDINGS = re.compile(r"Standings \((?:full|abort)\): (?P<rows>.+)$")
_STANDING_ROW = re.compile(r"^(?P<name>.+?) ≥?(?P<total>\d+)(?:–\d+)? \(")

# blue-action keys that repeat a TR raise every generation
_TR_ACTION_KEYS = ("tr", "global", "ocean", "greenery")


def _kept_count(bracket_inner: str) -> int:
    """Number of names inside a logged Python-list literal (its inner
    text). Fail-soft to a comma count — a parse miss must never crash."""
    inner = bracket_inner.strip()
    if not inner:
        return 0
    try:
        return len(ast.literal_eval(f"[{inner}]"))
    except (ValueError, SyntaxError):
        return inner.count(",") + 1


def _log_lines(store: Store) -> list[str]:
    try:
        return store.log_path.read_text().splitlines()
    except OSError:
        return []


def cards_bought(store: Store, me: str) -> dict:
    """{'mine': {gen: n}, 'opponents': {name: {gen: n}}, 'fieldMedian':
    {gen: median-of-opponents}} from the research/dealt log lines.
    Generations with several research events (the initial deal) sum."""
    mine: dict[int, int] = {}
    opps: dict[str, dict[int, int]] = {}
    for line in _log_lines(store):
        m = _DEALT.match(line) or _DRAFTED.match(line)
        if m:
            gen = int(m.group("gen"))
            kept = m.group("kept")
            n = (_kept_count(kept) if m.re is _DEALT
                 else (0 if not kept.strip() else len(kept.split(","))))
            mine[gen] = mine.get(gen, 0) + n
            continue
        m = _OPP.match(line)
        if m and m.group("who") != me:
            gen = int(m.group("gen"))
            slot = opps.setdefault(m.group("who"), {})
            slot[gen] = slot.get(gen, 0) + int(m.group("n"))
    gens = sorted({g for s in opps.values() for g in s})
    median = {g: statistics.median([s[g] for s in opps.values() if g in s])
              for g in gens}
    return {"mine": mine, "opponents": opps, "fieldMedian": median}


def vp_slope(store: Store, me: str) -> dict | None:
    """VP change over the last ≤3 turnovers, from logged standings lines.
    None (insufficient data) below 2 lines — never a crash."""
    rows: list[dict[str, int]] = []
    for line in _log_lines(store):
        m = _STANDINGS.search(line)
        if not m:
            continue
        row = {}
        for seg in m.group("rows").split(" · "):
            r = _STANDING_ROW.match(seg.strip())
            if r:
                row[r.group("name")] = int(r.group("total"))
        if row:
            rows.append(row)
    if len(rows) < 2:
        return None
    window = rows[-4:]                      # ≤3 turnovers of slope
    first, last = window[0], window[-1]
    deltas = {n: last[n] - first[n] for n in last if n in first}
    field = [d for n, d in deltas.items() if n != me]
    if me not in deltas or not field:
        return None
    return {"mine": deltas[me], "fieldMax": max(field),
            "fieldMedian": statistics.median(field),
            "turnovers": len(window) - 1}


def _action_branches(beh: dict) -> list[dict]:
    inner = beh.get("or")
    if isinstance(inner, dict):
        return [b for b in (inner.get("behaviors") or [])
                if isinstance(b, dict)]
    return [beh]


def repeatable_sources(game: dict, db: dict | None = None) -> list[str]:
    """My repeatable VP/TR sources, from playedCards + production:
    blue-card actions whose branches raise TR / a global / place a
    greenery, or feed a per-resource VP card; positive plant production;
    positive heat production while temperature is unmaxed."""
    import cards as cardlib
    if db is None:
        try:
            db = cardlib.load_db()
        except FileNotFoundError:
            db = {"cards": []}
    me = game["me"]
    out: list[str] = []
    prod = {**{r: 0 for r in tmlib.RESOURCES}, **(me.get("production") or {})}
    if prod["plants"] > 0:
        out.append(f"plant production +{prod['plants']} (greenery track)")
    if prod["heat"] > 0 and \
            game["globals"]["temperature"] < PARAM_SCALE["temperature"]["max"]:
        out.append(f"heat production +{prod['heat']} (temperature unmaxed)")
    for entry in me.get("playedCards") or []:
        name = str(entry.get("name") or "")
        try:
            info = cardlib.find(name, db)
        except Exception:
            info = None
        if not info or info.get("type") != "active":
            continue
        beh = info.get("actionBehavior")
        if not isinstance(beh, dict):
            continue
        for b in _action_branches(beh):
            merged = {**{k: v for k, v in beh.items() if k != "or"}, **b}
            alive = ("tr" in merged
                     or "greenery" in merged     # tile VP persists at max O2
                     or ("ocean" in merged
                         and game["globals"]["oceans"]
                         < PARAM_SCALE["oceans"]["max"])
                     or ("global" in merged and any(
                         game["globals"].get(p, 0) < PARAM_SCALE[p]["max"]
                         for p in (merged.get("global") or {})
                         if p in PARAM_SCALE)))
            if alive:
                out.append(f"{info['name']} action (repeatable TR)")
                break
            if "addResources" in merged and "per" in str(info.get("vp") or ""):
                out.append(f"{info['name']} action (repeatable VP: "
                           f"{info['vp']})")
                break
    corp = me.get("corporation")
    if tmlib.corp_rule(corp, "trBoostCost"):
        out.append(f"{corp} action (repeatable TR)")
    return out


def _gens_left_top(game: dict, setup: dict) -> int | None:
    """Generations left on the clock's RANGE TOP — the planning horizon
    (clock.py: plan to the range top). None when the clock cannot run."""
    try:
        history = [h for h in game.get("history") or []
                   if h.get("generation", 0) < game["generation"] - 1]
        est = clock.estimate(game["globals"], game["generation"],
                             players=setup.get("playerCount") or 5,
                             declared_final=game.get("declaredFinalGeneration"),
                             history=history, wgt=tmlib.wgt_enabled(setup))
        return est["gensLeftRange"][1]
    except Exception:
        return None


def compute(store: Store) -> dict:
    """All shape metrics + flags as one dict (importable contract)."""
    game = store.load_game()
    try:
        setup = store.load_setup()
    except (FileNotFoundError, ValueError):
        setup = {}
    me = game["me"]
    name = me.get("name") or ""
    gen = game["generation"]
    bought = cards_bought(store, name)
    mine_prod = (me.get("production") or {}).get("mc", 0)
    table = [mine_prod] + [
        (o.get("production") or {}).get("mc", 0)
        for o in (game.get("opponents") or {}).values()]
    table_median = statistics.median(table) if table else 0
    slope = vp_slope(store, name)
    sources = repeatable_sources(game)
    gens_top = _gens_left_top(game, setup)

    flags: dict[str, str | None] = {"cardsBought": None, "mcProd": None,
                                    "sources": None}
    gens_bought = sorted(bought["mine"])
    if len(gens_bought) >= 2:
        a, b = gens_bought[-2], gens_bought[-1]
        if b == a + 1 and bought["mine"][a] == 0 and bought["mine"][b] == 0:
            flags["cardsBought"] = (
                f"0 cards kept at research in gen {a} and again in gen {b} "
                f"(two consecutive zero-buy generations)")
    if gen > 4 and mine_prod < table_median:
        flags["mcProd"] = (f"my MC production {mine_prod} is below the table "
                           f"median {table_median} at generation {gen} (> 4)")
    if not sources and gens_top is not None and gens_top >= 3:
        flags["sources"] = (
            f"zero repeatable VP/TR sources with {gens_top} generation(s) "
            f"left on the clock's range top")
    return {"generation": gen, "me": name,
            "cardsBought": bought,
            "mcProd": {"mine": mine_prod, "tableMedian": table_median},
            "vpSlope": slope,
            "repeatableSources": sources,
            "gensLeftRangeTop": gens_top,
            "flags": flags}


def _series(counts: dict) -> str:
    return " ".join(f"g{g}:{counts[g]}" for g in sorted(counts)) or "none logged"


def _flag(text: str | None) -> str:
    return f"  ⚠ FLAG: {text}" if text else ""


def render(m: dict) -> str:
    """The compact SHAPE block — facts and flags, no recommendations."""
    b = m["cardsBought"]
    lines = [
        f"cards bought/gen — me: {_series(b['mine'])} · field median: "
        f"{_series(b['fieldMedian'])}" + _flag(m["flags"]["cardsBought"]),
    ]
    for who in sorted(b["opponents"]):
        lines.append(f"  {who}: {_series(b['opponents'][who])}")
    p = m["mcProd"]
    lines.append(f"MC production — mine {p['mine']} vs table median "
                 f"{p['tableMedian']}" + _flag(m["flags"]["mcProd"]))
    s = m["vpSlope"]
    if s is None:
        lines.append("VP slope — insufficient data (no standings lines "
                     "logged yet)")
    else:
        lines.append(f"VP slope (last {s['turnovers']} turnover(s)) — mine "
                     f"{s['mine']:+d} · field max {s['fieldMax']:+d} · field "
                     f"median {s['fieldMedian']:+g}")
    src = m["repeatableSources"]
    lines.append("repeatable VP/TR sources — "
                 + ("; ".join(src) if src else "none")
                 + _flag(m["flags"]["sources"]))
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".", help="repo root (state/ = active game)")
    p.add_argument("--state", default=None,
                   help="a game folder (games/<date>-gameN) instead of state/")
    p.add_argument("--json", action="store_true", help="metrics as JSON")
    a = p.parse_args()
    store = Store(a.root, state_dir=a.state)
    try:
        m = compute(store)
    except FileNotFoundError as e:
        print(f"ERROR: {e} — is a game active?", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(m, indent=2, ensure_ascii=False))
    else:
        print(render(m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
