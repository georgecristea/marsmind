"""Maxed global parameters must be priced at zero (D5).

From the blind 2p game: the opposing seat's acquisition evaluator tagged
Imported Hydrogen KEEP for its ocean AFTER the ocean track was already full.
The advisor overrode it by hand, but the tool was wrong, and it is wrong
exactly in the endgame research where cards are scarcest and a wasted keep
costs 3 MC plus the slot.

A global step or ocean with no room left on its track is worth nothing. Any
other effect on the same card still counts normally.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import research


def _ev(card, globals_):
    return {"name": card["name"], "windowInfo": {"status": "open"},
            "globals": globals_}


OPEN = {"temperature": -20, "oxygen": 4, "oceans": 3}
MAXED = {"temperature": 8, "oxygen": 14, "oceans": 9}


class TestMaxedGlobalsArePricedAtZero(unittest.TestCase):

    OCEAN_CARD = {"name": "Ice Asteroid", "cost": 23, "behavior": {"ocean": {"count": 2}}}
    TEMP_CARD = {"name": "Asteroid", "cost": 14,
                 "behavior": {"global": {"temperature": 1}}}
    MIXED = {"name": "Big Asteroid", "cost": 27,
             "behavior": {"global": {"temperature": 2},
                          "stock": {"titanium": 4}}}

    def test_oceans_are_worth_full_price_while_the_track_has_room(self):
        v, parts, _ = research._machine_value(self.OCEAN_CARD,
                                              _ev(self.OCEAN_CARD, OPEN), 6)
        self.assertEqual(v, research.PRICE["oceans"] * 2)
        self.assertIn("ocean ×2", parts)

    def test_oceans_are_worth_nothing_once_the_track_is_full(self):
        v, parts, _ = research._machine_value(self.OCEAN_CARD,
                                              _ev(self.OCEAN_CARD, MAXED), 6)
        self.assertEqual(v, 0, "a full ocean track makes the ocean worthless")
        self.assertTrue(any("maxed" in p for p in parts), parts)

    def test_temperature_step_is_worth_nothing_at_max(self):
        v, _, _ = research._machine_value(self.TEMP_CARD,
                                          _ev(self.TEMP_CARD, MAXED), 4)
        self.assertEqual(v, 0)

    def test_other_effects_on_the_same_card_still_count(self):
        v, parts, modeled = research._machine_value(self.MIXED,
                                                    _ev(self.MIXED, MAXED), 4)
        self.assertEqual(v, research.WINDFALL["titanium"] * 4,
                         "the titanium is still worth having")
        self.assertTrue(modeled)

    def test_missing_globals_falls_back_to_full_price(self):
        """Callers that do not supply globals keep today's behaviour."""
        e = {"name": "Ice Asteroid", "windowInfo": {"status": "open"}}
        v, _, _ = research._machine_value(self.OCEAN_CARD, e, 6)
        self.assertEqual(v, research.PRICE["oceans"] * 2)

    def test_evaluate_attaches_globals_to_every_evaluation(self):
        game = {"globals": dict(MAXED), "me": {"name": "Carl",
                "resources": {"mc": 40, "steel": 0, "titanium": 0,
                              "plants": 0, "energy": 0, "heat": 0},
                "production": {"mc": 5, "steel": 0, "titanium": 0,
                               "plants": 0, "energy": 0, "heat": 0},
                "playedCards": [], "hand": [], "tiles": {}},
                "opponents": {}, "generation": 12,
                "board": [], "milestonesClaimed": {}, "awardsFunded": {}}
        out = research.evaluate(game, ["Ice Asteroid"])
        self.assertEqual(out[0].get("globals"), MAXED)


if __name__ == "__main__":
    unittest.main()
