"""P3 lane 2: the round-loop drivers in scripts/turn.py.

`turn.py round --opp I --of N [--last-before-me] [--boundary]` — after
each opponent event: triage annotate → pending triggers → judgment
schedule → the --sweep brief (or "SWEEP: no") → one judgment.status line.
`turn.py go` — own turn: listen once (if scripts/listen.py exists) →
promote → executor hint → menu summary → NEXT. Both tested with the
listener / executor scripts ABSENT (other lanes own them) and stubbed."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP
import advise
import applog_parser as P
import judgment
import latency
import planlib
import triage
import turn

PLAYERS = [p["name"] for p in SETUP["players"]]
THREATS = "Anna 1 step from Builder"
EXIT = "test exit: card VP; repeatable: greenery from plant production"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "turn.py"


def entry(line: int, raw: str) -> dict:
    return triage.new_entry(P.parse_line(raw, PLAYERS), line=line, gen=1,
                            raw=raw, ts="2026-01-01T00:00:00")


class RoundCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        eng = Engine(self.store)
        eng.res("Zed", "mc", +40)
        eng.hand_add(["Comet"])
        self.feed = triage.feed_path(self.store)
        triage.write_feed(self.feed, [entry(1, "Felix gained 2 megacredits"),
                                      entry(2, "Anna claimed Builder milestone")])
        self.empty = self.root / "no-scripts"
        self.empty.mkdir()
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT, "steps": [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]},
            {"id": "1b", "summary": "pass", "volatility": "recheck",
             "passGate": True, "events": []}]}, draft=True)

    def tearDown(self):
        self.tmp.cleanup()

    def log(self):
        return (self.root / "state" / "log.md").read_text()


class TestRound(RoundCase):
    def test_round_annotates_prints_pending_and_sweeps(self):
        out = turn.round_(self.store, opp=1, of=2)
        self.assertIn("PENDING TRIGGERS", out)
        self.assertIn("#2 Anna claimed", out)
        self.assertIn("# SWEEP", out)                    # level every → sweep
        self.assertIn("turn: opponent 1/2", out)
        self.assertNotIn("SWEEP: no", out)
        self.assertTrue(out.strip().splitlines()[-1].startswith("judgment: level="))
        entries = triage.read_feed(self.feed)
        self.assertTrue(entries[1]["trigger"])          # annotated in place
        self.assertTrue(planlib.sweep_flag_path(self.store).exists())

    def test_quiet_zone_says_no(self):
        out = turn.round_(self.store, opp=2, of=2, last_before_me=True)
        self.assertIn("SWEEP: no", out)
        self.assertNotIn("# SWEEP", out)
        self.assertIn("#2 Anna claimed", out)            # triggers still listed
        self.assertTrue(out.strip().splitlines()[-1].startswith("judgment:"))
        self.assertFalse(planlib.sweep_flag_path(self.store).exists())

    def test_level_and_boundary_are_respected(self):
        judgment.set_value(self.store, "level", "per-opponent")
        self.assertIn("SWEEP: no", turn.round_(self.store, opp=1, of=2))
        self.assertIn("# SWEEP", turn.round_(self.store, opp=1, of=2, boundary=True))
        judgment.set_value(self.store, "level", "triggers-only")
        self.assertIn("SWEEP: no", turn.round_(self.store, opp=1, of=2, boundary=True))

    def test_triage_phase_is_timed(self):
        turn.round_(self.store, opp=1, of=2)
        phases = [m["phase"] for m in latency.read_marks(latency.path_for(self.store))]
        self.assertIn("triage", phases)
        self.assertIn("sweep", phases)

    def test_no_pending_line_when_feed_is_quiet(self):
        triage.write_feed(self.feed, [entry(1, "Felix gained 2 megacredits")])
        out = turn.round_(self.store, opp=1, of=2, last_before_me=True)
        self.assertIn("no pending triggers", out)


class TestGo(RoundCase):
    def test_go_without_listener_or_executor(self):
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertEqual(rc, 0)
        self.assertIn("listen.py absent", text)
        self.assertIn("promoted", text)
        self.assertFalse(planlib.load_plan(self.store)["draft"])
        self.assertIn("execute.py absent", text)
        self.assertIn("available: ", text)
        self.assertEqual(text.strip().splitlines()[-1], "NEXT: 1a")

    def test_go_with_stubbed_listener_and_executor(self):
        (self.empty / "listen.py").write_text(
            "import sys; print('listened', sys.argv[1:])\n")
        (self.empty / "execute.py").write_text("print('exec')\n")
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertEqual(rc, 0)
        self.assertIn("'once'", text)          # listen.py --state <dir> once
        self.assertIn("'--state'", text)
        self.assertIn("execute.py --dry-run", text)
        self.assertIn("executor=assist", text)
        phases = [m["phase"] for m in latency.read_marks(latency.path_for(self.store))]
        self.assertIn("listen", phases)
        self.assertIn("promote", phases)

    def test_go_abandons_inflight_sweep_and_records_it(self):
        turn.round_(self.store, opp=1, of=2)             # sweep in flight
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertEqual(rc, 0)
        self.assertIn("abandoned", text)
        self.assertEqual(judgment.load(self.store)["abandonStreak"], 1)
        self.assertFalse(planlib.sweep_flag_path(self.store).exists())

    def test_clean_round_resets_streak(self):
        planlib.set_sweep_inflight(self.store, [2])
        turn.go(self.store, scripts_dir=self.empty)        # abandoned: streak 1
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT, "steps": [
            {"id": "1a", "summary": "pass", "volatility": "recheck",
             "passGate": True, "events": []}]}, draft=True)
        turn.go(self.store, scripts_dir=self.empty)        # clean round
        self.assertEqual(judgment.load(self.store).get("abandonStreak"), 0)

    def test_go_on_live_plan_notes_it(self):
        planlib.promote(self.store)
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertEqual(rc, 0)
        self.assertIn("already live", text)
        self.assertEqual(text.strip().splitlines()[-1], "NEXT: 1a")

    def test_go_reports_refused_promote_nonzero(self):
        Engine(self.store).res("Zed", "mc", -40)          # Comet unaffordable
        text, rc = turn.go(self.store, scripts_dir=self.empty)
        self.assertNotEqual(rc, 0)
        self.assertIn("PROMOTE REFUSED", text)
        self.assertIn("1a", text)
        self.assertIn("planlib.py patch", text)
        self.assertTrue(planlib.load_plan(self.store)["draft"])


class TestCLI(RoundCase):
    def cli(self, *args):
        env = {**os.environ, "PHOBOS_SCRIPTS_DIR": str(self.empty)}
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                              cwd=self.tmp.name, capture_output=True, text=True)

    def test_round_cli(self):
        r = self.cli("round", "--opp", "2", "--of", "2", "--last-before-me")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SWEEP: no", r.stdout)
        self.assertTrue(r.stdout.strip().splitlines()[-1].startswith("judgment:"))
        r = self.cli("round", "--opp", "1", "--of", "2", "--boundary")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("# SWEEP", r.stdout)

    def test_go_cli(self):
        r = self.cli("go")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "NEXT: 1a")
        self.assertIn("promoted", r.stdout)

    def test_help_lists_new_verbs(self):
        r = self.cli("--help")
        self.assertIn("round", r.stdout)
        self.assertIn("go", r.stdout)


if __name__ == "__main__":
    unittest.main()
