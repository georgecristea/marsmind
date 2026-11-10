"""M1: fresh game.json creation from setup config."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import new_game_state

SETUP = {
    "playerCount": 3,
    "players": [
        {"name": "Zed", "color": "red", "isMe": True, "aliases": ["red"]},
        {"name": "Anna", "color": "green", "isMe": False, "aliases": ["ana"]},
        {"name": "Felix", "color": "blue", "isMe": False, "aliases": ["the blue guy"]},
    ],
    "expansions": ["base", "corporateEra"],
    "map": "tharsis",
    "draft": False,
    "houseRules": [],
    "seatingOrder": ["Zed", "Anna", "Felix"],
    "firstPlayerGen1": "Anna",
}


class TestNewGameState(unittest.TestCase):
    def setUp(self):
        self.g = new_game_state(SETUP)

    def test_generation_starts_at_1(self):
        self.assertEqual(self.g["generation"], 1)

    def test_globals_at_initial_values(self):
        self.assertEqual(self.g["globals"], {"temperature": -30, "oxygen": 0, "oceans": 0})

    def test_me_full_fidelity_starting_state(self):
        me = self.g["me"]
        self.assertEqual(me["name"], "Zed")
        self.assertEqual(me["tr"], 20)
        self.assertIsNone(me["corporation"])
        zeros = {"mc": 0, "steel": 0, "titanium": 0, "plants": 0, "energy": 0, "heat": 0}
        self.assertEqual(me["resources"], zeros)
        self.assertEqual(me["production"], zeros)
        self.assertEqual(me["hand"], [])          # ordered = recommended play order
        self.assertEqual(me["playedCards"], [])
        self.assertEqual(me["dealtLog"], [])
        self.assertEqual(me["actionsThisGen"], {})
        self.assertEqual(me["tiles"], {"cities": 0, "greeneries": 0, "special": 0})
        self.assertEqual(me["milestones"], [])

    def test_opponents_summary_schema(self):
        opps = self.g["opponents"]
        self.assertEqual(set(opps), {"Anna", "Felix"})
        anna = opps["Anna"]
        self.assertEqual(anna["tr"], 20)
        zeros = {"mc": 0, "steel": 0, "titanium": 0, "plants": 0, "energy": 0, "heat": 0}
        self.assertEqual(anna["resources"], zeros)
        self.assertEqual(anna["production"], zeros)
        self.assertTrue(anna["estimated"])
        self.assertIsNone(anna["lastObservedGen"])
        self.assertEqual(anna["tagCounts"], {})
        # `special` joined the opponent schema after P7: Landlord is
        # sum(tiles.values()), so a missing special counter silently
        # deflated every opponent's award metric (tests/test_p7_fixes.py)
        self.assertEqual(anna["tiles"],
                         {"cities": 0, "greeneries": 0, "special": 0})
        self.assertEqual(anna["playedCards"], [])
        self.assertIsNone(anna["corporation"])

    def test_first_player_tracked(self):
        self.assertEqual(self.g["firstPlayer"], "Anna")


if __name__ == "__main__":
    unittest.main()
