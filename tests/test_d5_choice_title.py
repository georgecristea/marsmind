"""D5 — or-branch selection by title, not just index (Codex H4a).

Or-choice prompts are addressed by integer branch index, but the app HIDES
branches the player cannot execute — so the LIVE prompt's visible index need
not match the card data's own branch order. Codex's advisor sent
`choice=1` meaning "remove 3 microbes to increase your terraform rating 1
step" and the app performed a different branch because an earlier
(unexecutable) branch had been hidden, shifting every index after it.

Fix: `appapi.or_branch_response` accepts `choice` as an integer, a dotted
path into a submenu ("0.1"), OR a case-insensitive substring of a branch's
title in the LIVE prompt's own options — resolved against `tmlib.or_branches()`
-style titles (`appapi.prompt_title`). An ambiguous or unmatched substring
raises the existing `Ask`, naming the candidate titles, before anything is
sent. Integers and dotted paths are unchanged. This is the ONE composer
(D1) — both execute.py (advisor) and sparring.py (seats) get the fix for
free through it; neither is touched here.

No card is named anywhere here (tests/test_no_card_literals.py only scans
scripts/*.py, but the branch titles below are deliberately generic).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from appapi import Ask, or_branch_response, or_choice, option, space, target_player


def or_prompt(*options, title="Select one option") -> dict:
    return {"type": "or", "title": title, "options": list(options)}


PLAYERS = [{"name": "Anna", "color": "red"}, {"name": "Ben", "color": "yellow"}]

# Generic branch titles shaped like the Codex fixture (an or-choice with a
# TR-increase branch and a draw-a-card branch), but no real card is named.
TR_BRANCH = {"title": "Remove 3 microbes to increase your terraform rating 1 step",
            "type": "option"}
DRAW_BRANCH = {"title": "Remove 3 microbes to draw a card", "type": "option"}
DECLINE_BRANCH = {"title": "Don't remove microbes", "type": "option"}
PLAYER_BRANCH = {"title": "Select player to remove 4 M€ from", "type": "player",
                 "players": ["red"]}
SPACE_BRANCH = {"title": "Select space for special tile", "type": "space",
                "spaces": ["16", "18"]}


class TitleSelectsHiddenIndex(unittest.TestCase):
    def test_title_selects_branch_the_app_hid_an_earlier_one_of(self):
        # The full card data would order [hidden-unexecutable-branch,
        # DRAW_BRANCH, TR_BRANCH], but the app only offers what the player
        # can execute — here the LIVE prompt has TR_BRANCH at index 1, not
        # wherever the card's own branch list would have put it. An
        # integer 1 is therefore no proof it means the TR branch; the
        # title is.
        wf = or_prompt(DRAW_BRANCH, TR_BRANCH)
        response, used = or_branch_response(
            wf, "increase your terraform rating")
        self.assertEqual(response, or_choice(1, option()))
        self.assertIsNone(used)

    def test_title_match_is_case_insensitive(self):
        wf = or_prompt(DRAW_BRANCH, TR_BRANCH)
        response, _ = or_branch_response(wf, "INCREASE YOUR TERRAFORM")
        self.assertEqual(response, or_choice(1, option()))


class IntegerPathUnchanged(unittest.TestCase):
    def test_plain_integer_still_selects_by_position(self):
        wf = or_prompt(DRAW_BRANCH, TR_BRANCH)
        response, _ = or_branch_response(wf, 1)
        self.assertEqual(response, or_choice(1, option()))
        response0, _ = or_branch_response(wf, 0)
        self.assertEqual(response0, or_choice(0, option()))

    def test_stringified_integer_still_selects_by_position(self):
        wf = or_prompt(DRAW_BRANCH, TR_BRANCH)
        response, _ = or_branch_response(wf, "0")
        self.assertEqual(response, or_choice(0, option()))

    def test_dotted_integer_path_into_a_submenu_still_works(self):
        submenu = {"type": "or", "title": "submenu",
                   "options": [DECLINE_BRANCH, TR_BRANCH]}
        wf = or_prompt(DRAW_BRANCH, submenu)
        response, _ = or_branch_response(wf, "1.1")
        self.assertEqual(response, or_choice(1, or_choice(1, option())))

    def test_out_of_range_integer_still_raises_ask(self):
        wf = or_prompt(DRAW_BRANCH, TR_BRANCH)
        with self.assertRaises(Ask):
            or_branch_response(wf, 5)


class AmbiguousOrUnmatchedTitle(unittest.TestCase):
    def test_ambiguous_substring_raises_ask_listing_candidates(self):
        wf = or_prompt(TR_BRANCH, DRAW_BRANCH)
        with self.assertRaises(Ask) as cm:
            or_branch_response(wf, "remove 3 microbes")
        msg = str(cm.exception)
        self.assertIn("remove 3 microbes", msg.lower())
        self.assertIn(TR_BRANCH["title"], msg)
        self.assertIn(DRAW_BRANCH["title"], msg)

    def test_unmatched_substring_raises_ask(self):
        wf = or_prompt(TR_BRANCH, DRAW_BRANCH)
        with self.assertRaises(Ask) as cm:
            or_branch_response(wf, "launch a colony")
        self.assertIn("launch a colony", str(cm.exception).lower())

    def test_ask_from_title_resolution_names_the_prompt(self):
        # nothing gets sent — the Ask carries the prompt for the caller
        # to render, same contract as the integer-path Ask.
        wf = or_prompt(TR_BRANCH, DRAW_BRANCH)
        with self.assertRaises(Ask) as cm:
            or_branch_response(wf, "nothing matches this")
        self.assertIs(cm.exception.wf, wf)


class TitleResolvedBranchStillConsumesItsArgument(unittest.TestCase):
    def test_title_to_player_branch_without_target_raises_ask_for_target(self):
        wf = or_prompt(DECLINE_BRANCH, PLAYER_BRANCH)
        with self.assertRaises(Ask) as cm:
            or_branch_response(wf, "remove 4", players=PLAYERS)
        self.assertIn("--target", str(cm.exception))

    def test_title_to_player_branch_with_target_consumes_it(self):
        wf = or_prompt(DECLINE_BRANCH, PLAYER_BRANCH)
        response, used = or_branch_response(
            wf, "remove 4", target="Anna", players=PLAYERS)
        self.assertEqual(response, or_choice(1, target_player("red")))
        self.assertEqual(used, "player")

    def test_title_to_space_branch_without_space_raises_ask_for_space(self):
        wf = or_prompt(DECLINE_BRANCH, SPACE_BRANCH)
        with self.assertRaises(Ask) as cm:
            or_branch_response(wf, "special tile")
        self.assertIn("--space", str(cm.exception))

    def test_title_to_space_branch_with_space_consumes_it(self):
        wf = or_prompt(DECLINE_BRANCH, SPACE_BRANCH)
        response, used = or_branch_response(wf, "special tile", space="16")
        self.assertEqual(response, or_choice(1, space("16")))
        self.assertEqual(used, "space")


if __name__ == "__main__":
    unittest.main()
