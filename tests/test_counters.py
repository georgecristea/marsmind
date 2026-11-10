"""ONE tag counter and ONE tile counter.

Two live wrong answers the audit found, both of which fire at a PHYSICAL
table where there is no app to correct them:

  * `score.py` counted a player's tags from playedCards / tagCounts and
    forgot the CORPORATION's own tags, while `menu.py` counted them — so
    the same Scientist award had two answers, and every tag-VP card was
    short, at a table with Inventrix or Mining Guild in it.
  * `score.py`'s Landlord metric was `sum(tiles.values())`, and `tiles`
    carries `citiesOffMars` as a SUB-count of `cities` — so a reserved-area
    city (Ganymede Colony, Phobos Space Haven) was counted twice.

Both counters now live in tmlib and every consumer asks them.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import menu
import score
import tmlib
import verify
from tmlib import Engine, Store
from test_new_game import SETUP

ME = SETUP["players"][0]["name"]
OPP = SETUP["players"][1]["name"]


def _fresh():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name))
    store.init(SETUP)
    return Engine(store), tmp


class TagCounterTest(unittest.TestCase):
    def setUp(self):
        self.eng, self.tmp = _fresh()
        self.addCleanup(self.tmp.cleanup)

    def game(self):
        return self.eng.store.load_game()

    def test_the_corporations_tags_count_for_everyone(self):
        self.eng.corp(ME, "Inventrix", 45)       # 1 science tag
        game = self.game()
        self.assertEqual(tmlib.persisting_tags(game, ME).get("science"), 1)
        self.assertEqual(menu.tag_counts(game, ME).get("science"), 1)
        self.assertEqual(score._tag_counts(game, game["me"], True,
                                           score.cardlib.load_db()
                                           ).get("science"), 1)

    def test_score_award_metric_includes_the_corporation_tag(self):
        # the audit's bug: score.compute under-counted Scientist while the
        # menu counted it — the same award, two answers.
        self.eng.corp(ME, "Inventrix", 45)
        self.eng.award(ME, "Scientist")
        rows = {r["name"]: r for r in score.compute(self.game())["players"]}
        self.assertEqual(rows[ME]["awardVP"], score.AWARD_VP[0])
        self.assertIn("Scientist 1st", " ".join(rows[ME]["vpNotes"]))

    def test_menu_and_score_never_disagree_about_an_award_metric(self):
        self.eng.corp(ME, "Inventrix", 45)
        game = self.game()
        for name in (ME, OPP):
            self.assertEqual(menu.award_metrics(game, name),
                             tmlib.award_metrics(game, name))

    def test_a_corporation_with_two_building_tags_counts_twice(self):
        self.eng.corp(ME, "Mining Guild", 30)    # two building tags
        game = self.game()
        self.assertEqual(tmlib.persisting_tags(game, ME)["building"], 2)
        self.assertEqual(menu.milestone_metrics(game, ME)["Builder"], 2)

    def test_event_tags_do_not_persist(self):
        self.eng.corp(ME, "Inventrix", 45)
        self.eng.hand_add(["Comet"])             # an event: space + earth
        self.eng.play(ME, "Comet", target=OPP)
        game = self.game()
        self.assertEqual(tmlib.persisting_tags(game, ME).get("space", 0), 0)
        self.assertEqual(menu.tag_counts(game, ME).get("space", 0), 0)

    def test_an_untracked_opponent_falls_back_to_the_event_counter(self):
        # a physical table: the opponent's tableau is unknown, only the
        # event-driven counter has anything in it.
        game = self.game()
        game["opponents"][OPP]["tagCounts"] = {"science": 3}
        self.assertEqual(tmlib.persisting_tags(game, OPP)["science"], 3)
        self.assertEqual(menu.tag_counts(game, OPP)["science"], 3)


class TileCounterTest(unittest.TestCase):
    def setUp(self):
        self.eng, self.tmp = _fresh()
        self.addCleanup(self.tmp.cleanup)

    def game(self):
        return self.eng.store.load_game()

    def _rich(self, mc=200):
        self.eng.corp(ME, "Teractor", 60)
        self.eng.res(ME, "mc", mc)

    def _off_mars_city(self):
        """A reserved-area city: no hex, cities +1 AND citiesOffMars +1."""
        self._rich()
        self.eng.hand_add(["Ganymede Colony"])
        self.eng.play(ME, "Ganymede Colony")

    def test_an_off_mars_city_is_never_counted_twice(self):
        self._off_mars_city()
        game = self.game()
        tiles = game["me"]["tiles"]
        self.assertEqual((tiles["cities"], tiles["citiesOffMars"]), (1, 1))
        counts = tmlib.tile_counts(game, ME)
        self.assertEqual(counts["cities"], 1)
        self.assertEqual(counts["citiesOnMars"], 0)
        self.assertEqual(counts["landlord"], 1)      # not 2
        self.assertEqual(tmlib.award_metric(game, ME, "Landlord"), 1)

    def test_landlord_counts_cities_greeneries_and_special_tiles_once(self):
        self._off_mars_city()
        self.eng.standard(ME, "city")
        self.eng.place(ME, "city", "A1")
        game = self.game()
        game["me"]["tiles"]["greeneries"] = 2
        game["me"]["tiles"]["special"] = 1
        self.eng.store.save_game(game)
        game = self.game()
        self.assertEqual(tmlib.tile_counts(game, ME)["cities"], 2)
        self.assertEqual(tmlib.award_metric(game, ME, "Landlord"), 5)

    def test_the_mayor_milestone_counts_cities_from_the_board(self):
        self._rich()
        for hexes in ("A1", "A3", "B1"):
            self.eng.standard(ME, "city")
            self.eng.place(ME, "city", hexes)
        game = self.game()
        game["me"]["tiles"]["cities"] = 0        # a stale cache
        self.eng.store.save_game(game)
        game = self.game()
        self.assertEqual(tmlib.tile_counts(game, ME)["cities"], 3)
        self.assertEqual(menu.milestone_metrics(game, ME)["Mayor"], 3)

    def test_every_caller_agrees_on_the_tile_counts(self):
        self._off_mars_city()
        self.eng.standard(ME, "city")
        self.eng.place(ME, "city", "A1")
        game = self.game()
        counts = tmlib.tile_counts(game, ME)
        board = verify.board_counts(game, ME)
        self.assertEqual(board["cities"], counts["citiesOnMars"])
        self.assertEqual(board["greeneries"], counts["greeneries"])
        self.assertEqual(menu.milestone_metrics(game, ME)["Mayor"],
                         counts["cities"])
        self.assertEqual(score.compute(game)["players"][0]["name"], ME)


if __name__ == "__main__":
    unittest.main()
