"""Iron rule 2 (AGENTS.md): every state change goes through a script verb
that LOGS it — never a hand edit of the state dict.

verify.py's own-tableau and card-resource adoption wrote
me["playedCards"] / pool["cardResources"] directly and then called the
engine's private _commit, so the change existed but no verb owned it. These
are the audited verbs it uses instead.

Plus: planlib.mark_done(apply_events=True) applied a step's events one at a
time, each committing on its own — a step whose 3rd event was illegal left
the first two applied and the step NOT done, which is the worst state to
recover from at a table. It is transactional now.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import planlib
from tmlib import Engine, EventError, Store


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

    def log(self):
        return self.store.log_path.read_text()


class TestObservePlayForMe(Base):
    """A card the app shows in MY tableau that the tracker lacks: recorded
    as BOOKKEEPING (no cost, no behavior) — the numeric sync that follows
    adopts the app's figures, so applying effects here would double-count."""

    def test_my_own_card_needs_the_explicit_flag(self):
        with self.assertRaises(EventError) as cm:
            self.eng.observe_play("Zed", "Ironworks")
        self.assertIn("allow_me", str(cm.exception))
        self.assertEqual(self.game()["me"]["playedCards"], [])

    def test_allow_me_records_the_card_and_logs_it(self):
        msg = self.eng.observe_play("Zed", "ironworks", allow_me=True)
        me = self.game()["me"]
        self.assertEqual([c["name"] for c in me["playedCards"]], ["Ironworks"])
        self.assertEqual(me["playedCards"][0]["gen"], 1)
        self.assertIn("observed from app", msg)
        self.assertIn("Ironworks", self.log())

    def test_no_cost_and_no_behavior_is_applied(self):
        mc = self.game()["me"]["resources"]["mc"]
        self.eng.observe_play("Zed", "Ironworks", allow_me=True)
        me = self.game()["me"]
        self.assertEqual(me["resources"]["mc"], mc)
        self.assertEqual(me["production"], {"mc": 0, "steel": 0,
                                            "titanium": 0, "plants": 0,
                                            "energy": 0, "heat": 0})

    def test_a_blue_action_card_reaches_the_ledger(self):
        # the whole point for verify.py: an action the app offers must be
        # offered by the menu too
        self.eng.observe_play("Zed", "Physics Complex", allow_me=True)
        self.assertIn("Physics Complex", self.game()["me"]["actionsThisGen"])

    def test_a_duplicate_is_refused(self):
        self.eng.observe_play("Zed", "Ironworks", allow_me=True)
        with self.assertRaises(EventError):
            self.eng.observe_play("Zed", "Ironworks", allow_me=True)

    def test_an_opponent_still_needs_no_flag(self):
        self.eng.observe_play("Anna", "Ironworks")
        self.assertEqual(
            [c["name"] for c in self.game()["opponents"]["Anna"]["playedCards"]],
            ["Ironworks"])


class TestSyncCardResources(Base):
    """Per-card accumulators (animals, microbes, science, floaters) adopted
    from the app — they are VP at scoring time, so the change is logged."""

    def test_adopts_and_logs(self):
        msg = self.eng.sync_card_resources("Zed", {"Physics Complex": 3})
        self.assertEqual(self.game()["me"]["cardResources"],
                         {"Physics Complex": 3})
        self.assertIn("unknown → 3", msg)     # never observed before
        self.assertIn("Physics Complex", self.log())

    def test_zero_is_kept_as_knowledge(self):
        # W2-A: an observed 0 is knowledge — only a count that was NEVER
        # observed stays absent (score.py bounds it instead of guessing 0)
        self.eng.sync_card_resources("Zed", {"Physics Complex": 3})
        msg = self.eng.sync_card_resources("Zed", {"Physics Complex": 0})
        self.assertEqual(self.game()["me"]["cardResources"],
                         {"Physics Complex": 0})
        self.assertIn("3 → 0", msg)

    def test_no_change_is_a_no_op_with_no_log_line(self):
        self.eng.sync_card_resources("Zed", {"Physics Complex": 3})
        before = self.log()
        msg = self.eng.sync_card_resources("Zed", {"Physics Complex": 3})
        self.assertEqual(self.log(), before)
        self.assertIn("no change", msg.lower())

    def test_works_for_an_opponent(self):
        self.eng.sync_card_resources("Anna", {"Predators": 4})
        self.assertEqual(self.game()["opponents"]["Anna"]["cardResources"],
                         {"Predators": 4})

    def test_canonical_card_spelling(self):
        self.eng.sync_card_resources("Zed", {"physics complex": 2})
        self.assertEqual(self.game()["me"]["cardResources"],
                         {"Physics Complex": 2})

    def test_unknown_player_refused(self):
        with self.assertRaises(EventError):
            self.eng.sync_card_resources("Nobody", {"Predators": 1})

    def test_a_negative_count_is_refused(self):
        with self.assertRaises(EventError):
            self.eng.sync_card_resources("Zed", {"Physics Complex": -1})


class TestMarkDoneIsTransactional(Base):
    def plan_with(self, events):
        planlib.set_plan(self.store, {
            "threats": "Anna: nothing pending; Ben: nothing pending",
            "exit": "test exit; repeatable: n/a",
            "steps": [{"id": "1a", "summary": "test step",
                       "volatility": "safe", "events": events}],
        })

    def test_an_illegal_later_event_applies_none_of_them(self):
        # the plan was legal when it was composed (set_plan simulates it);
        # the table moved since — an attack took the plants
        self.eng.res("Zed", "mc", +10)
        self.eng.res("Zed", "plants", +3)
        self.plan_with([
            {"method": "res", "args": ["Zed", "mc", -5]},
            {"method": "res", "args": ["Zed", "plants", -3]},
        ])
        self.eng.attack("Zed", "plants", 3, by="Anna")
        with self.assertRaises(EventError) as cm:
            planlib.mark_done(self.store, "1a", apply_events=True)
        text = str(cm.exception)
        self.assertIn("1a", text)
        self.assertIn("event 2 of 2", text)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 10)
        self.assertFalse(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_a_legal_step_still_applies_every_event(self):
        self.eng.res("Zed", "mc", +10)
        self.eng.res("Zed", "plants", +4)
        self.plan_with([
            {"method": "res", "args": ["Zed", "mc", -5]},
            {"method": "res", "args": ["Zed", "plants", -3]},
        ])
        planlib.mark_done(self.store, "1a", apply_events=True, verify=False)
        res = self.game()["me"]["resources"]
        self.assertEqual((res["mc"], res["plants"]), (5, 1))
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])


if __name__ == "__main__":
    unittest.main()
