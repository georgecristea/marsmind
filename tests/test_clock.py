"""clock.py: honest uncertainty.

A slow 5p table (17 generations): the quadratic fill model assumes rate keeps
accelerating; the table stalled instead (opponents hoarded 100-240 MC,
temperature sat at -2°C for gens 12-15). From gen 12 the clock said
'~1 gen left' every generation and the advisor rejected cards on a
3-gen payback with 5-8 gens actually left. Fix: pair the model with the
observed last-2-gen rate and expose the range; keep the pessimistic
bound as endGeneration (KB 05: plan on the short clock at 5p).

Issue #22 (3p game 2026-08-28-game2, base+CE, no WGT): the same model,
calibrated on 5p tables, said 'end ~gen 11; range 11-11' at gen 1 and
never got past 'end ~gen 13' — the table ran to gen 14. Fewer players
means fewer engines fill the parameters, so the gen-1 PRIOR knows the
player count, and a gen-1 estimate has no business printing a zero-width
range.

What these tests do NOT assert: a per-player-count stretch of the fitted
projection. That multiplier existed, was calibrated on two games, and was
removed — so the assertions below are what the RULES justify (the prior
ladder, a non-degenerate range, mid-game accuracy within ±2 on the two
real trajectories), never a tolerance narrowed until the fit passed.
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import clock  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _g(t, o, w):
    return {"temperature": t, "oxygen": o, "oceans": w}


# Slow 5p table: recorded start-of-generation globals.
# Ended after gen 17 (42/42 steps).
SLOW_TABLE = [_g(-30, 0, 0), _g(-28, 1, 0), _g(-28, 1, 0), _g(-26, 4, 1),
         _g(-26, 5, 2), _g(-26, 6, 2), _g(-26, 7, 2), _g(-20, 11, 2),
         _g(-20, 14, 2), _g(-16, 14, 2), _g(-12, 14, 2), _g(-12, 14, 2),
         _g(-6, 14, 3), _g(-4, 14, 5), _g(0, 14, 5), _g(2, 14, 5),
         _g(8, 14, 9)]

# Fast 5p table (ended after gen 10). The exact per-generation
# globals were not recorded; this series is RECONSTRUCTED to match the
# two anchors in test_calculators.py (gen 6: -20/6%/1 =
# 12 steps, gen 9: +8/14%/6 = 39 steps) and the reported averages
# (~2.4 steps/gen over gens 1-5, ~6/gen over gens 6-10).
FAST_TABLE = [_g(-30, 0, 0), _g(-28, 0, 0), _g(-26, 1, 0), _g(-24, 2, 1),
         _g(-22, 4, 1), _g(-20, 6, 1), _g(-14, 9, 2), _g(-6, 12, 4),
         _g(8, 14, 6), _g(8, 14, 8)]


# Real 3p table, games/2026-08-28-game2 (base + Corporate Era, no WGT):
# start-of-generation globals taken from game.json history (entry N = the
# close of gen N = the start of gen N+1). The last parameter step fell in
# generation 14, which was the final generation.
THREE_P = [_g(-30, 0, 0), _g(-30, 0, 0), _g(-30, 0, 1), _g(-28, 1, 1),
           _g(-24, 1, 2), _g(-24, 1, 3), _g(-20, 3, 3), _g(-18, 3, 4),
           _g(-12, 5, 5), _g(-12, 5, 6), _g(-10, 8, 8), _g(-8, 9, 9),
           _g(2, 11, 9), _g(8, 13, 9)]
THREE_P_END = 14

# Real 4p table, games/2026-08-28-game1 (base + Corporate Era), same source.
# Ended after generation 12.
FOUR_P = [_g(-30, 0, 0), _g(-30, 0, 0), _g(-30, 0, 0), _g(-20, 0, 1),
          _g(-18, 0, 1), _g(-16, 3, 1), _g(-14, 5, 1), _g(-8, 6, 1),
          _g(-6, 9, 2), _g(-4, 11, 2), _g(-4, 13, 3), _g(6, 14, 8)]
FOUR_P_END = 12


def _replay(series, players=5):
    """Yield (generation, estimate-with-history, estimate-without)."""
    for i, globals_ in enumerate(series):
        gen = i + 1
        with_hist = clock.estimate(globals_, gen, players=players,
                                   history=series[:i])
        without = clock.estimate(globals_, gen, players=players)
        yield gen, with_hist, without


class TestSlowTable(unittest.TestCase):
    def test_high_bound_stops_lying_from_gen12(self):
        for gen, est, old in _replay(SLOW_TABLE):
            if gen < 12:
                continue
            self.assertGreaterEqual(est["endRange"][1], 15, gen)
            # pessimistic value never longer than the old point estimate
            self.assertLessEqual(est["endGeneration"], old["endGeneration"], gen)
            self.assertEqual(est["endRange"][0], est["endGeneration"])
            self.assertEqual(est["gensLeftRange"],
                             [est["endRange"][0] - gen, est["endRange"][1] - gen])

    def test_stalling_note_at_gen12(self):
        est = clock.estimate(SLOW_TABLE[11], 12, players=5, history=SLOW_TABLE[:11])
        self.assertIn("below model", est["note"])
        self.assertIn("do not lengthen the prior", est["note"])
        self.assertIn(f"{est['endRange'][0]}-{est['endRange'][1]}", est["note"])

    def test_final_generation_carries_range_keys(self):
        est = clock.estimate(SLOW_TABLE[16], 17, players=5, history=SLOW_TABLE[:16])
        self.assertTrue(est["finalGeneration"])
        self.assertEqual(est["endRange"], [17, 17])
        self.assertEqual(est["gensLeftRange"], [0, 0])


class TestFastTable(unittest.TestCase):
    def test_gen6_still_predicts_real_end(self):
        est = clock.estimate(FAST_TABLE[5], 6, players=5, history=FAST_TABLE[:5])
        self.assertGreaterEqual(est["endGeneration"], 9)
        self.assertLessEqual(est["endGeneration"], 11)   # actual: 10

    def test_phase_transitions_unchanged(self):
        for gen, est, old in _replay(FAST_TABLE):
            self.assertEqual(est["phase"], old["phase"], gen)
            self.assertEqual(est["gensLeft"], old["gensLeft"], gen)

    def test_no_stalling_note(self):
        for gen, est, _ in _replay(FAST_TABLE):
            self.assertNotIn("below model", est["note"], gen)


class TestThreePlayerTable(unittest.TestCase):
    """Issue #22: a 3p table runs ~3 generations longer than the 5p
    calibration; the clock understated it all game and flipped the advisor
    into 'points' (no more production buys) around gen 8."""

    def test_estimate_at_gens_1_5_9_is_within_two_gens_of_the_truth(self):
        for gen in (1, 5, 9):
            est = clock.estimate(THREE_P[gen - 1], gen, players=3,
                                 history=THREE_P[:gen - 1])
            self.assertLessEqual(abs(est["endGeneration"] - THREE_P_END), 2,
                                 f"gen {gen}: {est['note']}")

    def test_gen1_prior_is_the_rules_derived_one(self):
        # a 3p table fills 42 steps with fewer engines: the gen-1 prior is
        # long, and it is a BAND, not a number.
        est = clock.estimate(THREE_P[0], 1, players=3)
        self.assertGreaterEqual(est["endGeneration"], 13)
        lo, hi = est["endRange"]
        self.assertGreater(hi, lo, est["note"])

    def test_gen1_prior_brackets_the_real_end(self):
        est = clock.estimate(THREE_P[0], 1, players=3)
        lo, hi = est["endRange"]
        self.assertLess(lo, hi, est["note"])          # never '11-11'
        self.assertLessEqual(lo, THREE_P_END)
        self.assertGreaterEqual(hi, THREE_P_END)

    def test_range_is_never_a_single_number_before_the_last_two_gens(self):
        for gen, est, _ in _replay(THREE_P, players=3):
            lo, hi = est["endRange"]
            if est["endGeneration"] - gen <= 1:       # last two generations
                continue
            self.assertLess(lo, hi, f"gen {gen}: {est['note']}")
            self.assertIn(f"range {lo}-{hi}", est["note"])
            self.assertNotIn(f"range {lo}-{lo}", est["note"])

    def test_economy_phase_survives_the_first_half(self):
        # the reported failure: 'points' (stop buying production) by mid-game
        for gen, est, _ in _replay(THREE_P, players=3):
            if gen <= 7:
                self.assertNotEqual(est["phase"], "points", gen)

    def test_whole_replay_never_understates_by_more_than_two(self):
        for gen, est, _ in _replay(THREE_P, players=3):
            self.assertGreaterEqual(est["endGeneration"], THREE_P_END - 2, gen)


class TestFourPlayerTable(unittest.TestCase):
    def test_midgame_predicts_the_real_end(self):
        for gen in range(5, FOUR_P_END + 1):
            est = clock.estimate(FOUR_P[gen - 1], gen, players=4,
                                 history=FOUR_P[:gen - 1])
            self.assertLessEqual(abs(est["endGeneration"] - FOUR_P_END), 2,
                                 f"gen {gen}: {est['note']}")

    def test_gen1_prior_brackets_the_real_end(self):
        est = clock.estimate(FOUR_P[0], 1, players=4)
        lo, hi = est["endRange"]
        self.assertLessEqual(lo, FOUR_P_END)
        self.assertGreaterEqual(hi, FOUR_P_END)


class TestPlayerCountLadder(unittest.TestCase):
    """The player count belongs to the PRIOR (rules: fewer engines fill the
    42 steps more slowly). It must NOT reappear as a coefficient on the
    projection — that was fitted to two games and removed."""

    def test_fewer_players_never_predicts_a_shorter_game(self):
        mid = _g(-20, 4, 3)
        ends = [clock.estimate(mid, 6, players=p, history=[_g(-24, 2, 2),
                                                           _g(-22, 3, 2)]
                               )["endGeneration"] for p in (2, 3, 4, 5, 6)]
        self.assertEqual(ends, sorted(ends, reverse=True), ends)

    def test_the_projection_itself_carries_no_player_count_term(self):
        # once there is fill to measure, THIS table's rate is the evidence
        # and the player count adds nothing to it
        mid = _g(-20, 4, 3)
        hist = [_g(-26, 1, 1), _g(-24, 2, 2), _g(-22, 3, 2)]
        ests = [clock.estimate(mid, 7, players=p, history=hist)
                for p in (2, 3, 4, 5, 6)]
        self.assertEqual({e["endGeneration"] for e in ests}, {ests[0]["endGeneration"]})
        self.assertEqual({tuple(e["endRange"]) for e in ests},
                         {tuple(ests[0]["endRange"])})
        self.assertFalse(hasattr(clock, "tail_factor"))

    def test_gen1_prior_ladder_is_monotone(self):
        ends = [clock.estimate(_g(-30, 0, 0), 1, players=p)["endGeneration"]
                for p in (2, 3, 4, 5, 6)]
        self.assertEqual(ends, sorted(ends, reverse=True), ends)


class TestNoHistory(unittest.TestCase):
    def test_range_collapses_to_point_estimate(self):
        est = clock.estimate(_g(-12, 14, 2), 12, players=5)
        self.assertEqual(est["endRange"], [est["endGeneration"]] * 2)
        self.assertEqual(est["gensLeftRange"], [est["gensLeft"]] * 2)

    def test_one_sample_falls_back_to_last_gen_rate(self):
        # only gen 11's start is known: 2 steps in one gen, 17 left → ~9 more
        est = clock.estimate(_g(-12, 14, 2), 12, players=5,
                             history=[_g(-16, 14, 2)])
        self.assertGreaterEqual(est["endRange"][1], 15)

    def test_prior_gens_ignore_history(self):
        # gens_elapsed <= 2 is prior territory: two noisy samples move
        # nothing (the prior band itself is honest about not knowing —
        # issue #22: a gen-1 'range 11-11' is a lie, not an estimate).
        est = clock.estimate(SLOW_TABLE[2], 3, players=5, history=SLOW_TABLE[:2])
        self.assertEqual(est, clock.estimate(SLOW_TABLE[2], 3, players=5))
        self.assertLess(est["endRange"][0], est["endRange"][1])


class TestClockCli(unittest.TestCase):
    def test_history_flag(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "game.json"
            state.write_text(json.dumps({"generation": 12, "globals": SLOW_TABLE[11],
                                         "opponents": {}}))
            hist = json.dumps([[g["temperature"], g["oxygen"], g["oceans"]]
                               for g in SLOW_TABLE[:11]])
            r = subprocess.run([sys.executable, str(SCRIPTS / "clock.py"),
                                "--state", str(state), "--players", "5",
                                "--history", hist],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertGreaterEqual(out["endRange"][1], 15)
            self.assertIn("below model", out["note"])

    def test_player_count_comes_from_setup_json(self):
        # 3p game, no --players: opponents{} may be empty early, setup.json
        # playerCount is the authority (research.py/advise.py already use it)
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "game.json"
            setup = Path(tmp) / "setup.json"
            state.write_text(json.dumps({"generation": 1, "globals": THREE_P[0],
                                         "opponents": {}}))
            setup.write_text(json.dumps({"playerCount": 3}))
            r = subprocess.run([sys.executable, str(SCRIPTS / "clock.py"),
                                "--state", str(state), "--setup", str(setup)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["endGeneration"],
                             clock.estimate(THREE_P[0], 1, players=3)["endGeneration"])
            self.assertGreaterEqual(out["endGeneration"], 12)


class TestPaybackRange(unittest.TestCase):
    """payback.py --gens-range LOW HIGH: verdict at the midpoint, both
    bounds printed. Lives here because payback.py's other tests are in
    test_calculators.py."""

    def _run(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "payback.py"),
                               *args], capture_output=True, text=True)

    def test_range_prints_both_bounds_and_midpoint_verdict(self):
        r = self._run("--cost", "11", "--gens-range", "3", "8", "mc=3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("horizon 3-8", r.stdout)
        # 14 MC total, 3/gen: net -5 at 3 gens, +10 at 8 gens, verdict at 5
        self.assertIn("-5", r.stdout)
        self.assertIn("+10", r.stdout)
        self.assertIn("pays back in 5 gens", r.stdout)

    def test_gens_left_path_untouched(self):
        r = self._run("--cost", "11", "--gens-left", "3", "mc=3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("horizon", r.stdout)
        self.assertIn("skip", r.stdout)

    def test_one_of_the_two_is_required(self):
        r = self._run("--cost", "11", "mc=3")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
