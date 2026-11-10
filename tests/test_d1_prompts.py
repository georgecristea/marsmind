"""D1 — nested prompt composer, shared by the advisor and the seat path.

Codex issue H3 (private/plans/codex-game-2026-08-29-diagnostic.md): the
advisor's `execute.py resolve` learned to build an `or` prompt's inner
response from the SELECTED BRANCH's type (P9 #1), but the seat path never
did — `sparring.py choose` always sent a bare `{"type": "option"}`:

  H3a  `or → player` (Flooding, Hired Raiders …): HTTP 400 "Not a valid
       SelectPlayerResponse"; the seat lost the action.
  H3b  the final-greenery prompt is an `or` wrapping a `space` branch
       ("Place any final greenery from plants" → [0] SelectSpace, [1] "Don't
       place a greenery"); `sparring.py space <hex>` sent a bare space
       response and got HTTP 400 "Not a valid OrOptionsResponse".

Invariant: ONE composer (`appapi.or_branch_response`), two callers. The
executor keeps its behaviour through the moved helper; the seat driver gains
`--target/--space/--cards/--amount` on `choose`, and `space` recognises the
final-greenery wrapper (`--skip` = the "Don't place" branch). A branch that
needs an argument the caller did not pass is refused BEFORE transmit, naming
the flag. No card is named anywhere (tests/test_no_card_literals.py).
"""
import copy
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, grid_to_space
from test_new_game import SETUP
import appapi
import execute
import sparring


# ── prompt shapes (vendor: OrOptions with typed branches) ─────

def or_prompt(*options, title="Select one option") -> dict:
    return {"type": "or", "title": title, "options": list(options)}


PLAYERS = [{"name": "Anna", "color": "red"},
           {"name": "Ben", "color": "yellow"},
           {"name": "Zed", "color": "green"}]

PLAYER_BRANCH = {"title": "Select adjacent player to remove 4 M€ from",
                 "type": "player", "players": ["red", "yellow"]}
DECLINE_BRANCH = {"title": "Don't remove M€ from adjacent player",
                  "type": "option"}
SPACE_BRANCH = {"title": "Select space for special tile", "type": "space",
                "spaces": [grid_to_space("C4"), "16", "18"]}
CARD_BRANCH = {"title": "Select a card to discard", "type": "card",
               "cards": [{"name": "Alpha Card"}, {"name": "Beta Card"}],
               "min": 1, "max": 1}
AMOUNT_BRANCH = {"title": "Select amount of heat to spend", "type": "amount",
                 "min": 0, "max": 8}

# Player.takeActionForFinalGreenery: an OrOptions whose branch [0] is the
# SelectSpace and branch [1] the decline option.
FINAL_GREENERY = or_prompt(
    {"title": "Select space for greenery tile", "type": "space",
     "spaces": [grid_to_space("C4"), grid_to_space("D5")]},
    {"title": "Don't place a greenery", "type": "option"},
    title="Place any final greenery from plants")

BARE_SPACE = {"type": "space", "title": "Select space for greenery tile",
              "spaces": [grid_to_space("C4"), "33"]}


def view(wf, players=PLAYERS) -> dict:
    return {"waitingFor": wf, "players": players,
            "thisPlayer": {"megacredits": 20, "terraformRating": 20},
            "game": {"generation": 5, "phase": "action"}}


class SeatCli(unittest.TestCase):
    """Drive `sparring.py` exactly as a seat does — through main()."""

    def run_cli(self, argv, v):
        sent, err = [], io.StringIO()
        with mock.patch.object(sparring, "get_player", return_value=v), \
             mock.patch.object(sparring, "send",
                               side_effect=lambda pid, r: sent.append(r)), \
             mock.patch.object(sparring, "describe_waiting",
                               return_value="ok"), \
             mock.patch("sys.argv", ["sparring.py", *argv]), \
             mock.patch("sys.stderr", err), \
             mock.patch("sys.stdout", io.StringIO()):
            code = sparring.main()
        return code, sent, err.getvalue()


# ── H3a: `or → player` and the other typed branches ──────────

class TestChooseTypedBranches(SeatCli):
    def test_or_player_branch_sends_a_player_response(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0", "--target", "Anna"],
            view(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [{"type": "or", "index": 0,
                                 "response": {"type": "player",
                                              "player": "red"}}])

    def test_or_player_branch_accepts_a_colour_directly(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0", "--target", "yellow"],
            view(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent[0]["response"], {"type": "player",
                                               "player": "yellow"})

    def test_or_space_branch_sends_a_space_response(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0", "--space", "C4"],
            view(or_prompt(SPACE_BRANCH, DECLINE_BRANCH)))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [{"type": "or", "index": 0,
                                 "response": {"type": "space",
                                              "spaceId": grid_to_space("C4")}}])

    def test_or_card_branch_sends_the_named_cards(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0", "--cards", "Alpha Card"],
            view(or_prompt(CARD_BRANCH, DECLINE_BRANCH)))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [{"type": "or", "index": 0,
                                 "response": {"type": "card",
                                              "cards": ["Alpha Card"]}}])

    def test_or_amount_branch_sends_the_amount(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0", "--amount", "3"],
            view(or_prompt(AMOUNT_BRANCH, DECLINE_BRANCH)))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [{"type": "or", "index": 0,
                                 "response": {"type": "amount", "amount": 3}}])

    def test_option_branch_still_sends_a_bare_option(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "1"], view(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [sparring.or_choice(1, sparring.option())])

    def test_title_and_player_name_still_select_the_branch(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "don't remove"],
            view(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [sparring.or_choice(1, sparring.option())])


class TestChooseMissingArgument(SeatCli):
    """A branch that needs an argument the seat did not pass: refuse BEFORE
    transmitting and NAME the flag (the seat must never guess shapes)."""

    def test_player_branch_without_target_names_the_flag(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0"], view(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)))
        self.assertNotEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn("--target", err)
        self.assertIn("player", err)

    def test_space_branch_without_space_names_the_flag(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0"], view(or_prompt(SPACE_BRANCH, DECLINE_BRANCH)))
        self.assertNotEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn("--space", err)

    def test_card_branch_without_cards_names_the_flag(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0"], view(or_prompt(CARD_BRANCH, DECLINE_BRANCH)))
        self.assertNotEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn("--cards", err)

    def test_amount_branch_without_amount_names_the_flag(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0"], view(or_prompt(AMOUNT_BRANCH, DECLINE_BRANCH)))
        self.assertNotEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn("--amount", err)

    def test_space_outside_the_branch_is_refused_before_transmit(self):
        code, sent, err = self.run_cli(
            ["choose", "p1", "0", "--space", "63"],
            view(or_prompt(SPACE_BRANCH, DECLINE_BRANCH)))
        self.assertNotEqual(code, 0)
        self.assertEqual(sent, [])


# ── H3b: the final-greenery `or → space` wrapper ─────────────

class TestSpaceVerbFinalGreenery(SeatCli):
    def test_final_greenery_place_wraps_the_space_in_the_or(self):
        code, sent, err = self.run_cli(["space", "p1", "C4"], view(FINAL_GREENERY))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [{"type": "or", "index": 0,
                                 "response": {"type": "space",
                                              "spaceId": grid_to_space("C4")}}])

    def test_final_greenery_skip_takes_the_dont_place_branch(self):
        code, sent, err = self.run_cli(["space", "p1", "--skip"],
                                       view(FINAL_GREENERY))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [sparring.or_choice(1, sparring.option())])

    def test_final_greenery_without_hex_or_skip_is_refused(self):
        code, sent, err = self.run_cli(["space", "p1"], view(FINAL_GREENERY))
        self.assertNotEqual(code, 0)
        self.assertEqual(sent, [])
        self.assertIn("--skip", err)

    def test_a_bare_space_prompt_is_unchanged(self):
        code, sent, err = self.run_cli(["space", "p1", "C4"], view(BARE_SPACE))
        self.assertEqual(code, 0, err)
        self.assertEqual(sent, [sparring.space("C4")])

    def test_skip_on_a_bare_space_prompt_is_refused(self):
        code, sent, err = self.run_cli(["space", "p1", "--skip"], view(BARE_SPACE))
        self.assertNotEqual(code, 0)
        self.assertEqual(sent, [])


class TestFollowUpUsesTheComposer(unittest.TestCase):
    """`play … --choice 0 --target red`: the follow-up chain feeds the
    remaining flags into the selected branch instead of a bare option."""

    def _run(self, states, **flags):
        it = iter(states)
        sent = []
        sparring.follow_up("p1", get=lambda pid: next(it),
                           post=lambda pid, r: sent.append(r), **flags)
        return sent

    def test_or_player_branch_consumes_the_target(self):
        sent = self._run([view(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)),
                          {"waitingFor": None}], choice=0, target="yellow")
        self.assertEqual(sent, [{"type": "or", "index": 0,
                                 "response": {"type": "player",
                                              "player": "yellow"}}])

    def test_option_branch_then_stop(self):
        sent = self._run([view(or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)),
                          {"waitingFor": None}], choice=1)
        self.assertEqual(sent, [sparring.or_choice(1, sparring.option())])


# ── one composer, two callers ─────────────────────────────────

class TestExecutorUsesTheMovedHelper(unittest.TestCase):
    """The advisor path is unchanged: execute.py imports the composer from
    appapi (no second implementation) and the player-branch payload is the
    one the P9 tests pinned."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(copy.deepcopy(SETUP))

    def tearDown(self):
        self.tmp.cleanup()

    def test_execute_binds_the_appapi_composer(self):
        self.assertIs(execute._or_branch_response, appapi.or_branch_response)
        self.assertIs(execute._player_color, appapi.player_color)
        self.assertIs(execute.Ask, appapi.Ask)
        self.assertIs(sparring.or_branch_response, appapi.or_branch_response)

    def test_player_branch_payload_through_the_store(self):
        wf = or_prompt({"title": "Select adjacent player to remove 4 M€ from",
                        "type": "player", "players": ["green", "blue"]},
                       DECLINE_BRANCH)
        response, used = execute._or_branch_response(
            wf, 0, store=self.store, target="Anna")
        self.assertEqual(response, {"type": "or", "index": 0,
                                    "response": {"type": "player",
                                                 "player": "green"}})
        self.assertEqual(used, "player")

    def test_missing_target_raises_the_executors_ask(self):
        wf = or_prompt(PLAYER_BRANCH, DECLINE_BRANCH)
        with self.assertRaises(execute.Ask) as cm:
            execute._or_branch_response(wf, 0, store=self.store)
        self.assertIn("--target", str(cm.exception))
        self.assertIs(cm.exception.wf, wf)

    def test_seat_and_advisor_compose_the_same_payload(self):
        wf = or_prompt(SPACE_BRANCH, DECLINE_BRANCH)
        advisor, _ = execute._or_branch_response(wf, 0, store=self.store,
                                                 space="C4")
        seat = sparring.choose(wf, 0, space="C4")
        self.assertEqual(advisor, seat)


class TestHelpNamesTheFlags(unittest.TestCase):
    def test_module_usage_shows_the_choose_flags_and_skip(self):
        doc = sparring.__doc__
        for flag in ("--target", "--space", "--cards", "--amount", "--skip"):
            self.assertIn(flag, doc)


if __name__ == "__main__":
    unittest.main()
