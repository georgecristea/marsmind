"""scripts/e2e_practice.py — the scripted end-to-end proof (no model).
The pure parts are unit-tested here; the network run is the script's job."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import e2e_practice as E                      # noqa: E402


def _wf_initial(corps, cards):
    return {"type": "initialCards", "title": "Initial Research Phase",
            "options": [
                {"type": "card", "title": "Select corporation",
                 "cards": [{"name": c} for c in corps]},
                {"type": "card", "title": "Select initial cards to buy",
                 "cards": [{"name": c} for c in cards]}]}


class TestSetupAnswers(unittest.TestCase):
    def test_answers_follow_setup_py_prompt_order(self):
        text = E.setup_answers("Zed", "red", [("Anna", "green"), ("Ben", "yellow")],
                               "http://localhost:8080", "p-zed")
        lines = text.split("\n")
        # name, color, opponents, expansions, map, draft, seating, first,
        # house-rules terminator, mode, url, pid
        self.assertEqual(lines[0], "Zed")
        self.assertEqual(lines[1], "red")
        self.assertEqual(lines[2], "Anna=green,Ben=yellow")
        self.assertEqual(lines[3:9], [""] * 6)
        self.assertEqual(lines[9:12], ["app-practice", "http://localhost:8080", "p-zed"])


class TestPromptChoices(unittest.TestCase):
    def test_first_corp_is_the_first_dealt(self):
        wf = _wf_initial(["Helion", "Teractor"], ["Comet", "Sponsors"])
        self.assertEqual(E.first_corp(wf), "Helion")

    def test_first_corp_prefers_one_without_a_first_action(self):
        # Tharsis Republic / Inventrix open with a "Take first action" prompt
        wf = _wf_initial(["Tharsis Republic", "Helion"], [])
        self.assertEqual(E.first_corp(wf), "Helion")
        wf = _wf_initial(["Tharsis Republic", "Inventrix"], [])
        self.assertEqual(E.first_corp(wf), "Tharsis Republic")

    def test_first_corp_none_without_corporation_option(self):
        self.assertIsNone(E.first_corp({"type": "initialCards", "options": []}))

    def test_offered_names_reads_dicts_and_strings(self):
        wf = {"type": "card", "cards": [{"name": "Comet"}, "Sponsors"]}
        self.assertEqual(E.offered_names(wf), ["Comet", "Sponsors"])


class TestSimpleCards(unittest.TestCase):
    """--greedy plays only cards the executor can send without follow-ups
    and the engine can verify blind: production / stock / TR / global
    parameter effects, nothing that draws, places, targets or chooses."""

    def test_production_card_is_simple(self):
        self.assertTrue(E.simple_card({"name": "Acquired Company", "cost": 10,
                                       "type": "automated",
                                       "behavior": {"production": {"megacredits": 3}}}))

    def test_tile_target_draw_choice_are_not(self):
        for beh in ({"ocean": 1}, {"city": {}}, {"greenery": 1}, {"tile": "x"},
                    {"drawCard": 2}, {"removeAnyPlants": 3},
                    {"decreaseAnyProduction": {"energy": 1}}, {"or": {}},
                    {"addResourcesToAnyCard": {}}):
            self.assertFalse(E.simple_card({"name": "X", "cost": 1, "type": "automated",
                                            "behavior": beh}), beh)

    def test_corporation_never_simple(self):
        self.assertFalse(E.simple_card({"name": "Helion", "type": "corporation",
                                        "behavior": {}}))

    def test_pick_buys_filters_to_simple_and_budget(self):
        db = {"Acquired Company": {"name": "Acquired Company", "cost": 10,
                                   "type": "automated",
                                   "behavior": {"production": {"megacredits": 3}}},
              "Comet": {"name": "Comet", "cost": 21, "type": "event",
                        "behavior": {"global": {"temperature": 1}, "ocean": 1}},
              "Sponsors": {"name": "Sponsors", "cost": 6, "type": "automated",
                           "behavior": {"production": {"megacredits": 2}}}}
        names = ["Comet", "Acquired Company", "Sponsors", "Unknown Card"]
        self.assertEqual(E.pick_buys(names, db.get, mc=40, limit=2),
                         ["Sponsors", "Acquired Company"])
        self.assertEqual(E.pick_buys(names, db.get, mc=40, limit=1), ["Sponsors"])
        self.assertEqual(E.pick_buys(names, db.get, mc=2, limit=2), [])


class TestGreedyPlan(unittest.TestCase):
    def test_plan_from_menu_item_play(self):
        items = [{"kind": "card", "name": "Sponsors", "cost": 6, "label": "play Sponsors"},
                 {"kind": "pass", "name": "pass"}]
        plan = E.greedy_plan("Zed", items, db_get=lambda n: {
            "name": "Sponsors", "cost": 6, "type": "automated",
            "behavior": {"production": {"megacredits": 2}}}.copy() if n == "Sponsors"
            else None)
        self.assertEqual(plan["threats"], E.THREATS)
        ids = [s["id"] for s in plan["steps"]]
        self.assertEqual(ids, ["1a", "1b"])
        self.assertEqual(plan["steps"][0]["events"],
                         [{"method": "play", "args": ["Zed", "Sponsors"], "kwargs": {}}])
        self.assertTrue(plan["steps"][1]["passGate"])
        self.assertEqual(plan["steps"][1]["events"], [])

    def test_plan_falls_back_to_asteroid_then_pass_only(self):
        items = [{"kind": "standard", "name": "asteroid", "cost": 14},
                 {"kind": "standard", "name": "city", "cost": 25}]
        plan = E.greedy_plan("Zed", items, db_get=lambda n: None)
        self.assertEqual(plan["steps"][0]["events"][0]["args"], ["Zed", "asteroid"])
        plan = E.greedy_plan("Zed", [{"kind": "standard", "name": "city"}],
                             db_get=lambda n: None)
        self.assertEqual([s["id"] for s in plan["steps"]], ["1a"])
        self.assertTrue(plan["steps"][0]["passGate"])


class TestSummary(unittest.TestCase):
    def test_feed_stats_counts_applied_and_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "feed.jsonl"
            p.write_text("\n".join(json.dumps(e) for e in [
                {"applied": True, "error": None},
                {"applied": False, "error": "unknown: x"},
                {"applied": True, "error": None}]) + "\n")
            self.assertEqual(E.feed_stats(p), {"lines": 3, "applied": 2, "gaps": 1,
                                               "gapLines": ["unknown: x"]})
            self.assertEqual(E.feed_stats(Path(tmp) / "none.jsonl")["lines"], 0)

    def test_exit_code_zero_only_when_clean(self):
        s = E.Summary()
        self.assertEqual(s.exit_code(), 0)
        s.drift_incidents.append("G2 Zed mc 40→41")
        self.assertEqual(s.exit_code(), 2)
        s = E.Summary()
        s.refusals.append("execute.py pick exit 40")
        self.assertEqual(s.exit_code(), 3)
        s = E.Summary()
        s.errors.append("app down")
        self.assertEqual(s.exit_code(), 1)

    def test_format_summary_lists_the_numbers(self):
        s = E.Summary(generations=3, own_turns=5, wall=12.5)
        s.feed = {"lines": 40, "applied": 38, "gaps": 2, "gapLines": ["unknown: q"]}
        text = E.format_summary(s)
        self.assertIn("generations played: 3", text)
        self.assertIn("own turns: 5", text)
        self.assertIn("feed lines: 40 applied 38 gaps 2", text)
        self.assertIn("drift incidents: 0", text)
        self.assertIn("wall-clock: 12.5s", text)


class TestDriftParse(unittest.TestCase):
    def test_parse_verify_output(self):
        out = ("  globals    exact\n  Zed        exact\n"
               "  Anna       DRIFT  mc: 30→28, tableau: +Comet\n")
        rows = E.parse_verify(out)
        self.assertEqual(rows, {"globals": "", "Zed": "",
                                "Anna": "mc: 30→28, tableau: +Comet"})


if __name__ == "__main__":
    unittest.main()
