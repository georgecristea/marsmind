"""SLOW lane: terse-mode end-to-end against the live practice app."""

import copy
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tmlib import Store, Engine, EventError            # noqa: E402
from test_new_game import SETUP                            # noqa: E402
import judgment                                            # noqa: E402
import planlib                                             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / "scripts"
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


# ── the dial ─────────────────────────────────────────────────────────


class TestVerbosityDial(Fixture):
    def test_default_is_terse_in_every_game_mode(self):
        for mode in ("physical", "app-online", "app-practice"):
            s = copy.deepcopy(SETUP)
            s["gameMode"] = mode
            self.assertEqual(judgment.defaults(s)["verbosity"], "terse", mode)

    def test_setup_without_the_key_reads_terse_without_migration(self):
        setup = self.store.load_setup()
        setup["judgment"] = {"level": "every", "k": 1, "quiet_zone": True,
                             "executor": "assist"}          # pre-dial setup
        Store._write_json(self.store.setup_path, setup)
        self.assertEqual(judgment.load(self.store)["verbosity"], "terse")

    def test_round_trips_and_persists(self):
        judgment.set_value(self.store, "verbosity", "full")
        self.assertEqual(judgment.load(self.store)["verbosity"], "full")
        setup = json.loads((self.root / "state" / "setup.json").read_text())
        self.assertEqual(setup["judgment"]["verbosity"], "full")
        judgment.set_value(self.store, "verbosity", "terse")
        self.assertEqual(judgment.load(self.store)["verbosity"], "terse")

    def test_a_bad_value_is_refused(self):
        with self.assertRaises(ValueError):
            judgment.set_value(self.store, "verbosity", "chatty")

    def test_a_change_is_logged(self):
        judgment.set_value(self.store, "verbosity", "full")
        self.assertIn("judgment verbosity: terse → full", self.log())

    def test_status_and_show_print_it(self):
        self.assertIn("verbosity=terse", judgment.status(self.store))
        r = subprocess.run([sys.executable, str(SCRIPTS / "judgment.py"), "show"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["verbosity"], "terse")

    def test_cli_sets_it_mid_game(self):
        r = subprocess.run([sys.executable, str(SCRIPTS / "judgment.py"),
                            "set", "verbosity", "full"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verbosity = full", r.stdout)
        r = subprocess.run([sys.executable, str(SCRIPTS / "judgment.py"), "status"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertIn("verbosity=full", r.stdout)


# ── the budget ───────────────────────────────────────────────────────


def _steps(summary: str, **extra):
    return [{"id": "1a", "summary": summary, "volatility": "safe",
             "events": [], **extra},
            {"id": "1b", "summary": "pass", "volatility": "safe",
             "events": [], "passGate": True}]


class TestSummaryBudget(Fixture):
    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)

    def set_plan(self, summary, **extra):
        return planlib.set_plan(self.store, _steps(summary, **extra),
                                threats=THREATS, exit_=EXIT)

    def at_budget(self) -> str:
        return "x" * planlib.SUMMARY_BUDGET

    def over_budget(self) -> str:
        return "y" * (planlib.SUMMARY_BUDGET + 1)

    def test_at_budget_summary_is_accepted_in_terse(self):
        self.set_plan(self.at_budget())

    def test_over_budget_summary_is_refused_naming_the_step_and_length(self):
        with self.assertRaises(EventError) as cm:
            self.set_plan(self.over_budget())
        msg = str(cm.exception)
        self.assertIn("1a", msg)
        self.assertIn(str(planlib.SUMMARY_BUDGET + 1), msg)
        self.assertIn(str(planlib.SUMMARY_BUDGET), msg)

    def test_the_refusal_is_logged_and_writes_nothing(self):
        with self.assertRaises(EventError):
            self.set_plan(self.over_budget())
        self.assertIn("GATE verbosity REFUSED", self.log())
        self.assertFalse((self.root / "state" / "plan.json").exists())

    def test_full_accepts_both(self):
        judgment.set_value(self.store, "verbosity", "full")
        self.set_plan(self.at_budget())
        self.set_plan(self.over_budget())

    def test_the_dial_flips_back_mid_game(self):
        judgment.set_value(self.store, "verbosity", "full")
        self.set_plan(self.over_budget())
        judgment.set_value(self.store, "verbosity", "terse")
        with self.assertRaises(EventError):
            self.set_plan(self.over_budget())

    def test_patch_enforces_the_same_budget(self):
        self.set_plan("short")
        with self.assertRaises(EventError) as cm:
            planlib.patch(self.store, {"replace": {"1a": {
                "id": "1a", "summary": self.over_budget(),
                "volatility": "safe", "events": []}}}, live=True)
        self.assertIn("1a", str(cm.exception))

    def test_done_steps_are_not_measured(self):
        # a replan carries executed steps written under an earlier dial
        planlib.set_plan(self.store,
                         [{"id": "1a", "summary": self.over_budget(),
                           "volatility": "safe", "events": [], "done": True},
                          {"id": "1b", "summary": "pass", "volatility": "safe",
                           "events": [], "passGate": True}],
                         threats=THREATS, exit_=EXIT)


class TestBudgetCarveOuts(Fixture):
    """Machine-required text never counts, and a step may opt out."""

    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)

    def test_explicit_verbose_escape_is_accepted_and_logged(self):
        planlib.set_plan(self.store,
                         _steps("z" * (planlib.SUMMARY_BUDGET + 60),
                                verbose="endgame branch: the player reads along"),
                         threats=THREATS, exit_=EXIT)
        log = self.log()
        self.assertIn("verbosity budget OVERRIDDEN", log)
        self.assertIn("endgame branch", log)

    def test_a_long_cue_does_not_count_against_the_budget(self):
        cue = "c" * (planlib.SUMMARY_BUDGET - 20)
        planlib.set_plan(
            self.store,
            [{"id": "1a", "summary": f"place greenery on F2. {cue}",
              "cue": cue, "cueGated": True, "volatility": "recheck",
              "events": []},
             {"id": "1b", "summary": "pass", "volatility": "safe",
              "events": [], "passGate": True}],
            threats=THREATS, exit_=EXIT)

    def _award_steps(self, summary):
        return [{"id": "1a", "summary": summary, "volatility": "recheck",
                 "events": [{"method": "award", "args": ["Zed", "Banker"]}]},
                {"id": "1b", "summary": "pass", "volatility": "safe",
                 "events": [], "passGate": True}]

    def _verdict(self) -> str:
        import menu
        return menu.award_lock(self.store.load_game(), "Banker",
                               self.store.load_setup())["why"]

    def test_award_step_long_only_because_of_the_lock_verdict_is_accepted(self):
        why = self._verdict()
        summary = ("Fund Banker 8 → 💰40 · menu.py: " + why + " "
                   + "p" * (planlib.SUMMARY_BUDGET - 40))
        self.assertGreater(len(summary), planlib.SUMMARY_BUDGET)
        planlib.set_plan(self.store, self._award_steps(summary),
                         threats=THREATS, exit_=EXIT)

    def test_the_same_length_of_prose_without_the_verdict_is_refused(self):
        why = self._verdict()
        summary = ("Fund Banker 8 — not lockable. " + "q" * len(why) + " "
                   + "p" * (planlib.SUMMARY_BUDGET - 40))
        with self.assertRaises(EventError) as cm:
            planlib.set_plan(self.store, self._award_steps(summary),
                             threats=THREATS, exit_=EXIT)
        self.assertIn("1a", str(cm.exception))


# ── the verification rule: the same gate, on the API lane ────────────


def _app_up(url: str) -> bool:
    u = urlparse(url)
    try:
        with socket.create_connection((u.hostname or "localhost",
                                       u.port or 80), timeout=1.5):
            return True
    except OSError:
        return False


class TestTerseEndToEnd(unittest.TestCase):
    """A scripted practice game (no model) on the local app, driven exactly
    like scripts/e2e_practice.py: the budget gate must never refuse a step
    the harness writes, and every summary in plan.json must be within it."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPTS))
        import e2e_practice as E
        import newgame
        cls.E, cls.url = E, newgame.BASE.rstrip("/")
        if not _app_up(cls.url):
            raise unittest.SkipTest(
                f"practice app not reachable at {cls.url} — start it with "
                f"`python3 scripts/server.py` (`server.py status` probes it)")
        if (ROOT / "state").exists():
            raise unittest.SkipTest(
                "a game is active (state/ exists in the repo root) — the "
                "scripted e2e refuses to run beside it")

    def test_scripted_practice_game_stays_within_the_terse_budget(self):
        E = self.E
        runner = E.Runner(ROOT, self.url, gens=2, greedy=True, keep=True,
                          out=lambda *_a, **_k: None)
        try:
            code = runner.run()
            game_dir = runner.game_dir
            self.assertIsNotNone(game_dir, "the e2e never created a game")
            self.assertEqual(
                judgment.defaults(json.loads(
                    (game_dir / "setup.json").read_text()))["verbosity"],
                "terse")
            # every plan written during the run passed the gate
            self.assertNotIn("GATE verbosity REFUSED",
                             (game_dir / "log.md").read_text())
            plan = json.loads((game_dir / "plan.json").read_text())
            summaries = [str(s.get("summary") or "") for s in plan["steps"]]
            self.assertTrue(summaries, "the game wrote no plan steps")
            for s in summaries:
                self.assertLessEqual(len(s), planlib.SUMMARY_BUDGET, s)
            # the run reached an end condition and no refusal came from
            # this gate. A scripted-harness ASK (a card follow-up the
            # greedy bot cannot answer) is a KNOWN e2e limitation and a
            # random deal away — it must never be read as a budget failure,
            # so it is asserted against by NAME, not by exit code.
            self.assertEqual(runner.summary.errors, [],
                             E.format_summary(runner.summary))
            self.assertTrue(runner.summary.ended, "the run never ended")
            self.assertGreaterEqual(runner.summary.generations, 1)
            for r in runner.summary.refusals:
                self.assertNotIn("verbosity", r.lower())
                self.assertNotIn("terse budget", r.lower())
            self.assertIn(code, (0, 3))
        finally:
            if runner.game_dir and runner.game_dir.exists():
                shutil.rmtree(runner.game_dir, ignore_errors=True)
            link = ROOT / "state"
            if link.is_symlink():
                link.unlink()


if __name__ == "__main__":
    unittest.main()
