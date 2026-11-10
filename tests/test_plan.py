"""Turn-ID plan store: labeled steps (1a, 1b, 2a...), done-tracking, volatility."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP
import planlib

THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)

    def tearDown(self):
        self.tmp.cleanup()

    def steps(self):
        return [
            {"id": "1a", "summary": "Play Business Network (1 MC)", "volatility": "safe"},
            {"id": "1b", "summary": "Play Immigration Shuttles (28 MC)", "volatility": "safe"},
            {"id": "2a", "summary": "Play Imported Hydrogen; ocean on hex 13", "volatility": "recheck"},
            {"id": "2b", "summary": "Business Network action", "volatility": "safe"},
        ]

    def test_set_stores_plan_with_generation(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        p = json.loads((Path(self.tmp.name) / "state" / "plan.json").read_text())
        self.assertEqual(p["generation"], 1)
        self.assertEqual([s["id"] for s in p["steps"]], ["1a", "1b", "2a", "2b"])
        self.assertFalse(p["steps"][0]["done"])

    def test_done_marks_and_logs(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"])
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("1a", log)

    def test_done_whole_turn(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1")        # both 1a and 1b
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"] and p["steps"][1]["done"])
        self.assertFalse(p["steps"][2]["done"])

    def test_done_unknown_id_rejected(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            planlib.mark_done(self.store, "9z")

    def test_done_twice_rejected(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        with self.assertRaises(EventError):
            planlib.mark_done(self.store, "1a")

    def test_show_renders_status_and_volatility(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        out = planlib.render(self.store)
        self.assertIn("✅ 1a", out)
        self.assertIn("⬜ 2a", out)
        self.assertIn("🔁", out)                  # recheck marker
        self.assertIn("🔒", out)                  # safe marker

    def test_new_plan_for_new_generation_replaces(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        g = self.store.load_game(); g["generation"] = 2; self.store.save_game(g)
        planlib.set_plan(self.store, [{"id": "1a", "summary": "x", "volatility": "safe"}], threats=THREATS, exit_=EXIT)
        p = planlib.load_plan(self.store)
        self.assertEqual(p["generation"], 2)
        self.assertEqual(len(p["steps"]), 1)


if __name__ == "__main__":
    unittest.main()


class TestNextMarker(TestPlan):
    def test_render_marks_first_open_step_as_next(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1")
        out = planlib.render(self.store)
        self.assertIn("▶️ NEXT 2a", out)
        self.assertEqual(out.count("▶️ NEXT"), 1)

    def test_all_done_says_generation_complete(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        for lbl in ("1", "2"):
            planlib.mark_done(self.store, lbl)
        out = planlib.render(self.store)
        self.assertIn("complete", out.lower())

    def test_next_returns_step_or_none(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        self.assertEqual(planlib.next_step(self.store)["id"], "1b")
        for lbl in ("1b", "2"):
            planlib.mark_done(self.store, lbl)
        self.assertIsNone(planlib.next_step(self.store))


class TestReopen(TestPlan):
    def test_reopen_marks_step_open_again_and_logs(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        planlib.reopen(self.store, "1a")
        p = planlib.load_plan(self.store)
        self.assertFalse(p["steps"][0]["done"])
        self.assertIn("Reopened", (Path(self.tmp.name) / "state" / "log.md").read_text())

    def test_reopen_open_step_rejected(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            planlib.reopen(self.store, "1a")


class TestPlanSimulation(TestPlan):
    def _rich(self):
        # Zed: 19 MC — exactly the practice-game bug setup
        from tmlib import Engine
        eng = Engine(self.store)
        eng.res("Zed", "mc", +19)
        eng.hand_add(["Comet"])
        return eng

    def test_unaffordable_step_rejected_at_plan_time(self):
        self._rich()
        steps = [{"id": "1a", "summary": "Play Comet (21)", "volatility": "safe",
                  "events": [{"method": "play",
                              "args": ["Zed", "Comet"], "kwargs": {"cost": 21}}]}]
        with self.assertRaises(EventError) as ctx:
            planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        self.assertIn("1a", str(ctx.exception))

    def test_valid_sequence_accepted_and_state_untouched(self):
        self._rich()
        steps = [{"id": "1a", "summary": "Play Comet (18 house discount)",
                  "volatility": "safe",
                  "events": [{"method": "play",
                              "args": ["Zed", "Comet"], "kwargs": {"cost": 18}}]}]
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)          # must not raise
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 19)   # sandbox only
        self.assertIn("Comet", g["me"]["hand"])

    def test_sequence_dependencies_simulated_in_order(self):
        self._rich()
        steps = [
            {"id": "1a", "summary": "Play Comet (18)", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]},
            {"id": "1b", "summary": "SP asteroid (14) — only 1 MC left: illegal",
             "volatility": "safe",
             "events": [{"method": "standard", "args": ["Zed", "asteroid"]}]},
        ]
        with self.assertRaises(EventError) as ctx:
            planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        self.assertIn("1b", str(ctx.exception))

    def test_steps_without_events_skip_simulation(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)   # legacy plain steps still fine


class TestMapMarker(TestPlan):
    def test_open_map_step_renders_attach_marker(self):
        steps = self.steps()
        steps[2]["mapHighlight"] = "32"           # 2a carries a placement
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        out = planlib.render(self.store)
        self.assertIn("ATTACH MAP", out)
        self.assertIn("--highlight 32", out)

    def test_done_map_step_has_no_marker(self):
        steps = self.steps()
        steps[0]["mapHighlight"] = "32"
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a")
        self.assertNotIn("ATTACH MAP", planlib.render(self.store))



class TestDoneAppliesEvents(TestPlan):
    def test_done_executes_attached_events(self):
        from tmlib import Engine
        eng = Engine(self.store)
        eng.res("Zed", "mc", +30)
        eng.hand_add(["Comet"])
        steps = [{"id": "1a", "summary": "Play Comet", "volatility": "safe",
                  "events": [{"method": "play", "args": ["Zed", "Comet"],
                              "kwargs": {"cost": 18}}]}]
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a", apply_events=True)
        g = self.store.load_game()
        self.assertNotIn("Comet", g["me"]["hand"])
        self.assertEqual(g["me"]["resources"]["mc"], 12)

    def test_done_no_apply_flag_skips_events(self):
        from tmlib import Engine
        eng = Engine(self.store)
        eng.res("Zed", "mc", +30)
        eng.hand_add(["Comet"])
        steps = [{"id": "1a", "summary": "Play Comet", "volatility": "safe",
                  "events": [{"method": "play", "args": ["Zed", "Comet"],
                              "kwargs": {"cost": 18}}]}]
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "1a", apply_events=False)
        self.assertIn("Comet", self.store.load_game()["me"]["hand"])


class TestPassGate(TestPlan):
    def _gate_plan(self):
        return [{"id": "2b", "summary": "Saturation → pass", "volatility": "safe",
                 "passGate": True, "events": []}]

    def test_pass_refused_while_conversion_available(self):
        from tmlib import Engine
        eng = Engine(self.store)
        eng.res("Zed", "heat", +8)
        planlib.set_plan(self.store, self._gate_plan(), threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done(self.store, "2b")
        self.assertIn("heat", str(ctx.exception).lower())

    def test_pass_allowed_when_nothing_available(self):
        planlib.set_plan(self.store, self._gate_plan(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "2b")     # 0 MC, no actions → legal

    def test_pass_force_overrides_with_reason(self):
        from tmlib import Engine
        Engine(self.store).res("Zed", "heat", +8)
        planlib.set_plan(self.store, self._gate_plan(), threats=THREATS, exit_=EXIT)
        planlib.mark_done(self.store, "2b", force="saving heat for Caretaker")
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("saving heat", log)


class TestActionCostAwareness(TestPlan):
    def test_costed_action_marked_unaffordable(self):
        from tmlib import Engine
        eng = Engine(self.store)
        eng.res("Zed", "mc", +30)
        eng.hand_add(["Underground Detonations"])
        eng.play("Zed", "Underground Detonations")   # 30-6=24... spend to 8:
        eng.res("Zed", "mc", -16)                    # 8 MC < action cost 10
        import menu
        names = [i["name"] for i in menu.available_actions(
            self.store.load_game(), self.store.load_setup())]
        self.assertNotIn("Underground Detonations", names)   # 8 MC < 10
        eng.res("Zed", "mc", +2)
        names = [i["name"] for i in menu.available_actions(
            self.store.load_game(), self.store.load_setup())]
        self.assertIn("Underground Detonations", names)


class TestHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)

    def tearDown(self):
        self.tmp.cleanup()
    """Plan hardening: format/map fields are structural,
    not advisor discipline."""

    def test_place_event_autofills_map_highlight(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "ocean", "volatility": "safe",
             "cue": "ocean tile on 04",
             "events": [{"method": "place",
                         "args": ["Zed", "ocean", "04"]}]}], threats=THREATS, exit_=EXIT)
        step = planlib.load_plan(self.store)["steps"][0]
        self.assertEqual(step["mapHighlight"], "04")

    def test_explicit_map_highlight_preserved(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "ocean", "volatility": "safe",
             "mapHighlight": "34", "cue": "ocean tile on 04",
             "events": [{"method": "place",
                         "args": ["Zed", "ocean", "04"]}]}], threats=THREATS, exit_=EXIT)
        step = planlib.load_plan(self.store)["steps"][0]
        self.assertEqual(step["mapHighlight"], "34")

    def test_render_warns_when_no_pass_gate(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "x", "volatility": "safe", "events": []}], threats=THREATS, exit_=EXIT)
        self.assertIn("no pass-gate", planlib.render(self.store))

    def test_render_silent_when_pass_gate_present(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "x", "volatility": "safe", "events": []},
            {"id": "1b", "summary": "pass", "volatility": "safe",
             "passGate": True, "events": []}], threats=THREATS, exit_=EXIT)
        self.assertNotIn("no pass-gate", planlib.render(self.store))


class TestMultiDone(TestPlan):
    """13a: done accepts multiple labels in one invocation, committed in order."""

    def _event_plan(self):
        from tmlib import Engine
        eng = Engine(self.store)
        eng.res("Zed", "mc", +40)
        eng.hand_add(["Comet"])
        return [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]},
            {"id": "1b", "summary": "SP asteroid (14)", "volatility": "safe",
             "events": [{"method": "standard", "args": ["Zed", "asteroid"]}]},
            {"id": "2a", "summary": "table talk", "volatility": "safe", "events": []},
        ]

    def test_multiple_labels_marked_in_order_with_events(self):
        planlib.set_plan(self.store, self._event_plan(), threats=THREATS, exit_=EXIT)
        ids = planlib.mark_done_many(self.store, ["1a", "1b"])
        self.assertEqual(ids, ["1a", "1b"])
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"] and p["steps"][1]["done"])
        self.assertFalse(p["steps"][2]["done"])
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 40 - 18 - 14)
        self.assertNotIn("Comet", g["me"]["hand"])

    def test_unknown_label_mid_sequence_names_it_and_keeps_earlier_done(self):
        planlib.set_plan(self.store, self._event_plan(), threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done_many(self.store, ["1a", "9z", "2a"])
        self.assertIn("9z", str(ctx.exception))
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"])      # 1a committed before the stop
        self.assertFalse(p["steps"][2]["done"])     # 2a never reached
        self.assertNotIn("Comet", self.store.load_game()["me"]["hand"])

    def test_event_failure_after_table_drift_names_failing_label(self):
        planlib.set_plan(self.store, self._event_plan(), threats=THREATS, exit_=EXIT)
        from tmlib import Engine
        Engine(self.store).res("Zed", "mc", -10)   # drift: 30 MC left
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done_many(self.store, ["1a", "1b"])
        # 1a (18 MC) fits, 1b's asteroid (14 MC) does not on the 12 left
        self.assertIn("1b", str(ctx.exception))
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"])
        self.assertFalse(p["steps"][1]["done"])
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 12)

    def test_cli_done_accepts_multiple_labels(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        script = Path(__file__).resolve().parent.parent / "scripts" / "planlib.py"
        r = subprocess.run([sys.executable, str(script), "done", "1a", "1b"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Marked done: 1a, 1b", r.stdout)
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"] and p["steps"][1]["done"])

    def test_cli_single_label_still_works(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        script = Path(__file__).resolve().parent.parent / "scripts" / "planlib.py"
        r = subprocess.run([sys.executable, str(script), "done", "1a"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Marked done: 1a", r.stdout)


class TestVerifyAfterApply(unittest.TestCase):
    """After done applies events, app modes diff tracker vs the app.

    The check is advisory (⚠ block, never an exception) and must NEVER
    break table play: any network/parse trouble → silent skip; physical
    mode → no fetch at all.
    """

    def setUp(self):
        import copy
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        setup = copy.deepcopy(SETUP)
        setup["gameMode"] = "app-practice"
        setup["appUrl"] = "http://localhost:8080"
        next(p for p in setup["players"] if p["isMe"])["playerId"] = "p1"
        self.store.init(setup)
        self._orig_fetch = planlib._fetch_app
        self.fetch_calls = []

    def tearDown(self):
        planlib._fetch_app = self._orig_fetch
        self.tmp.cleanup()

    def _fake_fetch(self, payload=None, exc=None):
        def fake(url, pid):
            self.fetch_calls.append((url, pid))
            if exc is not None:
                raise exc
            return payload
        planlib._fetch_app = fake

    @staticmethod
    def _app_payload(mc=0, tr=20, plants=0, heat=0,
                     temperature=-30, oxygen=0, oceans=0):
        return {"thisPlayer": {"megaCredits": mc, "terraformRating": tr,
                               "plants": plants, "heat": heat},
                "game": {"temperature": temperature, "oxygenLevel": oxygen,
                         "oceans": oceans}}

    def _plan_and_done(self):
        import contextlib, io
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "gain 5 MC", "volatility": "safe",
             "events": [{"method": "res", "args": ["Zed", "mc", 5]}]}], threats=THREATS, exit_=EXIT)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            # app modes default to no-apply; verify-after-apply is
            # exercised by the explicit --apply path
            planlib.mark_done(self.store, "1a", apply_events=True)
        return buf.getvalue()

    def test_match_is_silent(self):
        self._fake_fetch(self._app_payload(mc=5))
        out = self._plan_and_done()
        self.assertNotIn("VERIFY-AFTER-APPLY", out)
        self.assertEqual(len(self.fetch_calls), 1)

    def test_mismatch_prints_block_with_exact_deltas(self):
        self._fake_fetch(self._app_payload(mc=8, tr=21, oceans=1))
        out = self._plan_and_done()
        self.assertIn("⚠ VERIFY-AFTER-APPLY", out)
        self.assertIn("MC", out)         # tracker 5 vs app 8
        self.assertIn("TR", out)         # tracker 20 vs app 21
        self.assertIn("oceans", out)     # tracker 0 vs app 1
        # events were still applied — the check never blocks
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 5)
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_server_absent_is_silent_skip(self):
        import urllib.error
        self._fake_fetch(exc=urllib.error.URLError("connection refused"))
        out = self._plan_and_done()
        self.assertNotIn("VERIFY-AFTER-APPLY", out)   # never breaks table play

    def test_physical_mode_never_fetches(self):
        setup = self.store.load_setup()
        setup["gameMode"] = "physical"
        self.store._write_json(self.store.setup_path, setup)
        self._fake_fetch(self._app_payload())
        self._plan_and_done()
        self.assertEqual(self.fetch_calls, [])

    def test_no_app_url_or_player_id_skips_silently(self):
        setup = self.store.load_setup()
        del setup["appUrl"]
        self.store._write_json(self.store.setup_path, setup)
        self._fake_fetch(self._app_payload(mc=99))
        out = self._plan_and_done()
        self.assertEqual(self.fetch_calls, [])
        self.assertNotIn("VERIFY-AFTER-APPLY", out)

    def test_env_var_supplies_app_url(self):
        import os
        setup = self.store.load_setup()
        del setup["appUrl"]
        self.store._write_json(self.store.setup_path, setup)
        self._fake_fetch(self._app_payload(mc=7))
        os.environ["PHOBOS_APP_URL"] = "http://envhost:8080"
        try:
            out = self._plan_and_done()
        finally:
            del os.environ["PHOBOS_APP_URL"]
        self.assertEqual(len(self.fetch_calls), 1)
        self.assertIn("http://envhost:8080", self.fetch_calls[0][0])
        self.assertIn("⚠ VERIFY-AFTER-APPLY", out)

    def test_done_many_verifies_once_at_the_end(self):
        import contextlib, io
        self._fake_fetch(self._app_payload(mc=99))
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "gain 5 MC", "volatility": "safe",
             "events": [{"method": "res", "args": ["Zed", "mc", 5]}]},
            {"id": "1b", "summary": "gain 2 heat", "volatility": "safe",
             "events": [{"method": "res", "args": ["Zed", "heat", 2]}]}], threats=THREATS, exit_=EXIT)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            planlib.mark_done_many(self.store, ["1a", "1b"], apply_events=True)
        self.assertEqual(len(self.fetch_calls), 1)
        self.assertIn("⚠ VERIFY-AFTER-APPLY", buf.getvalue())


class TestDraftPlan(unittest.TestCase):
    """Speculative turn prep — draft plans composed during the
    opponents' round; promote re-simulates against CURRENT state and only
    then unlocks execution."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        from tmlib import Engine
        self.eng = Engine(self.store)
        g = self.store.load_game()
        g["me"]["resources"]["mc"] = 30
        self.store.save_game(g)

    def tearDown(self):
        self.tmp.cleanup()

    def steps(self, hex_id="03"):
        return [
            {"id": "1a", "summary": "city", "volatility": "recheck",
             "cue": f"your city tile on {hex_id}",       # cue gate
             "events": [{"method": "place",
                         "args": ["Zed", "city", hex_id]}]},
            {"id": "1b", "summary": "pass", "volatility": "recheck",
             "passGate": True, "events": []}]

    def test_draft_stored_and_rendered_as_draft(self):
        planlib.set_plan(self.store, self.steps(), draft=True, threats=THREATS, exit_=EXIT)
        self.assertTrue(planlib.load_plan(self.store)["draft"])
        self.assertIn("DRAFT", planlib.render(self.store))

    def test_done_refused_on_draft(self):
        planlib.set_plan(self.store, self.steps(), draft=True, threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError) as cm:
            planlib.mark_done(self.store, "1a")
        self.assertIn("promote", str(cm.exception))

    def test_promote_clean_unlocks_execution(self):
        planlib.set_plan(self.store, self.steps(), draft=True, threats=THREATS, exit_=EXIT)
        planlib.promote(self.store)
        self.assertFalse(planlib.load_plan(self.store)["draft"])
        planlib.mark_done(self.store, "1a", confirm="ok")   # now legal
        self.assertIn("03", self.store.load_game()["board"])

    def test_promote_refused_when_world_changed(self):
        planlib.set_plan(self.store, self.steps("03"), draft=True, threats=THREATS, exit_=EXIT)
        self.eng.place("Anna", "city", "03")   # opponent takes the hex
        with self.assertRaises(EventError) as cm:
            planlib.promote(self.store)
        self.assertIn("1a", str(cm.exception))
        self.assertTrue(planlib.load_plan(self.store)["draft"])  # stays draft

    def test_promote_on_live_plan_rejected(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            planlib.promote(self.store)

    def test_cli_state_flag_targets_that_folder(self):
        import subprocess
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        with tempfile.TemporaryDirectory() as elsewhere:
            r = subprocess.run(
                [sys.executable, str(Path(__file__).parent.parent / "scripts" / "planlib.py"),
                 "--state", str(self.store.state_dir), "show"],
                capture_output=True, text=True, cwd=elsewhere)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1a", r.stdout)

    def test_cli_draft_and_promote(self):
        import subprocess, json as _json
        env = {"PHOBOS_STATE_DIR": ""}
        r = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "planlib.py"),
             "set", "--draft"],
            input=_json.dumps(self.steps()), capture_output=True, text=True,
            cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("DRAFT", r.stdout)
        r = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "planlib.py"),
             "promote", "--threats", "Anna Builder 7/8", "--exit", EXIT],
            capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("promoted", r.stdout.lower())


class TestSetHonorsDone(TestPlan):
    def test_done_steps_survive_set_and_skip_simulation(self):
        steps = [
            # would be unaffordable if simulated (Zed starts with 0 MC)
            {"id": "1a", "summary": "already executed play", "volatility": "safe",
             "done": True,
             "events": [{"method": "res", "args": ["Zed", "mc", -999]}]},
            {"id": "1b", "summary": "next", "volatility": "safe", "events": []},
        ]
        plan = planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        self.assertTrue(plan["steps"][0]["done"])
        self.assertFalse(plan["steps"][1]["done"])
        # the done step's events were NOT applied by set
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 0)


class TestSkipVerb(TestPlan):
    def test_skip_closes_without_applying_events(self):
        steps = self.steps()
        steps[0]["events"] = [{"method": "res", "args": ["Zed", "mc", 5]}]
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        planlib.mark_skipped(self.store, "1a", reason="never executed at app")
        p = planlib.load_plan(self.store)
        self.assertTrue(p["steps"][0]["done"])
        self.assertTrue(p["steps"][0].get("skipped"))
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 0)

    def test_skip_requires_reason(self):
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            planlib.mark_skipped(self.store, "1a", reason="")


class TestLiveMatGate(TestPlan):
    def test_pass_gate_uses_live_app_mat_when_available(self):
        # tracker says 0 MC (nothing affordable) but the app reports 40 —
        # the gate must see the 40 and refuse the pass.
        steps = [{"id": "1a", "summary": "PASS", "volatility": "recheck",
                  "passGate": True, "events": []}]
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        g = self.store.load_game()
        g["me"]["hand"] = ["Micro-Mills"]        # 3 MC card, playable at 40
        self.store.save_game(g)
        orig = planlib._fetch_live_mat
        planlib._fetch_live_mat = lambda store: {"mc": 40}
        try:
            # playable cards are ADVISORY (a pass with money is
            # normal); the live mat must still surface the card in the
            # advisory list — the mechanism is what this test pins.
            gate, advisory = planlib.gate_split(self.store)
            self.assertTrue(any("Micro-Mills" in a for a in advisory))
            planlib.mark_done(self.store, "1a")          # not refused
        finally:
            planlib._fetch_live_mat = orig


class TestAppModeLite(TestPlan):
    """In app mode the advisor executes in the app
    FIRST and logs second, so `done` must not re-apply events and the
    pass gate reports instead of refusing. Physical mode unchanged."""

    def _app_mode(self):
        setup = self.store.load_setup()
        setup["gameMode"] = "app-practice"      # no appUrl → no network
        (Path(self.tmp.name) / "state" / "setup.json").write_text(
            json.dumps(setup))

    def _comet_plan(self):
        eng = Engine(self.store)
        eng.res("Zed", "mc", +30)
        eng.hand_add(["Comet"])
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]}], threats=THREATS, exit_=EXIT)

    def test_app_mode_done_defaults_to_no_apply(self):
        self._app_mode()
        self._comet_plan()
        planlib.mark_done(self.store, "1a")
        g = self.store.load_game()
        self.assertIn("Comet", g["me"]["hand"])
        self.assertEqual(g["me"]["resources"]["mc"], 30)
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_app_mode_explicit_apply_overrides(self):
        self._app_mode()
        self._comet_plan()
        planlib.mark_done(self.store, "1a", apply_events=True)
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 12)

    def test_cli_apply_flag_overrides_app_default(self):
        self._app_mode()
        self._comet_plan()
        script = Path(__file__).resolve().parent.parent / "scripts" / "planlib.py"
        r = subprocess.run([sys.executable, str(script), "done", "1a", "--apply"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 12)

    def test_physical_mode_still_applies_by_default(self):
        self._comet_plan()
        planlib.mark_done(self.store, "1a")
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 12)

    def _gate_plan(self):
        planlib.set_plan(self.store, [
            {"id": "2b", "summary": "PASS", "volatility": "safe",
             "passGate": True, "events": []}], threats=THREATS, exit_=EXIT)

    def test_sell_patents_alone_never_blocks_a_pass(self):
        g = self.store.load_game()
        g["me"]["hand"] = ["Comet"]              # 0 MC: only "sell patents"
        self.store.save_game(g)
        self._gate_plan()
        planlib.mark_done(self.store, "2b")      # physical mode, no force

    def test_app_mode_gate_reports_but_does_not_refuse(self):
        import contextlib, io
        self._app_mode()
        Engine(self.store).res("Zed", "heat", +8)
        self._gate_plan()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            planlib.mark_done(self.store, "2b")
        self.assertIn("heat", buf.getvalue().lower())
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_physical_mode_gate_still_refuses(self):
        Engine(self.store).res("Zed", "heat", +8)
        self._gate_plan()
        with self.assertRaises(EventError):
            planlib.mark_done(self.store, "2b")


class TestDuplicateEffectWarning(unittest.TestCase):
    """A plan step that carries a `play` event AND explicit prod/res
    events for the same resource double-applies the card — `apply.py play`
    already runs the db.json behavior. The simulation cannot detect it
    (double application is arithmetically legal), so set_plan warns.
    Canonical case: Cloud Seeding's MC and plant production landing twice."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.eng.corp("Zed", "Ecoline", 36)
        self.eng.hand_add(["Power Plant"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_warns_when_step_repeats_db_production(self):
        warnings = planlib.duplicate_effect_warnings([
            {"id": "1a", "events": [
                {"method": "play", "args": ["Zed", "Power Plant"],
                 "kwargs": {"cost": 4}},
                {"method": "prod", "args": ["Zed", "energy", 1]}]},
        ])
        self.assertTrue(warnings, "expected a duplicate-effect warning")
        joined = " ".join(warnings)
        self.assertIn("1a", joined)
        self.assertIn("Power Plant", joined)
        self.assertIn("energy", joined)

    def test_no_warning_for_bespoke_resource_events(self):
        """Nitrophilic Moss's 'lose 2 plants' is NOT in db behavior, so a
        res event alongside the play is correct and must not warn."""
        self.assertEqual(planlib.duplicate_effect_warnings([
            {"id": "1a", "events": [
                {"method": "play", "args": ["Zed", "Nitrophilic Moss"],
                 "kwargs": {"cost": 6}},
                {"method": "res", "args": ["Zed", "plants", -2]}]},
        ]), [])

    def test_no_warning_when_events_are_in_different_steps(self):
        self.assertEqual(planlib.duplicate_effect_warnings([
            {"id": "1a", "events": [
                {"method": "play", "args": ["Zed", "Power Plant"],
                 "kwargs": {"cost": 4}}]},
            {"id": "1b", "events": [
                {"method": "prod", "args": ["Anna", "energy", 1]}]},
        ]), [])

    def test_set_plan_surfaces_the_warning(self):
        plan = planlib.set_plan(self.store, [
            {"id": "1a", "volatility": "safe", "summary": "Power Plant",
             "events": [
                 {"method": "play", "args": ["Zed", "Power Plant"],
                  "kwargs": {"cost": 4}},
                 {"method": "prod", "args": ["Zed", "energy", 1]}]},
        ], threats=THREATS, exit_=EXIT)
        self.assertTrue(plan.get("warnings"))
        self.assertIn("⚠", planlib.render(self.store))


class TestDuplicateEffectWarningFormulaProduction(unittest.TestCase):
    """duplicate_effect_warnings flagged a manual prod event as
    duplicating a card's db behavior even when that behavior is a FORMULA
    (e.g. Medical Lab: production.megacredits = {"tag":"building","per":2}),
    not a plain int. _apply_behavior only auto-applies plain-int production
    deltas (see tmlib._apply_behavior's `all(isinstance(v, int) ...)` gate) —
    a formula falls through to a '→ TABLE' manual step, so a plan step's own
    prod event for that resource is CORRECT, not a duplicate (Medical Lab's plan step is the
    canonical case)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.eng.corp("Zed", "Interplanetary Cinematics", 30)
        self.eng.hand_add(["Medical Lab"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_warning_for_formula_production(self):
        self.assertEqual(planlib.duplicate_effect_warnings([
            {"id": "1a", "events": [
                {"method": "play", "args": ["Zed", "Medical Lab"],
                 "kwargs": {"cost": 13}},
                {"method": "prod", "args": ["Zed", "mc", 3]}]},
        ]), [])


class TestDuplicateEffectWarningTopLevelTR(unittest.TestCase):
    """duplicate_effect_warnings never checked a card's top-level
    `behavior["tr"]` field (a plain int, auto-applied by _apply_behavior
    at tmlib.py — see 'if isinstance(behavior.get("tr"), int): board["tr"]
    += behavior["tr"]'). A plan step carrying both a `play` event for such
    a card AND a manual `tr` event double-applies it, e.g.
    Nitrogen-Rich Asteroid (behavior: {"global":{"temperature":1},
    "tr":2}) — TR lands at +4 instead of +2."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.eng.corp("Zed", "Interplanetary Cinematics", 30)
        self.eng.hand_add(["Nitrogen-Rich Asteroid"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_warns_when_step_repeats_top_level_tr(self):
        warnings = planlib.duplicate_effect_warnings([
            {"id": "1a", "events": [
                {"method": "play", "args": ["Zed", "Nitrogen-Rich Asteroid"],
                 "kwargs": {"cost": 34}},
                {"method": "tr", "args": ["Zed", 2]}]},
        ])
        self.assertTrue(warnings, "expected a duplicate-effect warning")
        joined = " ".join(warnings)
        self.assertIn("1a", joined)
        self.assertIn("Nitrogen-Rich Asteroid", joined)

    def test_no_warning_when_no_manual_tr_event(self):
        self.assertEqual(planlib.duplicate_effect_warnings([
            {"id": "1a", "events": [
                {"method": "play", "args": ["Zed", "Nitrogen-Rich Asteroid"],
                 "kwargs": {"cost": 34}}]},
        ]), [])

    def test_no_warning_for_tr_event_on_a_different_player(self):
        """An opponent-targeted tr event (rare, but same principle as
        opponent-targeted prod/res) is bespoke, not a duplicate."""
        self.assertEqual(planlib.duplicate_effect_warnings([
            {"id": "1a", "events": [
                {"method": "play", "args": ["Zed", "Nitrogen-Rich Asteroid"],
                 "kwargs": {"cost": 34}},
                {"method": "tr", "args": ["Anna", 2]}]},
        ]), [])


class TestCueGate(unittest.TestCase):
    """Cue gate: milestone/award/place steps may only be marked done on their
    OWN execution cue — the player confirms what they SEE, the advisor never
    infers it from a report about a different step (else a milestone stays
    claimable for turns)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        eng = Engine(self.store)
        eng.res("Zed", "mc", +40)
        eng.tr("Zed", +15)                     # TR 35: Terraformer-eligible

    def tearDown(self):
        self.tmp.cleanup()

    def plain(self, sid="1a"):
        return {"id": sid, "summary": "SP asteroid", "volatility": "safe",
                "events": [{"method": "standard", "args": ["Zed", "asteroid"]}]}

    def milestone(self, cue=None, sid="2a"):
        st = {"id": sid, "summary": "Claim Terraformer", "volatility": "recheck",
              "events": [{"method": "milestone", "args": ["Zed", "Terraformer"]}]}
        if cue is not None:
            st["cue"] = cue
        return st

    def place(self, cue=None, sid="2a"):
        st = {"id": sid, "summary": "ocean on 04", "volatility": "recheck",
              "events": [{"method": "place", "args": ["Zed", "ocean", "04"]}]}
        if cue is not None:
            st["cue"] = cue
        return st

    # ── set_plan validation ──────────────────────────────────────
    def test_place_step_without_cue_rejected_naming_step(self):
        with self.assertRaises(EventError) as ctx:
            planlib.set_plan(self.store, [self.plain(), self.place()], threats=THREATS, exit_=EXIT)
        self.assertIn("2a", str(ctx.exception))
        self.assertIn("cue", str(ctx.exception))

    def test_cue_gated_flag_without_events_needs_cue(self):
        with self.assertRaises(EventError) as ctx:
            planlib.set_plan(self.store, [
                {"id": "1a", "summary": "x", "volatility": "safe",
                 "cueGated": True, "events": []}], threats=THREATS, exit_=EXIT)
        self.assertIn("1a", str(ctx.exception))

    def test_blank_cue_is_rejected(self):
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, [self.place(cue="   ")], threats=THREATS, exit_=EXIT)

    def test_milestone_step_with_cue_accepted_and_stored(self):
        planlib.set_plan(self.store,
                         [self.milestone(cue="your marker sits on Terraformer")], threats=THREATS, exit_=EXIT)
        st = planlib.load_plan(self.store)["steps"][0]
        self.assertEqual(st["cue"], "your marker sits on Terraformer")
        self.assertTrue(planlib.is_cue_gated(st))

    def test_milestone_and_award_autofill_cue_like_map_highlight(self):
        planlib.set_plan(self.store, [
            self.milestone(sid="1a"),
            {"id": "1b", "summary": "fund Banker — lock test: not lockable",
             "volatility": "recheck",
             "awardAck": "test fixture: funding is not the property under test",
             "events": [{"method": "award", "args": ["Zed", "Banker"]}]}], threats=THREATS, exit_=EXIT)
        steps = planlib.load_plan(self.store)["steps"]
        self.assertEqual(steps[0]["cue"], "your marker on Terraformer")
        self.assertEqual(steps[1]["cue"], "your marker on Banker")

    def test_draft_plan_follows_same_validation(self):
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, [self.place()], draft=True)
        planlib.set_plan(self.store, [self.place(cue="blue ocean tile on 04")],
                         draft=True)
        self.assertTrue(planlib.load_plan(self.store)["draft"])

    def test_already_done_steps_in_replan_not_validated(self):
        done = self.place(); done["done"] = True
        planlib.set_plan(self.store, [done, self.plain(sid="2b")], threats=THREATS, exit_=EXIT)
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_non_gated_steps_carry_no_cue_requirement(self):
        planlib.set_plan(self.store, [self.plain()], threats=THREATS, exit_=EXIT)
        st = planlib.load_plan(self.store)["steps"][0]
        self.assertFalse(planlib.is_cue_gated(st))

    # ── done ─────────────────────────────────────────────────────
    def test_done_refuses_gated_step_without_confirm_and_prints_cue(self):
        planlib.set_plan(self.store, [
            self.plain(), self.milestone(cue="your marker sits on Terraformer")], threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done(self.store, "2a")
        msg = str(ctx.exception)
        self.assertIn("your marker sits on Terraformer", msg)
        self.assertIn("done 2a --confirm", msg)
        self.assertFalse(planlib.load_plan(self.store)["steps"][1]["done"])
        # nothing applied: Terraformer still unclaimed
        self.assertEqual(self.store.load_game()["milestonesClaimed"], {})

    def test_done_with_confirm_applies_and_logs_confirmation(self):
        planlib.set_plan(self.store, [
            self.milestone(sid="1a", cue="your marker sits on Terraformer")], threats=THREATS, exit_=EXIT)
        ids = planlib.mark_done(self.store, "1a", confirm="ok")
        self.assertEqual(ids, ["1a"])
        self.assertEqual(self.store.load_game()["milestonesClaimed"],
                         {"Terraformer": "Zed"})
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("cue confirmed", log)

    def test_done_blank_confirm_still_refused(self):
        planlib.set_plan(self.store, [self.milestone(sid="1a")], threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            planlib.mark_done(self.store, "1a", confirm="   ")

    def test_non_gated_step_done_without_confirm(self):
        planlib.set_plan(self.store, [self.plain()], threats=THREATS, exit_=EXIT)
        self.assertEqual(planlib.mark_done(self.store, "1a"), ["1a"])

    def test_whole_turn_with_gated_step_needs_confirm(self):
        planlib.set_plan(self.store, [self.plain("1a"), self.milestone(sid="1b")], threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            planlib.mark_done(self.store, "1")
        self.assertFalse(any(s["done"]
                             for s in planlib.load_plan(self.store)["steps"]))
        planlib.mark_done(self.store, "1", confirm="saw it")
        self.assertTrue(all(s["done"]
                            for s in planlib.load_plan(self.store)["steps"]))

    def test_done_many_one_confirm_covers_all_gated(self):
        planlib.set_plan(self.store, [
            self.plain("1a"), self.milestone(sid="1b"),
            self.place(sid="2a", cue="ocean on 04")], threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done_many(self.store, ["1a", "1b", "2a"])
        self.assertIn("1b", str(ctx.exception))
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])  # 1a committed
        ids = planlib.mark_done_many(self.store, ["1b", "2a"], confirm="yes")
        self.assertEqual(ids, ["1b", "2a"])

    # ── show ─────────────────────────────────────────────────────
    def test_show_prints_cue_on_open_gated_steps_only(self):
        planlib.set_plan(self.store, [
            self.plain("1a"),
            self.milestone(sid="1b", cue="your marker sits on Terraformer")], threats=THREATS, exit_=EXIT)
        out = planlib.render(self.store)
        self.assertIn("cue: your marker sits on Terraformer", out)
        planlib.mark_done_many(self.store, ["1a", "1b"], confirm="ok")
        self.assertNotIn("cue:", planlib.render(self.store))

    # ── CLI ──────────────────────────────────────────────────────
    def _cli(self, *args, stdin=None):
        script = Path(__file__).resolve().parent.parent / "scripts" / "planlib.py"
        return subprocess.run([sys.executable, str(script), *args],
                              cwd=self.tmp.name, capture_output=True,
                              text=True, input=stdin)

    def test_cli_done_confirm_flag(self):
        r = self._cli("set", stdin=json.dumps({"threats": THREATS, "exit": EXIT, "steps": [self.milestone(sid="1a")]}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cue: your marker on Terraformer", r.stdout)
        r = self._cli("done", "1a")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("your marker on Terraformer", r.stderr)
        r = self._cli("done", "1a", "--confirm", "ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("✅ 1a", r.stdout)

    def test_help_mentions_confirm(self):
        r = self._cli("done", "--help")
        self.assertIn("--confirm", r.stdout)


class TestPassGateAdvisoryItems(TestPlan):
    """With money and playable cards in hand
    the new menu-based gate refused EVERY pass (cards, standard projects,
    awards listed). Only free / always-positive items block: conversions,
    unused free blue actions, claimable milestones. Cards, standard projects
    and award funding are advisory — the advisor decides those in the plan."""

    def _pass_plan(self):
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "pass", "volatility": "safe",
             "passGate": True, "events": []}], threats=THREATS, exit_=EXIT)

    def test_pass_allowed_with_money_and_playable_cards(self):
        g = self.store.load_game()
        g["me"]["resources"]["mc"] = 48
        g["me"]["hand"] = ["Nuclear Power", "Sponsors"]
        self.store.save_game(g)
        self._pass_plan()
        planlib.mark_done(self.store, "1a")          # must not raise
        self.assertTrue(planlib.load_plan(self.store)["steps"][0]["done"])

    def test_pass_still_refused_on_free_conversion(self):
        g = self.store.load_game()
        g["me"]["resources"]["mc"] = 48
        g["me"]["resources"]["heat"] = 8
        self.store.save_game(g)
        self._pass_plan()
        with self.assertRaises(EventError):
            planlib.mark_done(self.store, "1a")

    def test_gate_and_advisory_split_exposed(self):
        g = self.store.load_game()
        g["me"]["resources"]["mc"] = 48
        g["me"]["resources"]["plants"] = 8
        g["me"]["hand"] = ["Nuclear Power"]
        self.store.save_game(g)
        gate, advisory = planlib.gate_split(self.store)
        self.assertTrue(any("plants" in x for x in gate))
        self.assertTrue(any("Nuclear Power" in x for x in advisory))
        self.assertFalse(any("Nuclear Power" in x for x in gate))
