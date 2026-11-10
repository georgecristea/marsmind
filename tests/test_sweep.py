"""P3 lane 2: `advise.py --sweep` — the COMPACT brief for one judgment
sweep (feed since the cursor, pending triggers, races, plan threats + open
steps, menu line). Not the KB, not the full state dump. The cursor
(state/sweep-cursor.json) advances after printing; --peek does not."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine
from test_new_game import SETUP
import advise
import applog_parser as P
import latency
import planlib
import triage

PLAYERS = [p["name"] for p in SETUP["players"]]
THREATS = "Anna is 1 step from Builder; Felix leads Banker"
EXIT = "test exit: card VP; repeatable: greenery from plant production"
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "advise.py"
KB = Path(__file__).resolve().parent.parent / "strategy"


def entry(line: int, raw: str, gen: int = 1) -> dict:
    return triage.new_entry(P.parse_line(raw, PLAYERS), line=line, gen=gen,
                            raw=raw, ts="2026-01-01T00:00:00")


class SweepCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        eng = Engine(self.store)
        eng.res("Zed", "mc", +40)
        eng.hand_add(["Comet"])
        self.feed = triage.feed_path(self.store)
        triage.write_feed(self.feed, [
            entry(1, "Felix gained 2 megacredits"),
            entry(2, "Anna claimed Builder milestone"),
            entry(3, "Zed lost 3 titanium because of Anna"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self):
        planlib.set_plan(self.store, {"threats": THREATS, "exit": EXIT, "steps": [
            {"id": "1a", "summary": "Play Comet", "volatility": "safe",
             "events": [{"method": "play", "args": ["Zed", "Comet"],
                         "kwargs": {"cost": 18}}]},
            {"id": "1b", "summary": "pass", "volatility": "recheck",
             "passGate": True, "events": []}]}, draft=True)

    def cursor(self):
        p = self.root / "state" / advise.SWEEP_CURSOR
        return json.loads(p.read_text())["line"] if p.exists() else 0

    def sweep(self, **kw):
        return advise.build_sweep(self.store, **kw)


class TestSweepContent(SweepCase):
    def test_header_and_feed_lines_with_reasons(self):
        self.draft()
        out = self.sweep()
        self.assertTrue(out.startswith("# SWEEP"))
        self.assertIn("generation 1", out)
        self.assertIn("first player Anna", out)
        # every new feed line appears once, trigger reasons attached
        self.assertIn("#1 Felix gained", out)
        self.assertIn("#2 Anna claimed", out)
        self.assertIn("milestone: Anna claimed Builder", out)
        self.assertIn("attack: Anna removed 3 titanium from you", out)

    def test_pending_races_plan_and_menu_present(self):
        self.draft()
        out = self.sweep()
        self.assertIn("PENDING TRIGGERS", out)
        self.assertIn("## RACES", out)
        self.assertIn("RACE ALERT", out)
        self.assertIn(THREATS, out)                 # the plan's threats block
        self.assertIn("1a", out); self.assertIn("Play Comet", out)
        self.assertIn("DRAFT", out)                 # open steps of the draft
        self.assertIn("available: ", out)           # menu one-liner

    def test_open_steps_only_live_plan(self):
        self.draft()
        planlib.promote(self.store)
        planlib.mark_done(self.store, "1a")
        out = self.sweep()
        self.assertNotIn("Play Comet", out)         # executed step omitted
        self.assertIn("1b", out)
        self.assertNotIn("DRAFT", out)

    def test_not_the_kb_not_the_state_dump(self):
        self.draft()
        out = self.sweep()
        self.assertNotIn("STRATEGY KNOWLEDGE BASE", out)
        self.assertNotIn("Quantified Guide", out)
        self.assertNotIn("## OPPONENTS", out)
        self.assertNotIn("OUTPUT CONTRACT", out)
        self.assertNotIn("## ME —", out)

    def test_no_plan_and_no_feed_are_stated_not_errors(self):
        self.feed.unlink()
        out = self.sweep()
        self.assertIn("no plan", out.lower())
        self.assertIn("no feed", out.lower())

    def test_conclude_names_live_when_the_plan_is_live(self):
        # P8 #9: on the player's own turn the plan is live; `planlib.py
        # patch` without --live used to refuse, so the sweep concluded
        # into an error and the patch silently never landed.
        self.draft()
        planlib.promote(self.store)
        conclude = self.sweep().split("## CONCLUDE")[1]
        self.assertIn("planlib.py patch --live", conclude)

    def test_conclude_has_no_live_flag_for_a_draft(self):
        self.draft()
        conclude = self.sweep().split("## CONCLUDE")[1]
        self.assertIn("planlib.py patch", conclude)
        self.assertNotIn("--live", conclude)

    def test_whose_turn_label_passes_through(self):
        out = self.sweep(whose="opponent 2/2 (Felix)")
        self.assertIn("turn: opponent 2/2 (Felix)", out)


class TestSweepCursor(SweepCase):
    def test_cursor_advances_and_second_sweep_shows_only_new_lines(self):
        self.assertEqual(self.cursor(), 0)
        self.sweep()
        self.assertEqual(self.cursor(), 3)
        triage.write_feed(self.feed, triage.read_feed(self.feed)
                          + [entry(4, "Felix played Comet")])
        out = self.sweep()
        feed_section = out.split("## PENDING")[0]
        self.assertIn("#4 Felix played", feed_section)
        self.assertNotIn("#2 Anna claimed", feed_section)   # shown once, ever
        self.assertIn("since #3", out)
        self.assertEqual(self.cursor(), 4)

    def test_peek_does_not_advance(self):
        out = self.sweep(peek=True)
        self.assertIn("#2 Anna claimed", out)
        self.assertEqual(self.cursor(), 0)
        self.assertFalse(planlib.sweep_flag_path(self.store).exists())

    def test_sweep_sets_inflight_flag_and_is_timed(self):
        self.sweep()
        flag = planlib.sweep_flag_path(self.store)
        self.assertTrue(flag.exists())
        info = json.loads(flag.read_text())
        self.assertEqual(info["lines"], [1, 2, 3])
        marks = latency.read_marks(latency.path_for(self.store))
        self.assertEqual([(m["phase"], m["edge"]) for m in marks],
                         [("sweep", "start"), ("sweep", "end")])

    def test_pending_triggers_still_listed_after_cursor_passed_them(self):
        self.sweep()
        out = self.sweep()                       # nothing new in the feed
        self.assertIn("(none)", out)
        self.assertIn("#2 Anna claimed", out)    # still pending, still shown


class TestSweepCLI(SweepCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "--root",
                               str(self.root), "--kb", str(KB), *args],
                              capture_output=True, text=True)

    def test_sweep_flag(self):
        r = self.cli("--sweep")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("# SWEEP"))
        self.assertNotIn("Quantified Guide", r.stdout)
        self.assertEqual(self.cursor(), 3)

    def test_peek_flag(self):
        r = self.cli("--sweep", "--peek")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.cursor(), 0)

    def test_peek_requires_sweep(self):
        r = self.cli("--peek")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
