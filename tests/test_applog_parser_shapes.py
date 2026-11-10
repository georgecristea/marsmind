"""Generic-parser blind spots the replay gate reported as `unknown`.

Every line below is REAL text, copied from
`scripts/replay_gate.py --all`'s own "unknown L… ?:" report over the
practice games rebuilt from the vendor database (private/games/…):

    Ana revealed and discarded Ice Asteroid
    Ana is using their Mars University effect to draw a card by discarding a card.
    Ana discarded Arctic Algae
    Ana found life!
    Ben placed land claim at 21

Three of the four shapes carry NO state change — they are card flow (a
reveal, a discard, an effect announcement) or flavour ("found life!"
announces a card resource the line itself never numbers). They must parse
into NEUTRAL feed kinds so the replayer absorbs them as consequences of
the head that caused them, instead of pushing an `unknown` head that
orphans every consequence line behind it.

The fourth, a land claim, IS a board fact: a marker that makes the hex
illegal for every OTHER player while staying legal for its owner, and
that is not a tile of any kind. The parser side is here; the engine side
is pinned by `TestLandClaimMarkerNeedsTmlib` below.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import applog_parser as P                              # noqa: E402

PLAYERS = ["Ana", "Ben", "Hector", "Diana"]


class TestNeutralCardFlowShapes(unittest.TestCase):
    def test_revealed_and_discarded_is_neutral_card_flow(self):
        ev = P.parse_line("Ana revealed and discarded Ice Asteroid", PLAYERS)
        self.assertEqual(ev, {"kind": "card_flow", "player": "Ana",
                              "verb": "reveal_discard", "card": "Ice Asteroid"})

    def test_revealed_and_discarded_multiword_card(self):
        ev = P.parse_line("Hector revealed and discarded Water Import From Europa",
                          PLAYERS)
        self.assertEqual(ev["card"], "Water Import From Europa")
        self.assertEqual(ev["kind"], "card_flow")

    def test_using_their_card_effect_is_neutral_card_flow(self):
        ev = P.parse_line(
            "Ana is using their Mars University effect to draw a card by "
            "discarding a card.", PLAYERS)
        self.assertEqual(ev["kind"], "card_flow")
        self.assertEqual(ev["player"], "Ana")
        self.assertEqual(ev["verb"], "use_effect")
        self.assertEqual(ev["card"], "Mars University")

    def test_discarded_is_neutral_card_flow(self):
        ev = P.parse_line("Ana discarded Arctic Algae", PLAYERS)
        self.assertEqual(ev, {"kind": "card_flow", "player": "Ana",
                              "verb": "discard", "card": "Arctic Algae"})

    def test_found_life_is_a_neutral_note(self):
        ev = P.parse_line("Ana found life!", PLAYERS)
        self.assertEqual(ev["kind"], "note")
        self.assertEqual(ev["player"], "Ana")
        self.assertIn("found life", ev["text"])

    def test_a_gain_line_that_numbers_its_resource_still_wins(self):
        """"…if the line itself says the resource gain it is already
        handled" — the neutral note must never shadow a real card-resource
        line."""
        ev = P.parse_line("Ana added 1 Science to Search For Life", PLAYERS)
        self.assertEqual(ev["kind"], "card_resource")
        self.assertEqual(ev["verb"], "add")
        self.assertEqual(ev["n"], 1)

    def test_none_of_the_blind_spot_lines_stay_unknown(self):
        lines = [
            "Ana revealed and discarded Ice Asteroid",
            "Ana revealed and discarded Black Polar Dust",
            "Ana revealed and discarded Extreme-Cold Fungus",
            "Hector revealed and discarded Caretaker Contract",
            "Ana is using their Mars University effect to draw a card by "
            "discarding a card.",
            "Ana discarded Convoy From Europa",
            "Ana discarded Robotic Workforce",
            "Ana found life!",
            "Hector found life!",
            "Ben placed land claim at 21",
            "Ana placed land claim at 16",
            "Diana placed land claim at 21",
        ]
        for line in lines:
            with self.subTest(line=line):
                self.assertNotEqual(P.parse_line(line, PLAYERS)["kind"], "unknown")

    def test_existing_shapes_are_not_shadowed(self):
        """The new rules must not eat lines the parser already reads."""
        cases = [
            ("Ben placed greenery tile at 21", "placed"),
            ("Ana played Mars University", "played"),
            ("Ana used Search For Life action", "used_action"),
            ("Ana removed 1 resource(s) from Search For Life", "card_resource"),
            ("Ana gained 3 M€", "gained"),
        ]
        for line, kind in cases:
            with self.subTest(line=line):
                self.assertEqual(P.parse_line(line, PLAYERS)["kind"], kind)


class TestLandClaimParsing(unittest.TestCase):
    def test_land_claim_carries_player_and_space(self):
        ev = P.parse_line("Ben placed land claim at 21", PLAYERS)
        self.assertEqual(ev, {"kind": "land_claim", "player": "Ben",
                              "space": "21"})

    def test_land_claim_is_not_a_tile_placement(self):
        """It must never reach the `placed` path — a land claim is not a
        tile and would show up as an extra tile on the board."""
        ev = P.parse_line("Diana placed land claim at 21", PLAYERS)
        self.assertNotEqual(ev["kind"], "placed")
        self.assertNotIn("tile", ev)


class TestBlockGrouping(unittest.TestCase):
    """The real reason these shapes matter: an `unknown` head ORPHANS every
    consequence line behind it, so the block that caused them loses its
    tail. Grouped as consequences, the tail stays with its head."""

    def _blocks(self, text):
        return P.group_blocks(P.parse_log(text, PLAYERS))

    def test_search_for_life_keeps_its_consequences(self):
        blocks = self._blocks(
            "Ana used Search For Life action\n"
            "Ana revealed and discarded Decomposers\n"
            "Ana found life!\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["head"]["kind"], "used_action")
        self.assertEqual([e["kind"] for e in blocks[0]["tail"]],
                         ["card_flow", "note"])

    def test_mars_university_discard_keeps_the_draw_with_its_head(self):
        blocks = self._blocks(
            "Ana played Mars University\n"
            "Ana is using their Mars University effect to draw a card by "
            "discarding a card.\n"
            "Ana discarded Arctic Algae\n"
            "Ana drew 1 card(s)\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["head"]["kind"], "played")
        self.assertEqual([e["kind"] for e in blocks[0]["tail"]],
                         ["card_flow", "card_flow", "drew"])

    def test_land_claim_stays_with_the_card_that_placed_it(self):
        blocks = self._blocks(
            "Ben played Land Claim\n"
            "Ben placed land claim at 21\n"
            "Ben gained 3 M€\n")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["head"]["kind"], "played")
        self.assertEqual([e["kind"] for e in blocks[0]["tail"]],
                         ["land_claim", "gained"])

    def test_no_unknown_blocks_for_these_shapes(self):
        blocks = self._blocks(
            "Ana played Land Claim\n"
            "Ana placed land claim at 16\n"
            "Ana used Search For Life action\n"
            "Ana revealed and discarded Symbiotic Fungus\n"
            "Ana found life!\n")
        self.assertEqual([b for b in blocks if b["head"]["kind"] == "unknown"], [])


LAND_CLAIM_TILE = "landclaim"   # tmlib.LAND_CLAIM

SETUP = {"playerCount": 2, "gameMode": "app-practice",
         "players": [{"name": "Hector", "color": "blue", "isMe": True},
                     {"name": "Ben", "color": "red", "isMe": False}],
         "expansions": ["base"], "map": "tharsis", "draft": False,
         "houseRules": [], "seatingOrder": ["Hector", "Ben"],
         "firstPlayerGen1": "Hector"}


def _engine_with_marker(tmp, space="21", owner="Ben"):
    """A fresh session whose board carries one land-claim marker."""
    import json
    from tmlib import Engine, Store

    store = Store(Path(tmp))
    store.init(json.loads(json.dumps(SETUP)))
    eng = Engine(store)
    game = store.load_game()
    game.setdefault("board", {})[space] = {"tile": LAND_CLAIM_TILE,
                                           "player": owner}
    store.save_game(game)
    return eng, store


class TestLandClaimMarkerOnTheBoard(unittest.TestCase):
    """The board-side half of the land-claim requirement.

    What already holds today is asserted normally. What does NOT hold is
    marked `expectedFailure` with the exact one-function change needed —
    scripts/tmlib.py and scripts/verify.py were owned by other changes in
    this pass and were deliberately not touched.
    """

    def test_the_marker_blocks_every_other_player(self):
        """Already true: `place()` refuses an occupied hex and
        `legal_spaces()` skips it — which is the whole "blocks OTHER
        players' tiles" rule."""
        import tempfile
        from tmlib import EventError

        with tempfile.TemporaryDirectory() as tmp:
            eng, _ = _engine_with_marker(tmp)
            with self.assertRaises(EventError):
                eng.place("Hector", "city", "21")
            self.assertNotIn("21", {m["id"] for m in eng.legal_spaces("city")})

    def test_the_marker_is_not_a_greenery_or_a_city(self):
        """Already true: score.py and verify.py count "greenery"/"city" by
        name, so a `land_claim` scores nothing and is no city for
        adjacency."""
        import sys as _sys
        import tempfile
        _sys.path.insert(0, str(ROOT / "scripts"))
        import verify                                    # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            _, store = _engine_with_marker(tmp)
            counts = verify.board_counts(store.load_game(), "Ben")
            self.assertEqual(counts["greeneries"], 0)
            self.assertEqual(counts["cities"], 0)

    def test_owner_may_place_on_their_own_land_claim(self):
        """`Engine.place` lets the marker's OWNER through, replacing it —
        everyone else still meets the occupied-space refusal."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            eng, store = _engine_with_marker(tmp)
            eng.place("Ben", "city", "21")
            self.assertEqual(store.load_game()["board"]["21"]["tile"], "city")

    def test_the_marker_is_not_a_special_tile(self):
        """A land-claim marker is not a scored special tile: it would
        report false tile drift and, after `verify.py --sync`, inflate
        Landlord."""
        import sys as _sys
        import tempfile
        _sys.path.insert(0, str(ROOT / "scripts"))
        import verify                                    # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            _, store = _engine_with_marker(tmp)
            self.assertEqual(
                verify.board_counts(store.load_game(), "Ben")["special"], 0)


if __name__ == "__main__":
    unittest.main()
