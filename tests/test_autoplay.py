"""Sparring autopilot policy + information firewall.
Pure policy tests on canned waitingFor JSON — no server needed."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import autoplay


def mat(mc=30, plants=0, heat=0, steel=0, titanium=0):
    return {"megacredits": mc, "plants": plants, "heat": heat,
            "steel": steel, "titanium": titanium, "terraformRating": 30}


def or_menu(*titles):
    return {"type": "or", "title": "Take your first action",
            "options": [{"title": t, "type": "option"} for t in titles]}


class TestResearchPolicy(unittest.TestCase):
    def test_buys_positive_value_cards_within_budget(self):
        wf = {"type": "card", "title": "Select card(s) to buy",
              "cards": [{"name": "Trees"}, {"name": "Fusion Power"}]}
        globals_ = {"temperature": 8, "oxygen": 8, "oceans": 9}
        resp = autoplay.decide_research(wf, mat(mc=40), globals_, gens_left=4)
        self.assertEqual(resp["type"], "card")
        self.assertIn("Trees", resp["cards"])          # strong plant prod
        self.assertNotIn("Fusion Power", resp["cards"])  # dead energy late

    def test_keeps_nothing_when_broke(self):
        wf = {"type": "card", "title": "Select card(s) to buy",
              "cards": [{"name": "Trees"}]}
        globals_ = {"temperature": -20, "oxygen": 0, "oceans": 0}
        resp = autoplay.decide_research(wf, mat(mc=2), globals_, gens_left=10)
        self.assertEqual(resp["cards"], [])


class TestActionPolicy(unittest.TestCase):
    def test_prefers_plant_conversion(self):
        wf = or_menu("Convert 8 plants into greenery",
                     "Pass for this generation")
        wf["options"][0]["type"] = "space"
        wf["options"][0]["spaces"] = ["23"]
        act = autoplay.decide_action(wf, mat(plants=9),
                                     {"temperature": 0, "oxygen": 5, "oceans": 5})
        self.assertEqual(act["index"], 0)

    def test_skips_heat_conversion_at_max_temp(self):
        wf = or_menu("Convert 8 heat into temperature",
                     "Pass for this generation")
        act = autoplay.decide_action(wf, mat(heat=12),
                                     {"temperature": 8, "oxygen": 5, "oceans": 5})
        self.assertEqual(act["index"], 1)  # pass, not the dead conversion

    def test_passes_when_nothing_useful(self):
        wf = or_menu("Standard projects", "Pass for this generation",
                     "Sell patents")
        act = autoplay.decide_action(wf, mat(mc=5),
                                     {"temperature": 0, "oxygen": 5, "oceans": 5})
        self.assertEqual(act["index"], 1)


class TestFirewall(unittest.TestCase):
    def test_public_summary_hides_research_names(self):
        line = autoplay.public_summary(
            "research", kept=["Trees", "Bushes"], cost=6)
        self.assertNotIn("Trees", line)
        self.assertNotIn("Bushes", line)
        self.assertIn("2", line)

    def test_public_summary_shows_played_cards(self):
        # played cards are PUBLIC — must be named
        line = autoplay.public_summary("play", card="Trees", cost=13)
        self.assertIn("Trees", line)


class TestCardPlayPolicy(unittest.TestCase):
    def test_plays_best_positive_card_when_affordable(self):
        wf = {"type": "or", "title": "Take your first action", "options": [
            {"title": "Play project card", "type": "projectCard",
             "cards": [{"name": "Trees"}, {"name": "Fusion Power"}]},
            {"title": "Pass for this generation", "type": "option"}]}
        act = autoplay.decide_action(
            wf, mat(mc=30), {"temperature": 8, "oxygen": 8, "oceans": 9},
            gens_left=4)
        self.assertEqual(act["index"], 0)
        self.assertEqual(act["response"]["card"], "Trees")
        self.assertEqual(act["response"]["payment"]["megacredits"], 13)

    def test_passes_when_no_card_clears_value_bar(self):
        wf = {"type": "or", "title": "Take your first action", "options": [
            {"title": "Play project card", "type": "projectCard",
             "cards": [{"name": "Fusion Power"}]},
            {"title": "Pass for this generation", "type": "option"}]}
        act = autoplay.decide_action(
            wf, mat(mc=30), {"temperature": 8, "oxygen": 8, "oceans": 9},
            gens_left=3)
        self.assertEqual(act["index"], 1)


class TestInitialCardsPolicy(unittest.TestCase):
    WF = {"type": "initialCards", "title": " ", "options": [
        {"type": "card", "title": "Select corporation",
         "cards": [{"name": "Teractor"}, {"name": "UNMI"}]},
        {"type": "card", "title": "Select initial cards to buy",
         "cards": [{"name": "Trees"}, {"name": "Mine"},
                   {"name": "Fusion Power"}]},
    ]}
    GLOBALS = {"temperature": -30, "oxygen": 0, "oceans": 0}

    def test_picks_richer_corp_and_buys_within_budget(self):
        resp = autoplay.decide_initial(self.WF, self.GLOBALS, gens_left=10)
        self.assertEqual(resp["type"], "initialCards")
        corp, buys = resp["responses"]
        self.assertEqual(corp["cards"], ["Teractor"])   # 60 MC beats UNMI 40
        self.assertEqual(buys["type"], "card")
        # every buy costs 3 MC; must stay under the corp's starting MC
        self.assertLessEqual(3 * len(buys["cards"]), 60)

    def test_summary_withholds_names(self):
        line = autoplay.public_summary("initial", corp="Teractor",
                                       kept=["Trees", "Mine"])
        self.assertIn("Teractor", line)      # corp choice is public
        self.assertNotIn("Trees", line)      # bought cards are hidden
        self.assertIn("2", line)


class TestGensLeftWiring(unittest.TestCase):
    def test_gens_left_comes_from_clock_not_hardcode(self):
        game = {"generation": 1,
                "temperature": -30, "oxygenLevel": 0, "oceans": 0}
        g = autoplay._gens_left(game, players=3)
        self.assertGreaterEqual(g, 8)   # 3p prior ~11 gens, not 4

    def test_gens_left_shrinks_late(self):
        game = {"generation": 12,
                "temperature": 8, "oxygenLevel": 12, "oceans": 9}
        self.assertLessEqual(autoplay._gens_left(game, players=3), 3)


class TestStandardProjectFallback(unittest.TestCase):
    def _menu_with_sp(self):
        return {"type": "or", "title": "Take your first action", "options": [
            {"title": "Standard projects", "type": "projectCard",
             "cards": [{"name": "Power Plant:SP", "calculatedCost": 11},
                       {"name": "Asteroid:SP", "calculatedCost": 14},
                       {"name": "Aquifer", "calculatedCost": 18},
                       {"name": "Greenery", "calculatedCost": 23}]},
            {"title": "Pass for this generation", "type": "option"},
        ]}

    def test_rich_bot_buys_asteroid_sp_instead_of_passing(self):
        wf = self._menu_with_sp()
        globals_ = {"temperature": -20, "oxygen": 3, "oceans": 4}
        act = autoplay.decide_action(wf, mat(mc=120), globals_, gens_left=8)
        self.assertIsNotNone(act)
        self.assertEqual(act["index"], 0)
        self.assertEqual(act["response"]["card"], "Asteroid:SP")

    def test_asteroid_skipped_when_temp_maxed(self):
        wf = self._menu_with_sp()
        globals_ = {"temperature": 8, "oxygen": 3, "oceans": 9}
        act = autoplay.decide_action(wf, mat(mc=120), globals_, gens_left=8)
        # temp+oceans maxed → greenery is the remaining SP
        self.assertEqual(act["response"]["card"], "Greenery")

    def test_poor_bot_still_passes(self):
        wf = self._menu_with_sp()
        globals_ = {"temperature": -20, "oxygen": 3, "oceans": 4}
        act = autoplay.decide_action(wf, mat(mc=10), globals_, gens_left=8)
        # too poor for any SP → falls through to the pass option
        self.assertEqual(act["index"], 1)
        self.assertEqual(act["response"], {"type": "option"})


class TestBotLevels(unittest.TestCase):
    def test_passer_keeps_nothing_and_passes(self):
        wf = {"type": "card", "title": "Select card(s) to buy",
              "cards": [{"name": "Trees"}]}
        resp = autoplay.decide_research(wf, mat(mc=99),
                                        {"temperature": 8, "oxygen": 8,
                                         "oceans": 9}, 5, level="passer")
        self.assertEqual(resp["cards"], [])
        act = autoplay.decide_action(
            {"type": "or", "options": [
                {"title": "Play project card", "type": "projectCard"},
                {"title": "Pass for this generation", "type": "option"}]},
            mat(mc=99), {"temperature": -20, "oxygen": 0, "oceans": 0},
            gens_left=9, level="passer")
        self.assertIsNone(act)

    def test_competitive_refuses_autopilot(self):
        with self.assertRaises(autoplay.CompetitiveSeat):
            autoplay.run("pXXX", level="competitive")


class TestActionSummary(unittest.TestCase):
    def test_pass_title_summarised_as_pass(self):
        self.assertEqual(autoplay.summary_for_action(
            "Pass for this generation"), "PASSED")
        self.assertIn("converted",
                      autoplay.summary_for_action("Convert 8 plants into greenery"))
        self.assertIn("standard project",
                      autoplay.summary_for_action("Standard projects: Asteroid:SP"))


class TestPaymentPrompt(unittest.TestCase):
    """A research/card prompt can be followed by a `payment` prompt
    ("Select how to spend 6 M€ for 2 cards" — Helion, Credicor…). The bot
    answers MC-only, reading the amount from the model or the title."""

    def test_amount_field(self):
        wf = {"type": "payment", "title": "Select how to spend 6 M€ for 2 cards",
              "amount": 6}
        self.assertEqual(autoplay.decide_payment(wf)["payment"]["megacredits"], 6)

    def test_amount_parsed_from_title(self):
        wf = {"type": "payment", "title": "Select how to spend 9 M€ for 3 cards"}
        self.assertEqual(autoplay.decide_payment(wf)["payment"]["megacredits"], 9)

    def test_unknown_amount_pays_zero(self):
        self.assertEqual(autoplay.decide_payment({"type": "payment", "title": "?"})
                         ["payment"]["megacredits"], 0)
