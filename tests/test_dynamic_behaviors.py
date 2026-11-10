"""Engine gaps: dynamic tag/count-based production and stock printed
'-> TABLE' and were hand-applied (Satellites, Toll Station, Worms, Media
Archives, Greenhouses), each a drift source; the or-choice card
(Artificial Photosynthesis) had no way to record the chosen branch; and
convert() hard-failed on stale opponent ESTIMATES (heat at 7, plants at
5) where the estimates-are-soft policy says clamp and proceed."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP


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


class TestDynamicProduction(Base):
    def test_satellites_counts_own_space_tags_including_itself(self):
        # 2 persistent space tags on the board + Satellites itself = 3
        self.eng.res("Zed", "mc", +99)
        self.eng.res("Zed", "titanium", +9)
        for c in ("Vesta Shipyard", "Convoy From Europa"):  # space tags
            self.eng.hand_add([c])
            self.eng.play("Zed", c, ignore_requirements=True)
        # Convoy From Europa is an EVENT — its tag must NOT persist
        self.eng.hand_add(["Satellites"])
        before = self.game()["me"]["production"]["mc"]
        self.eng.play("Zed", "Satellites")
        after = self.game()["me"]["production"]["mc"]
        self.assertEqual(after - before, 2)   # Vesta 1 + itself 1

    def test_worms_per_2_microbe_tags(self):
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add(["GHG Producing Bacteria"])
        self.eng.play("Zed", "GHG Producing Bacteria",
                      ignore_requirements=True)      # 1 microbe tag
        self.eng.hand_add(["Worms"])
        before = self.game()["me"]["production"]["plants"]
        self.eng.play("Zed", "Worms", ignore_requirements=True)
        after = self.game()["me"]["production"]["plants"]
        self.assertEqual(after - before, 1)   # (1 + itself 1) // 2 = 1

    def test_toll_station_counts_other_players_space_tags(self):
        self.eng.res("Anna", "mc", +99)
        self.eng.res("Anna", "titanium", +9)
        self.eng.play("Anna", "Vesta Shipyard", ignore_requirements=True)
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add(["Toll Station"])
        before = self.game()["me"]["production"]["mc"]
        self.eng.play("Zed", "Toll Station")
        after = self.game()["me"]["production"]["mc"]
        self.assertEqual(after - before, 1)   # Anna's 1 space tag; own don't count

    def test_dynamic_production_works_for_opponents_too(self):
        self.eng.res("Anna", "mc", +99)
        self.eng.res("Anna", "titanium", +9)
        self.eng.play("Anna", "Vesta Shipyard", ignore_requirements=True)
        before = self.game()["opponents"]["Anna"]["production"]["mc"]
        self.eng.play("Anna", "Satellites")
        after = self.game()["opponents"]["Anna"]["production"]["mc"]
        self.assertEqual(after - before, 2)   # Vesta 1 + itself 1


class TestDynamicStock(Base):
    def test_media_archives_counts_events_played_by_all(self):
        self.eng.res("Anna", "mc", +99)
        self.eng.play("Anna", "Comet", ignore_requirements=True)   # event
        self.eng.res("Zed", "mc", +99)
        self.eng.res("Zed", "titanium", +9)
        self.eng.hand_add(["Convoy From Europa"])
        self.eng.play("Zed", "Convoy From Europa")               # event
        self.eng.hand_add(["Media Archives"])
        before = self.game()["me"]["resources"]["mc"]
        self.eng.play("Zed", "Media Archives")
        after = self.game()["me"]["resources"]["mc"]
        self.assertEqual(after - before, -8 + 2)   # cost 8, +2 events

    def test_greenhouses_counts_all_city_tiles(self):
        self.eng.res("Zed", "mc", +99)
        self.eng.standard("Zed", "city")
        self.eng.res("Anna", "mc", +99)
        self.eng.standard("Anna", "city")
        self.eng.hand_add(["Greenhouses"])
        before = self.game()["me"]["resources"]["plants"]
        self.eng.play("Zed", "Greenhouses")
        after = self.game()["me"]["resources"]["plants"]
        self.assertEqual(after - before, 2)


class TestOrChoice(Base):
    # Choice indices follow the CARD TEXT order — Artificial
    # Photosynthesis reads "plant production 1 step OR energy production 2
    # steps" → 0 = plants, 1 = energy (the db lists energy first). Full
    # contract in tests/test_grid_refs_and_choices.py.
    def test_choice_applies_selected_branch(self):
        self.eng.res("Anna", "mc", +99)
        self.eng.play("Anna", "Artificial Photosynthesis", choice=1)
        self.assertEqual(
            self.game()["opponents"]["Anna"]["production"]["energy"], 2)
        self.assertEqual(
            self.game()["opponents"]["Anna"]["production"]["plants"], 0)

    def test_no_choice_lists_branches_and_refuses(self):
        # MY play must be exact: two executable branches → say which.
        self.eng.res("Zed", "mc", +99)
        self.eng.hand_add(["Artificial Photosynthesis"])
        with self.assertRaises(EventError) as cm:
            self.eng.play("Zed", "Artificial Photosynthesis")
        self.assertIn("--choice 0", str(cm.exception))

    def test_an_opponents_ambiguous_branch_is_flagged_not_refused(self):
        # An opponent's state is an ESTIMATE and a log line must never be
        # blocked: the card is charged, the non-optional part applies and
        # the branch is flagged for the advisor to log.
        self.eng.res("Anna", "mc", +99)
        msg = self.eng.play("Anna", "Artificial Photosynthesis")
        self.assertIn("not recorded", msg)
        prod = self.game()["opponents"]["Anna"]["production"]
        self.assertEqual((prod["plants"], prod["energy"]), (0, 0))


class TestOpponentConvertClamps(Base):
    def test_opponent_heat_estimate_short_clamps_and_proceeds(self):
        # Carl's tracked heat is 7 (estimate), he really has 8
        self.eng.res("Anna", "heat", +7)
        msg = self.eng.convert("Anna", "heat")
        g = self.game()
        self.assertEqual(g["opponents"]["Anna"]["resources"]["heat"], 0)
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertIn("estimate", msg.lower())

    def test_opponent_plants_estimate_short_clamps_and_proceeds(self):
        self.eng.res("Anna", "plants", +5)
        self.eng.convert("Anna", "plants")
        g = self.game()
        self.assertEqual(g["opponents"]["Anna"]["resources"]["plants"], 0)
        self.assertEqual(g["opponents"]["Anna"]["tiles"]["greeneries"], 1)

    def test_my_own_convert_still_strict(self):
        self.eng.res("Zed", "heat", +7)
        with self.assertRaises(EventError):
            self.eng.convert("Zed", "heat")


if __name__ == "__main__":
    unittest.main()
