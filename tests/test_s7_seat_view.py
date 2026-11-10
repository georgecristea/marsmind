"""S7 — `sparring.py state|wait` print a real decision view (speed-plan 3.2).

Before: `gen N | <menu shape>` plus `mat: N MC, N steel, N heat, TR N` —
no plants, titanium, energy, production, globals, milestone/award state or
opponents. A seat needing any of those left its tool for a raw `curl` and
reasoned over the whole JSON: one extra model round-trip and a large token
cost per turn. Contract under test: from the SAME player dict the function
already fetched, print own resources AND production (all six), TR, the
global parameters, the menu shape, milestone/award slots (claimed/funded by
whom), and ONE public row per opponent. PUBLIC data only — nothing from any
hand. The first line's format is unchanged (`gen N | …`); `state` inherits
the view (same function).
"""
import io
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sparring                                 # noqa: E402

MENU = {"type": "or", "title": "Take action for action phase",
        "options": [{"title": "Play project card", "type": "projectCard"},
                    {"title": "Pass for this generation", "type": "option"}]}

HAND = [{"name": "Secret Hand Card One"}, {"name": "Secret Hand Card Two"}]


def _row(name, color, mc, tr, cities, tableau, **over):
    r = {"name": name, "color": color, "megacredits": mc, "steel": 1,
         "titanium": 0, "plants": 4, "energy": 0, "heat": 7,
         "terraformRating": tr, "megacreditProduction": 5,
         "steelProduction": 1, "titaniumProduction": 0, "plantProduction": 2,
         "energyProduction": 1, "heatProduction": 1, "citiesCount": cities,
         "cardsInHandNbr": 6,
         "tableau": [{"name": f"{name} Corp", "resources": 0}]
                    + [{"name": f"{name} card {i}", "resources": 0}
                       for i in range(tableau)]}
    r.update(over)
    return r


def _spaces():
    """A public board: greenery tiles (TileType 0) per colour, one city (2)."""
    return [{"id": "10", "spaceType": "land", "tileType": 0, "color": "green"},
            {"id": "11", "spaceType": "land", "tileType": 0, "color": "green"},
            {"id": "12", "spaceType": "land", "tileType": 0, "color": "green"},
            {"id": "13", "spaceType": "land", "tileType": 2, "color": "green"},
            {"id": "14", "spaceType": "land", "tileType": 0, "color": "red"},
            {"id": "15", "spaceType": "ocean", "tileType": 1, "color": None},
            {"id": "16", "spaceType": "colony", "tileType": 2, "color": "yellow"},
            {"id": "17", "spaceType": "land", "tileType": None}]


def view(wf=MENU, gen=10):
    me = _row("Anna", "red", mc=24, tr=30, cities=1, tableau=4,
              steel=3, titanium=2, plants=5, energy=1, heat=9,
              megacreditProduction=8, steelProduction=1,
              titaniumProduction=2, plantProduction=1, energyProduction=3,
              heatProduction=4, cardsInHandNbr=2)
    return {"thisPlayer": me,
            "cardsInHand": HAND,
            "players": [me,
                        _row("Zed", "green", mc=41, tr=33, cities=1, tableau=9),
                        _row("Ben", "yellow", mc=7, tr=25, cities=0, tableau=2)],
            "waitingFor": wf,
            "game": {"generation": gen, "phase": "action",
                     "temperature": -12, "oxygenLevel": 5, "oceans": 3,
                     "milestones": [
                         {"name": "Builder", "playerName": "Zed", "color": "green",
                          "scores": []},
                         {"name": "Mayor", "playerName": None, "color": None,
                          "scores": [{"color": "red", "score": 1}]},
                         {"name": "Gardener", "playerName": None,
                          "scores": []}],
                     "awards": [
                         {"name": "Landlord", "playerName": "Ben",
                          "color": "yellow", "scores": []},
                         {"name": "Banker", "playerName": None, "scores": []}],
                     "spaces": _spaces()}}


def describe(v=None):
    with mock.patch.object(sparring, "get_player", return_value=v or view()):
        return sparring.describe_waiting("p1")


class TestFirstLineUnchanged(unittest.TestCase):
    def test_first_line_is_gen_pipe_shape(self):
        out = describe()
        first = out.splitlines()[0]
        self.assertTrue(first.startswith("gen 10 | "), first)
        self.assertEqual(first, "gen 10 | " + sparring.shape(MENU).splitlines()[0])

    def test_menu_shape_lines_follow(self):
        out = describe()
        self.assertIn("[0] Play project card (type projectCard)", out)
        self.assertIn("[1] Pass for this generation (type option)", out)

    def test_not_waiting_is_still_the_bare_first_line(self):
        out = describe(view(wf=None))
        self.assertEqual(out, "gen 10 | NOT WAITING (opponent's move)")


class TestOwnMat(unittest.TestCase):
    def test_all_six_resources_present(self):
        out = describe()
        for token in ("24 MC", "3 steel", "2 titanium", "5 plants",
                      "1 energy", "9 heat"):
            self.assertIn(token, out, token)
        self.assertIn("TR 30", out)

    def test_all_six_production_values_present(self):
        out = describe()
        prod = next(l for l in out.splitlines() if "prod" in l.lower())
        for token in ("MC 8", "steel 1", "titanium 2", "plants 1",
                      "energy 3", "heat 4"):
            self.assertIn(token, prod, token)

    def test_hand_size_but_never_hand_contents(self):
        out = describe()
        self.assertNotIn("Secret Hand Card", out)
        self.assertIn("2 cards in hand", out)


class TestGlobals(unittest.TestCase):
    def test_temperature_oxygen_oceans(self):
        out = describe()
        g = next(l for l in out.splitlines() if l.startswith("globals"))
        self.assertIn("-12", g)
        self.assertIn("5", g)
        self.assertIn("3/9", g)
        for word in ("temperature", "oxygen", "oceans"):
            self.assertIn(word, g)


class TestMilestonesAndAwards(unittest.TestCase):
    def test_milestone_slots_name_the_taker_and_the_open_ones(self):
        out = describe()
        ms = next(l for l in out.splitlines() if l.startswith("milestones"))
        self.assertIn("1/3", ms)
        self.assertIn("Builder", ms)
        self.assertIn("Zed", ms)
        self.assertRegex(ms, r"Mayor[^·]*open")
        self.assertRegex(ms, r"Gardener[^·]*open")

    def test_award_slots_name_the_funder(self):
        out = describe()
        aw = next(l for l in out.splitlines() if l.startswith("awards"))
        self.assertIn("1/3", aw)
        self.assertIn("Landlord", aw)
        self.assertIn("Ben", aw)
        self.assertRegex(aw, r"Banker[^·]*open")

    def test_missing_blocks_do_not_break_the_view(self):
        v = view()
        del v["game"]["milestones"]
        del v["game"]["awards"]
        del v["game"]["spaces"]
        del v["game"]["temperature"]
        out = describe(v)
        self.assertTrue(out.startswith("gen 10 | "))
        self.assertIn("24 MC", out)


class TestOpponentRows(unittest.TestCase):
    def rows(self, out):
        return [l for l in out.splitlines() if l.startswith("opp ")]

    def test_one_row_per_opponent_and_none_for_me(self):
        rows = self.rows(describe())
        self.assertEqual(len(rows), 2)
        self.assertTrue(any("Zed" in r and "green" in r for r in rows), rows)
        self.assertTrue(any("Ben" in r and "yellow" in r for r in rows), rows)
        self.assertFalse(any("Anna" in r for r in rows), rows)

    def test_row_carries_tr_tiles_tableau_and_mc(self):
        zed = next(r for r in self.rows(describe()) if "Zed" in r)
        self.assertIn("TR 33", zed)
        self.assertIn("cities 1", zed)
        self.assertIn("greeneries 3", zed)        # counted from the public board
        self.assertIn("tableau 9", zed)           # slot 0 = corporation, excluded
        self.assertIn("41 MC", zed)
        ben = next(r for r in self.rows(describe()) if "Ben" in r)
        self.assertIn("cities 0", ben)
        self.assertIn("greeneries 0", ben)        # the colony space is off-Mars
        self.assertIn("tableau 2", ben)
        self.assertIn("7 MC", ben)

    def test_opponent_rows_carry_no_hand(self):
        out = describe()
        self.assertNotIn("Secret Hand Card", out)
        for r in self.rows(out):
            self.assertNotIn("card 0", r)        # no tableau names, a count

    def test_a_view_that_omits_mc_says_so_without_crashing(self):
        v = view()
        for p in v["players"]:
            if p["name"] == "Zed":
                del p["megacredits"]
        zed = next(r for r in self.rows(describe(v)) if "Zed" in r)
        self.assertIn("TR 33", zed)
        self.assertNotIn("None MC", zed)


class TestStateVerbInherits(unittest.TestCase):
    def test_state_prints_the_same_view(self):
        buf = io.StringIO()
        with mock.patch.object(sparring, "get_player", return_value=view()), \
             mock.patch("sys.argv", ["sparring.py", "state", "p1"]), \
             mock.patch("sys.stdout", buf):
            self.assertEqual(sparring.main(), 0)
        out = buf.getvalue()
        self.assertTrue(out.startswith("gen 10 | "))
        self.assertIn("globals", out)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("opp ")]), 2)
        self.assertNotIn("Secret Hand Card", out)


class TestNoCardSpecificBranch(unittest.TestCase):
    def test_source_has_no_card_literal_branches(self):
        src = Path(sparring.__file__).read_text()
        body = src[src.index("def describe_waiting"):]
        body = body[:body.index("\ndef ", 10)]
        self.assertNotRegex(body, r"==\s*['\"][A-Z][a-z]+ [A-Z]")


if __name__ == "__main__":
    unittest.main()
