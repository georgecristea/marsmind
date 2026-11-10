"""M1: production phase — income, energy→heat, gen advance, ledger reset."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine
from test_new_game import SETUP


class TestProduce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def test_me_income_tr_plus_mc_prod(self):
        self.eng.prod("Zed", "mc", +3)
        self.eng.produce()
        # TR 20 + 3 MC prod = 23
        self.assertEqual(self.game()["me"]["resources"]["mc"], 23)

    def test_me_energy_converts_to_heat_before_refill(self):
        self.eng.prod("Zed", "energy", +2)
        self.eng.prod("Zed", "heat", +1)
        self.eng.res("Zed", "energy", +3)  # leftover energy
        self.eng.produce()
        me = self.game()["me"]
        self.assertEqual(me["resources"]["heat"], 4)   # 3 leftover + 1 prod
        self.assertEqual(me["resources"]["energy"], 2)  # refilled from prod

    def test_me_other_resources_gain_production(self):
        self.eng.prod("Zed", "steel", +2)
        self.eng.prod("Zed", "plants", +1)
        self.eng.produce()
        me = self.game()["me"]
        self.assertEqual(me["resources"]["steel"], 2)
        self.assertEqual(me["resources"]["plants"], 1)

    def test_generation_advances_and_first_player_rotates(self):
        self.assertEqual(self.game()["firstPlayer"], "Anna")
        self.eng.produce()
        g = self.game()
        self.assertEqual(g["generation"], 2)
        self.assertEqual(g["firstPlayer"], "Felix")  # one seat clockwise

    def test_first_player_rotation_wraps(self):
        self.eng.produce()  # Anna → Felix
        self.eng.produce()  # Felix → Zed
        self.eng.produce()  # Zed → Anna
        self.assertEqual(self.game()["firstPlayer"], "Anna")

    def test_action_ledger_resets_to_available(self):
        self.eng.register_action("Ironworks")
        self.eng.res("Zed", "energy", +4)   # Ironworks: spend 4 energy
        self.eng.use_action("Ironworks")
        self.eng.produce()
        self.assertEqual(
            self.game()["me"]["actionsThisGen"], {"Ironworks": {"used": False}}
        )

    def test_opponents_simulated_income_marked_estimated(self):
        self.eng.prod("Anna", "mc", +4)
        self.eng.tr("Anna", +2)  # TR 22
        self.eng.prod("Anna", "plants", +2)
        self.eng.prod("Anna", "energy", +2)
        self.eng.prod("Anna", "heat", +1)
        self.eng.produce()
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["resources"]["mc"], 26)  # 22 TR + 4 prod
        self.assertTrue(anna["estimated"])
        self.assertEqual(anna["resources"]["plants"], 2)
        # energy→heat first: 0 leftover energy + 1 heat prod; energy refills to 2
        self.assertEqual(anna["resources"]["heat"], 1)
        self.assertEqual(anna["resources"]["energy"], 2)

    def test_produce_is_logged_with_summary(self):
        self.eng.prod("Zed", "mc", +3)
        self.eng.produce()
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("Production", log)
        self.assertIn("Generation 2", log)


class TestInvariants(unittest.TestCase):
    """Cheap sanity sweep before turnover.

    Violations are REPORTED (⚠ INVARIANT lines), never abort — produce
    must stay usable mid-game even on a drifted tracker.
    """

    def setUp(self):
        import produce
        from tmlib import new_game_state
        self.produce = produce
        self.game = new_game_state(SETUP)

    def test_clean_state_yields_no_lines(self):
        self.assertEqual(self.produce.check_invariants(self.game), [])

    def test_violations_each_reported_as_invariant_line(self):
        g = self.game
        g["me"]["resources"]["mc"] = -3                 # stock floor
        g["me"]["production"]["mc"] = -6                # below -5 floor
        g["opponents"]["Anna"]["production"]["energy"] = -1
        g["globals"]["temperature"] = -40               # off the scale
        g["board"] = {"05": {"tile": "city", "player": "Ghost"}}
        lines = self.produce.check_invariants(g)
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertIn("⚠ INVARIANT", line)
        text = "\n".join(lines)
        self.assertIn("mc", text)
        self.assertIn("temperature", text)
        self.assertIn("Ghost", text)

    def test_mc_production_floor_is_minus_five(self):
        self.game["me"]["production"]["mc"] = -5        # legal (base rule)
        self.assertEqual(self.produce.check_invariants(self.game), [])

    def test_cli_prints_warnings_but_still_produces(self):
        import subprocess, sys as _sys
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(tmp.name)
        store.init(SETUP)
        # drift the board via a raw record with an unknown player: simulate
        # by placing then renaming is impossible without hand-edits, so the
        # CLI check here is the clean path only (function tests cover dirty)
        script = Path(__file__).resolve().parent.parent / "scripts" / "produce.py"
        r = subprocess.run([_sys.executable, str(script)], cwd=tmp.name,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("⚠ INVARIANT", r.stdout)
        self.assertEqual(store.load_game()["generation"], 2)


if __name__ == "__main__":
    unittest.main()


class TestHistory(unittest.TestCase):
    """produce() records the globals as they stood
    when each generation closed so clock.estimate can see the observed
    fill rate (a stalled table otherwise reads '~1 gen left' for many
    generations)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_each_produce_appends_one_entry_with_closing_globals(self):
        self.eng.produce()                          # closes gen 1 at -30/0/0
        self.eng.sync_global("oxygen", 2)
        self.eng.sync_global("oceans", 1)
        self.eng.produce()                          # closes gen 2 at -30/2/1
        self.eng.sync_global("temperature", -26)
        self.eng.produce()                          # closes gen 3
        hist = self.store.load_game()["history"]
        self.assertEqual([h["generation"] for h in hist], [1, 2, 3])
        self.assertEqual(hist[1], {"generation": 2, "temperature": -30,
                                   "oxygen": 2, "oceans": 1})
        self.assertEqual(hist[2], {"generation": 3, "temperature": -26,
                                   "oxygen": 2, "oceans": 1})


class StandingsAtTurnover(unittest.TestCase):
    """The app's VP column does not exist at the physical
    table — produce.py prints score.py standings at every turnover."""

    def setUp(self):
        import produce, score
        self.produce, self.score = produce, score
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)

    def tearDown(self):
        self.tmp.cleanup()

    def test_standings_line_ranks_all_players_full_mode(self):
        g = self.store.load_game()
        g["me"]["tr"] = 30
        line = self.score.standings_line(g)
        self.assertTrue(line.startswith("Standings (full):"), line)
        self.assertIn("Zed 30", line)
        for name in g["opponents"]:
            self.assertIn(name, line)
        self.assertLess(line.index("Zed"), line.index("Anna"))  # leader first

    def test_turnover_output_includes_standings(self):
        out = self.produce.turnover(self.store)
        self.assertIn("Production (end of gen 1)", out)
        self.assertIn("Standings (full):", out)
