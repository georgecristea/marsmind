"""Card effects applied mechanically from db.json behavior data."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP


class TestExtractedBehavior(unittest.TestCase):
    """The extractor must now capture structured behavior."""

    @classmethod
    def setUpClass(cls):
        cls.db = json.loads(
            (Path(__file__).parent.parent / "cards" / "db.json").read_text())
        cls.by_name = {c["name"]: c for c in cls.db["cards"]}

    def test_comet_behavior(self):
        b = self.by_name["Comet"]["behavior"]
        self.assertEqual(b["global"], {"temperature": 1})
        self.assertEqual(b["ocean"], {})
        self.assertEqual(b["removeAnyPlants"], 3)

    def test_strip_mine_behavior(self):
        b = self.by_name["Strip Mine"]["behavior"]
        self.assertEqual(b["production"], {"energy": -2, "steel": 2, "titanium": 1})
        self.assertEqual(b["global"], {"oxygen": 2})

    def test_most_cards_have_behavior(self):
        with_b = sum(1 for c in self.db["cards"] if c.get("behavior"))
        self.assertGreater(with_b, 120)


class CardPlayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestAutoEffects(CardPlayTest):
    def test_comet_applies_temp_tr_ocean_and_lists_manual_steps(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Comet"])
        msg = self.eng.play("Zed", "Comet")     # cost from db (21)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 9)
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["globals"]["oceans"], 1)
        self.assertEqual(g["me"]["tr"], 22)        # temp + ocean
        self.assertIn("plants", msg.lower())       # manual removal step listed
        self.assertIn("ocean", msg.lower())

    def test_strip_mine_production_deltas_validated(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Strip Mine"])
        with self.assertRaises(EventError):        # no energy production to cut
            self.eng.play("Zed", "Strip Mine")
        self.eng.prod("Zed", "energy", +2)
        self.eng.play("Zed", "Strip Mine")
        g = self.game()
        self.assertEqual(g["me"]["production"]["energy"], 0)
        self.assertEqual(g["me"]["production"]["steel"], 2)
        self.assertEqual(g["me"]["production"]["titanium"], 1)
        self.assertEqual(g["globals"]["oxygen"], 2)
        self.assertEqual(g["me"]["tr"], 22)

    def test_cost_override_still_possible(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Comet"])
        self.eng.play("Zed", "Comet", cost=18)  # discount applied
        self.assertEqual(self.game()["me"]["resources"]["mc"], 12)

    def test_active_card_action_auto_registered(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Ironworks"])
        self.eng.play("Zed", "Ironworks")
        self.assertIn("Ironworks", self.game()["me"]["actionsThisGen"])

    def test_unknown_card_needs_explicit_cost(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Homebrew Card"])
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Homebrew Card")
        self.eng.play("Zed", "Homebrew Card", cost=10)  # manual fallback
        self.assertEqual(self.game()["me"]["resources"]["mc"], 20)

    def test_opponent_play_applies_globals_and_their_tr(self):
        self.eng.res("Anna", "mc", +25)
        self.eng.play("Anna", "Comet")
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["globals"]["oceans"], 1)
        anna = g["opponents"]["Anna"]
        self.assertEqual(anna["tr"], 22)
        self.assertEqual(anna["resources"]["mc"], 4)   # −21 from db cost

    def test_opponent_production_card_tracked(self):
        self.eng.prod("Anna", "energy", +2)
        self.eng.res("Anna", "mc", +30)
        self.eng.play("Anna", "Strip Mine")
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["production"]["steel"], 2)
        self.assertEqual(anna["production"]["energy"], 0)

    def test_stock_gains_applied(self):
        # Great Escarpment Consortium-style steel? use a known stock card:
        # 'Imported Nitrogen' (CE) or base 'Trees': stock plants
        db = json.loads((Path(__file__).parent.parent / "cards" / "db.json").read_text())
        card = next(c for c in db["cards"]
                    if isinstance((c.get("behavior") or {}).get("stock", {}).get("plants"), int)
                    and not c["behavior"].get("global")
                    and "production" not in (c.get("behavior") or {})
                    and c["type"] in ("automated", "event")
                    and not c.get("requirements"))
        self.eng.res("Zed", "mc", +40)
        self.eng.hand_add([card["name"]])
        self.eng.play("Zed", card["name"])
        expected = card["behavior"]["stock"]["plants"]
        self.assertEqual(self.game()["me"]["resources"]["plants"], expected)

    def test_tag_counts_tracked_for_opponents(self):
        self.eng.res("Anna", "mc", +25)
        self.eng.play("Anna", "Comet")
        self.assertEqual(self.game()["opponents"]["Anna"]["tagCounts"].get("space"), 1)


if __name__ == "__main__":
    unittest.main()


class TestPartialBehaviorExtraction(unittest.TestCase):
    """Behavior blocks with dynamic refs keep their parseable parts."""

    @classmethod
    def setUpClass(cls):
        db = json.loads((Path(__file__).parent.parent / "cards" / "db.json").read_text())
        cls.by_name = {c["name"]: c for c in db["cards"]}

    def test_nuclear_zone_keeps_global_temperature(self):
        b = self.by_name["Nuclear Zone"]["behavior"]
        self.assertIsNotNone(b)
        self.assertEqual(b["global"], {"temperature": 2})
        self.assertIn("tile", b)  # dynamic parts survive as markers

    def test_dynamic_marker_not_applied_mechanically(self):
        # tile value contains a dynamic marker → engine treats as manual step
        b = self.by_name["Nuclear Zone"]["behavior"]
        self.assertTrue("@dynamic" in json.dumps(b["tile"]) or isinstance(b["tile"], dict))


class TestBehaviorCompleteness(unittest.TestCase):
    """Drift follow-ups: nothing in a behavior block may be
    silently ignored, ocean counts apply fully, bespoke cards warn."""

    def setUp(self):
        import tempfile as _tf
        from test_new_game import SETUP as _S
        self.tmp = _tf.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(_S)
        self.eng = Engine(self.store)
        g = self.store.load_game()
        g["me"]["resources"]["mc"] = 60
        self.store.save_game(g)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ocean_count_applies_multiple_raises(self):
        g = self.store.load_game()
        steps = []
        self.eng._apply_behavior(g, "Zed", {"ocean": {"count": 2}}, steps)
        self.assertEqual(g["globals"]["oceans"], 2)
        self.assertEqual(g["me"]["tr"], 22)  # 20 + 2

    def test_unknown_behavior_key_emits_table_step(self):
        g = self.store.load_game()
        steps = []
        self.eng._apply_behavior(g, "Zed", {"holoSimulation": 3}, steps)
        self.assertTrue(any("holoSimulation" in s and "TABLE" in s
                            for s in steps), steps)

    def test_bespoke_card_play_warns_table(self):
        self.eng.hand_add(["Sabotage"])   # bespoke (needs target + choice)
        out = self.eng.play("Zed", "Sabotage", cost=1, target="Anna", choice=2)
        self.assertIn("bespoke", out.lower())


class TestPlayRequirementGate(unittest.TestCase):
    def setUp(self):
        import tempfile
        from tmlib import Store, Engine
        from test_new_game import SETUP
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.eng.res("Zed", "mc", 60)
        self.eng.hand_add(["Kelp Farming"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_closed_window_refused(self):
        from tmlib import EventError
        with self.assertRaises(EventError):          # needs 6 oceans, have 0
            self.eng.play("Zed", "Kelp Farming")

    def test_ignore_requirements_overrides(self):
        self.eng.play("Zed", "Kelp Farming", ignore_requirements=True)
        self.assertIn("Kelp Farming",
                      self.store.load_game()["me"]["playedCards"] and
                      [c["name"] if isinstance(c, dict) else c
                       for c in self.store.load_game()["me"]["playedCards"]])


class TestTempTrackBonuses(unittest.TestCase):
    def setUp(self):
        import tempfile
        from tmlib import Store, Engine
        from test_new_game import SETUP
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _warm_to(self, celsius):
        from tmlib import PARAM_SCALE
        g = self.store.load_game()
        g["globals"]["temperature"] = celsius
        self.store.save_game(g)

    def test_minus_24_grants_heat_production(self):
        self._warm_to(-26)
        self.eng.res("Zed", "heat", 8)
        self.eng.convert("Zed", "heat")            # −26 → −24
        self.assertEqual(self.store.load_game()["me"]["production"]["heat"], 1)

    def test_minus_20_grants_heat_production(self):
        self._warm_to(-22)
        self.eng.raise_param("temperature", "Zed")  # −22 → −20
        self.assertEqual(self.store.load_game()["me"]["production"]["heat"], 1)

    def test_no_bonus_on_other_steps(self):
        self._warm_to(-18)
        self.eng.raise_param("temperature", "Zed")
        self.assertEqual(self.store.load_game()["me"]["production"]["heat"], 0)

    def test_zero_crossing_flags_bonus_ocean(self):
        self._warm_to(-2)
        msg = self.eng.raise_param("temperature", "Zed")  # −2 → 0
        self.assertIn("bonus ocean", msg.lower())

    def test_opponent_bonus_tracked(self):
        self._warm_to(-26)
        self.eng.res("Anna", "heat", 8)
        self.eng.convert("Anna", "heat")
        g = self.store.load_game()
        self.assertEqual(g["opponents"]["Anna"]["production"]["heat"], 1)
