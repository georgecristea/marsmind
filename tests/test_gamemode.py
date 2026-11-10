"""gameMode in setup.json + planlib.game_mode helper.

Modes: physical (default — photos + words) | app-practice (API + sparring)
| app-online (API reads, human opponents). Old games have no gameMode key
and must keep working as physical.
"""
import copy, json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store
from test_new_game import SETUP
import planlib

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# The exact stdin an OLD driver (pre-gameMode) would feed setup.py — the
# new prompts must default gracefully on EOF, never crash.
LEGACY_ANSWERS = "\n".join([
    "Zed", "red", "Anna=green, Felix=blue",
    "", "", "", "", "Anna", "",
]) + "\n"


def run_setup(cwd, stdin):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "setup.py")],
        cwd=cwd, input=stdin, capture_output=True, text=True)


class TestGameModeHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_physical_when_key_absent(self):
        self.store.init(SETUP)                    # old game: no gameMode key
        self.assertEqual(planlib.game_mode(self.store), "physical")

    def test_reads_recorded_mode(self):
        setup = dict(copy.deepcopy(SETUP), gameMode="app-practice")
        self.store.init(setup)
        self.assertEqual(planlib.game_mode(self.store), "app-practice")

    def test_defaults_physical_when_setup_file_missing(self):
        self.assertEqual(planlib.game_mode(self.store), "physical")


class TestSetupCLIGameMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def read_setup(self):
        return json.loads(
            (Path(self.cwd) / "state" / "setup.json").read_text())

    def test_legacy_stdin_defaults_to_physical(self):
        r = run_setup(self.cwd, LEGACY_ANSWERS)
        self.assertEqual(r.returncode, 0, r.stderr)
        setup = self.read_setup()
        self.assertEqual(setup["gameMode"], "physical")
        self.assertNotIn("appUrl", setup)

    def test_records_app_practice_with_url_and_player_id(self):
        answers = LEGACY_ANSWERS + "\n".join([
            "app-practice",              # game mode
            "http://localhost:8080",     # app URL
            "pabc123",                   # my app playerId
        ]) + "\n"
        r = run_setup(self.cwd, answers)
        self.assertEqual(r.returncode, 0, r.stderr)
        setup = self.read_setup()
        self.assertEqual(setup["gameMode"], "app-practice")
        self.assertEqual(setup["appUrl"], "http://localhost:8080")
        me = next(p for p in setup["players"] if p["isMe"])
        self.assertEqual(me["playerId"], "pabc123")

    def test_records_app_online(self):
        answers = LEGACY_ANSWERS + "app-online\n\npxyz\n"
        r = run_setup(self.cwd, answers)
        self.assertEqual(r.returncode, 0, r.stderr)
        setup = self.read_setup()
        self.assertEqual(setup["gameMode"], "app-online")

    def test_invalid_mode_rejected(self):
        answers = LEGACY_ANSWERS + "vr-headset\n"
        r = run_setup(self.cwd, answers)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gameMode", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()


class TestPhysicalPreGameChecklist(unittest.TestCase):
    """Physical-mode setup must PRINT the pre-game
    checklist — the color-calibration ritual reminder is structural,
    not conversational memory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_physical_setup_prints_calibration_reminder(self):
        answers = "\n".join([
            "Zed", "red", "Anna=green, Alex=blue",
            "", "", "", "", "Anna", "",
            "physical",
        ]) + "\n"
        r = run_setup(self.tmp.name, answers)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.lower()
        self.assertIn("calibration", out)          # the 20-second ritual
        self.assertIn("player cubes", out)
        self.assertIn("table-notes", out)          # read the private notes

    def test_app_mode_setup_skips_checklist(self):
        answers = "\n".join([
            "Zed", "red", "Anna=green, Alex=blue",
            "", "", "", "", "Anna", "",
            "app-practice", "", "p123",
        ]) + "\n"
        r = run_setup(self.tmp.name, answers)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("calibration", r.stdout.lower())
