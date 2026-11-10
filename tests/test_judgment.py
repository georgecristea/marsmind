"""scripts/judgment.py — the "judgment" block of setup.json.

Schedule levels: every (sweep on every event) → per-opponent (once per
opponent turn) → after-k (only after the k-th opponent) → triggers-only
(never on schedule). The quiet zone (the last opponent before me) never
sweeps. Two consecutive rounds with a quiet-zone abandonment degrade the
level one notch; a clean round resets the streak.
"""
import copy, json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import GameManager, Store
from test_new_game import SETUP
import judgment
import latency

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


class JudgmentCase(unittest.TestCase):
    MODE = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        setup = copy.deepcopy(SETUP)
        if self.MODE:
            setup["gameMode"] = self.MODE
        GameManager(self.root, today="2031-05-01").start(setup)
        self.store = Store(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def setup_json(self):
        return json.loads((self.root / "state" / "setup.json").read_text())

    def log(self):
        return (self.root / "state" / "log.md").read_text()


class TestDefaults(JudgmentCase):
    def test_defaults_for_a_physical_three_player_game(self):
        d = judgment.defaults(self.store.load_setup())
        self.assertEqual(d, {"level": "every", "k": 1, "quiet_zone": True,
                             "executor": "assist", "verbosity": "terse"})

    def test_k_is_opponents_minus_one_with_a_floor_of_one(self):
        five = copy.deepcopy(SETUP)
        five["players"] += [
            {"name": "Bo", "color": "yellow", "isMe": False, "aliases": []},
            {"name": "Cy", "color": "black", "isMe": False, "aliases": []}]
        five["playerCount"] = 5
        self.assertEqual(judgment.defaults(five)["k"], 3)
        two = copy.deepcopy(SETUP)
        two["players"] = two["players"][:2]
        two["playerCount"] = 2
        self.assertEqual(judgment.defaults(two)["k"], 1)

    def test_executor_auto_in_app_practice_assist_otherwise(self):
        for mode, want in (("physical", "assist"), ("app-online", "assist"),
                           ("app-practice", "auto")):
            s = dict(copy.deepcopy(SETUP), gameMode=mode)
            self.assertEqual(judgment.defaults(s)["executor"], want, mode)

    def test_load_falls_back_to_defaults_for_old_games(self):
        # the game was created without a judgment block (legacy setup)
        self.assertNotIn("judgment", self.setup_json())
        j = judgment.load(self.store)
        self.assertEqual(j["level"], "every")
        self.assertEqual(j["k"], 1)
        self.assertTrue(j["quiet_zone"])
        self.assertEqual(j["executor"], "assist")

    def test_load_merges_a_partial_block_over_defaults(self):
        judgment.set_value(self.store, "level", "after-k")
        j = judgment.load(self.store)
        self.assertEqual(j["level"], "after-k")
        self.assertEqual(j["k"], 1)
        self.assertEqual(j["executor"], "assist")


class TestSetters(JudgmentCase):
    def test_set_level_persists_to_setup_json(self):
        judgment.set_value(self.store, "level", "per-opponent")
        self.assertEqual(self.setup_json()["judgment"]["level"], "per-opponent")

    def test_set_k_persists_an_int(self):
        judgment.set_value(self.store, "k", "2")
        self.assertEqual(self.setup_json()["judgment"]["k"], 2)

    def test_set_executor_persists(self):
        judgment.set_value(self.store, "executor", "manual")
        self.assertEqual(self.setup_json()["judgment"]["executor"], "manual")

    def test_invalid_values_refused(self):
        with self.assertRaises(ValueError):
            judgment.set_value(self.store, "level", "sometimes")
        with self.assertRaises(ValueError):
            judgment.set_value(self.store, "executor", "robot")
        with self.assertRaises(ValueError):
            judgment.set_value(self.store, "k", "0")
        with self.assertRaises(ValueError):
            judgment.set_value(self.store, "k", "two")
        with self.assertRaises(ValueError):
            judgment.set_value(self.store, "colour", "red")

    def test_set_logs_the_change(self):
        judgment.set_value(self.store, "level", "after-k")
        self.assertIn("judgment level: every → after-k", self.log())


class TestShouldSweep(JudgmentCase):
    """Schedule rules. opp_index is 1-based within the round of opponent
    turns; opps_total = number of opponents in the round."""

    def sweeps(self, level, idx, total, last=False, boundary=True):
        judgment.set_value(self.store, "level", level)
        return judgment.should_sweep(self.store, idx, total, last,
                                     boundary=boundary)

    def test_every_sweeps_on_every_event(self):
        self.assertTrue(self.sweeps("every", 1, 2))
        self.assertTrue(self.sweeps("every", 1, 2, boundary=False))

    def test_per_opponent_sweeps_only_at_a_turn_boundary(self):
        self.assertTrue(self.sweeps("per-opponent", 1, 3))
        self.assertTrue(self.sweeps("per-opponent", 2, 3))
        self.assertFalse(self.sweeps("per-opponent", 1, 3, boundary=False))

    def test_after_k_sweeps_only_for_the_kth_opponent(self):
        judgment.set_value(self.store, "k", "2")
        self.assertFalse(self.sweeps("after-k", 1, 4))
        self.assertTrue(self.sweeps("after-k", 2, 4))
        self.assertFalse(self.sweeps("after-k", 3, 4))

    def test_triggers_only_never_sweeps_on_schedule(self):
        self.assertFalse(self.sweeps("triggers-only", 1, 3))
        self.assertFalse(self.sweeps("triggers-only", 2, 3))

    def test_quiet_zone_wins_over_every_level(self):
        judgment.set_value(self.store, "k", "2")
        for level in judgment.LEVELS:
            self.assertFalse(self.sweeps(level, 2, 2, last=True), level)

    def test_quiet_zone_can_be_switched_off(self):
        judgment.set_value(self.store, "quiet_zone", "false")
        self.assertTrue(self.sweeps("every", 2, 2, last=True))


class TestDegrade(JudgmentCase):
    def test_degrade_walks_the_ladder_one_notch_per_call(self):
        self.assertEqual(judgment.degrade(self.store, "test"), "per-opponent")
        self.assertEqual(judgment.degrade(self.store, "test"), "after-k")
        self.assertEqual(judgment.degrade(self.store, "test"), "triggers-only")
        self.assertEqual(judgment.degrade(self.store, "test"), "triggers-only")
        self.assertEqual(self.setup_json()["judgment"]["level"], "triggers-only")

    def test_degrade_logs_reason(self):
        judgment.degrade(self.store, "sweeps too slow")
        log = self.log()
        self.assertIn("judgment degraded every → per-opponent", log)
        self.assertIn("sweeps too slow", log)

    def test_degrade_at_floor_logs_nothing_new(self):
        judgment.set_value(self.store, "level", "triggers-only")
        before = self.log()
        judgment.degrade(self.store, "again")
        self.assertEqual(self.log(), before)

    def test_two_consecutive_abandoned_rounds_degrade_once(self):
        r1 = judgment.record_abandonment(self.store)
        self.assertEqual(r1["streak"], 1)
        self.assertIsNone(r1["degraded"])
        self.assertEqual(judgment.load(self.store)["level"], "every")
        r2 = judgment.record_abandonment(self.store)
        self.assertEqual(r2["degraded"], "per-opponent")
        self.assertEqual(judgment.load(self.store)["level"], "per-opponent")
        self.assertIn("abandon", self.log().lower())
        # streak reset after the degrade: a third abandonment starts over
        r3 = judgment.record_abandonment(self.store)
        self.assertEqual(r3["streak"], 1)
        self.assertIsNone(r3["degraded"])
        self.assertEqual(judgment.load(self.store)["level"], "per-opponent")

    def test_clean_round_resets_the_streak(self):
        judgment.record_abandonment(self.store)
        judgment.record_clean_round(self.store)
        r = judgment.record_abandonment(self.store)
        self.assertEqual(r["streak"], 1)
        self.assertIsNone(r["degraded"])
        self.assertEqual(judgment.load(self.store)["level"], "every")

    def test_auto_degrade_is_a_noop_below_the_threshold(self):
        self.assertIsNone(judgment.auto_degrade(self.store))
        judgment.record_abandonment(self.store, auto=False)
        self.assertIsNone(judgment.auto_degrade(self.store))
        judgment.record_abandonment(self.store, auto=False)
        self.assertEqual(judgment.auto_degrade(self.store), "per-opponent")
        self.assertEqual(judgment.load(self.store)["abandonStreak"], 0)


class TestStatus(JudgmentCase):
    def test_status_line_carries_params_and_sweep_latency(self):
        with latency.timed("sweep", store=self.store):
            pass
        latency.mark("sweep", "start", store=self.store)
        latency.mark("sweep", "end", note="abandoned", store=self.store)
        line = judgment.status(self.store)
        self.assertEqual(line.count("\n"), 0)
        self.assertIn("level=every", line)
        self.assertIn("k=1", line)
        self.assertIn("executor=assist", line)
        self.assertIn("sweep p50=", line)
        self.assertIn("p95=", line)
        self.assertIn("abandonments=1", line)

    def test_status_without_marks(self):
        line = judgment.status(self.store)
        self.assertIn("sweep p50=- p95=-", line)
        self.assertIn("abandonments=0", line)


class TestCLI(JudgmentCase):
    def run_j(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "judgment.py"), *args],
            cwd=self.root, capture_output=True, text=True)

    def test_show_prints_the_block(self):
        r = self.run_j("show")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["level"], "every")

    def test_set_and_degrade_and_status(self):
        r = self.run_j("set", "level", "per-opponent")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.setup_json()["judgment"]["level"], "per-opponent")
        r = self.run_j("set", "k", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_j("set", "executor", "auto")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_j("degrade", "--reason", "table is fast tonight")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("after-k", r.stdout)
        self.assertIn("table is fast tonight", self.log())
        r = self.run_j("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("level=after-k", r.stdout)
        self.assertIn("k=3", r.stdout)
        self.assertIn("executor=auto", r.stdout)

    def test_set_invalid_value_fails(self):
        r = self.run_j("set", "level", "always")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ERROR", r.stderr)


class TestSetupWritesDefaults(unittest.TestCase):
    """setup.py writes the judgment defaults at game creation — no new
    prompts; the legacy stdin driver must keep working."""

    ANSWERS = "\n".join(["Zed", "red", "Anna=green, Felix=blue",
                         "", "", "", "", "Anna", ""]) + "\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_setup(self, stdin):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "setup.py")],
            cwd=self.cwd, input=stdin, capture_output=True, text=True)

    def read_setup(self):
        return json.loads((Path(self.cwd) / "state" / "setup.json").read_text())

    def test_physical_game_gets_assist_defaults(self):
        r = self.run_setup(self.ANSWERS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_setup()["judgment"],
                         {"level": "every", "k": 1, "quiet_zone": True,
                          "executor": "assist", "verbosity": "terse"})

    def test_app_practice_game_gets_auto_executor(self):
        r = self.run_setup(self.ANSWERS + "app-practice\nhttp://localhost:8080\npabc\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_setup()["judgment"]["executor"], "auto")


if __name__ == "__main__":
    unittest.main()
