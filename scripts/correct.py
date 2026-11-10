#!/usr/bin/env python3
"""Physical-table correction tool (the deviation drill).

`correct.py step <label>` reverses a WRONGLY-APPLIED plan step: the player
reports "I never actually did 1a" and this emits the inverse of the step's
OWN event list through the Engine (never hand-edits), reopens the plan
step, and prints the tracker summary for a single table-confirmation.

Guarantee: NEVER a silent partial reverse. Every inverse event applied is
printed (✓ lines) and everything that cannot be auto-inverted is printed
as a MANUAL note (convert, standard projects, milestones/awards, card
behavior effects, placement bonuses).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import Engine, EventError, Store, STEEL_VALUE, TITANIUM_VALUE
import planlib


def _reverse_event(eng: Engine, ev: dict) -> list[str]:
    """Inverse of one recorded plan event, applied via the Engine.

    Returns the printed trace: '  ✓ …' per inverse event applied and
    '  MANUAL: …' per step that must be fixed by hand.
    """
    method = ev.get("method")
    args = list(ev.get("args", []))
    kw = dict(ev.get("kwargs", {}))
    out: list[str] = []

    def apply(desc: str, fn, *a, **k):
        fn(*a, **k)
        out.append(f"  ✓ {desc}")

    if method == "play":
        player, card = args[0], args[1]
        info = eng.card(card)
        canonical = info["name"] if info else card
        apply(f"unplay {canonical} ({player})", eng.unplay, player, card)
        if eng._is_me(eng.resolve_player(player)):
            apply(f"return {canonical} to hand", eng.hand_add, [canonical])
        cost = kw.get("cost", (info or {}).get("cost"))
        steel = kw.get("steel", 0)
        titanium = kw.get("titanium", 0)
        heat = kw.get("heat", 0)
        if cost is None:
            out.append(f"  MANUAL: cost of {card!r} unknown — refund it "
                       "by hand (apply.py res <me> mc +cost)")
        else:
            mc_due = max(0, cost - steel * STEEL_VALUE
                         - titanium * TITANIUM_VALUE - heat)
            if mc_due:
                apply(f"refund {mc_due} MC (card cost)",
                      eng.res, player, "mc", +mc_due)
            for r, n in (("steel", steel), ("titanium", titanium),
                         ("heat", heat)):
                if n:
                    apply(f"refund {n} {r} (payment)", eng.res, player, r, +n)
        if (info or {}).get("behavior"):
            out.append(f"  MANUAL: reverse {canonical}'s card effects by "
                       f"hand (prod/tr/res/sync --force): {info['behavior']}")
    elif method == "place":
        space = args[2] if len(args) >= 3 else kw.get("space_id")
        apply(f"unplace tile from {space}", eng.unplace, space)
        out.append("  MANUAL: reverse any placement bonuses / "
                   "ocean-adjacency MC gained at placement (res events)")
    elif method == "res":
        player, resource, delta = args
        apply(f"res {player} {resource} {-delta:+d} (negated)",
              eng.res, player, resource, -delta)
    elif method == "tr":
        player, delta = args
        apply(f"tr {player} {-delta:+d} (negated)", eng.tr, player, -delta)
    elif method == "prod":
        player, resource, delta = args
        apply(f"prod {player} {resource} {-delta:+d} (negated)",
              eng.prod, player, resource, -delta)
    elif method == "convert":
        out.append("  MANUAL: convert cannot be auto-inverted — "
                   "use res/tr/sync --force")
    elif method == "use_action":
        # unuse_action is the GENERIC inverse of the card's actionBehavior
        # (refund the spend, take back the gains, walk a raised global back
        # with its TR, remove the card resource) AND frees the
        # once-per-generation ledger — all or nothing.
        action = args[0]
        player = args[1] if len(args) > 1 else kw.get("player")
        try:
            out.append("  ✓ " + eng.unuse_action(
                action, player=player, choice=kw.get("choice"),
                steel=kw.get("steel", 0), titanium=kw.get("titanium", 0),
                from_card=kw.get("from_card")))
        except EventError as e:
            out.append(f"  MANUAL: undo {action}'s action effect by hand "
                       f"— {e} (res/prod/tr/sync --force)")
            if player is None:
                apply(f"action ledger reset: {action!r} available again",
                      eng.register_action, action)
    elif method in ("milestone", "award", "standard"):
        out.append(f"  MANUAL: {method} {args!r} must be reversed by hand "
                   "(rare — check MC / tiles / globals / claim registry)")
    else:
        out.append(f"  MANUAL: no auto-inverse for {method!r} "
                   f"(args {args!r}, kwargs {kw!r}) — reverse by hand")
    return out


def reverse_step(store: Store, label: str) -> list[str]:
    """Reverse one done plan step; reopen it; return the full printed trace."""
    plan = planlib.load_plan(store)
    want = label.strip().lower()
    step = next((s for s in plan["steps"] if s["id"].lower() == want), None)
    if step is None:
        raise EventError(f"No plan step {label!r}; steps: "
                         f"{[s['id'] for s in plan['steps']]}")
    if not step.get("done"):
        raise EventError(f"Step {step['id']} is not marked done — "
                         "nothing to reverse")
    game = store.load_game()
    store.log(f"G{game['generation']}",
              f"CORRECTION: reversing plan step {step['id']} "
              f"({step.get('summary', '')})")
    lines = [f"CORRECTION — reversing step {step['id']}: "
             f"{step.get('summary', '')}"]
    eng = Engine(store)
    events = step.get("events", [])
    if not events:
        lines.append("  (step has no attached events — nothing to reverse; "
                     "if the table changed, log compensating events "
                     "via apply.py)")
    for ev in reversed(events):
        lines.extend(_reverse_event(eng, ev))
    planlib.reopen(store, step["id"])
    lines.append(f"Reopened plan step {step['id']}")
    g = store.load_game()
    me, res = g["me"], g["me"]["resources"]
    lines.append(f"Tracker now: {me['name']} — 💰 {res['mc']} MC · "
                 f"🏆 {me['tr']} TR · 🌱 {res['plants']} plants · "
                 f"🔥 {res['heat']} heat")
    lines.append("CONFIRM this matches the table")
    return lines


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("step",
                       help="reverse a wrongly-applied plan step by label")
    s.add_argument("label", help="plan step id (1a, 2b, …)")
    a = p.parse_args(argv)
    try:
        print("\n".join(reverse_step(Store(), a.label)))
        return 0
    except (EventError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
