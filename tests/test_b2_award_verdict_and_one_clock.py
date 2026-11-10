"""Wave B2: the award verdict is INJECTED, and there is ONE CLOCK.

Item 3 (award calibration). The old guard demanded that the step summary
embed menu.py's lock verdict, tested as `"lockable" in summary and
"not lockable" not in summary`. In a real game that REFUSED a correct plan
because the summary mentioned OTHER awards being "not lockable" — a false
positive, and crude gates train the operator to reflexively --force. The
engine already knows the verdict, so it injects it: `lockVerdict` is stored
on the step at set/patch time and RENDERED as its own line under the step
(`planlib show`, and therefore `turn.py done`). Machine-generated and
verbatim beats asking the model to quote it. The only remaining refusal is
the contradiction check — a summary claiming "locked" against a
"not lockable" verdict — now SCOPED to the sentence naming this step's
award, so another award's status can be mentioned safely.

Item 4d (ONE CLOCK). `research.py` printed "plan to gen 28 | range 10-28"
while `clock.py` printed "plan to gen 14 — range 10-14" from the same state
at the same moment. Not a second estimator: a second INPUT SET — every
in-process caller feeds clock.estimate the game's `history` (and the
declared final generation, and wgt), while the clock's own CLI fed none of
it, so the observed-rate projection that widens the range only existed on
one side. Both now build their inputs in one place
(`clock.estimate_for_game`), and this file asserts the two printed headers
agree on the same state.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError  # noqa: E402
from test_new_game import SETUP  # noqa: E402
import clock  # noqa: E402
import menu  # noqa: E402
import planlib  # noqa: E402
import research  # noqa: E402

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


# ── item 3: the verdict is injected, not demanded ────────────────────


class AwardFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)

    def steps(self, summary, award="Banker"):
        return [{"id": "1a", "summary": summary, "volatility": "recheck",
                 "awardAck": "test fixture: funding is not the property under test",
                 "events": [{"method": "award", "args": ["Zed", award]}]},
                {"id": "1b", "summary": "pass", "volatility": "safe",
                 "events": [], "passGate": True}]

    def verdict(self, award="Banker") -> dict:
        return menu.award_lock(self.store.load_game(), award,
                               self.store.load_setup())

    def make_lockable(self):
        g = self.store.load_game()
        g["declaredFinalGeneration"] = g["generation"]
        g["me"]["production"]["mc"] = 4
        self.store.save_game(g)

    def set_plan(self, summary, award="Banker"):
        return planlib.set_plan(self.store, self.steps(summary, award),
                                threats=THREATS, exit_=EXIT)

    def step(self, plan=None) -> dict:
        plan = plan or planlib.load_plan(self.store)
        return plan["steps"][0]


class TestVerdictInjection(AwardFixture):
    def test_fixture_verdicts(self):
        self.assertFalse(self.verdict()["lockable"])
        self.make_lockable()
        self.assertTrue(self.verdict()["lockable"])

    def test_not_lockable_verdict_is_stored_verbatim_on_the_step(self):
        why = self.verdict()["why"]
        self.assertIn("not lockable", why)
        plan = self.set_plan("Fund Banker 8 MC.")
        self.assertIn(why, self.step(plan)["lockVerdict"])
        self.assertIn("Banker", self.step(plan)["lockVerdict"])

    def test_lockable_verdict_is_stored_verbatim_on_the_step(self):
        self.make_lockable()
        why = self.verdict()["why"]
        self.assertIn("LOCKABLE", why)
        plan = self.set_plan("Fund Banker 8 MC.")
        self.assertIn(why, self.step(plan)["lockVerdict"])

    def test_render_carries_the_verbatim_why_on_its_own_line(self):
        why = self.verdict()["why"]
        self.set_plan("Fund Banker 8 MC.")
        line = next((ln for ln in planlib.render(self.store).splitlines()
                     if why in ln), None)
        self.assertIsNotNone(line, planlib.render(self.store))
        self.assertNotIn("Fund Banker 8 MC.", line)   # its OWN line

    def test_render_still_carries_the_verdict_once_the_step_is_done(self):
        # turn.py done marks the step, THEN renders — the moment the player
        # funds the award is exactly when the verdict must still be visible.
        why = self.verdict()["why"]
        self.set_plan("Fund Banker 8 MC.")
        planlib.mark_done_many(self.store, ["1a"], apply_events=True,
                               confirm="ok")
        self.assertIn(why, planlib.render(self.store))

    def test_lockable_render_carries_the_verbatim_why(self):
        self.make_lockable()
        why = self.verdict()["why"]
        self.set_plan("Fund Banker 8 MC.")
        self.assertIn(why, planlib.render(self.store))

    def test_patch_injects_the_verdict_too(self):
        planlib.set_plan(
            self.store,
            [{"id": "1a", "summary": "draw breath", "volatility": "safe",
              "events": []},
             {"id": "1b", "summary": "pass", "volatility": "safe",
              "events": [], "passGate": True}],
            threats=THREATS, exit_=EXIT)
        why = self.verdict()["why"]
        planlib.patch(self.store, {"replace": {"1a": {
            "id": "1a", "summary": "Fund Banker 8 MC.",
            "volatility": "recheck",
            "awardAck": "test fixture: funding is not the property under test",
            "events": [{"method": "award", "args": ["Zed", "Banker"]}]}}})
        self.assertIn(why, self.step()["lockVerdict"])

    def test_a_step_that_funds_no_award_carries_no_verdict(self):
        planlib.set_plan(
            self.store,
            [{"id": "1a", "summary": "draw breath", "volatility": "safe",
              "events": []},
             {"id": "1b", "summary": "pass", "volatility": "safe",
              "events": [], "passGate": True}],
            threats=THREATS, exit_=EXIT)
        self.assertNotIn("lockVerdict", self.step())
        self.assertNotIn("⚖", planlib.render(self.store))

    def test_summary_need_not_embed_the_verdict_any_more(self):
        # item 3b: the "summary must embed the verdict" demand is DELETED.
        self.set_plan("Fund Banker 8 MC.")
        self.make_lockable()

    def test_the_deleted_demand_is_not_logged_as_a_refusal(self):
        self.set_plan("Fund Banker 8 MC.")
        self.assertNotIn("award-calibration REFUSED", self.log())


class TestLockedClaimScoping(AwardFixture):
    def test_game1_false_positive_other_awards_not_lockable_is_accepted(self):
        """THE regression: the exact refusal from the 2026-08-31 practice
        game. The step funds a LOCKABLE award and the summary mentions the
        OTHER awards as not lockable — a correct plan the old substring
        test refused."""
        self.make_lockable()
        self.set_plan("Fund Banker 8 MC — first and cheapest slot. "
                      "Landlord and Miner are not lockable this game.")

    def test_locked_claim_against_a_not_lockable_verdict_is_still_refused(self):
        with self.assertRaises(EventError) as cm:
            self.set_plan("Fund Banker (8 MC) — not lockable per menu, "
                          "but effectively locked.")
        msg = str(cm.exception)
        self.assertIn("locked", msg)
        self.assertIn("not lockable", msg)
        self.assertIn("award-calibration REFUSED", self.log())

    def test_a_locked_claim_about_ANOTHER_award_is_not_my_claim(self):
        # scoping: the "locks" sentence names Landlord, not the funded
        # Banker, so it says nothing about this step's verdict.
        self.set_plan("Fund Banker 8 MC for the cheap slot. "
                      "Anna locks Landlord next generation regardless.")

    def test_a_locked_claim_in_the_same_sentence_is_still_refused(self):
        with self.assertRaises(EventError):
            self.set_plan("Fund Banker 8 MC — Landlord is gone but Banker "
                          "is locked from here.")

    def test_a_locked_claim_naming_no_award_is_read_as_this_award(self):
        # conservative fallback: prose that never names an award is about
        # the award the step funds.
        with self.assertRaises(EventError):
            self.set_plan("Fund the cheap first slot; it is locked.")

    def test_unlockable_wording_still_does_not_count_as_a_locked_claim(self):
        self.set_plan("Fund Banker (8 MC) — verdict not lockable "
                      "(unlockable this game).")

    def test_locked_claim_with_a_lockable_verdict_passes(self):
        self.make_lockable()
        self.set_plan("Fund Banker (8 MC) — LOCKABLE, locked in.")


class TestTerseBudgetMeetsInjection(AwardFixture):
    """Item 3d: Wave A's terse budget strips the award verdict from the
    measured length via `_exempt_substrings`. Now that the verdict is
    injected rather than hand-written the strip is usually a no-op — assert
    that, so the two features cannot silently fight."""

    def test_exempt_substrings_still_offers_the_verdict(self):
        self.set_plan("Fund Banker 8 MC.")
        why = self.verdict()["why"]
        self.assertIn(why, planlib._exempt_substrings(self.store, self.step()))

    def test_the_strip_is_a_no_op_when_the_summary_omits_the_verdict(self):
        summary = "Fund Banker 8 MC."
        self.set_plan(summary)
        self.assertEqual(planlib._budgeted_length(self.store, self.step()),
                         len(summary))

    def test_an_injected_verdict_never_pushes_a_step_over_budget(self):
        # the verdict lives on the step, not in the summary: a summary at
        # the budget stays at the budget however long the verdict is.
        summary = "F" * planlib.SUMMARY_BUDGET
        self.set_plan(summary)
        self.assertEqual(planlib._budgeted_length(self.store, self.step()),
                         planlib.SUMMARY_BUDGET)

    def test_a_hand_copied_verdict_is_still_exempt(self):
        why = self.verdict()["why"]
        summary = ("Fund Banker 8 → menu.py: " + why + " "
                   + "p" * (planlib.SUMMARY_BUDGET - 40))
        self.assertGreater(len(summary), planlib.SUMMARY_BUDGET)
        self.set_plan(summary)                       # accepted, not refused

    def test_prose_over_budget_is_still_refused(self):
        with self.assertRaises(EventError):
            self.set_plan("Fund Banker 8 MC. "
                          + "p" * (planlib.SUMMARY_BUDGET + 40))


# ── item 4d: ONE CLOCK ───────────────────────────────────────────────

# The real position: 2026-08-31 practice game, start of generation 4.
GEN4_GLOBALS = {"temperature": -22, "oxygen": 0, "oceans": 1}
GEN4_HISTORY = [{"generation": 1, "temperature": -28, "oxygen": 0, "oceans": 1},
                {"generation": 2, "temperature": -24, "oxygen": 0, "oceans": 1},
                {"generation": 3, "temperature": -22, "oxygen": 0, "oceans": 1}]


def _plan_to_gen(text: str) -> int:
    m = re.search(r"plan to gen (\d+)", text)
    assert m, text
    return int(m.group(1))


def _range(text: str) -> tuple[int, int]:
    m = re.search(r"range (\d+)-(\d+)", text)
    assert m, text
    return int(m.group(1)), int(m.group(2))


class TestOneClock(Fixture):
    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)
        g = self.store.load_game()
        g["generation"] = 4
        g["globals"] = dict(GEN4_GLOBALS)
        g["history"] = [dict(h) for h in GEN4_HISTORY]
        self.store.save_game(g)
        self.state = self.root / "state" / "game.json"

    def run_clock(self) -> dict:
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "clock.py"), "--state",
             str(self.state), "--setup", str(self.state.with_name("setup.json"))],
            capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def run_research(self) -> str:
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "research.py"), "Birds", "Comet",
             "--state", str(self.state)],
            capture_output=True, text=True, check=True)
        return out.stdout.splitlines()[0]

    def test_research_header_and_clock_note_agree(self):
        """The 2026-08-31 divergence: research said 'plan to gen 28 | range
        10-28' while clock.py said 'plan to gen 14 — range 10-14'."""
        note = self.run_clock()["note"]
        head = self.run_research()
        self.assertEqual(_plan_to_gen(head), _plan_to_gen(note),
                         f"{head!r} vs {note!r}")
        self.assertEqual(_range(head), _range(note), f"{head!r} vs {note!r}")

    def test_research_summary_matches_estimate_for_game(self):
        game = json.loads(self.state.read_text())
        setup = json.loads(self.state.with_name("setup.json").read_text())
        est = clock.estimate_for_game(game, setup)
        s = research.summary(game, [], setup=setup)
        self.assertEqual(list(s["endRange"]), list(est["endRange"]))
        self.assertEqual(s["gensLeft"], est["gensLeft"])
        self.assertEqual(s["endGeneration"], est["endGeneration"])

    def test_the_clock_cli_reads_the_games_history(self):
        # the root cause: the CLI's input set omitted `history`, so the
        # observed-rate projection that widens the range only existed for
        # the in-process callers.
        game = json.loads(self.state.read_text())
        setup = json.loads(self.state.with_name("setup.json").read_text())
        self.assertEqual(self.run_clock()["endRange"],
                         list(clock.estimate_for_game(game, setup)["endRange"]))
        self.assertNotEqual(
            clock.estimate(game["globals"], game["generation"],
                           players=setup["playerCount"])["endRange"],
            clock.estimate_for_game(game, setup)["endRange"])

    def test_explicit_history_still_overrides_the_cli(self):
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "clock.py"), "--state",
             str(self.state), "--setup",
             str(self.state.with_name("setup.json")),
             "--history", "[[-30,0,0]]"],
            capture_output=True, text=True, check=True)
        self.assertIn("endRange", json.loads(out.stdout))

    def test_declared_final_generation_pins_both(self):
        g = json.loads(self.state.read_text())
        g["declaredFinalGeneration"] = 4
        self.state.write_text(json.dumps(g))
        self.assertEqual(_plan_to_gen(self.run_research()), 4)
        self.assertEqual(_plan_to_gen(self.run_clock()["note"]), 4)


if __name__ == "__main__":
    unittest.main()
