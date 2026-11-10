"""narrate.py — assemble a finished game into the narrator's input bundle."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import GameManager, Store, Engine
from test_new_game import SETUP
import narrate


class TestNarrate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        gm = GameManager(self.root, today="2031-03-01")
        self.game_dir = gm.start(SETUP)
        eng = Engine(Store(self.root))
        eng.corp("Zed", "Thorgate", mc=48)
        eng.play("Anna", "Mining Rights")
        eng.res("Zed", "mc", -10) if False else None
        eng.produce()
        gm.end(note="Zed won, 68 VP")

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundle_contains_players_log_and_result(self):
        b = narrate.build_bundle(self.game_dir)
        self.assertIn("Zed won, 68 VP", b)
        self.assertIn("Thorgate", b)
        self.assertIn("Mining Rights", b)     # per-player timeline
        self.assertIn("Anna", b)
        self.assertIn("Game log", b)          # full log included
        self.assertIn("saga.md", b)           # output instructions present
        self.assertIn("epic but warm", b)     # narrator contract inlined

    def test_per_player_timelines_extracted(self):
        b = narrate.build_bundle(self.game_dir)
        self.assertRegex(b, r"Anna \[corp\?\].*: Mining Rights \(g1\)")

    def test_unfinished_game_refused(self):
        gm2 = GameManager(self.root, today="2031-03-02")
        d2 = gm2.start(SETUP)
        with self.assertRaises(narrate.NarrateError):
            narrate.build_bundle(d2)


if __name__ == "__main__":
    unittest.main()
