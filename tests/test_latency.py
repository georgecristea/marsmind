"""scripts/latency.py — table-hot instrumentation.

Marks are appended to state/latency.jsonl (one JSON object per line); the
digest pairs start/end marks per phase and reports count / p50 / p95 / max
in milliseconds plus the number of quiet-zone abandonments. session.py end
prints the digest and archives it as latency-digest.json (skipped silently
when no marks were recorded).
"""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import GameManager, Store
from test_new_game import SETUP
import latency

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _write_marks(path: Path, entries):
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _pair(phase, t0, t1, note=""):
    """A start/end pair for `phase`, seconds since epoch."""
    return [{"ts": t0, "phase": phase, "edge": "start", "gen": 1, "note": ""},
            {"ts": t1, "phase": phase, "edge": "end", "gen": 1, "note": note}]


class TestMarks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        GameManager(self.root, today="2031-04-01").start(SETUP)
        self.store = Store(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mark_appends_json_line_with_all_fields(self):
        latency.mark("sweep", "start", store=self.store)
        latency.mark("sweep", "end", note="abandoned", store=self.store)
        lines = latency.path_for(self.store).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        first, second = (json.loads(l) for l in lines)
        self.assertEqual(set(first), {"ts", "phase", "edge", "gen", "note"})
        self.assertEqual(first["phase"], "sweep")
        self.assertEqual(first["edge"], "start")
        self.assertEqual(first["gen"], 1)          # read from game.json
        self.assertEqual(second["edge"], "end")
        self.assertEqual(second["note"], "abandoned")
        self.assertGreaterEqual(second["ts"], first["ts"])

    def test_unknown_phase_or_edge_refused(self):
        with self.assertRaises(ValueError):
            latency.mark("lunch", "start", store=self.store)
        with self.assertRaises(ValueError):
            latency.mark("sweep", "middle", store=self.store)

    def test_timed_context_manager_writes_start_and_end(self):
        with latency.timed("triage", store=self.store):
            pass
        entries = latency.read_marks(latency.path_for(self.store))
        self.assertEqual([e["edge"] for e in entries], ["start", "end"])
        self.assertEqual({e["phase"] for e in entries}, {"triage"})
        d = latency.digest(latency.path_for(self.store))
        self.assertEqual(d["phases"]["triage"]["count"], 1)

    def test_timed_marks_abandoned_when_body_raises(self):
        with self.assertRaises(RuntimeError):
            with latency.timed("sweep", store=self.store):
                raise RuntimeError("player spoke — sweep dropped")
        entries = latency.read_marks(latency.path_for(self.store))
        self.assertEqual(entries[-1]["edge"], "end")
        self.assertEqual(entries[-1]["note"], "abandoned")
        d = latency.digest(latency.path_for(self.store))
        self.assertEqual(d["quiet_zone_abandonments"], 1)

    def test_timed_lets_caller_set_the_note(self):
        with latency.timed("plan", store=self.store) as t:
            t.note = "gen 3 plan"
        entries = latency.read_marks(latency.path_for(self.store))
        self.assertEqual(entries[-1]["note"], "gen 3 plan")

    def test_marks_round_trip_through_cli(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "latency.py"), "mark", "listen", "start"],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "latency.py"), "mark", "listen", "end",
             "--note", "abandoned"],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        entries = latency.read_marks(self.root / "state" / "latency.jsonl")
        self.assertEqual([e["edge"] for e in entries], ["start", "end"])
        self.assertEqual(entries[1]["note"], "abandoned")
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "latency.py"), "digest"],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["phases"]["listen"]["count"], 1)
        self.assertEqual(d["quiet_zone_abandonments"], 1)

    def test_cli_rejects_unknown_phase(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "latency.py"), "mark", "lunch", "start"],
            cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)


class TestDigest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "latency.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_is_an_empty_digest(self):
        d = latency.digest(self.path)
        self.assertEqual(d, {"marks": 0, "phases": {},
                             "quiet_zone_abandonments": 0})

    def test_odd_count_percentiles(self):
        # durations 100, 200, 300 ms → p50 = 200, p95 = 290, max = 300
        entries = (_pair("sweep", 10.0, 10.1) + _pair("sweep", 20.0, 20.2)
                   + _pair("sweep", 30.0, 30.3))
        _write_marks(self.path, entries)
        d = latency.digest(self.path)
        s = d["phases"]["sweep"]
        self.assertEqual(s["count"], 3)
        self.assertAlmostEqual(s["p50"], 200.0, places=3)
        self.assertAlmostEqual(s["p95"], 290.0, places=3)
        self.assertAlmostEqual(s["max"], 300.0, places=3)
        self.assertEqual(d["marks"], 6)

    def test_even_count_percentiles(self):
        # durations 100, 200, 300, 400 ms → p50 = 250 (median of the two
        # middle values), p95 = 385, max = 400
        entries = (_pair("plan", 1.0, 1.1) + _pair("plan", 2.0, 2.2)
                   + _pair("plan", 3.0, 3.3) + _pair("plan", 4.0, 4.4))
        _write_marks(self.path, entries)
        s = latency.digest(self.path)["phases"]["plan"]
        self.assertEqual(s["count"], 4)
        self.assertAlmostEqual(s["p50"], 250.0, places=3)
        self.assertAlmostEqual(s["p95"], 385.0, places=3)
        self.assertAlmostEqual(s["max"], 400.0, places=3)

    def test_single_pair(self):
        _write_marks(self.path, _pair("research", 5.0, 5.05))
        s = latency.digest(self.path)["phases"]["research"]
        self.assertEqual(s["count"], 1)
        self.assertAlmostEqual(s["p50"], 50.0, places=3)
        self.assertAlmostEqual(s["p95"], 50.0, places=3)
        self.assertAlmostEqual(s["max"], 50.0, places=3)

    def test_phases_are_paired_independently_and_abandonments_counted(self):
        entries = (_pair("sweep", 1.0, 1.5, note="abandoned")
                   + _pair("listen", 2.0, 2.1)
                   + _pair("sweep", 3.0, 3.2)
                   + _pair("execute", 4.0, 4.9, note="abandoned"))
        _write_marks(self.path, entries)
        d = latency.digest(self.path)
        self.assertEqual(set(d["phases"]), {"sweep", "listen", "execute"})
        self.assertEqual(d["phases"]["sweep"]["count"], 2)
        self.assertAlmostEqual(d["phases"]["sweep"]["max"], 500.0, places=3)
        self.assertEqual(d["quiet_zone_abandonments"], 2)

    def test_unpaired_start_is_not_a_duration(self):
        entries = [{"ts": 1.0, "phase": "sweep", "edge": "start", "gen": 1,
                    "note": ""}] + _pair("sweep", 2.0, 2.1)
        _write_marks(self.path, entries)
        s = latency.digest(self.path)["phases"]["sweep"]
        self.assertEqual(s["count"], 1)
        self.assertAlmostEqual(s["max"], 100.0, places=3)

    def test_garbage_lines_are_skipped(self):
        self.path.write_text("not json\n" + json.dumps(
            {"ts": 1.0, "phase": "other", "edge": "start", "gen": 1, "note": ""})
            + "\n" + json.dumps(
            {"ts": 1.25, "phase": "other", "edge": "end", "gen": 1, "note": ""})
            + "\n")
        d = latency.digest(self.path)
        self.assertEqual(d["phases"]["other"]["count"], 1)


class TestSessionEndDigest(unittest.TestCase):
    """session.py end prints the digest and archives latency-digest.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gm = GameManager(self.root, today="2031-04-02")
        self.game_dir = self.gm.start(SETUP)

    def tearDown(self):
        self.tmp.cleanup()

    def _end(self):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "session.py"), "end", "--note", "t"],
            cwd=self.root, capture_output=True, text=True)

    def test_end_writes_digest_when_marks_exist(self):
        _write_marks(self.game_dir / "latency.jsonl",
                     _pair("sweep", 1.0, 1.2) + _pair("sweep", 2.0, 2.4, "abandoned"))
        r = self._end()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Game ended and archived", r.stdout)
        self.assertIn("sweep", r.stdout)
        self.assertIn("abandon", r.stdout.lower())
        archived = json.loads((self.game_dir / "latency-digest.json").read_text())
        self.assertEqual(archived["phases"]["sweep"]["count"], 2)
        self.assertEqual(archived["quiet_zone_abandonments"], 1)

    def test_end_without_marks_is_silent(self):
        r = self._end()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("latency", r.stdout.lower())
        self.assertFalse((self.game_dir / "latency-digest.json").exists())

    def test_end_digest_helper_returns_none_without_marks(self):
        import session
        self.assertIsNone(session.end_latency_digest(self.game_dir))


if __name__ == "__main__":
    unittest.main()
