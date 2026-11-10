#!/usr/bin/env python3
"""Pre-live-game rehearsal gate (fix-plan W3): no live game without green.

    dryrun.py [--url U] [--skip-game] [--gens N]

Three stages, fail-fast, PASS/FAIL summary at the end:
  1. doctor.py            — environment + data coverage, must exit 0.
  2. PLAYBOOK coverage    — every table-hot verb documented in
                            docs/PLAYBOOK.md (--help is forbidden at a
                            live table; a gap here is the bug that made
                            game5's first generations slow).
  3. rehearsal            — e2e_practice.py --gens N --greedy against the
                            local practice server (server.py must be up):
                            corp pick, card buys, plan set, execute turn,
                            listener drain, verify — the same entry points
                            a live game uses, warmed before the table.
                            Skipped with --skip-game (stages 1–2 only).

Exit 0 = green (a live game may start). Non-zero = the table waits.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The live-play surface: every scripts/<verb>.py an advisor may invoke
# table-hot. A new table-hot script ships with a PLAYBOOK entry and a
# line here, in the same commit.
REQUIRED_VERBS = sorted([
    "setup", "session", "judgment", "doctor", "advise", "planlib", "turn",
    "execute", "listen", "apply", "produce", "menu", "clock", "shape",
    "payback", "research", "endgame", "odds", "score", "verify",
    "render_board", "evalprotocol", "bugs", "narrate",
])


def playbook_gaps(text: str) -> list[str]:
    """Verbs with no `<verb>.py` mention in the PLAYBOOK text, sorted."""
    return [v for v in REQUIRED_VERBS if f"{v}.py" not in text]


def static_checks(repo: Path) -> dict:
    """Stage-2 facts: playbook presence + coverage. No judgment, no I/O
    beyond one read."""
    pb = repo / "docs" / "PLAYBOOK.md"
    if not pb.is_file():
        return {"playbook": False, "playbook_gaps": sorted(REQUIRED_VERBS)}
    return {"playbook": True, "playbook_gaps": playbook_gaps(pb.read_text())}


def _run(argv: list[str]) -> int:
    print(f"→ {' '.join(argv)}", flush=True)
    return subprocess.run(argv, cwd=REPO).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=None, help="practice app URL for the rehearsal")
    ap.add_argument("--gens", type=int, default=2, help="rehearsal generations (default 2)")
    ap.add_argument("--skip-game", action="store_true",
                    help="stages 1-2 only (no server needed)")
    args = ap.parse_args()

    results: list[tuple[str, bool, str]] = []

    rc = _run([sys.executable, "scripts/doctor.py"])
    results.append(("doctor", rc == 0, f"exit {rc}"))

    facts = static_checks(REPO)
    ok = facts["playbook"] and not facts["playbook_gaps"]
    detail = ("ok" if ok else
              ("docs/PLAYBOOK.md missing" if not facts["playbook"]
               else f"gaps: {', '.join(facts['playbook_gaps'])}"))
    results.append(("playbook", ok, detail))

    if args.skip_game:
        results.append(("rehearsal", True, "SKIPPED (--skip-game)"))
    elif not all(ok for _, ok, _ in results):
        results.append(("rehearsal", False, "not attempted — earlier stage red"))
    else:
        argv = [sys.executable, "scripts/e2e_practice.py",
                "--gens", str(args.gens), "--greedy"]
        if args.url:
            argv += ["--url", args.url]
        rc = _run(argv)
        results.append(("rehearsal", rc == 0, f"e2e exit {rc}"))

    print("\n== DRYRUN ==")
    red = False
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name}: {detail}")
        red = red or not ok
    print("VERDICT:", "RED — the table waits" if red else
          "GREEN — a live game may start")
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
