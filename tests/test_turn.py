"""13b: scripts/turn.py — composite table verb: done + note + tracker numbers
+ plan render + NEXT line, all in one process (kill mechanical round trips)."""
import subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP
import planlib

THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"
import turn


class TurnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        eng = Engine(self.store)
        eng.res("Zed", "mc", +40)
        eng.res("Zed", "plants", +2)
        eng.res("Zed", "heat", +3)
        eng.hand_add(["Comet"])
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]},
            {"id": "1b", "summary": "SP asteroid (14)", "volatility": "safe",
             "events": [{"method": "standard", "args": ["Zed", "asteroid"]}]},
        ], threats=THREATS, exit_=EXIT)

    def tearDown(self):
        self.tmp.cleanup()

    def log_text(self):
        return (Path(self.tmp.name) / "state" / "log.md").read_text()


class TestTurnDone(TurnTest):
    def test_done_applies_events_and_prints_tracker_numbers(self):
        out = turn.run(self.store, ["1a"])
        self.assertIn("Marked done: 1a", out)
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"])
        g = self.store.load_game()
        self.assertNotIn("Comet", g["me"]["hand"])   # events really applied
        # tracker line carries the REAL post-apply numbers from game.json
        self.assertIn(f"G{g['generation']}", out)
        r = g["me"]["resources"]
        for token in (f"{r['mc']} MC", f"{g['me']['tr']} TR",
                      f"{r['plants']} plants", f"{r['heat']} heat"):
            self.assertIn(token, out)

    def test_output_ends_with_next_open_step(self):
        out = turn.run(self.store, ["1a"])
        self.assertIn("▶️ NEXT 1b", out)             # planlib.render included
        self.assertEqual(out.strip().splitlines()[-1], "NEXT: 1b")

    def test_next_none_when_plan_complete(self):
        out = turn.run(self.store, ["1a", "1b"])
        self.assertIn("Marked done: 1a, 1b", out)
        self.assertEqual(out.strip().splitlines()[-1], "NEXT: none")

    def test_note_is_logged_and_echoed(self):
        out = turn.run(self.store, ["1a"], note="Ana played Birds")
        self.assertIn("Ana played Birds", self.log_text())
        self.assertIn("Ana played Birds", out)

    def test_no_note_logs_nothing_extra(self):
        turn.run(self.store, ["1a"])
        self.assertNotIn("Noted", self.log_text())

    def test_failure_names_label_earlier_labels_stay_committed(self):
        with self.assertRaises(EventError) as ctx:
            turn.run(self.store, ["1a", "9z"])
        self.assertIn("9z", str(ctx.exception))
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_no_apply_ticks_box_without_events(self):
        turn.run(self.store, ["1a"], apply_events=False)
        self.assertIn("Comet", self.store.load_game()["me"]["hand"])
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])


class TestTurnPatchFailed(TurnTest):
    """P8 #10: a failed patch leaves `patchFailed` in plan.json — `go` and
    `show` must say so loudly (execute.py refuses to run on it)."""

    def go(self):
        with tempfile.TemporaryDirectory() as empty:      # no listen/execute
            return turn.go(self.store, scripts_dir=empty)

    def test_go_warns_and_breaks_the_chain_on_patch_failed(self):
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"remove": ["9z"]}, live=True)
        out, rc = self.go()
        self.assertIn("⚠ PATCH FAILED", out)
        self.assertIn("9z", out)
        self.assertEqual(rc, 1)                  # `go && execute.py` stops

    def test_go_is_quiet_on_a_healthy_plan(self):
        out, rc = self.go()
        self.assertNotIn("PATCH FAILED", out)
        self.assertEqual(rc, 0)


class TestTurnCLI(TurnTest):
    def _cli(self, *args):
        script = Path(__file__).resolve().parent.parent / "scripts" / "turn.py"
        return subprocess.run([sys.executable, str(script), *args],
                              cwd=self.tmp.name, capture_output=True, text=True)

    def test_cli_done_with_note_one_process(self):
        r = self._cli("done", "1a", "--note", "Felix funded Banker")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "NEXT: 1b")
        self.assertIn("Felix funded Banker", self.log_text())

    def test_cli_state_flag_targets_that_folder(self):
        # seats run turn.py against their own folder from any cwd
        script = Path(__file__).resolve().parent.parent / "scripts" / "turn.py"
        with tempfile.TemporaryDirectory() as elsewhere:
            r = subprocess.run([sys.executable, str(script), "--state",
                                str(self.store.state_dir), "done", "1a"],
                               cwd=elsewhere, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "NEXT: 1b")

    def test_cli_error_is_nonzero_and_names_label(self):
        r = self._cli("done", "9z")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("9z", r.stderr)


class TestTurnCueGate(TurnTest):
    """turn.py done passes --confirm through; one --confirm covers every
    cue-gated label in the batch."""

    def setUp(self):
        super().setUp()
        Engine(self.store).tr("Zed", +15)      # TR 35: Terraformer-eligible
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]},
            {"id": "1b", "summary": "Claim Terraformer", "volatility": "recheck",
             "cue": "your marker sits on Terraformer",
             "events": [{"method": "milestone", "args": ["Zed", "Terraformer"]}]},
            {"id": "2a", "summary": "ocean on 04", "volatility": "recheck",
             "cue": "blue ocean tile on 04",
             "events": [{"method": "place", "args": ["Zed", "ocean", "04"]}]},
        ], threats=THREATS, exit_=EXIT)

    def test_mixed_labels_refused_without_confirm_plain_stays_committed(self):
        with self.assertRaises(EventError) as ctx:
            turn.run(self.store, ["1a", "1b"])
        self.assertIn("your marker sits on Terraformer", str(ctx.exception))
        steps = planlib.load_plan(self.store)["steps"]
        self.assertTrue(steps[0]["done"])            # 1a committed
        self.assertFalse(steps[1]["done"])

    def test_one_confirm_covers_all_gated_labels(self):
        out = turn.run(self.store, ["1a", "1b", "2a"], confirm="saw both")
        self.assertIn("Marked done: 1a, 1b, 2a", out)
        g = self.store.load_game()
        self.assertEqual(g["milestonesClaimed"], {"Terraformer": "Zed"})
        self.assertIn("04", g["board"])
        self.assertEqual(out.strip().splitlines()[-1], "NEXT: none")

    def test_render_in_output_shows_cue_for_open_gated_steps(self):
        out = turn.run(self.store, ["1a"])
        self.assertIn("cue: your marker sits on Terraformer", out)

    def _cli(self, *args):
        script = Path(__file__).resolve().parent.parent / "scripts" / "turn.py"
        return subprocess.run([sys.executable, str(script), *args],
                              cwd=self.tmp.name, capture_output=True, text=True)

    def test_cli_confirm_flag_passes_through(self):
        r = self._cli("done", "1a", "1b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--confirm", r.stderr)
        r = self._cli("done", "1b", "--confirm", "ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "NEXT: 2a")

    def test_help_mentions_confirm(self):
        r = self._cli("done", "--help")
        self.assertIn("--confirm", r.stdout)


if __name__ == "__main__":
    unittest.main()
