"""doctor.py — environment checklist: playable / not, and the next command."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import doctor
from tmlib import GameManager
from test_new_game import SETUP


def minimal_repo(root: Path) -> None:
    """A repo skeleton with tiny but valid data files."""
    (root / "cards").mkdir()
    (root / "cards" / "db.json").write_text(json.dumps({
        "commit": "abc123", "cards": [
            {"name": "Comet", "type": "event"},
            {"name": "Ecoline", "type": "corporation"},
        ]}))
    (root / "board.json").write_text(json.dumps({
        "map": "tharsis", "spaces": [{"id": "C4"}, {"id": "C5"}]}))
    (root / "scripts").mkdir()


class TestChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        minimal_repo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_python_minimum(self):
        self.assertTrue(doctor.check_python((3, 10, 0)).ok)
        self.assertTrue(doctor.check_python((3, 14, 3)).ok)
        self.assertFalse(doctor.check_python((3, 9, 6)).ok)

    def test_fresh_clone_is_playable_and_suggests_setup(self):
        report = doctor.diagnose(self.root)
        self.assertTrue(report.playable, report.render())
        self.assertIn("setup.py", report.next_command)
        self.assertIn("no active session", report.render())

    def test_data_counts_reported(self):
        text = doctor.diagnose(self.root).render()
        self.assertIn("2 cards", text)
        self.assertIn("2 spaces", text)

    def test_missing_db_not_playable(self):
        (self.root / "cards" / "db.json").unlink()
        report = doctor.diagnose(self.root)
        self.assertFalse(report.playable)
        self.assertIn("✗", report.render())

    def test_corrupt_board_not_playable(self):
        (self.root / "board.json").write_text("{not json")
        self.assertFalse(doctor.diagnose(self.root).playable)

    def test_active_session_named_and_advise_suggested(self):
        GameManager(self.root, today="2031-01-01").start(SETUP)
        report = doctor.diagnose(self.root)
        self.assertTrue(report.playable)
        self.assertIn("2031-01-01-game1", report.render())
        self.assertIn("advise.py --brief", report.next_command)

    def test_dangling_state_link_flagged(self):
        (self.root / "state").symlink_to(self.root / "games" / "gone")
        report = doctor.diagnose(self.root)
        self.assertFalse(report.playable)
        self.assertIn("dangling", report.render())
        self.assertIn("rm state", report.next_command)

    def test_legacy_state_directory_flagged(self):
        (self.root / "state").mkdir()
        report = doctor.diagnose(self.root)
        self.assertFalse(report.playable)
        self.assertIn("real directory", report.render())

    def test_vendor_absent_is_optional(self):
        report = doctor.diagnose(self.root)
        self.assertTrue(report.playable)
        self.assertIn("vendor_bootstrap.sh", report.render())

    def test_vendor_present_reports_extractable(self):
        manifest = (self.root / "vendor" / "terraforming-mars" / "src" /
                    "server" / "cards" / "StandardCardManifests.ts")
        manifest.parent.mkdir(parents=True)
        manifest.write_text("export const BASE_CARD_MANIFEST = {}")
        text = doctor.diagnose(self.root).render()
        self.assertIn("extract_cards.py", text)
        self.assertNotIn("vendor_bootstrap.sh", text)

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_unwritable_games_dir_not_playable(self):
        games = self.root / "games"
        games.mkdir()
        games.chmod(0o500)
        try:
            self.assertFalse(doctor.diagnose(self.root).playable)
        finally:
            games.chmod(0o700)


class TestCli(unittest.TestCase):
    def test_exit_zero_on_this_repo(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "doctor.py")],
                           capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Python", r.stdout)
        self.assertIn("Next:", r.stdout)

    def test_exit_one_on_broken_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "doctor.py"),
                                "--root", tmp], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
