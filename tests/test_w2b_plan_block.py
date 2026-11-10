"""W2-B item 2: the tool-rendered plan block IS the house-style block —
planlib render / turn.py done output carry the contract glyphs (✅ done /
▶️ NEXT / ⬜ todo, 🔒/🔁 volatility, 🎯 EXIT), complete threats+exit+steps,
no code fences — and set_plan/patch validate the turn-grouped label
grammar ^[0-9]+[a-z]$ with labels in order, naming the offender.
Model-retyped blocks degrade under time pressure; the tool's cannot."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_new_game import SETUP                 # noqa: E402
from tmlib import Engine, EventError, Store     # noqa: E402
import planlib                                  # noqa: E402
import turn                                     # noqa: E402

THREATS = "Anna is 1 step from Builder"
EXIT = "test exit: card VP; repeatable: greenery from plant production"


def step(sid, summary="do the thing", vol="safe", **kw):
    return {"id": sid, "summary": summary, "volatility": vol,
            "events": [], **kw}


class PlanBlockBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def live_plan(self):
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT,
                                      "steps": [
            step("1a", "Play Sponsors"),
            step("1b", "SP asteroid", vol="recheck"),
            step("2a", "Pass", passGate=True)]})


class TestHouseStyleRender(PlanBlockBase):
    def test_glyphs_match_the_contract(self):
        self.live_plan()
        planlib.mark_done(self.store, "1a")
        out = planlib.render(self.store)
        self.assertIn("✅ 1a", out)                  # done
        self.assertIn("▶️ NEXT 1b", out)             # next open step
        self.assertIn("⬜ 2a", out)                  # todo
        self.assertIn("🔒", out)                     # volatility kept
        self.assertIn("🔁", out)
        self.assertIn("🎯 EXIT: " + EXIT, out)       # exit kept
        self.assertIn("⚠ THREATS", out)              # threats kept
        self.assertIn(THREATS, out)

    def test_old_glyphs_are_gone(self):
        self.live_plan()
        planlib.mark_done(self.store, "1a")
        out = planlib.render(self.store)
        self.assertNotIn("NEXT ▶ ", out)
        self.assertNotIn("▢", out)
        self.assertNotIn("✓ 1a", out)

    def test_no_code_fences(self):
        self.live_plan()
        self.assertNotIn("```", planlib.render(self.store))

    def test_turn_done_output_is_the_block(self):
        self.live_plan()
        out = turn.run(self.store, ["1a"])
        self.assertIn("✅ 1a", out)
        self.assertIn("▶️ NEXT 1b", out)
        self.assertIn("⬜ 2a", out)
        self.assertIn("🎯 EXIT:", out)
        self.assertIn("⚠ THREATS", out)
        self.assertNotIn("```", out)


class TestLabelGrammar(PlanBlockBase):
    def refuse(self, steps, *needles):
        with self.assertRaises(EventError) as ctx:
            planlib.set_plan(self.store, steps, draft=True)
        for n in needles:
            self.assertIn(n, str(ctx.exception))

    def test_malformed_labels_refused_naming_the_offender(self):
        self.refuse([step("1A")], "'1A'")
        self.refuse([step("a1")], "'a1'")
        self.refuse([step("1")], "'1'")
        self.refuse([step("1aa")], "'1aa'")
        self.refuse([step("pass")], "'pass'")

    def test_out_of_order_labels_refused_naming_the_offender(self):
        self.refuse([step("1a"), step("2a"), step("1b")], "'1b'", "'2a'")

    def test_letters_out_of_order_within_a_turn_refused(self):
        self.refuse([step("1b"), step("1a")], "'1a'", "'1b'")

    def test_duplicate_label_refused(self):
        self.refuse([step("1a"), step("1a")], "'1a'")

    def test_in_order_labels_accepted_including_turn_gaps(self):
        # execute-lane plans legally jump turn numbers (1a then 4a)
        planlib.set_plan(self.store, [step("1a"), step("1b"), step("4a")],
                         draft=True)
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT,
                                      "steps": [step("1a"), step("2a"),
                                                step("2b"),
                                                step("3a", passGate=True)]})

    def test_patch_insert_out_of_order_refused(self):
        self.live_plan()
        with self.assertRaises(EventError) as ctx:
            planlib.patch(self.store, {"insert_after":
                                       {"2a": [step("1c", "late insert")]}},
                          live=True)
        self.assertIn("'1c'", str(ctx.exception))

    def test_patch_insert_in_order_accepted(self):
        self.live_plan()
        plan = planlib.patch(self.store,
                             {"insert_after": {"1b": [step("1c", "extra")]}},
                             live=True)
        self.assertEqual([s["id"] for s in plan["steps"]],
                         ["1a", "1b", "1c", "2a"])


if __name__ == "__main__":
    unittest.main()
