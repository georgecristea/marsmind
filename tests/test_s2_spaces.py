"""S2 — `apply.py spaces` gains an adjMine column and a `--sort` flag.

Presentation only, over data `Engine.legal_spaces` already returns (which
already handles legality — city-not-adjacent-to-city doctrine is a table
reminder, not engine-enforced; greenery-adjacent-to-own-tile IS engine-
enforced). `legal_spaces` itself is untouched here — every assertion below
is about `apply.py`'s CLI formatting and its new `--sort` argparse option.

Layout used throughout (real board.json geometry, Tharsis):
  hex 10 (free, target) is adjacent to 04, 05, 11, 16, 17, 09
    - 05: Zed (me) city        -> counts toward adjMine
    - 17: Zed (me) special     -> counts toward adjMine
    - 16: Anna (opponent) city -> must NOT count toward adjMine
    - 04: ocean (ocean-reserved hex) -> must NOT count (oceans owned by no one)
    - 09, 11: left free
  hex 12 (free) is adjacent to 06, 07, 13, 19, 18, 11
    - 06, 07: ocean            -> adjOceans=2, beats hex 10's adjOceans=1
    - 13, 19, 18, 11: left free
  hex 19 (free) has NO occupied neighbours at all -> its default-format row
    must be byte-identical to the pre-S2 output.
"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cli import CLITest, run  # noqa: E402  (reuses the project's CLI harness)


class SpacesBase(CLITest):
    def setUp(self):
        super().setUp()
        # own tiles adjacent to hex 10
        self.place("Zed", "city", "05")
        self.place("Zed", "special", "17")
        # opponent tile adjacent to hex 10 — must never count as mine
        self.place("Anna", "city", "16")
        # oceans adjacent to hex 10 (one) and hex 12 (two) — owned by no one
        self.place("Zed", "ocean", "04")
        self.place("Zed", "ocean", "06")
        self.place("Anna", "ocean", "07")

    def place(self, player, tile, space):
        r = run(["apply.py", "place", player, tile, space], self.cwd)
        assert r.returncode == 0, r.stderr

    def spaces(self, tile="city", extra=()):
        r = run(["apply.py", "spaces", tile, *extra], self.cwd)
        assert r.returncode == 0, r.stderr
        return r.stdout.rstrip("\n").split("\n")

    def row(self, lines, hex_id):
        hit = [ln for ln in lines if ln.split()[0] == hex_id]
        assert hit, f"hex {hex_id} not in output:\n" + "\n".join(lines)
        return hit[0]


class TestAdjMineColumn(SpacesBase):
    def test_adjmine_counts_own_tiles_only(self):
        lines = self.spaces()
        row10 = self.row(lines, "10")
        self.assertIn("adjMine=2", row10)
        # Anna's city at 16 must not be counted
        self.assertNotIn("adjMine=3", row10)
        self.assertNotIn("adjMine=1", row10)

    def test_breakdown_names_the_hexes(self):
        lines = self.spaces()
        row10 = self.row(lines, "10")
        self.assertIn("(city 05, special 17)", row10)

    def test_oceans_never_count_toward_adjmine_even_when_self_placed(self):
        lines = self.spaces()
        row12 = self.row(lines, "12")
        # both ocean neighbours of 12 were placed by me/Anna; neither counts
        self.assertIn("adjMine=0", row12)
        self.assertIn("adjOceans=2", row12)

    def test_existing_columns_unchanged_order_and_content(self):
        lines = self.spaces()
        row10 = self.row(lines, "10")
        # id, name, bonus, adjOceans still appear, in order, before adjMine
        self.assertRegex(
            row10,
            r"^\s*10 {2,}bonus=\[\] adjOceans=1 adjMine=2")

    def test_adj_dict_still_present_and_unchanged_shape(self):
        lines = self.spaces()
        row10 = self.row(lines, "10")
        self.assertIn(
            "adj={'04': 'ocean', '05': 'city', '17': 'special', "
            "'16': 'city'}",
            row10)


class TestNoNeighboursByteIdentical(SpacesBase):
    def test_hex_with_no_occupied_neighbours_matches_pre_s2_format(self):
        lines = self.spaces()
        row19 = self.row(lines, "19")
        # the pre-S2 formatter: f"{id:>3} {name or '':<20} bonus={bonus}
        # adjOceans={adjOceans}" with NO adj= suffix when adjacentTiles is
        # empty — hex 19 has zero occupied neighbours in this fixture, so
        # adjMine must not appear either (mirrors the old adj= conditional).
        self.assertEqual(row19, " 19                      bonus=[] adjOceans=0")
        self.assertNotIn("adjMine", row19)
        self.assertNotIn("adj=", row19)


class TestSort(SpacesBase):
    def test_sort_mine_puts_the_highest_first(self):
        lines = self.spaces(extra=("--sort", "mine"))
        self.assertEqual(lines[0].split()[0], "10")  # adjMine=2, the max

    def test_sort_oceans_sorts_by_adjoceans(self):
        lines = self.spaces(extra=("--sort", "oceans"))
        self.assertEqual(lines[0].split()[0], "12")  # adjOceans=2, the max

    def test_sort_bonus_is_a_valid_choice(self):
        # no assertion on order beyond "it runs" — bonus counts on this
        # fixture's free city hexes are mostly 0/1, the flag's job here is
        # just to be accepted and not crash.
        r = run(["apply.py", "spaces", "city", "--sort", "bonus"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_unsorted_default_is_unaffected_by_sort_logic(self):
        default_lines = self.spaces()
        sorted_lines = self.spaces(extra=("--sort", "mine"))
        # same set of rows either way — sorting reorders, never drops/adds
        self.assertEqual(set(default_lines), set(sorted_lines))

    def test_bad_sort_value_rejected(self):
        r = run(["apply.py", "spaces", "city", "--sort", "bogus"], self.cwd)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
