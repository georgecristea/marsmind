#!/usr/bin/env python3
"""Narrator assembler: finished game folder → narrator input bundle.

The narrator (agents/narrator.md) turns this into games/<dir>/saga.md
(per-player stories) and insights.md. This script only assembles facts —
all prose is the narrator's job.
"""
import argparse
import json
import sys
from pathlib import Path


class NarrateError(Exception):
    pass


def build_bundle(game_dir: str | Path) -> str:
    game_dir = Path(game_dir)
    setup = json.loads((game_dir / "setup.json").read_text())
    game = json.loads((game_dir / "game.json").read_text())
    log = (game_dir / "log.md").read_text()
    if "endedAt" not in setup:
        raise NarrateError(
            f"{game_dir.name} has not ended — run scripts/session.py end first")

    timelines = []
    me = game["me"]
    me_cards = ", ".join(f"{c['name']} (g{c['gen']})" for c in me["playedCards"]) or "—"
    timelines.append(f"- {me['name']} [{me.get('corporation') or 'corp?'}] "
                     f"TR {me['tr']}, tiles {me['tiles']}, "
                     f"milestones {me['milestones'] or '—'}: {me_cards}")
    for name, o in game["opponents"].items():
        cards = ", ".join(f"{c['name']} (g{c['gen']})" for c in o["playedCards"]) or "—"
        timelines.append(f"- {name} [{o.get('corporation') or 'corp?'}] "
                         f"TR {o['tr']}, tiles {o['tiles']}: {cards}")

    return "\n".join([
        f"# NARRATOR BUNDLE — {game_dir.name}",
        f"Played {setup.get('startedAt')} → {setup['endedAt']}, "
        f"{setup['playerCount']} players "
        f"({', '.join(p['name'] + '=' + p['color'] for p in setup['players'])})",
        f"RESULT: {setup.get('result', 'not recorded')}",
        f"Final generation: {game['generation']}; globals {game['globals']}",
        "\n## Per-player card timelines",
        *timelines,
        "\n## Full game log",
        log,
        "\n## Narrator contract (agents/narrator.md)",
        "For EACH player write (1) a short story — epic but warm, personalized:",
        "their corporation's character, signature plays, dramatic moments —",
        "and (2) an insight report incl. their best unplayed line and one",
        "improvement. Never invent events not in the log. Output files:",
        f"{game_dir}/saga.md and {game_dir}/insights.md.",
    ])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game_dir", nargs="?", default=None,
                   help="games/<dir>; default: most recently ended game")
    a = p.parse_args()
    game_dir = a.game_dir
    if game_dir is None:
        ended = [d for d in sorted(Path("games").iterdir())
                 if (d / "setup.json").exists()
                 and "endedAt" in json.loads((d / "setup.json").read_text())]
        if not ended:
            print("ERROR: no finished games found", file=sys.stderr)
            return 1
        game_dir = ended[-1]
    try:
        print(build_bundle(game_dir))
        return 0
    except (NarrateError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
