"""The strategy knowledge base is product-neutral and loses no rules.

Three guards over strategy/*.md:
1. No player names, game numbers, calendar dates, or references to a
   specific table or private files.
2. 00-layers-and-sources.md indexes every other file in the folder, and
   every file it indexes exists.
3. Each file keeps at least its ledgered number of bullet/numbered lines
   (the rule count at the time of the neutrality pass) so a future edit
   cannot silently delete rules.
"""
import re
import unittest
from pathlib import Path

STRATEGY = Path(__file__).resolve().parent.parent / "strategy"
INDEX = "00-layers-and-sources.md"

# Case-sensitive, word-bounded: personal names of players at any table.
FORBIDDEN_NAMES = re.compile(r"\b(Anna|Ben|Carl|Diana|Zed)\b")
# Case-insensitive: game numbers, short game tags, dates, private material.
FORBIDDEN_OTHER = re.compile(
    r"game ?[0-9]|\bG[0-9]+\b|2026-|runbook|roster|private/", re.I)

# Bullet or numbered line = one rule (or one index/source entry).
RULE_LINE = re.compile(r"^\s*(-|\d+\.)\s")

# Floors ledgered at the neutrality pass. Raise when rules are added;
# never lower without a deliberate, reviewed deletion.
RULE_FLOORS = {
    "00-layers-and-sources.md": 15,
    "01-valuation-economy.md": 28,
    "02-archetypes-game-arc.md": 31,
    "03-corporations.md": 77,
    "04-card-tiers.md": 32,
    "05-openings.md": 60,
    "06-lessons-from-play.md": 45,
}

# 06 hygiene pass (evidence counts): every ledger rule ends with an
# evidence tag carrying multiplicity and class; sections stay mergeable-
# small; no near-duplicate appends.
LEDGER = "06-lessons-from-play.md"
LEDGER_TAG = re.compile(r"·\s*\([^()]*×\d+ (seats|humans|models)(\+(seats|humans|models))*\)\s*$")
LEDGER_SECTION_CEILING = 16


def _files():
    return sorted(p for p in STRATEGY.glob("*.md"))


class TestStrategyKBNeutral(unittest.TestCase):
    def test_no_forbidden_tokens(self):
        hits = []
        for path in _files():
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if FORBIDDEN_NAMES.search(line) or FORBIDDEN_OTHER.search(line):
                    hits.append(f"{path.name}:{n}: {line.strip()}")
        self.assertEqual(hits, [], "product-neutrality violations:\n"
                         + "\n".join(hits))

    def test_index_lists_every_file(self):
        index = (STRATEGY / INDEX).read_text()
        listed = set(re.findall(r"\b(0\d-[a-z-]+\.md)\b", index))
        on_disk = {p.name for p in _files()} - {INDEX}
        self.assertEqual(on_disk - listed, set(),
                         "files missing from the 00 index")
        self.assertEqual(listed - on_disk, set(),
                         "00 indexes files that do not exist")

    def test_every_file_has_a_floor(self):
        self.assertEqual({p.name for p in _files()}, set(RULE_FLOORS),
                         "add a RULE_FLOORS entry for every strategy file")

    def test_rule_counts_meet_floors(self):
        for name, floor in RULE_FLOORS.items():
            text = (STRATEGY / name).read_text()
            count = sum(1 for l in text.splitlines() if RULE_LINE.match(l))
            self.assertGreaterEqual(
                count, floor,
                f"{name}: {count} rule lines < ledgered floor {floor}")


if __name__ == "__main__":
    unittest.main()


class TestLedgerHygiene(unittest.TestCase):
    """06 format contract (2026-08-29): ×N class tags, dedup, ceilings —
    the fold discipline is enforced here, not remembered."""

    def _sections(self):
        sec, cur = None, []
        out = {}
        for line in (STRATEGY / LEDGER).read_text().splitlines():
            if line.startswith("## "):
                sec, cur = line[3:], out.setdefault(line[3:], [])
            elif RULE_LINE.match(line) and sec:
                cur.append(line)
        return out

    def test_every_rule_has_multiplicity_and_class_tag(self):
        bad = [l[:80] for rules in self._sections().values()
               for l in rules if not LEDGER_TAG.search(l)]
        self.assertEqual(bad, [], "06 rules missing '· (... ×N seats|humans)' tag:\n"
                         + "\n".join(bad))

    def test_no_near_duplicate_rules_in_a_section(self):
        for sec, rules in self._sections().items():
            heads = [" ".join(l.lstrip("- ").lower().split()[:6]) for l in rules]
            dups = {h for h in heads if heads.count(h) > 1}
            self.assertEqual(dups, set(),
                             f"near-duplicate rules in 06 '{sec}' — increment "
                             f"×N on the existing line instead: {dups}")

    def test_section_ceiling_forces_merges(self):
        for sec, rules in self._sections().items():
            self.assertLessEqual(
                len(rules), LEDGER_SECTION_CEILING,
                f"06 '{sec}' has {len(rules)} rules (ceiling "
                f"{LEDGER_SECTION_CEILING}) — merge before appending")
