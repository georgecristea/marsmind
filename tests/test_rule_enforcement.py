"""First-player exception, steel/titanium tag restriction, milestone eligibility."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestGenerationCorrection(Base):
    """produce.py once ran before all seats' real
    turns were logged (only app-side 'not currently waiting' was checked,
    which isn't the same as a received report) — a wrong income round was
    applied to every opponent and generation/firstPlayer advanced one
    step too far. Recovering needed a way to set generation back
    explicitly; there wasn't one (set_first_player existed, its
    generation equivalent didn't)."""

    def test_set_generation_corrects_and_logs(self):
        self.eng.produce()                    # 1 -> 2
        self.assertEqual(self.game()["generation"], 2)
        msg = self.eng.set_generation(1)
        self.assertEqual(self.game()["generation"], 1)
        self.assertIn("2", msg)
        self.assertIn("1", msg)

    def test_rejects_non_positive(self):
        with self.assertRaises(EventError):
            self.eng.set_generation(0)


class TestFirstPlayerException(Base):
    def test_override_first_player_and_logged(self):
        self.eng.set_first_player("blue")           # alias/color resolution
        self.assertEqual(self.game()["firstPlayer"], "Felix")
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("First player", log)
        self.assertIn("exception", log.lower())

    def test_rotation_continues_from_override(self):
        self.eng.set_first_player("Zed")
        self.eng.produce()
        self.assertEqual(self.game()["firstPlayer"], "Anna")  # next seat


class TestSteelTitaniumTags(Base):
    def test_steel_rejected_on_non_building_card(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.res("Zed", "steel", +3)
        self.eng.hand_add(["Comet"])                # space, no building tag
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Comet", steel=2)

    def test_titanium_ok_on_space_card(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.res("Zed", "titanium", +2)
        self.eng.hand_add(["Comet"])
        self.eng.play("Zed", "Comet", titanium=2)  # 21 − 6 = 15 MC
        self.assertEqual(self.game()["me"]["resources"]["mc"], 15)

    def test_titanium_rejected_on_building_only_card(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.res("Zed", "titanium", +2)
        self.eng.hand_add(["Strip Mine"])           # building, not space
        self.eng.prod("Zed", "energy", +2)
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Strip Mine", titanium=1)

    def test_steel_ok_on_building_card(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.res("Zed", "steel", +2)
        self.eng.prod("Zed", "energy", +2)
        self.eng.hand_add(["Strip Mine"])           # cost 25, building
        self.eng.play("Zed", "Strip Mine", steel=2)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 9)

    def test_unknown_card_payment_allowed_with_flag(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.res("Zed", "steel", +2)
        self.eng.hand_add(["Homebrew Thing"])
        msg = self.eng.play("Zed", "Homebrew Thing", cost=10, steel=2)
        self.assertIn("verify", msg.lower())        # unverifiable tag flagged


class TestMilestoneEligibility(Base):
    def test_terraformer_blocked_below_tr35_for_me(self):
        self.eng.res("Zed", "mc", +20)
        with self.assertRaises(EventError):
            self.eng.milestone("Zed", "Terraformer")   # TR 20

    def test_terraformer_ok_at_tr35(self):
        self.eng.res("Zed", "mc", +20)
        self.eng.tr("Zed", +15)                  # TR 35
        self.eng.milestone("Zed", "Terraformer")
        self.assertEqual(self.game()["milestonesClaimed"],
                         {"Terraformer": "Zed"})

    def test_mayor_needs_3_cities(self):
        self.eng.res("Zed", "mc", +100)
        with self.assertRaises(EventError):
            self.eng.milestone("Zed", "Mayor")
        for _ in range(3):
            self.eng.standard("Zed", "city")
        self.eng.milestone("Zed", "Mayor")

    def test_builder_counts_building_tags_from_played_cards(self):
        self.eng.res("Zed", "mc", +20)
        with self.assertRaises(EventError):
            self.eng.milestone("Zed", "Builder")

    def test_builder_counts_corporation_tags_too(self):
        # Mining Guild carries TWO building tags on
        # the corp card itself; the app accepted Builder at 6 card tags +
        # 2 corp tags while the tracker refused at "6 of 8". Corp tags
        # count toward milestones exactly like played-card tags — and per
        # tag, not per card.
        self.eng.corp("Zed", "Mining Guild", mc=30)
        self.eng.res("Zed", "mc", +100)
        self.eng.prod("Zed", "energy", +3)     # Strip Mine −2, Rad-Chem −1
        for c in ("Aquifer Pumping", "Steelworks", "Mining Rights",
                  "Strip Mine", "Rover Construction", "Rad-Chem Factory"):
            self.eng.hand_add([c])
            self.eng.play("Zed", c)
        self.eng.milestone("Zed", "Builder")     # 6 + 2 corp = 8
        self.assertEqual(self.game()["milestonesClaimed"],
                         {"Builder": "Zed"})

    def test_planner_needs_16_cards_in_hand(self):
        self.eng.res("Zed", "mc", +20)
        with self.assertRaises(EventError):
            self.eng.milestone("Zed", "Planner")
        self.eng.hand_add([f"C{i}" for i in range(16)])
        self.eng.milestone("Zed", "Planner")

    def test_opponent_claim_warns_but_records(self):
        self.eng.res("Anna", "mc", +20)
        msg = self.eng.milestone("Anna", "Gardener")   # 0 known greeneries
        self.assertIn("Gardener", self.game()["milestonesClaimed"])
        self.assertIn("⚠", msg)                     # apparent-ineligibility warning


if __name__ == "__main__":
    unittest.main()


class TestEventTagsDontPersist(Base):
    def test_builder_count_excludes_event_building_tags(self):
        # play a building-tag EVENT — must not count toward Builder
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add(["Test Event"])
        self.eng.play("Zed", "Test Event", cost=1)   # unknown card: no tags anyway
        # deterministic check via the counting helper on a known event:
        import tmlib
        game = self.store.load_game()
        game["me"]["playedCards"] = [
            {"name": "Comet", "gen": 1},               # event, space tag
            {"name": "Strip Mine", "gen": 1},          # automated, building
        ]
        self.store.save_game(game)
        with self.assertRaises(tmlib.EventError) as ctx:
            self.eng.milestone("Zed", "Builder")
        self.assertIn("has 1", str(ctx.exception))     # only Strip Mine counts


class TestRegisterActionCost(unittest.TestCase):
    """Pass-gate false positive: re-registering must parse mcCost."""
    def setUp(self):
        import tempfile as _tf
        from test_new_game import SETUP as _S
        self.tmp = _tf.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(_S)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_parses_mc_cost_from_db(self):
        self.eng.register_action("Underground Detonations")
        g = self.store.load_game()
        entry = g["me"]["actionsThisGen"]["Underground Detonations"]
        self.assertEqual(entry["mcCost"], 10)

    def test_register_parses_heat_cost_from_db(self):
        self.eng.register_action("Caretaker Contract")   # "Spend 8 heat…"
        g = self.store.load_game()
        entry = g["me"]["actionsThisGen"]["Caretaker Contract"]
        self.assertEqual(entry["heatCost"], 8)
        self.assertNotIn("mcCost", entry)                # heat is not MC

    def test_play_registers_heat_cost(self):
        self.eng.res("Zed", "mc", +10)
        self.eng.hand_add(["Caretaker Contract"])
        self.eng.play("Zed", "Caretaker Contract", ignore_requirements=True)
        g = self.store.load_game()
        entry = g["me"]["actionsThisGen"]["Caretaker Contract"]
        self.assertEqual(entry["heatCost"], 8)
        self.assertFalse(entry["used"])
