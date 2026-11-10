"""S5 — the unhandled-trigger surface lives IN execute.py, at the transmit
point. S6 — every execute.py invocation is latency-marked.

P9: `turn.py go` was the only place unread triggers surfaced, and with a
live plan every generation its promote was a no-op 38 times — the call
existed purely to run that check (~10 s each). Now `execute.py
step/turn/pass` call the same `triage.pending` before transmitting and
print the same JUDGMENT banner.

It WARNS and PROCEEDS — `turn.py go`'s contract verbatim ("it warns, not
refuses, so the loop cannot deadlock"). The first draft of this item made
it refuse; the scripted e2e proof then stopped dead at generation 1,
because turnover triggers (generation, first_player) arrive at EVERY
boundary and nothing in a no-model run dismisses them. `--force '<why>'`
suppresses the banner and logs the reason; a dry run says nothing.
`turn.py go` is untouched (the draft-promote path).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from test_execute import (ExecuteCase, PASS, PLAY_SPONSORS, after, root_menu,
                          view_from_game)
import execute
import latency
import triage

PENDING = {"line": 7, "ts": "2026-01-01T00:00:00", "gen": 1, "actor": "Anna",
           "kind": "play", "raw": "Anna played Asteroid",
           "event": {"kind": "played", "card": "Asteroid"},
           "trigger": True, "handled": False,
           "reasons": ["attack: Anna holds plant-removal cards — my plants exposed"]}


class GuardCase(ExecuteCase):
    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PASS])
        self.before = view_from_game(self.game(), root_menu(calculated={"Sponsors": 6}))
        self.landed = view_from_game(after(self.store, PLAY_SPONSORS["events"]),
                                     root_menu(cards=("Power Plant",)))

    def feed(self, entries):
        triage.write_feed(triage.feed_path(self.store), entries)

    def log(self) -> str:
        return (Path(self.tmp.name) / "state" / "log.md").read_text()


class TestTriggerGuard(GuardCase):
    def test_pending_trigger_warns_but_the_step_still_transmits(self):
        self.feed([PENDING])
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1, "the loop must never deadlock")
        self.assertTrue(self.plan_step("1a")["done"])
        self.assertIn("⚠ JUDGMENT: 1 unhandled trigger(s)", out)
        self.assertIn("#7 Anna play", out)           # the same rows `turn.py go` prints

    def test_a_turnover_trigger_does_not_stop_the_loop(self):
        """The e2e regression: generation/first_player triggers arrive at
        every boundary; a refusal there deadlocks the whole game."""
        turnover = {**PENDING, "kind": "generation",
                    "event": {"kind": "generation", "n": 1},
                    "reasons": ["generation 1 starts — turn order rotates"]}
        app = self.start_app([self.before, self.landed])
        self.feed([turnover])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)

    def test_empty_feed_transmits(self):
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertNotIn("JUDGMENT", out)

    def test_handled_trigger_transmits(self):
        self.feed([{**PENDING, "handled": True, "handledNote": "swept"}])
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)

    def test_force_overrides_and_is_logged(self):
        self.feed([PENDING])
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a", "--force", "plants already converted")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertIn("execute.py: 1 unhandled trigger(s) OVERRIDDEN: "
                      "plants already converted", self.log())
        self.assertIn("plants already converted", out)

    def test_dry_run_is_unaffected(self):
        self.feed([PENDING])
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [])
        self.assertIn("would send", out)
        self.assertNotIn("JUDGMENT", out)

    def test_turn_verb_warns_once_not_per_step(self):
        self.feed([PENDING])
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("turn", "1a", "4a")
        self.assertEqual(out.count("⚠ JUDGMENT"), 1)
        # 1a transmitted despite the trigger; 4a is a passGate step and the
        # SATURATION gate refuses it — a different gate, still refusing.
        self.assertEqual(len(app.posts), 1)
        self.assertTrue(self.plan_step("1a")["done"])
        if rc != 0:
            self.assertIn("PASS REFUSED", out)

    def test_turn_force_logs_the_override_once(self):
        self.feed([PENDING])
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("turn", "1a", "--force", "already read")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertEqual(self.log().count("unhandled trigger(s) OVERRIDDEN"), 1)

    def test_pass_verb_warns_without_blocking_on_the_trigger(self):
        """The trigger no longer stops `pass`; only the saturation gate can,
        and it names itself."""
        self.feed([PENDING])
        app = self.start_app([self.before, view_from_game(self.game(), None)])
        rc, out = self.run_cli("pass")
        self.assertIn("⚠ JUDGMENT", out)
        if rc != 0:
            self.assertIn("PASS REFUSED", out)
            self.assertNotIn("override with --force '<why the triggers",
                             out, "the trigger guard must not be the blocker")
        else:
            self.assertEqual(len(app.posts), 1)

    def test_pass_verb_force_sends(self):
        self.feed([PENDING])
        app = self.start_app([self.before, view_from_game(self.game(), None)])
        rc, out = self.run_cli("pass", "--force", "nothing to do about it")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertIn("unhandled trigger(s) OVERRIDDEN: nothing to do about it",
                      self.log())

    def test_a_trigger_that_resolved_itself_does_not_block(self):
        # generation-scoped (class f) trigger from a PAST generation: pending()
        # auto-resolves it, exactly as turn.py go would
        stale = {**PENDING, "gen": 0, "kind": "generation",
                 "event": {"kind": "generation", "n": 1},
                 "reasons": ["generation 1 starts — turn order rotates, "
                             "re-run produce/advise"]}
        self.feed([stale])
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)


class TestLatencyMarks(GuardCase):
    """S6: per-decision timing without anyone remembering to mark."""

    def marks(self):
        return latency.read_marks(latency.path_for(self.store))

    def test_step_records_start_and_end_marks_naming_the_step(self):
        self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        ex = [m for m in self.marks() if m["phase"] == "execute"]
        self.assertEqual([m["edge"] for m in ex], ["start", "end"])
        self.assertIn("step 1a", ex[-1]["note"])
        self.assertIn("rc=0", ex[-1]["note"])
        self.assertEqual(latency.digest(latency.path_for(self.store))
                         ["phases"]["execute"]["count"], 1)

    def test_a_refused_step_is_marked_too(self):
        # The trigger surface only warns now, so the refusal comes from the
        # saturation gate: 4a is the passGate step and actions remain.
        self.start_app([self.before, view_from_game(self.game(), None)])
        rc, _ = self.run_cli("step", "4a")
        self.assertEqual(rc, execute.EXIT_ASK)
        ex = [m for m in self.marks() if m["phase"] == "execute"]
        self.assertEqual([m["edge"] for m in ex], ["start", "end"])
        self.assertIn("rc=40", ex[-1]["note"])

    def test_turn_is_one_timed_block_not_nested(self):
        self.start_app([self.before, self.landed])
        rc, out = self.run_cli("turn", "1a")
        self.assertEqual(rc, 0, out)
        ex = [m for m in self.marks() if m["phase"] == "execute"]
        self.assertEqual([m["edge"] for m in ex], ["start", "end"])
        self.assertIn("turn 1a", ex[-1]["note"])

    def test_pass_verb_is_marked(self):
        self.start_app([self.before, view_from_game(self.game(), None)])
        rc, out = self.run_cli("pass")
        self.assertEqual(rc, 0, out)
        ex = [m for m in self.marks() if m["phase"] == "execute"]
        self.assertEqual([m["edge"] for m in ex], ["start", "end"])
        self.assertIn("pass", ex[-1]["note"])


if __name__ == "__main__":
    unittest.main()
