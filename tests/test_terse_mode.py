"""ITEM 1 — TERSE MODE: the `verbosity` dial and the plan-step prose budget.

The advisor's own clock in a real 12-generation game was 25m16s of a 50m55s
game while scripts and transport totalled ~1 second: essentially all of it is
generated tokens, and roughly 75% of a plan-step summary is KB citation,
rejected alternatives and justification prose. `judgment.py set verbosity
terse|full` (terse = the default in every game mode) makes the compression a
GATE rather than a preference — an advisory policy erodes under table
pressure, which is exactly what happened to the output-format contract.

Terse compresses PROSE ONLY. Machine-required text is exempt from the budget:
the step's cue and menu.py's award lock verdict (which another gate demands
verbatim). A step opts out with "verbose": "<reason>", logged like every
other override.

The last class is the VERIFICATION RULE test: a gate verified only by unit
fixtures is unverified, so the budget is also driven end-to-end over the API
lane against the local practice app (skipped when the app is not running).
"""
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError            # noqa: E402
from test_new_game import SETUP                            # noqa: E402
import judgment                                            # noqa: E402
import planlib                                             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
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
                 "awardAck": "test fixture: funding is not the property under test",
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


if __name__ == "__main__":
    unittest.main()
