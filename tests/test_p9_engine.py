"""P9 issues 3, 4 and 5 — three PREDICTION gaps found in game1 (2026-08-29).

In every case the app was adopted and the tracker stayed byte-exact, so
none of them corrupted state; all three made the SANDBOX (planlib's
simulation, i.e. every number the advisor quotes before a step is taken)
wrong.

  3. A blue-card action's per-use cost was registered in `actionsThisGen`
     ({"Search For Life": {"used": false, "mcCost": 1}}) but never spent
     when the action was simulated: gen 1 step 2c `mc: sandbox predicted
     8, app shows 7 (Δ −1)`, and again in every generation the action was
     used.
  4. "Decrease any X production 1 step and increase your own" (Great
     Escarpment Consortium, gen 3) and "increase THAT production 1 step"
     for a hex placement bonus (Mining Rights, gen 4) both applied only
     half the effect: `prod.steel: sandbox predicted 1, app shows 2`.
     Both are card DATA gaps — the fix belongs in cards/db.json, and the
     vocabulary it uses (decreaseAnyProduction + production, and an
     or-choice over the two bonus resources) is already interpreted.
  5. The oxygen track's 8% bonus — a FREE temperature step for whoever
     raised it — was not modelled, although the temperature track's own
     −24/−20 heat bonus was: gen 9 SP greenery predicted TR 25, the app
     showed 26 (`globals temperature −24 → −22, Zed TR 25 → 26`).
     Authority: vendor Game.increaseOxygenLevel + constants
     OXYGEN_LEVEL_FOR_TEMPERATURE_BONUS = 8.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from tmlib import Store, Engine, EventError, action_spend_options  # noqa: E402
from test_new_game import SETUP  # noqa: E402


def card(name: str) -> dict:
    db = json.loads((ROOT / "cards" / "db.json").read_text())
    for c in db["cards"]:
        if c["name"] == name:
            return c
    raise AssertionError(f"{name} is not in cards/db.json")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def mine(self):
        return self.store.load_game()["me"]

    def globals(self):
        return self.store.load_game()["globals"]


# ── issue 3 — blue-card action costs ─────────────────────────────────

class TestActionCostIsSpent(Base):
    """The registered per-use cost must leave the stock when the action
    is used — that is the whole of the −1 MC drift."""

    def play_sfl(self, mc: int = 20) -> None:
        self.eng.res("Zed", "mc", mc)
        self.eng.hand_add(["Search For Life"])
        self.eng.play("Zed", "Search For Life")

    def test_the_cost_is_registered_by_play(self):
        """Precondition of the whole issue: the data is already there."""
        self.play_sfl()
        self.assertEqual(self.mine()["actionsThisGen"]["Search For Life"],
                         {"used": False, "mcCost": 1})

    def test_using_the_action_spends_the_registered_mc(self):
        self.play_sfl()
        before = self.mine()["resources"]["mc"]
        self.eng.use_action("Search For Life")
        self.assertEqual(self.mine()["resources"]["mc"], before - 1)

    def test_the_trace_names_the_charge(self):
        self.play_sfl()
        msg = self.eng.use_action("Search For Life")
        self.assertIn("mc", msg.lower())
        self.assertIn("1", msg)

    def test_ledger_still_closes(self):
        self.play_sfl()
        self.eng.use_action("Search For Life")
        self.assertTrue(self.mine()["actionsThisGen"]["Search For Life"]["used"])
        with self.assertRaises(EventError):
            self.eng.use_action("Search For Life")

    def test_short_of_the_cost_refuses_before_mutating(self):
        self.play_sfl(mc=3)          # 3 MC card, 0 left
        self.assertEqual(self.mine()["resources"]["mc"], 0)
        with self.assertRaises(EventError):
            self.eng.use_action("Search For Life")
        self.assertEqual(self.mine()["resources"]["mc"], 0)
        self.assertFalse(self.mine()["actionsThisGen"]["Search For Life"]["used"])

    def test_correct_py_inverse_refunds_it(self):
        """unuse_action is the reversal path; it must give the MC back or
        correct.py silently loses 1 MC per reversed action step."""
        self.play_sfl()
        before = self.mine()["resources"]["mc"]
        self.eng.use_action("Search For Life")
        self.eng.unuse_action("Search For Life")
        self.assertEqual(self.mine()["resources"]["mc"], before)
        self.assertFalse(self.mine()["actionsThisGen"]["Search For Life"]["used"])

    def test_an_opponents_action_charges_their_estimate(self):
        self.eng.res("Anna", "mc", 10)
        self.eng.play("Anna", "Search For Life")
        self.eng.use_action("Search For Life", player="Anna")
        opp = self.store.load_game()["opponents"]["Anna"]
        self.assertEqual(opp["resources"]["mc"], 10 - 3 - 1)

    def test_a_structured_action_is_not_double_charged(self):
        """Restricted Area pays through its own actionBehavior.spend; the
        registered mcCost is DERIVED from that block, so charging it again
        would double the cost."""
        self.assertTrue(any(action_spend_options(card("Restricted Area"))))
        self.eng.res("Zed", "mc", 30)
        self.eng.hand_add(["Restricted Area"])
        self.eng.play("Zed", "Restricted Area")
        before = self.mine()["resources"]["mc"]
        self.eng.use_action("Restricted Area")
        self.assertEqual(self.mine()["resources"]["mc"], before - 2)

    def test_a_free_action_still_costs_nothing(self):
        self.eng.res("Zed", "mc", 30)
        self.eng.hand_add(["Ironworks"])
        self.eng.play("Zed", "Ironworks")
        self.eng.res("Zed", "energy", 4)
        before = self.mine()["resources"]["mc"]
        self.eng.use_action("Ironworks")
        self.assertEqual(self.mine()["resources"]["mc"], before)


# ── issue 4 — decrease any / increase your own ───────────────────────

class TestDecreaseAnyIncreaseOwn(Base):
    """Great Escarpment Consortium: 'Decrease any steel production 1 step
    and increase your own 1 step.' The sandbox applied the decrease only."""

    def test_the_db_carries_both_halves(self):
        beh = card("Great Escarpment Consortium")["behavior"] or {}
        self.assertEqual(beh.get("decreaseAnyProduction"),
                         {"type": "steel", "count": 1})
        self.assertEqual(beh.get("production"), {"steel": 1})

    def setup_play(self):
        self.eng.res("Zed", "mc", 30)
        self.eng.prod("Zed", "steel", 1)          # the card's requirement
        self.eng.prod("Anna", "steel", 2)
        self.eng.hand_add(["Great Escarpment Consortium"])

    def test_my_own_steel_production_goes_up(self):
        self.setup_play()
        self.eng.play("Zed", "Great Escarpment Consortium", target="Anna")
        game = self.store.load_game()
        self.assertEqual(game["me"]["production"]["steel"], 2)
        self.assertEqual(game["opponents"]["Anna"]["production"]["steel"], 1)

    def test_the_increase_applies_even_without_a_named_victim(self):
        """No --target is a TABLE step for the decrease; my own half is
        not optional and must still be applied."""
        self.setup_play()
        msg = self.eng.play("Zed", "Great Escarpment Consortium")
        self.assertEqual(self.mine()["production"]["steel"], 2)
        self.assertIn("TABLE", msg)


class TestMiningRightsBonusProduction(Base):
    """Mining Rights / Mining Area: 'Place this tile on an area with a
    steel or titanium placement bonus. Increase that production 1 step.'
    Which resource depends on the hex, so it is the app's own
    SelectResourceType prompt — an or-choice, in card-text order."""

    def branches(self, name: str) -> list:
        beh = card(name)["behavior"] or {}
        return ((beh.get("or") or {}).get("behaviors")) or []

    def test_the_db_offers_both_bonus_resources(self):
        for name in ("Mining Rights", "Mining Area"):
            with self.subTest(card=name):
                got = [b.get("production") for b in self.branches(name)]
                self.assertEqual(got, [{"steel": 1}, {"titanium": 1}])

    def test_the_choice_is_marked_deferred(self):
        """The hex is not known at play time — the app asks afterwards, so
        a missing choice must not refuse a legal play."""
        for name in ("Mining Rights", "Mining Area"):
            with self.subTest(card=name):
                self.assertTrue((card(name)["behavior"]["or"])["deferred"])

    def test_steel_branch(self):
        self.eng.res("Zed", "mc", 30)
        self.eng.hand_add(["Mining Rights"])
        self.eng.play("Zed", "Mining Rights", choice=0)
        self.assertEqual(self.mine()["production"]["steel"], 1)
        self.assertEqual(self.mine()["production"]["titanium"], 0)

    def test_titanium_branch(self):
        self.eng.res("Zed", "mc", 30)
        self.eng.hand_add(["Mining Rights"])
        self.eng.play("Zed", "Mining Rights", choice=1)
        self.assertEqual(self.mine()["production"]["titanium"], 1)
        self.assertEqual(self.mine()["production"]["steel"], 0)

    def test_no_choice_is_a_table_step_not_a_silent_zero(self):
        """Guessing the bonus resource is the class of silent error this
        issue is about, and refusing a legal play is not an option either
        (the replayer and every existing caller play the card without a
        branch): the trace has to ASK."""
        self.eng.res("Zed", "mc", 30)
        self.eng.hand_add(["Mining Rights"])
        msg = self.eng.play("Zed", "Mining Rights")
        self.assertIn("TABLE", msg)
        self.assertIn("--choice 0", msg)
        self.assertIn("--choice 1", msg)
        self.assertEqual(self.mine()["production"]["steel"], 0)
        self.assertEqual(self.mine()["production"]["titanium"], 0)

    def test_an_opponents_play_is_never_blocked(self):
        """An opponent's state is an estimate and their log line must
        always apply — the same rule every or-card already follows."""
        self.eng.res("Anna", "mc", 30)
        self.eng.play("Anna", "Mining Rights")
        played = self.store.load_game()["opponents"]["Anna"]["playedCards"]
        self.assertEqual([c["name"] for c in played], ["Mining Rights"])


# ── issue 5 — the oxygen track's 8% bonus ────────────────────────────

class TestOxygenTrackBonus(Base):
    """vendor Game.increaseOxygenLevel: crossing 8% gives the raiser a
    free temperature step, which grants its own TR (and can chain the
    −24/−20 heat bonus and the 0 °C ocean)."""

    def to_oxygen(self, pct: int) -> None:
        self.store.save_game(
            {**self.store.load_game(),
             "globals": {**self.globals(), "oxygen": pct}})

    def test_reaching_eight_percent_raises_the_temperature(self):
        self.to_oxygen(7)
        self.eng.raise_param("oxygen", "Zed")
        self.assertEqual(self.globals()["oxygen"], 8)
        self.assertEqual(self.globals()["temperature"], -28)

    def test_the_bonus_step_grants_its_own_tr(self):
        self.to_oxygen(7)
        before = self.mine()["tr"]
        self.eng.raise_param("oxygen", "Zed")
        self.assertEqual(self.mine()["tr"], before + 2)   # O2 raise + bonus

    def test_no_bonus_below_or_above_the_threshold(self):
        for start in (5, 8, 9):
            with self.subTest(oxygen=start), tempfile.TemporaryDirectory() as d:
                store = Store(d)
                store.init(SETUP)
                eng = Engine(store)
                store.save_game({**store.load_game(),
                                 "globals": {**store.load_game()["globals"],
                                             "oxygen": start}})
                eng.raise_param("oxygen", "Zed")
                self.assertEqual(store.load_game()["globals"]["temperature"],
                                 -30)
                self.assertEqual(store.load_game()["me"]["tr"], 21)

    def test_the_greenery_standard_project_chains_it(self):
        """The reported line: gen 9 SP greenery, TR 25 → 26 not 25."""
        self.to_oxygen(7)
        self.eng.res("Zed", "mc", 30)
        before = self.mine()["tr"]
        self.eng.standard("Zed", "greenery")
        self.assertEqual(self.globals()["temperature"], -28)
        self.assertEqual(self.mine()["tr"], before + 2)

    def test_a_plant_conversion_chains_it(self):
        self.to_oxygen(7)
        self.eng.res("Zed", "plants", 8)
        before = self.mine()["tr"]
        self.eng.convert("Zed", "plants")
        self.assertEqual(self.globals()["temperature"], -28)
        self.assertEqual(self.mine()["tr"], before + 2)

    def test_an_opponent_collects_their_own_bonus(self):
        self.to_oxygen(7)
        opp_before = self.store.load_game()["opponents"]["Anna"]["tr"]
        self.eng.raise_param("oxygen", "Anna")
        game = self.store.load_game()
        self.assertEqual(game["opponents"]["Anna"]["tr"], opp_before + 2)
        self.assertEqual(game["me"]["tr"], 20)

    def test_the_bonus_temperature_step_can_chain_the_heat_bonus(self):
        """At −26 the free step lands on −24, which is itself a track
        bonus: +1 heat production for the same player."""
        self.store.save_game(
            {**self.store.load_game(),
             "globals": {**self.globals(), "oxygen": 7, "temperature": -26}})
        self.eng.raise_param("oxygen", "Zed")
        game = self.store.load_game()
        self.assertEqual(game["globals"]["temperature"], -24)
        self.assertEqual(game["me"]["production"]["heat"], 1)
        self.assertEqual(game["me"]["tr"], 22)

    def test_maxed_temperature_gives_no_bonus_tr(self):
        self.store.save_game(
            {**self.store.load_game(),
             "globals": {**self.globals(), "oxygen": 7, "temperature": 8}})
        self.eng.raise_param("oxygen", "Zed")
        self.assertEqual(self.store.load_game()["me"]["tr"], 21)

    def test_the_world_government_step_still_grants_no_tr(self):
        """WGT is the solar phase: the 8% chain fires, the bonuses do not
        (already modelled in wgt(); this pins it against the new path)."""
        setup = {**SETUP, "expansions": ["base", "corporateEra", "wgt"]}
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            store.init(setup)
            eng = Engine(store)
            store.save_game({**store.load_game(),
                             "globals": {**store.load_game()["globals"],
                                         "oxygen": 7, "temperature": -26}})
            eng.wgt("oxygen")
            game = store.load_game()
            self.assertEqual(game["globals"]["oxygen"], 8)
            self.assertEqual(game["globals"]["temperature"], -24)
            self.assertEqual(game["me"]["tr"], 20)
            self.assertEqual(game["me"]["production"]["heat"], 0)


if __name__ == "__main__":
    unittest.main()
