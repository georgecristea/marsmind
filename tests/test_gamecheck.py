"""gamecheck.py: single-call whole-game 'who is it waiting on' status table.

Every 'stuck' incident (premature produce.py, missed redispatch,
un-checked own turn) has the same root cause -- reading ONE player's waitingFor in isolation and
inferring something about the whole game from it. This script removes
that inference: it always shows every player's status side by side, so
there is nothing left to misread.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import gamecheck


class TestSummarize(unittest.TestCase):
    def test_exactly_one_waiting_is_normal(self):
        rows = [
            {"name": "Zed", "waiting": True, "title": "Take your first action"},
            {"name": "Ana", "waiting": False, "title": None},
            {"name": "Ben", "waiting": False, "title": None},
        ]
        report = gamecheck.summarize(rows)
        self.assertFalse(report.anomaly)
        self.assertEqual(report.waiting_on, ["Zed"])

    def test_nobody_waiting_is_flagged(self):
        rows = [
            {"name": "Zed", "waiting": False, "title": None},
            {"name": "Ana", "waiting": False, "title": None},
        ]
        report = gamecheck.summarize(rows)
        self.assertTrue(report.anomaly)
        self.assertIn("nobody", report.headline.lower())

    def test_multiple_waiting_is_flagged(self):
        # shouldn't happen in a synchronous-turn game; surface it loudly
        rows = [
            {"name": "Zed", "waiting": True, "title": "x"},
            {"name": "Ana", "waiting": True, "title": "y"},
        ]
        report = gamecheck.summarize(rows)
        self.assertTrue(report.anomaly)
        self.assertEqual(set(report.waiting_on), {"Zed", "Ana"})

    def test_all_waiting_on_same_research_title_is_not_an_anomaly(self):
        # research/card-buy is the ONE phase
        # where every player waits simultaneously -- not a stall. Only flag
        # 'multiple waiting' when the titles actually differ (mid-action-
        # phase overlap, which IS suspicious).
        rows = [
            {"name": "Zed", "waiting": True, "title": "Select card(s) to buy"},
            {"name": "Ana", "waiting": True, "title": "Select card(s) to buy"},
            {"name": "Ben", "waiting": True, "title": "Select card(s) to buy"},
        ]
        report = gamecheck.summarize(rows)
        self.assertFalse(report.anomaly)
        self.assertEqual(set(report.waiting_on), {"Zed", "Ana", "Ben"})

    def test_multiple_waiting_different_titles_still_flagged(self):
        rows = [
            {"name": "Zed", "waiting": True, "title": "Select card(s) to buy"},
            {"name": "Ana", "waiting": True, "title": "Take your first action"},
        ]
        report = gamecheck.summarize(rows)
        self.assertTrue(report.anomaly)

    def test_render_lists_every_player(self):
        rows = [
            {"name": "Zed", "waiting": True, "title": "Take your first action"},
            {"name": "Ana", "waiting": False, "title": None},
        ]
        text = gamecheck.render(rows)
        self.assertIn("Zed", text)
        self.assertIn("Ana", text)
        self.assertIn("WAITING", text)


class TestGameCheck(unittest.TestCase):
    def test_pulls_status_for_every_configured_player(self):
        players = [{"name": "Zed", "playerId": "p1"},
                   {"name": "Ana", "playerId": "p2"}]
        calls = []

        def fake_get(pid):
            calls.append(pid)
            if pid == "p1":
                return {"waitingFor": {"title": "Take your first action"}}
            return {"waitingFor": None}

        rows = gamecheck.check_all(players, get=fake_get)
        self.assertEqual(calls, ["p1", "p2"])
        self.assertEqual(rows[0], {"name": "Zed", "waiting": True,
                                   "title": "Take your first action"})
        self.assertEqual(rows[1], {"name": "Ana", "waiting": False, "title": None})

    def test_get_failure_surfaces_as_unknown_not_silently_dropped(self):
        players = [{"name": "Zed", "playerId": "p1"}]

        def failing_get(pid):
            raise OSError("connection refused")

        rows = gamecheck.check_all(players, get=failing_get)
        self.assertEqual(rows[0]["name"], "Zed")
        self.assertIsNone(rows[0]["waiting"])
        self.assertIn("ERROR", rows[0]["title"])


if __name__ == "__main__":
    unittest.main()
