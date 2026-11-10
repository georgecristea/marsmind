"""S6 — instrument every decision boundary (speed-plan 2.2 / 3.1 / 3.3).

The P9 speed analysis reconstructed think-time per decision from the
wall-clock marks in latency.jsonl — but the advisor placed ONE plan mark by
hand in 13 generations and the seats had no trace at all (`sparring.py`
never called `latency.mark`). Contract under test:

* `sparring.py wait` / `send` (and every verb that sends) mark into the
  SEAT's own store, `seats/<pid>/latency.jsonl`, in the advisor's file
  shape ({ts, phase, edge, gen, note}) so one reconstruction reads both.
* The advisor's marks are unchanged in shape and the GO drain still ends
  its listen mark with a note ending in "GO" (the decision boundary the
  P9 analysis greps for).
* `sparring.py wait` TIMEOUT prints the elapsed seconds and the number of
  consecutive timeouts, so the next practice game measures the wait
  window (speed-plan 3.3).
* `latency.mark_path` is the path-based entry point (seats run without a
  Store); `latency.mark` keeps its API.
"""
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import latency                                  # noqa: E402
import sparring                                 # noqa: E402
from test_listen import ListenBase              # noqa: E402

SHAPE = {"ts", "phase", "edge", "gen", "note"}
LIVE = {"waitingFor": {"type": "or", "title": "Take action for action phase",
                       "options": [{"title": "Pass for this generation",
                                    "type": "option"}]},
        "thisPlayer": {"color": "red", "megacredits": 20, "terraformRating": 21},
        "players": [], "game": {"generation": 7, "phase": "action"}}
IDLE = {"waitingFor": None, "game": {"phase": "action", "generation": 7}}


class SeatBase(unittest.TestCase):
    """A seat named p1 whose store root is a temp dir (seats/p1/ under it)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._patch = mock.patch.object(sparring, "SEATS_ROOT", self.root)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self.tmp.cleanup()

    def marks(self, pid="p1"):
        return latency.read_marks(self.root / "seats" / pid / latency.FILENAME)

    def run_main(self, *argv, get=None, send=None):
        """Run the CLI against a fake AppClient: `get` answers /api/player,
        `send` takes the response. The real get_player/send run — only the
        HTTP client is replaced."""
        buf = io.StringIO()
        patches = [mock.patch("sys.argv", ["sparring.py", *argv]),
                   mock.patch("sys.stdout", buf)]
        if get is not None or send is not None:
            fake = mock.Mock()
            fake.send = send or (lambda pid, r: {})
            fake.player = get or (lambda pid: LIVE)
            patches.append(mock.patch.object(sparring, "client", lambda: fake))
        for p in patches:
            p.start()
        try:
            code = sparring.main()
        finally:
            for p in reversed(patches):
                p.stop()
        return code, buf.getvalue()


class TestMarkPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "seats" / "pX"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_the_advisor_shape_and_creates_the_folder(self):
        p = self.dir / latency.FILENAME
        e = latency.mark_path(p, "listen", "end", note="GO", gen=3)
        self.assertEqual(set(e), SHAPE)
        line = json.loads(p.read_text().splitlines()[0])
        self.assertEqual(line, e)
        self.assertEqual(line["gen"], 3)
        self.assertEqual(line["note"], "GO")

    def test_gen_falls_back_to_the_sibling_game_json(self):
        self.dir.mkdir(parents=True)
        (self.dir / "game.json").write_text(json.dumps({"generation": 5}))
        e = latency.mark_path(self.dir / latency.FILENAME, "execute", "start")
        self.assertEqual(e["gen"], 5)
        e = latency.mark_path(self.dir / latency.FILENAME, "execute", "end")
        self.assertEqual(e["gen"], 5)

    def test_no_game_json_means_gen_none(self):
        e = latency.mark_path(self.dir / latency.FILENAME, "other", "start")
        self.assertIsNone(e["gen"])

    def test_refuses_unknown_phase_or_edge(self):
        with self.assertRaises(ValueError):
            latency.mark_path(self.dir / latency.FILENAME, "lunch", "start")
        with self.assertRaises(ValueError):
            latency.mark_path(self.dir / latency.FILENAME, "listen", "middle")

    def test_seat_path_is_seats_pid_latency(self):
        self.assertEqual(latency.seat_path("p9", root=self.tmp.name),
                         Path(self.tmp.name) / "seats" / "p9" / latency.FILENAME)

    def test_digest_reads_a_seat_file_the_same_way(self):
        p = self.dir / latency.FILENAME
        latency.mark_path(p, "listen", "start", gen=1)
        latency.mark_path(p, "listen", "end", note="GO", gen=1)
        latency.mark_path(p, "execute", "start", gen=1)
        latency.mark_path(p, "execute", "end", note="send or", gen=1)
        d = latency.digest(p)
        self.assertEqual(d["marks"], 4)
        self.assertEqual(d["phases"]["listen"]["count"], 1)
        self.assertEqual(d["phases"]["execute"]["count"], 1)


class TestSeatWaitMarks(SeatBase):
    def test_wait_marks_listen_start_and_go_end_in_the_seat_store(self):
        code, out = self.run_main("wait", "p1", get=lambda pid: LIVE)
        self.assertEqual(code, 0)
        marks = self.marks()
        self.assertEqual([(m["phase"], m["edge"]) for m in marks],
                         [("listen", "start"), ("listen", "end")])
        for m in marks:
            self.assertEqual(set(m), SHAPE)
            self.assertIsInstance(m["ts"], float)
        self.assertEqual(marks[-1]["gen"], 7)          # from the view, not a file
        self.assertTrue(marks[-1]["note"].endswith("GO"), marks[-1])

    def test_wait_marks_land_under_the_pid_not_the_advisor_state(self):
        self.run_main("wait", "p2", get=lambda pid: LIVE)
        self.assertTrue((self.root / "seats" / "p2" / latency.FILENAME).exists())
        self.assertFalse((self.root / "state").exists())
        self.assertEqual(self.marks("p1"), [])

    def test_wait_scope_end_and_game_end_are_noted(self):
        over = {"waitingFor": None, "game": {"phase": "end", "generation": 12}}
        self.run_main("wait", "p1", get=lambda pid: over)
        self.assertEqual(self.marks()[-1]["note"], "GAME ENDED")
        later = dict(LIVE, game={"generation": 9, "phase": "action"})
        self.run_main("wait", "p1", "--until-gen", "8", get=lambda pid: later)
        self.assertEqual(self.marks()[-1]["note"], "SCOPE END")


class TestSeatWaitTimeout(SeatBase):
    def _timeout(self):
        with mock.patch.object(sparring, "wait_for_turn", return_value=None):
            return self.run_main("wait", "p1", "--timeout", "280",
                                 get=lambda pid: IDLE)

    def test_timeout_line_carries_elapsed_seconds_and_the_count(self):
        code, out = self._timeout()
        self.assertEqual(code, 2)
        self.assertIn("TIMEOUT", out)
        self.assertRegex(out, r"after \d+ s")
        self.assertRegex(out, r"timeout #1\b")
        self.assertIn("re-run wait", out)

    def test_consecutive_timeouts_count_up_and_a_go_resets(self):
        self._timeout()
        code, out = self._timeout()
        self.assertRegex(out, r"timeout #2\b")
        m = self.marks()
        self.assertEqual(m[-1]["phase"], "listen")
        self.assertEqual(m[-1]["edge"], "end")
        self.assertTrue(m[-1]["note"].startswith("TIMEOUT"), m[-1])
        self.run_main("wait", "p1", get=lambda pid: LIVE)          # GO
        code, out = self._timeout()
        self.assertRegex(out, r"timeout #1\b")

    def test_timeout_elapsed_is_measured_not_the_flag(self):
        clock = iter([100.0, 163.0])
        with mock.patch.object(sparring, "wait_for_turn", return_value=None), \
             mock.patch.object(sparring, "_now", lambda: next(clock)):
            code, out = self.run_main("wait", "p1", "--timeout", "280",
                                      get=lambda pid: IDLE)
        self.assertIn("after 63 s", out)


class TestSeatSendMarks(SeatBase):
    def test_send_marks_execute_start_and_end(self):
        sent = []
        code, out = self.run_main(
            "send", "p1", json.dumps({"type": "option"}),
            get=lambda pid: LIVE, send=lambda pid, r: sent.append(r) or {})
        self.assertEqual(code, 0)
        self.assertEqual(sent, [{"type": "option"}])
        marks = self.marks()
        self.assertEqual([(m["phase"], m["edge"]) for m in marks],
                         [("execute", "start"), ("execute", "end")])
        self.assertEqual(set(marks[0]), SHAPE)
        self.assertIn("option", marks[-1]["note"])

    def test_a_verb_that_sends_marks_too(self):
        sent = []
        code, out = self.run_main(
            "pass", "p1", get=lambda pid: LIVE,
            send=lambda pid, r: sent.append(r) or {})
        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 1)
        marks = self.marks()
        self.assertEqual([m["phase"] for m in marks], ["execute", "execute"])
        self.assertEqual(marks[-1]["gen"], 7)

    def test_send_gen_comes_from_the_last_view_seen(self):
        gen11 = dict(LIVE, game={"generation": 11, "phase": "action"})
        self.run_main("pass", "p1", get=lambda pid: gen11,
                      send=lambda pid, r: {})
        self.assertEqual([m["gen"] for m in self.marks()], [11, 11])

    def test_a_failed_send_still_closes_the_mark(self):
        from appapi import AppError

        def boom(pid, r):
            raise AppError(500, "server", "boom")
        code, out = self.run_main("send", "p1", json.dumps({"type": "option"}),
                                  get=lambda pid: LIVE, send=boom)
        self.assertEqual(code, 1)
        marks = self.marks()
        self.assertEqual([m["edge"] for m in marks], ["start", "end"])
        self.assertIn("error", marks[-1]["note"])

    def test_marks_never_break_play(self):
        """A store that cannot be written must not stop the seat's move."""
        sent = []
        with mock.patch.object(sparring, "SEATS_ROOT",
                               self.root / "no-such-file.txt"):
            (self.root / "no-such-file.txt").write_text("a file, not a dir")
            code, out = self.run_main(
                "send", "p1", json.dumps({"type": "option"}),
                get=lambda pid: LIVE, send=lambda pid, r: sent.append(r) or {})
        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 1)


class TestAdvisorMarksUnchanged(ListenBase):
    """The advisor's file is the reference shape; the GO drain's note still
    ends in "GO" — the decision boundary the P9 analysis greps for."""

    def test_go_drain_note_ends_in_go_and_shape_is_intact(self):
        self.reveal_to(16)
        self.app.waiting = "Take your first action"
        code, out = self.main("once")
        self.assertEqual(code, 30)
        marks = latency.read_marks(latency.path_for(self.store))
        self.assertEqual([(m["phase"], m["edge"]) for m in marks],
                         [("listen", "start"), ("listen", "end")])
        for m in marks:
            self.assertEqual(set(m), SHAPE)
        self.assertTrue(marks[-1]["note"].endswith(" GO"), marks[-1])
        self.assertRegex(marks[-1]["note"], r"^\d+ entries GO$")

    def test_non_go_drain_has_no_go_in_the_note(self):
        self.reveal_to(16)
        self.main("once")
        marks = latency.read_marks(latency.path_for(self.store))
        self.assertNotIn("GO", marks[-1]["note"])

    def test_seat_file_and_advisor_file_digest_identically(self):
        self.reveal_to(16)
        self.app.waiting = "Take your first action"
        self.main("once")
        adv = latency.read_marks(latency.path_for(self.store))
        seat = self.store.state_dir.parent / "seats" / "pZ" / latency.FILENAME
        for m in adv:
            latency.mark_path(seat, m["phase"], m["edge"], note=m["note"],
                              gen=m["gen"])
        a, s = latency.digest(latency.path_for(self.store)), latency.digest(seat)
        self.assertEqual(a["marks"], s["marks"])
        self.assertEqual(set(a["phases"]), set(s["phases"]))
        self.assertEqual([set(m) for m in adv],
                         [set(m) for m in latency.read_marks(seat)])


class TestListenerPassesTheLineGeneration(ListenBase):
    """D3: `Engine.use_action(gen=…)` absorbs a drained action line older
    than the tracker's generation. The listener must pass the SOURCE
    generation of every drained action line through."""

    def test_drained_action_line_carries_its_generation(self):
        from test_listen import LINES
        self.assertEqual(LINES[49], "Diana used Equatorial Magnetizer action")
        self.reveal_to(49)
        self.drain()
        L = self.listener()
        with mock.patch.object(L.eng, "use_action",
                               return_value="Action used: stub") as ua:
            self.reveal_to(50)
            self.drain(L)
        self.assertTrue(ua.called, "the drained action line never reached use_action")
        self.assertEqual(ua.call_args.kwargs.get("gen"), 1)


if __name__ == "__main__":
    unittest.main()
