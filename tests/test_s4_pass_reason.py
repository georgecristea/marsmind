"""S4 — the pass-gate reason is pre-declared ON THE STEP.

P9: the pass gate refused eight times and the advisor re-sent each pass
with `--force "<why>"` — two round trips per generation for a decision the
plan had already made. A `passGate` step may now carry
`"force": "<per-item reason>"`. execute.py step/turn and planlib done read
it exactly as they read `--force`: accepted and logged in the same
OVERRIDDEN format, and STILL refused when the live saturation list holds
an item the reason does not mention. The command-line flag keeps working
and wins over the field.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Engine, EventError, Store
from test_execute import ExecuteCase, PASS, root_menu, view_from_game
from test_new_game import SETUP
import execute
import planlib

THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"

# the fixture's blocking items: claim Terraformer (TR 35) and 8 heat
COVERS_BOTH = ("Terraformer: 8 MC is the Kelp Farming money next generation; "
               "heat: 8 heat saved for the final-generation double convert")
COVERS_ONE = "Terraformer: 8 MC is the Kelp Farming money next generation"


def step_with_force(reason: str) -> dict:
    return {**PASS, "force": reason}


class TestExecuteStepField(ExecuteCase):
    def log(self) -> str:
        return (Path(self.tmp.name) / "state" / "log.md").read_text()

    def test_field_covering_every_item_passes_in_one_call(self):
        self.set_plan([step_with_force(COVERS_BOTH)])
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "4a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertTrue(self.plan_step("4a")["done"])

    def test_field_is_logged_in_the_overridden_format(self):
        self.set_plan([step_with_force(COVERS_BOTH)])
        self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "4a")
        self.assertEqual(rc, 0, out)
        self.assertIn("execute.py: pass with 2 available action(s) OVERRIDDEN: "
                      + COVERS_BOTH, self.log())

    def test_uncovered_item_is_still_refused_and_nothing_sent(self):
        self.set_plan([step_with_force(COVERS_ONE)])
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "4a")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [], "the pass must NOT reach the app")
        self.assertFalse(self.plan_step("4a")["done"])
        self.assertIn("PASS REFUSED", out)
        self.assertIn("heat", out)                    # the uncovered item is named
        self.assertNotIn("OVERRIDDEN", self.log())

    def test_cli_flag_wins_over_the_field(self):
        self.set_plan([step_with_force("nothing here is worth it")])   # covers nothing
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "4a", "--force", "cli reason wins")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertIn("OVERRIDDEN: cli reason wins", self.log())
        self.assertNotIn("nothing here is worth it", self.log())

    def test_turn_verb_reads_the_field_too(self):
        self.set_plan([step_with_force(COVERS_BOTH)])
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("turn", "4a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)

    def test_saturated_board_with_a_field_passes_without_an_override_log(self):
        self.set_plan([step_with_force(COVERS_BOTH)])
        empty = root_menu(cards=(), milestones=(), awards=(), heat=False,
                          actions=(), sp_disabled=("Aquifer", "City"))
        eng = Engine(self.store)
        eng.res("Zed", "mc", -30)
        eng.res("Zed", "heat", -8)
        eng.tr("Zed", -1)                              # Terraformer out of reach
        eng.hand_remove("Sponsors")
        eng.hand_remove("Power Plant")
        app = self.start_app([view_from_game(self.game(), empty)])
        rc, out = self.run_cli("step", "4a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertNotIn("OVERRIDDEN", self.log())

    def test_without_field_or_flag_the_refusal_is_unchanged(self):
        self.set_plan([PASS])
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "4a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])
        self.assertIn("PASS REFUSED — free/positive actions still available", out)


class TestPlanlibDoneField(unittest.TestCase):
    """`planlib.py done` — physical mode, where the gate REFUSES."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        Engine(self.store).res("Zed", "heat", +8)       # one blocking item: heat

    def tearDown(self):
        self.tmp.cleanup()

    def plan(self, reason=None):
        step = {"id": "2b", "summary": "Saturation → pass", "volatility": "safe",
                "passGate": True, "events": []}
        if reason is not None:
            step["force"] = reason
        planlib.set_plan(self.store, [step], threats=THREATS, exit_=EXIT)

    def log(self) -> str:
        return (Path(self.tmp.name) / "state" / "log.md").read_text()

    def test_field_covering_the_item_marks_done_and_logs_overridden(self):
        self.plan("heat: saving 8 heat for Caretaker")
        planlib.mark_done(self.store, "2b")
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])
        self.assertIn("Pass with available actions OVERRIDDEN: heat: saving 8 heat "
                      "for Caretaker (1 items)", self.log())

    def test_field_not_covering_the_item_is_refused(self):
        self.plan("Terraformer: too expensive")
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done(self.store, "2b")
        self.assertIn("PASS REFUSED", str(ctx.exception))
        self.assertIn("heat", str(ctx.exception).lower())
        self.assertFalse(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_cli_force_wins_over_the_field(self):
        self.plan("Terraformer: too expensive")          # covers nothing live
        planlib.mark_done(self.store, "2b", force="cli: heat stays for Caretaker")
        self.assertIn("OVERRIDDEN: cli: heat stays for Caretaker", self.log())
        self.assertNotIn("Terraformer: too expensive", self.log())

    def test_done_cli_reads_the_field(self):
        self.plan("heat: saving 8 heat for Caretaker")
        rc = planlib.main(["--root", self.tmp.name, "done", "2b"])
        self.assertEqual(rc, 0)
        self.assertIn("OVERRIDDEN: heat: saving 8 heat for Caretaker", self.log())


class TestCoverage(unittest.TestCase):
    """The coverage rule: an item is mentioned by its menu name or label,
    case-insensitively — never by guessing."""

    def items(self):
        return [{"kind": "milestone", "name": "Terraformer",
                 "label": "claim Terraformer", "detail": "TR 35/35"},
                {"kind": "convert", "name": "heat",
                 "label": "8 heat → temperature", "detail": "have 8 heat"}]

    def test_every_item_named_is_covered(self):
        self.assertEqual(planlib.uncovered_items(
            "terraformer: no; HEAT: keep it", self.items()), [])

    def test_the_label_counts_as_a_mention(self):
        self.assertEqual(planlib.uncovered_items(
            "claim Terraformer is 8 MC too many; 8 heat → temperature next gen",
            self.items()), [])

    def test_a_missing_item_is_returned_as_its_gate_line(self):
        self.assertEqual(planlib.uncovered_items("Terraformer: no", self.items()),
                         ["8 heat → temperature — have 8 heat"])

    def test_an_empty_reason_covers_nothing(self):
        self.assertEqual(len(planlib.uncovered_items("", self.items())), 2)


if __name__ == "__main__":
    unittest.main()
