"""Engine validation regressions: heat conversion at max, setup and
milestone validation, duplicate players/aliases, legacy state dir,
single-source constants, hand removal CLI, card-index cache."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError, GameManager, MILESTONES
from test_new_game import SETUP

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestHeatConvertAtMax(Base):
    def test_heat_convert_at_maxed_temp_rejected_without_deduction(self):
        self.eng.sync_global("temperature", 8)
        self.eng.res("Zed", "heat", +10)
        with self.assertRaises(EventError):
            self.eng.convert("Zed", "heat")
        self.assertEqual(self.game()["me"]["resources"]["heat"], 10)  # untouched


class TestSetupValidation(Base):
    def _setup(self, **over):
        s = json.loads(json.dumps(SETUP))
        s.update(over)
        return s

    def new_store(self, setup):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Store(tmp.name), setup

    def test_seating_typo_rejected_at_init(self):
        st, s = self.new_store(self._setup(seatingOrder=["Zed", "Ana", "Felix"]))
        with self.assertRaises(EventError):
            st.init(s)

    def test_first_player_typo_rejected_at_init(self):
        st, s = self.new_store(self._setup(firstPlayerGen1="Ana"))
        with self.assertRaises(EventError):
            st.init(s)

    def test_player_count_bounds(self):
        s = self._setup()
        s["players"] = s["players"][:1]
        s["playerCount"] = 1
        s["seatingOrder"] = ["Zed"]
        s["firstPlayerGen1"] = "Zed"
        st, s = self.new_store(s)
        with self.assertRaises(EventError):
            st.init(s)

    def _six(self, n):
        # The online app allows 6 seats; the harness
        # must accept 6 (and still reject 7).
        colors = ["red", "green", "blue", "yellow", "black", "purple", "orange"]
        names = ["Zed"] + [f"Opp{i}" for i in range(1, n)]
        players = [{"name": nm, "color": colors[i], "isMe": i == 0, "aliases": []}
                   for i, nm in enumerate(names)]
        return self._setup(players=players, playerCount=n, seatingOrder=names,
                           firstPlayerGen1="Zed")

    def test_six_players_accepted(self):
        st, s = self.new_store(self._six(6))
        st.init(s)
        self.assertEqual(len(st.load_game()["opponents"]), 5)

    def test_seven_players_rejected(self):
        st, s = self.new_store(self._six(7))
        with self.assertRaises(EventError):
            st.init(s)

    def test_produce_with_corrupt_first_player_gives_event_error_not_traceback(self):
        g = self.store.load_game()
        g["firstPlayer"] = "Nobody"          # simulate legacy/corrupt state
        self.store.save_game(g)
        with self.assertRaises(EventError):
            self.eng.produce()


class TestDealtDuplicates(Base):
    def test_duplicate_kept_rejected(self):
        self.eng.res("Zed", "mc", +10)
        with self.assertRaises(EventError):
            self.eng.dealt(["A", "B", "C", "D"], kept=["A", "A"])
        self.assertEqual(self.game()["me"]["resources"]["mc"], 10)


class TestMilestoneValidation(Base):
    def test_bogus_milestone_name_rejected(self):
        self.eng.res("Zed", "mc", +10)
        with self.assertRaises(EventError):
            self.eng.milestone("Zed", "Terrformer")
        self.assertEqual(self.game()["me"]["resources"]["mc"], 10)

    def test_case_insensitive_canonicalized(self):
        self.eng.res("Zed", "mc", +10)
        self.eng.tr("Zed", +15)
        self.eng.milestone("Zed", "terraformer")
        self.assertEqual(self.game()["milestonesClaimed"], {"Terraformer": "Zed"})

    def test_milestones_constant_is_tharsis_five(self):
        self.assertEqual(MILESTONES,
                         ("Terraformer", "Mayor", "Gardener", "Builder", "Planner"))


class TestDuplicatePlayers(unittest.TestCase):
    def test_duplicate_names_rejected(self):
        s = json.loads(json.dumps(SETUP))
        s["players"][2]["name"] = "Anna"          # two Annas
        s["seatingOrder"] = ["Zed", "Anna", "Anna"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EventError):
                Store(tmp).init(s)

    def test_duplicate_colors_rejected(self):
        s = json.loads(json.dumps(SETUP))
        s["players"][2]["color"] = "green"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(EventError):
                Store(tmp).init(s)


class TestAlias(Base):
    def test_alias_colliding_with_other_player_rejected(self):
        with self.assertRaises(EventError):
            self.eng.add_alias("Anna", "felix")   # shadows player Felix
        with self.assertRaises(EventError):
            self.eng.add_alias("Anna", "Blue")    # shadows Felix's color

    def test_alias_added_resolves_and_is_logged(self):
        self.eng.add_alias("Anna", "the green one")
        self.assertEqual(self.eng.resolve_player("THE GREEN ONE"), "Anna")
        log = (self.root / "state" / "log.md").read_text()
        self.assertIn("alias", log.lower())
        self.assertIn("the green one", log)


class TestLegacyStateDir(unittest.TestCase):
    def test_real_state_directory_gives_clear_error_no_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()          # legacy real dir, not symlink
            gm = GameManager(root, today="2031-03-01")
            with self.assertRaises(EventError):
                gm.start(SETUP)
            self.assertFalse((root / "games").exists()
                             and any((root / "games").iterdir()))  # no orphan


class TestConstantsSingleSource(unittest.TestCase):
    def test_leaf_scripts_import_tmlib_constants(self):
        import tmlib, payback, endgame, advise as adv, clock as clk
        self.assertIs(payback.KEEP_COST, tmlib.CARD_KEEP_COST)
        self.assertEqual(endgame.ASTEROID, tmlib.STANDARD_PROJECTS["asteroid"])
        self.assertEqual(endgame.AQUIFER, tmlib.STANDARD_PROJECTS["aquifer"])
        self.assertEqual(endgame.GREENERY_SP, tmlib.STANDARD_PROJECTS["greenery"])
        self.assertEqual(endgame.MILESTONE, tmlib.MILESTONE_COST)
        # The standard-project menu lives in menu.py and reads
        # tmlib.STANDARD_PROJECTS directly (advise.py no longer copies it)
        import menu
        self.assertIs(menu.STANDARD_PROJECTS, tmlib.STANDARD_PROJECTS)
        self.assertFalse(hasattr(adv, "STANDARD_PROJECTS"))
        self.assertEqual(clk.TOTALS, {
            p: (s["max"] - s["min"]) // s["step"]
            for p, s in tmlib.PARAM_SCALE.items()})

    def test_no_literal_cost_drift(self):
        import tmlib
        self.assertEqual(tmlib.STANDARD_PROJECTS["city"], 25)  # sanity anchor


class TestHandRemoveCLI(unittest.TestCase):
    def test_hand_remove_removes_all_named_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.init(SETUP)
            def run(*args):
                return subprocess.run(
                    [sys.executable, str(SCRIPTS / "apply.py"), *args],
                    cwd=tmp, capture_output=True, text=True)
            run("hand", "add", "Comet", "Birds", "Insects")
            r = run("hand", "remove", "Comet", "Birds")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(store.load_game()["me"]["hand"], ["Insects"])




class TestCardsIndexCache(unittest.TestCase):
    def test_index_cached_between_lookups(self):
        import cards
        cards.load_db()
        db = cards.load_db()
        self.assertIs(cards._index(db), cards._index(db))


if __name__ == "__main__":
    unittest.main()
