"""M2: card database — extraction results, exact and fuzzy lookup."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cards


class TestDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = cards.load_db()
        cls.all = cls.db["cards"]
        cls.projects = [c for c in cls.all if c["type"] != "corporation"]
        cls.corps = [c for c in cls.all if c["type"] == "corporation"]

    def test_db_loads_with_expected_shape(self):
        self.assertEqual(self.db["modules"], ["base", "corporateEra"])
        for card in self.all:
            for key in ("name", "cost", "type", "tags", "requirements",
                        "effects", "action", "vp", "module"):
                self.assertIn(key, card, f"{card.get('name')} missing {key}")

    def test_counts(self):
        self.assertEqual(len(self.projects), 208)
        self.assertEqual(len(self.corps), 12)
        self.assertGreater(len(self.projects), 200)  # sanity floor per spec

    def test_types_are_valid(self):
        valid = {"event", "automated", "active", "corporation"}
        self.assertEqual({c["type"] for c in self.all}, valid)

    def test_no_expansion_cards_leak_in(self):
        names = {c["name"] for c in self.all}
        for foreign in ("Allied Bank", "Aerial Mappers", "Sky Docks",
                        "Lakefront Resorts", "Dirigibles", "Penguins"):
            self.assertNotIn(foreign, names)
        for c in self.all:
            self.assertNotIn("venus", c["tags"], c["name"])

    def test_comet(self):
        c = cards.find("Comet")
        self.assertEqual(c["cost"], 21)
        self.assertEqual(c["type"], "event")
        self.assertIn("space", c["tags"])
        self.assertIn("event", c["tags"])
        self.assertIsNone(c["requirements"])
        self.assertIn("temperature 1 step", c["effects"].lower())
        self.assertIn("3 plants", c["effects"])
        self.assertIn("ocean", c["effects"].lower())

    def test_mining_rights(self):
        c = cards.find("Mining Rights")
        self.assertEqual(c["cost"], 9)
        self.assertEqual(c["type"], "automated")
        self.assertEqual(c["tags"], ["building"])
        self.assertIn("steel or titanium", c["effects"])

    def test_ai_central(self):
        c = cards.find("AI Central")
        self.assertEqual(c["cost"], 21)
        self.assertEqual(c["type"], "active")
        self.assertEqual(sorted(c["tags"]), ["building", "science"])
        self.assertEqual(c["requirements"], "3 science tags")
        self.assertEqual(c["vp"], 1)
        self.assertIn("Draw 2 cards", c["action"])

    def test_ecoline_corp(self):
        c = cards.find("Ecoline")
        self.assertEqual(c["type"], "corporation")
        self.assertEqual(c["cost"], 36)  # startingMegaCredits
        self.assertEqual(c["tags"], ["plant"])
        self.assertIn("2 plant production", c["effects"])
        self.assertIn("7 plants", c["effects"])

    def test_requirement_strings(self):
        self.assertEqual(cards.find("Ants")["requirements"], "min 4% O2")
        self.assertEqual(cards.find("Arctic Algae")["requirements"], "max -12°C")
        self.assertEqual(cards.find("Capital")["requirements"], "min 4 oceans")
        self.assertEqual(cards.find("Breathing Filters")["requirements"], "min 7% O2")

    def test_vp_formulas(self):
        self.assertEqual(cards.find("Birds")["vp"], "1 per animal")
        self.assertEqual(cards.find("Pets")["vp"], "1 per 2 animals")
        self.assertEqual(cards.find("Io Mining Industries")["vp"], "1 per jovian tag")
        self.assertEqual(cards.find("Capital")["vp"], "1 per adjacent ocean tile")
        self.assertEqual(cards.find("Virus")["vp"], None)

    def test_every_card_has_some_text(self):
        for c in self.all:
            self.assertTrue(c["effects"] or c["action"], f"{c['name']} has no text")

    def test_active_cards_only_have_actions(self):
        for c in self.projects:
            if c["action"] and "Effect" not in (c["effects"] or ""):
                self.assertEqual(c["type"], "active", c["name"])


class TestLookup(unittest.TestCase):
    def test_find_is_case_insensitive(self):
        self.assertEqual(cards.find("cOMET")["name"], "Comet")
        self.assertEqual(cards.find("ai central")["name"], "AI Central")

    def test_find_unknown_returns_none(self):
        self.assertIsNone(cards.find("Definitely Not A Card"))

    def test_fuzzy_ocr_noise(self):
        best, score = cards.fuzzy("comets")[0]
        self.assertEqual(best["name"], "Comet")
        self.assertGreater(score, 0.8)

    def test_fuzzy_truncated(self):
        best, _ = cards.fuzzy("mining right")[0]
        self.assertEqual(best["name"], "Mining Rights")

    def test_fuzzy_exact_scores_one(self):
        matches = cards.fuzzy("Ecoline")
        self.assertEqual(matches[0][0]["name"], "Ecoline")
        self.assertEqual(matches[0][1], 1.0)

    def test_fuzzy_limit_and_scores_sorted(self):
        matches = cards.fuzzy("power", limit=3)
        self.assertEqual(len(matches), 3)
        scores = [s for _, s in matches]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_fuzzy_handles_apostrophes(self):
        best, score = cards.fuzzy("inventors guild")[0]
        self.assertEqual(best["name"], "Inventors' Guild")
        self.assertEqual(score, 1.0)


if __name__ == "__main__":
    unittest.main()


class TestResolvePolicy(unittest.TestCase):
    """Voice-noise resolution policy — the regression corpus is REAL table
    utterances recorded at physical game nights."""

    def test_accept_tier_clean_garbles(self):
        for noise, want in [("mhole area", "Mohole Area"),
                            ("imported gigi", "Imported GHG"),
                            ("awuafer pumping", "Aquifer Pumping"),
                            ("permafrost extension", "Permafrost Extraction")]:
            card, verdict = cards.resolve(noise)
            self.assertEqual(card["name"], want, noise)
            self.assertEqual(verdict, "accept", noise)

    def test_confirm_tier_heavier_garbles(self):
        for noise, want in [("colonizer camp", "Colonizer Training Camp"),
                            ("plaid marinaria", "Lake Marineris")]:
            card, verdict = cards.resolve(noise)
            self.assertEqual(card["name"], want, noise)
            self.assertEqual(verdict, "confirm", noise)

    def test_ask_tier_unresolvable(self):
        for noise in ("awuafer", "aerobtsking"):
            card, verdict = cards.resolve(noise)
            self.assertEqual(verdict, "ask", noise)

    def test_pool_context_rescues_ambiguity(self):
        hand = ["Ice Cap Melting", "Lake Marineris", "Lunar Beam",
                "Martian Rails"]
        card, verdict = cards.resolve("marinaria", pool=hand)
        self.assertEqual(card["name"], "Lake Marineris")
        self.assertEqual(verdict, "accept")
