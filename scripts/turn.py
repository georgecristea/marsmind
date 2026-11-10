#!/usr/bin/env python3
"""Composite table verb (kills mechanical round trips).

`turn.py done <labels...> [--note "..."]` does, in ONE process, what used to
take three: mark plan steps done via planlib (applying their events), log an
optional free-text note, then print the tracker's key numbers, the plan
render (threats block + exit + steps — plans are set as {"threats": …, "exit": …, "steps":
[…]}), the engine-derived `available: …` menu line, and the next open
step id as the LAST line (`NEXT: <id>` / `NEXT: none`). All logic is
planlib/tmlib/menu — nothing is duplicated here.

Cue gate: `--confirm "<text>"` passes straight through to planlib —
required when any label is cue-gated (milestone/award/place events or
cueGated:true); one --confirm covers every such label in the call. Without
it planlib refuses the gated label (earlier labels stay committed) and
prints the cue the player must confirm.

Round loop (API play, lane 2):
`turn.py round --opp I --of N [--last-before-me] [--boundary]` — the
per-opponent-event driver: triage annotate → pending triggers →
judgment.should_sweep (level, k, quiet zone) → the `advise.py --sweep`
brief or "SWEEP: no" → one `judgment.status` line, always last.
`turn.py go` — own turn: `scripts/listen.py once` when that script exists
(another lane's; skipped with a note otherwise) → the JUDGMENT warning
when the feed carries unhandled triggers (the blocking `listen.py wait`
sleeps through the opponents' turns, so `go` is the last place the loop
can be stopped from skipping lane 2 silently) → planlib promote (an
in-flight sweep is abandoned, never blocking; a clean round resets the
abandonment streak) → executor hint (`scripts/execute.py --dry-run` when
present) → plan → menu line → NEXT. PHOBOS_SCRIPTS_DIR overrides where
the listener / executor are looked up (tests).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import EventError, Store
import advise
import judgment
import latency
import menu
import planlib
import triage

SCRIPTS_DIR = Path(__file__).resolve().parent
JUDGMENT_MAX = 10                  # pending triggers listed in full by `go`


def _pending(store: Store) -> list[dict]:
    """Unhandled hard triggers in the feed (the listener's verdicts — no
    re-classification, so this stays free on the own-turn path)."""
    feed = triage.feed_path(store)
    if not feed.exists():
        return []
    try:
        game = store.load_game()
    except (FileNotFoundError, ValueError):
        game = None
    return triage.pending(feed, game)


def _judgment_warning(pend: list[dict]) -> list[str]:
    """`go` must never let the loop reach execute with unread triggers: the
    fast path (`listen.py wait` → `turn.py go` → `execute.py`) is asleep
    through every opponent turn, which is why the sweep fired once in
    twelve generations (p7 brief §7.3)."""
    if not pend:
        return []
    shown = pend[:JUDGMENT_MAX]
    out = [f"⚠ JUDGMENT: {len(pend)} unhandled trigger(s) — read these BEFORE "
           "executing this turn:"]
    out += ["  " + row for row in triage.render_pending(shown)]
    if len(pend) > len(shown):
        out.append(f"  … {len(pend) - len(shown)} more (triage.py pending)")
    out.append("  → python3 scripts/advise.py --sweep   (or triage.py handle "
               "<line>… --note \"…\" to dismiss)")
    return out


def _tail(store: Store) -> list[str]:
    """Plan render + the engine-derived menu line + the NEXT line."""
    game = store.load_game()
    lines = []
    try:
        lines.append(planlib.render(store))
    except EventError as e:
        lines.append(f"(plan: {e})")
    lines.append(menu.summary(menu.available_actions(game, store.load_setup())))
    try:
        nxt = planlib.next_step(store)
    except EventError:
        nxt = None
    lines.append(f"NEXT: {nxt['id'] if nxt else 'none'}")
    return lines


def round_(store: Store, opp: int, of: int, last_before_me: bool = False,
           boundary: bool = False) -> str:
    """One opponent event has been absorbed: classify it, list what is
    pending, sweep if the schedule says so. Ends with the judgment line."""
    lines = []
    with latency.timed("triage", store=store):
        game, setup = store.load_game(), store.load_setup()
        try:
            plan = planlib.load_plan(store)
        except EventError:
            plan = None
        feed = triage.feed_path(store)
        entries = triage.triage_feed(feed, game, setup, plan) if feed.exists() else []
        pend = [e for e in entries if e.get("trigger") and not e.get("handled")]
    lines.append(f"ROUND: opponent {opp}/{of}"
                 + (" (last before me — quiet zone)" if last_before_me else "")
                 + (" [turn boundary]" if boundary else ""))
    lines.append("PENDING TRIGGERS:")
    lines.extend(triage.render_pending(pend) or ["no pending triggers"])
    if judgment.should_sweep(store, opp, of, last_before_me, boundary=boundary):
        lines.append(advise.build_sweep(store, whose=f"opponent {opp}/{of}"))
    else:
        lines.append("SWEEP: no" + (" (quiet zone)" if last_before_me else
                                    f" (level {judgment.load(store)['level']})")
                     + (" — pending triggers above still need handling"
                        if pend else ""))
    lines.append(judgment.status(store))
    return "\n".join(lines)


def _scripts_dir(scripts_dir=None) -> Path:
    return Path(scripts_dir or os.environ.get("PHOBOS_SCRIPTS_DIR") or SCRIPTS_DIR)


def go(store: Store, scripts_dir=None) -> tuple[str, int]:
    """Own turn: listen once → promote → executor hint → plan → menu → NEXT.
    Returns (text, exit code); a refused promote is reported, not raised."""
    sdir = _scripts_dir(scripts_dir)
    cwd = str(store.state_dir.parent)
    lines, rc = [], 0
    listener = sdir / "listen.py"
    if listener.exists():
        with latency.timed("listen", store=store):
            try:
                r = subprocess.run([sys.executable, str(listener), "--state",
                                    str(store.state_dir), "once"],
                                   cwd=cwd, capture_output=True, text=True,
                                   timeout=120)
                out = (r.stdout.strip() or r.stderr.strip()).splitlines()
                lines.append("LISTEN: " + (out[-1] if out else "(no output)")
                             + ("" if r.returncode == 0 else f" [exit {r.returncode}]"))
            except (OSError, subprocess.SubprocessError) as e:
                lines.append(f"LISTEN: failed ({e}) — absorb the app log by hand")
    else:
        lines.append("LISTEN: scripts/listen.py absent — skipped (absorb the "
                     "app log by hand: apply.py batch)")
    lines.extend(_judgment_warning(_pending(store)))
    try:
        plan = planlib.load_plan(store)
    except EventError as e:
        plan = None
        lines.append(f"PROMOTE: {e}")
    if plan is not None:
        # a patch that never landed means the steps below are NOT what the
        # advisor decided — say it before anything else touches them, and
        # break the `turn.py go && execute.py` chain right here (P8 #10)
        failed = planlib.patch_failed_lines(plan)
        if failed:
            lines.extend(failed)
            rc = 1
        if plan.get("draft"):
            clean = not planlib.sweep_flag_path(store).exists()
            with latency.timed("promote", store=store) as t:
                try:
                    lines.append(f"PROMOTE: {planlib.promote(store)}")
                    if clean:
                        judgment.record_clean_round(store)
                except EventError as e:
                    t.note = "refused"
                    rc = 1
                    lines.append(f"PROMOTE REFUSED: {e}")
                    lines.append("→ patch the named step(s): planlib.py patch "
                                 "(JSON on stdin), then turn.py go again")
        else:
            lines.append("PROMOTE: plan already live — nothing to promote")
    ex = judgment.load(store).get("executor", "assist")
    executor = sdir / "execute.py"
    if executor.exists():
        lines.append(f"EXECUTE: scripts/execute.py --dry-run  (executor={ex}; "
                     f"drop --dry-run only when executor=auto)")
    else:
        lines.append(f"EXECUTE: scripts/execute.py absent — execute by hand, "
                     f"then turn.py done <labels>  (executor={ex})")
    lines.extend(_tail(store))
    return "\n".join(lines), rc


def run(store: Store, labels: list[str], note: str | None = None,
        apply_events: bool = True, force: str | None = None,
        confirm: str | None = None) -> str:
    ids = planlib.mark_done_many(store, labels, apply_events=apply_events,
                                 force=force, confirm=confirm)
    lines = [f"Marked done: {', '.join(ids)}"]
    game = store.load_game()
    gen = game["generation"]
    if note:
        store.log(f"G{gen}", note)
        lines.append(f"Noted: {note}")
    me, res = game["me"], game["me"]["resources"]
    lines.append(f"G{gen} — {me['name']}: 💰 {res['mc']} MC · "
                 f"🏆 {me['tr']} TR · 🌱 {res['plants']} plants · "
                 f"🔥 {res['heat']} heat")
    lines.append(planlib.render(store))
    # The engine-derived menu after EVERY done — the GO message ends
    # with this line ("available: NRB microbe, Terraformer claim (8), pass").
    import menu
    lines.append(menu.summary(menu.available_actions(game, store.load_setup())))
    nxt = planlib.next_step(store)
    lines.append(f"NEXT: {nxt['id'] if nxt else 'none'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".", help="repo root (state/ = active game)")
    p.add_argument("--state", default=None,
                   help="a state folder instead of state/ (a seat's own — "
                        "session.py seat-init); passed on to listen.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("done", help="mark labels done + note + tracker "
                                    "numbers + plan + NEXT, in one call")
    d.add_argument("labels", nargs="+",
                   help="step labels (1a 1b…) or whole turn numbers, in order")
    d.add_argument("--note", default=None, help="free-text log entry, "
                   "recorded like `apply.py note` in the same process")
    d.add_argument("--no-apply", action="store_true",
                   help="events already logged manually; only tick the boxes")
    d.add_argument("--force", default=None,
                   help="pass-gate override: reason each remaining item is bad")
    d.add_argument("--confirm", default=None, metavar="TEXT",
                   help="cue gate: the player confirmed the cue (what they SEE) "
                        "for the milestone/award/place or cueGated labels in "
                        "this call; one --confirm covers all of them")
    r = sub.add_parser("round", help="per-opponent-event driver: triage → "
                                     "pending triggers → sweep or 'SWEEP: no' "
                                     "→ judgment status line")
    r.add_argument("--opp", type=int, required=True,
                   help="1-based index of the acting opponent within the round")
    r.add_argument("--of", type=int, required=True, help="opponents in the round")
    r.add_argument("--last-before-me", action="store_true",
                   help="this opponent acts right before me (quiet zone)")
    r.add_argument("--boundary", action="store_true",
                   help="the event ends this opponent's turn (per-opponent "
                        "sweeps fire only here)")
    sub.add_parser("go", help="own turn: listen once (if scripts/listen.py) → "
                              "promote → executor hint → plan → menu → NEXT")
    a = p.parse_args(argv)
    store = Store(a.root, state_dir=a.state)
    try:
        if a.cmd == "round":
            print(round_(store, a.opp, a.of, last_before_me=a.last_before_me,
                         boundary=a.boundary))
            return 0
        if a.cmd == "go":
            text, rc = go(store)
            print(text)
            return rc
        print(run(store, a.labels, note=a.note,
                  apply_events=not a.no_apply, force=a.force,
                  confirm=a.confirm))
        return 0
    except (EventError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
