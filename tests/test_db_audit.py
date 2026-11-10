"""Card-db integrity — bespoke-code cards must be flagged
and carry curated behavior; audit_db diffs regenerated vs committed db."""
import json, subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

DB = json.loads((ROOT / "cards" / "db.json").read_text())


def all_cards():
    yield from DB["cards"]


class TestBespokeCoverage(unittest.TestCase):
    def test_flooding_has_ocean_behavior(self):
        card = next(c for c in all_cards() if c["name"] == "Flooding")
        self.assertIsNotNone(card["behavior"], "Flooding lost its ocean again")
        self.assertIn("ocean", card["behavior"])

    def test_moss_loses_a_plant(self):
        card = next(c for c in all_cards() if c["name"] == "Moss")
        self.assertEqual(card["behavior"].get("stock", {}).get("plants"), -1)

    def test_every_bespoke_card_is_flagged(self):
        # every card whose vendor class defines bespokePlay must carry
        # bespoke: true in the db so the engine/advisor knows the db
        # behavior may be partial
        flagged = {c["name"] for c in all_cards() if c.get("bespoke")}
        self.assertIn("Flooding", flagged)
        self.assertIn("Moss", flagged)


VENDOR = ROOT / "vendor" / "terraforming-mars"


@unittest.skipUnless(VENDOR.exists(),
                     "vendor/terraforming-mars clone absent (git-ignored; "
                     "needed only to re-audit cards/db.json against upstream)")
class TestAuditScript(unittest.TestCase):
    def test_audit_passes_on_committed_db(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "audit_db.py")],
            capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
