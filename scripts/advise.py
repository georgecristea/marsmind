#!/usr/bin/env python3
"""Advisor brief assembler (M3): state + strategy KB + calculators → one
self-contained brief the advisor reasons over before recommending.

The advisor NEVER answers from memory: this script re-reads every file.
Output contract (enforced in the brief itself): execution traces, hand in
play order, the engine-derived AVAILABLE ACTIONS menu before Pass, the
RACES table feeding the per-opponent threats section.

`--sweep [--peek] [--whose L]` is the COMPACT brief for one judgment sweep
of the round loop (feed since the cursor, pending triggers, races, plan
threats + open steps, menu line — no KB, no state dump).
"""
import pathlib
import re
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appapi
import clock
import latency
import menu
import planlib
import races
import shape
import tmlib
import triage
from tmlib import EventError

APP_MODES = ("app-practice", "app-online")
LAND_WARN = (" ⚠ BOARD NEARLY FULL — tile cards and plant production are "
             "dead weight; pivot to card VP")


def _fetch_app(setup: dict) -> dict | None:
    """App modes: my /api/player view (exact board occupancy, live blue-action
    count). None in physical mode or on ANY error — the tracker is the fallback."""
    if setup.get("gameMode") not in APP_MODES:
        return None
    try:
        pid = next((p.get("playerId") for p in setup.get("players", [])
                    if p.get("isMe")), None) or setup.get("playerId")
        url = appapi.configured_url(setup)
        if not pid or not url:
            return None
        # one attempt, 2s: table play never waits on the app
        return appapi.AppClient(url, timeout=2, retries=1).player(pid)
    except Exception:
        return None


def _free_land_app(payload: dict) -> int | None:
    """Exact free land from the app's game.spaces[] (None if absent)."""
    spaces = (payload.get("game") or {}).get("spaces")
    if not spaces:
        return None
    return sum(1 for s in spaces
               if s.get("spaceType") == "land" and s.get("tileType") is None)


def _requirement_windows(g: dict) -> list[str]:
    out = []
    o2, t = g["globals"]["oxygen"], g["globals"]["temperature"]
    if 3 <= o2 <= 5:
        out.append(f"O2 at {o2}% — 'max 5% O2' cards are expiring: play or discard NOW")
    if 6 <= o2 <= 7:
        out.append(f"O2 at {o2}% — 'max 7% O2' window closing")
    if -18 <= t <= -14:
        out.append(f"Temperature {t}°C — 'max −14°C' cards expiring soon")
    if g["globals"]["oceans"] >= 7:
        out.append(f"{9 - g['globals']['oceans']} ocean slots left — ocean cards/SPs are a race")
    return out


def build_brief(root: str | Path = ".", kb_dir: str | Path = "strategy",
                brief: bool | None = None) -> str:
    """`brief` drops the KB dump; None → on in app modes, where the
    advisor reads strategy/ once per session rather than per turn."""
    root = Path(root)
    g = json.loads((root / "state" / "game.json").read_text())
    setup = json.loads((root / "state" / "setup.json").read_text())
    log_tail = (root / "state" / "log.md").read_text().splitlines()[-15:]
    me = g["me"]
    if brief is None:
        brief = setup.get("gameMode") in APP_MODES

    # history entry k = globals when gen k closed = start of gen k+1; the
    # clock wants the starts of gens 1..current-1 (the current start is
    # g["globals"]), so the entry that IS the current start is excluded.
    history = [h for h in g.get("history", [])
               if h["generation"] < g["generation"] - 1]
    wgt = tmlib.wgt_enabled(setup)
    est = clock.estimate(g["globals"], g["generation"],
                         players=setup["playerCount"], history=history,
                         wgt=wgt)
    app = _fetch_app(setup)
    free = _free_land_app(app) if app else None
    if free is None:
        free = tmlib.free_land(tmlib.occupied_space_ids(g))

    kb_parts = ["(omitted — --brief; the advisor read strategy/*.md at session "
                "start; pass --full to include it)"]
    if not brief:
        kb_parts = [f"----- {f.name} -----\n{f.read_text()}"
                    for f in sorted(Path(kb_dir).glob("*.md"))]

    opp_lines = []
    for name, o in g["opponents"].items():
        played = ", ".join(f"{c['name']} (g{c['gen']})" for c in o["playedCards"]) or "none logged"
        conf = "estimated" if o.get("estimated") else f"observed g{o.get('lastObservedGen')}"
        opp_lines.append(
            f"- {name} [{o.get('corporation') or 'corp?'}] TR {o['tr']}, "
            f"resources {o['resources']} ({conf}), production {o['production']}, "
            f"tiles {o['tiles']}\n  played: {played}")

    windows = _requirement_windows(g)
    items = menu.available_actions(g, setup, free_land=free)
    menu_block = menu.render(items, g, app=app)
    race_block = races.render(races.race_table(g, setup))
    # W1-B item 2a: the SHAPE block is MANDATORY in every brief (both
    # --brief and --full) — position-shape facts + flags (shape.py).
    try:
        shape_block = shape.render(shape.compute(tmlib.Store(root)))
    except Exception as e:                # a brief must never fail on shape
        shape_block = f"(shape metrics unavailable: {e})"

    return "\n".join([
        "# PHOBOS ADVISOR BRIEF — read fully, then recommend",
        f"\n## Game: generation {g['generation']}, first player {g['firstPlayer']}",
        f"Globals: temp {g['globals']['temperature']}°C, O2 {g['globals']['oxygen']}%, "
        f"oceans {g['globals']['oceans']}/9, Free land: {free}"
        + (LAND_WARN if free <= 6 else ""),
        parameter_steps_line(parameter_steps(root / "state" / "feed.jsonl"),
                             me["name"]),
        f"Clock: {est['note']}" if 'note' in est else "",
        ("RESEARCH: DRAFT (pick-1-pass, 4/3/2 then buy) — skills/research-phase "
         "Draft variant; log with `apply.py dealt … --kept … --drafted`"
         if setup.get("draft") else ""),
        (f"WGT ON: {g['firstPlayer']} raises one parameter for free at "
         f"generation end (no TR, no bonuses; log `apply.py wgt …` BEFORE "
         f"produce.py)" + (" — THAT IS YOU: end the plan with a WGT-choice "
                           "step after passGate (skills/turn-advisor)"
                           if g['firstPlayer'] == g['me']['name'] else "")
         ) if wgt else "",
        f"Milestones claimed: {g['milestonesClaimed'] or 'none — free VP at this table'}",
        f"\n## ME — {me['name']} [{me.get('corporation') or 'no corp yet'}] TR {me['tr']}",
        f"Resources: {me['resources']}",
        f"Production: {me['production']}",
        f"Hand (CURRENT play order — re-sort if state changed): {me['hand'] or 'empty'}",
        f"Played: {[c['name'] for c in me['playedCards']] or 'none'}",
        f"Tiles: {me['tiles']}  Milestones: {me['milestones']}",
        "",
        menu_block,
        "",
        "## SHAPE (position-shape facts + flags — shape.py; a ⚠ FLAG line "
        "is evidence to reason over, not an instruction)",
        shape_block,
        "",
        race_block,
        "\n## REQUIREMENT WINDOWS",
        *(windows or ["(none critical)"]),
        "\n## OPPONENTS",
        *opp_lines,
        "\n## RECENT LOG",
        *log_tail,
        "\n## OUTPUT CONTRACT (house format — mandatory)",
        "1. Full-generation plan as EXECUTION TRACES: every action a numbered",
        "   micro-script in resolution order, one physical table-step per line,",
        "   cost → gain with before → after values and running MC balance.",
        "2. End with hand in recommended PLAY ORDER (this order is a contract;",
        "   if it changed, one-line reason per moved card).",
        "3. THREATS section: per opponent — inferred archetype from their",
        "   played cards + sequence, what they need next, concrete counters",
        "   (milestone snipes, removal targets, game-length control).",
        "4. Never recommend Pass while the AVAILABLE ACTIONS menu above lists",
        "   anything: a verdict per item (do it, or why it is bad). The pass",
        "   gate refuses otherwise. The threats block comes from RACES.",
        "5. Cite the KB principle behind every card evaluation; arithmetic",
        "   claims come from scripts (payback.py, clock.py, endgame.py).",
        "\n# STRATEGY KNOWLEDGE BASE",
        *kb_parts,
    ])


# ── judgment sweep (round loop, lane 2) ─────────────────────────────
# `--sweep` is the COMPACT brief for ONE judgment sweep over the opponent
# events since the last sweep: the feed lines with their trigger reasons,
# the pending triggers, the races table, the plan's threats + open steps,
# the menu line. NOT the KB, NOT the state dump — the model reasons over
# this and concludes with `planlib.py patch` (possibly an empty patch that
# only marks feed lines handled). state/sweep-cursor.json = {"line": N}
# (last feed line shown); the flag state/sweep-inflight marks the sweep
# as in flight until patch (concluded) or promote (abandoned).
SWEEP_CURSOR = "sweep-cursor.json"


def sweep_cursor(store: tmlib.Store) -> int:
    p = store.state_dir / SWEEP_CURSOR
    if not p.exists():
        return 0
    try:
        return int(json.loads(p.read_text()).get("line") or 0)
    except (ValueError, AttributeError):
        return 0


def _write_cursor(store: tmlib.Store, line: int) -> None:
    (store.state_dir / SWEEP_CURSOR).write_text(
        json.dumps({"line": int(line)}) + "\n")


_GLOBAL_RAISE = re.compile(
    r"global:\s*(?P<who>.+?)\s+raised\s+(?P<param>temperature|oxygen|oceans)"
    r"\s*\+(?P<n>\d+)")


def parameter_steps(feed_path) -> dict:
    """{player: {temperature, oxygen, oceans, total}} — how many global
    parameter steps each seat has personally RAISED.

    The sharpest signal a losing engine gives off, and the one the brief was
    missing: in one recorded 2p game the counts were 37 to 5 with temperature
    19-0, and the losing seat's TR was still its starting value at the end of
    generation 9 of 12. Counted from the listener's own feed, so it costs no
    new state and no engine verb; physical mode has no feed and gets nothing.

    APPROXIMATE BY CONSTRUCTION: only raises the app log attributes to a
    player are counted, so effects it reports without a "global:" reason are
    missed. On the game that motivated this it read 33 to 3 where the app's
    own globalParameterSteps said 37 to 5 — the ratio, which is the whole
    point, is unaffected. Never quote it as the authoritative count.
    """
    try:
        text = pathlib.Path(feed_path).read_text()
    except OSError:
        return {}
    tally: dict = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        for reason in row.get("reasons") or []:
            m = _GLOBAL_RAISE.search(str(reason))
            if not m:
                continue
            who = (row.get("actor") or m.group("who")).strip()
            slot = tally.setdefault(who, {"temperature": 0, "oxygen": 0,
                                          "oceans": 0, "total": 0})
            slot[m.group("param")] += int(m.group("n"))
            slot["total"] += int(m.group("n"))
    return tally


def parameter_steps_line(tally: dict, me: str) -> str:
    """One brief line, leader first, with a warning when I have raised
    almost nothing — the pivot signal, printed while it is still fixable."""
    if not tally:
        return ""
    rows = sorted(tally.items(), key=lambda kv: -kv[1]["total"])
    parts = [f"{n} {t['total']} (temp {t['temperature']}, O2 {t['oxygen']}, "
             f"oceans {t['oceans']})" for n, t in rows]
    mine = (tally.get(me) or {}).get("total", 0)
    best = rows[0][1]["total"]
    warn = ""
    if best >= 4 and mine * 3 <= best:
        warn = (f"  ⚠ YOU HAVE RAISED {mine} — parameters are NOT your scoring "
                f"line. That is fine ONLY if another one is already running: "
                f"name your VP exit (tiles / card VP / meta) and its rate. Two "
                f"games in the ledger were won while LOSING TR; both had tile "
                f"and milestone engines. An engine with no named exit is the leak.")
    return "Parameter steps raised (from the log, ≈): " + " · ".join(parts) + warn


def _feed_line(e: dict) -> str:
    head = f"#{e.get('line')} {e.get('actor') or '-'} {e.get('kind')}: {e.get('raw', '')}"
    if e.get("handled"):
        return head + "  [handled]"
    if e.get("trigger"):
        return head + "  ⚡ " + "; ".join(e.get("reasons") or [])
    if e.get("applied") is False:
        return head + f"  (NOT applied: {e.get('error')})"
    return head + "  (silent)"


def _plan_block(store: tmlib.Store) -> list[str]:
    try:
        plan = planlib.load_plan(store)
    except EventError:
        return ["## PLAN", "(no plan — compose the draft: planlib.py set --draft)"]
    head = f"## PLAN — generation {plan.get('generation')}"
    head += "  [DRAFT]" if plan.get("draft") else "  [LIVE]"
    lines = [head, *planlib.patch_failed_lines(plan)]
    threats = plan.get("threats")
    if planlib._threats_ok(threats):
        lines.append("⚠ THREATS")
        for t in ([threats] if isinstance(threats, str) else threats):
            lines.append(f"  - {t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)}")
    else:
        lines.append("⚠ THREATS: none yet (promote will require them)")
    open_steps = [s for s in plan["steps"] if not s.get("done")]
    done = len(plan["steps"]) - len(open_steps)
    lines.append(f"open steps ({done} executed, omitted):")
    for s in open_steps:
        mark = planlib.VOLATILITY.get(s.get("volatility"), "?")
        extra = f"  cue: {s['cue']}" if s.get("cue") else ""
        extra += f"  map: {s['mapHighlight']}" if s.get("mapHighlight") else ""
        lines.append(f"  ▢ {s['id']}  {mark} {s.get('summary')}{extra}")
    if not open_steps:
        lines.append("  (none — every step executed)")
    lines.extend(plan.get("warnings") or [])
    return lines


def build_sweep(store: tmlib.Store, peek: bool = False,
                whose: str | None = None) -> str:
    """The compact judgment-sweep brief (see the block comment above).
    Advances the cursor and raises the in-flight flag unless `peek`."""
    with latency.timed("sweep", store=store) as t:
        g = store.load_game()
        setup = store.load_setup()
        feed_path = triage.feed_path(store)
        cursor = sweep_cursor(store)
        try:
            plan = planlib.load_plan(store)
        except EventError:
            plan = None
        entries = (triage.triage_feed(feed_path, g, setup, plan)
                   if feed_path.exists() else [])
        new = [e for e in entries if int(e.get("line") or 0) > cursor]
        pend = [e for e in entries if e.get("trigger") and not e.get("handled")]
        turn = whose or next((e.get("actor") for e in reversed(new)
                              if e.get("actor")), None) or "?"
        items = menu.available_actions(g, setup)
        live_flag = " --live" if (plan and not plan.get("draft")) else ""
        lines = [
            f"# SWEEP — generation {g['generation']}, first player "
            f"{g['firstPlayer']}, turn: {turn}",
            f"## FEED since #{cursor} ({len(new)} new"
            + (")" if feed_path.exists() else "; no feed file — listener not running)"),
            *([_feed_line(e) for e in new] or ["(none)"]),
            "## PENDING TRIGGERS (unhandled — handle via planlib.py patch "
            "\"feed\" or triage.py handle)",
            *(triage.render_pending(pend) or ["no pending triggers"]),
            races.render(races.race_table(g, setup)),
            *_plan_block(store),
            "## MENU",
            menu.summary(items),
            "## CONCLUDE",
            # the EXACT command: on the player's own turn the plan is live,
            # and `patch` without --live used to refuse (P8 #9)
            f"planlib.py patch{live_flag} (JSON: replace / insert_after / "
            "remove / threats / feed) — an empty patch with only \"feed\" = "
            "plan stands; promote abandons an unfinished sweep.",
        ]
        if not peek:
            if new:
                _write_cursor(store, max(int(e["line"]) for e in new))
            # W2-C: stamp the feed cursor this sweep READ — its verdict is
            # valid for that feed only; planlib.patch refuses a conclusion
            # as STALE once the live feed has moved past the stamp.
            read_to = max([int(e.get("line") or 0) for e in entries]
                          + [cursor])
            planlib.set_sweep_inflight(store, [int(e["line"]) for e in new],
                                       gen=g["generation"], cursor=read_to)
            t.note = f"lines {len(new)}"
        else:
            t.note = "peek"
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".")
    p.add_argument("--kb", default="strategy")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--brief", action="store_true",
                      help="omit the strategy KB dump (default in app modes)")
    mode.add_argument("--full", action="store_true",
                      help="force the KB dump even in app modes")
    mode.add_argument("--sweep", action="store_true",
                      help="COMPACT judgment-sweep brief: feed since the "
                           "cursor + triggers + races + plan + menu (no KB, "
                           "no state dump); advances state/sweep-cursor.json")
    p.add_argument("--peek", action="store_true",
                   help="with --sweep: print without advancing the cursor "
                        "or raising the in-flight flag")
    p.add_argument("--whose", default=None,
                   help="with --sweep: whose-turn label for the header")
    a = p.parse_args()
    if a.peek and not a.sweep:
        p.error("--peek only makes sense with --sweep")
    try:
        if a.sweep:
            print(build_sweep(tmlib.Store(a.root), peek=a.peek, whose=a.whose))
            return 0
        print(build_brief(a.root, a.kb,
                          brief=True if a.brief else False if a.full else None))
        return 0
    except FileNotFoundError as e:
        print(f"ERROR: {e} — is a game active? (scripts/setup.py)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
