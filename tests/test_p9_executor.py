"""P9 live-fire issues 1 and 2 (private/plans/p9-issues.md).

1. `execute.py resolve --choice N` always emitted `{"type": "option"}` as the
   inner response of an `or` prompt, whatever the SELECTED BRANCH's type was.
   Generation 5 (Flooding): branch [0] was a `player` branch, `--target` was
   silently dropped, and the app answered HTTP 400 "Not a valid
   SelectPlayerResponse" — while `--target` without `--choice` was refused
   outright ("this is an `or` prompt — pass --choice <n>"). No combination of
   the two flags could answer the prompt. The inner response must be built
   from the branch's own type (option / player / space / card / amount),
   generically — the same shape hits any or-prompt with such a branch.

2. There was no `sell` capability: SELL PATENTS could not be applied as an
   event (`apply.py`) nor sent as an executor action, though the app menu
   offers it and advise.py lists it. Generation 8 it blocked a Mayor claim
   after a Sabotage and had to go out through a raw `sparring.py send`.
"""
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Engine, Store, grid_to_space
from test_new_game import SETUP
from test_execute import (ExecuteCase, ScriptedApp, PID, THREATS, after,
                          root_menu, view_from_game)
import execute
import planlib
import sparring
from appapi import AppClient

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


# ── prompt shapes (vendor: OrOptions with typed branches) ─────

def or_prompt(*options) -> dict:
    return {"type": "or", "title": "Select one option", "options": list(options)}


PLAYER_BRANCH = {"title": "Select adjacent player to remove 4 M€ from",
                 "type": "player", "players": ["green", "blue"]}
DECLINE_BRANCH = {"title": "Don't remove M€ from adjacent player",
                  "type": "option"}
SPACE_BRANCH = {"title": "Select space for special tile", "type": "space",
                "spaces": ["15", "16", "17", "18"]}
CARD_BRANCH = {"title": "Select a card to discard", "type": "card",
               "cards": [{"name": "Sponsors"}, {"name": "Power Plant"}],
               "min": 1, "max": 1}
AMOUNT_BRANCH = {"title": "Select amount of heat to spend", "type": "amount",
                 "min": 0, "max": 8}

# the step whose follow-up is being resolved: tracker-only events, so the
# resolve path itself (not a card's effects) is what the test exercises
RESOLVE_STEP = {"id": "2a", "summary": "Card with an or-prompt follow-up",
                "volatility": "recheck",
                "events": [{"method": "res", "args": ["Anna", "mc", -4]}]}


class ResolveOrBranchCase(ExecuteCase):
    """`execute.py resolve <label> --choice N …` on a typed `or` branch."""

    def setUp(self):
        super().setUp()
        Engine(self.store).res("Anna", "mc", +4)    # the 4 M€ Flooding removes
        self.set_plan([RESOLVE_STEP])

    def start(self, wf):
        landed = view_from_game(after(self.store, RESOLVE_STEP["events"]),
                                root_menu())
        return self.start_app([view_from_game(self.game(), wf), landed])


class TestResolveOrPlayerBranch(ResolveOrBranchCase):
    def test_player_branch_sends_the_target_as_a_player_response(self):
        app = self.start(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0",
                               "--target", "Anna")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [{"type": "or", "index": 0,
                                      "response": {"type": "player",
                                                   "player": "green"}}])
        self.assertTrue(self.plan_step("2a")["done"])

    def test_player_branch_without_target_asks_and_sends_nothing(self):
        app = self.start(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])
        self.assertIn("--target", out)
        self.assertFalse(self.plan_step("2a").get("done"))

    def test_option_branch_still_sends_a_bare_option(self):
        app = self.start(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [{"type": "or", "index": 1,
                                      "response": {"type": "option"}}])


class TestResolveOrSpaceBranch(ResolveOrBranchCase):
    def test_space_branch_sends_the_space_response(self):
        app = self.start(or_prompt(SPACE_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0",
                               "--space", "C4")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [{"type": "or", "index": 0,
                                      "response": {"type": "space",
                                                   "spaceId": grid_to_space("C4")}}])

    def test_space_branch_without_space_asks_for_the_flag(self):
        app = self.start(or_prompt(SPACE_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])
        self.assertIn("--space", out)

    def test_space_branch_refuses_a_hex_the_branch_does_not_list(self):
        app = self.start(or_prompt(SPACE_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0",
                               "--space", "63")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])


class TestResolveOrCardAndAmountBranches(ResolveOrBranchCase):
    def test_card_branch_sends_the_named_cards(self):
        app = self.start(or_prompt(CARD_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0",
                               "--cards", "Sponsors")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [{"type": "or", "index": 0,
                                      "response": {"type": "card",
                                                   "cards": ["Sponsors"]}}])

    def test_card_branch_without_cards_asks_for_the_flag(self):
        app = self.start(or_prompt(CARD_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])
        self.assertIn("--cards", out)

    def test_amount_branch_sends_the_amount(self):
        app = self.start(or_prompt(AMOUNT_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0",
                               "--amount", "3")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [{"type": "or", "index": 0,
                                      "response": {"type": "amount",
                                                   "amount": 3}}])

    def test_a_bare_amount_prompt_is_answered_too(self):
        app = self.start({"type": "amount", "title": "Select amount of heat",
                          "min": 0, "max": 8})
        rc, out = self.run_cli("resolve", "2a", "--amount", "5")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [{"type": "amount", "amount": 5}])

    def test_amount_branch_without_amount_asks_for_the_flag(self):
        app = self.start(or_prompt(AMOUNT_BRANCH, DECLINE_BRANCH))
        rc, out = self.run_cli("resolve", "2a", "--choice", "0")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])
        self.assertIn("--amount", out)


class TestStepFollowUpOrBranch(ExecuteCase):
    """The same defect in the follow-up chain: a step whose kwargs carry
    `choice` + `target` must answer an `or` prompt's player branch with a
    player response, not a bare option."""

    def test_follow_up_or_player_branch_uses_the_steps_target(self):
        wf = or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)
        app = self.start_app([view_from_game(self.game(), wf),
                              view_from_game(self.game(), root_menu())])
        client = AppClient(app.url)
        buf = io.StringIO()
        with redirect_stdout(buf):
            execute._answer_follow_ups(
                client, PID,
                {"space": None, "or": 0, "player": "Anna", "card": None},
                print, store=self.store)
        self.assertEqual(app.posts, [{"type": "or", "index": 0,
                                      "response": {"type": "player",
                                                   "player": "green"}}])


# ── issue 2: SELL PATENTS ────────────────────────────────────

def menu_with_sell(hand=("Sponsors", "Power Plant"), **kw) -> dict:
    """The action-phase root with the app's own "Sell patents" option
    (SellPatentsStandardProject.action: a SelectCard over the hand)."""
    wf = root_menu(**kw)
    wf["options"].insert(1, {"title": "Sell patents", "type": "card",
                             "cards": [{"name": c} for c in hand],
                             "min": 0, "max": len(hand)})
    return wf


SELL_STEP = {"id": "1a", "summary": "Sell Power Plant for 1 MC",
             "volatility": "recheck",
             "events": [{"method": "standard", "args": ["Zed", "sell_patents"],
                         "kwargs": {"cards": ["Power Plant"]}}]}


class TestApplySellVerb(unittest.TestCase):
    """`apply.py sell <cards…>` — hand removal + MC, ONE logged event."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(copy.deepcopy(SETUP))
        Engine(self.store).hand_add(["Sponsors", "Power Plant", "Comet"])

    def tearDown(self):
        self.tmp.cleanup()

    def run_apply(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "apply.py"), *args],
                              cwd=self.tmp.name, capture_output=True, text=True)

    def game(self):
        return self.store.load_game()

    def log(self):
        return (Path(self.tmp.name) / "state" / "log.md").read_text()

    def test_sell_removes_the_cards_and_pays_one_mc_each(self):
        r = self.run_apply("sell", "Sponsors", "Comet")
        self.assertEqual(r.returncode, 0, r.stderr)
        g = self.game()
        self.assertEqual(g["me"]["hand"], ["Power Plant"])
        self.assertEqual(g["me"]["resources"]["mc"], 2)

    def test_sell_is_logged_as_one_event(self):
        self.run_apply("sell", "Sponsors")
        lines = [ln for ln in self.log().splitlines() if "sell_patents" in ln]
        self.assertEqual(len(lines), 1, self.log())
        self.assertIn("Sponsors", lines[0])
        self.assertIn("+1 MC", lines[0])

    def test_sell_refuses_a_card_that_is_not_in_hand(self):
        r = self.run_apply("sell", "Colonizer Training Camp")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.game()["me"]["hand"],
                         ["Sponsors", "Power Plant", "Comet"])


class TestExecuteSell(ExecuteCase):
    """`execute.py sell <cards…>` sends the app's Sell patents option and
    charges the tracker; a plan step can carry the same action."""

    def test_sell_verb_sends_the_or_wrapped_card_response(self):
        before = view_from_game(self.game(), menu_with_sell())
        landed = view_from_game(after(self.store, SELL_STEP["events"]),
                                menu_with_sell(hand=("Sponsors",)))
        app = self.start_app([before, landed])
        rc, out = self.run_cli("sell", "Power Plant")
        self.assertEqual(rc, 0, out)
        idx = sparring.find_option(before["waitingFor"], "sell patents")
        self.assertEqual(app.posts, [sparring.or_choice(
            idx, sparring.cards(["Power Plant"]))])
        g = self.game()
        self.assertEqual(g["me"]["hand"], ["Sponsors"])
        self.assertEqual(g["me"]["resources"]["mc"], 31)      # 30 + 1

    def test_sell_refuses_a_card_the_app_does_not_offer(self):
        app = self.start_app([view_from_game(self.game(),
                                             menu_with_sell(hand=("Sponsors",)))])
        rc, out = self.run_cli("sell", "Power Plant")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])

    def test_sell_asks_when_the_app_does_not_offer_sell_patents(self):
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("sell", "Power Plant")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])

    def test_a_plan_step_can_express_sell_patents(self):
        self.set_plan([SELL_STEP])
        before = view_from_game(self.game(), menu_with_sell())
        landed = view_from_game(after(self.store, SELL_STEP["events"]),
                                menu_with_sell(hand=("Sponsors",)))
        app = self.start_app([before, landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        idx = sparring.find_option(before["waitingFor"], "sell patents")
        self.assertEqual(app.posts, [sparring.or_choice(
            idx, sparring.cards(["Power Plant"]))])
        self.assertTrue(self.plan_step("1a")["done"])
        self.assertEqual(self.game()["me"]["hand"], ["Sponsors"])


if __name__ == "__main__":
    unittest.main()
