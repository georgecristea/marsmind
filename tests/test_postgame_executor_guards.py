"""Executor guards from the blind 2p game (Distant Neutron Surge).

D2 — a numeric `or` branch index is trusted blind. In generation 8 the
opposing seat's step said choice 1 meaning "remove 2 microbes" while the
LIVE app's index 1 was "add 1 microbe". A WRONG ACTION was transmitted and
only app adoption made the state coherent again. or_branch_response already
accepts a title substring instead of an index (added after an earlier
incident); what was missing is a guard for steps that still pass a number.
A step may now carry `choiceLabel`, and the resolved branch's title must
contain it or nothing is sent.

D4 — plant-removal prompts arrive as an `or` menu whose branches are
players, not as the bare `player` selector that follow["player"] answers, so
a correct `target` kwarg went unused on Comet and Giant Ice Asteroid and both
needed a manual `execute.py resolve`. When a step carries `target`, an `or`
with exactly one `player` branch now selects itself.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import appapi
import execute
from appapi import Ask, or_branch_response


GHG = {"type": "or", "title": "Select action for GHG Producing Bacteria",
       "options": [{"type": "option", "title": "Add 1 microbe to this card"},
                   {"type": "option", "title": "Remove 2 microbes to raise temperature"}]}


class TestNumericChoiceIsGuarded(unittest.TestCase):

    def test_matching_label_passes_and_selects_that_index(self):
        resp, _ = or_branch_response(GHG, 1, expect="remove 2 microbes")
        self.assertEqual(resp["index"], 1)

    def test_mismatched_label_refuses_and_sends_nothing(self):
        """The exact in-game failure: index 1 meant the other branch."""
        with self.assertRaises(Ask) as ctx:
            or_branch_response(GHG, 1, expect="add 1 microbe")
        msg = str(ctx.exception)
        self.assertIn("add 1 microbe", msg.lower())
        self.assertIn("remove 2 microbes", msg.lower())

    def test_label_alone_still_works_without_an_index(self):
        resp, _ = or_branch_response(GHG, "remove 2 microbes")
        self.assertEqual(resp["index"], 1)

    def test_no_label_is_unchanged_behaviour(self):
        resp, _ = or_branch_response(GHG, 1)
        self.assertEqual(resp["index"], 1)

    def test_plan_step_carries_choiceLabel_into_the_follow_up(self):
        step = {"id": "1a", "events": [
            {"method": "use_action",
             "args": ["GHG Producing Bacteria", "Mortimer"],
             "kwargs": {"choice": 1, "choiceLabel": "remove 2 microbes"}}]}
        follow = execute.plan_actions(step)[0]["follow"]
        self.assertEqual(follow["or"], 1)
        self.assertEqual(follow["orExpect"], "remove 2 microbes")


class TestPlayerBranchAutoSelect(unittest.TestCase):

    REMOVAL = {"type": "or", "title": "Select player to remove plants from",
               "options": [{"type": "player", "title": "Remove 4 plants",
                            "players": ["red"]}]}

    def test_target_alone_answers_an_or_wrapped_player_prompt(self):
        sent = []
        prompts = [dict(self.REMOVAL), None]

        class Client:
            def player(self, pid):
                return {"waitingFor": prompts.pop(0)} if prompts else {}

        with mock.patch.object(execute, "_send",
                               side_effect=lambda c, p, r, w, o: sent.append(r)), \
             mock.patch.object(appapi, "player_color", return_value="red"):
            follow = {"space": None, "spaceQueue": [], "or": None,
                      "orExpect": None, "player": "Maxwell", "card": None}
            execute._answer_follow_ups(Client(), "pid", follow,
                                       out=lambda *a: None)
        self.assertEqual(len(sent), 1, "the or-wrapped removal must be answered")
        self.assertEqual(sent[0]["index"], 0)

    def test_two_player_branches_are_ambiguous_and_refuse(self):
        wf = {"type": "or", "title": "Select",
              "options": [{"type": "player", "title": "Remove plants"},
                          {"type": "player", "title": "Remove heat"}]}
        prompts = [wf]

        class Client:
            def player(self, pid):
                return {"waitingFor": prompts.pop(0)} if prompts else {}

        with mock.patch.object(execute, "_send"):
            follow = {"space": None, "spaceQueue": [], "or": None,
                      "orExpect": None, "player": "Maxwell", "card": None}
            with self.assertRaises(Ask):
                execute._answer_follow_ups(Client(), "pid", follow,
                                           out=lambda *a: None)

    def test_explicit_choice_still_wins_over_auto_select(self):
        resp, used = or_branch_response(self.REMOVAL, 0, target="Maxwell",
                                        players=[{"name": "Maxwell",
                                                  "color": "red"}])
        self.assertEqual(resp["index"], 0)
        self.assertEqual(used, "player")


if __name__ == "__main__":
    unittest.main()
