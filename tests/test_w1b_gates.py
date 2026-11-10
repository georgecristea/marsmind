"""W1-B items 2-4: the post-game5 gates.

Doctrine (private plan, binding): scripts compute FACTS; gates interrupt
with a refusal that names the variable and the evidence and accepts an
override with a logged reason; gates never prescribe strategy; every
firing is visible in state/log.md.

- apply.py/tmlib dealt: a SECOND consecutive zero-kept research is
  refused (×2 evidence — game5 bought one card in gens 2-9) unless
  --override "<reason>" (logged).
- planlib set_plan: a live plan must carry an "exit" top-level string
  (the VP exit and its repeatable component), mirroring the threats
  gate; when shape.py reports zero repeatable sources, an exit with no
  repeatable-component acknowledgment is refused unless the plan carries
  "exitAck": "<reason>" (logged).
- planlib calibration guard: a "locked" claim against a "not lockable"
  verdict is refused with both strings quoted. (The original "the summary
  must EMBED the verdict" demand was deleted in B2 — the engine injects
  the verdict onto the step instead; see
  tests/test_b2_award_verdict_and_one_clock.py.)
- advise.py brief: mandatory "## SHAPE" section (both --brief and --full).
- clock.py: the planning horizon is the RANGE TOP — the note leads with
  "plan to gen <top>", the point estimate demoted to a parenthetical.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError  # noqa: E402
from test_new_game import SETUP  # noqa: E402
import advise  # noqa: E402
import clock  # noqa: E402
import planlib  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def log(self) -> str:
        return (self.root / "state" / "log.md").read_text()

    def bump_gen(self, n: int) -> None:
        g = self.store.load_game()
        g["generation"] = n
        self.store.save_game(g)


# ── item 2b: the zero-buy research gate ──────────────────────────────


class TestDealtBuyZeroGate(Fixture):
    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)

    def test_first_zero_keep_is_legal(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=[])

    def test_second_consecutive_zero_keep_is_refused_with_evidence(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=[])
        self.bump_gen(2)
        with self.assertRaises(EventError) as cm:
            self.eng.dealt(["Worms", "Algae", "Grass", "Trees"], kept=[])
        msg = str(cm.exception)
        self.assertIn("--override", msg)
        self.assertIn("gen 1", msg)
        self.assertIn("gen 2", msg)
        self.assertIn("0", msg)

    def test_refusal_does_not_prescribe_strategy(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=[])
        self.bump_gen(2)
        with self.assertRaises(EventError) as cm:
            self.eng.dealt(["Worms", "Algae", "Grass", "Trees"], kept=[])
        low = str(cm.exception).lower()
        for verb in ("should buy", "recommend", "must keep"):
            self.assertNotIn(verb, low)

    def test_refusal_leaves_state_untouched(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=[])
        self.bump_gen(2)
        before = self.store.load_game()
        with self.assertRaises(EventError):
            self.eng.dealt(["Worms", "Algae", "Grass", "Trees"], kept=[])
        self.assertEqual(self.store.load_game(), before)

    def test_override_records_and_logs_the_reason(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=[])
        self.bump_gen(2)
        self.eng.dealt(["Worms", "Algae", "Grass", "Trees"], kept=[],
                       override="nothing above water; saving for Terraformer")
        self.assertEqual(len(self.store.load_game()["me"]["dealtLog"]), 2)
        self.assertIn("OVERRIDDEN", self.log())
        self.assertIn("nothing above water", self.log())

    def test_zero_after_a_positive_keep_is_legal(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=["Comet"])
        self.bump_gen(2)
        self.eng.dealt(["Worms", "Algae", "Grass", "Trees"], kept=[])

    def test_positive_keep_after_a_zero_is_legal(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=[])
        self.bump_gen(2)
        self.eng.dealt(["Worms", "Algae", "Grass", "Trees"], kept=["Worms"])

    def test_non_consecutive_zeros_are_legal(self):
        self.eng.dealt(["Comet", "Birds", "Fish", "Moss"], kept=[])
        self.bump_gen(3)                       # gen 2 had no research logged
        self.eng.dealt(["Worms", "Algae", "Grass", "Trees"], kept=[])

    def test_cli_wires_the_override_flag(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "apply.py"), "dealt",
             "A", "B", "C", "D", "--override", "cli smoke"],
            cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


# ── item 2c: the exit gate on plans ──────────────────────────────────


def _steps():
    return [{"id": "1a", "summary": "pass", "volatility": "safe",
             "events": [], "passGate": True}]


class TestExitGate(Fixture):
    def test_live_plan_without_exit_is_refused(self):
        with self.assertRaises(EventError) as cm:
            planlib.set_plan(self.store, _steps(), threats=THREATS)
        self.assertIn("exit", str(cm.exception).lower())

    def test_live_plan_dict_without_exit_is_refused(self):
        with self.assertRaises(EventError):
            planlib.set_plan(self.store,
                             {"threats": THREATS, "steps": _steps()})

    def test_exit_kwarg_and_dict_key_both_accepted_and_stored(self):
        planlib.set_plan(self.store, _steps(), threats=THREATS, exit_=EXIT)
        self.assertEqual(planlib.load_plan(self.store)["exit"], EXIT)
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT,
                                      "steps": _steps()})
        self.assertEqual(planlib.load_plan(self.store)["exit"], EXIT)

    def test_blank_exit_is_refused(self):
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, _steps(), threats=THREATS,
                             exit_="   ")

    def test_draft_may_omit_exit_but_promote_requires_it(self):
        planlib.set_plan(self.store, _steps(), draft=True)
        with self.assertRaises(EventError) as cm:
            planlib.promote(self.store, threats=THREATS)
        self.assertIn("exit", str(cm.exception).lower())
        self.assertEqual(planlib.promote(self.store, threats=THREATS,
                                         exit_=EXIT), "promoted")

    def test_render_shows_the_exit(self):
        planlib.set_plan(self.store, _steps(), threats=THREATS, exit_=EXIT)
        self.assertIn(EXIT, planlib.render(self.store))


class TestExitAckGate(Fixture):
    """Fresh game: zero repeatable sources and a long clock — shape's
    sources flag is up, so a live plan's exit must acknowledge its
    repeatable component (the string names one) or carry exitAck."""

    def test_exit_without_repeatable_component_is_refused_with_evidence(self):
        with self.assertRaises(EventError) as cm:
            planlib.set_plan(self.store, _steps(), threats=THREATS,
                             exit_="milestone sweep and tile VP")
        msg = str(cm.exception)
        self.assertIn("repeatable", msg.lower())
        self.assertIn("exitAck", msg)

    def test_exit_naming_a_repeatable_component_passes(self):
        planlib.set_plan(self.store, _steps(), threats=THREATS, exit_=EXIT)

    def test_exit_ack_overrides_and_is_logged(self):
        planlib.set_plan(
            self.store,
            {"threats": THREATS, "exit": "milestone sweep and tile VP",
             "exitAck": "sources arrive with 1b (Ironworks)",
             "steps": _steps()})
        self.assertIn("sources arrive with 1b", self.log())

    def test_no_refusal_when_a_repeatable_source_exists(self):
        self.eng.corp("Zed", "Thorgate", mc=48)
        self.eng.prod("Zed", "plants", +2)
        planlib.set_plan(self.store, _steps(), threats=THREATS,
                         exit_="milestone sweep and tile VP")


# ── item 4: award-funding calibration guard ──────────────────────────


class TestAwardCalibration(Fixture):
    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)

    def award_step(self, summary):
        return [{"id": "1a", "summary": summary, "volatility": "recheck",
                 "awardAck": "test fixture: funding is not the property under test",
                 "events": [{"method": "award", "args": ["Zed", "Banker"]}]},
                {"id": "1b", "summary": "pass", "volatility": "safe",
                 "events": [], "passGate": True}]

    def verdict(self):
        import menu
        return menu.award_lock(self.store.load_game(), "Banker",
                               self.store.load_setup())

    def make_lockable(self):
        g = self.store.load_game()
        g["declaredFinalGeneration"] = g["generation"]
        g["me"]["production"]["mc"] = 4
        self.store.save_game(g)

    def set_plan(self, summary):
        planlib.set_plan(self.store, self.award_step(summary),
                         threats=THREATS, exit_=EXIT)

    def test_fixture_verdicts(self):
        self.assertFalse(self.verdict()["lockable"])
        self.make_lockable()
        self.assertTrue(self.verdict()["lockable"])

    def test_award_step_without_verdict_in_summary_is_accepted(self):
        # B2 item 3 REPLACED this refusal: the engine injects the verdict
        # onto the step (lockVerdict) instead of demanding it in prose.
        # Full coverage: tests/test_b2_award_verdict_and_one_clock.py
        self.set_plan("fund Banker (8 MC)")
        step = planlib.load_plan(self.store)["steps"][0]
        self.assertIn(self.verdict()["why"], step["lockVerdict"])

    def test_summary_embedding_not_lockable_verdict_passes(self):
        self.set_plan("fund Banker (8 MC) — lock test: not lockable "
                      "(mine 0 vs reach)")

    def test_summary_embedding_lockable_verdict_passes(self):
        self.make_lockable()
        self.set_plan("fund Banker (8 MC) — lock test: LOCKABLE")

    def test_locked_claim_against_not_lockable_verdict_is_refused(self):
        with self.assertRaises(EventError) as cm:
            self.set_plan("fund Banker (8 MC) — not lockable per menu, "
                          "but effectively locked")
        msg = str(cm.exception)
        self.assertIn("locked", msg)
        self.assertIn("not lockable", msg)

    def test_locked_claim_with_lockable_verdict_passes(self):
        self.make_lockable()
        self.set_plan("fund Banker (8 MC) — LOCKABLE, locked in")

    def test_unlockable_wording_does_not_count_as_a_locked_claim(self):
        # "unlockable"/"not lockable" must not trip the word-boundary check
        self.set_plan("fund Banker (8 MC) — verdict not lockable "
                      "(unlockable this game)")


# ── item 2a: the SHAPE section of the brief ──────────────────────────


class TestBriefShapeSection(Fixture):
    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)

    def test_brief_mode_has_shape_section(self):
        b = advise.build_brief(self.root, brief=True)
        self.assertIn("## SHAPE", b)
        self.assertIn("cards bought", b.lower())

    def test_full_mode_has_shape_section(self):
        b = advise.build_brief(
            self.root,
            kb_dir=Path(__file__).parent.parent / "strategy", brief=False)
        self.assertIn("## SHAPE", b)


# ── shape data supply: turnover logs the standings line ──────────────


class TestTurnoverLogsStandings(Fixture):
    def test_standings_line_is_logged_so_vp_slope_has_data(self):
        """score.standings_line was only PRINTED at turnover; shape.py's
        VP slope reads standings from state/log.md, so turnover logs it."""
        import produce
        import shape
        produce.turnover(self.store)
        self.assertIn("Standings", self.log())
        produce.turnover(self.store)
        m = shape.compute(self.store)
        self.assertIsNotNone(m["vpSlope"])


# ── item 3: planning horizon = range top ─────────────────────────────


def _g(t, o, w):
    return {"temperature": t, "oxygen": o, "oceans": w}


class TestClockPlanHorizon(unittest.TestCase):
    def test_game5_shape_range_7_9_plans_to_gen_9(self):
        """Regression for game5: the clock printed range 7-9 mid-game, the
        game ended at gen 9, and the plan had been cut to the point
        estimate. The note now LEADS with the range top."""
        hist = [_g(-30, 0, 0), _g(-30, 0, 0), _g(-30, 0, 0), _g(-28, 0, 0)]
        est = clock.estimate(_g(0, 0, 0), 5, players=5, history=hist)
        self.assertEqual(est["endRange"], [7, 9])
        self.assertTrue(est["note"].startswith("plan to gen 9"), est["note"])
        self.assertIn("range 7-9", est["note"])
        self.assertIn("end ~gen 7", est["note"])   # demoted, still visible

    def test_point_estimate_is_parenthesised(self):
        hist = [_g(-30, 0, 0), _g(-30, 0, 0), _g(-30, 0, 0), _g(-28, 0, 0)]
        est = clock.estimate(_g(0, 0, 0), 5, players=5, history=hist)
        lead = est["note"].split("(")[0]
        self.assertNotIn("end ~gen", lead)
        self.assertIn("(", est["note"])

    def test_gen1_prior_note_leads_with_range_top(self):
        est = clock.estimate(_g(-30, 0, 0), 1, players=5)
        self.assertTrue(
            est["note"].startswith(f"plan to gen {est['endRange'][1]}"),
            est["note"])

    def test_declared_final_leads_with_plan_to_gen(self):
        est = clock.estimate(_g(-10, 5, 4), 8, players=5, declared_final=8)
        self.assertTrue(est["note"].startswith("plan to gen 8"), est["note"])
        self.assertIn("TABLE-DECLARED", est["note"])

    def test_all_maxed_leads_with_plan_to_gen(self):
        est = clock.estimate(_g(8, 14, 9), 11, players=5)
        self.assertTrue(est["note"].startswith("plan to gen 11"), est["note"])


if __name__ == "__main__":
    unittest.main()
