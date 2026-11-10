"""audit_db.py must SAY what the db still does not model, so the phase-2
interpreter has a checklist instead of a guess:

  - every card flagged bespoke that has no curated behavior patch
  - every card with an action the db carries only as prose
  - a one-line coverage summary (counts), so a regression is visible.

The report is advisory (exit 0); only a committed-vs-vendor delta fails.
"""
import io
import contextlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
VENDOR = ROOT / "vendor" / "terraforming-mars"

DB = json.loads((ROOT / "cards" / "db.json").read_text())


@unittest.skipUnless(VENDOR.exists(), "vendor clone absent (git-ignored)")
class TestAuditReport(unittest.TestCase):
    def _run(self):
        import audit_db
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = audit_db.main()
        return rc, buf.getvalue()

    def test_audit_passes_and_reports_both_gaps(self):
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertIn("bespoke cards without curated patches", out)
        self.assertIn("prose-only action", out)
        self.assertIn("COVERAGE", out)

    def test_prose_only_actions_are_named(self):
        _, out = self._run()
        # the four cards that implement action()/canAct() in TypeScript
        for name in ("Extreme-Cold Fungus", "Power Infrastructure",
                     "Search For Life", "United Nations Mars Initiative"):
            self.assertIn(name, out)

    def test_a_structured_action_card_is_not_listed_as_a_gap(self):
        _, out = self._run()
        gaps = out.split("prose-only action", 1)[1]
        self.assertNotIn("Ironworks", gaps)

    def test_coverage_counts_match_the_db(self):
        _, out = self._run()
        line = next(l for l in out.splitlines() if l.startswith("COVERAGE"))
        n_action = sum(1 for c in DB["cards"] if c.get("actionBehavior"))
        n_bespoke = sum(1 for c in DB["cards"] if c.get("bespoke"))
        self.assertIn(f"{n_action} structured actions", line)
        self.assertIn(f"{n_bespoke} bespoke", line)


if __name__ == "__main__":
    unittest.main()
