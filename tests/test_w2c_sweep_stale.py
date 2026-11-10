"""W2-C: the non-blocking sweep protocol's glue. `advise.py --sweep`
stamps the feed cursor it read into state/sweep-inflight; a `planlib.py
patch` concluding that sweep is refused as STALE when the live feed cursor
has advanced past the stamp (override --stale-ok "<reason>", logged).
Single-writer stays the main thread; the standing plan is never
invalidated by a stale refusal (no patchFailed stamp)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_new_game import SETUP                 # noqa: E402
from tmlib import Engine, EventError, Store     # noqa: E402
import advise                                   # noqa: E402
import applog_parser as P                       # noqa: E402
import planlib                                  # noqa: E402
import triage                                   # noqa: E402

PLAYERS = [p["name"] for p in SETUP["players"]]
THREATS = "Anna is 1 step from Builder"
EXIT = "test exit: card VP; repeatable: greenery from plant production"


def entry(line: int, raw: str, gen: int = 1) -> dict:
    return triage.new_entry(P.parse_line(raw, PLAYERS), line=line, gen=gen,
                            raw=raw, ts="2026-01-01T00:00:00")


class StaleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        Engine(self.store)
        self.feed = triage.feed_path(self.store)
        triage.write_feed(self.feed, [
            entry(1, "Felix gained 2 megacredits"),
            entry(2, "Anna claimed Builder milestone")])
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT,
                                      "steps": [
            {"id": "1a", "summary": "keep cash", "volatility": "safe",
             "events": []},
            {"id": "1b", "summary": "pass", "volatility": "recheck",
             "passGate": True, "events": []}]})

    def tearDown(self):
        self.tmp.cleanup()

    def sweep(self):
        with contextlib.redirect_stdout(io.StringIO()):
            advise.build_sweep(self.store)

    def advance_feed(self, line, raw):
        triage.write_feed(self.feed, triage.read_feed(self.feed)
                          + [entry(line, raw)])

    def flag(self) -> dict | None:
        p = planlib.sweep_flag_path(self.store)
        return json.loads(p.read_text()) if p.exists() else None

    def patch(self, spec=None, **kw):
        return planlib.patch(self.store, spec or {"feed": [2]}, live=True, **kw)


class TestCursorStamp(StaleBase):
    def test_sweep_stamps_the_feed_cursor_it_read(self):
        self.sweep()
        info = self.flag()
        self.assertEqual(info["cursor"], 2)          # last feed line read
        self.assertEqual(info["lines"], [1, 2])

    def test_stamp_tracks_the_feed_tail_on_a_later_sweep(self):
        self.sweep()
        self.advance_feed(3, "Felix gained 1 heat")
        self.sweep()
        self.assertEqual(self.flag()["cursor"], 3)


class TestStaleGuard(StaleBase):
    def test_patch_refused_stale_when_feed_advanced_past_the_stamp(self):
        self.sweep()
        self.advance_feed(3, "Felix gained 1 heat")
        with self.assertRaises(EventError) as ctx:
            self.patch()
        msg = str(ctx.exception)
        self.assertIn("STALE", msg)
        self.assertIn("#3", msg)                     # live cursor named
        self.assertIn("#2", msg)                     # stamp named
        self.assertIn("--stale-ok", msg)

    def test_stale_refusal_leaves_the_standing_plan_executable(self):
        self.sweep()
        self.advance_feed(3, "Felix gained 1 heat")
        with self.assertRaises(EventError):
            self.patch({"replace": {"1a": {"summary": "changed",
                                           "volatility": "safe",
                                           "events": []}},
                        "feed": [2]})
        plan = planlib.load_plan(self.store)
        self.assertNotIn("patchFailed", plan)        # never a broken plan
        self.assertEqual(plan["steps"][0]["summary"], "keep cash")
        self.assertIsNotNone(self.flag())            # sweep still marked

    def test_stale_ok_overrides_applies_and_logs(self):
        self.sweep()
        self.advance_feed(3, "Felix gained 1 heat")
        with contextlib.redirect_stdout(io.StringIO()):
            self.patch(stale_ok="line 3 is a plain gain, judged irrelevant")
        self.assertIsNone(self.flag())               # sweep concluded
        log = self.store.log_path.read_text()
        self.assertIn("OVERRIDDEN", log)
        self.assertIn("line 3 is a plain gain", log)

    def test_patch_fine_when_the_feed_did_not_move(self):
        self.sweep()
        with contextlib.redirect_stdout(io.StringIO()):
            self.patch()
        self.assertIsNone(self.flag())

    def test_patch_without_a_sweep_in_flight_is_untouched(self):
        self.advance_feed(3, "Felix gained 1 heat")
        with contextlib.redirect_stdout(io.StringIO()):
            self.patch({"feed": [3]})                # no flag, no guard

    def test_cli_stale_ok_flag(self):
        self.sweep()
        self.advance_feed(3, "Felix gained 1 heat")
        spec = json.dumps({"feed": [2]})
        with mock.patch.object(sys, "stdin", io.StringIO(spec)), \
                contextlib.redirect_stdout(io.StringIO()):
            code = planlib.main(["--root", str(self.root), "patch", "--live",
                                 "--stale-ok", "judged irrelevant"])
        self.assertEqual(code, 0)

    def test_cli_refusal_without_stale_ok(self):
        self.sweep()
        self.advance_feed(3, "Felix gained 1 heat")
        spec = json.dumps({"feed": [2]})
        err = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(spec)), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            code = planlib.main(["--root", str(self.root), "patch", "--live"])
        self.assertEqual(code, 1)
        self.assertIn("STALE", err.getvalue())


if __name__ == "__main__":
    unittest.main()
