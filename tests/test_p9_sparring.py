"""P9 #11 — `sparring.py claim|fund` must say WHY there is nothing to send.

Live-fire evidence (private/plans/p9-issues.md, issue 11): the Anna seat ran
`sparring.py claim <pid> Gardener` repeatedly, got only a generic
`ERROR: 'No option matching …'`, and concluded the harness was broken. It was
not: the advisor had claimed Gardener earlier in the SAME generation as first
player, all three milestone slots were used, and the app correctly stopped
offering "claim a milestone". The seat spent the rest of the game believing a
correct engine was faulty — exactly what agents/seat-kit.md warns against
twice ("Never conclude the harness is broken").

The fix is diagnostics, driven by what the app's player view actually
exposes: `game.milestones` / `game.awards` (each row carries `name`,
`playerName` when taken, and per-colour `scores` with a `claimable` flag
while slots remain), plus `thisPlayer.megacredits`. No milestone-specific or
card-specific branch may appear — tests/test_no_card_literals.py stays green.
"""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sparring


MENU_NO_CLAIM = {"type": "or", "title": "Take action for action phase",
                 "options": [
                     {"title": "Play project card", "type": "projectCard"},
                     {"title": "Standard projects", "type": "projectCard"},
                     {"title": "Pass for this generation", "type": "option"}]}

MENU_WITH_CLAIM = {"type": "or", "title": "Take action for action phase",
                   "options": [
                       {"title": "Play project card", "type": "projectCard"},
                       {"title": "Claim a milestone", "type": "or", "options": [
                           {"title": "Builder", "type": "option"}]},
                       {"title": "Pass for this generation", "type": "option"}]}


def scores(**by_color):
    """`scores` rows as the app writes them (claimable only on milestones)."""
    out = []
    for color, val in by_color.items():
        if isinstance(val, tuple):
            out.append({"color": color, "score": val[0], "claimable": val[1]})
        else:
            out.append({"color": color, "score": val})
    return out


def milestone(name, player=None, color=None, **sc):
    return {"name": name, "playerName": player, "color": color,
            "scores": [] if player else scores(**sc)}


def view(milestones=(), awards=(), mc=24, color="red", wf=MENU_NO_CLAIM,
         gen=10):
    return {"thisPlayer": {"color": color, "megacredits": mc,
                           "terraformRating": 30},
            "players": [{"name": "Anna", "color": "red"},
                        {"name": "Zed", "color": "green"},
                        {"name": "Ben", "color": "yellow"}],
            "waitingFor": wf,
            "game": {"generation": gen, "phase": "action",
                     "milestones": list(milestones), "awards": list(awards)}}


# the P9 board at generation 10: Zed had swept every slot
SWEPT = [milestone("Builder", "Zed", "green"),
         milestone("Mayor", "Zed", "green"),
         milestone("Gardener", "Zed", "green"),
         milestone("Terraformer"), milestone("Planner")]

# one slot used, Gardener still open, Anna (red) two greeneries short
OPEN = [milestone("Builder", "Zed", "green"),
        milestone("Mayor", red=(1, False), green=(2, False), yellow=(0, False)),
        milestone("Gardener", red=(2, False), green=(2, False), yellow=(1, False)),
        milestone("Terraformer", red=(30, False), green=(33, False),
                  yellow=(28, False)),
        milestone("Planner", red=(4, False), green=(5, False), yellow=(3, False))]


class TestAllSlotsUsed(unittest.TestCase):
    """(a) every milestone slot is gone — name what was taken and by whom."""

    def setUp(self):
        self.msg = sparring.explain_unavailable(view(SWEPT), "claim",
                                                "Gardener")

    def test_reason_is_the_exhausted_slots(self):
        self.assertIn("all 3 milestone slots", self.msg.lower())

    def test_names_every_claim_and_its_owner(self):
        for name in ("Builder", "Mayor", "Gardener"):
            self.assertIn(name, self.msg)
        self.assertIn("Zed", self.msg)

    def test_says_the_app_is_behaving_correctly(self):
        low = self.msg.lower()
        self.assertTrue("correct" in low or "not a harness" in low,
                        f"no not-a-bug reassurance in:\n{self.msg}")

    def test_does_not_blame_the_metric_when_no_slot_remains(self):
        self.assertNotIn("do not meet", self.msg.lower())


class TestMetricNotMet(unittest.TestCase):
    """(c) slots remain but the seat is short — print count vs threshold."""

    def setUp(self):
        self.msg = sparring.explain_unavailable(view(OPEN), "claim",
                                                "Gardener")

    def test_reason_is_the_shortfall(self):
        self.assertIn("do not meet", self.msg.lower())

    def test_reports_the_seats_own_count(self):
        self.assertIn("2", self.msg)

    def test_reports_the_threshold_and_its_metric(self):
        self.assertIn("3", self.msg)
        self.assertIn("greeneries", self.msg.lower())

    def test_shows_the_slots_still_open(self):
        self.assertIn("1 of 3", self.msg)
        self.assertIn("Builder", self.msg)


class TestAlreadyTakenAndAffordability(unittest.TestCase):
    def test_named_milestone_already_claimed_names_the_owner(self):
        rows = [milestone("Builder", "Zed", "green"),
                milestone("Gardener", red=(3, True))]
        msg = sparring.explain_unavailable(view(rows), "claim", "Builder")
        self.assertIn("already claimed", msg.lower())
        self.assertIn("Zed", msg)

    def test_cannot_afford_the_fee(self):
        rows = [milestone("Gardener", red=(3, True), green=(1, False))]
        msg = sparring.explain_unavailable(view(rows, mc=4), "claim",
                                           "Gardener")
        self.assertIn("afford", msg.lower())
        self.assertIn("8", msg)      # the 8 M€ milestone fee
        self.assertIn("4", msg)      # what the seat actually holds

    def test_unknown_name_lists_this_games_milestones(self):
        msg = sparring.explain_unavailable(view(OPEN), "claim", "Nowhere")
        self.assertIn("Nowhere", msg)
        self.assertIn("Planner", msg)

    def test_no_prompt_at_all_is_reported_as_such(self):
        msg = sparring.explain_unavailable(view(OPEN, wf=None), "claim",
                                           "Gardener")
        self.assertTrue(msg.strip())
        self.assertIn("Gardener", msg)


class TestAwardsGetTheSameTreatment(unittest.TestCase):
    """`fund` was equally silent; awards carry no `claimable` flag, so the
    reasons that apply are slots / already funded / fee."""

    FUNDED = [{"name": "Landlord", "playerName": "Zed", "color": "green",
               "scores": []},
              {"name": "Banker", "playerName": "Ben", "color": "yellow",
               "scores": []},
              {"name": "Scientist", "playerName": "Zed", "color": "green",
               "scores": []},
              {"name": "Thermalist", "playerName": None, "color": None,
               "scores": []},
              {"name": "Miner", "playerName": None, "color": None,
               "scores": []}]

    def test_all_awards_funded(self):
        msg = sparring.explain_unavailable(view(awards=self.FUNDED), "fund",
                                           "Miner")
        self.assertIn("all 3 award slots", msg.lower())
        self.assertIn("Landlord", msg)
        self.assertIn("Ben", msg)

    def test_fee_rises_with_the_number_already_funded(self):
        two = [{"name": "Landlord", "playerName": "Zed", "color": "green",
                "scores": []},
               {"name": "Banker", "playerName": "Ben", "color": "yellow",
                "scores": []},
               {"name": "Miner", "playerName": None, "color": None,
                "scores": scores(red=1, green=4)}]
        msg = sparring.explain_unavailable(view(awards=two, mc=3), "fund",
                                           "Miner")
        self.assertIn("afford", msg.lower())
        self.assertIn("20", msg)     # third award costs 20 M€

    def test_award_reason_never_claims_a_metric_shortfall(self):
        one = [{"name": "Miner", "playerName": None, "color": None,
                "scores": scores(red=1, green=4)}]
        msg = sparring.explain_unavailable(view(awards=one, mc=30), "fund",
                                           "Miner")
        self.assertNotIn("do not meet", msg.lower())


class TestNoHardCodedNames(unittest.TestCase):
    """The diagnostics must read the view, never a table of milestone names
    used as logic (the P8/P9 rule that keeps test_no_card_literals green)."""

    def test_a_made_up_milestone_set_is_handled_identically(self):
        rows = [milestone("Alpha", "Zed", "green"),
                milestone("Beta", "Ben", "yellow"),
                milestone("Gamma", "Zed", "green"),
                milestone("Delta")]
        msg = sparring.explain_unavailable(view(rows), "claim", "Delta")
        self.assertIn("all 3 milestone slots", msg.lower())
        self.assertIn("Alpha", msg)
        self.assertIn("Beta", msg)

    def test_shortfall_without_a_known_threshold_still_reports_the_count(self):
        rows = [milestone("Alpha", red=(7, False), green=(9, False))]
        msg = sparring.explain_unavailable(view(rows), "claim", "Alpha")
        self.assertIn("7", msg)
        self.assertIn("do not meet", msg.lower())


class TestCliSurfacesTheReason(unittest.TestCase):
    """The seat runs the CLI, not the library: the reason must reach stderr
    and the exit code must stay non-zero."""

    def _run(self, argv, v):
        buf = io.StringIO()
        with mock.patch.object(sparring, "get_player", return_value=v), \
             mock.patch.object(sparring, "send",
                               side_effect=AssertionError("must not transmit")), \
             mock.patch("sys.argv", argv), \
             mock.patch("sys.stderr", buf), \
             mock.patch("sys.stdout", io.StringIO()):
            code = sparring.main()
        return code, buf.getvalue()

    def test_claim_with_no_slots_left_explains_instead_of_keyerror(self):
        code, err = self._run(
            ["sparring.py", "claim", "p1", "Gardener"], view(SWEPT))
        self.assertEqual(code, 1)
        self.assertIn("all 3 milestone slots", err.lower())
        self.assertNotIn("No option matching", err)

    def test_claim_short_of_the_metric_explains(self):
        code, err = self._run(
            ["sparring.py", "claim", "p1", "Gardener"],
            view(OPEN, wf=MENU_WITH_CLAIM))
        self.assertEqual(code, 1)
        self.assertIn("do not meet", err.lower())
        self.assertIn("greeneries", err.lower())

    def test_fund_is_explained_too(self):
        code, err = self._run(
            ["sparring.py", "fund", "p1", "Miner"],
            view(awards=TestAwardsGetTheSameTreatment.FUNDED))
        self.assertEqual(code, 1)
        self.assertIn("all 3 award slots", err.lower())

    def test_a_valid_claim_still_transmits(self):
        sent = []
        v = view([milestone("Builder", red=(8, True))], wf=MENU_WITH_CLAIM)
        with mock.patch.object(sparring, "get_player", return_value=v), \
             mock.patch.object(sparring, "send",
                               side_effect=lambda pid, r: sent.append(r)), \
             mock.patch.object(sparring, "describe_waiting",
                               return_value="ok"), \
             mock.patch("sys.argv", ["sparring.py", "claim", "p1", "Builder"]), \
             mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(sparring.main(), 0)
        self.assertEqual(sent, [sparring.nested_or(1, 0)])


if __name__ == "__main__":
    unittest.main()
