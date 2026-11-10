"""P9 issue 7: clock.py must not print a range that cannot be wrong.

Live game `games/2026-08-29-game1` (3p, base + Corporate Era, no WGT,
ended after generation 13). Nobody built a greenery until generation 7, so
oxygen sat at 0% for six generations and the whole-track quadratic fit
extrapolated the missing 14 steps over the tail:

    gen 1: ~12 gens left (end ~gen 13; range 12-15). Phase: economy.
    gen 3: ~10 gens left (end ~gen 13; range 12-15).
    gen 5: ~15 gens left (end ~gen 20; range 20-20). Phase: economy.

The gen-5 line is the defect. "range 20-20" is a zero-width interval
emitted at the moment the estimate is LEAST certain, and downstream
(menu.award_lock via advise.py's RACE ALERT) priced every rival on
"15 gen(s) left", so nothing looked lockable — in a game with 8 to go.

The alarm underneath is REAL and is preserved: the fill rate really was
0.2 steps/gen and the model really should say so. What these tests pin is
the REPORTING — a parameter that has shown no fill at all makes the
projection unbounded above, so the estimate must (a) carry a non-zero
width, (b) name the stalled parameter, and (c) keep the rules-derived
player-count prior as the short clock rather than pricing the whole
remaining game off a stall that breaks the moment someone plays a
greenery.

Deliberate collapses stay collapsed (clock.py docstring, lines ~18-40):
a table-declared final generation, all 42 steps done, and the last two
generations before the projected end.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clock  # noqa: E402


def _g(t, o, w):
    return {"temperature": t, "oxygen": o, "oceans": w}


# Real 3p table, games/2026-08-29-game1: START-of-generation globals
# (game.json history entry N is the close of gen N = the start of gen N+1).
# Oxygen is 0 for the starts of generations 1-6. The game ended after
# generation 13.
P9 = [_g(-30, 0, 0), _g(-30, 0, 0), _g(-30, 0, 0), _g(-30, 0, 1),
      _g(-28, 0, 1), _g(-28, 0, 2), _g(-28, 1, 2), _g(-28, 4, 2),
      _g(-24, 5, 2), _g(-22, 8, 5), _g(-16, 13, 5), _g(-8, 14, 6),
      _g(4, 14, 8)]
P9_END = 13
P9_PLAYERS = 3


def _hist(gen):
    """History exactly as advise.py/research.py/menu.py feed it: the
    start-of-generation globals of the generations before this one."""
    return P9[:gen - 1]


class TestStalledParameterReporting(unittest.TestCase):
    """The gen-5 line that started the issue."""

    def test_gen5_range_is_not_zero_width_without_history(self):
        # the exact call the clock.py CLI makes (no --history): this is the
        # invocation that printed "range 20-20".
        est = clock.estimate(P9[4], 5, players=P9_PLAYERS)
        lo, hi = est["endRange"]
        self.assertLess(lo, hi, est["note"])
        self.assertNotIn(f"range {lo}-{lo}", est["note"])
        self.assertIn(f"range {lo}-{hi}", est["note"])

    def test_gen5_range_is_not_zero_width_with_history(self):
        est = clock.estimate(P9[4], 5, players=P9_PLAYERS, history=_hist(5))
        lo, hi = est["endRange"]
        self.assertLess(lo, hi, est["note"])

    def test_stalled_parameter_is_named(self):
        for gen in (4, 5, 6):                     # oxygen still at 0%
            est = clock.estimate(P9[gen - 1], gen, players=P9_PLAYERS,
                                 history=_hist(gen))
            self.assertIn("oxygen", est.get("stalledParams", []),
                          f"gen {gen}: {est['note']}")
            self.assertIn("parameter-stalled", est["note"], gen)
            self.assertIn("oxygen", est["note"], gen)
        # temperature is still at -30 at the start of gen 4 and moves at
        # gen 5: the marker follows the evidence, it is not hard-coded.
        self.assertEqual(clock.estimate(P9[3], 4, players=P9_PLAYERS,
                                        history=_hist(4))["stalledParams"],
                         ["temperature", "oxygen"])
        self.assertEqual(clock.estimate(P9[4], 5, players=P9_PLAYERS,
                                        history=_hist(5))["stalledParams"],
                         ["oxygen"])

    def test_no_stalled_marker_once_the_parameter_moves(self):
        # oxygen reaches 1% at the start of gen 7 and never stalls again
        for gen in range(7, len(P9) + 1):
            est = clock.estimate(P9[gen - 1], gen, players=P9_PLAYERS,
                                 history=_hist(gen))
            self.assertEqual(est.get("stalledParams", []), [], gen)
            self.assertNotIn("parameter-stalled", est["note"], gen)

    def test_stall_does_not_price_the_whole_game_as_remaining(self):
        # the downstream symptom: award_lock read "15 gen(s) left" at gen 5
        # of a game with 8 to go. The short clock may not run past the
        # player-count prior while the projection rests on a stall.
        for gen in (4, 5, 6):
            est = clock.estimate(P9[gen - 1], gen, players=P9_PLAYERS,
                                 history=_hist(gen))
            self.assertLessEqual(est["endGeneration"], P9_END + 2,
                                 f"gen {gen}: {est['note']}")
            self.assertLessEqual(est["gensLeft"], P9_END + 2 - gen,
                                 f"gen {gen}: {est['note']}")

    def test_the_long_projection_survives_as_the_upper_bound(self):
        # the alarm is real: the fit says the table could run very long and
        # the pessimistic bound must still say so.
        est = clock.estimate(P9[4], 5, players=P9_PLAYERS)
        self.assertGreaterEqual(est["endRange"][1], 20, est["note"])

    def test_whole_replay_never_reports_a_degenerate_midgame_range(self):
        for gen in range(1, len(P9) + 1):
            for history in (None, _hist(gen)):
                est = clock.estimate(P9[gen - 1], gen, players=P9_PLAYERS,
                                     history=history)
                lo, hi = est["endRange"]
                if est["endGeneration"] - gen <= 1:   # last two generations
                    continue
                if history is None and not est.get("stalledParams"):
                    continue      # documented no-history collapse (see below)
                self.assertLess(lo, hi, f"gen {gen}: {est['note']}")

    def test_range_keys_stay_consistent(self):
        for gen in range(1, len(P9) + 1):
            est = clock.estimate(P9[gen - 1], gen, players=P9_PLAYERS,
                                 history=_hist(gen))
            lo, hi = est["endRange"]
            self.assertEqual(est["gensLeftRange"],
                             [max(0, lo - gen), max(0, hi - gen)], gen)
            self.assertLessEqual(lo, est["endGeneration"], gen)
            self.assertLessEqual(est["endGeneration"], hi, gen)
            if gen > 3:      # projection branch: the short clock IS the low
                self.assertEqual(est["endGeneration"], lo, gen)


class TestDeliberateCollapsesPreserved(unittest.TestCase):
    """clock.py collapses the range on purpose in three places. None of
    them may change: a table vote, a maxed board, and the last two
    generations (plus the documented no-history point estimate)."""

    def test_table_declared_final_generation_collapses(self):
        est = clock.estimate(P9[8], 9, players=P9_PLAYERS, history=_hist(9),
                             declared_final=9)
        self.assertTrue(est["finalGeneration"])
        self.assertEqual(est["endRange"], [9, 9])
        self.assertEqual(est["gensLeftRange"], [0, 0])
        self.assertEqual(est["gensLeft"], 0)
        self.assertEqual(est["phase"], "points")
        self.assertNotIn("parameter-stalled", est["note"])

    def test_declared_final_collapses_even_with_a_stalled_parameter(self):
        # gen 5 of the P9 game, if the table had declared it final: the
        # vote overrides every estimate, stall or not.
        est = clock.estimate(P9[4], 5, players=P9_PLAYERS, history=_hist(5),
                             declared_final=5)
        self.assertEqual(est["endRange"], [5, 5])
        self.assertEqual(est["gensLeftRange"], [0, 0])

    def test_all_parameters_maxed_collapses(self):
        est = clock.estimate(_g(8, 14, 9), 13, players=P9_PLAYERS,
                             history=_hist(13))
        self.assertTrue(est["finalGeneration"])
        self.assertEqual(est["endRange"], [13, 13])
        self.assertEqual(est["gensLeftRange"], [0, 0])
        self.assertEqual(est["stepsLeft"], 0)

    def test_last_two_generations_may_still_collapse(self):
        # end_lo - generation <= 1 is the window clock.py calls knowledge
        # rather than coincidence; nothing here forces a width onto it.
        est = clock.estimate(P9[11], 12, players=P9_PLAYERS,
                             history=_hist(12))
        self.assertLessEqual(est["endGeneration"] - 12, 1, est["note"])
        self.assertLessEqual(est["endRange"][1] - est["endRange"][0], 1,
                             est["note"])

    def test_no_history_point_estimate_survives_without_a_stall(self):
        # test_clock.TestNoHistory pins this: with no history and every
        # parameter moving, the range is the point estimate.
        est = clock.estimate(_g(-12, 14, 2), 12, players=5)
        self.assertEqual(est.get("stalledParams", []), [])
        self.assertEqual(est["endRange"], [est["endGeneration"]] * 2)
        self.assertEqual(est["gensLeftRange"], [est["gensLeft"]] * 2)

    def test_prior_generations_are_untouched(self):
        # gens_elapsed <= 2 is prior territory and already carries a band;
        # the stall rule must not reach into it (gens 1-3 printed fine).
        for gen in (1, 2, 3):
            est = clock.estimate(P9[gen - 1], gen, players=P9_PLAYERS,
                                 history=_hist(gen))
            self.assertEqual(est["endRange"], [12, 15], f"gen {gen}")
            self.assertEqual(est["endGeneration"], 13, f"gen {gen}")
            self.assertEqual(est.get("stalledParams", []), [], f"gen {gen}")


class TestFastFillReporting(unittest.TestCase):
    """H7 (Codex game diagnostic, 2026-08-29): the mirror of the stalled-
    parameter fix above. A live 3p table (prior 13-14 gens) moved from
    that prior to an exact 'end ~gen 9' after one fast generation, and
    the game actually ended at generation 11.

    Reproduced here: a 3p, base+CE table that fills slowly through
    generation 6, then bursts in generation 6 (temperature -24→-6,
    oxygen 3%→8%, oceans 1→3), so at generation 7 both the whole-track
    fit and the observed last-2-gen rate project 'end ~gen 9' — a range
    of [9, 10] under the pre-fix model, vs. a rules prior of 13 for 3
    players. clock.py's own CLI feeds exactly this: current globals +
    generation + history, no other input."""

    def _g(self, t, o, w):
        return {"temperature": t, "oxygen": o, "oceans": w}

    def setUp(self):
        self.series = [
            self._g(-30, 0, 0), self._g(-30, 0, 0), self._g(-28, 0, 0),
            self._g(-28, 1, 0), self._g(-26, 2, 1), self._g(-24, 3, 1),
            self._g(-6, 8, 3),
        ]
        self.players = 3
        self.prior = clock.PRIOR_END[self.players]  # 13

    def _hist(self, gen):
        return self.series[:gen - 1]

    def _est(self, gen):
        return clock.estimate(self.series[gen - 1], gen, players=self.players,
                              history=self._hist(gen))

    def test_fast_generation_reproduces_the_pre_fix_collapse_shape(self):
        # sanity check on the fixture itself: generation ~7 is where the
        # fast fill lands and the projection first undercuts the prior.
        est = self._est(7)
        self.assertEqual(est["endGeneration"], 9)
        self.assertLess(est["endGeneration"], self.prior)
        self.assertGreater(est["endRange"][1] - est["endRange"][0], 0,
                           est["note"])

    def test_range_is_not_zero_width(self):
        lo, hi = self._est(7)["endRange"]
        self.assertLess(lo, hi)

    def test_upper_bound_is_at_least_the_prior(self):
        est = self._est(7)
        self.assertGreaterEqual(est["endRange"][1], self.prior, est["note"])

    def test_lower_bound_is_the_fast_projection(self):
        est = self._est(7)
        self.assertEqual(est["endRange"][0], est["endGeneration"])
        self.assertEqual(est["endRange"][0], 9)

    def test_note_names_the_fast_fill_assumption(self):
        est = self._est(7)
        self.assertIn("fast-fill projection 9 vs prior 13", est["note"])
        self.assertIn(f"range {est['endRange'][0]}-{est['endRange'][1]}",
                      est["note"])

    def test_last_two_generations_still_collapse(self):
        # one generation later the projected end is itself close enough
        # (gens_left <= 1) that the deliberate collapse applies again —
        # this fix must not force a floor onto that window.
        series8 = self.series + [self._g(2, 11, 5)]
        est = clock.estimate(series8[7], 8, players=self.players,
                             history=series8[:7])
        self.assertLessEqual(est["endGeneration"] - 8, 1, est["note"])
        self.assertLessEqual(est["endRange"][1] - est["endRange"][0], 1,
                             est["note"])
        self.assertNotIn("fast-fill", est["note"])

    def test_stalled_case_from_last_night_is_unaffected(self):
        # the OTHER direction (P9 issue 7 / TestStalledParameterReporting)
        # must still hold with this fix in place.
        est = clock.estimate(P9[4], 5, players=P9_PLAYERS, history=_hist(5))
        lo, hi = est["endRange"]
        self.assertLess(lo, hi, est["note"])
        self.assertIn("oxygen", est.get("stalledParams", []))
        self.assertIn("parameter-stalled", est["note"])
        self.assertNotIn("fast-fill", est["note"])


if __name__ == "__main__":
    unittest.main()
