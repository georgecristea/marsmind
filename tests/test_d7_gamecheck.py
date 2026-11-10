"""D7 — gamecheck.py recognises game end.

Bug (Codex H5): at game end every seat's waitingFor goes None (nobody is
"WAITING") so gamecheck's ambiguous-table branch ("nobody is waiting")
fired and exited 2 -- even though the app's own player view already says
game.phase == "end" and carries a final victoryPointsBreakdown per player.
Before treating an all-idle table as ambiguous, gamecheck must check for
that end-phase signal: if the game is over, print `GAME ENDED` plus one
line per player with their final total (victoryPointsBreakdown.total) and
exit 0 -- no anomaly.

All scenarios below are driven by stubbed /api/player views (the `get`
callable gamecheck.py already takes for injection) -- no server.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import gamecheck


def _ended_view(pid_players):
    """One /api/player response shape once the app has finished the game:
    every seat's waitingFor is None, game.phase is 'end', and 'players'
    carries the whole table's final victoryPointsBreakdown (this is the
    same view regardless of which pid is queried -- see score.py's
    app_final_table, which relies on the identical assumption)."""
    return {
        "waitingFor": None,
        "game": {"phase": "end"},
        "players": [{"name": name, "victoryPointsBreakdown": {"total": total}}
                    for name, total in pid_players],
    }


class TestFindEnded(unittest.TestCase):
    def test_ended_game_yields_sorted_totals(self):
        rows = gamecheck.check_all_full(
            [{"name": "Zed", "playerId": "p1"}, {"name": "Ana", "playerId": "p2"}],
            get=lambda pid: _ended_view([("Zed", 69), ("Ana", 87)]))
        ended = gamecheck.find_ended(rows)
        self.assertEqual(ended, [{"name": "Ana", "total": 87},
                                  {"name": "Zed", "total": 69}])

    def test_live_game_yields_none(self):
        rows = gamecheck.check_all_full(
            [{"name": "Zed", "playerId": "p1"}],
            get=lambda pid: {"waitingFor": None, "game": {"phase": "action"},
                              "players": None})
        self.assertIsNone(gamecheck.find_ended(rows))

    def test_missing_players_list_is_not_treated_as_ended(self):
        # phase says 'end' but no breakdown data came through -- don't
        # fabricate a totals table, fall back to the ambiguous path.
        rows = gamecheck.check_all_full(
            [{"name": "Zed", "playerId": "p1"}],
            get=lambda pid: {"waitingFor": None, "game": {"phase": "end"},
                              "players": None})
        self.assertIsNone(gamecheck.find_ended(rows))


class TestRenderEnd(unittest.TestCase):
    def test_lists_every_player_and_total(self):
        text = gamecheck.render_end([{"name": "Ana", "total": 87},
                                     {"name": "Zed", "total": 69}])
        self.assertIn("GAME ENDED", text)
        self.assertIn("Ana", text)
        self.assertIn("87", text)
        self.assertIn("Zed", text)
        self.assertIn("69", text)


class TestCheckAllBackCompat(unittest.TestCase):
    def test_check_all_row_shape_unchanged(self):
        # check_all (used by the pre-existing suite / other callers) must
        # keep returning exactly the old 3-key rows even at game end --
        # callers that don't know about end-of-game see no shape change.
        rows = gamecheck.check_all(
            [{"name": "Zed", "playerId": "p1"}],
            get=lambda pid: _ended_view([("Zed", 42)]))
        self.assertEqual(rows, [{"name": "Zed", "waiting": False, "title": None}])


class TestRun(unittest.TestCase):
    """The full check-and-report cycle main() wires to the real app, but
    decoupled from setup.json/AppClient -- exactly the three scenarios the
    bug report calls for."""

    def test_ended_game_exits_0_and_prints_totals(self):
        players = [{"name": "Zed", "playerId": "p1"}, {"name": "Ana", "playerId": "p2"}]
        code, text = gamecheck.run(
            players, get=lambda pid: _ended_view([("Zed", 69), ("Ana", 87)]))
        self.assertEqual(code, 0)
        self.assertIn("GAME ENDED", text)
        self.assertIn("Ana", text)
        self.assertIn("87", text)
        self.assertIn("Zed", text)
        self.assertIn("69", text)

    def test_live_all_idle_still_exits_2(self):
        players = [{"name": "Zed", "playerId": "p1"}, {"name": "Ana", "playerId": "p2"}]
        code, text = gamecheck.run(
            players,
            get=lambda pid: {"waitingFor": None, "game": {"phase": "action"},
                              "players": None})
        self.assertEqual(code, 2)
        self.assertNotIn("GAME ENDED", text)
        self.assertIn("nobody", text.lower())

    def test_live_one_seat_waiting_unchanged(self):
        players = [{"name": "Zed", "playerId": "p1"}, {"name": "Ana", "playerId": "p2"}]

        def get(pid):
            if pid == "p1":
                return {"waitingFor": {"title": "Take your first action"},
                        "game": {"phase": "action"}, "players": None}
            return {"waitingFor": None, "game": {"phase": "action"},
                    "players": None}

        code, text = gamecheck.run(players, get=get)
        self.assertEqual(code, 0)
        self.assertNotIn("GAME ENDED", text)
        self.assertIn("Zed", text)
        self.assertIn("WAITING", text)


if __name__ == "__main__":
    unittest.main()
