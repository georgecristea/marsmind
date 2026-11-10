"""M2: Tharsis board database — spaces, bonuses, adjacency."""
import json, unittest
from pathlib import Path

BOARD_PATH = Path(__file__).resolve().parent.parent / "board.json"


class TestBoard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = json.loads(BOARD_PATH.read_text(encoding="utf-8"))
        cls.spaces = cls.board["spaces"]
        cls.by_id = {s["id"]: s for s in cls.spaces}
        cls.on_map = [s for s in cls.spaces if not s["offMap"]]
        cls.off_map = [s for s in cls.spaces if s["offMap"]]

    def test_is_tharsis(self):
        self.assertEqual(self.board["map"], "tharsis")

    def test_exactly_61_on_map_spaces(self):
        self.assertEqual(len(self.on_map), 61)

    def test_off_map_special_spaces(self):
        names = {s["name"] for s in self.off_map}
        self.assertEqual(names, {"Ganymede Colony", "Phobos Space Haven"})
        for s in self.off_map:
            self.assertTrue(s["offMap"])
            self.assertEqual(s["adjacent"], [])

    def test_row_structure(self):
        rows = [5, 6, 7, 8, 9, 8, 7, 6, 5]
        for y, count in enumerate(rows):
            self.assertEqual(sum(1 for s in self.on_map if s["y"] == y), count)

    def test_ocean_reserved_count_is_12(self):
        self.assertEqual(sum(1 for s in self.on_map if s["oceanReserved"]), 12)

    def test_adjacency_symmetric(self):
        for s in self.on_map:
            self.assertNotIn(s["id"], s["adjacent"])
            for other in s["adjacent"]:
                self.assertIn(s["id"], self.by_id[other]["adjacent"],
                              f"{s['id']} -> {other} not symmetric")

    def test_adjacency_degree_distribution(self):
        # Hex board of 61: 6 corners (3 neighbours), 18 edges (4), 37 interior (6).
        degrees = {}
        for s in self.on_map:
            degrees[len(s["adjacent"])] = degrees.get(len(s["adjacent"]), 0) + 1
        self.assertEqual(degrees, {3: 6, 4: 18, 6: 37})

    def test_noctis_city_space(self):
        noctis = self.by_id["31"]
        self.assertEqual(noctis["name"], "Noctis City")
        self.assertEqual(noctis["y"], 4)
        self.assertEqual(noctis["bonus"], ["plant", "plant"])
        self.assertIn("Noctis City", noctis["reservedFor"])

    def test_volcano_names(self):
        volcanoes = {s["name"]: s for s in self.on_map if s.get("volcanic")}
        self.assertEqual(set(volcanoes), {"Tharsis Tholus", "Ascraeus Mons",
                                          "Pavonis Mons", "Arsia Mons"})
        self.assertEqual(volcanoes["Tharsis Tholus"]["bonus"], ["steel"])
        self.assertEqual(volcanoes["Ascraeus Mons"]["bonus"], ["card"])
        self.assertEqual(volcanoes["Pavonis Mons"]["bonus"], ["plant", "titanium"])
        self.assertEqual(volcanoes["Arsia Mons"]["bonus"], ["plant", "plant"])

    def test_known_space_bonuses(self):
        # Top-left space: 2 steel, land.
        top_left = self.by_id["03"]
        self.assertEqual(top_left["bonus"], ["steel", "steel"])
        self.assertEqual(top_left["type"], "land")
        # Bottom-right ocean: 2 titanium.
        bottom_right = self.by_id["63"]
        self.assertEqual(bottom_right["bonus"], ["titanium", "titanium"])
        self.assertTrue(bottom_right["oceanReserved"])

    def test_known_adjacency(self):
        # Top-left corner touches its row neighbour and two spaces below.
        self.assertEqual(sorted(self.by_id["03"]["adjacent"]), ["04", "08", "09"])

    def test_ids_unique_and_sequential(self):
        ids = [s["id"] for s in self.spaces]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual([s["id"] for s in self.on_map],
                         [f"{i:02d}" for i in range(3, 64)])


if __name__ == "__main__":
    unittest.main()
