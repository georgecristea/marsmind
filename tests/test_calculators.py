"""Layer 2: deterministic calculators — LLM judges, code computes."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import payback
import clock


class TestPayback(unittest.TestCase):
    def test_mc_production_card_positive(self):
        # cost 12 (+3 keep), +3 MC prod, 8 gens left → 24 return, +9 net
        r = payback.evaluate(cost=12, prod={"mc": 3}, gens_left=8)
        self.assertEqual(r["totalCost"], 15)
        self.assertEqual(r["perGen"], 3)
        self.assertEqual(r["totalReturn"], 24)
        self.assertEqual(r["net"], 9)
        self.assertEqual(r["breakEvenGens"], 5)  # ceil(15/3)

    def test_keep_cost_can_be_excluded_for_drafted_now(self):
        r = payback.evaluate(cost=12, prod={"mc": 3}, gens_left=8, keep_cost=0)
        self.assertEqual(r["totalCost"], 12)
        self.assertEqual(r["breakEvenGens"], 4)

    def test_mixed_production_uses_mc_equivalents(self):
        # steel prod ≈ 2 MC/gen, heat ≈ 1 MC/gen
        r = payback.evaluate(cost=9, prod={"steel": 1, "heat": 2}, gens_left=5)
        self.assertEqual(r["perGen"], 4)
        self.assertEqual(r["totalReturn"], 20)
        self.assertEqual(r["net"], 8)

    def test_negative_when_too_late(self):
        r = payback.evaluate(cost=12, prod={"mc": 3}, gens_left=2)
        self.assertEqual(r["net"], -9)
        self.assertIn("skip", r["verdict"].lower())

    def test_never_breaks_even_flagged(self):
        r = payback.evaluate(cost=10, prod={}, gens_left=5)
        self.assertIsNone(r["breakEvenGens"])


class TestClock(unittest.TestCase):
    def test_remaining_steps_counts_all_three_tracks(self):
        s = clock.remaining_steps({"temperature": -30, "oxygen": 0, "oceans": 0})
        self.assertEqual(s, {"temperature": 19, "oxygen": 14, "oceans": 9})

    def test_endgame_when_all_maxed(self):
        est = clock.estimate({"temperature": 8, "oxygen": 14, "oceans": 9},
                             generation=9)
        self.assertEqual(est["gensLeft"], 0)
        self.assertTrue(est["finalGeneration"])

    def test_estimate_from_observed_fill_rate(self):
        # gen 5, 12 of 42 steps done in 4 completed gens → 3 steps/gen
        # 30 steps remain → 10 more gens at flat rate, accel factor tightens it
        est = clock.estimate({"temperature": -18, "oxygen": 4, "oceans": 2},
                             generation=5)
        self.assertEqual(est["stepsDone"], 12)
        self.assertEqual(est["stepsLeft"], 30)
        self.assertGreater(est["endGeneration"], 5)
        self.assertLessEqual(est["endGeneration"], 16)
        self.assertEqual(est["gensLeft"], est["endGeneration"] - 5)

    def test_gen1_six_player_prior_is_shorter_than_five(self):
        # 6p (online app allows it): the board fills faster than 5p — the
        # prior must move DOWN, never fall back to the generic 10.
        six = clock.estimate({"temperature": -30, "oxygen": 0, "oceans": 0},
                             generation=1, players=6)
        five = clock.estimate({"temperature": -30, "oxygen": 0, "oceans": 0},
                              generation=1, players=5)
        self.assertLess(six["endGeneration"], five["endGeneration"])
        self.assertEqual(six["endGeneration"], 8)

    def test_gen1_uses_player_count_prior(self):
        est = clock.estimate({"temperature": -30, "oxygen": 0, "oceans": 0},
                             generation=1, players=5)
        self.assertGreaterEqual(est["endGeneration"], 8)
        self.assertLessEqual(est["endGeneration"], 10)

    def test_phase_advice_matches_kb_cutoff(self):
        # production cutoff = last 3-4 gens (01-valuation-economy.md)
        est = clock.estimate({"temperature": -4, "oxygen": 10, "oceans": 7},
                             generation=8)
        self.assertIn(est["phase"], ("points",))
        early = clock.estimate({"temperature": -28, "oxygen": 1, "oceans": 0},
                               generation=2, players=5)
        self.assertIn(early["phase"], ("economy",))


if __name__ == "__main__":
    unittest.main()


import endgame
import odds


class TestEndgame(unittest.TestCase):
    def test_heat_conversions_maximized(self):
        best = endgame.best_line(
            resources={"mc": 0, "heat": 16, "plants": 0},
            globals_={"temperature": -4, "oxygen": 14, "oceans": 9}, gens=1)
        self.assertEqual(best["vpGain"], 2)  # two 8-heat → temp conversions
        self.assertEqual(len([a for a in best["actions"]
                              if "heat" in a]), 2)

    def test_maxed_temperature_makes_heat_worthless(self):
        best = endgame.best_line(
            resources={"mc": 0, "heat": 16, "plants": 0},
            globals_={"temperature": 8, "oxygen": 14, "oceans": 9}, gens=1)
        self.assertEqual(best["vpGain"], 0)

    def test_greenery_conversion_beats_asteroid_with_same_budget(self):
        # 8 plants → greenery = 1 TR + 1 VP; 14 MC asteroid = 1 TR
        best = endgame.best_line(
            resources={"mc": 14, "heat": 0, "plants": 8},
            globals_={"temperature": -4, "oxygen": 10, "oceans": 9}, gens=1)
        self.assertEqual(best["vpGain"], 3)  # greenery (2) + asteroid (1)

    def test_milestone_when_eligible_dominates(self):
        best = endgame.best_line(
            resources={"mc": 8, "heat": 0, "plants": 0},
            globals_={"temperature": 8, "oxygen": 14, "oceans": 9},
            gens=1, milestone_eligible=True)
        self.assertEqual(best["vpGain"], 5)
        self.assertTrue(any("milestone" in a.lower() for a in best["actions"]))

    def test_two_gens_uses_production_income(self):
        # gen 1: nothing affordable; production adds 14 MC (TR 12 + prod 2)
        # → gen 2 asteroid affordable
        best = endgame.best_line(
            resources={"mc": 1, "heat": 0, "plants": 0},
            globals_={"temperature": -4, "oxygen": 14, "oceans": 9},
            gens=2, tr=12, production={"mc": 2, "heat": 0, "plants": 0})
        self.assertGreaterEqual(best["vpGain"], 1)

    def test_ocean_cap_respected(self):
        best = endgame.best_line(
            resources={"mc": 40, "heat": 0, "plants": 0},
            globals_={"temperature": 8, "oxygen": 14, "oceans": 9}, gens=1)
        self.assertTrue(all("aquifer" not in a.lower() for a in best["actions"]))


class TestOdds(unittest.TestCase):
    def test_p_at_least_one_known_value(self):
        # deck 10, 5 matching, draw 2: 1 - C(5,2)/C(10,2) = 7/9
        p = odds.p_at_least_one(matching=5, deck_size=10, draws=2)
        self.assertAlmostEqual(p, 7 / 9, places=6)

    def test_one_of_four_in_two_draws_is_half(self):
        # 1 - C(3,2)/C(4,2) = 1 - 3/6 = 1/2
        self.assertAlmostEqual(odds.p_at_least_one(1, 4, 2), 0.5, places=9)

    def test_two_of_five_in_two_draws(self):
        # 1 - C(3,2)/C(5,2) = 1 - 3/10 = 7/10
        self.assertAlmostEqual(odds.p_at_least_one(2, 5, 2), 0.7, places=9)

    def test_expected_hits(self):
        self.assertAlmostEqual(odds.expected(matching=5, deck_size=10, draws=4), 2.0)

    def test_zero_matching(self):
        self.assertEqual(odds.p_at_least_one(0, 50, 10), 0.0)

    def test_zero_draws(self):
        self.assertEqual(odds.p_at_least_one(5, 50, 0), 0.0)

    def test_draws_capped_at_deck(self):
        self.assertEqual(odds.p_at_least_one(1, 3, 10), 1.0)


# ── odds.py removal: plant-removal deck composition ──

FAKE_DB = {"cards": [
    {"name": "Rock Thrower", "type": "event",
     "effects": "Remove up to 3 plants from any player."},
    {"name": "Sneaky Spores", "type": "automated",
     "effects": "remove 5 Plants from another player."},
    {"name": "Grass", "type": "automated",
     "effects": "Increase your plant production 1 step."},
    {"name": "Quiet Mines", "type": "automated",
     "effects": "Increase your steel production 2 steps."},
    {"name": "Peaceful Fields", "type": "automated",
     "effects": "Gain 3 plants."},
    {"name": "Attack Corp", "type": "corporation",
     "effects": "Remove 2 plants from any player."},
]}


class TestRemovalOdds(unittest.TestCase):
    def test_counts_matching_project_cards_only(self):
        # corporation excluded from the deck; 2 of 5 project cards match
        count, deck, names = odds.count_removal(FAKE_DB)
        self.assertEqual(count, 2)
        self.assertEqual(deck, 5)
        self.assertEqual(names, ["Rock Thrower", "Sneaky Spores"])

    def test_removal_report_exact_fraction(self):
        # 2 matching of 5, hand of 2: P = 1 - C(3,2)/C(5,2) = 7/10
        rep = odds.removal_report(FAKE_DB, hands=(2,))
        self.assertIn("2 of 5", rep)
        self.assertIn("70.0%", rep)

    def test_removal_report_real_db_shape(self):
        # real deck: count > 0, fraction line + three default hand sizes
        import cards
        rep = odds.removal_report(cards.load_db())
        for h in (4, 8, 12):
            self.assertIn(f"drew {h}", rep)


# ── evalprotocol.py: N-game evaluation ledger ──
# (housed here with the other script-level tests; no dedicated file
#  was provisioned for evalprotocol)

import json as _json
import tempfile

import evalprotocol
from test_new_game import SETUP


class TestEvalProtocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "evals.jsonl"
        self.game_dir = Path(self.tmp.name) / "2031-03-01-game1"
        self.game_dir.mkdir()
        (self.game_dir / "setup.json").write_text(_json.dumps(SETUP))

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_appends_jsonl_with_me_from_setup(self):
        evalprotocol.record(self.file, game=self.game_dir, winner="Zed",
                            margin=18, model="fable-5", notes="clean win",
                            shape=False)
        evalprotocol.record(self.file, game=self.game_dir, winner="Anna",
                            margin=-4, model="fable-5", notes="", shape=False)
        lines = self.file.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        first = _json.loads(lines[0])
        self.assertEqual(first["winner"], "Zed")
        self.assertEqual(first["me"], "Zed")   # from setup.json isMe
        self.assertEqual(first["margin"], 18)
        self.assertEqual(first["model"], "fable-5")

    def test_report_aggregates_per_model(self):
        evalprotocol.record(self.file, game=self.game_dir, winner="Zed",
                            margin=18, model="fable-5", shape=False)
        evalprotocol.record(self.file, game=self.game_dir, winner="Anna",
                            margin=-4, model="fable-5", shape=False)
        evalprotocol.record(self.file, game=self.game_dir, winner="Zed",
                            margin=2, model="sonnet", shape=False)
        rep = evalprotocol.report(self.file)
        self.assertIn("fable-5", rep)
        self.assertIn("sonnet", rep)
        self.assertIn("50%", rep)         # fable-5: 1 win of 2
        self.assertIn("100%", rep)        # sonnet: 1 of 1
        self.assertIn("+7.0", rep)        # fable-5 margin mean (18-4)/2
        self.assertIn("-4", rep)          # fable-5 margin min
        self.assertIn("+18", rep)         # fable-5 margin max

    def test_report_without_file_is_graceful(self):
        rep = evalprotocol.report(Path(self.tmp.name) / "missing.jsonl")
        self.assertIn("no evals recorded", rep.lower())


class TestClockEarlyPrior(unittest.TestCase):
    def test_early_slow_observation_capped_by_player_prior(self):
        import clock
        # gen 2, one lonely temp step done — naive rate says ~30+ gens
        est = clock.estimate({"temperature": -28, "oxygen": 0, "oceans": 0},
                             generation=2, players=3)
        # issue #22 recalibrated the 3p prior to 13 (game2 ran to gen 14);
        # the point of this test is the cap, not the old number
        self.assertLessEqual(est["endGeneration"], 14)   # 3p prior 13 (+1)

    def test_fast_observation_still_trusted(self):
        import clock
        est = clock.estimate({"temperature": -10, "oxygen": 7, "oceans": 6},
                             generation=4, players=3)
        self.assertLess(est["endGeneration"], 11)


class TestEvalBotsField(unittest.TestCase):
    def test_record_stores_bots(self):
        import evalprotocol, tempfile, json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "evals.jsonl"
            e = evalprotocol.record(f, "games/x", "Zed", 10, "fable-5",
                                    bots="dummy-v1", shape=False)
            self.assertEqual(e["bots"], "dummy-v1")
            self.assertEqual(json.loads(f.read_text())["bots"], "dummy-v1")


class TestClockAcceleratingFill(unittest.TestCase):
    """At gen 6 a flat-average model can say 'end ~gen 16' when the real
    end is gen 10 -- the advisor keeps buying economy through gen 8-9 on
    a 6-gen payback that never existed, and finishes last. Root cause: fill RATE GROWS as engines mature (observed: 2.4
    steps/gen average over gens 1-5, then 6 steps/gen over gens 6-10).
    A constant-acceleration multiplier can't capture that; a model where
    rate grows linearly with generation (steps ~ quadratic in time) fits
    the whole trajectory."""

    def test_fast_table_gen6_predicts_real_end(self):
        import clock
        # a real fast-table state at gen 6: temp -20 (5 steps), O2 6%, oceans 1
        est = clock.estimate({"temperature": -20, "oxygen": 6, "oceans": 1},
                             generation=6, players=5)
        self.assertGreaterEqual(est["endGeneration"], 9)
        self.assertLessEqual(est["endGeneration"], 11)   # actual: 10
        self.assertIn(est["phase"], ("points", "transition"))

    def test_fast_table_gen9_predicts_imminent_end(self):
        import clock
        # a real fast-table state entering gen 9: temp/O2 maxed, oceans 6
        est = clock.estimate({"temperature": 8, "oxygen": 14, "oceans": 6},
                             generation=9, players=5)
        self.assertLessEqual(est["endGeneration"], 10)   # actual: 10
        self.assertEqual(est["phase"], "points")

    def test_end_never_before_current_generation(self):
        import clock
        # a blazing rate must clamp end >= current generation
        est = clock.estimate({"temperature": 6, "oxygen": 14, "oceans": 8},
                             generation=12, players=5)
        self.assertGreaterEqual(est["endGeneration"], 12)
