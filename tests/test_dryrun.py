"""dryrun.py — the pre-live-game rehearsal gate (fix-plan W3).

A live game may not start without a green dryrun (AGENTS.md). The unit
surface is the deterministic part: the PLAYBOOK coverage check — every
table-hot verb must have its invocation documented in docs/PLAYBOOK.md,
because --help is forbidden at a live table. The live-game rehearsal
itself (e2e_practice.py) needs a running local server and is exercised
by the e2e suite, not here.
"""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dryrun  # noqa: E402


class TestPlaybookCoverage(unittest.TestCase):
    def test_required_verbs_are_the_live_surface(self):
        # The gate covers every script named in AGENTS.md's live-play
        # sections; a new table-hot script must be added here AND to the
        # PLAYBOOK when it ships.
        for verb in ("setup", "session", "judgment", "advise", "planlib",
                     "turn", "execute", "listen", "apply", "produce",
                     "menu", "clock", "shape", "payback", "research",
                     "endgame", "odds", "score", "verify", "render_board",
                     "evalprotocol", "bugs"):
            self.assertIn(verb, dryrun.REQUIRED_VERBS)

    def test_repo_playbook_covers_everything(self):
        text = (REPO / "docs" / "PLAYBOOK.md").read_text()
        self.assertEqual(dryrun.playbook_gaps(text), [])

    def test_missing_verb_is_named(self):
        text = (REPO / "docs" / "PLAYBOOK.md").read_text()
        gutted = text.replace("payback.py", "XXXX.py")
        self.assertEqual(dryrun.playbook_gaps(gutted), ["payback"])

    def test_empty_playbook_reports_all(self):
        self.assertEqual(dryrun.playbook_gaps(""),
                         sorted(dryrun.REQUIRED_VERBS))


class TestChecklist(unittest.TestCase):
    def test_static_checks_pass_on_this_repo(self):
        report = dryrun.static_checks(REPO)
        self.assertTrue(report["playbook"], report)
        self.assertTrue(report["playbook_gaps"] == [], report)

    def test_missing_playbook_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            report = dryrun.static_checks(Path(td))
            self.assertFalse(report["playbook"])


if __name__ == "__main__":
    unittest.main()
