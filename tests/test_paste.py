"""W2-B item 1: `listen.py paste` — pasted app-LOG text through the SAME
parse/apply/feed lane as `once` (per-line replay apply, one feed entry per
line, hard-trigger verdicts), with a paste-specific cursor so re-pasting an
overlapping window applies nothing twice.

Screenshot mode is the point: NO appUrl configured, no network. The dedup
anchors on a stored consumed-line list: a paste that appears verbatim
anywhere in the consumed stream is an exact repeat (nothing applied);
otherwise the longest suffix of the consumed stream that is a prefix of
the paste marks where the new lines start."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import applog_parser as P                       # noqa: E402
import listen                                   # noqa: E402
import replay_applog as R                       # noqa: E402
import triage                                   # noqa: E402
from tmlib import Engine, Store                 # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "replay-4p-wgt"
LINES = FIXTURE.joinpath("applog.txt").read_text().splitlines()[:80]
PLAYERS = ["Diana", "Anna", "Carl", "Ben"]


def _setup() -> dict:
    """The fixture setup in SCREENSHOT mode: app-online, NO appUrl, no
    playerId — pasted LOG text is the only opponent channel."""
    s = json.loads((FIXTURE / "setup.json").read_text())
    s["gameMode"] = "app-online"
    s.pop("appUrl", None)
    return s


class PasteBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root, state_dir=root / "state")
        self.store.init(_setup())
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def paste(self, lines) -> tuple[int, str]:
        """Run the CLI verb with the text in a --file (a fresh process-like
        invocation each time: cursors must live in files, not memory)."""
        f = Path(self.tmp.name) / "paste.txt"
        f.write_text("\n".join(lines) + "\n")
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = listen.main(["--state", str(self.store.state_dir),
                                "paste", "--file", str(f)])
        return code, buf.getvalue()

    def feed(self) -> list[dict]:
        return triage.read_feed(triage.feed_path(self.store))

    def game(self) -> dict:
        return self.store.load_game()

    def pool(self, name: str) -> dict:
        g = self.game()
        return g["me"] if g["me"]["name"] == name else g["opponents"][name]

    def reference(self, lines) -> dict:
        """The regression replay of the same lines — the paste lane must
        land on the same state."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ref = Store(tmp.name, state_dir=Path(tmp.name) / "state")
        ref.init(_setup())
        rp = R.Replayer(Engine(ref), R.Report(), verbose=False)
        for b in P.group_blocks(P.parse_log("\n".join(lines), PLAYERS)):
            rp.block(b)
        return ref.load_game()


class TestPasteIngest(PasteBase):
    def test_paste_needs_no_app_url(self):
        self.assertNotIn("appUrl", self.store.load_setup())
        code, out = self.paste(LINES[:16])
        self.assertEqual(code, 10)                    # events applied
        self.assertIn("logged: ", out)

    def test_same_lane_as_once_feed_schema_and_numbering(self):
        self.paste(LINES[:16])
        feed = self.feed()
        self.assertEqual([e["raw"] for e in feed],
                         [l for l in LINES[:16] if not l.startswith("Good luck")])
        self.assertEqual([e["line"] for e in feed],
                         [1, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
        for key in ("ts", "gen", "line", "actor", "kind", "raw", "event",
                    "applied", "error", "trigger", "reasons", "handled"):
            self.assertIn(key, feed[1])

    def test_engine_state_matches_the_replay(self):
        self.paste(LINES[:30])
        want = self.reference(LINES[:30])
        got = self.game()
        self.assertEqual(got["globals"], want["globals"])
        for name in PLAYERS:
            w = want["me"] if want["me"]["name"] == name else want["opponents"][name]
            g = self.pool(name)
            self.assertEqual((name, g["resources"]), (name, w["resources"]))
            self.assertEqual((name, g["production"]), (name, w["production"]))

    def test_trigger_verdicts_and_judgment_banner(self):
        code, out = self.paste(LINES[:80])
        self.assertIn("TRIGGER:", out)
        self.assertIn("JUDGMENT NEEDED", out)
        e = next(e for e in self.feed() if e["kind"] == "stole")
        self.assertTrue(e["trigger"])
        self.assertTrue(any("attack" in x for x in e["reasons"]))

    def test_generation_line_runs_produce(self):
        self.paste(LINES[:53])
        g = self.game()
        self.assertEqual(g["generation"], 1)
        mc = g["me"]["resources"]["mc"]
        self.paste(LINES[:55])                        # overlapping window
        g = self.game()
        self.assertEqual(g["generation"], 2)
        self.assertEqual(g["me"]["resources"]["mc"],
                         mc + g["me"]["tr"] + g["me"]["production"]["mc"])

    def test_physical_mode_is_refused(self):
        setup = self.store.load_setup()
        setup["gameMode"] = "physical"
        Store._write_json(self.store.setup_path, setup)
        code, _out = self.paste(LINES[:5])
        self.assertEqual(code, 1)

    def test_stdin_is_the_default_channel(self):
        text = "\n".join(LINES[:16]) + "\n"
        with mock.patch.object(sys, "stdin", io.StringIO(text)), \
                contextlib.redirect_stdout(io.StringIO()) as buf:
            code = listen.main(["--state", str(self.store.state_dir), "paste"])
        self.assertEqual(code, 10)
        self.assertEqual(len(self.feed()), 12)
        self.assertIn("logged: ", buf.getvalue())


class TestPasteDedup(PasteBase):
    def test_overlapping_window_applies_only_the_new_lines(self):
        self.paste(LINES[:30])
        n = len(self.feed())
        code, out = self.paste(LINES[20:50])          # 10 old + 20 new
        self.assertEqual(code, 10)
        feed = self.feed()
        self.assertEqual([e["raw"] for e in feed[n:]],
                         [l for l in LINES[30:50] if not l.startswith("Good luck")])
        self.assertEqual(len({e["line"] for e in feed}), len(feed))
        want = self.reference(LINES[:50])
        for name in PLAYERS:
            w = want["me"] if want["me"]["name"] == name else want["opponents"][name]
            self.assertEqual((name, self.pool(name)["resources"]),
                             (name, w["resources"]))

    def test_exact_repeat_applies_nothing(self):
        self.paste(LINES[:30])
        state = json.dumps(self.game(), sort_keys=True)
        n = len(self.feed())
        code, out = self.paste(LINES[:30])
        self.assertEqual(code, 0)                     # nothing new
        self.assertEqual(len(self.feed()), n)
        self.assertEqual(json.dumps(self.game(), sort_keys=True), state)
        self.assertIn("already consumed", out)

    def test_exact_repeat_of_an_older_window_applies_nothing(self):
        self.paste(LINES[:30])
        state = json.dumps(self.game(), sort_keys=True)
        code, _out = self.paste(LINES[10:20])         # a window from the middle
        self.assertEqual(code, 0)
        self.assertEqual(json.dumps(self.game(), sort_keys=True), state)

    def test_gap_applies_everything_and_says_so(self):
        self.paste(LINES[:16])
        n = len(self.feed())
        code, out = self.paste(LINES[20:26])          # lines 17-20 never pasted
        self.assertEqual(code, 10)
        self.assertEqual(len(self.feed()), n + 6)
        self.assertIn("no overlap", out)

    def test_legitimately_repeated_line_across_the_boundary(self):
        # the app log can print the SAME text twice; a content hash would
        # eat the second one. The suffix-anchor consumes only the overlap.
        self.paste(["Generation 1", "Carl played ThorGate", "Carl gained 2 steel"])
        self.assertEqual(self.pool("Carl")["resources"]["steel"], 2)
        code, _out = self.paste(["Carl gained 2 steel", "Carl gained 2 steel"])
        self.assertEqual(code, 10)
        self.assertEqual(self.pool("Carl")["resources"]["steel"], 4)

    def test_paste_cursor_survives_process_death(self):
        self.paste(LINES[:30])
        cur = json.loads((self.store.state_dir / listen.PASTE_CURSOR_FILE)
                         .read_text())
        self.assertEqual(cur["consumed"],
                         [l.strip() for l in LINES[:30] if l.strip()])


class TestPasteOwnLines(PasteBase):
    def test_own_action_already_applied_reconciles_not_double_applies(self):
        # the tracker already holds my play (executed via the app + logged);
        # the pasted log echoes it — reuse the `once` machinery, never a
        # second charge (the triple double-count failure this lane kills)
        self.eng.corp("Diana", "Teractor", mc=60)
        self.eng.hand_add(["Business Contacts"])
        self.eng.play("Diana", "Business Contacts")
        mc = self.game()["me"]["resources"]["mc"]
        code, out = self.paste(
            ["Generation 1", "Diana played Teractor",
             "Diana played Business Contacts", "Diana drew 2 card(s)",
             "You drew Artificial Photosynthesis,GHG Producing Bacteria"])
        self.assertEqual(self.game()["me"]["resources"]["mc"], mc)
        self.assertIn("own action, already applied", out)
        self.assertIn("Artificial Photosynthesis", self.game()["me"]["hand"])

    def test_own_action_not_reflected_is_absorbed(self):
        code, out = self.paste(["Generation 1", "Diana played Teractor"])
        self.assertEqual(self.game()["me"]["corporation"], "Teractor")
        self.assertIn("own action absorbed", out)


class TestPasteBurst(PasteBase):
    def test_plan_is_printable_between_every_pair_of_half_turn_pastes(self):
        # the protocol's acceptance shape: a burst of half-turn windows,
        # and the standing plan block renders between every pair — "my
        # turn but no plan on screen" is structurally impossible
        import planlib
        planlib.set_plan(self.store, {
            "threats": "Anna is 1 step from Builder",
            "exit": "card VP; repeatable: greenery from plant production",
            "steps": [{"id": "1a", "summary": "hold cash",
                       "volatility": "safe", "events": []},
                      {"id": "1b", "summary": "pass", "volatility": "recheck",
                       "passGate": True, "events": []}]})
        cuts = [10, 16, 21, 30, 40, 53, 57, 66, 80]     # half-turn windows
        prev = 0
        for cut in cuts:
            code, _out = self.paste(LINES[max(0, prev - 3):cut])  # overlap 3
            self.assertIn(code, (0, 10))
            block = planlib.render(self.store)
            self.assertIn("▶️ NEXT 1a", block)
            self.assertIn("🎯 EXIT:", block)
            prev = cut
        want = self.reference(LINES[:80])
        self.assertEqual(self.game()["globals"], want["globals"])


class TestPasteHelpers(unittest.TestCase):
    def test_overlap_function(self):
        f = listen.paste_overlap
        self.assertEqual(f([], ["a", "b"]), 0)
        self.assertEqual(f(["a", "b", "c"], ["b", "c", "d"]), 2)   # overlap
        self.assertEqual(f(["a", "b", "c"], ["a", "b", "c"]), 3)   # repeat
        self.assertEqual(f(["a", "b", "c", "d"], ["b", "c"]), 2)   # older window
        self.assertEqual(f(["a", "b", "c"], ["x", "y"]), 0)        # gap
        self.assertEqual(f(["a", "b"], ["b", "b"]), 1)             # legit repeat


if __name__ == "__main__":
    unittest.main()
