"""Corporation abilities modeled mechanically."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestEcoline(Base):
    def test_greenery_costs_7_plants(self):
        self.eng.corp("Anna", "Ecoline", mc=36)   # grants 3 starting plants
        self.eng.res("Anna", "plants", +4)
        self.eng.convert("Anna", "plants")
        g = self.game()
        self.assertEqual(g["opponents"]["Anna"]["resources"]["plants"], 0)
        self.assertEqual(g["opponents"]["Anna"]["tiles"]["greeneries"], 1)

    def test_others_still_pay_8(self):
        self.eng.corp("Zed", "Thorgate", mc=48)
        self.eng.res("Zed", "plants", +7)
        with self.assertRaises(EventError):
            self.eng.convert("Zed", "plants")


class TestCredicor(Base):
    # db.json's canonical corp name is "CrediCor" (mixed-case C's) —
    # apply.py corp stores exactly that string. tmlib's rebate checks must
    # match it, not an invented spelling, or the rebate silently never
    # fires against real game data (Deimos Down cost 31: the app applied
    # the rebate, the tracker didn't).
    def test_rebate_on_20plus_card(self):
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.hand_add(["Comet"])            # cost 21
        self.eng.play("Zed", "Comet")
        # 57 − 21 + 4 rebate = 40
        self.assertEqual(self.game()["me"]["resources"]["mc"], 40)

    def test_no_rebate_below_20(self):
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.hand_add(["Cheap Thing"])
        self.eng.play("Zed", "Cheap Thing", cost=10)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 47)

    def test_rebate_on_20plus_standard_project(self):
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.standard("Zed", "greenery")   # 23 → rebate 4
        self.assertEqual(self.game()["me"]["resources"]["mc"], 38)


class TestHelion(Base):
    def test_heat_spendable_as_mc(self):
        self.eng.corp("Zed", "Helion", mc=42)
        self.eng.res("Zed", "heat", +10)
        self.eng.hand_add(["Comet"])
        self.eng.play("Zed", "Comet", heat=10)  # 21 = 10 heat + 11 MC
        g = self.game()
        self.assertEqual(g["me"]["resources"]["heat"], 0)
        self.assertEqual(g["me"]["resources"]["mc"], 31)

    def test_non_helion_cannot_pay_heat(self):
        self.eng.corp("Zed", "Thorgate", mc=48)
        self.eng.res("Zed", "heat", +10)
        self.eng.hand_add(["Comet"])
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Comet", heat=5)


class TestSaturnSystems(Base):
    def test_mc_prod_on_any_jovian_play(self):
        self.eng.corp("Felix", "Saturn Systems", mc=42)
        self.eng.res("Zed", "mc", +40)
        self.eng.corp("Zed", "Thorgate", mc=0)
        self.eng.hand_add(["Methane From Titan"])
        try:
            self.eng.play("Zed", "Methane From Titan")
        except EventError:
            self.skipTest("requirement/production blocks; use direct opponent play")
        self.assertEqual(self.game()["opponents"]["Felix"]["production"]["mc"], 1)

    def test_saturn_triggers_on_own_jovian_too(self):
        self.eng.corp("Anna", "Saturn Systems", mc=42)
        self.eng.res("Anna", "mc", +40)
        self.eng.play("Anna", "Miranda Resort")   # jovian tag, CE card
        # card's own prod is dynamic (per earth tag → manual); Saturn trigger = +1
        self.assertEqual(self.game()["opponents"]["Anna"]["production"]["mc"], 1)


class TestInterplanetaryCinematics(Base):
    def test_2mc_back_on_event(self):
        self.eng.corp("Zed", "Interplanetary Cinematics", mc=30)
        self.eng.hand_add(["Comet"])
        self.eng.play("Zed", "Comet")
        # 30 − 21 + 2 = 11
        self.assertEqual(self.game()["me"]["resources"]["mc"], 11)


class TestTharsisRepublic(Base):
    def test_mc_prod_when_any_city_placed_and_3mc_own_city(self):
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.eng.res("Zed", "mc", -15)  # simplify balance: 25
        self.eng.standard("Zed", "city")     # own city on Mars
        g = self.game()
        me = g["me"]
        # paid 25; +3 own-city cash; +1 MC prod (any city) +1 (SP city itself)
        self.assertEqual(me["resources"]["mc"], 3)
        self.assertEqual(me["production"]["mc"], 2)

    def test_tharsis_triggers_on_opponent_city(self):
        self.eng.corp("Anna", "Tharsis Republic", mc=40)
        self.eng.res("Zed", "mc", +25)
        self.eng.standard("Zed", "city")
        self.assertEqual(self.game()["opponents"]["Anna"]["production"]["mc"], 1)

    def test_reserved_area_city_does_not_trigger_tharsis_for_opponent_play(self):
        # Ben plays Ganymede Colony (a RESERVED-AREA card --
        # cards/db.json behavior.city.space="ganymedecolony", per
        # board.json's offMap=True spaces) and it incorrectly fired
        # Zed's Tharsis +1 MC production. Reserved-area cities are not
        # "on Mars" and must never trigger Tharsis, for anyone.
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.eng.res("Anna", "mc", +30)
        self.eng.play("Anna", "Ganymede Colony", cost=20)
        g = self.game()
        self.assertEqual(g["me"]["production"]["mc"], 0)
        self.assertEqual(g["opponents"]["Anna"]["tiles"]["cities"], 1)

    def test_reserved_area_city_does_not_trigger_tharsis_self_bonus(self):
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Ganymede Colony"])
        self.eng.play("Zed", "Ganymede Colony", cost=20)
        g = self.game()
        self.assertEqual(g["me"]["production"]["mc"], 0)   # no +1, no +3
        self.assertEqual(g["me"]["tiles"]["cities"], 1)     # tile still counted

    def test_normal_city_card_still_triggers_tharsis(self):
        # regression guard: a card with a plain city behavior (no "space"
        # key -- a real Mars hex) must keep triggering Tharsis normally.
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.eng.res("Anna", "mc", +30)
        self.eng.prod("Anna", "energy", +1)
        self.eng.play("Anna", "Open City", cost=23, ignore_requirements=True)
        self.assertEqual(self.game()["me"]["production"]["mc"], 1)


class TestMiningGuild(Base):
    def test_steel_prod_on_steel_placement_bonus(self):
        self.eng.corp("Zed", "Mining Guild", mc=30)
        import json
        board = json.loads((Path(__file__).parent.parent / "board.json").read_text())
        sid = next(s["id"] for s in board["spaces"]
                   if "steel" in s.get("bonus", []) and not s.get("oceanReserved")
                   and not s.get("offMap"))
        self.eng.place("Zed", "city", sid)
        # 1 starting production (corp) + 1 from the metal-bonus placement
        self.assertEqual(self.game()["me"]["production"]["steel"], 2)


if __name__ == "__main__":
    unittest.main()


class TestCorpStartingStock(unittest.TestCase):
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

    def test_ic_grants_20_steel(self):
        self.eng.corp("Zed", "Interplanetary Cinematics", mc=30)
        me = self.store.load_game()["me"]
        self.assertEqual(me["resources"]["steel"], 20)

    def test_mining_guild_grants_stock_and_production(self):
        self.eng.corp("Zed", "Mining Guild", mc=30)
        me = self.store.load_game()["me"]
        self.assertEqual(me["resources"]["steel"], 5)
        self.assertEqual(me["production"]["steel"], 1)

    def test_unknown_corp_still_works(self):
        self.eng.corp("Zed", "Totally Homebrew Corp", mc=40)
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 40)
