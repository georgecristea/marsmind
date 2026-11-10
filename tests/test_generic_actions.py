"""Phase 2 of private/plans/generalize-engine-plan.md: ONE generic
interpreter for blue-card actions.

tests/test_actions_p8.py pins the eight cards a real game exposed; this file
proves the SAME code path handles cards nobody hand-modelled — every card
below was outside ACTION_EFFECTS and would have done nothing but tick the
ledger before. Nothing here names a behaviour the engine knows by card name:
each expectation is exactly what cards/db.json's `actionBehavior` says.

Covered: `spend` (energy / MC / plants / steel / resources on the card),
`or` (auto-select the only executable branch, refuse when several are, apply
a named one), Countables ({"cities": …}, {"resourcesHere": …}), and the
GENERIC unuse_action inverse.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import menu
import score
import tmlib
from tmlib import Engine, EventError, Store


class Base(unittest.TestCase):
    SETUP = {
        "playerCount": 3,
        "players": [
            {"name": "Zed", "color": "red", "isMe": True, "aliases": ["red"]},
            {"name": "Anna", "color": "green", "isMe": False, "aliases": []},
            {"name": "Ben", "color": "yellow", "isMe": False, "aliases": []},
        ],
        "expansions": ["base", "corporateEra"],
        "map": "tharsis",
        "draft": False,
        "houseRules": [],
        "seatingOrder": ["Zed", "Anna", "Ben"],
        "firstPlayerGen1": "Anna",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(self.SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def me(self):
        return self.game()["me"]

    def play_mine(self, card, energy_prod=0, **kw):
        """Bankroll + play a card of mine so its blue action is registered."""
        self.eng.res("Zed", "mc", +99)
        if energy_prod:
            self.eng.prod("Zed", "energy", +energy_prod)
        self.eng.hand_add([card])
        kw.setdefault("ignore_requirements", "test fixture")
        return self.eng.play("Zed", card, **kw)

    def reopen(self, card):
        g = self.game()
        g["me"]["actionsThisGen"][card]["used"] = False
        self.store.save_game(g)


class TestSpendEnergy(Base):
    """`spend: {energy: N}` + a global raise — Water Splitting Plant and Ore
    Processor were never hand-modelled; the db says what they do."""

    def test_water_splitting_plant_3_energy_for_an_oxygen_step(self):
        self.play_mine("Water Splitting Plant")
        self.eng.res("Zed", "energy", +5)
        tr = self.me()["tr"]
        self.eng.use_action("Water Splitting Plant")
        self.assertEqual(self.me()["resources"]["energy"], 2)
        self.assertEqual(self.game()["globals"]["oxygen"], 1)
        self.assertEqual(self.me()["tr"], tr + 1)

    def test_ore_processor_4_energy_for_titanium_and_oxygen(self):
        self.play_mine("Ore Processor")
        self.eng.res("Zed", "energy", +4)
        tr = self.me()["tr"]
        self.eng.use_action("Ore Processor")
        me = self.me()
        self.assertEqual(me["resources"]["energy"], 0)
        self.assertEqual(me["resources"]["titanium"], 1)
        self.assertEqual(self.game()["globals"]["oxygen"], 1)
        self.assertEqual(me["tr"], tr + 1)

    def test_short_of_energy_refuses_and_mutates_nothing(self):
        self.play_mine("Ore Processor")
        self.eng.res("Zed", "energy", +3)
        with self.assertRaises(EventError) as cm:
            self.eng.use_action("Ore Processor")
        self.assertIn("4 energy", str(cm.exception))
        self.assertEqual(self.me()["resources"]["energy"], 3)
        self.assertEqual(self.game()["globals"]["oxygen"], 0)
        self.assertFalse(self.me()["actionsThisGen"]["Ore Processor"]["used"])

    def test_an_opponent_short_of_energy_clamps_instead(self):
        self.eng.res("Anna", "mc", +99)
        self.eng.play("Anna", "Ore Processor")
        self.eng.res("Anna", "energy", +1)
        msg = self.eng.use_action("Ore Processor", player="Anna")
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["resources"]["energy"], 0)
        self.assertEqual(anna["resources"]["titanium"], 1)
        self.assertIn("clamped", msg)

    def test_development_center_spends_1_energy_and_flags_the_draw(self):
        self.play_mine("Development Center")
        self.eng.res("Zed", "energy", +2)
        msg = self.eng.use_action("Development Center")
        self.assertEqual(self.me()["resources"]["energy"], 1)
        self.assertIn("draw 1 card", msg)


class TestSpendMegacredits(Base):
    def test_space_mirrors_pays_7_for_energy_production(self):
        self.play_mine("Space Mirrors")
        mc = self.me()["resources"]["mc"]
        prod = self.me()["production"]["energy"]
        self.eng.use_action("Space Mirrors")
        self.assertEqual(self.me()["resources"]["mc"], mc - 7)
        self.assertEqual(self.me()["production"]["energy"], prod + 1)

    def test_underground_detonations_pays_10_for_2_heat_production(self):
        self.play_mine("Underground Detonations")
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Underground Detonations")
        self.assertEqual(self.me()["resources"]["mc"], mc - 10)
        self.assertEqual(self.me()["production"]["heat"], 2)

    def test_restricted_area_pays_2_and_flags_the_draw(self):
        self.play_mine("Restricted Area")
        mc = self.me()["resources"]["mc"]
        msg = self.eng.use_action("Restricted Area")
        self.assertEqual(self.me()["resources"]["mc"], mc - 2)
        self.assertIn("draw 1 card", msg)

    def test_too_little_mc_refuses(self):
        self.play_mine("Underground Detonations")
        g = self.game()
        g["me"]["resources"]["mc"] = 9
        self.store.save_game(g)
        with self.assertRaises(EventError):
            self.eng.use_action("Underground Detonations")
        self.assertEqual(self.me()["production"]["heat"], 0)

    def test_ore_may_not_pay_when_the_card_does_not_allow_it(self):
        self.play_mine("Underground Detonations")
        self.eng.res("Zed", "steel", +5)
        with self.assertRaises(EventError) as cm:
            self.eng.use_action("Underground Detonations", steel=5)
        self.assertIn("steel may not pay", str(cm.exception).lower())


class TestOrActions(Base):
    """`or` with the auto-single-executable-branch rule, on the microbe
    accumulators (P8 only ever exercised Nitrite Reducing Bacteria)."""

    def test_regolith_eaters_auto_adds_when_it_cannot_pay(self):
        self.play_mine("Regolith Eaters")           # starts with 0 microbes
        msg = self.eng.use_action("Regolith Eaters")
        self.assertIn("or-choice AUTO", msg)
        self.assertEqual(self.me()["cardResources"]["Regolith Eaters"], 1)
        self.assertEqual(self.game()["globals"]["oxygen"], 0)

    def test_regolith_eaters_refuses_once_both_branches_are_open(self):
        self.play_mine("Regolith Eaters")
        g = self.game()
        g["me"]["cardResources"] = {"Regolith Eaters": 2}
        self.store.save_game(g)
        with self.assertRaises(EventError) as cm:
            self.eng.use_action("Regolith Eaters")
        self.assertIn("--choice", str(cm.exception))
        self.assertEqual(self.me()["cardResources"]["Regolith Eaters"], 2)

    def test_regolith_eaters_named_branch_spends_the_card_resources(self):
        self.play_mine("Regolith Eaters")
        g = self.game()
        g["me"]["cardResources"] = {"Regolith Eaters": 2}
        self.store.save_game(g)
        tr = self.me()["tr"]
        self.eng.use_action("Regolith Eaters", choice=1)
        self.assertEqual(self.me()["cardResources"]["Regolith Eaters"], 0)
        self.assertEqual(self.game()["globals"]["oxygen"], 1)
        self.assertEqual(self.me()["tr"], tr + 1)

    def test_branch_indices_follow_the_action_text_not_the_db(self):
        # "Add 1 microbe to this card, or remove 2 microbes to raise oxygen"
        # — the db lists the removal first, the player reads add first.
        info = self.eng.card("GHG Producing Bacteria")
        titles = [b["title"] for b in tmlib.or_branches(
            info, behavior=info["actionBehavior"], text=info["action"])]
        self.assertTrue(titles[0].lower().startswith("add"))
        self.assertTrue(titles[1].lower().startswith("remove"))

    def test_ghg_producing_bacteria_removes_2_for_a_temperature_step(self):
        self.play_mine("GHG Producing Bacteria")
        g = self.game()
        g["me"]["cardResources"] = {"GHG Producing Bacteria": 3}
        self.store.save_game(g)
        tr = self.me()["tr"]
        self.eng.use_action("GHG Producing Bacteria", choice=1)
        self.assertEqual(self.me()["cardResources"]["GHG Producing Bacteria"], 1)
        self.assertEqual(self.game()["globals"]["temperature"], -28)
        self.assertEqual(self.me()["tr"], tr + 1)

    def test_electro_catapult_auto_picks_the_ore_it_actually_holds(self):
        self.play_mine("Electro Catapult", energy_prod=1)
        self.eng.res("Zed", "steel", +1)          # no plants
        mc = self.me()["resources"]["mc"]
        msg = self.eng.use_action("Electro Catapult")
        self.assertIn("steel", msg)
        self.assertEqual(self.me()["resources"]["steel"], 0)
        self.assertEqual(self.me()["resources"]["mc"], mc + 7)

    def test_electro_catapult_refuses_when_both_ores_are_available(self):
        self.play_mine("Electro Catapult", energy_prod=1)
        self.eng.res("Zed", "steel", +1)
        self.eng.res("Zed", "plants", +1)
        with self.assertRaises(EventError) as cm:
            self.eng.use_action("Electro Catapult")
        self.assertIn("--choice", str(cm.exception))
        self.assertEqual(self.me()["resources"]["plants"], 1)


class TestCountables(Base):
    """Amounts the vendor writes as a Countable object, resolved from state
    instead of printed as a → TABLE step."""

    def test_cities_on_mars_countable_on_a_play_behavior(self):
        # Zeppelins: MC production = cities ON MARS (a Countable in
        # `behavior`, the same evaluator Martian Rails' action uses)
        self.eng.place("Zed", "city", "05")
        self.eng.place("Anna", "city", "20")
        self.play_mine("Zeppelins")
        self.assertEqual(self.me()["production"]["mc"], 2)

    def test_reserved_area_cities_never_count_as_on_mars(self):
        self.play_mine("Ganymede Colony")       # off-Mars city
        self.play_mine("Zeppelins")
        self.assertEqual(self.me()["production"]["mc"], 0)

    def test_resources_here_countable_reads_the_acting_card(self):
        self.play_mine("Regolith Eaters")
        g = self.game()
        g["me"]["cardResources"] = {"Regolith Eaters": 5}
        self.store.save_game(g)
        n, why = self.eng._resolve_dynamic(
            self.game(), "Zed", {"resourcesHere": {}},
            self.eng.card("Regolith Eaters"))
        self.assertEqual(n, 5)
        self.assertIn("Regolith Eaters", why)


class TestGenericUnuse(Base):
    """unuse_action inverts the behavior dict, whatever card it came from."""

    def test_space_mirrors_production_and_mc_come_back(self):
        self.play_mine("Space Mirrors")
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Space Mirrors")
        self.eng.unuse_action("Space Mirrors")
        me = self.me()
        self.assertEqual(me["resources"]["mc"], mc)
        self.assertEqual(me["production"]["energy"], 0)
        self.assertFalse(me["actionsThisGen"]["Space Mirrors"]["used"])

    def test_ore_processor_gives_back_the_titanium_and_the_oxygen_step(self):
        self.play_mine("Ore Processor")
        self.eng.res("Zed", "energy", +4)
        tr = self.me()["tr"]
        self.eng.use_action("Ore Processor")
        self.eng.unuse_action("Ore Processor")
        me = self.me()
        self.assertEqual(me["resources"]["energy"], 4)
        self.assertEqual(me["resources"]["titanium"], 0)
        self.assertEqual(self.game()["globals"]["oxygen"], 0)
        self.assertEqual(me["tr"], tr)

    def test_underground_detonations_reverses_two_production_steps(self):
        self.play_mine("Underground Detonations")
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Underground Detonations")
        self.eng.unuse_action("Underground Detonations")
        me = self.me()
        self.assertEqual(me["resources"]["mc"], mc)
        self.assertEqual(me["production"]["heat"], 0)

    def test_regolith_eaters_branch_must_be_named_and_inverts(self):
        self.play_mine("Regolith Eaters")
        g = self.game()
        g["me"]["cardResources"] = {"Regolith Eaters": 2}
        self.store.save_game(g)
        self.eng.use_action("Regolith Eaters", choice=1)
        with self.assertRaises(EventError):
            self.eng.unuse_action("Regolith Eaters")
        self.eng.unuse_action("Regolith Eaters", choice=1)
        self.assertEqual(self.me()["cardResources"]["Regolith Eaters"], 2)
        self.assertEqual(self.game()["globals"]["oxygen"], 0)

    def test_an_uninvertible_state_refuses_and_commits_nothing(self):
        self.play_mine("Ore Processor")
        self.eng.res("Zed", "energy", +4)
        self.eng.use_action("Ore Processor")
        self.eng.res("Zed", "titanium", -1)      # spent it since
        with self.assertRaises(EventError):
            self.eng.unuse_action("Ore Processor")
        self.assertEqual(self.game()["globals"]["oxygen"], 1)
        self.assertTrue(self.me()["actionsThisGen"]["Ore Processor"]["used"])

    def test_electro_catapult_refunds_the_ore_of_the_branch_used(self):
        self.play_mine("Electro Catapult", energy_prod=1)
        self.eng.res("Zed", "plants", +1)
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Electro Catapult", choice=0)
        self.eng.unuse_action("Electro Catapult", choice=0)
        me = self.me()
        self.assertEqual(me["resources"]["plants"], 1)
        self.assertEqual(me["resources"]["mc"], mc)


class TestMenuDerivesAvailability(Base):
    """menu.py prices and gates blue actions from actionBehavior — the
    35-entry ACTION_COSTS table is gone."""

    def items(self):
        return [i for i in menu.available_actions(self.game(), self.SETUP)
                if i["kind"] == "action"]

    def names(self):
        return sorted(i["name"] for i in self.items())

    def test_an_unaffordable_action_is_not_listed(self):
        self.play_mine("Ore Processor")           # needs 4 energy, has 0
        self.assertNotIn("Ore Processor", self.names())
        self.eng.res("Zed", "energy", +4)
        self.assertIn("Ore Processor", self.names())

    def test_the_mc_cost_comes_from_the_behavior(self):
        self.play_mine("Underground Detonations")
        item = next(i for i in self.items()
                    if i["name"] == "Underground Detonations")
        self.assertEqual(item["cost"], 10)

    def test_an_or_action_is_listed_while_any_branch_is_payable(self):
        self.play_mine("Electro Catapult", energy_prod=1)
        self.assertNotIn("Electro Catapult", self.names())
        self.eng.res("Zed", "steel", +1)
        self.assertIn("Electro Catapult", self.names())

    def test_a_dead_global_raise_is_not_offered(self):
        self.play_mine("Water Splitting Plant")
        self.eng.res("Zed", "energy", +9)
        self.assertIn("Water Splitting Plant", self.names())
        g = self.game()
        g["globals"]["oxygen"] = tmlib.PARAM_SCALE["oxygen"]["max"]
        self.store.save_game(g)
        self.assertNotIn("Water Splitting Plant", self.names())

    def test_a_production_decrease_the_player_cannot_pay_is_not_offered(self):
        self.play_mine("Equatorial Magnetizer")   # −1 energy prod → +1 TR
        self.assertNotIn("Equatorial Magnetizer", self.names())
        self.eng.prod("Zed", "energy", +1)
        self.assertIn("Equatorial Magnetizer", self.names())

    def test_the_four_prose_only_actions_are_the_whole_exception_list(self):
        self.assertEqual(
            sorted(menu.PROSE_ACTIONS),
            ["Business Network", "Extreme-Cold Fungus", "Inventors' Guild",
             "Power Infrastructure", "Search For Life",
             "United Nations Mars Initiative"])


class TestScoreReadsVpData(Base):
    """score.py scores formula VP from the db's `vpData`, not from prose."""

    def rows(self):
        return {r["name"]: r for r in score.compute(self.game())["players"]}

    def test_resources_here_each(self):
        self.play_mine("Physics Complex")         # 2 VP per science resource
        g = self.game()
        g["me"]["cardResources"] = {"Physics Complex": 3}
        self.store.save_game(g)
        self.assertEqual(self.rows()["Zed"]["cardVP"], 6)

    def test_resources_here_per(self):
        self.play_mine("Pets")                    # 1 VP per 2 animals
        g = self.game()
        g["me"]["cardResources"] = {"Pets": 5}
        self.store.save_game(g)
        self.assertEqual(self.rows()["Zed"]["cardVP"], 2)

    def test_per_tag_formula(self):
        self.play_mine("Ganymede Colony")         # 1 VP per jovian tag
        self.assertEqual(self.rows()["Zed"]["cardVP"], 1)
        self.assertNotIn("Ganymede Colony", self.rows()["Zed"]["formulaVPCards"])

    def test_per_cities_formula_counts_the_board(self):
        self.play_mine("Immigration Shuttles")    # 1 VP per 3 cities in play
        for hex_ in ("05", "20", "35"):
            self.eng.place("Zed", "city", hex_)
        self.assertEqual(self.rows()["Zed"]["cardVP"], 1)

    def test_a_board_formula_stays_in_the_manual_pile(self):
        # Capital: "1 per adjacent ocean tile" — vpData is null because the
        # vendor computes it from hexes; it must never be read off a
        # card-resource count.
        self.play_mine("Capital", energy_prod=2)
        row = self.rows()["Zed"]
        self.assertIn("Capital", row["formulaVPCards"])


if __name__ == "__main__":
    unittest.main()
