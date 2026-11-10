"""THE VERIFICATION RULE (fix plan, post-practice-game): a gate or metric
verified only by unit fixtures is UNVERIFIED — it needs one test on the path
it actually guards. The shape metrics guard the API lane, and that is exactly
where they were dead: the unit suite was green while a whole 12-generation
game logged neither my research lines nor a single standings line.

So this test drives the REAL pipeline the way scripts/e2e_practice.py does —
newgame.py → setup.py → listen/execute as subprocesses against the local
practice app — and then asserts on the finished game folder that

  * `shape.cardsBought.mine` has an entry for the generation whose research
    went through `execute.py pick`, and
  * `shape.vpSlope` is not None after listener-owned turnovers.

It SKIPS (never fails) when the local app is not running: start it with
`python3 scripts/server.py`, probe it with `python3 scripts/server.py status`.
"""
import shutil
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_practice                              # noqa: E402
import newgame                                   # noqa: E402
import shape                                     # noqa: E402
from tmlib import Store                          # noqa: E402

URL = newgame.BASE


def _app_running(url: str = URL) -> bool:
    try:
        with urllib.request.urlopen(url + "/", timeout=3) as r:
            return r.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


@unittest.skipUnless(_app_running(),
                     f"local practice app not reachable at {URL} — start it "
                     f"with `python3 scripts/server.py`")
@unittest.skipIf((ROOT / "state").exists(),
                 "a game is active in this checkout (state/ exists) — the "
                 "e2e refuses to run beside it")
class TestShapeMetricsOnTheApiLane(unittest.TestCase):
    """One scripted 2-generation practice game, then the metrics."""

    game_dir: Path | None = None

    @classmethod
    def setUpClass(cls):
        runner = e2e_practice.Runner(ROOT, URL, gens=2, greedy=True,
                                     keep=True, out=lambda *a: None)
        cls.rc = runner.run()
        cls.summary = runner.summary
        d = (runner.summary.game_dir or "").split(" (")[0]
        cls.game_dir = Path(d) if d else None

    @classmethod
    def tearDownClass(cls):
        if cls.game_dir and cls.game_dir.exists():
            shutil.rmtree(cls.game_dir, ignore_errors=True)
        state = ROOT / "state"
        if state.is_symlink() or state.exists():
            state.unlink(missing_ok=True)

    def setUp(self):
        if not self.game_dir or not self.game_dir.exists():
            self.skipTest(f"the e2e run produced no game folder "
                          f"(errors: {self.summary.errors})")
        self.store = Store(ROOT, state_dir=str(self.game_dir))

    def test_the_run_itself_was_clean(self):
        self.assertEqual(self.summary.errors, [])
        self.assertEqual(self.summary.drift_incidents, [])
        self.assertEqual(self.summary.refusals, [])

    def test_my_research_through_execute_pick_is_logged(self):
        log = (self.game_dir / "log.md").read_text()
        self.assertIn("Research: dealt", log,
                      "execute.py pick wrote no research line — shape.py "
                      "parses my buys out of exactly this line")

    def test_shape_reports_my_cards_bought_for_that_generation(self):
        mine = shape.compute(self.store)["cardsBought"]["mine"]
        self.assertTrue(mine, "shape.cardsBought.mine is empty on the API "
                              "lane — the bug this test exists for")
        self.assertIn(2, mine, mine)             # gen-2 research = the pick

    def test_listener_owned_turnover_logs_standings(self):
        log = (self.game_dir / "log.md").read_text()
        self.assertIn("Standings (", log,
                      "no standings line — the listener calls Engine.produce "
                      "directly, so the engine must log it")

    def test_shape_reports_a_vp_slope(self):
        self.assertIsNotNone(shape.compute(self.store)["vpSlope"])


if __name__ == "__main__":
    unittest.main()
