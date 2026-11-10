"""Item 4a — two of the four shape metrics were BLIND on the API path.

Measured on games/2026-08-31-game1 (12 generations, full API autopilot):

  * `shape.cardsBought.mine == {}` — every research line in the log was an
    OPPONENT's. My own buys go through `execute.py pick`, which charged the
    tracker but never wrote the "Research: dealt […], kept […]" line that
    `shape.cards_bought` parses. The buy-0 gate reads that series, so the
    flagship gate of the previous fix plan never fired once — in a game
    where I bought zero cards in three consecutive generations.
  * `shape.vpSlope is None` — zero "Standings (…)" lines. `produce.py`
    logged them; the LISTENER (replay_applog) calls `Engine.produce`
    directly, and in app modes the listener owns turnover.

The fix is one composer with two callers (`Engine.dealt` and
`execute.py pick`) and standings logging inside `Engine.produce`, so every
turnover path writes it. These are the unit tests; the end-to-end proof
demanded by the plan's VERIFICATION RULE lives in test_e2e_shape_api.py.
"""
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import shape                                   # noqa: E402
import tmlib                                   # noqa: E402
from tmlib import Engine, Store                # noqa: E402
from test_execute import ExecuteCase, view_from_game   # noqa: E402
from test_new_game import SETUP                # noqa: E402

BUY_TWO = {"type": "card", "title": "Select card(s) to buy",
           "cards": [{"name": "Comet"}, {"name": "Birds"}], "min": 0, "max": 2}
EXIT_ASK = 40


# ── the ONE composer ─────────────────────────────────────────


class TestResearchLineComposer(unittest.TestCase):
    """One format string, two callers. The shape is FROZEN: historical
    logs (games/2026-08-29-*/log.md) must keep parsing."""

    def test_dealt_shape_is_the_historical_one(self):
        line = tmlib.research_log_line(["Adapted Lichen", "Birds"],
                                       ["Adapted Lichen"], 3, 16)
        self.assertEqual(
            line,
            "Research: dealt ['Adapted Lichen', 'Birds'], "
            "kept ['Adapted Lichen'] (−3 MC → 16)")

    def test_historical_line_still_parses(self):
        hist = ("- G2 — Research: dealt ['Adapted Lichen', 'Restricted Area'], "
                "kept ['Adapted Lichen'] (−3 MC → 16)")
        m = shape._DEALT.match(hist)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("gen"), "2")

    def test_composed_line_parses(self):
        line = "- G4 — " + tmlib.research_log_line(["A", "B"], ["A"], 3, 9)
        self.assertIsNotNone(shape._DEALT.match(line))

    def test_drafted_shape(self):
        line = tmlib.research_log_line(["A", "B"], ["A"], 3, 9, drafted=True)
        self.assertEqual(line, "Research: drafted A,B → kept A (−3 MC → 9)")
        self.assertIsNotNone(shape._DRAFTED.match("- G4 — " + line))

    def test_suffix_is_appended(self):
        line = tmlib.research_log_line(["A"], [], 0, 9, suffix=" — tag")
        self.assertTrue(line.endswith(" — tag"), line)


# ── execute.py pick writes the same line ─────────────────────


class PickCase(ExecuteCase):
    def log(self) -> str:
        return self.store.log_path.read_text()

    def buy(self, *names, extra=()):
        self.start_app([view_from_game(self.game(), BUY_TWO),
                        view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick", *names, *extra)
        self.app.close()
        self.app = None
        return rc, out


class TestPickLogsTheResearchLine(PickCase):
    def test_a_buy_is_logged_in_the_shape_py_format(self):
        rc, out = self.buy("Comet")
        self.assertEqual(rc, 0, out)
        self.assertIn("Research: dealt", self.log())
        self.assertIn("kept ['Comet']", self.log())

    def test_shape_sees_my_buy_from_the_api_path(self):
        rc, out = self.buy("Comet")
        self.assertEqual(rc, 0, out)
        gen = self.game()["generation"]
        self.assertEqual(shape.compute(self.store)["cardsBought"]["mine"],
                         {gen: 1})

    def test_a_declined_research_is_logged_as_zero(self):
        rc, out = self.buy()
        self.assertEqual(rc, 0, out)
        gen = self.game()["generation"]
        self.assertEqual(shape.compute(self.store)["cardsBought"]["mine"],
                         {gen: 0})

    def test_the_dealtlog_entry_is_recorded(self):
        rc, out = self.buy("Comet")
        self.assertEqual(rc, 0, out)
        entry = self.game()["me"]["dealtLog"][-1]
        self.assertEqual(entry["kept"], ["Comet"])
        self.assertIn("Comet", entry["dealt"])

    def test_pick_and_apply_dealt_produce_the_same_line_shape(self):
        """The two callers, side by side: same regex, same groups."""
        self.buy("Comet")
        mine = [ln for ln in self.log().splitlines() if "Research: dealt" in ln]
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.init(SETUP)
            eng = Engine(store)
            eng.res("Zed", "mc", +30)
            eng.dealt(["Comet", "Birds"], ["Comet"])
            theirs = [ln for ln in store.log_path.read_text().splitlines()
                      if "Research: dealt" in ln]
        self.assertEqual(len(mine), 1)
        self.assertEqual(len(theirs), 1)
        a, b = shape._DEALT.match(mine[0]), shape._DEALT.match(theirs[0])
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(a.group("kept"), b.group("kept"))


# ── the buy-0 gate, re-armed on the API path ─────────────────


class TestBuyZeroGateOnTheApiPath(PickCase):
    """The regression that proves the flagship gate is alive where it
    matters: two consecutive zero-buy research phases through
    `execute.py pick` must REFUSE before transmitting."""

    def _turnover(self):
        Engine(self.store).produce()

    def test_second_consecutive_zero_buy_is_refused_before_sending(self):
        rc, _ = self.buy()
        self.assertEqual(rc, 0)
        self._turnover()
        self.start_app([view_from_game(self.game(), BUY_TWO),
                        view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick")
        self.assertEqual(rc, EXIT_ASK, out)
        self.assertEqual(self.app.posts, [])            # nothing transmitted
        self.assertIn("RESEARCH kept=0 REFUSED", out)
        self.assertIn("GATE research buy-0 REFUSED", self.log())

    def test_a_buy_after_a_zero_is_never_gated(self):
        rc, _ = self.buy()
        self.assertEqual(rc, 0)
        self._turnover()
        rc, out = self.buy("Comet")
        self.assertEqual(rc, 0, out)

    def test_the_gate_is_overridable_and_the_reason_is_logged(self):
        rc, _ = self.buy()
        self.assertEqual(rc, 0)
        self._turnover()
        rc, out = self.buy(extra=("--override", "hand is full of playables"))
        self.assertEqual(rc, 0, out)
        self.assertIn("buy-0 gate OVERRIDDEN: hand is full of playables",
                      self.log())

    def test_shape_flags_the_two_zero_generations(self):
        rc, _ = self.buy()
        self.assertEqual(rc, 0)
        self._turnover()
        self.buy(extra=("--override", "scripted"))
        self.assertIsNotNone(shape.compute(self.store)["flags"]["cardsBought"])


# ── standings on EVERY turnover path ─────────────────────────


class TestEngineProduceLogsStandings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)

    def tearDown(self):
        self.tmp.cleanup()

    def log(self) -> str:
        return self.store.log_path.read_text()

    def test_direct_engine_turnover_logs_standings(self):
        """The listener (replay_applog) calls Engine.produce DIRECTLY, so
        the standings line has to come from the engine, not the CLI."""
        Engine(self.store).produce()
        self.assertIn("Standings (", self.log())

    def test_vp_slope_after_two_direct_turnovers(self):
        eng = Engine(self.store)
        eng.produce()
        eng.tr("Zed", +3)
        eng.produce()
        self.assertIsNotNone(shape.compute(self.store)["vpSlope"])

    def test_the_cli_does_not_log_it_twice(self):
        import produce
        produce.turnover(self.store)
        self.assertEqual(self.log().count("Standings ("), 1)


if __name__ == "__main__":
    unittest.main()
