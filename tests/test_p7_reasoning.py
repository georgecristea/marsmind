"""P7 autopilot game (2026-08-28) — reasoning-quality regressions.

Two defects the first full API-autopilot game surfaced. Each test names the
observed symptom so a future reader can tie it back to
that game's log.

L1 award funding was flagged off a LEAD test where the KB demands a LOCK
   test (strategy/02-archetypes-game-arc.md, strategy/04-card-tiers.md:
   "fund only if you can LOCK the metric by the last generation — price
   every rival's reachable max INCLUDING last-gen production cards").
   Observed at generation 3, ~7 generations left and rivals sitting on
   ~80 M€ unspent: "Banker lockable: Zed leads by 3".
L2 no warning before ending a turn on 9 plants while plant removal was
   live: an opponent's Deimos Down took 8 (~19 M€ of greenery value),
   an Asteroid took 3 more in gen 7 — 11 plants lost across the game.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import menu                                       # noqa: E402
import planlib                                    # noqa: E402
import races                                      # noqa: E402
from tmlib import Store                           # noqa: E402
from test_new_game import SETUP                   # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def setup(self):
        return self.store.load_setup()

    def save(self, g):
        self.store.save_game(g)

    def award_item(self, game, award):
        items = menu.available_actions(game, self.setup())
        return next((i for i in items
                     if i["kind"] == "award" and i["name"] == award), None)


# ── L1: award funding is a LOCK test, not a lead test ────────────────────

class TestAwardLockTest(Base):
    def banker_state(self, gen: int, my_prod: int, opp_prod: int,
                     opp_cash: int) -> dict:
        g = self.game()
        g["generation"] = gen
        g["me"]["resources"]["mc"] = 40           # enough to fund a slot
        g["me"]["production"]["mc"] = my_prod
        for n in g["opponents"]:
            g["opponents"][n]["production"]["mc"] = opp_prod
            g["opponents"][n]["resources"]["mc"] = opp_cash
        self.save(g)
        return self.game()

    def test_gen3_banker_lead_over_unspent_banks_is_not_lockable(self):
        """Observed: 'Banker lockable: Zed leads by 3 (slot 1 costs 8 MC)'
        at generation 3 with ~7 generations left and both rivals holding
        ~80 M€ unspent — M€ buys the production that flips Banker."""
        g = self.banker_state(3, my_prod=5, opp_prod=2, opp_cash=80)
        lock = menu.award_lock(g, "Banker", self.setup())
        self.assertFalse(lock["lockable"], lock["why"])
        self.assertIn("reachable", lock["why"])

        alerts = races.race_table(g, self.setup())["alerts"]
        banker = [a for a in alerts if a.startswith("Banker")]
        self.assertTrue(banker, alerts)
        self.assertIn("NOT lockable", banker[0])
        self.assertNotIn("Banker lockable", " ".join(alerts))

        item = self.award_item(g, "Banker")
        self.assertIsNotNone(item)
        self.assertNotIn("(LOCKABLE)", item["detail"])
        self.assertIn("not lockable", item["detail"])

    def test_final_generation_lead_is_lockable(self):
        """The same 3-step lead in the declared final generation IS a
        lock — nobody has the turns left to reach it."""
        g = self.banker_state(8, my_prod=8, opp_prod=5, opp_cash=5)
        g["declaredFinalGeneration"] = 8
        self.save(g)
        g = self.game()
        lock = menu.award_lock(g, "Banker", self.setup())
        self.assertTrue(lock["lockable"], lock["why"])
        alerts = " ".join(races.race_table(g, self.setup())["alerts"])
        self.assertIn("Banker LOCKABLE", alerts)
        self.assertIn("(LOCKABLE)", self.award_item(g, "Banker")["detail"])

    def test_big_landlord_lead_a_rivals_bank_can_still_buy_is_not_lockable(self):
        """Landlord is cash-convertible too (M€ → standard-project tiles):
        an 8-vs-3 tile lead with 2 generations left does not survive a
        120 M€ bank, but does survive a broke rival."""
        g = self.game()
        g["generation"] = 6
        g["globals"] = {"temperature": -10, "oxygen": 5, "oceans": 3}
        g["me"]["resources"]["mc"] = 40
        g["me"]["tiles"] = {"cities": 2, "greeneries": 6, "special": 0}
        g["opponents"]["Anna"]["tiles"] = {"cities": 2, "greeneries": 1}
        g["opponents"]["Anna"]["resources"]["mc"] = 120
        g["opponents"]["Felix"]["tiles"] = {"cities": 1, "greeneries": 0}
        g["opponents"]["Felix"]["resources"]["mc"] = 0
        self.save(g)
        rich = menu.award_lock(self.game(), "Landlord", self.setup())
        self.assertFalse(rich["lockable"], rich["why"])
        self.assertIn("Anna", rich["why"])

        g = self.game()
        g["opponents"]["Anna"]["resources"]["mc"] = 0
        self.save(g)
        broke = menu.award_lock(self.game(), "Landlord", self.setup())
        self.assertTrue(broke["lockable"], broke["why"])

    def test_why_prices_the_horizon_and_the_bank(self):
        """The printed reason must be explainable: whose reach, how many
        generations it is priced over, and the unspent M€ behind it."""
        g = self.banker_state(3, my_prod=5, opp_prod=2, opp_cash=80)
        why = menu.award_lock(g, "Banker", self.setup())["why"]
        self.assertRegex(why, r"reachable \+\d+")
        self.assertIn("gen", why)
        self.assertIn("80 MC unspent", why)


# ── L2: 8+ plants carried across an opponent's turn ──────────────────────

class TestPlantHoardWarning(Base):
    def items(self, plants: int, plant_prod: int = 0, corp: str | None = None,
              free_land: int | None = None) -> list[dict]:
        g = self.game()
        g["me"]["resources"]["plants"] = plants
        g["me"]["production"]["plants"] = plant_prod
        if corp:
            g["me"]["corporation"] = corp
        self.save(g)
        return menu.available_actions(self.game(), self.setup(),
                                      free_land=free_land)

    @staticmethod
    def warnings(items: list[dict]) -> list[dict]:
        return [i for i in items if i["kind"] == "warning"]

    def test_nine_plants_with_conversion_available_warns(self):
        """Observed: generation 3 ended holding 9 plants; an opponent's
        Deimos Down removed 8 (~19 M€ of greenery value)."""
        items = self.items(9)
        warns = self.warnings(items)
        self.assertEqual(len(warns), 1, [i["label"] for i in items])
        text = (warns[0]["label"] + " " + warns[0]["detail"]).lower()
        self.assertIn("plants", text)
        self.assertIn("convert", text)
        self.assertIn("greenery", text)
        self.assertIn("odds.py", text)

    def test_three_plants_no_warning(self):
        self.assertEqual(self.warnings(self.items(3)), [])

    def test_eight_plants_with_no_free_land_no_false_warning(self):
        """No legal greenery hex → the conversion is not available and the
        warning must not fire (nothing the player could do about it)."""
        items = self.items(8, free_land=0)
        self.assertEqual([i for i in items if i["kind"] == "convert"
                          and i["name"] == "plants"], [])
        self.assertEqual(self.warnings(items), [])

    def test_seven_plants_at_two_plant_production_warns_when_convertible(self):
        """KB 02: 'never carry 8+ plants (7 at 2+ plant prod)' — Ecoline
        converts at 7, so 7 plants with 2 plant production is exposed."""
        self.assertEqual(len(self.warnings(
            self.items(7, plant_prod=2, corp="Ecoline"))), 1)
        self.assertEqual(self.warnings(
            self.items(7, plant_prod=0, corp="Ecoline")), [])

    def test_warning_shows_in_the_menu_block_and_the_go_line(self):
        items = self.items(9)
        g = self.game()
        block = menu.render(items, g)
        self.assertIn("⚠", block)
        self.assertIn("9 plants", block)
        line = menu.summary(items)
        self.assertTrue(line.startswith("available: "))
        self.assertIn("plants", line)

    def test_pass_gate_carries_the_warning(self):
        """planlib.gate_split() must surface it unchanged — the pass gate
        is the last place the hoard can be caught."""
        self.items(9)
        gate, advisory = planlib.gate_split(self.store)
        self.assertTrue(any("plants" in line for line in gate + advisory),
                        (gate, advisory))
        self.assertTrue(any("exposed" in line for line in advisory), advisory)


if __name__ == "__main__":
    unittest.main()
