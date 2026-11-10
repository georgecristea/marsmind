"""M1: apply events — every state change goes through these, validated + logged."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def log_text(self):
        return (Path(self.tmp.name) / "state" / "log.md").read_text()


class TestPlayerResolution(EngineTest):
    def test_resolves_name_case_insensitive(self):
        self.assertEqual(self.eng.resolve_player("zed"), "Zed")

    def test_resolves_alias(self):
        self.assertEqual(self.eng.resolve_player("the blue guy"), "Felix")
        self.assertEqual(self.eng.resolve_player("ana"), "Anna")

    def test_resolves_color(self):
        self.assertEqual(self.eng.resolve_player("green"), "Anna")

    def test_unknown_player_raises(self):
        with self.assertRaises(EventError):
            self.eng.resolve_player("zorg")


class TestResourceEvents(EngineTest):
    def test_me_gains_resources_and_is_logged(self):
        self.eng.res("Zed", "mc", +7)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 7)
        self.assertIn("Zed", self.log_text())
        self.assertIn("MC", self.log_text())

    def test_me_stock_cannot_go_negative(self):
        with self.assertRaises(EventError):
            self.eng.res("Zed", "steel", -1)
        self.assertEqual(self.game()["me"]["resources"]["steel"], 0)  # unchanged

    def test_opponent_all_resources_tracked(self):
        self.eng.res("Anna", "mc", +12)
        self.eng.res("Anna", "titanium", +2)
        self.eng.res("Felix", "plants", +3)
        g = self.game()
        self.assertEqual(g["opponents"]["Anna"]["resources"]["mc"], 12)
        self.assertEqual(g["opponents"]["Anna"]["resources"]["titanium"], 2)
        self.assertEqual(g["opponents"]["Felix"]["resources"]["plants"], 3)


class TestProductionEvents(EngineTest):
    def test_me_production_increase(self):
        self.eng.prod("Zed", "energy", +2)
        self.assertEqual(self.game()["me"]["production"]["energy"], 2)

    def test_me_mc_production_floor_minus_5(self):
        self.eng.prod("Zed", "mc", -5)
        self.assertEqual(self.game()["me"]["production"]["mc"], -5)
        with self.assertRaises(EventError):
            self.eng.prod("Zed", "mc", -1)

    def test_me_non_mc_production_floor_zero(self):
        with self.assertRaises(EventError):
            self.eng.prod("Zed", "plants", -1)

    def test_opponent_all_productions_tracked(self):
        self.eng.prod("Anna", "plants", +2)
        self.eng.prod("Anna", "heat", +1)
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["production"]["plants"], 2)
        self.assertEqual(anna["production"]["heat"], 1)


if __name__ == "__main__":
    unittest.main()


class TestTRAndGlobals(EngineTest):
    def test_tr_delta_any_player(self):
        self.eng.tr("Zed", +2)
        self.eng.tr("ana", +1)
        self.assertEqual(self.game()["me"]["tr"], 22)
        self.assertEqual(self.game()["opponents"]["Anna"]["tr"], 21)

    def test_raise_temperature_steps_and_credits_tr(self):
        self.eng.raise_param("temperature", by="Zed")
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -28)  # one step = 2°C
        self.assertEqual(g["me"]["tr"], 21)

    def test_raise_oxygen_credits_tr(self):
        self.eng.raise_param("oxygen", by="Felix")
        g = self.game()
        self.assertEqual(g["globals"]["oxygen"], 1)
        self.assertEqual(g["opponents"]["Felix"]["tr"], 21)

    def test_raise_beyond_cap_rejected(self):
        self.eng.sync_global("temperature", 8)
        with self.assertRaises(EventError):
            self.eng.raise_param("temperature", by="Zed")

    def test_raise_ocean_requires_placement_note(self):
        self.eng.raise_param("oceans", by="Zed")
        self.assertEqual(self.game()["globals"]["oceans"], 1)

    def test_sync_global_latest_wins_but_only_up(self):
        self.eng.sync_global("oxygen", 4)
        self.assertEqual(self.game()["globals"]["oxygen"], 4)
        with self.assertRaises(EventError):
            self.eng.sync_global("oxygen", 3)  # parameters only move up

    def test_sync_global_rejects_off_scale_values(self):
        with self.assertRaises(EventError):
            self.eng.sync_global("temperature", -29)  # temp moves in 2°C steps
        with self.assertRaises(EventError):
            self.eng.sync_global("oceans", 10)


class TestConversions(EngineTest):
    def test_heat_conversion_needs_8(self):
        self.eng.res("Zed", "heat", +7)
        with self.assertRaises(EventError):
            self.eng.convert("Zed", "heat")

    def test_heat_conversion_spends_8_raises_temp_and_tr(self):
        self.eng.res("Zed", "heat", +9)
        msg = self.eng.convert("Zed", "heat")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["heat"], 1)
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["me"]["tr"], 21)
        self.assertIn("8 heat", msg)

    def test_plant_conversion_places_greenery_raises_o2_and_tr(self):
        self.eng.res("Zed", "plants", +8)
        self.eng.convert("Zed", "plants")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["plants"], 0)
        self.assertEqual(g["globals"]["oxygen"], 1)
        self.assertEqual(g["me"]["tr"], 21)
        self.assertEqual(g["me"]["tiles"]["greeneries"], 1)

    def test_opponent_plant_conversion(self):
        self.eng.res("Anna", "plants", +8)
        self.eng.convert("Anna", "plants")
        g = self.game()
        anna = g["opponents"]["Anna"]
        self.assertEqual(anna["resources"]["plants"], 0)
        self.assertEqual(anna["tr"], 21)
        self.assertEqual(anna["tiles"]["greeneries"], 1)
        self.assertEqual(g["globals"]["oxygen"], 1)

    def test_conversion_at_maxed_parameter_gives_no_tr_but_still_allowed(self):
        # Greenery at 14% O2 still places a tile + VP; no O2/TR bump.
        self.eng.sync_global("oxygen", 14)
        self.eng.res("Zed", "plants", +8)
        self.eng.convert("Zed", "plants")
        g = self.game()
        self.assertEqual(g["globals"]["oxygen"], 14)
        self.assertEqual(g["me"]["tr"], 20)
        self.assertEqual(g["me"]["tiles"]["greeneries"], 1)


class TestPlayCard(EngineTest):
    def test_me_play_deducts_cost_moves_hand_to_played(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.hand_add(["Comet", "Mining Rights"])
        msg = self.eng.play("Zed", "Comet", cost=21)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 9)
        self.assertEqual(g["me"]["hand"], ["Mining Rights"])
        self.assertEqual(g["me"]["playedCards"], [{"name": "Comet", "gen": 1}])
        self.assertIn("21", msg)

    def test_me_play_with_steel_payment(self):
        self.eng.res("Zed", "mc", +10)
        self.eng.res("Zed", "steel", +3)
        self.eng.hand_add(["Test Steel Card"])
        # 2 steel pays 4 MC of an 8 MC card → 4 MC cash
        self.eng.play("Zed", "Test Steel Card", cost=8, steel=2)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 6)
        self.assertEqual(g["me"]["resources"]["steel"], 1)

    def test_me_cannot_overpay_resources_not_held(self):
        self.eng.res("Zed", "mc", +10)
        self.eng.hand_add(["Test Steel Card"])
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Test Steel Card", cost=8, steel=2)

    def test_me_play_card_not_in_hand_rejected(self):
        self.eng.res("Zed", "mc", +30)
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Comet", cost=21)

    def test_me_insufficient_mc_rejected(self):
        self.eng.hand_add(["Comet"])
        with self.assertRaises(EventError):
            self.eng.play("Zed", "Comet", cost=21)

    def test_opponent_play_appends_event_driven_tableau_with_gen(self):
        self.eng.play("ana", "Mining Rights")  # no cost known yet (db is M2)
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["playedCards"], [{"name": "Mining Rights", "gen": 1}])

    def test_opponent_play_with_known_cost_reduces_mc_estimate(self):
        self.eng.res("Anna", "mc", +20)
        self.eng.play("Anna", "Comet", cost=21)  # estimate floors at 0
        self.assertEqual(self.game()["opponents"]["Anna"]["resources"]["mc"], 0)


class TestActionLedger(EngineTest):
    def test_register_action_starts_available(self):
        self.eng.register_action("Ironworks")
        self.assertEqual(
            self.game()["me"]["actionsThisGen"], {"Ironworks": {"used": False}}
        )

    def test_use_action_marks_used(self):
        self.eng.register_action("Ironworks")
        self.eng.res("Zed", "energy", +4)   # Ironworks: spend 4 energy
        self.eng.use_action("Ironworks")
        self.assertTrue(self.game()["me"]["actionsThisGen"]["Ironworks"]["used"])

    def test_use_action_twice_in_gen_rejected(self):
        self.eng.register_action("Ironworks")
        self.eng.res("Zed", "energy", +4)
        self.eng.use_action("Ironworks")
        with self.assertRaises(EventError):
            self.eng.use_action("Ironworks")

    def test_use_unregistered_action_rejected(self):
        with self.assertRaises(EventError):
            self.eng.use_action("Ironworks")


class TestHandAndDealt(EngineTest):
    def test_hand_add_appends_in_order(self):
        self.eng.hand_add(["Comet", "Birds"])
        self.eng.hand_add(["Insects"])
        self.assertEqual(self.game()["me"]["hand"], ["Comet", "Birds", "Insects"])

    def test_hand_reorder_is_the_play_order_contract(self):
        self.eng.hand_add(["Comet", "Birds", "Insects"])
        self.eng.hand_reorder(["Insects", "Comet", "Birds"])
        self.assertEqual(self.game()["me"]["hand"], ["Insects", "Comet", "Birds"])

    def test_hand_reorder_must_be_same_multiset(self):
        self.eng.hand_add(["Comet", "Birds"])
        with self.assertRaises(EventError):
            self.eng.hand_reorder(["Comet"])

    def test_hand_remove(self):
        self.eng.hand_add(["Comet", "Birds"])
        self.eng.hand_remove("Comet")
        self.assertEqual(self.game()["me"]["hand"], ["Birds"])

    def test_dealt_logs_all_4_and_buys_kept_at_3mc_each(self):
        self.eng.res("Zed", "mc", +10)
        self.eng.dealt(["Comet", "Birds", "Insects", "Moss"], kept=["Comet", "Moss"])
        g = self.game()
        self.assertEqual(
            g["me"]["dealtLog"],
            [{"gen": 1, "dealt": ["Comet", "Birds", "Insects", "Moss"],
              "kept": ["Comet", "Moss"]}],
        )
        self.assertEqual(g["me"]["resources"]["mc"], 4)  # 10 - 2×3
        self.assertEqual(g["me"]["hand"], ["Comet", "Moss"])

    def test_dealt_kept_must_be_subset(self):
        self.eng.res("Zed", "mc", +10)
        with self.assertRaises(EventError):
            self.eng.dealt(["Comet", "Birds"], kept=["Moss"])


class TestCorpAndMilestones(EngineTest):
    def test_corp_sets_name_and_starting_resources(self):
        self.eng.corp("Zed", "Thorgate", mc=48)
        g = self.game()
        self.assertEqual(g["me"]["corporation"], "Thorgate")
        self.assertEqual(g["me"]["resources"]["mc"], 48)

    def test_corp_for_opponent_summary(self):
        self.eng.corp("Felix", "Ecoline", mc=36)
        felix = self.game()["opponents"]["Felix"]
        self.assertEqual(felix["corporation"], "Ecoline")
        self.assertEqual(felix["resources"]["mc"], 36)

    def test_milestone_claim_costs_8_and_is_recorded(self):
        self.eng.res("Zed", "mc", +10)
        self.eng.tr("Zed", +15)                  # TR 35: Terraformer-eligible
        self.eng.milestone("Zed", "Terraformer")
        g = self.game()
        self.assertEqual(g["me"]["milestones"], ["Terraformer"])
        self.assertEqual(g["me"]["resources"]["mc"], 2)
        self.assertEqual(g["milestonesClaimed"], {"Terraformer": "Zed"})

    def test_milestone_limit_three_total(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.tr("Zed", +15)
        self.eng.milestone("Zed", "Terraformer")
        self.eng.milestone("Anna", "Mayor")        # opponent: warn-only
        self.eng.milestone("Felix", "Builder")
        with self.assertRaises(EventError):
            self.eng.milestone("Anna", "Gardener")  # all 3 slots gone

    def test_milestone_already_claimed_rejected(self):
        self.eng.res("Zed", "mc", +20)
        self.eng.tr("Zed", +15)
        self.eng.milestone("Zed", "Terraformer")
        with self.assertRaises(EventError):
            self.eng.milestone("Anna", "Terraformer")


class TestFreeActionCity(EngineTest):
    """Tharsis Republic's free first-action city
    placement went through place() alone (position + hex bonus only) —
    place() deliberately never touches tile counters or corp triggers
    (that split belongs to standard()/play()), so the free city silently
    undercounted tiles.cities by 1 and skipped Tharsis's own +1 MC
    prod / +3 MC trigger. This is the dedicated engine path for it."""

    def test_increments_city_counter(self):
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.eng.free_action_city("Zed")
        self.assertEqual(self.game()["me"]["tiles"]["cities"], 1)

    def test_triggers_tharsis_own_bonus_for_the_owner(self):
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.eng.free_action_city("Zed")
        g = self.game()
        self.assertEqual(g["me"]["production"]["mc"], 1)
        self.assertEqual(g["me"]["resources"]["mc"], 43)  # 40 + 3 own-city

    def test_no_standard_project_mc_prod_bonus_double_dip(self):
        # the SP City's own +1 MC prod is specific to that standard
        # project's printed text, not a universal city-placement rule —
        # a free action city must NOT also grant it (only Tharsis's own
        # corp-effect production step, asserted above, should land).
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.eng.free_action_city("Zed")
        self.assertEqual(self.game()["me"]["production"]["mc"], 1)

    def test_non_tharsis_corp_gets_the_tile_but_no_trigger(self):
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.free_action_city("Zed")
        g = self.game()
        self.assertEqual(g["me"]["tiles"]["cities"], 1)
        self.assertEqual(g["me"]["production"]["mc"], 0)
        self.assertEqual(g["me"]["resources"]["mc"], 57)

    def test_opponent_tharsis_holder_also_gets_the_prod_step(self):
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.corp("Anna", "Tharsis Republic", mc=40)
        self.eng.free_action_city("Anna")
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["tiles"]["cities"], 1)
        self.assertEqual(anna["production"]["mc"], 1)
        self.assertEqual(anna["resources"]["mc"], 43)


class TestStandardProjects(EngineTest):
    def test_power_plant_costs_11_adds_energy_prod(self):
        self.eng.res("Zed", "mc", +11)
        self.eng.standard("Zed", "power_plant")
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 0)
        self.assertEqual(g["me"]["production"]["energy"], 1)

    def test_asteroid_costs_14_raises_temp_and_tr(self):
        self.eng.res("Zed", "mc", +14)
        self.eng.standard("Zed", "asteroid")
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["me"]["tr"], 21)

    def test_aquifer_costs_18_places_ocean_and_tr(self):
        self.eng.res("Zed", "mc", +18)
        self.eng.standard("Zed", "aquifer")
        g = self.game()
        self.assertEqual(g["globals"]["oceans"], 1)
        self.assertEqual(g["me"]["tr"], 21)

    def test_greenery_costs_23(self):
        self.eng.res("Zed", "mc", +23)
        self.eng.standard("Zed", "greenery")
        g = self.game()
        self.assertEqual(g["me"]["tiles"]["greeneries"], 1)
        self.assertEqual(g["globals"]["oxygen"], 1)
        self.assertEqual(g["me"]["tr"], 21)

    def test_city_costs_25_adds_mc_prod_and_tile(self):
        self.eng.res("Zed", "mc", +25)
        self.eng.standard("Zed", "city")
        g = self.game()
        self.assertEqual(g["me"]["tiles"]["cities"], 1)
        self.assertEqual(g["me"]["production"]["mc"], 1)

    def test_sell_patents_gains_1mc_per_card_from_hand(self):
        self.eng.hand_add(["Comet", "Birds"])
        self.eng.standard("Zed", "sell_patents", cards=["Comet", "Birds"])
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 2)
        self.assertEqual(g["me"]["hand"], [])

    def test_insufficient_mc_rejected(self):
        with self.assertRaises(EventError):
            self.eng.standard("Zed", "asteroid")

    def test_opponent_standard_project_updates_summary(self):
        self.eng.res("Anna", "mc", +30)
        self.eng.standard("Anna", "city")
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["resources"]["mc"], 5)
        self.assertEqual(anna["tiles"]["cities"], 1)
        self.assertEqual(anna["production"]["mc"], 1)


class TestObserve(EngineTest):
    """Between-generation mat snapshot: adopt observed values, report drift."""

    def test_observe_adopts_full_snapshot_and_clears_estimated(self):
        self.eng.observe("green", tr=24, mc=12, steel=3, titanium=0,
                         plants=5, energy=2, heat=4)
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["tr"], 24)
        self.assertEqual(anna["resources"],
                         {"mc": 12, "steel": 3, "titanium": 0,
                          "plants": 5, "energy": 2, "heat": 4})
        self.assertFalse(anna["estimated"])
        self.assertEqual(anna["lastObservedGen"], 1)

    def test_observe_production_tracks_too(self):
        self.eng.observe("Anna", prod_mc=3, prod_plants=2)
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["production"]["mc"], 3)
        self.assertEqual(anna["production"]["plants"], 2)

    def test_observe_partial_leaves_other_fields_alone(self):
        self.eng.res("Anna", "steel", +4)
        self.eng.observe("Anna", mc=9)
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["resources"]["mc"], 9)
        self.assertEqual(anna["resources"]["steel"], 4)

    def test_observe_reports_drift_vs_simulation(self):
        self.eng.res("Anna", "mc", +5)  # simulated balance: 5
        msg = self.eng.observe("Anna", mc=17)
        self.assertIn("drift", msg.lower())
        self.assertIn("+12", msg)  # observed 17 vs simulated 5

    def test_observe_me_rejected(self):
        with self.assertRaises(EventError):
            self.eng.observe("Zed", mc=10)

    def test_produce_after_observe_marks_estimated_again(self):
        self.eng.observe("Anna", mc=10)
        self.eng.produce()
        self.assertTrue(self.game()["opponents"]["Anna"]["estimated"])


class TestOpponentResearch(EngineTest):
    def test_research_charges_3_per_kept_card(self):
        self.eng.res("Anna", "mc", +20)
        msg = self.eng.research("Anna", kept=2)
        self.assertEqual(self.game()["opponents"]["Anna"]["resources"]["mc"], 14)
        self.assertIn("2", msg)

    def test_research_own_redirects_to_dealt(self):
        with self.assertRaises(EventError):
            self.eng.research("Zed", kept=2)


class TestSyncForce(unittest.TestCase):
    """Correction path: sync --force may
    move a global DOWN to reverse a phantom raise."""
    def setUp(self):
        import tempfile as _tf
        from test_new_game import SETUP as _S
        self.tmp = _tf.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(_S)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sync_down_requires_force(self):
        self.eng.raise_param("oxygen", "Zed")
        with self.assertRaises(EventError):
            self.eng.sync_global("oxygen", 0)
        self.eng.sync_global("oxygen", 0, force=True)
        self.assertEqual(self.store.load_game()["globals"]["oxygen"], 0)


class TestBatch(EngineTest):
    """13c: apply.py batch — JSON-lines events from stdin, one engine call
    per line, committed line by line (state before a failing line stays)."""

    def _run(self, lines):
        import io, contextlib, apply, json
        stdin = io.StringIO("\n".join(json.dumps(l) if isinstance(l, dict) else l
                                      for l in lines) + "\n")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = apply.batch(self.eng, stdin)
        return rc, out.getvalue(), err.getvalue()

    def test_batch_success_applies_all_and_prints_each_result(self):
        rc, out, err = self._run([
            {"method": "res", "args": ["Zed", "mc", 7]},
            {"method": "prod", "args": ["Zed", "energy", 2]},
            {"method": "tr", "args": ["Anna", 1]},
        ])
        self.assertEqual(rc, 0, err)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 7)
        self.assertEqual(g["me"]["production"]["energy"], 2)
        self.assertEqual(g["opponents"]["Anna"]["tr"], 21)
        self.assertEqual(len(out.strip().splitlines()), 3)  # one result per line

    def test_batch_applies_in_order(self):
        # asteroid only affordable AFTER the +14 MC line — order matters
        rc, out, err = self._run([
            {"method": "res", "args": ["Zed", "mc", 14]},
            {"method": "standard", "args": ["Zed", "asteroid"]},
        ])
        self.assertEqual(rc, 0, err)
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["me"]["tr"], 21)

    def test_batch_reversed_order_fails_at_line_1(self):
        rc, out, err = self._run([
            {"method": "standard", "args": ["Zed", "asteroid"]},
            {"method": "res", "args": ["Zed", "mc", 14]},
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("line 1", err)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 0)  # nothing ran

    def test_batch_stops_at_first_error_prior_lines_stay_committed(self):
        rc, out, err = self._run([
            {"method": "res", "args": ["Zed", "mc", 5]},
            {"method": "res", "args": ["Zed", "steel", -1]},   # illegal
            {"method": "res", "args": ["Zed", "mc", 100]},     # must NOT run
        ])
        self.assertNotEqual(rc, 0)
        self.assertIn("line 2", err)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 5)   # line 1 IS committed
        self.assertEqual(g["me"]["resources"]["steel"], 0)

    def test_batch_bad_json_and_unknown_method_name_the_line(self):
        rc, out, err = self._run(["{not json"])
        self.assertNotEqual(rc, 0)
        self.assertIn("line 1", err)
        rc, out, err = self._run([{"method": "no_such_event"}])
        self.assertNotEqual(rc, 0)
        self.assertIn("no_such_event", err)

    def test_batch_help_documents_commit_semantics(self):
        import io, contextlib, apply
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            apply.main(["batch", "--help"])
        self.assertIn("committed", out.getvalue().lower())

    def test_batch_cli_reads_stdin(self):
        import subprocess
        script = Path(__file__).resolve().parent.parent / "scripts" / "apply.py"
        payload = '{"method": "res", "args": ["Zed", "mc", 9]}\n'
        r = subprocess.run([sys.executable, str(script), "batch"], input=payload,
                           cwd=self.tmp.name, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 9)


class TestProvenanceSnap(unittest.TestCase):
    """Public-anchor absorption — snap sets an observed
    absolute value on an opponent, logs the unexplained delta, updates
    provenance, and NEVER raises on inconsistency."""
    def setUp(self):
        import tempfile as _tf
        from test_new_game import SETUP as _S
        self.tmp = _tf.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(_S)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snap_tr_absorbs_unexplained_delta(self):
        msg = self.eng.snap("Anna", "tr", 27)
        g = self.store.load_game()
        self.assertEqual(g["opponents"]["Anna"]["tr"], 27)
        self.assertIn("unexplained", msg)
        self.assertEqual(g["opponents"]["Anna"]["provenance"]["tr"], "observed")

    def test_snap_resource_and_generation_stamp(self):
        self.eng.snap("Anna", "heat", 11)
        g = self.store.load_game()
        self.assertEqual(g["opponents"]["Anna"]["resources"]["heat"], 11)
        self.assertEqual(g["opponents"]["Anna"]["provenance"]["asOfGen"],
                         g["generation"])

    def test_snap_equal_value_is_quiet_confirmation(self):
        g = self.store.load_game()
        cur = g["opponents"]["Anna"]["tr"]
        msg = self.eng.snap("Anna", "tr", cur)
        self.assertIn("confirmed", msg)

    def test_observe_marks_provenance_observed(self):
        self.eng.observe("Anna", mc=33)
        g = self.store.load_game()
        self.assertEqual(g["opponents"]["Anna"]["provenance"]["resources"],
                         "observed")


class TestTilesFix(unittest.TestCase):
    def setUp(self):
        import tempfile
        from tmlib import Store, Engine
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        from test_new_game import SETUP
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tiles_fix_sets_counter_with_provenance(self):
        self.eng.tiles_fix("Zed", "cities", 1)
        g = self.store.load_game()
        self.assertEqual(g["me"]["tiles"]["cities"], 1)

    def test_tiles_fix_rejects_unknown_kind(self):
        from tmlib import EventError
        with self.assertRaises(EventError):
            self.eng.tiles_fix("Zed", "volcanoes", 2)


class TestOpponentMetalPayment(EngineTest):
    """play() honoured --steel/--titanium/--heat only on MY branch;
    for an opponent the metals were accepted and silently ignored, so their
    steel pile never went down and `cost` had to be hand-converted to
    net MC at the call site. Same semantics on both branches now: `cost`
    is the card's GROSS cost, metals cover part of it."""

    def test_opponent_steel_is_spent_and_covers_cost(self):
        self.eng.res("Anna", "mc", +20)
        self.eng.res("Anna", "steel", +10)
        self.eng.play("Anna", "Mining Rights", cost=9, steel=4)
        opp = self.game()["opponents"]["Anna"]["resources"]
        self.assertEqual(opp["steel"], 6)          # 10 − 4
        self.assertEqual(opp["mc"], 19)            # 20 − max(0, 9 − 4×2)

    def test_opponent_titanium_is_spent(self):
        self.eng.res("Anna", "mc", +20)
        self.eng.res("Anna", "titanium", +5)
        self.eng.play("Anna", "Comet", cost=21, titanium=5)
        opp = self.game()["opponents"]["Anna"]["resources"]
        self.assertEqual(opp["titanium"], 0)
        self.assertEqual(opp["mc"], 14)            # 20 − max(0, 21 − 15)

    def test_opponent_metal_stock_floors_at_zero(self):
        """Opponent stocks are ESTIMATES — over-spending clamps, never raises."""
        self.eng.res("Anna", "mc", +20)
        self.eng.play("Anna", "Mining Rights", cost=9, steel=4)
        self.assertEqual(
            self.game()["opponents"]["Anna"]["resources"]["steel"], 0)


class TestAnonymousAttack(unittest.TestCase):
    """'Someone removed 4 of my
    money' must be loggable — effect applies NOW, attribution pends."""

    def setUp(self):
        import tempfile
        from tmlib import Store, Engine
        from test_new_game import SETUP
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.eng.res("Zed", "mc", 20)

    def tearDown(self):
        self.tmp.cleanup()

    def test_attack_applies_effect_and_pends_attribution(self):
        msg = self.eng.attack("Zed", "mc", 4)
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 16)
        self.assertEqual(len(g.get("pendingAttribution", [])), 1)
        self.assertIn("who", msg.lower())          # prompts the ask

    def test_attack_with_known_attacker_attributes(self):
        self.eng.attack("Zed", "mc", 4, by="Anna")
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 16)
        self.assertEqual(g.get("pendingAttribution", []), [])

    def test_attribute_resolves_pending(self):
        self.eng.attack("Zed", "plants", 0, by=None)  # zero-effect probe
        self.eng.attribute(0, "Anna")
        g = self.store.load_game()
        self.assertEqual(g["pendingAttribution"], [])


class TestDeclaredFinalGeneration(unittest.TestCase):
    """The table's 'this is the last generation' vote pins the
    clock — advisor flips to pure-VP mode."""

    def setUp(self):
        import tempfile
        from tmlib import Store, Engine
        from test_new_game import SETUP
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_final_declaration_recorded_and_pins_clock(self):
        import clock
        self.eng.declare_final()
        g = self.store.load_game()
        self.assertEqual(g["declaredFinalGeneration"], g["generation"])
        est = clock.estimate(g["globals"], g["generation"], players=3,
                             declared_final=g.get("declaredFinalGeneration"))
        self.assertEqual(est["gensLeft"], 0)
        self.assertEqual(est["phase"], "points")
