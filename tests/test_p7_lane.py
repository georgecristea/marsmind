"""P7 lane defects (the first full-autopilot game, sections 7.3 and 8 of its post-mortem).

D1 — per-opponent reasoning was unreachable in the fast path: `listen.py
wait` is a BLOCKING call that sleeps through every opponent turn and wakes
on a finished batch, so "after each opponent's turn" never happens and
lane 2 (`turn.py round`) fired once in twelve generations. The fix keeps
the blocking wait and moves the surfacing into the listener: a drain that
ends with unhandled hard triggers prints a loud, actionable JUDGMENT
banner, `turn.py go` repeats the warning so the loop cannot silently skip
judgment, and stale generation-boundary triggers are pruned so the list
carries live signal only.

D2 — a dead seat froze the table and the orchestrator learned it only from
a bare `listen.py wait` TIMEOUT. The timeout now names the seat the app is
waiting on, cheaply and without ever raising.
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import applog_parser as P                         # noqa: E402
import listen                                     # noqa: E402
import planlib                                    # noqa: E402
import triage                                     # noqa: E402
import turn                                       # noqa: E402
from appapi import AppClient, AppUnavailable      # noqa: E402
from test_listen import LINES, ME_PID, FakeApp, ListenBase   # noqa: E402
from test_new_game import SETUP                   # noqa: E402
from tmlib import Engine, Store                   # noqa: E402

GEN2 = 54          # applog line 54 = "Generation 2" (55 = first player)


# ── D1: the listener surfaces the judgment lane ───────────────────────

class TestJudgmentBanner(ListenBase):
    def test_drain_with_unhandled_triggers_prints_an_actionable_banner(self):
        self.reveal_to(80)                       # gens 1 + 2, incl. an attack
        r, out = self.drain()
        pend = triage.pending(triage.feed_path(self.store))
        self.assertTrue(pend)                    # the run's real signal
        self.assertIn("JUDGMENT NEEDED", out)
        self.assertIn(f"{len(pend)} unhandled", out)
        stole = next(e for e in self.feed() if e["kind"] == "stole")
        self.assertIn(f"#{stole['line']}", out.split("JUDGMENT NEEDED")[1])
        # the exact commands, not a vague nudge
        self.assertIn("advise.py --sweep", out)
        self.assertIn("triage.py", out.split("JUDGMENT NEEDED")[1])
        self.assertIn(f"handle {pend[0]['line']}", out)

    def test_no_banner_when_every_trigger_is_handled(self):
        self.reveal_to(80)
        self.drain()
        feed = triage.feed_path(self.store)
        triage.handle(feed, [e["line"] for e in triage.pending(feed)], "read")
        self.app.reveal(["Ben gained 3 M€"])     # a quiet opponent event
        r, out = self.drain()
        self.assertTrue(r.new)
        self.assertEqual(triage.pending(feed), [])
        self.assertNotIn("JUDGMENT NEEDED", out)

    def test_banner_repeats_at_go_even_without_new_events(self):
        self.reveal_to(80)
        self.drain()
        self.app.waiting = "Take your first action"
        r, out = self.drain()
        self.assertTrue(r.go)
        self.assertFalse(r.new)
        self.assertIn("JUDGMENT NEEDED", out)

    def test_wait_surfaces_the_banner_without_polling_changes(self):
        self.reveal_to(16)
        self.drain()
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            if len(sleeps) == 1:
                self.reveal_to(80)
                self.app.waiting = "Take your first action"
        t = [0]

        def clock():
            t[0] += 1
            return t[0]
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code, title = listen.wait(self.listener(), interval=1, idle=10,
                                      timeout=570, sleep=sleep, clock=clock)
        self.assertEqual(code, 30)
        self.assertIn("JUDGMENT NEEDED", buf.getvalue())
        self.assertEqual(sleeps, [1])            # still blocking, no extra polls


class TestStaleTriggerPruning(ListenBase):
    def test_past_generation_turnover_triggers_are_pruned(self):
        self.reveal_to(GEN2 - 1)                 # all of generation 1
        r, out = self.drain()
        raws = {e["raw"]: e for e in self.feed()}
        self.assertTrue(raws["Generation 1"]["trigger"])
        self.assertFalse(raws["Generation 1"]["handled"])     # still live
        self.assertFalse(raws["First player this generation is Anna"]["handled"])

        self.reveal_to(GEN2 + 1)                 # "Generation 2" + first player
        r, out = self.drain()
        self.assertEqual(self.game()["generation"], 2)
        feed = self.feed()
        handled = sorted(e["raw"] for e in feed if e["handled"])
        self.assertEqual(handled, ["First player this generation is Anna",
                                   "Generation 1"])
        note = next(e for e in feed if e["raw"] == "Generation 1")["handledNote"]
        self.assertIn("auto-resolved", note)
        live = {e["raw"] for e in feed if e["trigger"] and not e["handled"]}
        self.assertIn("Generation 2", live)      # this generation stays pending
        self.assertIn("First player this generation is Carl", live)

    def test_pruning_never_touches_a_non_turnover_trigger(self):
        self.reveal_to(80)
        self.drain()
        stole = next(e for e in self.feed() if e["kind"] == "stole")
        self.assertTrue(stole["trigger"])
        self.assertFalse(stole["handled"])


# ── D1: turn.py go warns instead of silently skipping judgment ────────

class TestGoWarnsOnPendingTriggers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        eng = Engine(self.store)
        eng.res("Zed", "mc", +40)
        eng.hand_add(["Comet"])
        self.empty = self.root / "no-scripts"
        self.empty.mkdir()
        planlib.set_plan(self.store, {"threats": "Anna 1 step from Builder",
                                      "exit": "test exit; repeatable: n/a",
                                      "steps": [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]}]}, draft=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _feed(self, trigger: bool):
        raw = "Anna claimed Builder milestone"
        players = [p["name"] for p in SETUP["players"]]
        e = triage.new_entry(P.parse_line(raw, players), line=7, gen=1, raw=raw)
        e["trigger"] = trigger
        e["reasons"] = ["milestone: Anna claimed Builder — 4 slot(s) left"] if trigger else []
        triage.write_feed(triage.feed_path(self.store), [e])

    def test_go_names_the_pending_triggers_and_still_promotes(self):
        self._feed(True)
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertEqual(rc, 0)
        self.assertIn("JUDGMENT", text)
        self.assertIn("#7 Anna claimed", text)
        self.assertIn("advise.py --sweep", text)
        self.assertIn("promoted", text)          # never blocks the turn
        self.assertEqual(text.strip().splitlines()[-1], "NEXT: 1a")

    def test_go_is_silent_when_nothing_is_pending(self):
        self._feed(False)
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertEqual(rc, 0)
        self.assertNotIn("JUDGMENT", text)

    def test_go_without_a_feed_file_is_silent(self):
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertEqual(rc, 0)
        self.assertNotIn("JUDGMENT", text)


# ── D2: TIMEOUT names the seat the table is waiting on ────────────────

class StallApp(FakeApp):
    """The app while a seat agent is dead: /api/waitingfor still says WAIT
    but names the colors it is waiting on; the player view marks the active
    seat and lists who has passed."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.blocking: list[str] = []
        self.passed: list[str] = []

    def handle(self, path, body):
        status, payload = super().handle(path, body)
        if path.split("?")[0] == "/api/waitingfor" and isinstance(payload, dict) \
                and payload.get("result") == "WAIT":
            payload["waitingFor"] = list(self.blocking)
        return status, payload

    def view(self):
        v = super().view()
        v["game"]["passedPlayers"] = list(self.passed)
        for p in v["players"]:
            p["isActive"] = p["color"] in self.blocking
        return v


class TestStallDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root, state_dir=root / "state")
        setup = json.loads((ROOT / "tests" / "fixtures" / "replay-4p-wgt"
                            / "setup.json").read_text())
        setup["gameMode"] = "app-online"
        for p in setup["players"]:
            if p["isMe"]:
                p["playerId"] = ME_PID
        self.app = StallApp(setup, self.store)
        setup["appUrl"] = self.app.url
        self.store.init(setup)
        self.colors = {p["name"]: p["color"] for p in setup["players"]}

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def listener(self):
        return listen.Listener(self.store, AppClient(self.app.url, timeout=2,
                                                     retries=1), ME_PID)

    def _wait(self, listener=None):
        t = [0]

        def clock():
            t[0] += 5
            return t[0]
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code, title = listen.wait(listener or self.listener(), interval=1,
                                      idle=10, timeout=10, sleep=lambda s: None,
                                      clock=clock)
        return code, buf.getvalue()

    def test_timeout_names_the_blocking_seat(self):
        self.app.blocking = [self.colors["Carl"]]
        self.app.passed = [self.colors["Ben"]]
        code, out = self._wait()
        self.assertEqual(code, 3)
        self.assertIn("TIMEOUT", out)
        self.assertIn("WAITING ON", out)
        self.assertIn("Carl", out)
        self.assertIn("Ben", out)                # passed seats named, not blamed
        self.assertNotIn("Carl", out.split("WAITING ON")[0])

    def test_timeout_says_so_when_the_app_names_nobody(self):
        code, out = self._wait()
        self.assertEqual(code, 3)
        self.assertIn("WAITING ON", out)
        self.assertIn("nobody", out.lower())

    def test_the_diagnostic_never_breaks_the_wait(self):
        L = self.listener()
        self.app.blocking = [self.colors["Carl"]]
        with mock.patch.object(L.client, "player",
                               side_effect=AppUnavailable("boom", self.app.url)):
            code, out = self._wait(L)
        self.assertEqual(code, 3)
        self.assertIn("TIMEOUT", out)
        self.assertIn("WAITING ON", out)

    def test_who_blocks_is_a_plain_string_and_cheap(self):
        self.app.blocking = [self.colors["Anna"]]
        L = self.listener()
        self.app.requests.clear()
        who = L.who_blocks()
        self.assertIsInstance(who, str)
        self.assertIn("Anna", who)
        self.assertLessEqual(len(self.app.requests), 2)   # waitingfor + player


if __name__ == "__main__":
    unittest.main()
