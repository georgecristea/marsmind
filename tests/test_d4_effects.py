"""D4 — two interpreter generalisations (private/plans/handoff-opus-2026-08-29.md).

H4b  A standard-project rebate is CARD DATA (`behavior.standardProjectRebate`
     = {"amount": N, "except": [project, …]}), applied by Engine.standard for
     every rebate source the acting player holds — the corporation rule AND
     any tableau card carrying the key — AFTER the gross price was checked
     and paid (KB 04: rebates arrive after payment). The vendor's
     StandardProjectCard.projectPlayed() calls onStandardProject on every
     tableau card (corporations included: Player.tableau = playedCards, whose
     array holds the corporation too), so CrediCor and a rebate card stack;
     StandardTechnology.onStandardProject excludes SELL_PATENTS only.

H4c  A card whose ocean / temperature / oxygen effect cannot fire because the
     track is full still resolves for its cost, tags and printed VP, but
     NOTHING downstream fires: no placement obligation, no hex bonus, no
     ocean-adjacency MC, no ocean-trigger gain (Game.addOcean returns before
     addTile when canAddOcean() is false; ArtificialLake.bespokeCanPlay says
     "Card is playable, it just has no effect").

Plus the small D3 follow-up: the replayer passes the drained line's
generation into Engine.use_action so a stale reflection is absorbed.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tmlib                                              # noqa: E402
from tmlib import Store, Engine, EventError               # noqa: E402
from replay_applog import Replayer, Report                # noqa: E402
from test_new_game import SETUP                           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = json.loads((ROOT / "cards" / "db.json").read_text())
BY_NAME = {c["name"]: c for c in DB["cards"]}

# Test data, resolved from the db by SHAPE so the test never depends on a
# name the engine must not know: a card with a standard-project rebate, a
# land-ocean card, a card with a persistent ocean trigger, a plain
# temperature card.
REBATE_CARD = next(c["name"] for c in DB["cards"]
                   if isinstance((c.get("behavior") or {})
                                 .get("standardProjectRebate"), dict))
LAND_OCEAN_CARD = next(
    c["name"] for c in DB["cards"]
    if isinstance((c.get("behavior") or {}).get("ocean"), dict)
    and c["behavior"]["ocean"].get("on") == "land"
    and isinstance(c.get("vp"), int))
OCEAN_TRIGGER_CARD = next(iter(tmlib.OCEAN_TRIGGERS))
TEMP_CARD = next(
    c["name"] for c in DB["cards"]
    if (c.get("behavior") or {}).get("global") == {"temperature": 1}
    and set(c["behavior"]) <= {"global", "stock", "removeAnyPlants"}
    and not c.get("requirements"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def game(self) -> dict:
        return self.store.load_game()

    def me(self) -> dict:
        return self.game()["me"]

    def play_rebate_card(self, mc: int = 40) -> None:
        self.eng.res("Zed", "mc", +mc)
        self.eng.hand_add([REBATE_CARD])
        self.eng.play("Zed", REBATE_CARD)


# ── H4b ──────────────────────────────────────────────────────


class TestRebateData(unittest.TestCase):
    def test_db_carries_the_rebate_as_behavior(self):
        spec = BY_NAME[REBATE_CARD]["behavior"]["standardProjectRebate"]
        self.assertEqual(spec, {"amount": 3, "except": ["sell_patents"]})

    def test_engine_never_names_the_card(self):
        src = (ROOT / "scripts" / "tmlib.py").read_text()
        self.assertNotIn(REBATE_CARD, src)


class TestCardRebate(Base):
    def test_rebate_after_a_standard_project(self):
        self.play_rebate_card(40)
        before = self.me()["resources"]["mc"]
        cost = tmlib.STANDARD_PROJECTS["power_plant"]
        msg = self.eng.standard("Zed", "power_plant")
        self.assertEqual(self.me()["resources"]["mc"], before - cost + 3)
        self.assertIn("+3 MC", msg)
        self.assertIn(REBATE_CARD, msg)

    def test_no_rebate_after_sell_patents(self):
        self.play_rebate_card(40)
        self.eng.hand_add(["Some Card"])
        before = self.me()["resources"]["mc"]
        msg = self.eng.standard("Zed", "sell_patents", cards=["Some Card"])
        self.assertEqual(self.me()["resources"]["mc"], before + 1)
        self.assertNotIn("+3 MC", msg)

    def test_corp_and_card_rebates_stack(self):
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.hand_add([REBATE_CARD])
        self.eng.play("Zed", REBATE_CARD)
        before = self.me()["resources"]["mc"]
        cost = tmlib.STANDARD_PROJECTS["greenery"]        # base 23 ≥ 20
        msg = self.eng.standard("Zed", "greenery")
        self.assertEqual(self.me()["resources"]["mc"], before - cost + 4 + 3)
        self.assertIn("+4 MC", msg)
        self.assertIn("+3 MC", msg)

    def test_gross_affordability_is_checked_before_the_rebate(self):
        self.play_rebate_card(40)
        have = self.me()["resources"]["mc"]
        cost = tmlib.STANDARD_PROJECTS["power_plant"]
        # bring the stock to one short of the GROSS price: net-of-rebate
        # it would be affordable, but the rebate arrives after payment
        self.eng.res("Zed", "mc", (cost - 1) - have)
        self.assertEqual(self.me()["resources"]["mc"], cost - 1)
        with self.assertRaises(EventError):
            self.eng.standard("Zed", "power_plant")
        self.assertEqual(self.me()["resources"]["mc"], cost - 1)

    def test_quote_carries_the_card_rebate(self):
        self.play_rebate_card(40)
        g = self.game()
        self.assertEqual(
            tmlib.standard_project_price(g, "Zed", "power_plant")["rebate"], 3)
        self.assertEqual(
            tmlib.standard_project_price(g, "Zed", "sell_patents")["rebate"], 0)

    def test_quote_stacks_corp_and_card(self):
        self.eng.corp("Zed", "CrediCor", mc=57)
        self.eng.hand_add([REBATE_CARD])
        self.eng.play("Zed", REBATE_CARD)
        g = self.game()
        self.assertEqual(
            tmlib.standard_project_price(g, "Zed", "city")["rebate"], 7)

    def test_opponent_holding_the_card_is_refunded_too(self):
        self.eng.res("Anna", "mc", +40)
        self.eng.play("Anna", REBATE_CARD)
        before = self.game()["opponents"]["Anna"]["resources"]["mc"]
        cost = tmlib.STANDARD_PROJECTS["power_plant"]
        self.eng.standard("Anna", "power_plant")
        self.assertEqual(self.game()["opponents"]["Anna"]["resources"]["mc"],
                         before - cost + 3)

    def test_without_the_card_nothing_changes(self):
        self.eng.res("Zed", "mc", +40)
        before = self.me()["resources"]["mc"]
        cost = tmlib.STANDARD_PROJECTS["power_plant"]
        self.eng.standard("Zed", "power_plant")
        self.assertEqual(self.me()["resources"]["mc"], before - cost)


# ── H4c ──────────────────────────────────────────────────────


class OceanBase(Base):
    def fill_oceans(self, n: int) -> None:
        """n ocean tiles on the board AND the track at n."""
        for sid in [s["id"] for s in self.eng.legal_spaces("ocean")][:n]:
            self.eng.place("Anna", "ocean", sid)
        self.eng.sync_global("oceans", n)

    def land_hex(self) -> str:
        occupied = self.game().get("board", {})
        for sid, sp in self.eng._board().items():
            if sp.get("offMap") or sp["oceanReserved"] or sid in occupied:
                continue
            return sid
        raise AssertionError("no free land hex")

    def prime(self, oceans: int) -> None:
        # the ocean-trigger card first (its own requirement is a cold
        # planet), then the land-ocean card's temperature requirement
        self.eng.res("Zed", "mc", +60)
        self.eng.hand_add([OCEAN_TRIGGER_CARD, LAND_OCEAN_CARD])
        self.eng.play("Zed", OCEAN_TRIGGER_CARD)
        self.eng.sync_global("temperature", 0)
        self.fill_oceans(oceans)


class TestMaxedOcean(OceanBase):
    def test_land_ocean_card_at_max_resolves_with_no_effects(self):
        self.prime(9)
        before = self.me()
        msg = self.eng.play("Zed", LAND_OCEAN_CARD)
        after = self.me()
        cost = BY_NAME[LAND_OCEAN_CARD]["cost"]
        self.assertEqual(after["resources"]["mc"], before["resources"]["mc"] - cost)
        self.assertEqual(after["resources"]["plants"], before["resources"]["plants"])
        self.assertEqual(after["tr"], before["tr"])
        self.assertEqual(self.game()["globals"]["oceans"], 9)
        self.assertNotIn("→ TABLE: place", msg)
        self.assertIn("maxed", msg)
        self.assertIn("VP", msg)
        self.assertIn(LAND_OCEAN_CARD, [c["name"] for c in after["playedCards"]])
        # no placement obligation: the plan's place step is refused, so
        # neither the hex bonus nor ocean-adjacency MC can be simulated
        hex_id = self.land_hex()
        with self.assertRaises(EventError):
            self.eng.place("Zed", "ocean", hex_id, card=LAND_OCEAN_CARD)
        self.assertNotIn(hex_id, self.game()["board"])
        self.assertEqual(self.me()["resources"]["mc"], after["resources"]["mc"])

    def test_legal_ocean_spaces_are_empty_when_the_board_is_full(self):
        self.fill_oceans(9)
        self.assertEqual(self.eng.legal_spaces("ocean"), [])

    def test_land_ocean_card_below_max_still_places(self):
        self.prime(8)
        before = self.me()
        msg = self.eng.play("Zed", LAND_OCEAN_CARD)
        after = self.me()
        self.assertEqual(self.game()["globals"]["oceans"], 9)
        self.assertEqual(after["tr"], before["tr"] + 1)
        self.assertEqual(after["resources"]["plants"],
                         before["resources"]["plants"] + 2)   # ocean trigger
        self.assertIn("→ TABLE: place", msg)
        hex_id = self.land_hex()
        self.eng.place("Zed", "ocean", hex_id, card=LAND_OCEAN_CARD)
        self.assertEqual(self.game()["board"][hex_id],
                         {"tile": "ocean", "player": "Zed"})


class TestMaxedTemperature(Base):
    def test_temperature_card_at_max_keeps_cost_tags_and_stock(self):
        self.eng.sync_global("temperature", 8)
        self.eng.res("Zed", "mc", +40)
        self.eng.hand_add([TEMP_CARD])
        before = self.me()
        info = BY_NAME[TEMP_CARD]
        msg = self.eng.play("Zed", TEMP_CARD)
        after = self.me()
        self.assertEqual(after["resources"]["mc"],
                         before["resources"]["mc"] - info["cost"])
        for r, d in (info["behavior"].get("stock") or {}).items():
            self.assertEqual(after["resources"][r], before["resources"][r] + d)
        self.assertEqual(self.game()["globals"]["temperature"], 8)
        self.assertEqual(after["tr"], before["tr"])
        self.assertEqual(after["production"]["heat"], before["production"]["heat"])
        self.assertIn("maxed", msg)
        self.assertIn(TEMP_CARD, [c["name"] for c in after["playedCards"]])


# ── replay passes the generation through ─────────────────────


class TestReplayGeneration(Base):
    ACTION = "Ironworks"

    def setUp(self):
        super().setUp()
        self.eng.register_action(self.ACTION)
        self.eng.res("Zed", "energy", +12)
        self.rep = Report()
        self.replayer = Replayer(self.eng, self.rep, verbose=False)

    def head(self, line: int = 5) -> dict:
        return {"head": {"kind": "used_action", "player": "Zed",
                         "card": self.ACTION, "line": line,
                         "raw": f"Zed used {self.ACTION} action"},
                "tail": []}

    def ledger(self) -> dict:
        return self.me()["actionsThisGen"][self.ACTION]

    def test_stale_line_is_absorbed_and_leaves_the_ledger_alone(self):
        self.eng.use_action(self.ACTION)                  # generation 1
        self.eng.produce()                                # generation 2
        self.assertEqual(self.ledger(), {"used": False})
        energy = self.me()["resources"]["energy"]
        o2 = self.game()["globals"]["oxygen"]
        self.replayer.block(self.head(), gen=1)           # gen-1 echo, drained late
        self.assertEqual(self.ledger(), {"used": False})
        self.assertEqual(self.me()["resources"]["energy"], energy)
        self.assertEqual(self.game()["globals"]["oxygen"], o2)
        self.assertIn("absorbed", self.store.log_path.read_text())

    def test_stale_line_never_reopens_a_used_slot(self):
        self.eng.produce()                                # generation 2
        # produce() turns every unit of energy into heat, so the setUp
        # stock is gone by now — refill before the gen-2 use.
        self.eng.res("Zed", "energy", +12)
        self.eng.use_action(self.ACTION)                  # the gen-2 use
        self.assertEqual(self.ledger(), {"used": True, "gen": 2})
        self.replayer.block(self.head(), gen=1)
        self.assertEqual(self.ledger(), {"used": True, "gen": 2})

    def test_current_generation_line_applies(self):
        self.eng.produce()                                # generation 2
        o2 = self.game()["globals"]["oxygen"]
        self.replayer.block(self.head(), gen=2)
        self.assertEqual(self.ledger(), {"used": True, "gen": 2})
        self.assertEqual(self.game()["globals"]["oxygen"], o2 + 1)

    def test_generation_head_sets_the_replayer_generation(self):
        self.assertIsNone(self.replayer.gen)
        self.replayer.block({"head": {"kind": "generation", "n": 2, "line": 1},
                             "tail": []})
        self.assertEqual(self.replayer.gen, 2)
        self.assertEqual(self.game()["generation"], 2)
        self.replayer.block(self.head())                  # no gen kwarg: uses it
        self.assertEqual(self.ledger(), {"used": True, "gen": 2})


if __name__ == "__main__":
    unittest.main()
