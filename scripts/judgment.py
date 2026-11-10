#!/usr/bin/env python3
"""The "judgment" block of state/setup.json — how often the advisor runs a
judgment sweep over incoming opponent events, and who executes plan steps.

  level      every | per-opponent | after-k | triggers-only
             every: a sweep after every event; per-opponent: once per
             opponent turn; after-k: only after the k-th opponent of the
             round; triggers-only: never on schedule (explicit triggers only).
  k          the opponent index (1-based within a round) for after-k;
             default = opponents - 1 (the seat before the quiet zone).
  quiet_zone true → never sweep during the last opponent before me (the
             sweep would be abandoned when the player speaks).
  executor   manual | assist | auto — auto in app-practice, assist otherwise.
  verbosity  terse | full — terse (DEFAULT, every game mode) holds plan-step
             summaries to a character budget (planlib refuses an over-budget
             step); full lifts the budget for a live human table where the
             player is reading along.

Auto-degrade: two consecutive rounds with a quiet-zone abandonment move the
level one notch down (every → per-opponent → after-k → triggers-only); a
clean round resets the streak. Every change is logged to state/log.md.

CLI:  judgment.py show
      judgment.py set level|k|executor|quiet_zone|verbosity VALUE
      judgment.py degrade [--reason TEXT]
      judgment.py status
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import EventError, Store
import latency

LEVELS = ("every", "per-opponent", "after-k", "triggers-only")
EXECUTORS = ("manual", "assist", "auto")
VERBOSITIES = ("terse", "full")
KEYS = ("level", "k", "quiet_zone", "executor", "verbosity")
DEGRADE_AFTER = 2          # consecutive abandoned rounds before one notch down
STREAK_KEY = "abandonStreak"


def defaults(setup: dict) -> dict:
    """Judgment defaults for a setup dict (no state read)."""
    players = setup.get("players") or []
    opponents = max(0, len(players) - 1)
    mode = setup.get("gameMode", "physical")
    return {
        "level": "every",
        "k": max(1, opponents - 1),
        "quiet_zone": True,
        "executor": "auto" if mode == "app-practice" else "assist",
        "verbosity": "terse",
    }


def _opponents(setup: dict) -> int:
    return max(0, len(setup.get("players") or []) - 1)


def k_warning(setup: dict, k: int) -> str:
    """Warn when an after-k index can never fire.

    `k` is the opponent INDEX that triggers the single after-k sweep, not a
    count. should_sweep() checks the quiet zone FIRST, so a k landing on the
    seat immediately before me (k == opponents) is suppressed before k is
    read — zero scheduled sweeps, silently. Same for k above the count.
    """
    opps = _opponents(setup)
    if opps and int(k) >= opps and setup.get("judgment", {}).get(
            "quiet_zone", True):
        return (f"k={k} is the seat immediately before you at {opps} "
                f"opponent(s), which the quiet zone suppresses — that gives 0 "
                f"scheduled sweeps a round. The last position that still "
                f"fires is k={max(1, opps - 1)}; use `level` (not k) to trade "
                f"information for speed.")
    return ""


def ladder_text(setup: dict) -> str:
    """The speed dial, printed where the player will actually see it."""
    opps = _opponents(setup)
    return (
        "JUDGMENT / SPEED DIAL — most information first, fastest last:\n"
        "  every         (DEFAULT) sweep on every opponent event — maximum "
        "information\n"
        "  per-opponent  one sweep per opponent turn\n"
        f"  after-k       ONE sweep a round, after opponent k (k={max(1, opps - 1)} "
        f"here; k is a POSITION, not a count)\n"
        "  triggers-only no scheduled sweeps; hard triggers still interrupt\n"
        "  change mid-game: python3 scripts/judgment.py set level <name>\n"
        "  quiet_zone=on never sweeps during the seat before you, so no dial "
        "makes the table wait on you")


def load(store: Store) -> dict:
    """The judgment block, defaults filled in for games created without
    one (nothing is written)."""
    setup = store.load_setup()
    block = dict(defaults(setup))
    block.update(setup.get("judgment") or {})
    return block


def _save(store: Store, block: dict) -> None:
    setup = store.load_setup()
    setup["judgment"] = block
    Store._write_json(store.setup_path, setup)


def _log(store: Store, message: str) -> None:
    try:
        gen = store.load_game().get("generation")
    except (FileNotFoundError, ValueError):
        gen = "?"
    store.log(f"G{gen}", message)


def _coerce(key: str, value) -> object:
    if key == "level":
        if value not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, got {value!r}")
        return value
    if key == "executor":
        if value not in EXECUTORS:
            raise ValueError(f"executor must be one of {EXECUTORS}, got {value!r}")
        return value
    if key == "verbosity":
        if value not in VERBOSITIES:
            raise ValueError(
                f"verbosity must be one of {VERBOSITIES}, got {value!r}")
        return value
    if key == "k":
        try:
            k = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"k must be a positive integer, got {value!r}")
        if k < 1:
            raise ValueError(f"k must be ≥ 1, got {k}")
        return k
    if key == "quiet_zone":
        if isinstance(value, bool):
            return value
        s = str(value).strip().lower()
        if s in ("true", "yes", "on", "1"):
            return True
        if s in ("false", "no", "off", "0"):
            return False
        raise ValueError(f"quiet_zone must be true|false, got {value!r}")
    raise ValueError(f"unknown judgment key {key!r} (one of {KEYS})")


def set_value(store: Store, key: str, value, warn=print) -> dict:
    """Set one key (validated), persist, log. Returns the new block.

    A `k` that the quiet zone would suppress is WARNED about rather than
    silently accepted: it would leave zero scheduled sweeps a round.
    """
    new = _coerce(key, value)
    block = load(store)
    if key == "k":
        setup = dict(store.load_setup())
        setup["judgment"] = block
        msg = k_warning(setup, new)
        if msg and warn:
            warn(f"⚠ {msg}")
    old = block.get(key)
    block[key] = new
    _save(store, block)
    if old != new:
        _log(store, f"judgment {key}: {old} → {new}")
    return block


def should_sweep(store: Store, opp_index: int, opps_total: int,
                 is_last_before_me: bool, boundary: bool = True) -> bool:
    """Schedule rule for one incoming opponent event.

    opp_index: 1-based index of the acting opponent within the round;
    opps_total: opponents in the round; is_last_before_me: the quiet zone;
    boundary: the event is an opponent-turn boundary (per-opponent sweeps
    only there; every-level callers may pass any event).
    """
    j = load(store)
    if is_last_before_me and j.get("quiet_zone", True):
        return False
    level = j.get("level", "every")
    if level == "every":
        return True
    if level == "per-opponent":
        return bool(boundary)
    if level == "after-k":
        return opp_index == int(j.get("k", 1))
    return False                                   # triggers-only


def degrade(store: Store, reason: str = "") -> str:
    """One notch down the ladder; logs the change. Returns the new level
    (unchanged at the floor)."""
    block = load(store)
    level = block["level"]
    i = LEVELS.index(level)
    if i == len(LEVELS) - 1:
        return level
    new = LEVELS[i + 1]
    block["level"] = new
    _save(store, block)
    _log(store, f"judgment degraded {level} → {new}"
         + (f" — {reason}" if reason else ""))
    return new


def record_clean_round(store: Store) -> None:
    """A round with no quiet-zone abandonment resets the streak."""
    block = load(store)
    if block.get(STREAK_KEY):
        block[STREAK_KEY] = 0
        _save(store, block)


def auto_degrade(store: Store) -> str | None:
    """Degrade once when the abandonment streak reaches DEGRADE_AFTER;
    the streak restarts from 0. Returns the new level or None."""
    block = load(store)
    if int(block.get(STREAK_KEY) or 0) < DEGRADE_AFTER:
        return None
    block[STREAK_KEY] = 0
    _save(store, block)
    return degrade(store, f"{DEGRADE_AFTER} consecutive rounds with a "
                          "quiet-zone abandonment")


def record_abandonment(store: Store, auto: bool = True) -> dict:
    """A round in which a sweep was abandoned. Returns {"streak", "degraded"}
    (degraded = the new level when auto-degrade fired, else None)."""
    block = load(store)
    streak = int(block.get(STREAK_KEY) or 0) + 1
    block[STREAK_KEY] = streak
    _save(store, block)
    degraded = auto_degrade(store) if auto else None
    return {"streak": streak, "degraded": degraded}


def status(store: Store) -> str:
    """One line: parameters + the sweep latency from the digest."""
    j = load(store)
    d = latency.digest(latency.path_for(store))
    s = d["phases"].get("sweep")
    p50 = f"{s['p50']:.0f}ms" if s else "-"
    p95 = f"{s['p95']:.0f}ms" if s else "-"
    return (f"judgment: level={j['level']} k={j['k']} "
            f"quiet_zone={'on' if j.get('quiet_zone', True) else 'off'} "
            f"executor={j['executor']} verbosity={j['verbosity']} | sweep p50={p50} p95={p95} "
            f"abandonments={d['quiet_zone_abandonments']}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print the judgment block as JSON")
    s = sub.add_parser(
        "set", help="set level | k | executor | quiet_zone | verbosity")
    s.add_argument("key", choices=KEYS)
    s.add_argument("value")
    d = sub.add_parser("degrade", help="one notch down the schedule ladder")
    d.add_argument("--reason", default="", help="logged with the change")
    sub.add_parser("status", help="one-line status incl. sweep latency")
    a = p.parse_args(argv)
    store = Store()
    try:
        if a.cmd == "show":
            print(json.dumps(load(store), indent=2))
        elif a.cmd == "set":
            block = set_value(store, a.key, a.value)
            print(f"judgment {a.key} = {block[a.key]}")
        elif a.cmd == "degrade":
            before = load(store)["level"]
            after = degrade(store, a.reason)
            print(f"judgment level: {before} → {after}"
                  if before != after else f"judgment level already at floor: {after}")
        elif a.cmd == "status":
            print(status(store))
        return 0
    except (ValueError, EventError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
