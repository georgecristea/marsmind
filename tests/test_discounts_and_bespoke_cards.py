"""Discounts, ocean triggers, bespoke cards, draft variant, own-panel sync.

Ground truth: the online app's own log of a real game (names aliased).
Every number below is one the app printed:

- discounts: Teractor Earth −3 (Zed), ThorGate power −3 + Power
      Plant SP 8 (Carl), CrediCor +4 after a BASE-cost ≥20 card/SP (Ben:
      Immigration Shuttles, Greenery SP), Earth Catapult / Space Station /
      Earth Office (Anna), Research Outpost (Carl) — none were auto-applied.
- a World Government ocean fires Arctic Algae ("Anna gained 2 plants
      from Arctic Algae" after every WGT ocean).
- bespoke cards formerly replayed by hand: Zeppelins +7 (cities ON MARS),
      Greenhouses +9 (all cities), Immigrant City, Power Supply Consortium,
      Sabotage, Martian Rails 3/5/6/7, Media Archives +9, Toll Station +4,
      Terraforming Ganymede +4 TR, Water Import From Europa, Indentured
      Workers → Open City, Nitrite Reducing Bacteria, Robotic Workforce
      copying Nuclear Power, Olympus Conference; `--no-effects`.
- draft variant visible: brief header + `dealt --drafted`.
- `sync me --mc …` own-panel correction verb.
"""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tmlib
from tmlib import Store, Engine, EventError
from test_new_game import SETUP
from test_cli import run, SETUP_ANSWERS

ROOT = Path(__file__).resolve().parent.parent


def _setup(**over):
    s = json.loads(json.dumps(SETUP))
    s.update(over)
    return s


class Base(unittest.TestCase):
    setup = SETUP

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(self.setup)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def me(self):
        return self.game()["me"]

    def opp(self, name):
        return self.game()["opponents"][name]

    def log(self):
        return self.store.log_path.read_text()

    def give(self, player, card, mc=99):
        """Put a card in play position: MC for anyone, hand for me."""
        self.eng.res(player, "mc", +mc)
        if player == "Zed":
            self.eng.hand_add([card])


# ══════════════════════════════════════════════════════════════
# discounts
# ══════════════════════════════════════════════════════════════

class TestDiscountsAreDbData(unittest.TestCase):
    """The engine's DISCOUNTS table is gone: card-cost discounts are read
    from the db's `cardDiscount` (vendor data), and only ThorGate's
    STANDARD-PROJECT half — a TypeScript hook with no data — is hand-coded,
    in tmlib's one corporations table."""

    def test_every_discount_source_is_db_data(self):
        self.assertFalse(hasattr(tmlib, "DISCOUNTS"))
        for n in ("Teractor", "ThorGate", "Earth Catapult", "Research Outpost",
                  "Space Station", "Earth Office", "Mass Converter",
                  "Quantum Extractor", "Shuttles", "Anti-Gravity Technology"):
            hit = tmlib.card_discount_spec(n)
            self.assertIsNotNone(hit, n)
            canon, spec = hit
            self.assertEqual(canon, n)
            self.assertIsInstance(spec["amount"], int, n)
            self.assertGreater(spec["amount"], 0, n)

    def test_thorgate_standard_project_discount_stays_in_the_corp_table(self):
        self.assertEqual(tmlib.corp_rule("ThorGate", "standardDiscount"),
                         {"power_plant": 3})
        self.assertEqual(tmlib.corp_rule("thorgate", "standardDiscount"),
                         {"power_plant": 3})       # case-insensitive

    def test_a_card_without_a_discount_reads_as_none(self):
        self.assertIsNone(tmlib.card_discount_spec("Ironworks"))


class TestCorpDiscounts(Base):
    def test_teractor_own_earth_card(self):
        self.eng.corp("Zed", "Teractor", mc=60)
        self.eng.hand_add(["Sponsors"])                 # earth, 6
        msg = self.eng.play("Zed", "Sponsors")
        self.assertEqual(self.me()["resources"]["mc"], 57)
        self.assertIn("paid 3 MC (base 6", msg)
        self.assertIn("Teractor −3", msg)

    def test_teractor_opponent_earth_card(self):
        self.eng.corp("Anna", "Teractor", mc=60)
        msg = self.eng.play("Anna", "Sponsors")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 57)
        self.assertIn("paid 3 MC (base 6", msg)

    def test_teractor_not_on_non_earth(self):
        self.eng.corp("Zed", "Teractor", mc=60)
        self.eng.hand_add(["Nuclear Power"])            # power/building, 10
        self.eng.play("Zed", "Nuclear Power")
        self.assertEqual(self.me()["resources"]["mc"], 50)

    def test_thorgate_own_power_card(self):
        self.eng.corp("Zed", "Thorgate", mc=48)     # case-insensitive
        self.eng.hand_add(["Nuclear Power"])
        self.eng.play("Zed", "Nuclear Power")
        self.assertEqual(self.me()["resources"]["mc"], 41)

    def test_thorgate_opponent_power_card(self):
        self.eng.corp("Anna", "ThorGate", mc=48)
        self.eng.play("Anna", "Power Plant")            # power, 4
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 47)

    def test_thorgate_power_plant_standard_project_is_8(self):
        self.eng.corp("Zed", "ThorGate", mc=48)
        msg = self.eng.standard("Zed", "power_plant")
        self.assertEqual(self.me()["resources"]["mc"], 40)
        self.assertIn("8 MC", msg)
        self.assertIn("ThorGate", msg)

    def test_thorgate_power_plant_sp_for_opponent(self):
        self.eng.corp("Anna", "ThorGate", mc=48)
        self.eng.standard("Anna", "power_plant")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 40)

    def test_thorgate_other_standard_projects_full_price(self):
        self.eng.corp("Zed", "ThorGate", mc=48)
        self.eng.standard("Zed", "asteroid")
        self.assertEqual(self.me()["resources"]["mc"], 34)

    def test_non_thorgate_power_plant_sp_is_11(self):
        self.eng.res("Zed", "mc", +20)
        self.eng.standard("Zed", "power_plant")
        self.assertEqual(self.me()["resources"]["mc"], 9)


class TestCredicorRebate(Base):
    def test_opponent_immigration_shuttles(self):
        # applog gen 1: "Ben played Immigration Shuttles … Ben gained 4 M€"
        self.eng.corp("Anna", "CrediCor", mc=57)
        msg = self.eng.play("Anna", "Immigration Shuttles")   # 31
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 30)
        self.assertIn("+4", msg)

    def test_opponent_greenery_sp(self):
        # applog gen 10: "Ben used Greenery standard project / gained 4 M€"
        self.eng.corp("Anna", "CrediCor", mc=57)
        self.eng.standard("Anna", "greenery")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 57 - 23 + 4)

    def test_aquifer_18_does_not_qualify(self):
        self.eng.corp("Anna", "CrediCor", mc=57)
        self.eng.standard("Anna", "aquifer")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 39)

    def test_rebate_keyed_on_base_cost_not_discounted_price(self):
        # Earth Catapult (23) rebates; then Comet 21 → paid 19 but base 21 ≥ 20
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.hand_add(["Earth Catapult", "Comet"])
        self.eng.play("Zed", "Earth Catapult")
        self.assertEqual(self.me()["resources"]["mc"], 57 - 23 + 4)
        self.eng.play("Zed", "Comet")
        self.assertEqual(self.me()["resources"]["mc"], 38 - 19 + 4)


class TestCardDiscounts(Base):
    def test_earth_catapult_minus_2_all_cards(self):
        self.give("Anna", "Earth Catapult")
        self.eng.play("Anna", "Earth Catapult")          # 23
        before = self.opp("Anna")["resources"]["mc"]
        self.eng.play("Anna", "Nuclear Power")           # 10 → 8
        self.assertEqual(self.opp("Anna")["resources"]["mc"], before - 8)

    def test_space_station_minus_2_space_only(self):
        self.give("Zed", "Space Station")
        self.eng.hand_add(["Vesta Shipyard", "Sponsors"])
        self.eng.play("Zed", "Space Station")         # 10
        before = self.me()["resources"]["mc"]
        self.eng.play("Zed", "Vesta Shipyard")        # space 15 → 13
        self.assertEqual(self.me()["resources"]["mc"], before - 13)
        before = self.me()["resources"]["mc"]
        self.eng.play("Zed", "Sponsors")              # earth 6 → 6
        self.assertEqual(self.me()["resources"]["mc"], before - 6)

    def test_research_outpost_minus_1_all(self):
        self.give("Anna", "Research Outpost")
        self.eng.play("Anna", "Research Outpost")        # 18, city tile
        self.assertEqual(self.opp("Anna")["tiles"]["cities"], 1)
        before = self.opp("Anna")["resources"]["mc"]
        self.eng.play("Anna", "Sponsors")                # 6 → 5
        self.assertEqual(self.opp("Anna")["resources"]["mc"], before - 5)

    def test_stacking_teractor_plus_earth_office_never_below_zero(self):
        self.eng.corp("Zed", "Teractor", mc=60)
        self.eng.hand_add(["Earth Office", "Sponsors", "Cartel"])
        self.eng.play("Zed", "Earth Office")          # earth 1 → 0
        self.assertEqual(self.me()["resources"]["mc"], 60)
        msg = self.eng.play("Zed", "Sponsors")        # 6 − 3 − 3 = 0
        self.assertEqual(self.me()["resources"]["mc"], 60)
        self.assertIn("paid 0 MC (base 6", msg)
        self.assertIn("Teractor −3", msg)
        self.assertIn("Earth Office −3", msg)
        self.eng.play("Zed", "Cartel")                # 8 − 6 = 2
        self.assertEqual(self.me()["resources"]["mc"], 58)

    def test_discount_does_not_apply_to_opponents_cards(self):
        self.give("Anna", "Earth Catapult")
        self.eng.play("Anna", "Earth Catapult")
        self.give("Zed", "Sponsors", mc=10)
        self.eng.play("Zed", "Sponsors")
        self.assertEqual(self.me()["resources"]["mc"], 4)

    def test_cost_override_skips_discounts_and_says_so(self):
        self.eng.corp("Zed", "Teractor", mc=60)
        self.eng.hand_add(["Sponsors"])
        msg = self.eng.play("Zed", "Sponsors", cost=6)
        self.assertEqual(self.me()["resources"]["mc"], 54)
        self.assertIn("override", msg)
        self.assertNotIn("Teractor −3", msg)

    def test_steel_still_covers_the_discounted_price(self):
        self.eng.corp("Zed", "ThorGate", mc=48)
        self.eng.res("Zed", "steel", +3)
        self.eng.hand_add(["Nuclear Power"])             # 10 − 3 = 7
        msg = self.eng.play("Zed", "Nuclear Power", steel=3)
        self.assertEqual(self.me()["resources"]["mc"], 47)   # 7 − 6 = 1 MC
        self.assertIn("paid 1 MC (base 10", msg)


# ══════════════════════════════════════════════════════════════
# ocean triggers (Arctic Algae), WGT included
# ══════════════════════════════════════════════════════════════

class TestOceanTriggers(Base):
    setup = _setup(expansions=["base", "corporateEra", "wgt"])

    def _algae(self, player):
        self.give(player, "Arctic Algae")
        self.eng.play(player, "Arctic Algae")            # +1 plant on play

    def _hex(self):
        return next(k for k, v in self.eng._board().items()
                    if v.get("oceanReserved") and v.get("bonus"))

    def test_wgt_ocean_fires_arctic_algae_no_tr(self):
        # applog gen 4: "Ben acted as World Government and placed an ocean /
        # Anna gained 2 plants from Arctic Algae"
        self._algae("Anna")
        tr_before = {n: o["tr"] for n, o in self.game()["opponents"].items()}
        msg = self.eng.wgt("oceans", space_id=self._hex())
        self.assertEqual(self.opp("Anna")["resources"]["plants"], 3)
        self.assertIn("Arctic Algae", msg)
        for n, o in self.game()["opponents"].items():
            self.assertEqual(o["tr"], tr_before[n])
        self.assertEqual(self.me()["tr"], 20)

    def test_wgt_ocean_fires_for_every_holder(self):
        self._algae("Anna")
        self._algae("Zed")
        self.eng.wgt("oceans", space_id=self._hex())
        self.assertEqual(self.opp("Anna")["resources"]["plants"], 3)
        self.assertEqual(self.me()["resources"]["plants"], 3)

    def test_standard_aquifer_by_anyone_fires_it(self):
        self._algae("Anna")
        self.eng.res("Felix", "mc", +30)
        self.eng.standard("Felix", "aquifer")
        self.assertEqual(self.opp("Anna")["resources"]["plants"], 3)

    def test_card_ocean_fires_it(self):
        self._algae("Anna")
        self.give("Zed", "Comet")
        self.eng.play("Zed", "Comet", target="Felix")
        self.assertEqual(self.opp("Anna")["resources"]["plants"], 3)

    def test_wgt_temperature_does_not_fire(self):
        self._algae("Anna")
        self.eng.wgt("temperature")
        self.assertEqual(self.opp("Anna")["resources"]["plants"], 1)

    def test_docs_updated(self):
        # the KB (strategy/) is the rule source shipped with the repo;
        # session notes live outside the tree.
        kb = (ROOT / "strategy" / "02-card-evaluation.md").read_text() \
            if (ROOT / "strategy" / "02-card-evaluation.md").exists() else \
            "".join(p.read_text() for p in (ROOT / "strategy").glob("02*.md"))
        self.assertIn("Arctic Algae", kb)


# ══════════════════════════════════════════════════════════════
# bespoke cards reproduce the app log; --no-effects
# ══════════════════════════════════════════════════════════════

class TestNoEffects(Base):
    def test_no_effects_charges_and_records_only(self):
        self.give("Zed", "Nuclear Power", mc=20)
        msg = self.eng.play("Zed", "Nuclear Power", no_effects=True)
        me = self.me()
        self.assertEqual(me["resources"]["mc"], 10)
        self.assertEqual(me["production"], {r: 0 for r in tmlib.RESOURCES})
        self.assertIn("Nuclear Power", [c["name"] for c in me["playedCards"]])
        self.assertIn("NO EFFECTS", msg)

    def test_no_effects_for_opponent_keeps_tags(self):
        self.give("Anna", "Sponsors")
        self.eng.play("Anna", "Sponsors", no_effects=True)
        o = self.opp("Anna")
        self.assertEqual(o["production"]["mc"], 0)
        self.assertEqual(o["tagCounts"].get("earth"), 1)

    def test_no_effects_skips_city_triggers(self):
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.give("Anna", "Open City")
        self.eng.sync_global("oxygen", 12)
        self.eng.prod("Anna", "energy", +1)
        self.eng.play("Anna", "Open City", no_effects=True)
        self.assertEqual(self.me()["production"]["mc"], 0)
        self.assertEqual(self.opp("Anna")["tiles"]["cities"], 0)


class TestCities(Base):
    """Cities on Mars vs off-Mars (Ganymede Colony, Phobos Space Haven)."""

    def _board_late_game(self):
        # at Carl's Zeppelins (gen 10): Carl 5 + Zed 1 + Ben 1 on Mars,
        # Ben's Ganymede Colony off-Mars → 7 on Mars, 8 in play
        self.eng.tiles_fix("Anna", "cities", 5)
        self.eng.tiles_fix("Zed", "cities", 1)
        self.eng.tiles_fix("Felix", "cities", 1)
        self.give("Felix", "Ganymede Colony")
        self.eng.play("Felix", "Ganymede Colony")

    def test_ganymede_colony_counts_off_mars(self):
        self._board_late_game()
        o = self.opp("Felix")
        self.assertEqual(o["tiles"]["cities"], 2)
        self.assertEqual(o["tiles"]["citiesOffMars"], 1)
        g = self.game()
        self.assertEqual(self.eng._cities_in_play(g), 8)
        self.assertEqual(self.eng._cities_on_mars(g), 7)

    def test_zeppelins_counts_cities_on_mars_only(self):
        # applog: "Carl played Zeppelins / Carl gained 7 M€ production"
        self._board_late_game()
        self.eng.sync_global("oxygen", 5)
        self.give("Anna", "Zeppelins")
        msg = self.eng.play("Anna", "Zeppelins")
        self.assertEqual(self.opp("Anna")["production"]["mc"], 7)
        self.assertIn("7", msg)

    def test_greenhouses_counts_all_cities_incl_off_mars(self):
        # applog: "Anna played Greenhouses / Anna gained 9 plants"
        self._board_late_game()
        self.give("Zed", "Phobos Space Haven")
        self.eng.play("Zed", "Phobos Space Haven")     # Zed 2 (1 off)
        self.give("Anna", "Greenhouses")
        self.eng.play("Anna", "Greenhouses")
        self.assertEqual(self.opp("Anna")["resources"]["plants"], 9)

    def test_phobos_space_haven_is_off_mars_no_tharsis(self):
        self.eng.corp("Anna", "Tharsis Republic", mc=40)
        self.give("Zed", "Phobos Space Haven")
        self.eng.play("Zed", "Phobos Space Haven")
        self.assertEqual(self.opp("Anna")["production"]["mc"], 0)
        self.assertEqual(self.me()["tiles"]["citiesOffMars"], 1)


class TestImmigrantCity(Base):
    def test_play_deltas_including_this(self):
        # applog gen 3: Carl played Immigrant City … "gained 1 M€ production"
        self.eng.prod("Anna", "energy", +1)
        self.give("Anna", "Immigrant City")
        msg = self.eng.play("Anna", "Immigrant City")
        o = self.opp("Anna")
        self.assertEqual(o["production"]["energy"], 0)
        self.assertEqual(o["production"]["mc"], -1)     # −2 + 1 (this city)
        self.assertEqual(o["tiles"]["cities"], 1)
        self.assertIn("Immigrant City", msg)

    def test_every_later_city_by_anyone_adds_1(self):
        self.eng.prod("Anna", "energy", +1)
        self.give("Anna", "Immigrant City")
        self.eng.play("Anna", "Immigrant City")
        self.eng.res("Zed", "mc", +30)
        self.eng.standard("Zed", "city")                # on Mars
        self.assertEqual(self.opp("Anna")["production"]["mc"], 0)
        self.give("Felix", "Ganymede Colony")
        self.eng.play("Felix", "Ganymede Colony")          # off-Mars counts too
        self.assertEqual(self.opp("Anna")["production"]["mc"], 1)
        self.give("Zed", "Phobos Space Haven")
        self.eng.play("Zed", "Phobos Space Haven")
        self.assertEqual(self.opp("Anna")["production"]["mc"], 2)

    def test_refused_when_energy_production_is_zero(self):
        self.give("Anna", "Immigrant City")
        with self.assertRaises(EventError):
            self.eng.play("Anna", "Immigrant City")

    def test_rover_construction_2mc_on_any_city(self):
        # applog: "Anna gained 2 M€" after every city, Ganymede Colony included
        self.give("Anna", "Rover Construction", mc=8)
        self.eng.play("Anna", "Rover Construction")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 0)
        self.give("Felix", "Ganymede Colony")
        self.eng.play("Felix", "Ganymede Colony")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 2)


class TestTargetedCards(Base):
    def test_power_supply_consortium_steals_energy_production(self):
        # applog gen 2: "Carl stole 1 energy production from Zed"
        self.eng.prod("Zed", "energy", +2)
        self.give("Anna", "Power Supply Consortium")
        msg = self.eng.play("Anna", "Power Supply Consortium",
                            target="Zed", ignore_requirements="test")
        self.assertEqual(self.me()["production"]["energy"], 1)
        self.assertEqual(self.opp("Anna")["production"]["energy"], 1)
        self.assertIn("Zed", msg)

    def test_power_supply_consortium_needs_target(self):
        self.give("Anna", "Power Supply Consortium")
        with self.assertRaises(EventError) as cm:
            self.eng.play("Anna", "Power Supply Consortium",
                          ignore_requirements="test")
        self.assertIn("--target", str(cm.exception))

    def test_sabotage_titanium_choice(self):
        # applog gen 5: "Zed lost 3 titanium because of Carl"
        self.eng.res("Zed", "titanium", +4)
        self.give("Anna", "Sabotage")
        self.eng.play("Anna", "Sabotage", target="Zed", choice=0)
        self.assertEqual(self.me()["resources"]["titanium"], 1)

    def test_sabotage_mc_choice_up_to(self):
        self.eng.res("Zed", "mc", +5)
        self.give("Anna", "Sabotage")
        self.eng.play("Anna", "Sabotage", target="Zed", choice=2)
        self.assertEqual(self.me()["resources"]["mc"], 0)   # up to 7

    def test_sabotage_lists_options_without_choice(self):
        self.give("Anna", "Sabotage")
        with self.assertRaises(EventError) as cm:
            self.eng.play("Anna", "Sabotage", target="Zed")
        self.assertIn("titanium", str(cm.exception))
        self.assertIn("--choice", str(cm.exception))

    def test_remove_any_plants_with_target(self):
        # applog gen 5: "Ben lost 4 plants because of Zed" (Big Asteroid)
        self.eng.res("Felix", "plants", +6)
        self.give("Zed", "Big Asteroid")
        self.eng.play("Zed", "Big Asteroid", target="Felix")
        self.assertEqual(self.opp("Felix")["resources"]["plants"], 2)

    def test_remove_any_plants_without_target_stays_a_table_step(self):
        self.give("Zed", "Big Asteroid")
        msg = self.eng.play("Zed", "Big Asteroid")
        self.assertIn("TABLE", msg)


class TestMartianRails(Base):
    def _cities(self, n):
        self.eng.tiles_fix("Anna", "cities", n)

    def test_opponent_action_gains_mc_per_city_on_mars(self):
        # applog: Carl gained 3 / 5 / 6 / 7 M€ as cities on Mars grew
        self.give("Anna", "Martian Rails")
        self.eng.play("Anna", "Martian Rails")
        self.give("Felix", "Ganymede Colony")
        self.eng.play("Felix", "Ganymede Colony")          # off-Mars: ignored
        for n, gain in ((3, 3), (5, 5), (6, 6), (7, 7)):
            self._cities(n)
            self.eng.res("Anna", "energy", +1)
            before = self.opp("Anna")["resources"]["mc"]
            msg = self.eng.use_action("Martian Rails", player="Anna")
            self.assertEqual(self.opp("Anna")["resources"]["mc"], before + gain)
            self.assertEqual(self.opp("Anna")["resources"]["energy"], 0)
            self.assertIn(str(gain), msg)

    def test_my_action_uses_ledger_and_needs_energy(self):
        self.give("Zed", "Martian Rails")
        self.eng.play("Zed", "Martian Rails")
        self.eng.tiles_fix("Anna", "cities", 2)
        with self.assertRaises(EventError):
            self.eng.use_action("Martian Rails")            # no energy
        self.eng.res("Zed", "energy", +1)
        self.eng.use_action("Martian Rails")
        self.assertEqual(self.me()["resources"]["mc"], 99 - 13 + 2)
        with self.assertRaises(EventError):
            self.eng.use_action("Martian Rails")            # once per gen


class TestCountingCards(Base):
    EVENTS = ["Ice Asteroid", "Business Contacts", "Bribed Committee",
              "Hired Raiders", "Big Asteroid", "Comet", "Sabotage",
              "Deimos Down", "Technology Demonstration"]

    def test_media_archives_9_events_by_all(self):
        # applog gen 7: "Ben played Media Archives / Ben gained 9 M€"
        self.eng.res("Anna", "mc", +200)
        for ev in self.EVENTS:
            kw = {}
            if ev == "Sabotage":
                kw = {"target": "Felix", "choice": 2}
            self.eng.play("Anna", ev, **kw)
        self.give("Felix", "Media Archives", mc=8)
        self.eng.play("Felix", "Media Archives")
        self.assertEqual(self.opp("Felix")["resources"]["mc"], 9)

    def test_toll_station_4_opponent_space_tags_events_excluded(self):
        # applog gen 8: "Ben played Toll Station / gained 4 M€ production"
        # Anna: Solar Wind Power, Space Station, Satellites (3) + Comet (event,
        # does not persist); Zed: Miranda Resort (1) → 4
        self.eng.res("Anna", "mc", +99)
        for c in ("Solar Wind Power", "Space Station", "Satellites", "Comet"):
            self.eng.play("Anna", c)
        self.give("Zed", "Miranda Resort")
        self.eng.play("Zed", "Miranda Resort")
        self.give("Felix", "Toll Station")
        self.eng.play("Felix", "Toll Station")
        self.assertEqual(self.opp("Felix")["production"]["mc"], 4)

    def test_terraforming_ganymede_1_tr_per_jovian_including_this(self):
        # applog gen 9: "Ben played Terraforming Ganymede / Ben gained 4 TR"
        self.eng.res("Felix", "mc", +200)
        for c in ("Colonizer Training Camp", "Water Import From Europa",
                  "Ganymede Colony"):
            self.eng.play("Felix", c)
        msg = self.eng.play("Felix", "Terraforming Ganymede")
        self.assertEqual(self.opp("Felix")["tr"], 24)
        self.assertIn("jovian", msg.lower())


class TestWaterImportFromEuropa(Base):
    def test_action_pays_12_places_ocean_with_tr(self):
        # applog gen 7: "Ben used Water Import From Europa action / placed
        # ocean tile at 43"
        self.give("Felix", "Water Import From Europa", mc=40)
        self.eng.play("Felix", "Water Import From Europa")   # 25 → 15 left
        msg = self.eng.use_action("Water Import From Europa", player="Felix")
        o = self.opp("Felix")
        self.assertEqual(o["resources"]["mc"], 3)
        self.assertEqual(o["tr"], 21)
        self.assertEqual(self.game()["globals"]["oceans"], 1)
        self.assertIn("place", msg.lower())

    def test_my_action_needs_12_mc(self):
        self.give("Zed", "Water Import From Europa", mc=30)
        self.eng.play("Zed", "Water Import From Europa")  # 5 left
        with self.assertRaises(EventError):
            self.eng.use_action("Water Import From Europa")


class TestIndenturedWorkersOpenCity(Base):
    def setUp(self):
        super().setUp()
        self.eng.sync_global("oxygen", 12)
        self.eng.prod("Anna", "energy", +1)
        self.eng.res("Anna", "mc", +50)

    def test_next_card_costs_8_less_then_full_price(self):
        # applog gen 10: Carl played Indentured Workers, then Open City
        self.eng.play("Anna", "Indentured Workers")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 50)
        msg = self.eng.play("Anna", "Open City")            # 23 → 15
        o = self.opp("Anna")
        self.assertEqual(o["resources"]["mc"], 35)
        self.assertIn("Indentured Workers −8", msg)
        self.assertEqual(o["production"]["mc"], 4)
        self.assertEqual(o["production"]["energy"], 0)
        self.assertEqual(o["resources"]["plants"], 2)
        self.assertEqual(o["tiles"]["cities"], 1)
        self.eng.play("Anna", "Sponsors")                   # full price again
        self.assertEqual(self.opp("Anna")["resources"]["mc"], 29)

    def test_discount_expires_at_generation_end(self):
        self.eng.play("Anna", "Indentured Workers")
        self.eng.produce()
        before = self.opp("Anna")["resources"]["mc"]
        self.eng.play("Anna", "Sponsors")
        self.assertEqual(self.opp("Anna")["resources"]["mc"], before - 6)


class TestNitriteReducingBacteria(Base):
    def setUp(self):
        super().setUp()
        self.give("Zed", "Nitrite Reducing Bacteria", mc=20)
        self.eng.play("Zed", "Nitrite Reducing Bacteria")

    def test_three_microbes_on_play(self):
        self.assertEqual(self.me()["cardResources"]["Nitrite Reducing Bacteria"], 3)

    def test_remove_3_for_tr_then_add_next_gen(self):
        # applog gen 8: played, added 3, used action removing 3 (TR)
        msg = self.eng.use_action("Nitrite Reducing Bacteria", choice=1)
        me = self.me()
        self.assertEqual(me["cardResources"]["Nitrite Reducing Bacteria"], 0)
        self.assertEqual(me["tr"], 21)
        self.assertIn("TR", msg)
        with self.assertRaises(EventError):
            self.eng.use_action("Nitrite Reducing Bacteria", choice=0)
        self.eng.produce()
        self.eng.use_action("Nitrite Reducing Bacteria", choice=0)
        self.assertEqual(self.me()["cardResources"]["Nitrite Reducing Bacteria"], 1)

    def test_needs_choice(self):
        with self.assertRaises(EventError) as cm:
            self.eng.use_action("Nitrite Reducing Bacteria")
        self.assertIn("--choice", str(cm.exception))

    def test_remove_refused_below_3(self):
        self.eng.use_action("Nitrite Reducing Bacteria", choice=1)
        self.eng.produce()
        with self.assertRaises(EventError):
            self.eng.use_action("Nitrite Reducing Bacteria", choice=1)


class TestRoboticWorkforce(Base):
    def setUp(self):
        super().setUp()
        self.eng.res("Zed", "mc", +60)
        self.eng.hand_add(["Nuclear Power", "Robotic Workforce", "Sponsors"])
        self.eng.play("Zed", "Nuclear Power")   # energy +3, mc −2

    def test_copies_building_production_box(self):
        # applog gen 8: "copied Nuclear Power production … lost 2 M€
        # production / gained 3 energy production"
        msg = self.eng.play("Zed", "Robotic Workforce", copy="Nuclear Power")
        me = self.me()
        self.assertEqual(me["production"]["energy"], 6)
        self.assertEqual(me["production"]["mc"], -4)
        self.assertIn("Nuclear Power", msg)

    def test_needs_copy(self):
        with self.assertRaises(EventError) as cm:
            self.eng.play("Zed", "Robotic Workforce")
        self.assertIn("--copy", str(cm.exception))

    def test_copy_must_be_own_building_card(self):
        self.eng.play("Zed", "Sponsors")
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Robotic Workforce", copy="Sponsors")
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Robotic Workforce", copy="Mining Rights")


class TestOlympusConference(Base):
    def setUp(self):
        super().setUp()
        self.eng.res("Zed", "mc", +80)
        self.eng.hand_add(["Olympus Conference", "Gene Repair",
                           "Robotic Workforce", "Nuclear Power"])

    def test_science_tag_adds_a_resource_including_itself(self):
        # applog gen 5: "Zed played Olympus Conference / added 1 Science"
        self.eng.play("Zed", "Olympus Conference")
        self.assertEqual(self.me()["cardResources"]["Olympus Conference"], 1)
        self.eng.play("Zed", "Gene Repair", ignore_requirements="test")
        self.assertEqual(self.me()["cardResources"]["Olympus Conference"], 2)

    def test_draw_choice_removes_a_resource(self):
        # applog gen 8: "removed a resource from Olympus Conference to draw"
        self.eng.play("Zed", "Olympus Conference")
        self.eng.play("Zed", "Nuclear Power")
        msg = self.eng.play("Zed", "Robotic Workforce", copy="Nuclear Power",
                            olympus="draw")
        self.assertEqual(self.me()["cardResources"]["Olympus Conference"], 0)
        self.assertIn("draw", msg.lower())

    def test_non_science_card_does_not_trigger(self):
        self.eng.play("Zed", "Olympus Conference")
        self.eng.play("Zed", "Nuclear Power")
        self.assertEqual(self.me()["cardResources"]["Olympus Conference"], 1)


# ══════════════════════════════════════════════════════════════
# sync me
# ══════════════════════════════════════════════════════════════

class TestSyncOwn(Base):
    def test_sets_values_and_logs_each_delta(self):
        self.eng.res("Zed", "mc", +30)
        msg = self.eng.sync_own("Zed", mc=28, steel=2, prod_mc=5, tr=22)
        me = self.me()
        self.assertEqual(me["resources"]["mc"], 28)
        self.assertEqual(me["resources"]["steel"], 2)
        self.assertEqual(me["production"]["mc"], 5)
        self.assertEqual(me["tr"], 22)
        self.assertIn("MC 30 → 28", msg)
        self.assertIn("correction", msg.lower())
        self.assertIn("MC 30 → 28", self.log())

    def test_unchanged_fields_confirmed(self):
        self.eng.res("Zed", "mc", +30)
        msg = self.eng.sync_own("me", mc=30)
        self.assertIn("confirmed", msg.lower())
        self.assertEqual(self.me()["resources"]["mc"], 30)

    def test_refuses_opponents(self):
        with self.assertRaises(EventError) as cm:
            self.eng.sync_own("Anna", mc=10)
        self.assertIn("observe", str(cm.exception))


# ══════════════════════════════════════════════════════════════
# draft variant
# ══════════════════════════════════════════════════════════════

class TestDraft(Base):
    def test_dealt_drafted_logs_distinct_event(self):
        self.eng.res("Zed", "mc", +20)
        msg = self.eng.dealt(["A", "B", "C", "D"], kept=["A", "C"], drafted=True)
        self.assertIn("drafted A,B,C,D → kept A,C", msg)
        self.assertIn("drafted A,B,C,D → kept A,C", self.log())
        self.assertTrue(self.me()["dealtLog"][-1]["drafted"])
        self.assertEqual(self.me()["hand"], ["A", "C"])
        self.assertEqual(self.me()["resources"]["mc"], 14)

    def test_plain_dealt_unchanged(self):
        self.eng.res("Zed", "mc", +20)
        msg = self.eng.dealt(["A", "B"], kept=["A"])
        self.assertNotIn("drafted", msg)
        self.assertFalse(self.me()["dealtLog"][-1].get("drafted"))


class TestDraftBrief(unittest.TestCase):
    def _brief(self, draft):
        import advise
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(tmp.name)
        store.init(_setup(draft=draft))
        return advise.build_brief(tmp.name, kb_dir=ROOT / "strategy", brief=True)

    def test_header_flags_draft(self):
        self.assertIn("RESEARCH: DRAFT (pick-1-pass, 4/3/2 then buy)",
                      self._brief(True))

    def test_header_silent_without_draft(self):
        self.assertNotIn("RESEARCH: DRAFT", self._brief(False))


# ══════════════════════════════════════════════════════════════
# CLI wiring
# ══════════════════════════════════════════════════════════════

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        r = run(["setup.py"], self.cwd, stdin=SETUP_ANSWERS)
        assert r.returncode == 0, r.stderr
        assert run(["apply.py", "res", "Zed", "mc", "80"], self.cwd).returncode == 0

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return json.loads((Path(self.cwd) / "state" / "game.json").read_text())

    def test_play_no_effects_flag(self):
        run(["apply.py", "hand", "add", "Nuclear Power"], self.cwd)
        r = run(["apply.py", "play", "Zed", "Nuclear Power", "--no-effects"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NO EFFECTS", r.stdout)
        self.assertEqual(self.game()["me"]["production"]["energy"], 0)

    def test_play_target_and_choice(self):
        run(["apply.py", "res", "Zed", "titanium", "4"], self.cwd)
        run(["apply.py", "res", "Anna", "mc", "10"], self.cwd)
        r = run(["apply.py", "play", "Anna", "Sabotage", "--target", "Zed",
                 "--choice", "0"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["me"]["resources"]["titanium"], 1)

    def test_play_copy_flag(self):
        run(["apply.py", "hand", "add", "Nuclear Power", "Robotic Workforce"], self.cwd)
        run(["apply.py", "play", "Zed", "Nuclear Power"], self.cwd)
        r = run(["apply.py", "play", "Zed", "Robotic Workforce",
                 "--copy", "Nuclear Power"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["me"]["production"]["energy"], 6)

    def test_action_use_player_and_choice(self):
        run(["apply.py", "res", "Anna", "mc", "20"], self.cwd)
        run(["apply.py", "res", "Anna", "energy", "1"], self.cwd)
        run(["apply.py", "play", "Anna", "Martian Rails"], self.cwd)
        r = run(["apply.py", "action", "use", "Martian Rails", "--player", "Anna"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["opponents"]["Anna"]["resources"]["energy"], 0)

    def test_sync_me(self):
        r = run(["apply.py", "sync", "me", "--mc", "70", "--prod-mc", "3", "--tr", "21"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        me = self.game()["me"]
        self.assertEqual(me["resources"]["mc"], 70)
        self.assertEqual(me["production"]["mc"], 3)
        self.assertEqual(me["tr"], 21)

    def test_sync_global_still_works(self):
        r = run(["apply.py", "sync", "temperature", "-28"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["globals"]["temperature"], -28)

    def test_sync_opponent_refused(self):
        r = run(["apply.py", "sync", "Anna", "--mc", "5"], self.cwd)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("observe", r.stderr)

    def test_dealt_drafted(self):
        r = run(["apply.py", "dealt", "A", "B", "C", "D", "--kept", "A", "--drafted"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("drafted A,B,C,D → kept A", r.stdout)


if __name__ == "__main__":
    unittest.main()
