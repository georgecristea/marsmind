"""ONE or-branch selector grammar (fix plan item 2).

The practice game drove Nitrite Reducing Bacteria's action with
`choice: 1` meaning "remove 3 microbes" and the app executed "add 1
microbe". Two defects:

2a — the mismatch guard was never armed: `execute.py` read `choiceLabel`
from the EVENT's kwargs while the plan step carried it at STEP top level,
so `expect` was None and `or_branch_response` never checked.

2b — two grammars for one concept: the transmitter resolves an int, a
dotted path OR a title substring against the APP's live options, while the
simulator (`tmlib.use_action`) accepted only an int indexing the CARD-TEXT
branch order. When the two orders disagree the same integer means two
different branches — and one branch was not expressible at all.

The fix is ONE matcher (`appapi.match_branch`) shared by both layers, ONE
normalisation point in execute, and a planlib gate that makes the safe form
(a title) the easy form. No card is named in any of it.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import appapi                                        # noqa: E402
import execute                                       # noqa: E402
import planlib                                       # noqa: E402
import tmlib                                         # noqa: E402
from appapi import Ask, match_branch                 # noqa: E402
from tmlib import Store, Engine, EventError          # noqa: E402


# The card whose two orders disagree, as the two layers see it. The db
# (and the app) list the removal branch first; the printed card text reads
# "Add 1 microbe to this card, or remove 3 microbes …", so tmlib's
# card-text ordering puts the ADD branch at index 0. Same card, two
# integers — which is the whole bug.
OR_CARD = "Nitrite Reducing Bacteria"
APP_ORDER = ["Remove 3 microbes to increase your terraform rating 1 step",
             "Add 1 microbe to this card"]


class TestMatchBranch(unittest.TestCase):
    """The one matcher: titles in, index out, generic."""

    TITLES = ["Add 1 microbe to this card",
              "Remove 3 microbes to increase your terraform rating 1 step"]

    def test_exact_title(self):
        self.assertEqual(match_branch(self.TITLES, self.TITLES[0]), 0)

    def test_substring(self):
        self.assertEqual(match_branch(self.TITLES, "remove 3 microbes"), 1)

    def test_case_insensitive(self):
        self.assertEqual(match_branch(self.TITLES, "ADD 1 MICROBE"), 0)

    def test_ambiguous_refuses_naming_the_candidates(self):
        with self.assertRaises(ValueError) as cm:
            match_branch(self.TITLES, "microbe")
        msg = str(cm.exception)
        self.assertIn("microbe", msg.lower())
        for t in self.TITLES:
            self.assertIn(t, msg)

    def test_no_match_refuses_naming_the_options(self):
        with self.assertRaises(ValueError) as cm:
            match_branch(self.TITLES, "launch a colony")
        self.assertIn("launch a colony", str(cm.exception).lower())
        self.assertIn(self.TITLES[0], str(cm.exception))

    def test_the_appapi_transmitter_uses_the_same_matcher(self):
        wf = {"type": "or", "title": "Select action",
              "options": [{"type": "option", "title": t} for t in APP_ORDER]}
        resp, _ = appapi.or_branch_response(wf, "remove 3 microbes")
        self.assertEqual(resp["index"], 0)          # the APP's own order


class Base(unittest.TestCase):
    SETUP = {
        "playerCount": 2,
        "players": [
            {"name": "Zed", "color": "red", "isMe": True, "aliases": ["red"]},
            {"name": "Anna", "color": "green", "isMe": False, "aliases": []},
        ],
        "expansions": ["base", "corporateEra"],
        "map": "tharsis",
        "draft": False,
        "houseRules": [],
        "seatingOrder": ["Zed", "Anna"],
        "firstPlayerGen1": "Zed",
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

    def play_or_card(self, microbes: int = 0):
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add([OR_CARD])
        self.eng.play("Zed", OR_CARD)
        if microbes:
            g = self.store.load_game()
            g["me"]["cardResources"][OR_CARD] = microbes
            self.store.save_game(g)

    def reset_ledger(self):
        g = self.store.load_game()
        g["me"]["actionsThisGen"][OR_CARD]["used"] = False
        self.store.save_game(g)


class TestUseActionTitleSelector(Base):
    """The simulator speaks the same grammar as the transmitter."""

    def test_the_two_orders_really_disagree(self):
        """The regression's precondition, asserted rather than assumed."""
        info = self.eng.card(OR_CARD)
        branches = tmlib.or_branches(info, behavior=info["actionBehavior"],
                                     text=info["action"])
        text_titles = [b["title"] for b in branches]
        self.assertIn("Add 1 microbe", text_titles[0])
        # …while the app puts the removal branch first: the same integer
        # names two different branches.
        self.assertNotEqual(match_branch(text_titles, "remove 3 microbes"),
                            match_branch(APP_ORDER, "remove 3 microbes"))

    def test_title_selector_picks_the_removal_branch(self):
        self.play_or_card(microbes=3)
        tr_before = self.game()["me"]["tr"]
        self.eng.use_action(OR_CARD, choice="remove 3 microbes")
        me = self.game()["me"]
        self.assertEqual(me["tr"], tr_before + 1)
        self.assertEqual(me["cardResources"][OR_CARD], 0)

    def test_title_selector_picks_the_add_branch(self):
        """Unexpressible before: at 1 microbe the int meant the other
        branch and the sandbox refused for lacking microbes."""
        self.play_or_card(microbes=1)
        tr_before = self.game()["me"]["tr"]
        self.eng.use_action(OR_CARD, choice="add 1 microbe")
        me = self.game()["me"]
        self.assertEqual(me["cardResources"][OR_CARD], 2)
        self.assertEqual(me["tr"], tr_before)

    def test_int_selectors_still_work(self):
        self.play_or_card(microbes=3)
        tr_before = self.game()["me"]["tr"]
        self.eng.use_action(OR_CARD, choice=1)      # card-text order: remove
        self.assertEqual(self.game()["me"]["tr"], tr_before + 1)

    def test_ambiguous_title_refuses_naming_the_branches(self):
        self.play_or_card(microbes=3)
        with self.assertRaises(EventError) as cm:
            self.eng.use_action(OR_CARD, choice="microbe")
        msg = str(cm.exception)
        self.assertIn("Add 1 microbe", msg)
        self.assertIn("Remove 3 microbes", msg)

    def test_unmatched_title_refuses(self):
        self.play_or_card(microbes=3)
        with self.assertRaises(EventError) as cm:
            self.eng.use_action(OR_CARD, choice="launch a colony")
        self.assertIn("launch a colony", str(cm.exception).lower())


class TestUnuseActionSpeaksTheSameGrammar(Base):
    """correct.py reverses a step with the kwargs the step carried — a
    title selector must not reach the reversal as a raw string (it would
    be compared to an index and crash, not refuse)."""

    def test_a_title_selector_reverses_the_branch_it_applied(self):
        self.play_or_card(microbes=3)
        tr_before = self.game()["me"]["tr"]
        self.eng.use_action(OR_CARD, choice="remove 3 microbes")
        self.eng.unuse_action(OR_CARD, choice="remove 3 microbes")
        me = self.game()["me"]
        self.assertEqual(me["tr"], tr_before)
        self.assertEqual(me["cardResources"][OR_CARD], 3)
        self.assertFalse(me["actionsThisGen"][OR_CARD]["used"])


class TestExecuteNormalisation(unittest.TestCase):
    """ONE place reads the selector, from either home, preferring the step."""

    @staticmethod
    def step(step_kw: dict, ev_kw: dict) -> dict:
        return {"id": "1a", **step_kw,
                "events": [{"method": "use_action", "args": [OR_CARD, "Zed"],
                            "kwargs": ev_kw}]}

    def test_label_at_step_level_is_read(self):
        s = self.step({"choiceLabel": "remove 3 microbes"}, {"choice": 1})
        follow = execute.plan_actions(s)[0]["follow"]
        self.assertEqual(follow["orExpect"], "remove 3 microbes")
        self.assertEqual(follow["or"], 1)

    def test_label_in_kwargs_is_read(self):
        s = self.step({}, {"choice": 1, "choiceLabel": "remove 3 microbes"})
        follow = execute.plan_actions(s)[0]["follow"]
        self.assertEqual(follow["orExpect"], "remove 3 microbes")

    def test_both_present_and_agreeing_is_fine(self):
        s = self.step({"choiceLabel": "remove 3 microbes"},
                      {"choice": 1, "choiceLabel": "remove 3 microbes"})
        follow = execute.plan_actions(s)[0]["follow"]
        self.assertEqual(follow["orExpect"], "remove 3 microbes")

    def test_both_present_and_conflicting_refuses_naming_both(self):
        s = self.step({"choiceLabel": "add 1 microbe"},
                      {"choice": 1, "choiceLabel": "remove 3 microbes"})
        with self.assertRaises(Ask) as cm:
            execute.plan_actions(s)
        msg = str(cm.exception).lower()
        self.assertIn("add 1 microbe", msg)
        self.assertIn("remove 3 microbes", msg)

    def test_step_level_choice_is_read_too(self):
        s = self.step({"choice": "remove 3 microbes"}, {})
        follow = execute.plan_actions(s)[0]["follow"]
        self.assertEqual(follow["or"], "remove 3 microbes")

    def test_conflicting_choices_refuse_naming_both(self):
        s = self.step({"choice": 0}, {"choice": 1})
        with self.assertRaises(Ask) as cm:
            execute.plan_actions(s)
        self.assertIn("0", str(cm.exception))
        self.assertIn("1", str(cm.exception))


class TestGuardIsArmedEndToEnd(unittest.TestCase):
    """The step's label reaches `expect`, so the wrong branch is refused
    BEFORE anything is transmitted — the guard the game never armed."""

    APP_PROMPT = {"type": "or", "title": "Select action",
                  "options": [{"type": "option", "title": t} for t in APP_ORDER]}

    def test_step_level_label_refuses_the_wrong_index_before_any_send(self):
        step = {"id": "1a", "choiceLabel": "remove 3 microbes",
                "events": [{"method": "use_action", "args": [OR_CARD, "Zed"],
                            "kwargs": {"choice": 1}}]}
        follow = execute.plan_actions(step)[0]["follow"]
        sent = []
        prompts = [dict(self.APP_PROMPT)]

        class Client:
            def player(self, pid):
                return {"waitingFor": prompts.pop(0)} if prompts else {}

        with mock.patch.object(execute, "_send",
                               side_effect=lambda c, p, r, w, o: sent.append(r)):
            with self.assertRaises(Ask) as cm:
                execute._answer_follow_ups(Client(), "pid", follow,
                                           out=lambda *a: None)
        self.assertEqual(sent, [], "nothing may be transmitted")
        self.assertIn("remove 3 microbes", str(cm.exception).lower())


class TestPlanlibOrSelectorGate(Base):
    """A bare integer on an or-card step is refused; a title is not."""

    def base_step(self, kwargs: dict, **step_kw) -> dict:
        return {"id": "1a", "summary": "use the action", "volatility": "safe",
                "events": [{"method": "use_action", "args": [OR_CARD, "Zed"],
                            "kwargs": kwargs}], **step_kw}

    def plan(self, step: dict) -> dict:
        return {"threats": "Anna: nothing", "exit": "TR engine: the action",
                "exitAck": "the action is the repeatable component",
                "steps": [step]}

    def setUp(self):
        super().setUp()
        self.play_or_card(microbes=3)

    def test_bare_integer_without_a_label_is_refused(self):
        with self.assertRaises(EventError) as cm:
            planlib.set_plan(self.store, self.plan(self.base_step({"choice": 1})))
        msg = str(cm.exception)
        self.assertIn("1a", msg)
        self.assertIn("Remove 3 microbes", msg)
        self.assertIn("choice", msg.lower())
        self.assertIn("GATE or-selector REFUSED",
                      self.store.log_path.read_text())

    def test_title_selector_is_accepted(self):
        plan = planlib.set_plan(
            self.store, self.plan(self.base_step({"choice": "remove 3 microbes"})))
        self.assertEqual(len(plan["steps"]), 1)

    def test_integer_with_a_label_is_accepted(self):
        plan = planlib.set_plan(self.store, self.plan(self.base_step(
            {"choice": 1, "choiceLabel": "remove 3 microbes"})))
        self.assertEqual(len(plan["steps"]), 1)

    def test_integer_with_a_step_level_label_is_accepted(self):
        plan = planlib.set_plan(self.store, self.plan(self.base_step(
            {"choice": 1}, choiceLabel="remove 3 microbes")))
        self.assertEqual(len(plan["steps"]), 1)


class TestNoCardSpecificTable(unittest.TestCase):
    """The forbidden fix: a per-card branch-order map anywhere."""

    def test_no_card_name_in_the_selector_code(self):
        for name in ("appapi.py", "execute.py", "planlib.py"):
            text = (Path(__file__).resolve().parent.parent / "scripts"
                    / name).read_text()
            self.assertNotIn(OR_CARD, text, f"{name} names a card")


if __name__ == "__main__":
    unittest.main()
