"""The AVAILABLE ACTIONS menu is DERIVED from state — the app's action menu,
recomputed by the engine. Items whose prerequisites fail are never listed
(a hand-maintained list once showed Equatorial Magnetizer at 0 energy
production while missing NRB / Business Network / Underground Detonations)."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP
import menu
import planlib

THREATS = "test threats"
EXIT = "test exit: card VP; repeatable: greenery from plant production"


def _items(game, setup=SETUP, **kw):
    return menu.available_actions(game, setup, **kw)


def _by_kind(items, kind):
    return [i for i in items if i["kind"] == kind]


def _names(items, kind=None):
    return [i["name"] for i in items if kind is None or i["kind"] == kind]


class MenuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def set(self, **changes):
        """Test-only direct state edit for positions events can't reach fast."""
        g = self.game()
        me = g["me"]
        for k, v in changes.items():
            if k in me["resources"]:
                me["resources"][k] = v
            elif k.startswith("prod_"):
                me["production"][k[5:]] = v
            elif k in ("temperature", "oxygen", "oceans"):
                g["globals"][k] = v
            elif k == "tr":
                me["tr"] = v
            elif k == "hand":
                me["hand"] = list(v)
            elif k == "corporation":
                me["corporation"] = v
            elif k in ("cities", "greeneries"):
                me["tiles"][k] = v
            else:
                g[k] = v
        self.store.save_game(g)
        return g

    def items(self, **kw):
        return _items(self.game(), self.store.load_setup(), **kw)


class TestItemShape(MenuTest):
    def test_every_item_has_the_contract_fields(self):
        self.set(mc=30, heat=9, hand=["Comet"])
        for it in self.items():
            for key in ("kind", "label", "cost", "detail", "ok", "name"):
                self.assertIn(key, it, it)
            self.assertTrue(it["ok"])
            self.assertIn(it["kind"], ("card", "action", "standard",
                                       "milestone", "award", "convert"))

    def test_fresh_game_zero_mc_lists_nothing(self):
        self.assertEqual(self.items(), [])


class TestHandCards(MenuTest):
    """Playable NOW: cost vs MC + steel (building) + titanium (space) + Helion
    heat; requirement window open (Inventrix/Adaptation ±2)."""

    def test_affordable_requirement_met_card_listed_with_cost(self):
        self.set(mc=8, oxygen=4, hand=["Worms"])       # Worms: 8 MC, min 4% O2
        cards = _by_kind(self.items(), "card")
        self.assertEqual(_names(cards), ["Worms"])
        self.assertEqual(cards[0]["cost"], 8)

    def test_unaffordable_card_not_listed(self):
        self.set(mc=7, oxygen=4, hand=["Worms"])
        self.assertEqual(_names(self.items(), "card"), [])

    def test_requirement_closed_card_not_listed(self):
        self.set(mc=20, oxygen=3, hand=["Worms"])
        self.assertEqual(_names(self.items(), "card"), [])

    def test_expired_max_requirement_not_listed(self):
        self.set(mc=20, temperature=-10, hand=["Arctic Algae"])   # max -12°C
        self.assertEqual(_names(self.items(), "card"), [])
        self.set(temperature=-12)
        self.assertEqual(_names(self.items(), "card"), ["Arctic Algae"])

    def test_steel_pays_for_building_tag_cards_only(self):
        # Equatorial Magnetizer: 11 MC, building tag → 3 MC + 4 steel is enough
        self.set(mc=3, steel=4, hand=["Equatorial Magnetizer", "Comet"])
        cards = _by_kind(self.items(), "card")
        self.assertEqual(_names(cards), ["Equatorial Magnetizer"])
        self.assertIn("steel", cards[0]["detail"])
        # Comet (21, space) is not payable with steel; titanium does it
        self.set(mc=3, steel=4, titanium=6)
        self.assertIn("Comet", _names(self.items(), "card"))

    def test_helion_heat_pays_as_mc(self):
        self.set(mc=10, heat=12, hand=["Comet"], corporation="Helion")
        self.assertIn("Comet", _names(self.items(), "card"))
        self.set(corporation="Thorgate")
        self.assertNotIn("Comet", _names(self.items(), "card"))

    def test_inventrix_widens_requirement_by_two_steps(self):
        # Worms needs min 4% O2; Inventrix plays it from 2%
        self.set(mc=20, oxygen=2, hand=["Worms"], corporation="Inventrix")
        cards = _by_kind(self.items(), "card")
        self.assertEqual(_names(cards), ["Worms"])
        self.assertIn("±2", cards[0]["detail"])
        self.set(oxygen=1)
        self.assertEqual(_names(self.items(), "card"), [])

    def test_adaptation_technology_widens_temperature_two_steps(self):
        # Arctic Algae max -12°C → with Adaptation up to -8°C (2 steps of 2°C)
        self.set(mc=20, temperature=-8, hand=["Arctic Algae"])
        self.assertEqual(_names(self.items(), "card"), [])
        g = self.game()
        g["me"]["playedCards"].append({"name": "Adaptation Technology", "gen": 1})
        self.store.save_game(g)
        self.assertEqual(_names(self.items(), "card"), ["Arctic Algae"])
        self.set(temperature=-6)
        self.assertEqual(_names(self.items(), "card"), [])

    def test_tag_requirement_checked_from_played_cards(self):
        # AI Central needs 3 science tags (+ energy prod 1 to decrease)
        self.set(mc=30, prod_energy=1, hand=["AI Central"])
        self.assertEqual(_names(self.items(), "card"), [])
        g = self.game()
        g["me"]["playedCards"] += [{"name": n, "gen": 1} for n in
                                   ("Research", "Mars University")]  # 2+1 = 3
        self.store.save_game(g)
        self.assertEqual(_names(self.items(), "card"), ["AI Central"])

    def test_production_floor_blocks_card(self):
        # Business Network: -1 MC production; at -5 it is illegal
        self.set(mc=10, prod_mc=-5, hand=["Business Network"])
        self.assertEqual(_names(self.items(), "card"), [])
        self.set(prod_mc=-4)
        self.assertEqual(_names(self.items(), "card"), ["Business Network"])

    def test_or_choice_card_listed_once_with_branch_menu(self):
        self.set(mc=20, hand=["Artificial Photosynthesis"])
        cards = _by_kind(self.items(), "card")
        self.assertEqual(len(cards), 1)
        self.assertIn("choice=0", cards[0]["detail"])
        self.assertIn("choice=1", cards[0]["detail"])
        self.assertIn("energy", cards[0]["detail"])

    def test_corp_discount_lowers_the_listed_cost(self):
        # Teractor: earth tags -3 → Business Network 4 → 1
        self.set(mc=1, hand=["Business Network"], corporation="Teractor")
        cards = _by_kind(self.items(), "card")
        self.assertEqual(_names(cards), ["Business Network"])
        self.assertEqual(cards[0]["cost"], 1)

    def test_unknown_card_listed_flagged_for_manual_check(self):
        self.set(mc=30, hand=["Some Promo Card"])
        cards = _by_kind(self.items(), "card")
        self.assertEqual(_names(cards), ["Some Promo Card"])
        self.assertIn("not in db", cards[0]["detail"].lower())


class TestBlueActions(MenuTest):
    def register(self, *names, used=()):
        for n in names:
            self.eng.register_action(n)
        for n in used:
            self.eng.use_action(n)

    def test_magnetizer_at_zero_energy_production_not_listed(self):
        self.register("Equatorial Magnetizer")
        self.assertEqual(_names(self.items(), "action"), [])
        self.set(prod_energy=1)
        self.assertEqual(_names(self.items(), "action"), ["Equatorial Magnetizer"])

    def test_always_available_actions_listed_until_used(self):
        self.register("Nitrite Reducing Bacteria", "Business Network")
        self.assertEqual(sorted(_names(self.items(), "action")),
                         ["Business Network", "Nitrite Reducing Bacteria"])
        self.eng.use_action("Business Network")
        self.assertEqual(_names(self.items(), "action"),
                         ["Nitrite Reducing Bacteria"])

    def test_mc_cost_actions_need_the_money(self):
        self.register("Underground Detonations")
        self.set(mc=9)
        self.assertEqual(_names(self.items(), "action"), [])
        self.set(mc=10)
        self.assertEqual(_names(self.items(), "action"), ["Underground Detonations"])

    def test_water_import_needs_12_mc_and_an_ocean_slot(self):
        self.register("Water Import From Europa")
        self.set(mc=12)
        self.assertEqual(_names(self.items(), "action"), ["Water Import From Europa"])
        self.set(oceans=9)
        self.assertEqual(_names(self.items(), "action"), [])
        self.set(oceans=8, mc=3, titanium=3)         # titanium pays too
        self.assertEqual(_names(self.items(), "action"), ["Water Import From Europa"])

    def test_steelworks_needs_4_energy(self):
        self.register("Steelworks")
        self.set(energy=3)
        self.assertEqual(_names(self.items(), "action"), [])
        self.set(energy=4)
        self.assertEqual(_names(self.items(), "action"), ["Steelworks"])

    def test_caretaker_contract_needs_8_heat(self):
        self.register("Caretaker Contract")
        self.set(heat=7)
        self.assertEqual(_names(self.items(), "action"), [])
        self.set(heat=8)
        self.assertEqual(_names(self.items(), "action"), ["Caretaker Contract"])

    def test_unknown_action_listed_with_prereq_unknown(self):
        self.register("Mystery Blue Card")
        acts = _by_kind(self.items(), "action")
        self.assertEqual(_names(acts), ["Mystery Blue Card"])
        self.assertIn("prereq unknown", acts[0]["detail"])

    def test_play_registers_blue_action_automatically(self):
        self.set(mc=30, hand=["Business Network", "Underground Detonations",
                              "Nitrite Reducing Bacteria"])
        for c in ("Business Network", "Underground Detonations",
                  "Nitrite Reducing Bacteria"):
            self.eng.play("Zed", c)
        ledger = self.game()["me"]["actionsThisGen"]
        self.assertEqual(sorted(ledger), ["Business Network",
                                          "Nitrite Reducing Bacteria",
                                          "Underground Detonations"])
        self.set(mc=10)
        self.assertEqual(sorted(_names(self.items(), "action")),
                         ["Business Network", "Nitrite Reducing Bacteria",
                          "Underground Detonations"])

    def test_produce_resets_ledger_so_actions_return(self):
        self.register("Business Network", used=["Business Network"])
        self.assertEqual(_names(self.items(), "action"), [])
        self.eng.produce()
        self.assertEqual(_names(self.items(), "action"), ["Business Network"])

    def test_played_active_card_missing_from_ledger_is_flagged_not_hidden(self):
        g = self.game()
        g["me"]["playedCards"].append({"name": "Tardigrades", "gen": 1})
        self.store.save_game(g)
        acts = _by_kind(self.items(), "action")
        self.assertEqual(_names(acts), ["Tardigrades"])
        self.assertIn("not in ledger", acts[0]["detail"])


class TestStandardProjects(MenuTest):
    def test_sell_patents_only_with_a_hand(self):
        self.assertEqual(_names(self.items(), "standard"), [])
        self.set(hand=["Comet"])
        self.assertEqual(_names(self.items(), "standard"), ["sell_patents"])

    def test_projects_by_affordability(self):
        self.set(mc=14)
        self.assertEqual(_names(self.items(), "standard"),
                         ["power_plant", "asteroid"])
        self.set(mc=25)
        self.assertEqual(_names(self.items(), "standard"),
                         ["power_plant", "asteroid", "aquifer", "greenery", "city"])

    def test_maxed_parameters_drop_asteroid_and_aquifer(self):
        self.set(mc=40, temperature=8, oceans=9)
        self.assertEqual(_names(self.items(), "standard"),
                         ["power_plant", "greenery", "city"])

    def test_greenery_still_legal_when_o2_maxed_but_flagged(self):
        self.set(mc=40, oxygen=14)
        g = [i for i in self.items() if i["name"] == "greenery"]
        self.assertEqual(len(g), 1)
        self.assertIn("O2 maxed", g[0]["detail"])

    def test_no_free_land_drops_greenery_and_city(self):
        self.set(mc=40)
        self.assertEqual(_names(self.items(free_land=0), "standard"),
                         ["power_plant", "asteroid", "aquifer"])

    def test_thorgate_power_plant_costs_8(self):
        self.set(mc=8, corporation="Thorgate")
        pp = [i for i in self.items() if i["name"] == "power_plant"]
        self.assertEqual(pp[0]["cost"], 8)
        self.set(corporation=None)
        self.assertEqual(_names(self.items(), "standard"), [])


class TestMilestones(MenuTest):
    def test_terraformer_at_35_tr_with_8_mc(self):
        self.set(mc=8, tr=34)
        self.assertEqual(_names(self.items(), "milestone"), [])
        self.set(tr=35)
        self.assertEqual(_names(self.items(), "milestone"), ["Terraformer"])
        self.set(mc=7)
        self.assertEqual(_names(self.items(), "milestone"), [])

    def test_mayor_gardener_builder_planner_metrics(self):
        self.set(mc=8, cities=3, greeneries=3, hand=["x"] * 16)
        g = self.game()
        g["me"]["corporation"] = "Mining Guild"          # 2 building tags
        g["me"]["playedCards"] += [{"name": n, "gen": 1} for n in (
            "Equatorial Magnetizer", "Steelworks", "Ironworks",
            "Underground Detonations", "Ore Processor", "Industrial Center")]
        self.store.save_game(g)
        self.assertEqual(sorted(_names(self.items(), "milestone")),
                         ["Builder", "Gardener", "Mayor", "Planner"])

    def test_claimed_and_full_boards(self):
        self.set(mc=8, tr=35, cities=3)
        g = self.game(); g["milestonesClaimed"] = {"Terraformer": "Anna"}
        self.store.save_game(g)
        self.assertEqual(_names(self.items(), "milestone"), ["Mayor"])
        g["milestonesClaimed"] = {"Terraformer": "Anna", "Gardener": "Anna",
                                  "Builder": "Felix"}
        self.store.save_game(g)
        self.assertEqual(_names(self.items(), "milestone"), [])


class TestAwards(MenuTest):
    def test_award_listed_with_slot_price_and_metrics(self):
        self.set(mc=8, prod_mc=5)
        g = self.game()
        g["opponents"]["Anna"]["production"]["mc"] = 3
        self.store.save_game(g)
        aw = _by_kind(self.items(), "award")
        self.assertEqual(len(aw), 5)
        banker = next(i for i in aw if i["name"] == "Banker")
        self.assertEqual(banker["cost"], 8)
        self.assertIn("Zed 5", banker["detail"])
        self.assertIn("Anna 3", banker["detail"])
        self.assertIn("lead", banker["detail"].lower())

    def test_slot_price_escalates_and_funded_awards_vanish(self):
        self.set(mc=14)
        g = self.game(); g["awardsFunded"] = {"Miner": "Anna"}
        self.store.save_game(g)
        aw = _by_kind(self.items(), "award")
        self.assertEqual(len(aw), 4)
        self.assertTrue(all(i["cost"] == 14 for i in aw))
        self.assertNotIn("Miner", _names(aw))
        self.set(mc=13)
        self.assertEqual(_by_kind(self.items(), "award"), [])

    def test_no_awards_when_three_funded(self):
        self.set(mc=40)
        g = self.game()
        g["awardsFunded"] = {"Miner": "Anna", "Banker": "Zed", "Landlord": "Felix"}
        self.store.save_game(g)
        self.assertEqual(_by_kind(self.items(), "award"), [])


class TestConversions(MenuTest):
    def test_heat_threshold_and_max_temperature(self):
        self.set(heat=7)
        self.assertEqual(_names(self.items(), "convert"), [])
        self.set(heat=8)
        self.assertEqual(_names(self.items(), "convert"), ["heat"])
        self.set(temperature=8)
        self.assertEqual(_names(self.items(), "convert"), [])

    def test_plants_threshold_ecoline_and_free_land(self):
        self.set(plants=7)
        self.assertEqual(_names(self.items(), "convert"), [])
        self.set(corporation="Ecoline")
        self.assertEqual(_names(self.items(), "convert"), ["plants"])
        self.set(corporation=None, plants=8)
        self.assertEqual(_names(self.items(), "convert"), ["plants"])
        self.assertEqual(_names(self.items(free_land=0), "convert"), [])

    def test_plants_at_max_o2_still_listed_as_tile_only(self):
        self.set(plants=8, oxygen=14)
        conv = _by_kind(self.items(), "convert")
        self.assertEqual(_names(conv), ["plants"])
        self.assertIn("O2 maxed", conv[0]["detail"])


class TestRenderAndSummary(MenuTest):
    def test_render_block_and_one_line_summary(self):
        self.set(mc=30, heat=9, hand=["Comet"])
        self.eng.register_action("Business Network")
        self.eng.register_action("Ironworks")
        self.eng.res("Zed", "energy", +4)   # Ironworks: spend 4 energy
        self.eng.use_action("Ironworks")
        items = self.items()
        block = menu.render(items, self.game())
        self.assertIn("AVAILABLE ACTIONS", block)
        self.assertIn("Comet", block)
        self.assertIn("Business Network", block)
        self.assertIn("used this generation: Ironworks", block)
        line = menu.summary(items)
        self.assertTrue(line.startswith("available: "))
        self.assertIn("Comet", line)
        self.assertTrue(line.endswith(", pass"))

    def test_empty_menu_summary(self):
        self.assertEqual(menu.summary([]), "available: nothing — pass is legal")
        self.assertIn("(nothing available", menu.render([], self.game()))

    def test_app_blue_action_count_drift_flagged(self):
        self.eng.register_action("Inventors' Guild")
        block = menu.render(self.items(), self.game(),
                            app={"thisPlayer": {"availableBlueCardActionCount": 0}})
        self.assertIn("ledger drift", block)
        block = menu.render(self.items(), self.game(),
                            app={"thisPlayer": {"availableBlueCardActionCount": 1}})
        self.assertNotIn("ledger drift", block)

    def test_cli_prints_menu(self):
        self.set(mc=30, hand=["Comet"])
        script = Path(__file__).resolve().parent.parent / "scripts" / "menu.py"
        r = subprocess.run([sys.executable, str(script)], cwd=self.tmp.name,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("AVAILABLE ACTIONS", r.stdout)
        self.assertIn("Comet", r.stdout)
        self.assertIn("available: ", r.stdout)


class TestFogRobustness(MenuTest):
    """Physical-table reality: opponent records with missing fields, hand
    cards not in the db — the menu still renders."""

    def test_missing_opponent_fields_do_not_crash(self):
        self.set(mc=30, hand=["Comet", "Unknown Thing"])
        g = self.game()
        for o in g["opponents"].values():
            o.pop("tagCounts", None); o.pop("tiles", None)
            o.pop("production", None); o["corporation"] = None
        self.store.save_game(g)
        items = self.items()
        self.assertIn("Comet", _names(items, "card"))
        self.assertTrue(_by_kind(items, "award"))


class TestPassGateUsesMenu(MenuTest):
    def _gate(self):
        planlib.set_plan(self.store, [
            {"id": "2b", "summary": "pass", "volatility": "safe",
             "passGate": True, "events": []}], threats=THREATS, exit_=EXIT)

    def test_pass_refused_while_a_prerequisite_met_action_is_open(self):
        self.eng.register_action("Nitrite Reducing Bacteria")
        self._gate()
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done(self.store, "2b")
        self.assertIn("Nitrite Reducing Bacteria", str(ctx.exception))

    def test_pass_accepted_when_only_failed_prereq_actions_remain(self):
        self.eng.register_action("Equatorial Magnetizer")   # 0 energy prod
        self._gate()
        planlib.mark_done(self.store, "2b")

    def test_pass_refused_on_claimable_milestone(self):
        self.set(mc=8, tr=35)
        self._gate()
        with self.assertRaises(EventError) as ctx:
            planlib.mark_done(self.store, "2b")
        self.assertIn("Terraformer", str(ctx.exception))

    def test_force_overrides_and_logs(self):
        self.eng.register_action("Business Network")
        self._gate()
        planlib.mark_done(self.store, "2b", force="deck is junk")
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("OVERRIDDEN", log)


if __name__ == "__main__":
    unittest.main()


class TestTilePlacementFeasibility(unittest.TestCase):
    """Live e2e finding: the app did not list Mining Area as playable (it
    needs an own tile with an adjacent steel/titanium hex) but the menu did
    — the executor refused correctly. Tile cards are listed only when a
    legal hex exists for them right now."""

    def _game(self, board=None, hand=None, mc=60):
        import tmlib
        from test_new_game import SETUP
        g = tmlib.new_game_state(SETUP)
        g["me"]["resources"]["mc"] = mc
        g["me"]["hand"] = hand or []
        g["board"] = board or {}
        return g, SETUP

    def _names(self, g, setup):
        import menu
        return {i["name"] for i in menu.available_actions(g, setup) if i["kind"] == "card"}

    def test_mining_area_needs_own_tile_with_adjacent_metal_hex(self):
        g, s = self._game(hand=["Mining Area"])
        self.assertNotIn("Mining Area", self._names(g, s))
        # own city on 09 (Tharsis Tholus, steel) — 03 (A1, 2 steel) is adjacent
        g["board"] = {"09": {"tile": "city", "player": g["me"]["name"]}}
        self.assertIn("Mining Area", self._names(g, s))

    def test_mining_rights_needs_a_free_metal_bonus_hex(self):
        g, s = self._game(hand=["Mining Rights"])
        self.assertIn("Mining Rights", self._names(g, s))
        import tmlib
        metal = {sid for sid, sp in tmlib.Engine._board().items()
                 if not sp.get("offMap") and not sp.get("oceanReserved")
                 and any(b in ("steel", "titanium") for b in sp.get("bonus", []))}
        g["board"] = {sid: {"tile": "greenery", "player": "Anna"} for sid in metal}
        self.assertNotIn("Mining Rights", self._names(g, s))

    def test_ocean_tile_card_needs_a_free_ocean_slot(self):
        g, s = self._game(hand=["Mohole Area"])
        self.assertIn("Mohole Area", self._names(g, s))
        import tmlib
        oceans = {sid for sid, sp in tmlib.Engine._board().items() if sp.get("oceanReserved")}
        g["board"] = {sid: {"tile": "ocean", "player": None} for sid in oceans}
        g["globals"]["oceans"] = 9
        self.assertNotIn("Mohole Area", self._names(g, s))
