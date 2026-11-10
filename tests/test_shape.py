"""W1-B item 1: scripts/shape.py — deterministic position-shape metrics.

The reference failure is games/2026-08-29-game5: Zed bought cards per
generation [gen2: 1, gens 3-9: 0], finished MC production 5 vs table max
18, and the plan was tiles+milestones with no repeatable VP/TR source
after gen 3. The acceptance fixture below reproduces that position at
generation 5 and every applicable flag must trip THERE — while the game
was still winnable — not at the postmortem.

Flags are FACTS + evidence, never recommendations (fix-plan DOCTRINE).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine  # noqa: E402
import shape  # noqa: E402

SETUP5 = {
    "playerCount": 5,
    "players": [
        {"name": "Zed", "color": "red", "isMe": True, "aliases": []},
        {"name": "Ben", "color": "green", "isMe": False, "aliases": []},
        {"name": "Carl", "color": "blue", "isMe": False, "aliases": []},
        {"name": "Anna", "color": "yellow", "isMe": False, "aliases": []},
        {"name": "Diana", "color": "black", "isMe": False, "aliases": []},
    ],
    "expansions": ["base", "corporateEra"],
    "map": "tharsis",
    "draft": False,
    "houseRules": [],
    "seatingOrder": ["Zed", "Ben", "Carl", "Anna", "Diana"],
    "firstPlayerGen1": "Zed",
}


def _game5_fixture(store: Store) -> None:
    """Game5's shape at the START of generation 5, from real engine events
    where the format matters (research lines are parsed from log.md)."""
    eng = Engine(store)
    eng.corp("Zed", "CrediCor", mc=57)
    # G1: initial research, 2 kept; every opponent keeps some.
    eng.dealt(["Comet", "Birds", "Insects", "Moss"], kept=["Comet", "Birds"])
    eng.research("Ben", kept=3)
    eng.research("Carl", kept=3)
    eng.research("Anna", kept=5)
    eng.research("Diana", kept=5)
    g = store.load_game()
    g["generation"] = 2
    store.save_game(g)
    # G2: the ONE project card bought all game.
    eng.dealt(["Sponsors", "Worms", "Fish", "Algae"], kept=["Sponsors"])
    eng.research("Ben", kept=1)
    eng.research("Carl", kept=2)
    eng.research("Anna", kept=2)
    eng.research("Diana", kept=1)
    g = store.load_game()
    g["generation"] = 3
    store.save_game(g)
    # G3: zero kept (first zero — legal).
    eng.dealt(["Heather", "Bushes", "Grass", "Trees"], kept=[])
    eng.research("Ben", kept=2)
    eng.research("Carl", kept=1)
    eng.research("Anna", kept=2)
    eng.research("Diana", kept=2)
    g = store.load_game()
    g["generation"] = 4
    store.save_game(g)
    # G4: zero kept AGAIN (the apply.py gate needs an override for this —
    # the fixture reproduces exactly what game5 did).
    eng.dealt(["Mine", "Cartel", "Zeppelins", "Windmills"], kept=[],
              override="fixture: reproducing game5's buy pattern")
    eng.research("Ben", kept=2)
    eng.research("Carl", kept=2)
    eng.research("Anna", kept=3)
    eng.research("Diana", kept=2)
    g = store.load_game()
    g["generation"] = 5
    # mid-game globals, no history: clock's fit gives end ~gen 8, range
    # top 9 → 4 generations left on the long clock at gen 5.
    g["globals"] = {"temperature": -24, "oxygen": 5, "oceans": 5}
    me = g["me"]
    me["production"] = {"mc": 3, "steel": 0, "titanium": 0, "plants": 0,
                       "energy": 0, "heat": 0}
    me["hand"] = []
    # game5's actual tableau by gen 5: automated/event cards only — no
    # blue action, no plant/heat production, i.e. no repeatable source.
    me["playedCards"] = [
        {"name": "Invention Contest", "gen": 1},
        {"name": "Towing A Comet", "gen": 1},
        {"name": "Imported GHG", "gen": 1},
        {"name": "Phobos Space Haven", "gen": 2},
        {"name": "Ganymede Colony", "gen": 3},
        {"name": "Satellites", "gen": 3},
    ]
    for name, mcprod in (("Ben", 4), ("Carl", 6), ("Anna", 8),
                         ("Diana", 5)):
        g["opponents"][name]["production"]["mc"] = mcprod
    store.save_game(g)


class Game5Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP5)
        _game5_fixture(self.store)

    def tearDown(self):
        self.tmp.cleanup()


class TestGame5Acceptance(Game5Fixture):
    """The acceptance test from the plan: on game5's shape at generation 5
    every applicable flag must trip."""

    def test_cards_bought_flag_trips_on_two_consecutive_zero_gens(self):
        m = shape.compute(self.store)
        self.assertTrue(m["flags"]["cardsBought"])
        self.assertIn("gen 3", m["flags"]["cardsBought"])
        self.assertIn("gen 4", m["flags"]["cardsBought"])

    def test_mc_prod_flag_trips_below_table_median_after_gen4(self):
        m = shape.compute(self.store)
        self.assertEqual(m["mcProd"]["mine"], 3)
        self.assertEqual(m["mcProd"]["tableMedian"], 5)
        self.assertTrue(m["flags"]["mcProd"])
        self.assertIn("3", m["flags"]["mcProd"])
        self.assertIn("5", m["flags"]["mcProd"])

    def test_sources_flag_trips_with_zero_repeatables_and_3plus_gens(self):
        m = shape.compute(self.store)
        self.assertEqual(m["repeatableSources"], [])
        self.assertTrue(m["flags"]["sources"])

    def test_all_applicable_flags_trip_at_gen5(self):
        m = shape.compute(self.store)
        for name in ("cardsBought", "mcProd", "sources"):
            self.assertTrue(m["flags"][name], name)

    def test_render_marks_flag_lines(self):
        out = shape.render(shape.compute(self.store))
        flagged = [ln for ln in out.splitlines() if "FLAG" in ln]
        self.assertGreaterEqual(len(flagged), 3, out)

    def test_render_carries_no_strategy_advice(self):
        out = shape.render(shape.compute(self.store)).lower()
        for verb in ("should", "recommend", "consider", "buy more",
                     "pivot", "must play"):
            self.assertNotIn(verb, out)


class TestCardsBought(Game5Fixture):
    def test_my_per_generation_counts_from_log(self):
        m = shape.compute(self.store)
        self.assertEqual(m["cardsBought"]["mine"],
                         {1: 2, 2: 1, 3: 0, 4: 0})

    def test_opponent_counts_and_field_median(self):
        m = shape.compute(self.store)
        self.assertEqual(m["cardsBought"]["opponents"]["Anna"][2], 2)
        # G4 field: Ben 2, Carl 2, Anna 3, Diana 2 → median 2
        self.assertEqual(m["cardsBought"]["fieldMedian"][4], 2)

    def test_no_flag_when_last_generation_bought(self):
        eng = Engine(self.store)
        eng.dealt(["Sabotage", "Hackers", "Virus", "Flooding"],
                  kept=["Sabotage"])
        m = shape.compute(self.store)
        self.assertFalse(m["flags"]["cardsBought"])


class TestMCProd(Game5Fixture):
    def test_no_flag_before_gen5(self):
        g = self.store.load_game()
        g["generation"] = 4
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertFalse(m["flags"]["mcProd"])

    def test_no_flag_at_or_above_median(self):
        g = self.store.load_game()
        g["me"]["production"]["mc"] = 9
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertFalse(m["flags"]["mcProd"])


class TestVPSlope(Game5Fixture):
    def test_degrades_to_insufficient_data_without_standings(self):
        m = shape.compute(self.store)
        self.assertIsNone(m["vpSlope"])
        self.assertIn("insufficient data", shape.render(m))

    def test_slope_from_standings_lines(self):
        for gen, mine, anna in ((2, 24, 25), (3, 26, 30), (4, 27, 36)):
            self.store.log(f"G{gen}",
                           f"Standings (full): Anna {anna} (TR {anna}) · "
                           f"Zed {mine} (TR {mine}) · Ben 20 (TR 20) · "
                           f"Carl 20 (TR 20) · Diana 20 (TR 20)")
        m = shape.compute(self.store)
        self.assertIsNotNone(m["vpSlope"])
        self.assertEqual(m["vpSlope"]["mine"], 3)       # 24 → 27
        self.assertEqual(m["vpSlope"]["fieldMax"], 11)  # Anna 25 → 36
        self.assertNotIn("insufficient data", shape.render(m))

    def test_single_standings_line_is_still_insufficient(self):
        self.store.log("G4", "Standings (full): Zed 27 (TR 27) · "
                             "Anna 36 (TR 36)")
        m = shape.compute(self.store)
        self.assertIsNone(m["vpSlope"])


class TestRepeatableSources(Game5Fixture):
    def test_plant_production_is_a_source(self):
        g = self.store.load_game()
        g["me"]["production"]["plants"] = 2
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertTrue(any("plant" in s.lower()
                            for s in m["repeatableSources"]))
        self.assertFalse(m["flags"]["sources"])

    def test_heat_production_counts_only_while_temperature_unmaxed(self):
        g = self.store.load_game()
        g["me"]["production"]["heat"] = 3
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertTrue(any("heat" in s.lower()
                            for s in m["repeatableSources"]))
        g["globals"]["temperature"] = 8            # maxed
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertFalse(any("heat" in s.lower()
                             for s in m["repeatableSources"]))

    def test_blue_tr_action_is_a_source(self):
        g = self.store.load_game()
        g["me"]["playedCards"].append(
            {"name": "Nitrite Reducing Bacteria", "gen": 4})
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertTrue(any("Nitrite Reducing Bacteria" in s
                            for s in m["repeatableSources"]))
        self.assertFalse(m["flags"]["sources"])

    def test_blue_vp_action_is_a_source(self):
        g = self.store.load_game()
        g["me"]["playedCards"].append({"name": "Birds", "gen": 4})
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertTrue(any("Birds" in s for s in m["repeatableSources"]))

    def test_no_sources_flag_needs_3plus_gens_left(self):
        g = self.store.load_game()
        g["declaredFinalGeneration"] = 5          # 0 gens left
        self.store.save_game(g)
        m = shape.compute(self.store)
        self.assertFalse(m["flags"]["sources"])


class TestRobustness(unittest.TestCase):
    def test_compute_survives_missing_log(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            store.init(SETUP5)
            (Path(d) / "state" / "log.md").unlink()
            m = shape.compute(store)              # must not crash
            self.assertEqual(m["cardsBought"]["mine"], {})

    def test_cli_prints_the_block(self):
        import subprocess
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            store.init(SETUP5)
            _game5_fixture(store)
            r = subprocess.run(
                [sys.executable, str(scripts / "shape.py"), "--root", d],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("FLAG", r.stdout)
            self.assertIn("cards bought", r.stdout.lower())

    def test_compute_returns_json_serialisable_dict(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            store.init(SETUP5)
            _game5_fixture(store)
            m = shape.compute(store)
            json.dumps(m)                          # importable-as-function contract
            for key in ("cardsBought", "mcProd", "vpSlope",
                        "repeatableSources", "flags"):
                self.assertIn(key, m)


if __name__ == "__main__":
    unittest.main()
