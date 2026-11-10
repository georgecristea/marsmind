"""Grid refs (A1..I5, rows top→bottom, hexes numbered left→right) are what
the online app's log panel prints for every placement ("placed at C4") and
what render_board.py already uses for instructions. `apply.py place`/
`unplace` must accept them directly."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tmlib
from tmlib import Store, Engine, EventError
from test_new_game import SETUP


class TestGridToSpace(unittest.TestCase):
    def test_known_refs_match_render_board_and_the_app(self):
        # Cross-checked against the app's nameMapping (vendor spaces.ts)
        # and render_board.describe() output from real games.
        self.assertEqual(tmlib.grid_to_space("B2"), "09")   # Tharsis Tholus
        self.assertEqual(tmlib.grid_to_space("E5"), "33")
        self.assertEqual(tmlib.grid_to_space("E4"), "32")
        self.assertEqual(tmlib.grid_to_space("A1"), "03")

    def test_case_and_whitespace_tolerant_and_ids_pass_through(self):
        self.assertEqual(tmlib.grid_to_space(" e5 "), "33")
        self.assertEqual(tmlib.grid_to_space("33"), "33")
        self.assertEqual(tmlib.grid_to_space(33), "33")

    def test_bad_ref_raises(self):
        with self.assertRaises(EventError):
            tmlib.grid_to_space("Z9")
        with self.assertRaises(EventError):
            tmlib.grid_to_space("E99")


class TestPlaceAcceptsGridRef(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_place_and_unplace_by_grid_ref(self):
        self.eng.place("Anna", "city", "C4")
        board = self.store.load_game()["board"]
        self.assertIn("17", board)
        self.assertEqual(board["17"]["tile"], "city")
        self.eng.unplace("C4")
        self.assertNotIn("17", self.store.load_game()["board"])


if __name__ == "__main__":
    unittest.main()
