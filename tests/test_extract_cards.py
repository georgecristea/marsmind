"""Phase 1 of the generalize-engine plan: cards/db.json must carry the
vendor's DECLARATIVE card data, so the engine can interpret it generically
instead of hand-modelling one card at a time.

New fields (all additive — existing fields keep their meaning and values):
  actionBehavior  the ActionCard `action:` object literal (prose stays in
                  `action`, which every reader today parses as text)
  vpData          the structured `victoryPoints` (prose stays in `vp`)
  cardDiscount    {"amount": N, "tag"?: t}  — tmlib.DISCOUNTS as data
  resourceType    the card resource this card holds
  cardCost        corporations that change the price of project cards
  bespokeMethods  the TS hooks the class actually overrides; `bespoke` is
                  now exactly `bool(bespokeMethods)`
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
VENDOR = ROOT / "vendor" / "terraforming-mars"

DB = json.loads((ROOT / "cards" / "db.json").read_text())
CARDS = {c["name"]: c for c in DB["cards"]}


class TestActionBehavior(unittest.TestCase):
    """The `action:` block of every ActionCard, as data."""

    def test_physics_complex(self):
        self.assertEqual(CARDS["Physics Complex"]["actionBehavior"],
                         {"spend": {"energy": 6}, "addResources": 1})

    def test_aquifer_pumping_keeps_the_steel_flag(self):
        self.assertEqual(CARDS["Aquifer Pumping"]["actionBehavior"],
                         {"spend": {"megacredits": 8, "canUseSteel": True},
                          "ocean": {}})

    def test_ironworks(self):
        self.assertEqual(CARDS["Ironworks"]["actionBehavior"],
                         {"spend": {"energy": 4}, "stock": {"steel": 1},
                          "global": {"oxygen": 1}})

    def test_martian_rails_keeps_the_countable(self):
        self.assertEqual(
            CARDS["Martian Rails"]["actionBehavior"],
            {"spend": {"energy": 1},
             "stock": {"megacredits": {"cities": {"where": "onmars"}}}})

    def test_caretaker_contract(self):
        self.assertEqual(CARDS["Caretaker Contract"]["actionBehavior"],
                         {"spend": {"heat": 8}, "tr": 1})

    def test_predators_moves_a_resource(self):
        self.assertEqual(
            CARDS["Predators"]["actionBehavior"],
            {"removeResourcesFromAnyCard": {"type": "animal", "source": "all"},
             "addResources": 1})

    def test_prose_action_is_unchanged(self):
        # the prose stays the DISPLAY text (cards.py, research.py, the
        # menu's detail line) even though every reader now derives the
        # MECHANICS from actionBehavior.
        self.assertEqual(CARDS["Physics Complex"]["action"],
                         "Spend 6 energy to add a science resource to this card.")
        self.assertIsInstance(CARDS["Ironworks"]["action"], str)

    def test_every_action_card_has_a_structured_action(self):
        # a card with an action but no actionBehavior is one phase 2 cannot
        # drive generically; audit_db.py reports them and this pins zero.
        # The four exceptions implement action()/canAct() in TypeScript
        # instead of extending ActionCard — they are flagged bespoke, and
        # audit_db.py lists them.
        legacy = {"Extreme-Cold Fungus", "Power Infrastructure",
                  "Search For Life", "United Nations Mars Initiative"}
        missing = sorted(c["name"] for c in DB["cards"]
                         if c.get("action") and c.get("actionBehavior") is None
                         and c["name"] not in legacy)
        self.assertEqual(missing, [], f"no structured action for {missing}")
        for name in legacy:
            self.assertTrue(CARDS[name].get("bespoke"), name)


class TestVictoryPointsData(unittest.TestCase):
    def test_resources_here_each(self):
        self.assertEqual(CARDS["Physics Complex"]["vpData"],
                         {"resourcesHere": {}, "each": 2})

    def test_resources_here_plain(self):
        self.assertEqual(CARDS["Predators"]["vpData"], {"resourcesHere": {}})

    def test_plain_number(self):
        self.assertEqual(CARDS["Earth Catapult"]["vpData"], 2)

    def test_prose_vp_is_unchanged(self):
        self.assertEqual(CARDS["Physics Complex"]["vp"], "2 per science resource")
        self.assertEqual(CARDS["Earth Catapult"]["vp"], 2)

    def test_no_vp_card_has_null_vpdata(self):
        self.assertIsNone(CARDS["Ironworks"]["vpData"])


class TestDiscountAndResourceType(unittest.TestCase):
    def test_untagged_discount(self):
        self.assertEqual(CARDS["Earth Catapult"]["cardDiscount"], {"amount": 2})

    def test_tagged_discount(self):
        self.assertEqual(CARDS["Space Station"]["cardDiscount"],
                         {"tag": "space", "amount": 2})

    def test_corporation_discount(self):
        self.assertEqual(CARDS["Teractor"]["cardDiscount"],
                         {"tag": "earth", "amount": 3})

    def test_every_price_modifier_the_engine_needs_is_in_the_db(self):
        # phase 2 deleted tmlib.DISCOUNTS: these ten ARE the engine's price
        # model now, so the extractor must keep emitting them.
        expect = {
            "Teractor": ("earth", 3), "ThorGate": ("power", 3),
            "Earth Catapult": (None, 2), "Research Outpost": (None, 1),
            "Anti-Gravity Technology": (None, 2),
            "Space Station": ("space", 2), "Mass Converter": ("space", 2),
            "Quantum Extractor": ("space", 2), "Shuttles": ("space", 2),
            "Earth Office": ("earth", 3),
        }
        for name, (tag, amount) in expect.items():
            got = CARDS[name].get("cardDiscount")
            self.assertIsNotNone(got, f"{name} lost its cardDiscount")
            self.assertEqual(got.get("amount"), amount, name)
            self.assertEqual(got.get("tag"), tag, name)

    def test_resource_type(self):
        self.assertEqual(CARDS["Physics Complex"]["resourceType"], "science")
        self.assertEqual(CARDS["Predators"]["resourceType"], "animal")
        self.assertEqual(CARDS["Tardigrades"]["resourceType"], "microbe")
        self.assertIsNone(CARDS["Ironworks"]["resourceType"])


class TestBespokeMethods(unittest.TestCase):
    def test_bespoke_play_card_lists_its_hook(self):
        self.assertIn("bespokePlay", CARDS["Sabotage"]["bespokeMethods"])
        self.assertTrue(CARDS["Sabotage"]["bespoke"])

    def test_tile_trigger_card_is_bespoke(self):
        # Immigrant City's "when a city is placed" lives in an onTilePlaced
        # method; the old rule (bespokePlay only) missed it.
        self.assertIn("onTilePlaced", CARDS["Immigrant City"]["bespokeMethods"])
        self.assertTrue(CARDS["Immigrant City"]["bespoke"])

    def test_card_played_trigger_is_bespoke(self):
        self.assertIn("onCardPlayed", CARDS["Olympus Conference"]["bespokeMethods"])

    def test_purely_declarative_card_is_not_bespoke(self):
        self.assertFalse(CARDS["Ironworks"].get("bespoke"))
        self.assertNotIn("bespokeMethods", CARDS["Ironworks"])

    def test_bespoke_is_exactly_bool_of_bespoke_methods(self):
        for c in DB["cards"]:
            self.assertEqual(bool(c.get("bespoke")),
                             bool(c.get("bespokeMethods")), c["name"])


class TestOrChoicePatch(unittest.TestCase):
    """tmlib.OR_CHOICE_PATCHES moved into the db, in the vocabulary the
    engine already understands, so phase 2 can delete the table."""

    def test_imported_hydrogen_branches(self):
        beh = CARDS["Imported Hydrogen"]["behavior"]
        self.assertEqual(beh.get("ocean"), {})   # non-optional part survives
        branches = beh["or"]["behaviors"]
        self.assertEqual(len(branches), 3)
        self.assertEqual(branches[0]["stock"], {"plants": 3})
        self.assertEqual(branches[1]["addResourcesToAnother"],
                         {"type": "microbes", "count": 3})
        self.assertEqual(branches[2]["addResourcesToAnother"],
                         {"type": "animals", "count": 2})

    def test_the_engine_no_longer_carries_the_patch_table(self):
        # phase 2 deleted tmlib.OR_CHOICE_PATCHES — or_branches reads the db.
        import tmlib
        self.assertFalse(hasattr(tmlib, "OR_CHOICE_PATCHES"))
        titles = [b["title"] for b in
                  tmlib.or_branches(CARDS["Imported Hydrogen"])]
        self.assertEqual(titles[0], "Gain 3 plants")
        self.assertEqual(len(titles), 3)


class TestReserveUnitsSpend(unittest.TestCase):
    """The vendor spells a card's PLAY-TIME resource cost as the constructor
    property `reserveUnits: {heat: 5}` — a sibling of `behavior`, not part of
    it. Cards using that shape (Local Heat Trapping in base/Corporate Era,
    most of the Moon module) had their cost silently dropped: the db said
    `behavior: null` while the card text says "Spend 5 heat". reserveUnits is
    never repeated inside `behavior`, so it maps 1:1 onto the engine's own
    `spend` vocabulary."""

    def test_local_heat_trapping_spends_five_heat(self):
        beh = CARDS["Local Heat Trapping"]["behavior"]
        self.assertIsNotNone(beh, "Local Heat Trapping lost its behavior block")
        self.assertEqual(beh.get("spend"), {"heat": 5})

    def test_the_prose_still_says_spend_5_heat(self):
        self.assertIn("Spend 5 heat", CARDS["Local Heat Trapping"]["effects"])

    @unittest.skipUnless(VENDOR.exists(), "vendor clone absent (git-ignored)")
    def test_every_vendor_reserve_units_reaches_the_db(self):
        """Shape-level, not card-level: whatever the vendor declares as
        reserveUnits must show up as a `spend` in that card's behavior."""
        import re

        import extract_cards as ex

        cardnames = ex.parse_cardnames(VENDOR)
        imports, entries = ex.parse_manifests(VENDOR)
        checked = 0
        for _module, _section, key, cls in entries:
            name = cardnames[key]
            if name not in CARDS:
                continue
            path = imports.get(cls)
            if path is None or not path.exists():
                continue
            src = ex.strip_comments(path.read_text(encoding="utf-8"))
            raw = ex.field_value(src, "reserveUnits")
            if not raw:
                continue
            units = ex.parse_reserve_units(raw)
            if not units:
                continue
            checked += 1
            beh = CARDS[name]["behavior"] or {}
            spend = beh.get("spend") or {}
            for res, qty in units.items():
                self.assertEqual(spend.get(res), qty,
                                 f"{name}: reserveUnits {res}={qty} missing "
                                 f"from behavior.spend ({spend!r})")
        self.assertGreaterEqual(checked, 1, "no reserveUnits card exercised")


@unittest.skipUnless(VENDOR.exists(), "vendor clone absent (git-ignored)")
class TestDeterminism(unittest.TestCase):
    def test_two_runs_are_byte_identical(self):
        import tempfile
        outs = []
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(2):
                out = Path(tmp) / f"db{i}.json"
                r = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / "extract_cards.py"),
                     "--out", str(out)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                outs.append(out.read_bytes())
        self.assertEqual(outs[0], outs[1])


if __name__ == "__main__":
    unittest.main()
