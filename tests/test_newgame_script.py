"""newgame.py — create a game on the local app; payload builder is pure."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import newgame


class TestPayload(unittest.TestCase):
    def test_players_parsed_first_flag_and_colors(self):
        p = newgame.payload("Zed=red,Ana=green,Ben=yellow")
        names = [(x["name"], x["color"], x["first"]) for x in p["players"]]
        self.assertEqual(names, [("Zed", "red", True),
                                 ("Ana", "green", False),
                                 ("Ben", "yellow", False)])

    def test_base_corpera_defaults_and_no_cloned_key(self):
        p = newgame.payload("A=red,B=green")
        self.assertTrue(p["expansions"]["corpera"])
        self.assertFalse(any(v for k, v in p["expansions"].items()
                             if k != "corpera"))
        self.assertEqual(p["board"], "tharsis")
        self.assertFalse(p["draftVariant"])
        # the server 500s on clonedGamedId: null — key must be ABSENT
        self.assertNotIn("clonedGamedId", p)


    def test_wgt_is_the_default(self):
        # World Government Terraforming is the vendor's solarPhaseOption
        # (id="WGT-checkbox" in CreateGameForm.vue). WGT is the house
        # default for every game — practice and table.
        p = newgame.payload("A=red,B=green")
        self.assertTrue(p["solarPhaseOption"])

    def test_wgt_can_be_turned_off(self):
        p = newgame.payload("A=red,B=green", wgt=False)
        self.assertFalse(p["solarPhaseOption"])

    def test_bad_spec_rejected(self):
        with self.assertRaises(ValueError):
            newgame.payload("Zedred")
        with self.assertRaises(ValueError):
            newgame.payload("OnlyOne=red")


if __name__ == "__main__":
    unittest.main()
