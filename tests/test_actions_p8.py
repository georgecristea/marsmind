"""P8 issues #11, #12, #7 (private/plans/p8-issues.md).

#11/#12: `apply.py action use` applied the once-per-generation LEDGER only
for Physics Complex (no −6 energy, no science resource) and Aquifer Pumping
(no −8 MC, no ocean, no TR) — a verify mismatch and a recovery call every
generation of games/2026-08-28-game2. Blue-card actions with a printed cost
must be modeled like Water Import From Europa already is.

#7: Imported Hydrogen ("Gain 3 plants, or add 3 microbes or 2 animals to
ANOTHER card") was played without a `choice`; the engine applied NO branch
while the app auto-picked the only executable one → `✗ plants: engine 0,
app 3`. When exactly one branch is executable the engine must apply it.
"""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError, card_holds_resource


class Base(unittest.TestCase):
    SETUP = {
        "playerCount": 3,
        "players": [
            {"name": "Zed", "color": "red", "isMe": True, "aliases": ["red"]},
            {"name": "Anna", "color": "green", "isMe": False, "aliases": []},
            {"name": "Ben", "color": "yellow", "isMe": False, "aliases": []},
        ],
        "expansions": ["base", "corporateEra"],
        "map": "tharsis",
        "draft": False,
        "houseRules": [],
        "seatingOrder": ["Zed", "Anna", "Ben"],
        "firstPlayerGen1": "Anna",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(self.SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def me(self):
        return self.game()["me"]

    def play_mine(self, card, **kw):
        """Bankroll + play a card of mine so its blue action is registered."""
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add([card])
        return self.eng.play("Zed", card, **kw)


class TestPhysicsComplex(Base):
    """#11 — energy −6, +1 science resource on the card (VP 2 per)."""

    def test_action_spends_6_energy_and_adds_a_science_resource(self):
        self.play_mine("Physics Complex")
        self.eng.res("Zed", "energy", +7)
        msg = self.eng.use_action("Physics Complex")
        me = self.me()
        self.assertEqual(me["resources"]["energy"], 1)
        self.assertEqual(me["cardResources"]["Physics Complex"], 1)
        self.assertIn("science", msg)

    def test_second_use_next_generation_stacks_resources(self):
        self.play_mine("Physics Complex")
        self.eng.res("Zed", "energy", +12)
        self.eng.use_action("Physics Complex")
        self.me()["actionsThisGen"]["Physics Complex"]["used"] = False
        g = self.game()
        g["me"]["actionsThisGen"]["Physics Complex"]["used"] = False
        self.store.save_game(g)
        self.eng.use_action("Physics Complex")
        self.assertEqual(self.me()["cardResources"]["Physics Complex"], 2)
        self.assertEqual(self.me()["resources"]["energy"], 0)

    def test_too_little_energy_refuses_for_me(self):
        self.play_mine("Physics Complex")
        self.eng.res("Zed", "energy", +5)
        with self.assertRaises(EventError) as cm:
            self.eng.use_action("Physics Complex")
        self.assertIn("6", str(cm.exception))
        self.assertEqual(self.me()["resources"]["energy"], 5)   # no mutation
        self.assertFalse(
            self.me()["actionsThisGen"]["Physics Complex"]["used"])

    def test_opponent_energy_estimate_clamps_instead_of_raising(self):
        self.eng.res("Anna", "mc", +99)
        self.eng.play("Anna", "Physics Complex")
        self.eng.res("Anna", "energy", +2)
        msg = self.eng.use_action("Physics Complex", player="Anna")
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["resources"]["energy"], 0)
        self.assertEqual(anna["cardResources"]["Physics Complex"], 1)
        self.assertIn("clamped", msg)


class TestAquiferPumping(Base):
    """#12 — MC −8 (steel may pay), oceans +1, TR +1, tile placed at table."""

    def test_action_spends_8_mc_raises_oceans_and_tr(self):
        self.play_mine("Aquifer Pumping", steel=0)
        mc = self.me()["resources"]["mc"]
        tr = self.me()["tr"]
        msg = self.eng.use_action("Aquifer Pumping")
        self.assertEqual(self.me()["resources"]["mc"], mc - 8)
        self.assertEqual(self.game()["globals"]["oceans"], 1)
        self.assertEqual(self.me()["tr"], tr + 1)
        self.assertIn("place the ocean tile", msg)

    def test_steel_may_pay_for_the_action(self):
        self.play_mine("Aquifer Pumping")
        self.eng.res("Zed", "steel", +4)
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Aquifer Pumping", steel=4)
        self.assertEqual(self.me()["resources"]["mc"], mc)   # 4 steel = 8 MC
        self.assertEqual(self.me()["resources"]["steel"], 0)

    def test_not_enough_mc_refuses(self):
        self.play_mine("Aquifer Pumping")
        g = self.game()
        g["me"]["resources"]["mc"] = 3
        self.store.save_game(g)
        with self.assertRaises(EventError):
            self.eng.use_action("Aquifer Pumping")
        self.assertEqual(self.game()["globals"]["oceans"], 0)

    def test_oceans_maxed_costs_nothing_and_grants_no_tr(self):
        self.play_mine("Aquifer Pumping")
        g = self.game()
        g["globals"]["oceans"] = 9
        self.store.save_game(g)
        tr = self.me()["tr"]
        msg = self.eng.use_action("Aquifer Pumping")
        self.assertEqual(self.me()["tr"], tr)
        self.assertIn("maxed", msg)


class TestOtherCostedActions(Base):
    """Same family, modeled with the two the game exposed: Ironworks /
    Steelworks (4 energy → steel + O2 step) and Caretaker Contract."""

    def test_ironworks_4_energy_1_steel_and_oxygen_step(self):
        self.play_mine("Ironworks")
        self.eng.res("Zed", "energy", +4)
        tr = self.me()["tr"]
        self.eng.use_action("Ironworks")
        me = self.me()
        self.assertEqual(me["resources"]["energy"], 0)
        self.assertEqual(me["resources"]["steel"], 1)
        self.assertEqual(self.game()["globals"]["oxygen"], 1)
        self.assertEqual(me["tr"], tr + 1)

    def test_steelworks_4_energy_2_steel_and_oxygen_step(self):
        self.play_mine("Steelworks")
        self.eng.res("Zed", "energy", +4)
        tr = self.me()["tr"]
        self.eng.use_action("Steelworks")
        me = self.me()
        self.assertEqual(me["resources"]["energy"], 0)
        self.assertEqual(me["resources"]["steel"], 2)
        self.assertEqual(self.game()["globals"]["oxygen"], 1)
        self.assertEqual(me["tr"], tr + 1)

    def test_caretaker_contract_8_heat_for_1_tr(self):
        self.play_mine("Caretaker Contract",
                       ignore_requirements="test: temperature waived")
        self.eng.res("Zed", "heat", +8)
        tr = self.me()["tr"]
        self.eng.use_action("Caretaker Contract")
        self.assertEqual(self.me()["resources"]["heat"], 0)
        self.assertEqual(self.me()["tr"], tr + 1)

    def test_caretaker_contract_short_of_heat_refuses(self):
        self.play_mine("Caretaker Contract",
                       ignore_requirements="test: temperature waived")
        self.eng.res("Zed", "heat", +7)
        with self.assertRaises(EventError):
            self.eng.use_action("Caretaker Contract")
        self.assertEqual(self.me()["tr"], 20)


class TestOrChoiceAutoBranch(Base):
    """#7 — one executable branch is applied; several still refuse."""

    def test_imported_hydrogen_gains_plants_when_no_resource_card(self):
        self.eng.res("Zed", "mc", +99)
        self.eng.res("Zed", "titanium", +3)
        self.eng.hand_add(["Imported Hydrogen"])
        msg = self.eng.play("Zed", "Imported Hydrogen")
        me = self.me()
        self.assertEqual(me["resources"]["plants"], 3)
        self.assertEqual(self.game()["globals"]["oceans"], 1)   # still an ocean
        self.assertIn("only branch", msg)

    def test_imported_hydrogen_refuses_when_a_microbe_host_is_in_play(self):
        self.play_mine("Tardigrades")           # holds microbes
        self.eng.hand_add(["Imported Hydrogen"])
        with self.assertRaises(EventError) as cm:
            self.eng.play("Zed", "Imported Hydrogen")
        self.assertIn("--choice", str(cm.exception))
        self.assertEqual(self.me()["resources"]["plants"], 0)

    def test_explicit_choice_still_wins_over_the_auto_branch(self):
        self.play_mine("Tardigrades")
        self.eng.hand_add(["Imported Hydrogen"])
        msg = self.eng.play("Zed", "Imported Hydrogen", choice=1)
        self.assertEqual(self.me()["resources"]["plants"], 0)
        self.assertIn("ANOTHER card", msg)

    def test_an_opponents_ambiguous_branch_is_flagged_not_refused(self):
        # Opponent state is an estimate and a log line must never be blocked
        # (the replay fixture plays exactly this card for Anna, who owns
        # Predators): the card is still CHARGED and the ocean still rises.
        self.eng.res("Anna", "mc", +99)
        self.eng.play("Anna", "Predators", ignore_requirements="test")
        mc = self.game()["opponents"]["Anna"]["resources"]["mc"]
        msg = self.eng.play("Anna", "Imported Hydrogen")
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["resources"]["mc"], mc - 16)   # cost charged
        self.assertEqual(self.game()["globals"]["oceans"], 1)
        self.assertEqual(anna["resources"]["plants"], 0)     # no branch guessed
        self.assertIn("not recorded", msg)

    def test_two_executable_branches_still_refuse(self):
        # Artificial Photosynthesis: both branches are production changes,
        # both always executable — the "say which" error must survive for
        # MY play (an opponent's is flagged, see the test above).
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add(["Artificial Photosynthesis"])
        with self.assertRaises(EventError) as cm:
            self.eng.play("Zed", "Artificial Photosynthesis")
        self.assertIn("--choice 0", str(cm.exception))


class TestHelionStandardProjects(Base):
    """p8 #19 — execute.py's payment splitter sends a standard project as
    mc + heat for Helion (asteroid 14 = mc 0 + heat 14), but Engine.standard
    knew only MC and refused the very event it had just transmitted, so
    verify_step's sandbox raised too. Mirrors play()'s Helion branch."""

    def helion(self, mc=0, heat=0):
        self.eng.corp("Zed", "Helion", mc=mc)
        if heat:
            self.eng.res("Zed", "heat", +heat)

    def test_asteroid_paid_entirely_with_heat(self):
        self.helion(mc=0, heat=23)
        self.eng.standard("Zed", "asteroid", heat=14)
        me = self.me()
        self.assertEqual(me["resources"]["mc"], 0)
        self.assertEqual(me["resources"]["heat"], 9)
        self.assertEqual(me["tr"], 21)
        self.assertEqual(self.game()["globals"]["temperature"], -28)

    def test_greenery_splits_mc_then_heat(self):
        self.helion(mc=21, heat=18)
        self.eng.standard("Zed", "greenery", heat=2)
        me = self.me()
        self.assertEqual(me["resources"]["mc"], 0)      # 23 = 21 MC + 2 heat
        self.assertEqual(me["resources"]["heat"], 16)
        self.assertEqual(me["tiles"]["greeneries"], 1)

    def test_the_trace_names_the_heat(self):
        self.helion(mc=0, heat=23)
        msg = self.eng.standard("Zed", "asteroid", heat=14)
        self.assertIn("heat", msg)

    def test_a_non_helion_corp_may_not_pay_with_heat(self):
        self.eng.corp("Zed", "Thorgate", mc=30)
        self.eng.res("Zed", "heat", +20)
        with self.assertRaises(EventError) as cm:
            self.eng.standard("Zed", "asteroid", heat=14)
        self.assertIn("Helion", str(cm.exception))
        self.assertEqual(self.me()["resources"]["mc"], 30)

    def test_more_heat_than_held_refuses(self):
        self.helion(mc=0, heat=5)
        with self.assertRaises(EventError):
            self.eng.standard("Zed", "asteroid", heat=14)
        self.assertEqual(self.game()["globals"]["temperature"], -30)

    def test_heat_short_of_the_price_still_needs_the_mc(self):
        self.helion(mc=3, heat=10)
        with self.assertRaises(EventError):
            self.eng.standard("Zed", "asteroid", heat=10)   # 4 MC due, have 3
        self.assertEqual(self.me()["resources"]["heat"], 10)

    def test_mc_only_path_is_unchanged(self):
        self.eng.corp("Zed", "Helion", mc=40)
        self.eng.res("Zed", "heat", +9)
        self.eng.standard("Zed", "asteroid")
        me = self.me()
        self.assertEqual(me["resources"]["mc"], 26)
        self.assertEqual(me["resources"]["heat"], 9)


class TestCardHoldsResource(Base):
    def test_known_hosts_and_non_hosts(self):
        for name, kind in (("Tardigrades", "microbe"), ("Ants", "microbe"),
                           ("Birds", "animal"), ("Physics Complex", "science"),
                           ("Nitrite Reducing Bacteria", "microbe")):
            self.assertTrue(card_holds_resource(self.eng.card(name), kind),
                            f"{name} should host {kind}s")
        for name, kind in (("Ironworks", "microbe"), ("Steelworks", "animal"),
                           ("Imported Hydrogen", "microbe"),
                           ("Tardigrades", "animal")):
            self.assertFalse(card_holds_resource(self.eng.card(name), kind),
                             f"{name} should NOT host {kind}s")


class TestActionSteelFlag(Base):
    """P8 #24 — `apply.py action use … --steel N` (Engine.use_action already
    took steel=; the CLI had no way to say it, so ore paid at the table was
    tracked as MC)."""

    def test_cli_steel_flag_charges_4_mc_and_2_steel(self):
        import subprocess
        self.play_mine("Aquifer Pumping")
        self.eng.res("Zed", "steel", +2)
        mc = self.me()["resources"]["mc"]
        script = Path(__file__).resolve().parent.parent / "scripts" / "apply.py"
        r = subprocess.run([sys.executable, str(script), "action", "use",
                            "Aquifer Pumping", "--steel", "2"],
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        me = self.me()
        self.assertEqual(me["resources"]["mc"], mc - 4)   # 2 steel = 4 MC
        self.assertEqual(me["resources"]["steel"], 0)
        self.assertEqual(self.game()["globals"]["oceans"], 1)

    def test_action_help_mentions_steel(self):
        import contextlib, io, apply
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            apply.main(["action", "--help"])
        self.assertIn("--steel", out.getvalue())


class TestCitiesOnMarsFromBoard(Base):
    """AGENTS.md: TILE COUNTS COME FROM game['board'], never the derived
    tiles{} cache — `place` records the hex but does not touch the cache, so
    Martian Rails / Zeppelins paid 0 until verify.py --sync ran."""

    def test_two_placed_cities_pay_2_without_a_verify_sync(self):
        self.play_mine("Martian Rails")
        self.eng.res("Zed", "energy", +1)
        self.eng.place("Zed", "city", "05")
        self.eng.place("Anna", "city", "20")     # any player's city counts
        self.assertEqual(self.me()["tiles"]["cities"], 0)   # cache untouched
        mc = self.me()["resources"]["mc"]
        msg = self.eng.use_action("Martian Rails")
        self.assertEqual(self.me()["resources"]["mc"], mc + 2, msg)

    def test_a_mat_tracked_city_with_no_hex_still_counts(self):
        """Physical mode / photo snapshots: an opponent's cities arrive as
        counters (tiles_fix / observe) with no hex. The board is truth, but
        the counter is a floor — never undercount a city that is on the
        table (verify.py reports the drift and --sync repairs it)."""
        self.play_mine("Martian Rails")
        self.eng.res("Zed", "energy", +1)
        self.eng.tiles_fix("Anna", "cities", 3)     # mat photo, no hexes
        self.eng.place("Zed", "city", "05")         # my own, on the board
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Martian Rails")
        self.assertEqual(self.me()["resources"]["mc"], mc + 4)

    def test_reserved_area_city_is_off_mars_and_never_counts(self):
        self.play_mine("Martian Rails")
        self.eng.res("Zed", "energy", +1)
        self.play_mine("Ganymede Colony")        # off-Mars, fixed slot
        self.assertEqual(self.me()["tiles"]["cities"], 1)
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Martian Rails")
        self.assertEqual(self.me()["resources"]["mc"], mc)   # 0 cities ON MARS


class TestUnuseAction(Base):
    """P8 #23 — Engine.unuse_action: the exact inverse of the modeled
    effects, so correct.py can reverse a `use_action` plan step."""

    def test_martian_rails_gives_back_energy_and_takes_the_mc(self):
        self.play_mine("Martian Rails")
        self.eng.res("Zed", "energy", +1)
        self.eng.place("Zed", "city", "05")   # 1 city ON MARS → +1 MC/use
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Martian Rails")
        self.assertEqual(self.me()["resources"]["mc"], mc + 1)
        self.eng.unuse_action("Martian Rails")
        me = self.me()
        self.assertEqual(me["resources"]["mc"], mc)
        self.assertEqual(me["resources"]["energy"], 1)
        self.assertFalse(me["actionsThisGen"]["Martian Rails"]["used"])

    def test_water_import_from_europa_refunds_12_and_drops_the_ocean(self):
        self.play_mine("Water Import From Europa")
        mc = self.me()["resources"]["mc"]
        tr = self.me()["tr"]
        self.eng.use_action("Water Import From Europa")
        self.eng.unuse_action("Water Import From Europa")
        me = self.me()
        self.assertEqual(me["resources"]["mc"], mc)
        self.assertEqual(me["tr"], tr)
        self.assertEqual(self.game()["globals"]["oceans"], 0)

    def test_steelworks_reversed_exactly(self):
        self.play_mine("Steelworks")
        self.eng.res("Zed", "energy", +4)
        tr = self.me()["tr"]
        self.eng.use_action("Steelworks")
        self.eng.unuse_action("Steelworks")
        me = self.me()
        self.assertEqual(me["resources"]["energy"], 4)
        self.assertEqual(me["resources"]["steel"], 0)
        self.assertEqual(me["tr"], tr)
        self.assertEqual(self.game()["globals"]["oxygen"], 0)

    def test_aquifer_pumping_paid_with_steel_is_refunded_in_steel(self):
        self.play_mine("Aquifer Pumping")
        self.eng.res("Zed", "steel", +2)
        mc = self.me()["resources"]["mc"]
        self.eng.use_action("Aquifer Pumping", steel=2)
        self.eng.unuse_action("Aquifer Pumping", steel=2)
        me = self.me()
        self.assertEqual(me["resources"]["mc"], mc)
        self.assertEqual(me["resources"]["steel"], 2)
        self.assertEqual(self.game()["globals"]["oceans"], 0)

    def test_nitrite_branch_must_be_named_and_both_branches_invert(self):
        self.play_mine("Nitrite Reducing Bacteria")
        self.eng.use_action("Nitrite Reducing Bacteria", choice=0)
        with self.assertRaises(EventError):          # which branch?
            self.eng.unuse_action("Nitrite Reducing Bacteria")
        self.eng.unuse_action("Nitrite Reducing Bacteria", choice=0)
        me = self.me()
        self.assertEqual(me["cardResources"]["Nitrite Reducing Bacteria"], 3)
        self.assertFalse(
            me["actionsThisGen"]["Nitrite Reducing Bacteria"]["used"])

    def test_uninvertible_effect_raises_and_commits_nothing(self):
        """The science resource is already gone (spent elsewhere): refuse,
        leaving the energy AND the ledger untouched — never a half-undo."""
        self.play_mine("Physics Complex")
        self.eng.res("Zed", "energy", +6)
        self.eng.use_action("Physics Complex")
        g = self.game()
        g["me"]["cardResources"]["Physics Complex"] = 0
        self.store.save_game(g)
        with self.assertRaises(EventError):
            self.eng.unuse_action("Physics Complex")
        me = self.me()
        self.assertEqual(me["resources"]["energy"], 0)
        self.assertTrue(me["actionsThisGen"]["Physics Complex"]["used"])

    def test_opponent_action_effect_is_reversed_without_a_ledger(self):
        self.eng.res("Anna", "mc", +30)
        self.eng.hand_add([])
        self.eng.play("Anna", "Aquifer Pumping")
        tr = self.game()["opponents"]["Anna"]["tr"]
        self.eng.use_action("Aquifer Pumping", player="Anna")
        self.eng.unuse_action("Aquifer Pumping", player="Anna")
        opp = self.game()["opponents"]["Anna"]
        self.assertEqual(opp["tr"], tr)
        self.assertEqual(self.game()["globals"]["oceans"], 0)


if __name__ == "__main__":
    unittest.main()
