"""P3 lane 2: `planlib.py patch` — replace / insert_after / remove named
steps of the DRAFT (or the live plan with --live) from a JSON spec; done
steps are untouchable; the remainder is re-simulated like set_plan; the
feed lines given are marked handled. `promote` never blocks on an
in-flight sweep: it clears the flag, records the abandonment, proceeds."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP
import applog_parser as P
import judgment
import latency
import planlib
import triage

PLAYERS = [p["name"] for p in SETUP["players"]]
THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "planlib.py"


def entry(line: int, raw: str) -> dict:
    return triage.new_entry(P.parse_line(raw, PLAYERS), line=line, gen=1,
                            raw=raw, ts="2026-01-01T00:00:00")


class PatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.eng.res("Zed", "mc", +60)
        self.eng.tr("Zed", +15)                       # Terraformer-eligible
        self.eng.hand_add(["Comet", "Sponsors"])
        self.feed = triage.feed_path(self.store)
        triage.write_feed(self.feed, [entry(7, "Anna placed city tile at 03"),
                                      entry(8, "Anna claimed Builder milestone")])

    def tearDown(self):
        self.tmp.cleanup()

    def steps(self):
        return [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]},
            {"id": "1b", "summary": "city on 03", "volatility": "recheck",
             "cue": "your city on 03",
             "events": [{"method": "place", "args": ["Zed", "city", "03"]}]},
            {"id": "2a", "summary": "Claim Terraformer", "volatility": "recheck",
             "events": [{"method": "milestone", "args": ["Zed", "Terraformer"]}]},
            {"id": "2b", "summary": "pass", "volatility": "recheck",
             "passGate": True, "events": []}]

    def set(self, draft=True):
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT, "steps": self.steps()},
                         draft=draft)

    def plan(self):
        return planlib.load_plan(self.store)

    def ids(self):
        return [s["id"] for s in self.plan()["steps"]]

    def log(self):
        return (self.root / "state" / "log.md").read_text()


class TestPatch(PatchCase):
    def test_replace_insert_remove_keep_order_and_autofills(self):
        self.set()
        plan = planlib.patch(self.store, {
            "replace": [{"id": "1b", "summary": "city on 05", "volatility":
                         "recheck", "cue": "your city on 05",
                         "events": [{"method": "place",
                                     "args": ["Zed", "city", "05"]}]}],
            "insert_after": {"1a": [{"id": "1c", "summary": "Play Sponsors",
                                     "volatility": "safe",
                                     "events": [{"method": "play",
                                                 "args": ["Zed", "Sponsors"],
                                                 "kwargs": {"cost": 6}}]}]},
            "remove": ["2a"],
            "feed": [7, 8]})
        self.assertEqual([s["id"] for s in plan["steps"]], ["1a", "1c", "1b", "2b"])
        by = {s["id"]: s for s in plan["steps"]}
        self.assertEqual(by["1b"]["mapHighlight"], "05")        # autofill
        self.assertTrue(plan["draft"])                          # stays draft
        self.assertEqual(plan["threats"], THREATS)
        self.assertIn("Plan patched", self.log())
        self.assertIn("#7", self.log()); self.assertIn("#8", self.log())

    def test_milestone_cue_autofill_and_threats_update(self):
        self.set()
        plan = planlib.patch(self.store, {
            "replace": [{"id": "2a", "summary": "Claim Mayor", "volatility":
                         "recheck", "events": [{"method": "milestone",
                                                "args": ["Zed", "Terraformer"]}]}],
            "threats": "Anna took Builder — Terraformer is the only race left"})
        by = {s["id"]: s for s in plan["steps"]}
        self.assertEqual(by["2a"]["cue"], "your marker on Terraformer")
        self.assertIn("only race left", plan["threats"])

    def test_feed_lines_marked_handled_with_patched_ids(self):
        self.set()
        planlib.patch(self.store, {"remove": ["2a"], "feed": [8]})
        entries = {e["line"]: e for e in triage.read_feed(self.feed)}
        self.assertTrue(entries[8]["handled"])
        self.assertIn("patched", entries[8]["handledNote"])
        self.assertIn("2a", entries[8]["handledNote"])
        self.assertFalse(entries[7]["handled"])

    def test_empty_patch_concludes_sweep_marks_feed_only(self):
        self.set()
        before = self.plan()
        plan = planlib.patch(self.store, {"feed": [7, 8]})
        self.assertEqual(plan["steps"], before["steps"])
        self.assertTrue(all(e["handled"] for e in triage.read_feed(self.feed)))

    def test_patch_clears_inflight_sweep_flag(self):
        self.set()
        planlib.set_sweep_inflight(self.store, [7, 8])
        planlib.patch(self.store, {"feed": [7, 8]})
        self.assertFalse(planlib.sweep_flag_path(self.store).exists())

    def test_done_steps_are_untouchable(self):
        self.set(draft=False)
        planlib.mark_done(self.store, "1a")
        for spec in ({"replace": [{"id": "1a", "summary": "x", "volatility": "safe"}]},
                     {"remove": ["1a"]}):
            with self.assertRaises(EventError) as cm:
                planlib.patch(self.store, spec, live=True)
            self.assertIn("1a", str(cm.exception))
            self.assertIn("done", str(cm.exception).lower())
        self.assertEqual(self.ids(), ["1a", "1b", "2a", "2b"])   # untouched

    def test_patch_preserves_done_markers_of_other_steps(self):
        self.set(draft=False)
        planlib.mark_done(self.store, "1a")
        plan = planlib.patch(self.store, {"remove": ["2a"]}, live=True)
        self.assertTrue(plan["steps"][0]["done"])
        self.assertEqual([s["id"] for s in plan["steps"]], ["1a", "1b", "2b"])
        self.assertFalse(plan["draft"])

    def test_simulation_failure_leaves_the_steps_untouched(self):
        self.set()
        before = self.plan()
        with self.assertRaises(EventError) as cm:
            planlib.patch(self.store, {
                "insert_after": {"2a": [{"id": "2c", "summary": "SP city x3",
                                         "volatility": "safe",
                                         "events": [{"method": "standard",
                                                     "args": ["Zed", "city"]},
                                                    {"method": "standard",
                                                     "args": ["Zed", "city"]},
                                                    {"method": "standard",
                                                     "args": ["Zed", "city"]}]}]},
                "feed": [7]})
        self.assertIn("2c", str(cm.exception))
        after = self.plan()
        self.assertEqual(after["steps"], before["steps"])
        self.assertEqual(after["threats"], before["threats"])
        self.assertFalse(triage.read_feed(self.feed)[0]["handled"])

    def test_cue_gate_applies_to_patched_steps(self):
        self.set()
        with self.assertRaises(EventError) as cm:
            planlib.patch(self.store, {"replace": [
                {"id": "1b", "summary": "city on 05", "volatility": "recheck",
                 "events": [{"method": "place", "args": ["Zed", "city", "05"]}]}]})
        self.assertIn("cue", str(cm.exception))

    def test_live_plan_is_patched_without_the_flag_when_no_draft_exists(self):
        # P8 #9: the sweep's CONCLUDE runs `patch` on the player's own turn,
        # when the plan is always live and no draft exists — refusing there
        # is a dead end (the gen-3 feed patch silently failed).
        self.set(draft=False)
        planlib.patch(self.store, {"remove": ["2a"]})
        self.assertEqual(self.ids(), ["1a", "1b", "2b"])
        self.assertIn("live", self.log().lower())

    def test_refusal_kept_while_a_draft_exists_beside_the_live_plan(self):
        self.set(draft=False)
        (self.root / "state" / planlib.DRAFT_SIDECAR).write_text("{}\n")
        with self.assertRaises(EventError) as cm:
            planlib.patch(self.store, {"remove": ["2a"]})
        self.assertIn("--live", str(cm.exception))
        self.assertEqual(self.ids(), ["1a", "1b", "2a", "2b"])

    def test_unknown_or_duplicate_ids_refused(self):
        self.set()
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"remove": ["9z"]})
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"insert_after": {"1a": [
                {"id": "1b", "summary": "dup", "volatility": "safe"}]}})
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"insert_after": {"1a": [
                {"id": "1c", "summary": "x", "volatility": "safe", "done": True}]}})

    def test_live_patch_refuses_empty_threats(self):
        self.set(draft=False)
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"threats": ""}, live=True)

    def test_cli_patch_reads_stdin(self):
        self.set()
        r = subprocess.run([sys.executable, str(SCRIPT), "patch"],
                           input=json.dumps({"remove": ["2a"], "feed": [8]}),
                           capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("patched", r.stdout.lower())
        self.assertIn("DRAFT", r.stdout)
        self.assertEqual(self.ids(), ["1a", "1b", "2b"])
        r = subprocess.run([sys.executable, str(SCRIPT), "patch", "--live"],
                           input=json.dumps({"remove": ["1b"]}),
                           capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stderr)   # --live also covers drafts


class TestPatchSpecShapes(PatchCase):
    """P8 #10: `{"replace": {"1b": {…}}}` (a dict keyed by step id) raised a
    traceback and the chained execute ran the UNPATCHED step. Both shapes
    are accepted; anything else is a one-line usage error."""

    def city05(self):
        return {"summary": "city on 05", "volatility": "recheck",
                "cue": "your city on 05",
                "events": [{"method": "place", "args": ["Zed", "city", "05"]}]}

    def test_replace_accepts_a_dict_keyed_by_step_id(self):
        self.set()
        plan = planlib.patch(self.store, {"replace": {"1b": self.city05()}})
        by = {s["id"]: s for s in plan["steps"]}
        self.assertEqual(by["1b"]["summary"], "city on 05")
        self.assertEqual(by["1b"]["mapHighlight"], "05")
        self.assertEqual([s["id"] for s in plan["steps"]],
                         ["1a", "1b", "2a", "2b"])

    def test_dict_key_wins_over_a_missing_id(self):
        self.set()
        step = self.city05()
        self.assertNotIn("id", step)
        planlib.patch(self.store, {"replace": {"1b": step}})
        self.assertEqual(self.ids(), ["1a", "1b", "2a", "2b"])

    def test_insert_after_values_accept_a_dict_too(self):
        self.set()
        plan = planlib.patch(self.store, {"insert_after": {"1a": {
            "1c": {"summary": "Play Sponsors", "volatility": "safe",
                   "events": [{"method": "play", "args": ["Zed", "Sponsors"],
                               "kwargs": {"cost": 6}}]}}}})
        self.assertEqual([s["id"] for s in plan["steps"]],
                         ["1a", "1c", "1b", "2a", "2b"])

    def test_bad_shape_is_a_one_line_usage_error(self):
        self.set()
        for spec in ({"replace": "1b"},
                     {"replace": ["1b"]},
                     {"replace": {"1b": "city on 05"}},
                     {"remove": {"2a": True}},
                     {"insert_after": ["1a"]}):
            with self.subTest(spec=spec):
                with self.assertRaises(EventError) as cm:
                    planlib.patch(self.store, spec)
                msg = str(cm.exception)
                self.assertEqual(len(msg.splitlines()), 1, msg)
                self.assertIn("patch:", msg)
        self.assertEqual(self.ids(), ["1a", "1b", "2a", "2b"])

    def test_cli_bad_shape_exits_nonzero_without_a_traceback(self):
        self.set()
        r = subprocess.run([sys.executable, str(SCRIPT), "patch"],
                           input=json.dumps({"replace": {"1b": "nope"}}),
                           capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("patch:", r.stderr)

    def test_cli_invalid_json_is_not_a_traceback(self):
        self.set()
        r = subprocess.run([sys.executable, str(SCRIPT), "patch"],
                           input="{not json",
                           capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)


class TestPatchFailedFlag(PatchCase):
    """P8 #10: a failed patch is recorded in plan.json so the executor
    (execute.py checks `patchFailed`) refuses to run the unpatched step."""

    def fail(self):
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"remove": ["9z"]})

    def test_failure_records_patch_failed(self):
        self.set()
        self.fail()
        self.assertIn("9z", self.plan()["patchFailed"])
        self.assertEqual(len(self.plan()["patchFailed"].splitlines()), 1)

    def test_show_prints_a_warning_line(self):
        self.set()
        self.fail()
        out = planlib.render(self.store)
        self.assertIn("⚠ PATCH FAILED", out)
        self.assertIn("9z", out)

    def test_shape_error_records_it_too(self):
        self.set()
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"replace": "1b"})
        self.assertIn("patch:", self.plan()["patchFailed"])

    def test_next_successful_patch_clears_it(self):
        self.set()
        self.fail()
        planlib.patch(self.store, {"feed": [7]})
        self.assertNotIn("patchFailed", self.plan())

    def test_set_plan_clears_it(self):
        self.set()
        self.fail()
        self.set()
        self.assertNotIn("patchFailed", self.plan())

    def test_promote_clears_it(self):
        self.set()
        self.fail()
        planlib.promote(self.store)
        self.assertNotIn("patchFailed", self.plan())

    def test_no_plan_at_all_is_not_an_error_path(self):
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"remove": ["1a"]})   # no plan stored


class TestFeedCursor(PatchCase):
    """P8 #14: the plan records the feed line it was composed at, so triage
    never re-matches older lines against it."""

    def test_set_plan_records_the_last_feed_line(self):
        self.set()
        self.assertEqual(self.plan()["feedCursor"], 8)

    def test_patch_keeps_the_creation_cursor(self):
        self.set()
        triage.write_feed(self.feed, triage.read_feed(self.feed)
                          + [entry(9, "Anna gained 2 megacredits")])
        planlib.patch(self.store, {"remove": ["2a"]})
        self.assertEqual(self.plan()["feedCursor"], 8)

    def test_no_feed_means_cursor_zero(self):
        self.feed.unlink()
        self.set()
        self.assertEqual(self.plan()["feedCursor"], 0)


class TestPromoteNeverBlocks(PatchCase):
    def test_promote_with_inflight_sweep_abandons_and_proceeds(self):
        self.set()
        planlib.set_sweep_inflight(self.store, [7, 8])
        out = planlib.promote(self.store)
        self.assertIn("promoted", out)
        self.assertIn("abandoned", out)
        self.assertFalse(self.plan()["draft"])
        self.assertFalse(planlib.sweep_flag_path(self.store).exists())
        self.assertEqual(judgment.load(self.store)["abandonStreak"], 1)
        marks = latency.read_marks(latency.path_for(self.store))
        self.assertEqual(marks[-1]["phase"], "sweep")
        self.assertEqual(marks[-1]["note"], "abandoned")
        self.assertIn("abandoned", self.log().lower())

    def test_promote_without_flag_records_nothing(self):
        self.set()
        out = planlib.promote(self.store)
        self.assertEqual(out, "promoted")
        self.assertNotIn("abandonStreak", self.store.load_setup().get("judgment") or {})
        self.assertEqual(latency.read_marks(latency.path_for(self.store)), [])

    def test_refused_promote_still_clears_the_flag(self):
        self.set()
        self.eng.place("Anna", "city", "03")          # 1b now infeasible
        planlib.set_sweep_inflight(self.store, [7])
        with self.assertRaises(EventError):
            planlib.promote(self.store)
        self.assertFalse(planlib.sweep_flag_path(self.store).exists())
        self.assertTrue(self.plan()["draft"])

    def test_abandon_helper_returns_none_without_flag(self):
        self.assertIsNone(planlib.abandon_sweep(self.store))


if __name__ == "__main__":
    unittest.main()
