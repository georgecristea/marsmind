"""The judgment dial must be VISIBLE at game start and safe to turn.

Two gaps found while planning a live game:

1. setup.py wrote the judgment block silently, so the player had no idea the
   speed dial existed or what to type when the table ran slow.
2. `k` is the opponent INDEX that triggers the single after-k sweep, not a
   count. At N players, k = N-1 opponents is the last position that still
   sits outside the quiet zone. Setting k to the opponent count puts it ON
   the seat immediately before me, where should_sweep()'s quiet-zone check
   returns False before k is ever read — silently ZERO scheduled sweeps.
   That footgun must warn.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import judgment


def _setup(n):
    names = ["Me", "B", "C", "D", "E"][:n]
    return {"playerCount": n, "gameMode": "app-online",
            "players": [{"name": x, "color": c, "isMe": x == "Me"}
                        for x, c in zip(names, ["red", "blue", "green",
                                                "yellow", "black"])]}


class TestSweepLadderIsVisible(unittest.TestCase):

    def test_ladder_names_every_level_in_order(self):
        text = judgment.ladder_text(_setup(5))
        for level in ("every", "per-opponent", "after-k", "triggers-only"):
            self.assertIn(level, text)
        self.assertLess(text.index("every"), text.index("triggers-only"),
                        "fastest-to-slowest order must be obvious")

    def test_ladder_states_the_current_default_is_maximum_information(self):
        text = judgment.ladder_text(_setup(5))
        self.assertIn("every", text)
        self.assertIn("judgment.py set level", text,
                      "the player must be told the exact command")

    def test_ladder_reports_the_live_k_for_this_table(self):
        self.assertIn("k=3", judgment.ladder_text(_setup(5)))   # 4 opponents
        self.assertIn("k=1", judgment.ladder_text(_setup(3)))   # 2 opponents


class TestQuietZoneFootgun(unittest.TestCase):

    def test_k_at_the_opponent_count_is_flagged(self):
        w = judgment.k_warning(_setup(5), 4)      # 4 opponents, k=4
        self.assertTrue(w)
        self.assertIn("quiet", w.lower())
        self.assertIn("0", w)          # names the consequence: zero sweeps

    def test_safe_k_is_silent(self):
        self.assertEqual(judgment.k_warning(_setup(5), 3), "")
        self.assertEqual(judgment.k_warning(_setup(5), 1), "")

    def test_k_above_the_opponent_count_never_fires_either(self):
        self.assertTrue(judgment.k_warning(_setup(5), 9))

    def test_two_player_table_has_no_safe_k(self):
        """1 opponent IS the quiet zone — after-k can never fire there."""
        self.assertTrue(judgment.k_warning(_setup(2), 1))


if __name__ == "__main__":
    unittest.main()
