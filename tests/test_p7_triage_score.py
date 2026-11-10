"""P7 field defects — the first full-autopilot game's post-mortem, L3 and E4.

L3: the PENDING TRIGGERS list carried gen-1/gen-2 class-f entries
("generation 2 starts", "turn order: first player is now Anna") into
generation 8. A trigger scoped to ONE generation is dead once that
generation is over; a race / plan trigger from the same generation is not.
The feed is a record — the entries stay, they only stop being pending.

E4: `score.py --abort` ranked me last at 20 VP with Mayor (5 VP) claimed.
The omission is documented (AGENTS.md), so the maths must NOT change — the
omission must become VISIBLE.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))     # sibling fixtures

import score
import triage
from tmlib import Engine, Store

from test_new_game import SETUP as SCORE_SETUP
from test_triage import PLAN_44, SETUP as TRIAGE_SETUP, fixture_entry

ROOT = Path(__file__).resolve().parent.parent

GEN_LINE = 54        # "Generation 2"            → class f
FIRST_LINE = 55      # "First player … is Carl"  → class f
RACE_LINE = 127      # "Carl played Immigrant City" → 🔁 step 2a races Builder

# P8 #14: plan-relative triggers only look at feed lines NEWER than the plan
# (feedCursor, generation fallback). The plan under test here is therefore
# the one composed at the generation these fixture lines belong to — the
# class-f scoping under test is unaffected either way.
PLAN = {**PLAN_44, "generation": 1}


# ── L3: stale generation-scoped triggers ─────────────────────────────
class TestStaleGenerationTriggers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(TRIAGE_SETUP)
        self.game = self.store.load_game()
        self.setup = self.store.load_setup()
        self.feed = Path(self.tmp.name) / "state" / "feed.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, lines, gen=1):
        with self.feed.open("w") as f:
            for n in lines:
                f.write(json.dumps(fixture_entry(n, gen=gen)) + "\n")
        return self.feed

    def annotate(self, generation):
        self.game["generation"] = generation
        return triage.triage_feed(self.feed, self.game, self.setup, PLAN)

    def test_generation_boundary_trigger_from_gen1_is_not_pending_in_gen3(self):
        self.write([GEN_LINE, FIRST_LINE, RACE_LINE])
        self.annotate(3)
        self.assertEqual([e["line"] for e in triage.pending(self.feed)],
                         [RACE_LINE])

    def test_race_trigger_from_gen1_is_still_pending_in_gen3(self):
        self.write([RACE_LINE])
        self.annotate(3)
        pend = triage.pending(self.feed)
        self.assertEqual(len(pend), 1)
        self.assertTrue(any("Builder" in r for r in pend[0]["reasons"]),
                        pend[0]["reasons"])

    def test_generation_scoped_triggers_stay_pending_in_their_own_generation(self):
        self.write([GEN_LINE, FIRST_LINE], gen=3)
        self.annotate(3)
        self.assertEqual([e["line"] for e in triage.pending(self.feed)],
                         [GEN_LINE, FIRST_LINE])

    def test_nothing_is_lost_from_the_feed_record(self):
        self.write([GEN_LINE, FIRST_LINE, RACE_LINE])
        self.annotate(3)
        entries = {e["line"]: e for e in triage.read_feed(self.feed)}
        self.assertEqual(sorted(entries), [GEN_LINE, FIRST_LINE, RACE_LINE])
        for n in (GEN_LINE, FIRST_LINE):
            e = entries[n]
            self.assertTrue(e["trigger"])            # it DID fire — history
            self.assertTrue(e["reasons"])
            self.assertTrue(e["raw"])
            self.assertTrue(e["handled"])
            self.assertIn("generation", (e.get("handledNote") or "").lower())

    def test_auto_resolve_is_idempotent(self):
        self.write([GEN_LINE, RACE_LINE])
        self.annotate(3)
        text = self.feed.read_text()
        self.annotate(3)
        self.assertEqual(text, self.feed.read_text())

    def test_a_hand_handled_note_is_never_overwritten(self):
        self.write([GEN_LINE])
        self.annotate(1)
        triage.handle(self.feed, [GEN_LINE], note="looked, produce run")
        self.annotate(3)
        e = triage.read_feed(self.feed)[0]
        self.assertEqual(e["handledNote"], "looked, produce run")


# ── E4: abort scoring shows what it excludes ─────────────────────────
class TestAbortShowsExcluded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SCORE_SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def claim(self):
        self.eng.res("Zed", "mc", +80)
        self.eng.tr("Zed", +15)                      # TR 35 — Terraformer
        self.eng.milestone("Zed", "Terraformer")     # 5 VP, excluded by abort
        self.eng.award("Zed", "Banker")
        self.eng.prod("Zed", "mc", +3)               # leads the Banker metric

    def run_score(self, *argv):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "score.py"),
             "--state", str(Path(self.tmp.name) / "state" / "game.json"), *argv],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_abort_names_the_claimed_milestone_and_says_it_is_excluded(self):
        self.claim()
        out = self.run_score("--abort")
        self.assertIn("Terraformer", out)
        self.assertIn("exclud", out.lower())

    def test_abort_names_the_funded_award_it_leaves_out(self):
        self.claim()
        out = self.run_score("--abort")
        self.assertIn("Banker", out)

    def test_abort_total_maths_is_unchanged(self):
        self.claim()
        g = self.game()
        row = {p["name"]: p for p in score.compute(g, "abort")["players"]}["Zed"]
        self.assertEqual(row["milestoneVP"], 0)
        self.assertEqual(row["awardVP"], 0)
        self.assertEqual(row["total"], row["tr"] + row["cardVP"] + row["tileVP"])
        out = self.run_score("--abort")
        self.assertIn(f"Zed: {row['total']} VP", out)

    def test_the_excluded_line_shows_the_would_be_total(self):
        self.claim()
        g = self.game()
        abort = {p["name"]: p for p in score.compute(g, "abort")["players"]}["Zed"]
        full = {p["name"]: p for p in score.compute(g, "full")["players"]}["Zed"]
        self.assertEqual(full["total"] - abort["total"], 10)   # 5 ms + 5 award
        self.assertIn(str(full["total"]), self.run_score("--abort"))

    def test_nothing_claimed_keeps_the_output_clean(self):
        self.eng.res("Zed", "mc", +80)
        out = self.run_score("--abort")
        self.assertNotIn("exclud", out.lower())

    def test_full_mode_does_not_print_the_excluded_block(self):
        self.claim()
        out = self.run_score()
        self.assertNotIn("exclud", out.lower())


if __name__ == "__main__":
    unittest.main()
