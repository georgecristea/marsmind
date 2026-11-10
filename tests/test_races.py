"""The RACE TABLE is generated, not remembered —
milestone + award metrics per player from tracked TR/tiles/tags/production,
alerts for anyone within 1 step of an unclaimed milestone, and planlib
refusing a generation plan without a `threats` block."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP
import planlib
import races


class RaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        g = self.store.load_game()
        me = g["me"]
        me["tr"] = 34
        me["tiles"] = {"cities": 1, "greeneries": 2, "special": 0}
        me["production"]["mc"] = 11
        me["resources"]["heat"] = 5
        me["resources"]["steel"] = 4
        me["hand"] = ["a", "b", "c"]
        me["playedCards"] = [{"name": n, "gen": 1} for n in
                             ("Research", "Mars University", "Steelworks")]
        anna = g["opponents"]["Anna"]
        anna["tr"] = 30
        anna["tagCounts"] = {"building": 7, "science": 1}
        anna["tiles"] = {"cities": 3, "greeneries": 0}
        anna["production"]["mc"] = 11
        anna["resources"]["heat"] = 12
        felix = g["opponents"]["Felix"]
        felix["tr"] = 25
        felix["tiles"] = {"cities": 0, "greeneries": 1}
        felix["production"]["mc"] = 4
        felix["resources"]["titanium"] = 7
        self.store.save_game(g)

    def tearDown(self):
        self.tmp.cleanup()

    def table(self):
        return races.race_table(self.store.load_game(), self.store.load_setup())

    def row(self, name):
        return next(p for p in self.table()["players"] if p["name"] == name)


class TestMetrics(RaceTest):
    def test_milestone_metrics_per_player(self):
        me = self.row("Zed")["milestones"]
        self.assertEqual(me, {"Terraformer": 34, "Mayor": 1, "Gardener": 2,
                              "Builder": 2, "Planner": 3})
        anna = self.row("Anna")["milestones"]
        self.assertEqual(anna["Builder"], 7)
        self.assertEqual(anna["Mayor"], 3)
        self.assertIsNone(anna["Planner"])            # hand size unknown

    def test_award_metrics_per_player(self):
        me = self.row("Zed")["awards"]
        self.assertEqual(me, {"Landlord": 3, "Banker": 11, "Scientist": 3,
                              "Thermalist": 5, "Miner": 4})
        felix = self.row("Felix")["awards"]
        self.assertEqual(felix["Miner"], 7)
        self.assertEqual(felix["Landlord"], 1)

    def test_award_leader_runner_up_and_gap(self):
        banker = self.table()["awards"]["Banker"]
        self.assertEqual(banker["leader"][1], 11)
        self.assertEqual(banker["runnerUp"][1], 11)
        self.assertEqual(banker["gap"], 0)
        self.assertIn("tie", banker["status"])
        miner = self.table()["awards"]["Miner"]
        self.assertEqual(miner["leader"], ("Felix", 7))
        self.assertEqual(miner["gap"], 3)


class TestAlerts(RaceTest):
    def test_within_one_step_of_unclaimed_milestone_is_alerted(self):
        alerts = "\n".join(self.table()["alerts"])
        self.assertIn("Zed", alerts); self.assertIn("Terraformer", alerts)
        self.assertIn("Anna", alerts); self.assertIn("Builder", alerts)
        self.assertIn("Mayor", alerts)                # Anna at 3 cities: NOW

    def test_claimed_milestone_no_longer_alerts(self):
        g = self.store.load_game()
        g["milestonesClaimed"] = {"Mayor": "Anna", "Builder": "Felix"}
        self.store.save_game(g)
        alerts = "\n".join(self.table()["alerts"])
        self.assertNotIn("Mayor", alerts)
        self.assertNotIn("Builder", alerts)
        self.assertIn("Terraformer", alerts)

    def test_three_claimed_silences_milestone_alerts(self):
        g = self.store.load_game()
        g["milestonesClaimed"] = {"Mayor": "Anna", "Builder": "Felix",
                                  "Gardener": "Anna"}
        self.store.save_game(g)
        self.assertFalse([a for a in self.table()["alerts"]
                          if "Terraformer" in a])

    def test_funded_award_tie_is_alerted(self):
        g = self.store.load_game(); g["awardsFunded"] = {"Banker": "Anna"}
        self.store.save_game(g)
        alerts = "\n".join(self.table()["alerts"])
        self.assertIn("Banker", alerts)

    def test_render_block(self):
        out = races.render(self.table())
        self.assertIn("RACES", out)
        self.assertIn("RACE ALERT", out)
        for name in ("Zed", "Anna", "Felix"):
            self.assertIn(name, out)
        self.assertIn("Builder", out)
        self.assertIn("Banker", out)

    def test_fog_missing_fields(self):
        g = self.store.load_game()
        for o in g["opponents"].values():
            o.pop("tagCounts", None); o.pop("tiles", None)
            o.pop("production", None)
        self.store.save_game(g)
        out = races.render(self.table())
        self.assertIn("Anna", out)


class TestBriefHasRaces(RaceTest):
    def test_brief_prints_races_and_alert(self):
        import advise
        b = advise.build_brief(self.tmp.name, brief=True,
                               kb_dir=Path(__file__).parent.parent / "strategy")
        self.assertIn("## RACES", b)
        self.assertIn("RACE ALERT", b)
        self.assertIn("Builder", b)


EXIT = "test exit: card VP; repeatable: greenery from plant production"


class TestPlanThreatsGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.steps = [{"id": "1a", "summary": "x", "volatility": "safe",
                       "events": []},
                      {"id": "1b", "summary": "pass", "volatility": "safe",
                       "passGate": True, "events": []}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_list_without_threats_refused_with_wrap_hint(self):
        with self.assertRaises(EventError) as ctx:
            planlib.set_plan(self.store, self.steps)
        msg = str(ctx.exception)
        self.assertIn("threats", msg)
        self.assertIn('"steps"', msg)

    def test_object_without_threats_refused(self):
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, {"steps": self.steps})
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, {"threats": "", "steps": self.steps})
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, {"threats": [], "steps": self.steps})

    def test_object_with_threats_accepted_and_shown(self):
        plan = planlib.set_plan(self.store, {
            "threats": ["Anna 7/8 Builder — claim first or deny",
                        "Banker tie 11/11 — fund only if lockable"],
            "exit": EXIT,
            "steps": self.steps})
        self.assertEqual(len(plan["threats"]), 2)
        out = planlib.render(self.store)
        self.assertIn("THREATS", out)
        self.assertIn("Anna 7/8 Builder", out)
        self.assertLess(out.index("Anna 7/8 Builder"), out.index("1a"))

    def test_list_with_threats_kwarg_accepted(self):
        planlib.set_plan(self.store, self.steps, threats="Anna Builder race",
                         exit_=EXIT)
        self.assertIn("Anna Builder race", planlib.render(self.store))

    def test_draft_may_omit_threats_but_promote_needs_them(self):
        planlib.set_plan(self.store, self.steps, draft=True)
        with self.assertRaises(EventError) as ctx:
            planlib.promote(self.store, exit_=EXIT)
        self.assertIn("threats", str(ctx.exception))
        planlib.promote(self.store, threats="Anna Builder race", exit_=EXIT)
        self.assertIn("Anna Builder race", planlib.render(self.store))

    def test_cli_set_accepts_object_shape(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "planlib.py"
        r = subprocess.run([sys.executable, str(script), "set"],
                           input=json.dumps({"threats": "Anna Builder 7/8",
                                             "exit": EXIT,
                                             "steps": self.steps}),
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Anna Builder 7/8", r.stdout)
        r = subprocess.run([sys.executable, str(script), "set"],
                           input=json.dumps(self.steps),
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("threats", r.stderr)


if __name__ == "__main__":
    unittest.main()
