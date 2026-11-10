"""Board occupancy — tiles placed on named hexes, bonuses granted."""
import json, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP

BOARD = json.loads((Path(__file__).parent.parent / "board.json").read_text())
SPACES = {s["id"]: s for s in BOARD["spaces"]}
LAND = [s for s in BOARD["spaces"]
        if not s.get("offMap") and not s.get("oceanReserved")]
OCEANS = [s for s in BOARD["spaces"] if s.get("oceanReserved")]


def land_id(bonus_pred=lambda b: True, exclude=()):
    for s in LAND:
        if s["id"] not in exclude and bonus_pred(s.get("bonus", [])):
            return s["id"]
    raise AssertionError("no matching space")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()


class TestPlace(Base):
    def test_place_city_records_occupancy_and_grants_bonus(self):
        sid = land_id(lambda b: b == ["steel", "steel"])
        self.eng.place("Zed", "city", sid)
        g = self.game()
        self.assertEqual(g["board"][sid], {"tile": "city", "player": "Zed"})
        self.assertEqual(g["me"]["resources"]["steel"], 2)

    def test_place_on_occupied_rejected(self):
        sid = land_id()
        self.eng.place("Zed", "city", sid)
        with self.assertRaises(EventError):
            self.eng.place("Anna", "greenery", sid)

    def test_ocean_only_on_reserved(self):
        with self.assertRaises(EventError):
            self.eng.place("Zed", "ocean", land_id())
        self.eng.place("Zed", "ocean", OCEANS[0]["id"])
        self.assertEqual(self.game()["board"][OCEANS[0]["id"]]["tile"], "ocean")

    def test_non_ocean_not_on_reserved(self):
        with self.assertRaises(EventError):
            self.eng.place("Zed", "city", OCEANS[0]["id"])

    def test_ocean_space_special_tiles_allowed_on_reserved(self):
        # Mohole Area is placed ON AN AREA RESERVED FOR OCEAN (card 142)
        sid = next(s["id"] for s in OCEANS if s.get("bonus") == ["card", "card"])
        self.eng.place("Zed", "moholearea", sid)
        self.assertEqual(self.game()["board"][sid]["tile"], "moholearea")

    def test_unknown_space_rejected(self):
        with self.assertRaises(EventError):
            self.eng.place("Zed", "city", "99")

    def test_ocean_adjacency_pays_2mc_per_ocean(self):
        # find a land space adjacent to an ocean-reserved space
        osid = OCEANS[0]["id"]
        adj_land = next(a for a in SPACES[osid]["adjacent"]
                        if a in SPACES and not SPACES[a].get("oceanReserved")
                        and not SPACES[a].get("offMap"))
        self.eng.place("Anna", "ocean", osid)
        before = self.game()["me"]["resources"]["mc"]
        self.eng.place("Zed", "greenery", adj_land)
        gained = self.game()["me"]["resources"]["mc"] - before
        bonus_mc = 2  # one adjacent ocean
        self.assertEqual(gained, bonus_mc)

    def test_placement_does_not_touch_tile_counters(self):
        # counters move via play/convert/standard; place() only records position
        sid = land_id()
        self.eng.place("Zed", "greenery", sid)
        self.assertEqual(self.game()["me"]["tiles"]["greeneries"], 0)


class TestLegalMoves(Base):
    def test_legal_spaces_enumerates_bonuses(self):
        moves = self.eng.legal_spaces("greenery")
        self.assertEqual(len(moves), 49)  # 61 on-map − 12 ocean-reserved
        m = moves[0]
        self.assertIn("id", m); self.assertIn("bonus", m); self.assertIn("adjacentOceans", m)

    def test_legal_spaces_excludes_occupied_and_reserved(self):
        sid = land_id()
        self.eng.place("Zed", "city", sid)
        ids = [m["id"] for m in self.eng.legal_spaces("greenery")]
        self.assertNotIn(sid, ids)
        for o in OCEANS:
            self.assertNotIn(o["id"], ids)

    def test_city_vp_countable_from_occupancy(self):
        sid = land_id()
        adj = next(a for a in SPACES[sid]["adjacent"]
                   if a in SPACES and not SPACES[a].get("oceanReserved")
                   and not SPACES[a].get("offMap"))
        self.eng.place("Zed", "city", sid)
        self.eng.place("Zed", "greenery", adj)
        import score
        vp = score.city_adjacency_vp(self.game(), "Zed")
        self.assertEqual(vp, 1)


if __name__ == "__main__":
    unittest.main()


class TestOceanPlacementBonus(Base):
    def test_ocean_placer_gains_hex_bonus(self):
        # hex 28 is ocean-reserved with 2-plant bonus
        self.eng.place("Zed", "ocean", "28")
        self.assertEqual(self.game()["me"]["resources"]["plants"], 2)


class TestGreeneryAdjacency(Base):
    """Official rule: greenery must be adjacent to a tile you OWN if possible.
    Placed oceans are owned by NO ONE."""

    def test_greenery_must_touch_own_tile_when_possible(self):
        sid = land_id()
        self.eng.place("Zed", "greenery", sid)
        adj = set(SPACES[sid]["adjacent"])
        legal = [m["id"] for m in self.eng.legal_spaces("greenery", "Zed")]
        self.assertTrue(legal, "some legal hex must remain")
        for m in legal:
            self.assertIn(m, adj, f"{m} not adjacent to own tile {sid}")

    def test_greenery_adjacency_ignores_oceans(self):
        # Zed's own placed ocean must NOT count as an owned tile
        self.eng.place("Zed", "ocean", OCEANS[0]["id"])
        legal = [m["id"] for m in self.eng.legal_spaces("greenery", "Zed")]
        # unconstrained: all 49 land hexes stay legal (the ocean sits on a
        # reserved hex and grants no ownership adjacency)
        self.assertEqual(len(legal), 49)

    def test_place_rejects_non_adjacent_greenery(self):
        sid = land_id()
        self.eng.place("Zed", "greenery", sid)
        far = next(s["id"] for s in LAND
                   if s["id"] != sid and s["id"] not in SPACES[sid]["adjacent"])
        with self.assertRaises(EventError):
            self.eng.place("Zed", "greenery", far)


class TestUndoVerbs(Base):
    """A plan step applied for a card the player never bought needs
    script-level reversal (iron rule: no hand edits)."""

    def test_unplace_removes_board_entry(self):
        sid = land_id()
        self.eng.place("Zed", "city", sid)
        self.eng.unplace(sid)
        self.assertNotIn(sid, self.game()["board"])

    def test_unplace_empty_hex_rejected(self):
        with self.assertRaises(EventError):
            self.eng.unplace("99")

    def test_unplay_removes_from_played_cards_only(self):
        self.eng.hand_add(["Media Group"])
        self.eng.res("Zed", "mc", 6)
        self.eng.play("Zed", "Media Group", cost=6)
        self.eng.unplay("Zed", "Media Group")
        names = [c["name"] for c in self.game()["me"]["playedCards"]]
        self.assertNotIn("Media Group", names)

    def test_unplay_unknown_card_rejected(self):
        with self.assertRaises(EventError):
            self.eng.unplay("Zed", "Never Played")


class TestOpponentPlacementBonuses(Base):
    """place() granted hex bonuses, ocean-adjacency MC and the Mining
    Guild trigger ONLY to me — an opponent's tile placement is fully public
    and deterministic, so dropping it silently drifts their mat every time
    they build (Ben's mine on Pavonis Mons, plant + titanium bonus, left
    the tracker at 0/0)."""

    def test_opponent_gains_hex_bonus(self):
        sid = land_id(lambda b: b == ["plant", "titanium"])
        self.eng.place("Anna", "special", sid)
        opp = self.game()["opponents"]["Anna"]["resources"]
        self.assertEqual(opp["plants"], 1)
        self.assertEqual(opp["titanium"], 1)

    def test_opponent_gains_2mc_per_adjacent_ocean(self):
        ocean = OCEANS[0]
        neighbour = next(a for a in ocean["adjacent"]
                         if a in SPACES and not SPACES[a].get("oceanReserved")
                         and not SPACES[a].get("offMap"))
        self.eng.place("Anna", "ocean", ocean["id"])
        before = self.game()["opponents"]["Anna"]["resources"]["mc"]
        self.eng.place("Anna", "city", neighbour)
        after = self.game()["opponents"]["Anna"]["resources"]["mc"]
        self.assertEqual(after - before,
                         2 + 2 * sum(1 for b in SPACES[neighbour].get("bonus", [])
                                     if b == "mc"))

    def test_opponent_mining_guild_gains_steel_production(self):
        self.eng.corp("Anna", "Mining Guild", 30)
        sid = land_id(lambda b: "steel" in b)
        before = self.game()["opponents"]["Anna"]["production"]["steel"]
        self.eng.place("Anna", "city", sid)
        self.assertEqual(
            self.game()["opponents"]["Anna"]["production"]["steel"], before + 1)


class TestOceanReservedSpecialTiles(Base):
    """`place` exempted ocean-reserved hexes for a tile literally named
    'moholearea', but the CLI only accepts city|greenery|ocean|special — so
    the exemption was unreachable and Mohole Area, a base-game card, could
    not be recorded at all (Ben's play on hex 28 was rejected). The rule now comes from card data (`behavior.tile.on`),
    not from a hardcoded name the caller cannot express."""

    def _ocean_hex(self):
        return next(s["id"] for s in OCEANS if not s.get("offMap"))

    def test_mohole_area_places_on_ocean_reserved_hex(self):
        sid = self._ocean_hex()
        self.eng.place("Anna", "special", sid, card="Mohole Area")
        placed = self.game()["board"][sid]
        self.assertEqual(placed["player"], "Anna")
        self.assertEqual(placed["tile"], "moholearea")

    def test_ordinary_special_still_rejected_on_ocean_reserved_hex(self):
        with self.assertRaises(EventError):
            self.eng.place("Anna", "special", self._ocean_hex(),
                           card="Restricted Area")

    def test_special_without_card_still_rejected_on_ocean_reserved_hex(self):
        with self.assertRaises(EventError):
            self.eng.place("Anna", "special", self._ocean_hex())

    def test_ocean_reserved_special_still_grants_the_hex_bonus(self):
        sid = next(s["id"] for s in OCEANS
                   if not s.get("offMap") and "plant" in s.get("bonus", []))
        before = self.game()["opponents"]["Anna"]["resources"]["plants"]
        self.eng.place("Anna", "special", sid, card="Mohole Area")
        self.assertGreater(
            self.game()["opponents"]["Anna"]["resources"]["plants"], before)


class TestGreeneryOnOceanArea(Base):
    """The first fix read only `behavior.tile.on`, but a greenery
    placed on an ocean area is encoded as `behavior.greenery.on == "ocean"`
    (Protected Valley: 'Place a greenery tile ON AN AREA RESERVED FOR OCEAN,
    disregarding normal placement restrictions'). Ben's play on hex 07
    was still rejected — and that card ALSO waives
    the adjacent-to-your-own-tile rule, which the engine enforces separately."""

    def _ocean_hex(self):
        return next(s["id"] for s in OCEANS if not s.get("offMap"))

    def test_protected_valley_greenery_on_ocean_area(self):
        sid = self._ocean_hex()
        self.eng.place("Anna", "greenery", sid, card="Protected Valley")
        self.assertEqual(self.game()["board"][sid],
                         {"tile": "greenery", "player": "Anna"})

    def test_it_also_waives_the_adjacency_rule(self):
        """Anna owns a tile elsewhere, so the normal rule would force the
        greenery next to it; the card disregards that."""
        self.eng.place("Anna", "city", land_id())
        sid = self._ocean_hex()
        self.eng.place("Anna", "greenery", sid, card="Protected Valley")
        self.assertEqual(self.game()["board"][sid]["tile"], "greenery")

    def test_plain_greenery_still_cannot_take_an_ocean_area(self):
        with self.assertRaises(EventError):
            self.eng.place("Anna", "greenery", self._ocean_hex())


class TestFreeLand(Base):
    """Free land is a tracked scarcity: a game can end with dozens of
    unconverted plants on a board with ZERO free land because nothing
    surfaced it (tests/fixtures/endgame-5p/spaces_end.json)."""

    FIXTURE = Path(__file__).parent / "fixtures" / "endgame-5p" / "spaces_end.json"

    def test_full_final_board_has_no_free_land(self):
        import tmlib
        api_spaces = json.loads(self.FIXTURE.read_text())
        occupied = {s["id"] for s in api_spaces if s.get("tileType") is not None}
        self.assertEqual(len(occupied), 61)
        self.assertEqual(tmlib.free_land(occupied), 0)

    def test_fresh_board_counts_every_on_map_land_hex(self):
        import tmlib
        expected = sum(1 for s in BOARD["spaces"]
                       if s.get("type") == "land" and not s.get("offMap"))
        self.assertEqual(expected, 49)
        self.assertEqual(tmlib.occupied_space_ids(self.game()), set())
        self.assertEqual(tmlib.free_land(set()), expected)
        self.assertEqual(tmlib.free_land(set(), BOARD), expected)

    def test_placed_tiles_reduce_free_land_but_oceans_do_not(self):
        import tmlib
        sid = land_id()
        self.eng.place("Zed", "city", sid)
        g = self.game()
        self.assertEqual(tmlib.occupied_space_ids(g), {sid})
        self.assertEqual(tmlib.free_land(tmlib.occupied_space_ids(g)), 48)
        self.eng.place("Anna", "ocean", OCEANS[0]["id"])
        g = self.game()
        self.assertEqual(tmlib.free_land(tmlib.occupied_space_ids(g)), 48)
