#!/usr/bin/env python3
"""Test runner with two lanes, the fast one parallel across cores.

    test.py            fast lane: every tests/test_*.py, one process per
                       module across all cores (the suite is thousands of
                       ~50 ms tests that each spawn a script; serially that
                       is minutes, in parallel it is seconds)
    test.py slow       slow lane: tests/slow/ — real games against the live
                       practice app on :8080; run before merge/push, NEVER
                       in a play session
    test.py all        both

Exit 0 only when every module passed. Prints one line per failing module
with its tail, then a total.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _run_module(mod: str, start: str) -> tuple[str, int, str]:
    r = subprocess.run([sys.executable, "-m", "unittest", "discover",
                        "-s", start, "-p", f"{mod}.py"],
                       cwd=ROOT, capture_output=True, text=True)
    return mod, r.returncode, r.stdout + r.stderr


def lane(start: Path, parallel: bool) -> bool:
    mods = sorted(p.stem for p in start.glob("test_*.py"))
    t0 = time.time()
    if parallel:
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
            results = list(ex.map(lambda m: _run_module(m, str(start)), mods))
    else:
        results = [_run_module(m, str(start)) for m in mods]
    ran = ok = 0
    failed = []
    for mod, rc, out in results:
        tail = [l for l in out.splitlines() if l.startswith("Ran ")]
        if tail:
            ran += int(tail[-1].split()[1])
        if rc == 0:
            ok += 1
        else:
            failed.append((mod, out))
    for mod, out in failed:
        print(f"✗ {mod}\n" + "\n".join(out.splitlines()[-25:]) + "\n")
    print(f"{start.relative_to(ROOT)}: {ran} tests, {ok}/{len(mods)} modules OK, "
          f"{time.time() - t0:.1f}s")
    return not failed


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "fast"
    good = True
    if which in ("fast", "all"):
        good &= lane(TESTS, parallel=True)
    if which in ("slow", "all"):
        good &= lane(TESTS / "slow", parallel=False)
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
