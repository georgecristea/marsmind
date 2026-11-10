"""scripts/triage.py — the hard-trigger classifier of the event feed
(lane 1 of the judgment design): pure functions over one feed entry +
game/setup/plan, an annotate/pending/handle CLI over state/feed.jsonl.

Every trigger class gets one table row built from a REAL fixture line
(tests/fixtures/replay-4p-wgt/applog.txt, me = Diana); twenty plain lines
assert silence; the 🔁-intersection and race-threshold cases plant state.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import applog_parser as P
import triage
from tmlib import Store

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "replay-4p-wgt"
SETUP = json.loads((FIX / "setup.json").read_text())
PLAYERS = [p["name"] for p in SETUP["players"]]
LINES = (FIX / "applog.txt").read_text().splitlines()


def fixture_entry(n: int, gen: int = 5) -> dict:
    """Feed entry for fixture line n (1-based), parsed by applog_parser."""
    raw = LINES[n - 1]
    ev = P.parse_line(raw, PLAYERS)
    return triage.new_entry(ev, line=n, gen=gen, raw=raw, ts="2026-01-01T00:00:00")


class TriageBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.game = self.store.load_game()
        self.setup = self.store.load_setup()

    def tearDown(self):
        self.tmp.cleanup()

    def classify(self, n, plan=None, game=None, game_before=None):
        return triage.classify(fixture_entry(n), game or self.game,
                               self.setup, plan, game_before=game_before)


class TestEntrySchema(TriageBase):
    def test_new_entry_has_every_documented_field(self):
        e = fixture_entry(21)
        for key in ("ts", "gen", "line", "actor", "kind", "raw", "event",
                    "applied", "error", "trigger", "reasons", "handled"):
            self.assertIn(key, e)
        self.assertEqual(e["actor"], "Carl")
        self.assertEqual(e["kind"], "placed")
        self.assertEqual(e["line"], 21)
        self.assertFalse(e["trigger"]); self.assertEqual(e["reasons"], [])
        self.assertFalse(e["handled"])
        self.assertTrue(e["applied"]); self.assertIsNone(e["error"])

    def test_generation_line_has_no_actor(self):
        e = fixture_entry(54)
        self.assertIsNone(e["actor"])
        self.assertEqual(e["kind"], "generation")


class TestTriggerClasses(TriageBase):
    """One row per trigger class, each from a real fixture line."""

    def test_table(self):
        table = [
            # (line, class, substring expected in a reason)
            (213, "a-attack-resources", "Carl"),          # Diana lost 3 titanium because of Carl
            (217, "a-attack-production", "heat production"),  # Diana lost 1 heat prod because of Carl
            (65, "a-steal-production", "Carl"),            # Carl stole 1 energy production from Diana
            (328, "b-milestone-claim", "Builder"),         # Diana claimed Builder milestone
            (93, "b-award-funded", "Banker"),              # Ben funded Banker award
            (53, "c-wgt-temperature", "temperature"),      # Anna acted as WGT ... temperature
            (21, "c-ocean-placed", "oceans"),              # Carl placed ocean tile at 63
            (77, "c-greenery-placed", "oxygen"),           # Ben placed greenery tile at 32
            (567, "c-standard-asteroid", "temperature"),   # Carl used Asteroid:SP
            (197, "c-card-raises-temperature", "temperature"),  # Diana played Big Asteroid
            (55, "f-first-player", "Carl"),                # First player this generation is Carl
            (54, "f-generation", "generation"),            # Generation 2
        ]
        for line, label, needle in table:
            with self.subTest(line=line, label=label):
                trig, reasons = self.classify(line)
                self.assertTrue(trig, f"{label}: line {line} should trigger: "
                                      f"{LINES[line - 1]!r}")
                self.assertTrue(reasons)
                self.assertIn(needle, " ".join(reasons))

    def test_attack_on_an_opponent_is_not_my_attack(self):
        # Ben lost 4 plants because of Diana — Diana is me: not an attack ON me
        trig, reasons = self.classify(200)
        self.assertFalse(any(r.startswith("attack") for r in reasons))

    def test_steal_from_an_opponent_by_me_is_silent(self):
        trig, reasons = self.classify(117)     # Diana stole 3 M€ from Ben
        self.assertFalse(trig, reasons)

    def test_global_step_reason_names_clock_and_windows(self):
        g = json.loads(json.dumps(self.game))
        g["globals"]["temperature"] = -14
        g["me"]["hand"] = ["Arctic Algae", "Sponsors"]
        trig, reasons = self.classify(53, game=g)     # WGT temperature
        text = " ".join(reasons)
        self.assertTrue(trig)
        self.assertIn("steps left", text)
        self.assertIn("Arctic Algae", text)          # max -12°C window
        self.assertNotIn("Sponsors", text)

    def test_seven_plants_asteroid_target(self):
        g = json.loads(json.dumps(self.game))
        g["opponents"]["Ben"]["resources"]["plants"] = 7
        trig, reasons = self.classify(78, game=g)     # Ben gained 2 plants
        self.assertTrue(trig)
        self.assertIn("7", " ".join(reasons))
        self.assertTrue(any("asteroid" in r.lower() for r in reasons))

    def test_plants_below_seven_stay_silent(self):
        g = json.loads(json.dumps(self.game))
        g["opponents"]["Ben"]["resources"]["plants"] = 4
        trig, reasons = self.classify(78, game=g)
        self.assertFalse(trig, reasons)


class TestSilence(TriageBase):
    QUIET = [8, 10, 11, 13, 15, 17, 19, 25, 27, 29, 30, 31, 32, 33, 34, 35,
             36, 38, 39, 40]

    def test_twenty_plain_lines_are_silent(self):
        self.assertEqual(len(self.QUIET), 20)
        for n in self.QUIET:
            with self.subTest(line=n, raw=LINES[n - 1]):
                trig, reasons = self.classify(n)
                self.assertFalse(trig, f"line {n} {LINES[n - 1]!r}: {reasons}")
                self.assertEqual(reasons, [])

    def test_unknown_and_ignore_lines_are_silent(self):
        for n in (2, 583, 595):
            trig, reasons = self.classify(n)
            self.assertFalse(trig, reasons)


PLAN_44 = {
    "generation": 9, "draft": False, "threats": "Ben Landlord race",
    "steps": [
        {"id": "1a", "summary": "Play Giant Ice Asteroid; ocean on 44",
         "volatility": "recheck", "mapHighlight": "44", "cue": "blue tile on 44",
         "events": [{"method": "play", "args": ["Diana", "Giant Ice Asteroid"]},
                    {"method": "place", "args": ["Diana", "ocean", "44"]}],
         "done": False},
        {"id": "1b", "summary": "Sell Patents ×1", "volatility": "safe",
         "events": [{"method": "standard", "args": ["Diana", "sell_patents"]}],
         "done": False},
        {"id": "2a", "summary": "claim Builder", "volatility": "recheck",
         "cue": "your marker on Builder",
         "events": [{"method": "milestone", "args": ["Diana", "Builder"]}],
         "done": False},
        {"id": "3a", "summary": "pass", "volatility": "safe", "passGate": True,
         "events": [], "done": False},
    ],
}


class TestPlanIntersection(TriageBase):
    def test_opponent_ocean_on_my_planned_hex_triggers(self):
        # Ben placed ocean tile at 13 (line 178) — rewrite the hex to 44
        ev = P.parse_line("Ben placed ocean tile at 44", PLAYERS)
        entry = triage.new_entry(ev, line=999, gen=9,
                                 raw="Ben placed ocean tile at 44")
        trig, reasons = triage.classify(entry, self.game, self.setup, PLAN_44)
        self.assertTrue(trig)
        self.assertTrue(any("1a" in r and "44" in r for r in reasons), reasons)

    def test_ocean_elsewhere_only_triggers_the_global_step(self):
        ev = P.parse_line("Ben placed ocean tile at 13", PLAYERS)
        entry = triage.new_entry(ev, line=998, gen=9, raw="Ben placed ocean tile at 13")
        trig, reasons = triage.classify(entry, self.game, self.setup, PLAN_44)
        self.assertTrue(trig)
        self.assertFalse(any("plan" in r for r in reasons), reasons)

    def test_grid_ref_in_plan_matches_numeric_space(self):
        plan = json.loads(json.dumps(PLAN_44))
        import tmlib
        plan["steps"][0]["events"][1]["args"][2] = tmlib.space_to_grid("44")
        plan["steps"][0]["mapHighlight"] = None
        ev = P.parse_line("Ben placed ocean tile at 44", PLAYERS)
        entry = triage.new_entry(ev, line=997, gen=9, raw="Ben placed ocean tile at 44")
        trig, reasons = triage.classify(entry, self.game, self.setup, plan)
        self.assertTrue(any("1a" in r for r in reasons), reasons)

    def test_card_named_in_recheck_step(self):
        ev = P.parse_line("Ben played Giant Ice Asteroid", PLAYERS)
        entry = triage.new_entry(ev, line=996, gen=9, raw="Ben played Giant Ice Asteroid")
        trig, reasons = triage.classify(entry, self.game, self.setup, PLAN_44)
        self.assertTrue(any("1a" in r and "Giant Ice Asteroid" in r for r in reasons), reasons)

    def test_done_or_safe_steps_do_not_intersect(self):
        plan = json.loads(json.dumps(PLAN_44))
        plan["steps"][0]["done"] = True
        ev = P.parse_line("Ben placed ocean tile at 44", PLAYERS)
        entry = triage.new_entry(ev, line=995, gen=9, raw="Ben placed ocean tile at 44")
        trig, reasons = triage.classify(entry, self.game, self.setup, plan)
        self.assertFalse(any("plan" in r for r in reasons), reasons)

    def test_race_metric_named_in_recheck_step(self):
        # 2a claims Builder; an opponent's building card moves the Builder metric
        ev = P.parse_line("Carl played Immigrant City", PLAYERS)
        entry = triage.new_entry(ev, line=994, gen=9, raw="Carl played Immigrant City")
        trig, reasons = triage.classify(entry, self.game, self.setup, PLAN_44)
        self.assertTrue(any("2a" in r and "Builder" in r for r in reasons), reasons)

    def test_draft_plan_counts_too(self):
        plan = json.loads(json.dumps(PLAN_44)); plan["draft"] = True
        ev = P.parse_line("Ben placed ocean tile at 44", PLAYERS)
        entry = triage.new_entry(ev, line=993, gen=9, raw="Ben placed ocean tile at 44")
        trig, reasons = triage.classify(entry, self.game, self.setup, plan)
        self.assertTrue(any("1a" in r for r in reasons), reasons)


class TestPlanCursorScoping(TriageBase):
    """P8 #14: a plan is composed at a moment in time. Feed lines OLDER
    than the plan are history the advisor already priced in — re-matching
    them against the new plan's step names/races produced 15-22 stale
    "plan:" triggers per generation. Own actions never disrupt my own plan."""

    def plan(self, **kw):
        p = json.loads(json.dumps(PLAN_44))
        p.update(kw)
        return p

    def entry(self, raw, line, gen):
        return triage.new_entry(P.parse_line(raw, PLAYERS), line=line, gen=gen,
                                raw=raw)

    def plan_reasons(self, entry, plan):
        _, reasons = triage.classify(entry, self.game, self.setup, plan)
        return [r for r in reasons if r.startswith("plan:")]

    def test_feed_line_older_than_the_plan_never_matches(self):
        e = self.entry("Ben played Giant Ice Asteroid", line=40, gen=1)
        self.assertEqual(self.plan_reasons(e, self.plan(feedCursor=500)), [])

    def test_feed_line_newer_than_the_plan_still_matches(self):
        e = self.entry("Ben played Giant Ice Asteroid", line=501, gen=9)
        self.assertTrue(any("1a" in r for r in
                            self.plan_reasons(e, self.plan(feedCursor=500))))

    def test_race_reason_from_an_old_line_is_dropped_too(self):
        # 2a claims Builder: a generation-1 building card must not re-arm it
        e = self.entry("Carl played Immigrant City", line=12, gen=1)
        self.assertEqual(self.plan_reasons(e, self.plan(feedCursor=500)), [])

    def test_generation_fallback_when_the_plan_has_no_cursor(self):
        plan = self.plan()                       # generation 9, no feedCursor
        old = self.entry("Ben placed ocean tile at 44", line=40, gen=1)
        new = self.entry("Ben placed ocean tile at 44", line=601, gen=9)
        self.assertEqual(self.plan_reasons(old, plan), [])
        self.assertTrue(any("1a" in r for r in self.plan_reasons(new, plan)))

    def test_my_own_action_is_never_a_plan_trigger(self):
        # Diana is me: executing my own step is not a disruption of it
        e = self.entry("Diana played Giant Ice Asteroid", line=501, gen=9)
        self.assertEqual(self.plan_reasons(e, self.plan(feedCursor=500)), [])

    def test_cursor_zero_keeps_every_line_in_scope(self):
        e = self.entry("Ben played Giant Ice Asteroid", line=3, gen=9)
        self.assertTrue(any("1a" in r for r in
                            self.plan_reasons(e, self.plan(feedCursor=0))))


class TestRequirementWindowWording(TriageBase):
    """P8 #8: a raise OPENS a `min` window and CLOSES a `max` one."""

    def hand(self, cards):
        g = json.loads(json.dumps(self.game))
        g["me"]["hand"] = list(cards)
        return g

    def test_min_window_opens_on_a_raise(self):
        # line 21: Carl placed ocean tile at 63; Capital needs min 4 oceans
        _, reasons = self.classify(21, game=self.hand(["Capital"]))
        text = " ".join(reasons)
        self.assertIn("windows opening: Capital", text)
        self.assertNotIn("windows closing", text)

    def test_max_window_closes_on_a_raise(self):
        # Dust Seals: max 3 oceans
        _, reasons = self.classify(21, game=self.hand(["Dust Seals"]))
        text = " ".join(reasons)
        self.assertIn("windows closing: Dust Seals", text)
        self.assertNotIn("windows opening", text)

    def test_both_kinds_are_named_separately(self):
        _, reasons = self.classify(21, game=self.hand(["Capital", "Dust Seals"]))
        text = " ".join(reasons)
        self.assertIn("windows opening: Capital", text)
        self.assertIn("windows closing: Dust Seals", text)

    def test_no_windows_says_so(self):
        _, reasons = self.classify(21, game=self.hand(["Sponsors"]))
        self.assertIn("no hand requirement windows on oceans", " ".join(reasons))


class TestRaceThreshold(TriageBase):
    def carl_with_building(self, n):
        g = json.loads(json.dumps(self.game))
        g["opponents"]["Carl"]["tagCounts"] = {"building": n}
        return g

    def test_opponent_at_seven_building_tags_plays_building_card(self):
        trig, reasons = self.classify(127, game=self.carl_with_building(7))
        self.assertTrue(trig)
        self.assertTrue(any("Builder" in r and "Carl" in r for r in reasons), reasons)

    def test_before_after_crossing(self):
        before, after = self.carl_with_building(6), self.carl_with_building(7)
        trig, reasons = self.classify(127, game=after, game_before=before)
        self.assertTrue(any("Builder" in r for r in reasons), reasons)

    def test_no_crossing_when_already_close_before(self):
        before, after = self.carl_with_building(8), self.carl_with_building(9)
        trig, reasons = self.classify(127, game=after, game_before=before)
        self.assertFalse(any("Builder" in r for r in reasons), reasons)

    def test_non_building_card_at_seven_is_silent_on_builder(self):
        trig, reasons = self.classify(212, game=self.carl_with_building(7))  # Sabotage
        self.assertFalse(any("Builder" in r for r in reasons), reasons)

    def test_claimed_milestone_no_longer_races(self):
        g = self.carl_with_building(7)
        g["milestonesClaimed"] = {"Builder": "Diana"}
        trig, reasons = self.classify(127, game=g)
        self.assertFalse(any("Builder" in r for r in reasons), reasons)

    def test_overtaking_me_on_funded_award(self):
        g = json.loads(json.dumps(self.game))
        g["awardsFunded"] = {"Banker": "Diana"}
        g["me"]["production"]["mc"] = 5
        g["opponents"]["Ben"]["production"]["mc"] = 5
        trig, reasons = self.classify(75, game=g)   # Ben gained 2 M€ production
        self.assertTrue(any("Banker" in r and "Ben" in r for r in reasons), reasons)

    def test_unfunded_award_gain_is_silent(self):
        g = json.loads(json.dumps(self.game))
        g["me"]["production"]["mc"] = 5
        g["opponents"]["Ben"]["production"]["mc"] = 5
        trig, reasons = self.classify(75, game=g)
        self.assertFalse(trig, reasons)


class TestFeedStore(TriageBase):
    def feed_path(self):
        return Path(self.tmp.name) / "state" / "feed.jsonl"

    def write_feed(self, lines):
        p = self.feed_path()
        with p.open("w") as f:
            for n in lines:
                f.write(json.dumps(fixture_entry(n), ensure_ascii=False) + "\n")
        return p

    def test_annotate_is_idempotent(self):
        p = self.write_feed([21, 25, 65, 93])
        out1 = triage.triage_feed(p, self.game, self.setup, None)
        text1 = p.read_text()
        out2 = triage.triage_feed(p, self.game, self.setup, None)
        self.assertEqual(text1, p.read_text())
        self.assertEqual([e["trigger"] for e in out1], [True, False, True, True])
        self.assertEqual(out1, out2)
        self.assertEqual(len(text1.strip().splitlines()), 4)

    def test_pending_and_handle_round_trip(self):
        p = self.write_feed([21, 25, 65, 93])
        triage.triage_feed(p, self.game, self.setup, None)
        pend = triage.pending(p)
        self.assertEqual([e["line"] for e in pend], [21, 65, 93])
        lines = triage.render_pending(pend)
        self.assertTrue(lines[0].startswith("#21 Carl placed:"), lines)
        n = triage.handle(p, [21, 65], note="seen, plan unchanged")
        self.assertEqual(n, 2)
        pend = triage.pending(p)
        self.assertEqual([e["line"] for e in pend], [93])
        e21 = [e for e in triage.read_feed(p) if e["line"] == 21][0]
        self.assertTrue(e21["handled"])
        self.assertEqual(e21["handledNote"], "seen, plan unchanged")
        # a re-annotate keeps the handled flag
        triage.triage_feed(p, self.game, self.setup, None)
        self.assertEqual([e["line"] for e in triage.pending(p)], [93])

    def test_cli_round_trip(self):
        p = self.write_feed([21, 25, 93])
        script = ROOT / "scripts" / "triage.py"
        run = lambda *a: subprocess.run(
            [sys.executable, str(script), "--root", self.tmp.name, *a],
            capture_output=True, text=True)
        r = run("annotate")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("pending")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("#21 Carl placed:", r.stdout)
        self.assertIn("#93 Ben funded:", r.stdout)
        self.assertNotIn("#25", r.stdout)
        r = run("handle", "21", "--note", "ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("pending")
        self.assertNotIn("#21", r.stdout)
        self.assertIn("#93", r.stdout)
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("triage", log)
        self.assertIn("21", log)

    def test_cli_feed_option_after_subcommand(self):
        alt = Path(self.tmp.name) / "elsewhere.jsonl"
        alt.write_text(json.dumps(fixture_entry(93)) + "\n")
        script = ROOT / "scripts" / "triage.py"
        run = lambda *a: subprocess.run(
            [sys.executable, str(script), "--root", self.tmp.name, *a],
            capture_output=True, text=True)
        r = run("annotate", "--feed", str(alt))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run("pending", "--feed", str(alt))
        self.assertIn("#93 Ben funded:", r.stdout)
        self.assertFalse(self.feed_path().exists())

    def test_missing_feed_is_empty_not_an_error(self):
        self.assertEqual(triage.read_feed(self.feed_path()), [])
        self.assertEqual(triage.pending(self.feed_path()), [])


if __name__ == "__main__":
    unittest.main()
