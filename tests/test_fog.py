"""Fog harness — the advisor pipeline must run with
degraded opponent info (physical-table reality): missing fields, stale
observations, unknown corp, sparse played-card logs. No crashes, briefs
and plans still generated, opponent seats still updatable."""
import json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from tmlib import Store, Engine
from test_new_game import SETUP
import advise
import planlib

THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"
import score


def foggy(g: dict) -> dict:
    g = json.loads(json.dumps(g))
    for opp in g["opponents"].values():
        opp["estimated"] = True
        opp["lastObservedGen"] = max(1, g["generation"] - 3)
        opp["corporation"] = None
        opp["playedCards"] = opp["playedCards"][:1]
        opp.pop("tagCounts", None)
    return g


class TestFog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        g = self.store.load_game()
        g["generation"] = 7
        g["globals"] = {"temperature": -12, "oxygen": 4, "oceans": 5}
        g["me"]["hand"] = ["Trees"]
        self.store.save_game(foggy(g))

    def tearDown(self):
        self.tmp.cleanup()

    def test_brief_generates_under_fog(self):
        brief = advise.build_brief(root=self.tmp.name,
                                   kb_dir=str(ROOT / "strategy"))
        self.assertIn("AVAILABLE ACTIONS", brief)
        self.assertIn("## RACES", brief)

    def test_menu_and_races_run_under_fog(self):
        import menu, races
        g = self.store.load_game()
        self.assertIsInstance(menu.available_actions(g, self.store.load_setup()), list)
        self.assertIn("Anna", races.render(races.race_table(g, self.store.load_setup())))

    def test_plan_simulation_runs_under_fog(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "x", "volatility": "safe", "events": []},
            {"id": "1b", "summary": "pass", "volatility": "recheck",
             "passGate": True, "events": []}], threats=THREATS, exit_=EXIT)
        self.assertIn("1a", planlib.render(self.store))

    def test_scoring_runs_under_fog(self):
        self.assertTrue(score.compute(self.store.load_game()))

    def test_opponent_events_still_apply_under_fog(self):
        before = self.store.load_game()["opponents"]["Anna"]["tr"]
        self.eng.tr("Anna", 2)
        self.assertEqual(
            self.store.load_game()["opponents"]["Anna"]["tr"], before + 2)
