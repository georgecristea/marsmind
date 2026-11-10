"""W2-A item 2: formula VP computed, with honest bounds.

Reference failure: a real 5p game where score.py printed "2 cards with
formula VP not countable" and the 5-point lead the advisor relayed was a
5-point deficit — the winner's Capital (+3, adjacent oceans) and
Commercial District (+1, adjacent city) were invisible.

Contract pinned here:
- adjacency formulas are computed from the tracked board (Capital =
  1 VP / adjacent ocean; Commercial District = 1 VP / adjacent city);
- per-resource formulas score exactly from tracked counts;
- a genuinely unknown component (count never observed / tile hex not on
  the tracked board) produces an explicit [min–max] bound on that
  player's TOTAL — min = known floor, max = floor + a cap derived from
  the db + board (≤6 neighbours, only tiles already on the board), or
  "unbounded" when no sane cap exists (per-resource counts have no db
  ceiling) — never a silent "not countable";
- the standings line carries the bound, never the bare floor, whenever a
  bound exists.

The acceptance fixture reconstructs the reference game's end state with
aliased seats (rule 7: no real names in committed files):
Anna=the winner (Capital 3 adjacent oceans, Commercial District adjacent
to 1 city), Ben=Small Animals 2 animals, Diana=Security Fleet 3 fighters
observed; app final table Anna 64 · Zed 56 · Ben 52 · Carl 50 · Diana 41.
"""
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from tmlib import Store, Engine                       # noqa: E402
import score                                          # noqa: E402
import shape                                          # noqa: E402

SETUP5 = {
    "playerCount": 5,
    "players": [
        {"name": "Zed", "color": "red", "isMe": True, "aliases": []},
        {"name": "Anna", "color": "yellow", "isMe": False, "aliases": []},
        {"name": "Ben", "color": "blue", "isMe": False, "aliases": []},
        {"name": "Carl", "color": "green", "isMe": False, "aliases": []},
        {"name": "Diana", "color": "orange", "isMe": False, "aliases": []},
    ],
    "expansions": ["base", "corporateEra"],
    "map": "tharsis",
    "draft": False,
    "houseRules": [],
    "seatingOrder": ["Zed", "Anna", "Ben", "Carl", "Diana"],
    "firstPlayerGen1": "Zed",
}

APP_FINAL = {"Anna": 64, "Zed": 56, "Ben": 52, "Carl": 50, "Diana": 41}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(copy.deepcopy(SETUP5))
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def rows(self, mode="full"):
        return {r["name"]: r for r in
                score.compute(self.game(), mode)["players"]}

    def set_tr(self, player, tr):
        g = self.game()
        pool = g["me"] if g["me"]["name"] == player else g["opponents"][player]
        self.eng.tr(player, tr - pool["tr"])

    def cli(self, *argv):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "score.py"), "--state",
             str(Path(self.tmp.name) / "state" / "game.json"), *argv],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout


class AdjacencyBase(Base):
    def place_capital(self, oceans=("33", "34", "43")):
        for sid in oceans:
            self.eng.place("Carl", "ocean", sid)
        self.eng.observe_play("Anna", "Capital")
        self.eng.place("Anna", "capital", "42", card="Capital")


class TestAdjacencyFormulas(AdjacencyBase):
    def test_capital_scores_adjacent_oceans_from_the_board(self):
        self.place_capital()
        anna = self.rows()["Anna"]
        self.assertEqual(anna["cardVP"], 3)
        self.assertNotIn("Capital", anna["formulaVPCards"])

    def test_commercial_district_scores_adjacent_cities(self):
        self.eng.observe_play("Anna", "Commercial District")
        self.eng.place("Anna", "commercialdistrict", "23",
                       card="Commercial District")
        self.eng.place("Ben", "city", "22")
        anna = self.rows()["Anna"]
        self.assertEqual(anna["cardVP"], 1)

    def test_commercial_district_counts_a_capital_as_a_city(self):
        self.eng.observe_play("Anna", "Commercial District")
        self.eng.place("Anna", "commercialdistrict", "23",
                       card="Commercial District")
        self.eng.place("Ben", "capital", "22", card="Capital")
        self.assertEqual(self.rows()["Anna"]["cardVP"], 1)

    def test_unplaced_capital_is_bounded_by_the_board(self):
        # 3 oceans on the board, but the Capital tile hex is untracked:
        # the bound is [floor, floor + min(6, oceans-on-board)]
        for sid in ("33", "34", "43"):
            self.eng.place("Carl", "ocean", sid)
        self.eng.observe_play("Anna", "Capital")
        anna = self.rows()["Anna"]
        self.assertEqual(anna["cardVP"], 0)
        self.assertIn("Capital", anna["formulaVPCards"])
        self.assertEqual(anna["vpMax"], anna["total"] + 3)

    def test_unplaced_capital_with_no_oceans_collapses_to_exact(self):
        self.eng.observe_play("Anna", "Capital")
        anna = self.rows()["Anna"]
        self.assertEqual(anna["vpMax"], anna["total"])
        self.assertIsNone(score.bound_str(anna))


class TestResourceBounds(Base):
    def test_tracked_count_scores_exactly(self):
        self.eng.observe_play("Diana", "Security Fleet")
        self.eng.sync_card_resources("Diana", {"Security Fleet": 3})
        diana = self.rows()["Diana"]
        self.assertEqual(diana["cardVP"], 3)
        self.assertEqual(diana["vpMax"], diana["total"])

    def test_unobserved_count_is_unbounded_above(self):
        self.eng.observe_play("Diana", "Security Fleet")
        diana = self.rows()["Diana"]
        self.assertEqual(diana["cardVP"], 0)          # excluded from min
        self.assertIsNone(diana["vpMax"])             # no sane db cap
        self.assertTrue(any("Security Fleet" in m for m in diana["manualVP"]))
        self.assertEqual(score.bound_str(diana), f"≥{diana['total']}")

    def test_bounded_player_standings_carry_the_bound(self):
        self.eng.observe_play("Diana", "Security Fleet")
        line = score.standings_line(self.game())
        self.assertIn("Diana ≥", line)

    def test_exact_players_keep_the_plain_number(self):
        self.set_tr("Carl", 50)
        line = score.standings_line(self.game())
        self.assertIn("Carl 50", line)


class TestCardVPLineContract(Base):
    """'not countable' may no longer appear without a bound — the line
    names each uncounted card WITH its cap (or 'unbounded')."""

    def test_line_carries_the_per_card_bound(self):
        self.eng.observe_play("Diana", "Security Fleet")
        line = score.card_vp_line(self.rows()["Diana"])
        self.assertIn("Security Fleet", line)
        self.assertIn("unbounded", line)

    def test_adjacency_unknown_carries_its_cap(self):
        for sid in ("33", "34"):
            self.eng.place("Carl", "ocean", sid)
        self.eng.observe_play("Anna", "Capital")
        line = score.card_vp_line(self.rows()["Anna"])
        self.assertIn("Capital", line)
        self.assertIn("≤2", line)

    def test_all_counted_line_unchanged(self):
        self.eng.observe_play("Anna", "Trees")
        self.assertIn("all card VP counted",
                      score.card_vp_line(self.rows()["Anna"]))

    def test_cli_never_says_not_countable_without_a_bound(self):
        self.eng.observe_play("Diana", "Security Fleet")
        for argv in ([], ["--abort"]):
            out = self.cli(*argv)
            self.assertNotIn("not countable", out)
            self.assertIn("unbounded", out)


class TestShapeParsesBoundedStandings(Base):
    """shape.vp_slope reads the produce-logged standings lines; a bound
    ('Diana ≥38', 'Anna 61–64') must parse to the FLOOR, not corrupt the
    slope."""

    def test_standing_row_regex_reads_the_floor(self):
        for seg, want in (("Anna 61–64 (TR 60 +1 cards)", ("Anna", "61")),
                          (("Diana ≥38 (TR 38 +?)"), ("Diana", "38")),
                          ("Carl 50 (TR 50)", ("Carl", "50"))):
            m = shape._STANDING_ROW.match(seg)
            self.assertIsNotNone(m, seg)
            self.assertEqual((m.group("name"), m.group("total")), want, seg)


class TestAcceptanceReferenceGame(AdjacencyBase):
    """The reference game's end state: per-player totals must match the
    app's real final table within the printed bounds."""

    def fixture(self, fighters_observed=True, capital_placed=True):
        # the winner: Capital w/ 3 adjacent oceans + Commercial District
        # adjacent to 1 city
        if capital_placed:
            self.place_capital()
        else:
            for sid in ("33", "34", "43"):
                self.eng.place("Carl", "ocean", sid)
            self.eng.observe_play("Anna", "Capital")
        self.eng.observe_play("Anna", "Commercial District")
        self.eng.place("Anna", "commercialdistrict", "23",
                       card="Commercial District")
        self.eng.place("Ben", "city", "22")
        self.set_tr("Anna", 60)
        # me
        self.set_tr("Zed", 56)
        # Small Animals: 2 animals observed → 1 VP (1 per 2)
        self.eng.observe_play("Ben", "Small Animals")
        self.eng.sync_card_resources("Ben", {"Small Animals": 2})
        self.set_tr("Ben", 51)
        self.set_tr("Carl", 50)
        # Security Fleet: 3 fighters observed → 3 VP
        self.eng.observe_play("Diana", "Security Fleet")
        if fighters_observed:
            self.eng.sync_card_resources("Diana", {"Security Fleet": 3})
        self.set_tr("Diana", 38)

    def test_fully_tracked_state_matches_the_app_table_exactly(self):
        self.fixture()
        rows = self.rows("full")
        for name, want in APP_FINAL.items():
            self.assertEqual(rows[name]["total"], want, name)
            self.assertEqual(rows[name]["vpMax"], want, name)
        order = [r["name"] for r in
                 score.compute(self.game(), "full")["players"]]
        self.assertEqual(order, ["Anna", "Zed", "Ben", "Carl", "Diana"])

    def test_cli_prints_the_exact_totals(self):
        self.fixture()
        out = self.cli()
        for name, want in APP_FINAL.items():
            self.assertIn(f"{name}: {want} VP", out)
        self.assertNotIn("not countable", out)

    def test_unobserved_fighters_bound_contains_the_app_value(self):
        self.fixture(fighters_observed=False)
        diana = self.rows("full")["Diana"]
        self.assertLessEqual(diana["total"], APP_FINAL["Diana"])
        self.assertIsNone(diana["vpMax"])             # unbounded above
        self.assertIn("Diana ≥38", score.standings_line(self.game()))

    def test_unplaced_capital_bound_contains_the_app_value(self):
        self.fixture(capital_placed=False)
        anna = self.rows("full")["Anna"]
        self.assertLessEqual(anna["total"], APP_FINAL["Anna"])
        self.assertGreaterEqual(anna["vpMax"], APP_FINAL["Anna"])
        self.assertIn(f"Anna {anna['total']}–{anna['vpMax']}",
                      score.standings_line(self.game()))


if __name__ == "__main__":
    unittest.main()
