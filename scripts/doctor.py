#!/usr/bin/env python3
"""Environment checklist: is this clone ready to play, and what to run next.

Checks the Python version, the card and board data files, the state/
symlink, the optional vendor/ engine clone and whether games/ is writable.
Prints one ✓/✗ line per check (○ = optional item absent) and a "Next:"
line. Exit 0 when the harness is playable, 1 otherwise.

    python3 scripts/doctor.py [--root PATH]
"""
import tmlib
import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

MIN_PYTHON = (3, 10)      # PEP 604 unions are evaluated at import time
ROOT = Path(__file__).resolve().parent.parent
VENDOR_MANIFEST = Path("src/server/cards/StandardCardManifests.ts")


@dataclass
class Check:
    ok: bool
    text: str
    required: bool = True

    def line(self) -> str:
        mark = "✓" if self.ok else ("✗" if self.required else "○")
        return f"{mark} {self.text}"


@dataclass
class Report:
    checks: list = field(default_factory=list)
    next_command: str = ""

    @property
    def playable(self) -> bool:
        return all(c.ok for c in self.checks if c.required)

    def render(self) -> str:
        lines = [c.line() for c in self.checks]
        lines.append("")
        lines.append("Ready to play." if self.playable
                     else "Not playable yet — fix the ✗ items above.")
        lines.append(f"Next: {self.next_command}")
        return "\n".join(lines)


# ── individual checks ─────────────────────────────────────────

def check_python(version=None) -> Check:
    v = tuple(version or sys.version_info[:3])
    shown = ".".join(str(x) for x in v[:3])
    need = ".".join(str(x) for x in MIN_PYTHON)
    if v[:2] >= MIN_PYTHON:
        return Check(True, f"Python {shown} (minimum {need})")
    return Check(False, f"Python {shown} is too old — need {need} or newer")


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_db(root: Path) -> Check:
    path = root / "cards" / "db.json"
    if not path.exists():
        return Check(False, "cards/db.json missing — run scripts/vendor_bootstrap.sh "
                            "then scripts/extract_cards.py")
    try:
        db = _load_json(path)
        cards = db["cards"]
        corps = sum(1 for c in cards if c.get("type") == "corporation")
        return Check(True, f"cards/db.json: {len(cards)} cards "
                           f"({corps} corporations), engine commit "
                           f"{str(db.get('commit', '?'))[:10]}")
    except (ValueError, KeyError, TypeError) as e:
        return Check(False, f"cards/db.json unreadable: {e}")


def check_board(root: Path) -> Check:
    path = root / "board.json"
    if not path.exists():
        return Check(False, "board.json missing — run scripts/extract_board.py")
    try:
        board = _load_json(path)
        spaces = board["spaces"]
        return Check(True, f"board.json: {board.get('map', '?')} map, "
                           f"{len(spaces)} spaces")
    except (ValueError, KeyError, TypeError) as e:
        return Check(False, f"board.json unreadable: {e}")


def check_state(root: Path) -> tuple[Check, str]:
    """Returns (check, status) with status in none|dangling|legacy|active."""
    link = root / "state"
    if link.is_symlink():
        if link.exists():
            game_dir = link.resolve()
            gen = "?"
            try:
                gen = _load_json(game_dir / "game.json").get("generation", "?")
            except (OSError, ValueError):
                pass
            return (Check(True, f"state/ → active session {game_dir.name} "
                                f"(generation {gen})"), "active")
        return (Check(False, f"state/ is a dangling symlink → {os.readlink(link)}"),
                "dangling")
    if link.exists():
        return (Check(False, "state/ is a real directory (legacy layout) — move "
                             "it into games/ so setup.py can manage the symlink"),
                "legacy")
    return (Check(True, "state/: no active session"), "none")


def check_vendor(root: Path) -> Check:
    vendor = root / "vendor" / "terraforming-mars"
    if not (vendor / VENDOR_MANIFEST).exists():
        return Check(False, "vendor/terraforming-mars absent (optional: needed only "
                            "for the local app and card-db regeneration) — "
                            "scripts/vendor_bootstrap.sh", required=False)
    note = "extract_cards.py / audit_db.py can run"
    try:
        head = subprocess.run(["git", "-C", str(vendor), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=5)
        pinned = str(_load_json(root / "cards" / "db.json").get("commit", ""))
        if head.returncode == 0 and pinned:
            same = head.stdout.strip() == pinned
            note += (", at the pinned commit" if same
                     else f", NOT at the pinned commit ({head.stdout.strip()[:10]}"
                          f" vs {pinned[:10]}) — audit_db.py will report deltas")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return Check(True, f"vendor/terraforming-mars present — {note}",
                 required=False)


def check_games_writable(root: Path) -> Check:
    games = root / "games"
    target = games if games.exists() else root
    if os.access(target, os.W_OK):
        n = sum(1 for d in games.iterdir() if d.is_dir()) if games.exists() else 0
        return Check(True, f"games/ writable ({n} session folders)")
    return Check(False, f"{target} is not writable — sessions cannot be created")


# Empty files a repo legitimately keeps in its root.
_ALLOWED_EMPTY = {".gitkeep", "py.typed", "__init__.py"}


def check_stray_root_files(root: Path) -> Check:
    """Empty files loose in the repository root — advisory.

    Two malformed plan submissions in one recorded game (shell quoting)
    created EIGHT empty untracked files in the root. They were caught by eye
    before the commit; this catches the next one for free. Never required:
    an empty stray file cannot affect a game in progress.
    """
    strays = sorted(p.name for p in Path(root).iterdir()
                    if p.is_file() and p.name not in _ALLOWED_EMPTY
                    and not p.name.startswith(".") and p.stat().st_size == 0)
    if not strays:
        return Check(True, "no stray empty files in the repo root",
                     required=False)
    shown = ", ".join(strays[:8]) + (" …" if len(strays) > 8 else "")
    return Check(False, f"{len(strays)} empty file(s) loose in the repo root "
                        f"({shown}) — likely a malformed heredoc; delete them",
                 required=False)


def check_setup_coverage(root: Path) -> Check:
    """Does the ACTIVE session ask for data we do not ship? Advisory.

    cards/db.json is base + corporateEra; board.json is Tharsis. A game set
    up with Prelude or on Hellas only fails in play, which is the worst
    moment to find out.
    """
    path = Path(root) / "state" / "setup.json"
    try:
        setup = json.loads(path.read_text())
    except (OSError, ValueError):
        return Check(True, "no active session to check for data coverage",
                     required=False)
    warnings = tmlib.setup_coverage_warnings(setup)
    if not warnings:
        exp = ", ".join(setup.get("expansions") or [])
        return Check(True, f"session data covered ({exp}, "
                           f"{setup.get('map', 'tharsis')} map)", required=False)
    return Check(False, "session exceeds shipped data — " + " | ".join(warnings),
                 required=False)


# ── assembly ──────────────────────────────────────────────────

def diagnose(root: Path) -> Report:
    root = Path(root)
    state_check, status = check_state(root)
    report = Report(checks=[
        check_python(),
        check_db(root),
        check_board(root),
        state_check,
        check_vendor(root),
        check_games_writable(root),
        check_stray_root_files(root),
        check_setup_coverage(root),
    ])
    if status == "dangling":
        report.next_command = ("rm state  # then python3 scripts/setup.py "
                               "(or python3 scripts/session.py list)")
    elif status == "legacy":
        report.next_command = "mv state games/legacy-state  # then python3 scripts/setup.py"
    elif not report.playable:
        report.next_command = "fix the ✗ items, then re-run python3 scripts/doctor.py"
    elif status == "active":
        report.next_command = ("python3 scripts/advise.py --brief  "
                               "# or: python3 scripts/session.py end --note '…'")
    else:
        report.next_command = "python3 scripts/setup.py  # start a game session"
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT,
                    help="repo root to inspect (default: this checkout)")
    a = ap.parse_args(argv)
    report = diagnose(a.root)
    print(report.render())
    return 0 if report.playable else 1


if __name__ == "__main__":
    sys.exit(main())
