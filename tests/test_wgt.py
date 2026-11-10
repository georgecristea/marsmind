"""World Government Terraforming (Venus Next 'solar phase' option).

Rules verified against the vendored app (Game.ts): after every
player has passed and before production, the generation's FIRST player
raises one global parameter one step. The raise happens in the SOLAR
phase: NO TR, NO -24/-20 heat-production bonus, NO card triggers, and an
ocean placed this way grants NO placement bonus and NO ocean-adjacency
MC. The 8% O2 -> temperature bump and the 0 C bonus ocean still chain
(also without TR/bonuses). Skipped once Mars is fully terraformed.
"""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import clock
from tmlib import Store, Engine, EventError, wgt_enabled
from test_new_game import SETUP


def _wgt_setup(**over):
    s = json.loads(json.dumps(SETUP))
    s["expansions"] = ["base", "corporateEra", "wgt"]
    s.update(over)
    return s


class Base(unittest.TestCase):
    setup = _wgt_setup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.store.init(self.setup)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestEnabledFlag(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(wgt_enabled(SETUP))

    def test_expansion_token(self):
        self.assertTrue(wgt_enabled(_wgt_setup()))

    def test_house_rule_text(self):
        s = json.loads(json.dumps(SETUP))
        s["houseRules"] = ["World Government Terraforming on"]
        self.assertTrue(wgt_enabled(s))


class TestWgtEvent(Base):
    def test_temperature_no_tr_no_heat_bonus(self):
        # first player gen 1 is Anna (SETUP); -30 -> -28: nobody gains TR
        before = self.game()
        self.eng.wgt("temperature")
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["opponents"]["Anna"]["tr"], before["opponents"]["Anna"]["tr"])
        self.assertEqual(g["me"]["tr"], before["me"]["tr"])

    def test_reaching_minus24_grants_no_heat_production(self):
        # reaching -24 by WGT grants NO heat production (SOLAR phase)
        self.eng.sync_global("temperature", -26)
        msg = self.eng.wgt("temperature")           # -> -24
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -24)
        self.assertEqual(g["opponents"]["Anna"]["production"]["heat"], 0)
        self.assertIn("NOT granted", msg)

    def test_oxygen_chain_to_temperature_without_tr(self):
        self.eng.sync_global("oxygen", 7)
        before_tr = self.game()["opponents"]["Anna"]["tr"]
        msg = self.eng.wgt("oxygen")
        g = self.game()
        self.assertEqual(g["globals"]["oxygen"], 8)
        self.assertEqual(g["globals"]["temperature"], -28)   # 8% bonus bump
        self.assertEqual(g["opponents"]["Anna"]["tr"], before_tr)
        self.assertIn("8%", msg)

    def test_ocean_requires_hex_and_grants_no_bonuses(self):
        with self.assertRaises(EventError):
            self.eng.wgt("oceans")
        before = self.game()
        mc0 = before["opponents"]["Anna"]["resources"]["mc"]
        # space 6 (Tharsis top-left area) is ocean-reserved with a bonus in
        # board.json; whichever hex, resources must not move.
        spaces = self.eng._board()
        hex_id = next(k for k, v in spaces.items()
                      if v.get("oceanReserved") and v.get("bonus"))
        self.eng.wgt("oceans", space_id=hex_id)
        g = self.game()
        self.assertEqual(g["globals"]["oceans"], 1)
        self.assertEqual(g["board"][hex_id]["tile"], "ocean")
        self.assertEqual(g["opponents"]["Anna"]["resources"], before["opponents"]["Anna"]["resources"])
        self.assertEqual(g["opponents"]["Anna"]["resources"]["mc"], mc0)
        self.assertEqual(g["opponents"]["Anna"]["tr"], before["opponents"]["Anna"]["tr"])

    def test_zero_degrees_bonus_ocean_pending_then_placed(self):
        self.eng.sync_global("temperature", -2)
        msg = self.eng.wgt("temperature")
        self.assertIn("BONUS OCEAN", msg)
        g = self.game()
        self.assertTrue(g.get("wgtBonusOceanPending"))
        # a second wgt call in the same gen is allowed ONLY for that ocean
        with self.assertRaises(EventError):
            self.eng.wgt("oxygen")
        spaces = self.eng._board()
        hex_id = next(k for k, v in spaces.items() if v.get("oceanReserved"))
        self.eng.wgt("oceans", space_id=hex_id)
        self.assertFalse(self.game().get("wgtBonusOceanPending"))

    def test_once_per_generation(self):
        self.eng.wgt("temperature")
        with self.assertRaises(EventError):
            self.eng.wgt("oxygen")

    def test_refused_when_not_enabled(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        st = Store(Path(tmp.name)); st.init(SETUP)
        with self.assertRaises(EventError):
            Engine(st).wgt("temperature")

    def test_log_names_chooser(self):
        msg = self.eng.wgt("oxygen")
        self.assertIn("Anna", msg)          # gen-1 first player chooses
        self.assertIn("WGT", msg)


class TestProduceGuard(Base):
    def test_produce_refuses_without_wgt_step(self):
        with self.assertRaises(EventError):
            self.eng.produce()

    def test_produce_ok_after_wgt_step(self):
        self.eng.wgt("temperature")
        self.eng.produce()
        self.assertEqual(self.game()["generation"], 2)
        # flag resets: next gen needs its own step
        with self.assertRaises(EventError):
            self.eng.produce()

    def test_produce_skip_flag(self):
        self.eng.produce(skip_wgt="host forgot the step")
        self.assertEqual(self.game()["generation"], 2)

    def test_produce_ok_when_mars_terraformed(self):
        self.eng.sync_global("temperature", 8)
        self.eng.sync_global("oxygen", 14)
        self.eng.sync_global("oceans", 9)
        self.eng.produce()
        self.assertEqual(self.game()["generation"], 2)

    def test_produce_refuses_with_bonus_ocean_pending(self):
        self.eng.sync_global("temperature", -2)
        self.eng.wgt("temperature")           # 0 C -> bonus ocean pending
        with self.assertRaises(EventError):
            self.eng.produce()


class TestClockPrior(unittest.TestCase):
    def test_wgt_shortens_prior_by_one(self):
        g = {"temperature": -30, "oxygen": 0, "oceans": 0}
        for n in (3, 4, 5, 6):
            base = clock.estimate(g, 1, players=n)["endGeneration"]
            wgt = clock.estimate(g, 1, players=n, wgt=True)["endGeneration"]
            self.assertEqual(wgt, base - 1, n)


if __name__ == "__main__":
    unittest.main()
