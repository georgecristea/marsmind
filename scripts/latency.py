#!/usr/bin/env python3
"""Table-hot latency instrumentation.

Every phase of the advisor loop (listen, triage, sweep, promote, execute,
plan, research, other) marks its start and end in state/latency.jsonl —
one JSON object per line: {"ts", "phase", "edge", "gen", "note"}. A mark
whose note is "abandoned" records a sweep dropped because the player
spoke (the quiet zone). `digest` pairs start/end marks per phase and
reports count / p50 / p95 / max in milliseconds plus the abandonment
count; session.py end prints and archives it.

Practice seats have no Store: `mark_path(path, …)` appends the SAME shape to
any file (sparring.py writes seats/<pid>/latency.jsonl — `seat_path`), so
one reconstruction reads the advisor's trace and every seat's alike.

CLI:  latency.py mark <phase> start|end [--note TEXT]
      latency.py digest
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import Store

PHASES = ("listen", "triage", "sweep", "promote", "execute", "plan",
          "research", "other")
EDGES = ("start", "end")
ABANDONED = "abandoned"
FILENAME = "latency.jsonl"


SEATS_DIR = "seats"


def path_for(store: Store) -> Path:
    return store.state_dir / FILENAME


def seat_path(pid: str, root: str | Path = ".") -> Path:
    """A practice seat's own store: seats/<pid>/latency.jsonl — the same
    file shape as the advisor's, so one reconstruction reads both."""
    return Path(root) / SEATS_DIR / pid / FILENAME


def _gen(store: Store):
    try:
        return store.load_game().get("generation")
    except (FileNotFoundError, ValueError):
        return None


def _gen_from_dir(directory: Path):
    """The generation of a game.json beside the marks file, if there is one
    (a seat folder built by session.py seat-init carries it)."""
    try:
        return json.loads((directory / "game.json").read_text()).get("generation")
    except (FileNotFoundError, ValueError, OSError):
        return None


def _append(path: Path, phase: str, edge: str, note: str, gen) -> dict:
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}, got {phase!r}")
    if edge not in EDGES:
        raise ValueError(f"edge must be start|end, got {edge!r}")
    entry = {"ts": round(time.time(), 6), "phase": phase, "edge": edge,
             "gen": gen, "note": note}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def mark(phase: str, edge: str, note: str = "", store: Store | None = None,
         gen: int | None = None) -> dict:
    """Append one mark to state/latency.jsonl and return it."""
    store = store or Store()
    return _append(path_for(store), phase, edge, note,
                   gen if gen is not None else _gen(store))


def mark_path(path: str | Path, phase: str, edge: str, note: str = "",
              gen: int | None = None) -> dict:
    """`mark` for a caller without a Store (a practice seat): append one
    mark of the same shape to `path`. `gen` falls back to the generation of
    a game.json beside the file, else null."""
    path = Path(path)
    return _append(path, phase, edge, note,
                   gen if gen is not None else _gen_from_dir(path.parent))


class _Timer:
    """Handle yielded by `timed`: set `.note` before the block ends."""

    def __init__(self, phase: str, note: str):
        self.phase = phase
        self.note = note


@contextmanager
def timed(phase: str, note: str = "", store: Store | None = None):
    """Mark start on entry, end on exit. An exception inside the block ends
    the phase with note "abandoned" (unless the caller set another note)
    and is re-raised."""
    store = store or Store()
    mark(phase, "start", store=store)
    t = _Timer(phase, "")
    try:
        yield t
    except BaseException:
        mark(phase, "end", note=t.note or ABANDONED, store=store)
        raise
    mark(phase, "end", note=t.note or note, store=store)


def read_marks(path: Path) -> list[dict]:
    """All well-formed marks in file order; garbage lines are skipped."""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and "phase" in e and "edge" in e and "ts" in e:
            out.append(e)
    return out


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (q in 0..1) over a sorted list."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    pos = q * (len(values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return float(values[lo] + (values[hi] - values[lo]) * frac)


def empty_digest() -> dict:
    return {"marks": 0, "phases": {}, "quiet_zone_abandonments": 0}


def digest(path: Path) -> dict:
    """Per-phase count / p50 / p95 / max (ms) + abandonment count.
    Missing file → empty digest. Start/end marks are paired in file order
    per phase; an unmatched start is not a duration."""
    marks = read_marks(path)
    if not marks:
        return empty_digest()
    open_start: dict[str, float] = {}
    durations: dict[str, list[float]] = {}
    abandoned = 0
    for e in marks:
        phase, edge = e["phase"], e["edge"]
        try:
            ts = float(e["ts"])
        except (TypeError, ValueError):
            continue
        if e.get("note") == ABANDONED:
            abandoned += 1
        if edge == "start":
            open_start[phase] = ts          # a fresh start supersedes a dangling one
        elif edge == "end" and phase in open_start:
            durations.setdefault(phase, []).append(
                (ts - open_start.pop(phase)) * 1000.0)
    phases = {}
    for phase, ds in durations.items():
        ds.sort()
        phases[phase] = {
            "count": len(ds),
            "p50": round(percentile(ds, 0.50), 3),
            "p95": round(percentile(ds, 0.95), 3),
            "max": round(ds[-1], 3),
        }
    return {"marks": len(marks), "phases": phases,
            "quiet_zone_abandonments": abandoned}


def format_digest(d: dict) -> str:
    """Human lines for the end-of-game printout."""
    lines = [f"⏱ Latency digest ({d['marks']} marks, "
             f"{d['quiet_zone_abandonments']} quiet-zone abandonments)"]
    for phase in PHASES:
        s = d["phases"].get(phase)
        if s:
            lines.append(f"   {phase:<9} n={s['count']:<4} p50={s['p50']:.0f}ms  "
                         f"p95={s['p95']:.0f}ms  max={s['max']:.0f}ms")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mark", help="append a start/end mark for a phase")
    m.add_argument("phase", choices=PHASES)
    m.add_argument("edge", choices=EDGES)
    m.add_argument("--note", default="", help='e.g. "abandoned"')
    sub.add_parser("digest", help="print the per-phase digest as JSON")
    a = p.parse_args(argv)
    store = Store()
    if a.cmd == "mark":
        e = mark(a.phase, a.edge, note=a.note, store=store)
        print(f"{e['phase']} {e['edge']}" + (f" ({e['note']})" if e["note"] else ""))
    elif a.cmd == "digest":
        print(json.dumps(digest(path_for(store)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
