"""Board renderer: SVG map of current state with target-hex highlight."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine
from test_new_game import SETUP
import render_board


class TestRenderBoard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_svg_has_61_hexes_and_grid_labels(self):
        svg = render_board.render(self.store.load_game())
        self.assertEqual(svg.count('class="hex"'), 61)
        self.assertIn(">A<", svg)     # row labels A..I
        self.assertIn(">I<", svg)
        self.assertIn("E1", svg)      # per-hex grid ref exists

    def test_grid_label_stable_scheme(self):
        # row A = top (y 0), numbering left→right within row, 1-based
        self.assertEqual(render_board.grid_label({"y": 0, "x": 4}), "A1")
        self.assertEqual(render_board.grid_label({"y": 4, "x": 0}), "E1")
        self.assertEqual(render_board.grid_label({"y": 8, "x": 8}), "I5")

    def test_highlight_ring_on_target(self):
        svg = render_board.render(self.store.load_game(), highlight="28")
        self.assertIn('class="target"', svg)
        self.assertEqual(svg.count('class="target"'), 1)

    def test_occupied_tiles_drawn_with_player_color(self):
        self.eng.place("Anna", "ocean", "13")
        svg = render_board.render(self.store.load_game())
        self.assertIn("OCEAN", svg.upper())
        # occupied hex marked
        self.assertIn('class="tile', svg)

    def test_names_and_bonuses_visible(self):
        svg = render_board.render(self.store.load_game())
        self.assertIn("Noctis", svg)
        self.assertIn("🌱🌱", svg)    # 2-plant bonus glyph

    def test_describe_names_landmark_and_grid(self):
        d = render_board.describe("28", self.store.load_game())
        self.assertIn(render_board.grid_label(
            next(s for s in render_board.SPACES.values() if s["id"] == "28")), d)
        self.assertIn("ocean", d.lower())

    def test_describe_importable_with_bonus_and_adjacency(self):
        # describe() is the single source of landmark directions: grid ref,
        # bonus icons, named neighbours, and occupied-neighbour tiles.
        from render_board import describe
        self.eng.place("Anna", "city", "39")       # neighbour of 30
        d = describe("30", self.store.load_game())
        self.assertIn(render_board.grid_label(render_board.SPACES["30"]), d)
        self.assertIn("land hex", d)
        self.assertIn("bonus: 🌱 🌱", d)           # 2-plant bonus icons
        self.assertIn("next to", d)                # named-neighbour phrase
        self.assertIn("Noctis City", d)
        self.assertIn("adjacent tiles: Anna's city", d)


class TestPlacementBanner(unittest.TestCase):
    """The placement instruction is baked INTO the map
    image so phone readers never see the map and the text apart."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.game = self.store.load_game()

    def tearDown(self):
        self.tmp.cleanup()

    def test_app_label_skips_letter_I(self):
        # The online app labels rows A..H then J (no I). Our grid_label
        # keeps I for every other caller; app_label is the banner's ref.
        for y, letter in enumerate("ABCDEFGHJ"):
            sp = next(s for s in render_board.SPACES.values() if s["y"] == y)
            self.assertTrue(render_board.app_label(sp).startswith(letter),
                            (y, letter, render_board.app_label(sp)))
        self.assertEqual(render_board.app_label(render_board.SPACES["38"]), "F1")
        self.assertEqual(render_board.grid_label(render_board.SPACES["60"]), "I2")
        self.assertEqual(render_board.app_label(render_board.SPACES["60"]), "J2")

    def test_title_drawn_into_svg_banner(self):
        svg = render_board.render(self.game, highlight="38",
                                  title="3b — CITY on F1 (land hex). +1 plant")
        self.assertIn('class="banner"', svg)
        self.assertIn("3b — CITY on F1 (land hex). +1 plant", svg)
        # banner sits on top: its text precedes the first hex
        self.assertLess(svg.index('class="banner"'), svg.index('class="hex"'))
        # and it never overlaps the board — the board shifts down
        self.assertIn('class="board"', svg)

    def test_title_wraps_to_two_lines_when_long(self):
        long = ("4a — GREENERY on J2 (land hex, next to Noctis City, "
                "adjacent tiles: Anna's city). +2 steel, +2 MC (1 adjacent ocean)")
        svg = render_board.render(self.game, highlight="60", title=long)
        self.assertGreaterEqual(svg.count('class="banner-line"'), 2)
        self.assertLessEqual(svg.count('class="banner-line"'), 3)
        self.assertIn("&apos;", svg)          # XML-escaped, never raw quote

    def test_compose_title_from_step_tile_space(self):
        t = render_board.compose_title("3b", "city", "38", self.game)
        self.assertTrue(t.startswith("3b — CITY on F1 ("), t)
        self.assertIn("land hex", t)
        self.assertIn("next to Arsia Mons", t)
        self.assertTrue(t.rstrip().endswith("+1 plant"), t)

    def test_compose_title_uses_app_label_and_ocean_gains(self):
        t = render_board.compose_title("2a", "greenery", "60", self.game)
        self.assertTrue(t.startswith("2a — GREENERY on J2 ("), t)
        self.assertNotIn("I2", t)
        self.assertIn("+2 steel", t)
        self.eng.place("Anna", "ocean", "63")        # ocean slot next to 62
        t = render_board.compose_title("2a", "greenery", "62",
                                       self.store.load_game())
        self.assertTrue(t.startswith("2a — GREENERY on J4 ("), t)
        self.assertIn("adjacent tiles: Anna's ocean", t)
        self.assertIn("+2 MC (1 adjacent ocean)", t)

    def test_highlight_marker_is_unmistakable_and_drawn_last(self):
        svg = render_board.render(self.game, highlight="28")
        self.assertIn('class="target"', svg)
        self.assertIn('class="pointer"', svg)          # arrow/marker
        # the ring is drawn AFTER every hex so neighbours never cover it
        self.assertGreater(svg.index('class="target"'), svg.rindex('class="hex"'))
        # thick outline
        ring = svg[svg.index('class="target"'):]
        ring = ring[:ring.index("/>")]
        self.assertIn('stroke-width="8"', ring)

    def test_cli_prints_title_as_last_line_and_writes_svg(self):
        import subprocess
        state = Path(self.tmp.name) / "state"
        out = Path(self.tmp.name) / "board.svg"
        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent
                                 / "scripts" / "render_board.py"),
             "--state", str(state / "game.json"),
             "--setup", str(state / "setup.json"),
             "--highlight", "60", "--step", "2a", "--tile", "greenery",
             "--out", str(out)],
            capture_output=True, text=True, check=True)
        lines = r.stdout.rstrip("\n").split("\n")
        self.assertTrue(lines[-1].startswith("2a — GREENERY on J2 ("), lines)
        self.assertIn(lines[-1], out.read_text())      # baked into the SVG
        # explicit --title wins and is echoed verbatim
        r = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent
                                 / "scripts" / "render_board.py"),
             "--state", str(state / "game.json"),
             "--setup", str(state / "setup.json"),
             "--highlight", "38", "--title", "1a — CITY on F1. go",
             "--out", str(out)],
            capture_output=True, text=True, check=True)
        self.assertEqual(r.stdout.rstrip("\n").split("\n")[-1],
                         "1a — CITY on F1. go")
        self.assertIn("1a — CITY on F1. go", out.read_text())


if __name__ == "__main__":
    unittest.main()


class TestReferenceCard(unittest.TestCase):
    """A standalone board reference the player keeps on the phone: empty
    board, every hex labelled with the APP ref, bonuses + landmarks, legend."""

    def test_reference_needs_no_game_state(self):
        svg = render_board.reference_card()
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("</svg>", svg)

    def test_labels_every_hex_with_app_ref(self):
        svg = render_board.reference_card()
        # app rows skip I: J-row refs present, I-row refs absent
        self.assertIn(">J1<", svg)
        self.assertNotIn(">I1<", svg)
        for ref in ("A1", "B2", "E3", "H1"):
            self.assertIn(f">{ref}<", svg, ref)

    def test_shows_bonuses_landmarks_and_legend(self):
        svg = render_board.reference_card()
        self.assertIn("Noctis", svg)               # a named landmark (wrapped)
        self.assertIn("ocean", svg.lower())        # legend mentions ocean slots
        self.assertIn("REFERENCE", svg.upper())    # titled as a reference card

    def test_no_tiles_drawn(self):
        self.assertNotIn('class="tile"', render_board.reference_card())
