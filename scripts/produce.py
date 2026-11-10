#!/usr/bin/env python3
"""Production phase: my income + energy→heat, opponents' simulated income,
action-ledger reset, generation + first-player advance.

Before turnover it runs cheap invariant checks: resource/
production floors, global-parameter scales, board ownership. Violations
are REPORTED as ⚠ INVARIANT lines — never abort; a drifted tracker still
gets its production, and the advisor decides what to reconcile.

MODE GATE (D3 / H1a): this is the PHYSICAL table's verb. In app-online /
app-practice the app is the rules engine and `listen.py once` adopts its
"Generation N" line — which already runs Engine.produce exactly once.
Running produce.py on top paid the income a second time and put the
tracker a generation ahead of the app (the Codex game closed generation 2
twice and needed `apply.py gen` + a full sync to recover). So in app
modes it refuses unless `--force "<why>"`, which is logged.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import planlib
from tmlib import Engine, EventError, PARAM_SCALE, Store

APP_MODE_REFUSAL = ("the listener owns turnover in app modes — run "
                    "`listen.py once` (it ingests the app's \"Generation N\" "
                    "line and runs production exactly once); to close the "
                    "generation by hand anyway: produce.py --force \"<why>\"")


def check_invariants(game: dict) -> list[str]:
    """Cheap sanity sweep over game.json. Returns ⚠ INVARIANT lines.

    Non-int values are skipped, unknown shapes tolerated — opponent state
    may grow provenance metadata; this must degrade gracefully, never crash.
    """
    problems: list[str] = []

    def sweep(label: str, pool: dict) -> None:
        for r, v in (pool.get("resources") or {}).items():
            if isinstance(v, int) and v < 0:
                problems.append(f"{label} {r} stock negative ({v})")
        for r, v in (pool.get("production") or {}).items():
            floor = -5 if r == "mc" else 0
            if isinstance(v, int) and v < floor:
                problems.append(
                    f"{label} {r} production below floor {floor} ({v})")

    sweep(game["me"]["name"], game["me"])
    for name, opp in (game.get("opponents") or {}).items():
        if isinstance(opp, dict):
            sweep(name, opp)

    for param, scale in PARAM_SCALE.items():
        v = (game.get("globals") or {}).get(param)
        if not isinstance(v, int) or not scale["min"] <= v <= scale["max"]:
            problems.append(
                f"global {param}={v!r} outside scale "
                f"[{scale['min']}, {scale['max']}]")

    known = {game["me"]["name"], *(game.get("opponents") or {})}
    for sid, tile in (game.get("board") or {}).items():
        owner = tile.get("player") if isinstance(tile, dict) else None
        if owner not in known:
            problems.append(f"board space {sid}: unknown player {owner!r}")

    return [f"⚠ INVARIANT: {p}" for p in problems]


def turnover(store: Store, skip_wgt: str | None = None,
             force: str | None = None) -> str:
    """Invariant check → production → standings (score.py at every
    turnover, because the table has no VP column). Returns the text.

    App modes refuse (see MODE GATE above) unless `force` carries the
    reason, which is logged before the production line."""
    import score
    mode = planlib.game_mode(store)
    if mode in planlib.APP_MODES:
        if not (force or "").strip():
            raise EventError(f"gameMode {mode}: {APP_MODE_REFUSAL}")
        store.log(f"G{store.load_game()['generation']}",
                  f"produce.py --force in {mode} mode: {force}")
    lines = list(check_invariants(store.load_game()))
    lines.append(Engine(store).produce(skip_wgt=skip_wgt))
    game = store.load_game()
    # PRINTED here only: Engine.produce logs the line itself, so every
    # turnover path (CLI, listener, e2e) writes exactly one (item 4a).
    lines.append(score.standings_line(game))
    return "\n".join(lines)


def main() -> int:
    # This script takes NO arguments, but it used to have no parser
    # at all — `produce.py --help` silently ran a real generation turnover
    # mid-game. argparse now owns argv: --help prints, anything else fails.
    ap = argparse.ArgumentParser(
        prog="produce.py",
        description="Run the production phase and advance the generation. "
                    "Running it CHANGES STATE.",
    )
    ap.add_argument("--skip-wgt", default=None, metavar="REASON",
                    help="WGT games only: close the generation without a "
                         "logged World Government step (reason is logged)")
    ap.add_argument("--force", default=None, metavar="WHY",
                    help="app modes only: close the generation by hand even "
                         "though the listener owns turnover (reason is logged)")
    a = ap.parse_args()
    try:
        print(turnover(Store(), skip_wgt=a.skip_wgt, force=a.force))
        return 0
    except (EventError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
