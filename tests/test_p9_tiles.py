"""P9 issue 6: the tracker's GENERIC tile vocabulary vs the app's SPECIFIC
tile names.

`apply.py place` records four generic terms (city | greenery | ocean |
special) while the app's board names the exact tile (commercialdistrict,
miningrights, capital …). verify.location_drift compared the two strings,
so every special tile printed a `TILE LOCATION` row for the rest of the
game (game1 gen 1: `18 Zed special → Zed commercialdistrict [app]`; gen 4
the same for miningrights) even though the state was byte-exact.

A generic term must match any app tile of ITS OWN CLASS — the same
classification tmlib.tile_counts uses to count tiles — and nothing else:
a different hex, a different owner, or a class change (city vs ocean,
special vs capital) is still real drift and must still report.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine  # noqa: E402
from test_new_game import SETUP  # noqa: E402
import verify  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def app(self, **spaces):
        return {sid: {"tile": t, "player": p} for sid, (t, p) in spaces.items()}


class TestGenericSpecialTile(Base):
    def test_generic_special_matches_a_named_app_special_tile(self):
        """The reported false positive: same hex, same owner, the tracker's
        generic 'special' against the app's 'commercialdistrict'."""
        self.eng.place("Zed", "special", "18")
        self.assertEqual(
            verify.location_drift(
                self.eng, self.app(**{"18": ("commercialdistrict", "Zed")})),
            [])

    def test_generic_special_matches_any_special_tile_name(self):
        for name in ("miningrights", "naturalpreserve", "lavaflows",
                     "miningarea", "restrictedarea", "nuclearzone",
                     "ecologicalzone", "industrialcenter", "moholearea"):
            with self.subTest(tile=name), tempfile.TemporaryDirectory() as d:
                store = Store(d)
                store.init(SETUP)
                eng = Engine(store)
                eng.place("Zed", "special", "18")
                self.assertEqual(
                    verify.location_drift(eng, self.app(**{"18": (name, "Zed")})),
                    [])

    def test_no_sync_row_is_emitted_for_a_named_special_tile(self):
        """gen 1 printed `TILE LOCATION: 18 Zed special → Zed
        commercialdistrict [app]`; nothing should be adopted or logged."""
        self.eng.place("Zed", "special", "18")
        out = verify.sync_locations(
            self.eng, self.app(**{"18": ("commercialdistrict", "Zed")}))
        self.assertEqual(out, [])

    def test_generic_city_matches_the_apps_capital_tile(self):
        """Capital IS a city for every counter the tracker keeps
        (tmlib.CITY_TILES), so the generic 'city' covers it."""
        self.eng.place("Zed", "city", "18")
        self.assertEqual(
            verify.location_drift(self.eng, self.app(**{"18": ("capital", "Zed")})),
            [])


class TestRealMismatchesStillReport(Base):
    def test_special_on_a_different_hex_still_reports(self):
        self.eng.place("Zed", "special", "18")
        rows = verify.location_drift(
            self.eng, self.app(**{"19": ("commercialdistrict", "Zed")}))
        self.assertEqual({r["kind"] for r in rows}, {"phantom", "missing"})

    def test_special_with_a_different_owner_still_reports(self):
        self.eng.place("Zed", "special", "18")
        rows = verify.location_drift(
            self.eng, self.app(**{"18": ("commercialdistrict", "Anna")}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "mismatch")

    def test_tracker_city_against_an_app_ocean_still_reports(self):
        self.eng.place("Zed", "city", "18")
        rows = verify.location_drift(self.eng, self.app(**{"18": ("ocean", None)}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "mismatch")

    def test_generic_special_against_a_city_class_tile_still_reports(self):
        """'special' does not swallow a capital: the two are different
        classes and the tile counters would disagree."""
        self.eng.place("Zed", "special", "18")
        rows = verify.location_drift(
            self.eng, self.app(**{"18": ("capital", "Zed")}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "mismatch")

    def test_two_different_named_special_tiles_still_report(self):
        """When BOTH sides name a specific tile, the names must match —
        the generic term is the only wildcard."""
        self.eng.place("Zed", "miningrights", "18")
        rows = verify.location_drift(
            self.eng, self.app(**{"18": ("commercialdistrict", "Zed")}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "mismatch")


class TestSyncPairsGenericAndNamedTiles(Base):
    def test_a_misplaced_generic_special_is_MOVED_not_re_added(self):
        """The move-pairing in sync_locations matches tracker tile against
        app tile too: a generic 'special' on the wrong hex is the same
        placement as the app's named special tile on the right one."""
        self.eng.place("Zed", "special", "18")
        out = verify.sync_locations(
            self.eng, self.app(**{"19": ("commercialdistrict", "Zed")}))
        board = self.store.load_game()["board"]
        self.assertNotIn("18", board)
        self.assertEqual(board["19"],
                         {"tile": "commercialdistrict", "player": "Zed"})
        self.assertEqual(len(out), 1)
        self.assertIn("moved", out[0])


if __name__ == "__main__":
    unittest.main()
