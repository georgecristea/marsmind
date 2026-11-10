"""M1: file persistence + append-only log. Files are the only truth."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, new_game_state
from test_new_game import SETUP


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_writes_setup_game_and_log(self):
        self.store.init(SETUP)
        assert (self.root / "state" / "setup.json").exists()
        assert (self.root / "state" / "game.json").exists()
        assert (self.root / "state" / "log.md").exists()
        game = json.loads((self.root / "state" / "game.json").read_text())
        self.assertEqual(game, new_game_state(SETUP))

    def test_load_returns_what_was_saved(self):
        self.store.init(SETUP)
        game = self.store.load_game()
        game["me"]["resources"]["mc"] = 42
        self.store.save_game(game)
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 42)

    def test_log_appends_one_line_per_event_with_generation(self):
        self.store.init(SETUP)
        self.store.log("G1", "Anna played Mining Rights")
        self.store.log("G1", "Zed: +3 MC")
        lines = (self.root / "state" / "log.md").read_text().splitlines()
        body = [l for l in lines if l.startswith("- ")]
        self.assertEqual(len(body), 2)
        self.assertIn("G1", body[0])
        self.assertIn("Anna played Mining Rights", body[0])
        self.assertIn("Zed: +3 MC", body[1])

    def test_init_refuses_to_overwrite_existing_game(self):
        self.store.init(SETUP)
        with self.assertRaises(FileExistsError):
            self.store.init(SETUP)


if __name__ == "__main__":
    unittest.main()
