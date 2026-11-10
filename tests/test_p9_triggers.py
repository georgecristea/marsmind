"""P9 trigger noise — issues 8, 9, 10 of private/plans/p9-issues.md.

Three ways the ⚠ JUDGMENT NEEDED banner broke its own acceptance rule
("banners name only fresh events") in the 2026-08-29 live game, each one
costing the advisor a wasted round-trip:

  8  SELF-TRIGGERS — the global-parameter class fired on the advisor's OWN
     executed plan step (gen 3 #79 "Zed raised oceans +1" came from step 1a,
     which had already priced exactly that ocean; again at gen 5 #144).
  9  BACK-DATED TRIGGERS — Ben funding Scientist in gen 5 re-derived the same
     "Ben overtakes you on Scientist" race onto FIVE historical science plays
     (feed lines #22, #45, #74, #76, #134, generations 2-5), so a gen-6 banner
     was raised by lines four generations old.
 10  UNBOUNDED BACKLOG — 32 pending entries by the gen 11/12 boundary, among
     them race lines for milestones already CLAIMED and requirement-window
     lines for cards SOLD two generations earlier. The banner only ever names
     the newest few, so clearing them needed a manual --sweep --peek scrape.

Same fixture as tests/test_triage.py: tests/fixtures/replay-4p-wgt, me = Diana.
"""
import json
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


class P9Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.game = self.store.load_game()
        self.setup = self.store.load_setup()

    def tearDown(self):
        self.tmp.cleanup()

    def copy(self, **globals_) -> dict:
        g = json.loads(json.dumps(self.game))
        g["globals"].update(globals_)
        return g

    def entry(self, raw: str, line: int, gen: int = 9) -> dict:
        return triage.new_entry(P.parse_line(raw, PLAYERS), line=line, gen=gen,
                                raw=raw, ts="2026-01-01T00:00:00")

    def fixture_entry(self, n: int, gen: int = 5) -> dict:
        return self.entry(LINES[n - 1], line=n, gen=gen)

    def feed(self, entries: list[dict]) -> Path:
        p = Path(self.tmp.name) / "state" / "feed.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return p


# ── issue 8: the banner fires on my own executed plan step ───────────
def plan_with(step: dict, generation: int = 9) -> dict:
    base = {"id": "1a", "volatility": "recheck", "done": True,
            "cue": "blue tile on 44", "events": []}
    return {"generation": generation, "draft": False, "feedCursor": 0,
            "threats": "Ben Landlord race", "steps": [{**base, **step}]}


OCEAN_44 = plan_with({
    "summary": "SP Aquifer — the ocean on 44 (oceans 3 → 4, TR +1)",
    "mapHighlight": "44",
    "events": [{"method": "standard", "args": ["Diana", "aquifer"]},
               {"method": "place", "args": ["Diana", "ocean", "44"]}]})

BIG_ASTEROID = plan_with({
    "summary": "Play Big Asteroid — temperature +2",
    "cue": "temperature marker moved",
    "events": [{"method": "play", "args": ["Diana", "Big Asteroid"]}]})


class TestOwnPlannedGlobalStep(P9Base):
    """Issue 8: my own planned parameter change was already priced by the
    step that produced it; an UNPLANNED own change must still surface."""

    def globals_reasons(self, entry, plan, game=None):
        _, reasons = triage.classify(entry, game or self.game, self.setup, plan)
        return [r for r in reasons if r.startswith("global:")]

    def test_own_planned_ocean_raises_no_global_trigger(self):
        e = self.entry("Diana placed ocean tile at 44", line=501)
        self.assertEqual(self.globals_reasons(e, OCEAN_44), [])

    def test_own_planned_card_raises_no_global_trigger(self):
        e = self.entry("Diana played Big Asteroid", line=502)
        self.assertEqual(self.globals_reasons(e, BIG_ASTEROID), [])

    def test_own_unplanned_ocean_still_triggers(self):
        e = self.entry("Diana placed ocean tile at 13", line=503)
        self.assertTrue(self.globals_reasons(e, OCEAN_44))

    def test_step_not_yet_executed_still_triggers(self):
        plan = json.loads(json.dumps(OCEAN_44))
        plan["steps"][0]["done"] = False
        e = self.entry("Diana placed ocean tile at 44", line=504)
        self.assertTrue(self.globals_reasons(e, plan))

    def test_skipped_step_still_triggers(self):
        plan = json.loads(json.dumps(OCEAN_44))
        plan["steps"][0]["skipped"] = True
        e = self.entry("Diana placed ocean tile at 44", line=505)
        self.assertTrue(self.globals_reasons(e, plan))

    def test_an_opponent_on_my_planned_hex_still_triggers(self):
        e = self.entry("Ben placed ocean tile at 44", line=506)
        self.assertTrue(self.globals_reasons(e, OCEAN_44))

    def test_a_plan_from_another_generation_does_not_suppress(self):
        plan = plan_with(OCEAN_44["steps"][0], generation=4)
        e = self.entry("Diana placed ocean tile at 44", line=507, gen=9)
        self.assertTrue(self.globals_reasons(e, plan))

    def test_no_plan_at_all_still_triggers(self):
        e = self.entry("Diana placed ocean tile at 44", line=508)
        self.assertTrue(self.globals_reasons(e, None))


# ── issue 9: one race trigger, dated at the funding line ─────────────
class TestAwardFundingRace(P9Base):
    """Issue 9: funding an award re-evaluates the race. That is ONE fact,
    dated at the funding line — not one copy per historical play."""

    def banker(self) -> dict:
        g = json.loads(json.dumps(self.game))
        g["awardsFunded"] = {"Banker": "Ben"}
        g["me"]["production"]["mc"] = 2
        g["opponents"]["Ben"]["production"]["mc"] = 5
        return g

    def races(self, entry, game, context=None):
        _, reasons = triage.classify(entry, game, self.setup, None,
                                     context=context)
        return [r for r in reasons if r.startswith("race:")]

    def test_the_funding_line_itself_carries_the_race(self):
        e = self.fixture_entry(93)              # Ben funded Banker award
        rows = self.races(e, self.banker())
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("Ben overtakes you on Banker (funded by Ben)", rows[0])
        self.assertIn("5 vs your 2", rows[0])

    def test_a_play_older_than_the_funding_line_is_not_back_dated(self):
        e = self.entry("Ben gained 2 M€ production", line=75, gen=2)
        ctx = {"decidedAt": {"Banker": 93}}
        self.assertEqual(self.races(e, self.banker(), ctx), [])

    def test_a_play_after_the_funding_line_still_races(self):
        e = self.entry("Ben gained 2 M€ production", line=150, gen=6)
        ctx = {"decidedAt": {"Banker": 93}}
        self.assertTrue(self.races(e, self.banker(), ctx))

    def test_re_annotating_the_feed_emits_exactly_one_race_line(self):
        # the P9 shape: four generations of metric plays, then the funding
        # (game feed lines #22, #45, #74, #76, #134 → funded at #141)
        entries = [self.entry("Ben gained 2 M€ production", line=n, gen=g)
                   for n, g in ((22, 2), (45, 3), (74, 4), (76, 4), (134, 5))]
        entries.append(self.entry("Ben funded Banker award", line=141, gen=5))
        path = self.feed(entries)
        out = triage.triage_feed(path, self.banker(), self.setup, None)
        carriers = [e["line"] for e in out
                    if any(r.startswith("race:") for r in e["reasons"])]
        self.assertEqual(carriers, [141], carriers)

    def test_funding_with_nobody_ahead_of_me_is_silent(self):
        g = self.banker()
        g["me"]["production"]["mc"] = 9
        self.assertEqual(self.races(self.fixture_entry(93), g), [])


# ── issue 10: prune pending entries whose premise is dead ────────────
class TestDeadPremisePruning(P9Base):
    """Issue 10: the banner only names the newest few, so anything stale in
    the pending list has to be scraped out by hand. An entry whose premise
    cannot come back is auto-resolved, exactly like a stale generation
    trigger — trigger and reasons are kept, it just stops being pending."""

    def pend(self, entries, game):
        path = self.feed(entries)
        return triage.pending(path, game, self.setup), path

    def triggered(self, raw, line, reasons, gen=5):
        e = self.entry(raw, line=line, gen=gen)
        e["trigger"], e["reasons"] = True, list(reasons)
        return e

    def test_race_line_for_a_claimed_milestone_is_pruned(self):
        g = json.loads(json.dumps(self.game))
        g["milestonesClaimed"] = {"Builder": "Ben"}
        e = self.triggered("Carl played Immigrant City", 127,
                           ["race: Carl can claim NOW Builder (buildingTags 8/8)"])
        pend, path = self.pend([e], g)
        self.assertEqual(pend, [])
        stored = triage.read_feed(path)[0]
        self.assertTrue(stored["handled"])
        self.assertIn("Builder", stored["handledNote"])
        self.assertEqual(stored["reasons"], e["reasons"])   # the feed is a record

    def test_plan_race_line_for_a_claimed_milestone_is_pruned(self):
        g = json.loads(json.dumps(self.game))
        g["milestonesClaimed"] = {"Builder": "Diana"}
        e = self.triggered("Carl played Immigrant City", 41,
                           ["plan: 🔁 step 2a races Builder — Carl's played "
                            "moves that metric"])
        pend, _ = self.pend([e], g)
        self.assertEqual(pend, [])

    def test_race_line_for_an_unclaimed_milestone_survives(self):
        e = self.triggered("Carl played Immigrant City", 127,
                           ["race: Carl can claim NOW Builder (buildingTags 8/8)"])
        pend, _ = self.pend([e], self.game)
        self.assertEqual([x["line"] for x in pend], [127])

    def test_award_race_line_survives_while_the_opponent_leads(self):
        g = json.loads(json.dumps(self.game))
        g["awardsFunded"] = {"Banker": "Ben"}
        g["me"]["production"]["mc"] = 2
        g["opponents"]["Ben"]["production"]["mc"] = 5
        e = self.triggered("Ben gained 2 M€ production", 75,
                           ["race: Ben overtakes you on Banker (funded by Ben): "
                            "5 vs your 2"])
        pend, _ = self.pend([e], g)
        self.assertEqual([x["line"] for x in pend], [75])

    def test_award_race_line_is_pruned_once_i_lead_again(self):
        g = json.loads(json.dumps(self.game))
        g["awardsFunded"] = {"Banker": "Ben"}
        g["me"]["production"]["mc"] = 9
        g["opponents"]["Ben"]["production"]["mc"] = 5
        e = self.triggered("Ben gained 2 M€ production", 75,
                           ["race: Ben overtakes you on Banker (funded by Ben): "
                            "5 vs your 2"])
        pend, _ = self.pend([e], g)
        self.assertEqual(pend, [])

    def test_requirement_window_for_a_sold_card_is_pruned(self):
        g = json.loads(json.dumps(self.game))
        g["me"]["hand"] = ["Sponsors"]                  # Capital was sold
        e = self.triggered("Carl placed ocean tile at 63", 21,
                           ["global: Carl raised oceans +1 → 6 steps left on "
                            "oceans (clock shortens; re-run clock.py); "
                            "windows opening: Capital (min 4 oceans)"])
        pend, _ = self.pend([e], g)
        self.assertEqual(pend, [])

    def test_requirement_window_for_a_card_still_in_hand_survives(self):
        g = json.loads(json.dumps(self.game))
        g["me"]["hand"] = ["Capital", "Sponsors"]
        e = self.triggered("Carl placed ocean tile at 63", 21,
                           ["global: Carl raised oceans +1 → 6 steps left on "
                            "oceans (clock shortens; re-run clock.py); "
                            "windows opening: Capital (min 4 oceans)"])
        pend, _ = self.pend([e], g)
        self.assertEqual([x["line"] for x in pend], [21])

    def test_one_live_reason_keeps_the_entry_pending(self):
        g = json.loads(json.dumps(self.game))
        g["milestonesClaimed"] = {"Builder": "Ben"}
        e = self.triggered("Diana lost 3 titanium because of Carl", 213,
                           ["attack: Carl removed 3 titanium from you",
                            "race: Carl can claim NOW Builder (buildingTags 8/8)"])
        pend, _ = self.pend([e], g)
        self.assertEqual([x["line"] for x in pend], [213])

    def test_a_parameter_line_without_a_window_is_left_alone(self):
        """Only the WINDOW is a dead premise. A parameter line still carries
        the clock, and pruning those would silence a whole generation of
        global steps the moment the generation turned over (test_p7_lane's
        stale-trigger contract: class f only)."""
        g = json.loads(json.dumps(self.game))
        g["generation"] = 9
        g["me"]["hand"] = ["Sponsors"]
        e = self.triggered("Carl placed ocean tile at 63", 21,
                           ["global: Carl raised oceans +1 → 6 steps left on "
                            "oceans (clock shortens; re-run clock.py); no hand "
                            "requirement windows on oceans"], gen=4)
        pend, _ = self.pend([e], g)
        self.assertEqual([x["line"] for x in pend], [21])

    def test_annotate_prunes_a_dead_premise_too(self):
        """The P9 backlog case that survives re-classification: an open plan
        step still races Builder, and Builder was claimed four generations
        ago (feed lines #41/#48/#55, Builder claimed at #200)."""
        g = json.loads(json.dumps(self.game))
        g["generation"] = 9
        g["milestonesClaimed"] = {"Builder": "Diana"}
        plan = {"generation": 9, "draft": False, "feedCursor": 0,
                "threats": "Ben Builder race",
                "steps": [{"id": "2a", "summary": "claim Builder",
                           "volatility": "recheck",
                           "cue": "your marker on Builder",
                           "events": [{"method": "milestone",
                                       "args": ["Diana", "Builder"]}],
                           "done": False}]}
        path = self.feed([self.entry("Carl played Immigrant City", 41, gen=2)])
        out = triage.triage_feed(path, g, self.setup, plan)
        self.assertTrue(out[0]["reasons"])                 # the feed is a record
        self.assertIn("Builder", " ".join(out[0]["reasons"]))
        self.assertTrue(out[0]["handled"])
        self.assertIn("premise dead", out[0]["handledNote"])
        self.assertEqual(triage.pending(path), [])

    def test_pending_without_game_prunes_nothing(self):
        g = json.loads(json.dumps(self.game))
        g["milestonesClaimed"] = {"Builder": "Ben"}
        e = self.triggered("Carl played Immigrant City", 127,
                           ["race: Carl can claim NOW Builder (buildingTags 8/8)"])
        path = self.feed([e])
        self.assertEqual([x["line"] for x in triage.pending(path)], [127])


if __name__ == "__main__":
    unittest.main()
