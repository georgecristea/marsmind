#!/usr/bin/env python3
"""N-game evaluation protocol — the private/evals.jsonl ledger.

Fixed harness, ≥10 practice games per configuration: this script keeps
the per-game results (winner, VP margin, session model, notes) and
aggregates them per model, separating strategy quality from deck luck
before the stakes get real.

    python3 scripts/evalprotocol.py record --game games/<date>-game<N> \
        --winner Diana --margin 18 --model fable-5 --notes "milestone race won"
    python3 scripts/evalprotocol.py report

A win is winner == the isMe player of the game dir's setup.json
(captured at record time as "me"); margin is signed VP margin from
the player's perspective (negative = lost by that much).

The ledger is the player's own data and lives OUTSIDE version control:
default private/evals.jsonl (created on first record), overridable with
--ledger PATH or the PHOBOS_EVALS_LEDGER environment variable.

Record format (one JSON object per line):
  {"date": "YYYY-MM-DD", "game": "games/<dir>", "winner": "<name>",
   "me": "<isMe player from setup.json>", "players": <count>,
   "margin": <signed VP>, "model": "<session model>",
   "bots": "<opponent tier>", "notes": "<free text>",
   "shape": {…} | null}

"shape" holds automatic PROCESS metrics computed from the closed game
folder via scripts/shape.py's compute(): generations played, cards
bought per generation (mine / per opponent / field median), MC
production vs the table median, VP slope, and the repeatable-source
inventory. Numbers only — no flags, no judgment (fix-plan DOCTRINE:
scripts compute facts). A folder shape.compute() cannot read refuses
the record and names the escape hatch: --no-shape stores null.
"""
import argparse
import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILE = ROOT / "private" / "evals.jsonl"
ENV_VAR = "PHOBOS_EVALS_LEDGER"


def default_ledger() -> Path:
    """private/evals.jsonl unless PHOBOS_EVALS_LEDGER points elsewhere."""
    override = os.environ.get(ENV_VAR)
    return Path(override) if override else DEFAULT_FILE


def _setup_of(game_dir) -> dict:
    p = Path(game_dir) / "setup.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, TypeError):
        return {}


def _me_from_game(game_dir) -> str | None:
    setup = _setup_of(game_dir)
    return next((pl["name"] for pl in setup.get("players", [])
                 if pl.get("isMe")), None)


def _players_from_game(game_dir) -> int | None:
    return _setup_of(game_dir).get("playerCount")


def shape_metrics(game_dir) -> dict:
    """Process metrics from a closed game folder, via shape.compute() on
    a Store pointed at the folder. Numbers only — the flags (judgment
    triggers for LIVE play) are deliberately not stored."""
    import shape as shapelib
    from tmlib import Store
    m = shapelib.compute(Store(".", state_dir=game_dir))
    return {"gens": m["generation"],
            "cardsBought": m["cardsBought"],
            "mcProd": m["mcProd"],
            "vpSlope": m["vpSlope"],
            "repeatableSources": m["repeatableSources"]}


def record(file, game, winner: str, margin: int, model: str,
           notes: str = "", bots: str = "", players: int | None = None,
           shape: bool = True) -> dict:
    entry = {"date": date.today().isoformat(), "game": str(game),
             "winner": winner, "me": _me_from_game(game),
             "players": players if players is not None
                        else _players_from_game(game),
             "margin": margin, "model": model, "bots": bots, "notes": notes}
    if shape:
        try:
            entry["shape"] = shape_metrics(game)
        except Exception as e:
            raise ValueError(
                f"shape metrics failed for {game} ({type(e).__name__}: {e}) "
                "— fix the folder, or record without process metrics via "
                "--no-shape") from e
    else:
        entry["shape"] = None
    file = Path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load(file) -> list[dict]:
    return [json.loads(line) for line in Path(file).read_text().splitlines()
            if line.strip()]


def _is_win(e: dict) -> bool:
    me, winner = e.get("me"), (e.get("winner") or "").lower()
    return winner == me.lower() if me else winner == "me"


def report(file) -> str:
    file = Path(file)
    if not file.exists():
        return "no evals recorded yet (evalprotocol.py record …)"
    entries = load(file)
    if not entries:
        return "no evals recorded yet (evalprotocol.py record …)"
    # Keyed on (model, players): player count changes game dynamics enough
    # (milestone/award scarcity, game length, tile contention) that mixing
    # 3p and 5p games into one row would misrepresent both.
    by_key: dict[tuple[str, str], list[dict]] = {}
    for e in entries:
        n = e.get("players")
        key = (e.get("model", "?"), f"{n}p" if n else "?p")
        by_key.setdefault(key, []).append(e)
    lines = [f"{'model':<16} {'players':>7} {'games':>5} {'winRate':>8}  "
             f"margin mean/min/max"]
    for model, players in sorted(by_key):
        es = by_key[(model, players)]
        margins = [e["margin"] for e in es]
        wins = sum(1 for e in es if _is_win(e))
        lines.append(
            f"{model:<16} {players:>7} {len(es):>5} {wins / len(es):>8.0%}  "
            f"{statistics.mean(margins):+.1f} / {min(margins):+g} / "
            f"{max(margins):+g}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", "--file", dest="file",
                   default=str(default_ledger()),
                   help=f"ledger path (default private/evals.jsonl, or "
                        f"${ENV_VAR}); parent dirs are created")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record", help="append one game result")
    r.add_argument("--game", required=True, help="games/<date>-gameN dir")
    r.add_argument("--winner", required=True)
    r.add_argument("--margin", type=int, required=True,
                   help="signed VP margin from my perspective")
    r.add_argument("--model", required=True, help="session model name")
    r.add_argument("--players", type=int, default=None,
                   help="player count override (default: read from the "
                        "game dir's setup.json playerCount)")
    r.add_argument("--notes", default="")
    r.add_argument("--bots", default="",
                   help="opponent quality: model-piloted | competitive | "
                        "greedy-v2 | dummy-v1 | human — dummy margins are "
                        "harness validation, NOT strategy evidence")
    r.add_argument("--no-shape", action="store_true",
                   help="record without the automatic process metrics "
                        "(escape hatch for a corrupt/partial game folder); "
                        "the row stores shape: null")
    sub.add_parser("report", help="per-model games, win rate, margin stats")
    a = p.parse_args()
    if a.cmd == "record":
        try:
            entry = record(a.file, a.game, a.winner, a.margin, a.model,
                           notes=a.notes, bots=a.bots, players=a.players,
                           shape=not a.no_shape)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(f"recorded: {json.dumps(entry, ensure_ascii=False)}")
    else:
        print(report(a.file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
