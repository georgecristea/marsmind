"""M3: advise.py assembles state + KB + calculators into the advisor brief."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine
from test_new_game import SETUP
import advise


class TestAdvise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        # a mid-game-ish position
        self.eng.corp("Zed", "Thorgate", mc=48)
        self.eng.res("Zed", "heat", +9)
        self.eng.res("Zed", "plants", +3)
        self.eng.prod("Zed", "mc", +4)
        self.eng.hand_add(["Comet", "Birds"])
        self.eng.register_action("Ironworks")
        self.eng.res("Zed", "energy", +4)   # Ironworks: spend 4 energy
        self.eng.use_action("Ironworks")
        self.eng.play("Anna", "Mining Rights")
        self.eng.sync_global("oxygen", 4)

    def tearDown(self):
        self.tmp.cleanup()

    def brief(self):
        return advise.build_brief(self.root, kb_dir=Path(__file__).parent.parent / "strategy")

    def test_brief_contains_exact_state_numbers(self):
        b = self.brief()
        self.assertIn("Thorgate", b)
        self.assertIn("48", b)       # MC balance
        self.assertIn("Comet", b)    # hand in order
        self.assertIn("Mining Rights", b)  # opponent tableau

    def test_brief_includes_available_actions_menu(self):
        b = self.brief()
        self.assertIn("AVAILABLE ACTIONS", b)
        self.assertIn("used this generation: Ironworks", b)   # ✓ used
        self.assertIn("8 heat → temperature", b)   # conversion available (9 heat)
        self.assertIn("available: ", b)            # one-line summary
        self.assertIn("## RACES", b)

    def test_brief_flags_requirement_windows(self):
        b = self.brief()   # oxygen at 4 → max-5% cards expiring
        self.assertIn("O2", b)
        self.assertIn("expir", b.lower())

    def test_brief_includes_clock_estimate(self):
        b = self.brief()
        self.assertIn("end ~gen", b.lower())

    def test_brief_includes_kb_contents(self):
        b = self.brief()
        self.assertIn("Quantified Guide", b)     # 04 loaded
        self.assertIn("three-phase arc", b.lower())  # 02 loaded

    def test_brief_states_output_contract(self):
        b = self.brief()
        self.assertIn("execution trace", b.lower())
        self.assertIn("available actions", b.lower())
        self.assertIn("threats", b.lower())
        self.assertIn("play order", b.lower())


if __name__ == "__main__":
    unittest.main()


class TestActionLedgerCanonicalNames(unittest.TestCase):
    """play() registers a blue action under the
    db spelling, but register/use took the raw string — a differently
    cased `action use` could not find (or duplicated) the entry, and the
    saturation renderer then showed the db-spelled entry as AVAILABLE."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.eng.corp("Zed", "Thorgate", mc=48)

    def tearDown(self):
        self.tmp.cleanup()

    def test_use_action_finds_entry_registered_by_play_under_db_spelling(self):
        self.eng.hand_add(["Inventors' Guild"])
        self.eng.play("Zed", "inventors' guild")
        self.eng.use_action("INVENTORS' GUILD")
        ledger = self.store.load_game()["me"]["actionsThisGen"]
        self.assertEqual(list(ledger), ["Inventors' Guild"])
        self.assertTrue(ledger["Inventors' Guild"]["used"])
        import menu
        g = self.store.load_game()
        items = menu.available_actions(g, self.store.load_setup())
        self.assertNotIn("Inventors' Guild", [i["name"] for i in items])
        self.assertIn("used this generation: Inventors' Guild",
                      menu.render(items, g))

    def test_register_action_canonicalises_and_never_duplicates(self):
        self.eng.register_action("ironworks")
        self.eng.register_action("Ironworks")
        self.assertEqual(list(self.store.load_game()["me"]["actionsThisGen"]),
                         ["Ironworks"])

class TestFreeLandInBrief(unittest.TestCase):
    """Free land is a fourth clock in the brief."""

    FIX = Path(__file__).parent / "fixtures" / "endgame-5p"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.kb = Path(__file__).parent.parent / "strategy"

    def tearDown(self):
        self.tmp.cleanup()

    def fill_board(self, leave: int):
        """Occupy every land hex but `leave` (test-only state write)."""
        import tmlib
        land = [sid for sid, sp in tmlib.Engine._board().items()
                if sp.get("type") == "land" and not sp.get("offMap")]
        g = self.store.load_game()
        g["board"] = {sid: {"tile": "city", "player": "Anna"}
                      for sid in land[:len(land) - leave]}
        self.store.save_game(g)

    def test_header_shows_free_land_on_fresh_board(self):
        b = advise.build_brief(self.root, kb_dir=self.kb)
        self.assertIn("Free land: 49", b)
        self.assertNotIn("BOARD NEARLY FULL", b)

    def test_header_warns_at_six_or_fewer(self):
        self.fill_board(leave=6)
        b = advise.build_brief(self.root, kb_dir=self.kb)
        self.assertIn("Free land: 6 ⚠ BOARD NEARLY FULL — tile cards and plant "
                      "production are dead weight; pivot to card VP", b)

    def menu_names(self, kind):
        import menu
        g = self.store.load_game()
        return [i["name"] for i in menu.available_actions(g, self.store.load_setup())
                if i["kind"] == kind]

    def test_plant_conversion_not_available_without_a_hex(self):
        # menu.py derives free land from the tracker's board occupancy
        self.fill_board(leave=0)
        self.eng.res("Zed", "plants", +9)
        self.assertNotIn("plants", self.menu_names("convert"))

    def test_plant_conversion_available_with_a_hex(self):
        self.fill_board(leave=1)
        self.eng.res("Zed", "plants", +9)
        self.assertIn("plants", self.menu_names("convert"))

    def test_sp_greenery_and_city_dead_without_a_hex(self):
        # SP greenery/city need a land hex too.
        self.fill_board(leave=0)
        self.eng.res("Zed", "mc", +40)
        names = self.menu_names("standard")
        self.assertNotIn("greenery", names); self.assertNotIn("city", names)
        self.fill_board(leave=1)
        names = self.menu_names("standard")
        self.assertIn("greenery", names); self.assertIn("city", names)

    def test_app_payload_gives_exact_free_land(self):
        payload = json.loads((self.FIX / "me_end.json").read_text())
        self.assertEqual(advise._free_land_app(payload), 0)
        self.assertIsNone(advise._free_land_app({"game": {}}))

    def test_fetch_app_is_none_for_physical_and_on_error(self):
        self.assertIsNone(advise._fetch_app({"gameMode": "physical"}))
        self.assertIsNone(advise._fetch_app(
            {"gameMode": "app-practice", "appUrl": "http://127.0.0.1:9",
             "players": [{"name": "Zed", "isMe": True, "playerId": "p1"}]}))

    def test_app_mode_header_uses_api_count_and_falls_back(self):
        import copy
        setup = copy.deepcopy(SETUP)
        setup.update(gameMode="app-practice", appUrl="http://127.0.0.1:9")
        setup["players"][0]["playerId"] = "p1"
        self.store._write_json(self.store.setup_path, setup)
        b = advise.build_brief(self.root, kb_dir=self.kb)
        self.assertIn("Free land: 49", b)     # fallback: tracker


class TestBriefFlag(unittest.TestCase):
    """--brief drops the 42 KB KB dump; default in app
    modes (the advisor reads strategy/ once per session, not per turn)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.kb = Path(__file__).parent.parent / "strategy"

    def tearDown(self):
        self.tmp.cleanup()

    def app_mode(self):
        import copy
        setup = copy.deepcopy(SETUP)
        setup["gameMode"] = "app-practice"
        self.store._write_json(self.store.setup_path, setup)

    def test_physical_default_dumps_kb(self):
        b = advise.build_brief(self.root, kb_dir=self.kb)
        self.assertIn("Quantified Guide", b)

    def test_brief_omits_kb_but_keeps_everything_else(self):
        b = advise.build_brief(self.root, kb_dir=self.kb, brief=True)
        self.assertNotIn("Quantified Guide", b)
        self.assertIn("omitted", b.split("# STRATEGY KNOWLEDGE BASE")[1])
        for must in ("AVAILABLE ACTIONS", "RACES", "REQUIREMENT WINDOWS", "OPPONENTS",
                     "RECENT LOG", "OUTPUT CONTRACT"):
            self.assertIn(must, b)

    def test_app_mode_defaults_to_brief_and_full_overrides(self):
        self.app_mode()
        self.assertNotIn("Quantified Guide",
                         advise.build_brief(self.root, kb_dir=self.kb))
        self.assertIn("Quantified Guide",
                      advise.build_brief(self.root, kb_dir=self.kb, brief=False))

    def test_cli_flags(self):
        import subprocess
        script = Path(__file__).resolve().parent.parent / "scripts" / "advise.py"
        base = [sys.executable, str(script), "--root", str(self.root),
                "--kb", str(self.kb)]
        full = subprocess.run(base, capture_output=True, text=True)
        self.assertEqual(full.returncode, 0, full.stderr)
        self.assertIn("Quantified Guide", full.stdout)
        brief = subprocess.run(base + ["--brief"], capture_output=True, text=True)
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertNotIn("Quantified Guide", brief.stdout)
        self.assertIn("Free land:", brief.stdout)
        self.app_mode()
        forced = subprocess.run(base + ["--full"], capture_output=True, text=True)
        self.assertIn("Quantified Guide", forced.stdout)


class TestClockHistoryWiring(unittest.TestCase):
    """The brief hands game['history'] to the clock
    so the printed Clock line carries the observed-rate range."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.kb = Path(__file__).parent.parent / "strategy"

    def tearDown(self):
        self.tmp.cleanup()

    def test_clock_line_reflects_recorded_history(self):
        import clock
        from test_clock import SLOW_TABLE
        g = self.store.load_game()
        g["generation"] = 12
        g["globals"] = dict(SLOW_TABLE[11])
        # produce() entry k = globals when gen k CLOSED = start of gen k+1
        g["history"] = [dict(generation=k, **SLOW_TABLE[k]) for k in range(1, 12)]
        self.store.save_game(g)
        b = advise.build_brief(self.root, kb_dir=self.kb)
        want = clock.estimate(SLOW_TABLE[11], 12, players=3, history=SLOW_TABLE[:11])
        bare = clock.estimate(SLOW_TABLE[11], 12, players=3)
        self.assertNotEqual(want["endRange"], bare["endRange"])
        self.assertIn(f"Clock: {want['note']}", b)
        self.assertIn(f"range {want['endRange'][0]}-{want['endRange'][1]}", b)
