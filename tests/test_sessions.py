"""Game sessions: games/ holds one dated folder per game; state → active game."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import GameManager, Store, EventError
from test_new_game import SETUP


class TestGameSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gm = GameManager(self.root, today="2031-03-01")

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_creates_dated_game_dir_with_fresh_state(self):
        game_dir = self.gm.start(SETUP)
        self.assertEqual(game_dir, self.root / "games" / "2031-03-01-game1")
        assert (game_dir / "setup.json").exists()
        assert (game_dir / "game.json").exists()
        assert (game_dir / "log.md").exists()
        game = json.loads((game_dir / "game.json").read_text())
        self.assertEqual(game["generation"], 1)

    def test_start_points_state_symlink_at_active_game(self):
        game_dir = self.gm.start(SETUP)
        link = self.root / "state"
        assert link.is_symlink()
        self.assertEqual(link.resolve(), game_dir.resolve())
        # documented paths keep working: state/game.json is the live game
        store = Store(self.root)
        self.assertEqual(store.load_game()["generation"], 1)

    def test_start_second_game_while_active_refused(self):
        self.gm.start(SETUP)
        with self.assertRaises(EventError):
            self.gm.start(SETUP)

    def test_end_stamps_result_and_clears_active(self):
        game_dir = self.gm.start(SETUP)
        self.gm.end(note="Anna won, 71 VP")
        meta = json.loads((game_dir / "setup.json").read_text())
        self.assertEqual(meta["endedAt"], "2031-03-01")
        self.assertEqual(meta["result"], "Anna won, 71 VP")
        assert not (self.root / "state").exists()
        log = (game_dir / "log.md").read_text()
        self.assertIn("Game ended", log)

    def test_end_without_active_game_refused(self):
        with self.assertRaises(EventError):
            self.gm.end()

    def test_same_day_games_get_distinct_dirs(self):
        self.gm.start(SETUP)
        self.gm.end()
        d2 = self.gm.start(SETUP)
        self.assertEqual(d2.name, "2031-03-01-game2")

    def test_list_games_returns_all_with_active_flag(self):
        self.gm.start(SETUP)
        self.gm.end(note="test")
        self.gm.start(SETUP)
        games = self.gm.list_games()
        self.assertEqual(len(games), 2)
        self.assertFalse(games[0]["active"])
        self.assertTrue(games[1]["active"])
        self.assertEqual(games[1]["dir"], "2031-03-01-game2")


class TestLinkPlayer(unittest.TestCase):
    """Opponent app playerIds must be persisted to setup.json, not only the
    player's own. Otherwise every opponent id used all session comes from
    conversation memory, a silent violation of the 'never use game values
    from memory' rule, and a whole-game status check (gamecheck.py) cannot
    be built."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gm = GameManager(self.root, today="2031-03-02")
        self.gm.start(SETUP)

    def tearDown(self):
        self.tmp.cleanup()

    def test_link_player_writes_id_to_setup(self):
        self.gm.link_player("Anna", "p999")
        setup = json.loads((self.gm.active_dir() / "setup.json").read_text())
        players = {p["name"]: p for p in setup["players"]}
        self.assertEqual(players["Anna"]["playerId"], "p999")

    def test_link_player_unknown_name_refused(self):
        with self.assertRaises(EventError):
            self.gm.link_player("Nobody", "p999")

    def test_link_player_no_active_game_refused(self):
        self.gm.end()
        with self.assertRaises(EventError):
            self.gm.link_player("Anna", "p999")

    def test_relink_different_id_refused_without_force(self):
        self.gm.link_player("Anna", "p999")
        with self.assertRaises(EventError):
            self.gm.link_player("Anna", "pOTHER")

    def test_relink_same_id_is_a_noop_without_force(self):
        self.gm.link_player("Anna", "p999")
        self.gm.link_player("Anna", "p999")  # must not raise

    def test_force_overwrites_existing_id(self):
        self.gm.link_player("Anna", "p999")
        self.gm.link_player("Anna", "pOTHER", force=True)
        setup = json.loads((self.gm.active_dir() / "setup.json").read_text())
        players = {p["name"]: p for p in setup["players"]}
        self.assertEqual(players["Anna"]["playerId"], "pOTHER")



class TestSeatInit(unittest.TestCase):
    """`session.py seat-init <pid>`: a competitive seat's OWN state folder,
    built from that seat's /api/player view — isMe = the seat, only its
    playerId stored, app-practice mode. The advisor's state/ is untouched."""

    VIEW = {"thisPlayer": {"name": "Anna", "color": "green"},
            "players": [{"name": "Zed", "color": "red"},
                        {"name": "Anna", "color": "green"},
                        {"name": "Ben", "color": "yellow"}],
            "game": {"generation": 1, "phase": "research"}}

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_appapi import CannedServer
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.srv = CannedServer({"/api/player": [(200, self.VIEW)]})

    def tearDown(self):
        self.srv.close()
        self.tmp.cleanup()

    def test_seat_init_writes_an_isolated_seat_store(self):
        import session
        d = session.seat_init("p-anna", url=self.srv.url, root=self.root)
        self.assertEqual(d, self.root / "seats" / "p-anna")
        setup = json.loads((d / "setup.json").read_text())
        me = [p for p in setup["players"] if p.get("isMe")]
        self.assertEqual([p["name"] for p in me], ["Anna"])
        self.assertEqual(me[0]["playerId"], "p-anna")
        self.assertEqual([p["name"] for p in setup["players"]], ["Zed", "Anna", "Ben"])
        self.assertFalse(any(p.get("playerId") for p in setup["players"]
                             if not p.get("isMe")), "only the seat's own id is stored")
        self.assertEqual(setup["gameMode"], "app-practice")
        self.assertEqual(setup["appUrl"], self.srv.url)
        game = json.loads((d / "game.json").read_text())
        self.assertEqual(game["me"]["name"], "Anna")
        self.assertFalse((self.root / "state").exists(), "the advisor's state/ is untouched")

    def test_seat_init_refuses_an_existing_folder(self):
        import session
        session.seat_init("p-anna", url=self.srv.url, root=self.root)
        with self.assertRaises(EventError):
            session.seat_init("p-anna", url=self.srv.url, root=self.root)

    def test_seat_init_cli(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "session.py"
        r = subprocess.run([sys.executable, str(script), "seat-init", "p-anna",
                            "--url", self.srv.url, "--dir", str(self.root / "seat-a")],
                           capture_output=True, text=True, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("seat-a", r.stdout)
        self.assertTrue((self.root / "seat-a" / "game.json").exists())


if __name__ == "__main__":
    unittest.main()


class TestEndReminder(unittest.TestCase):
    """session.py end must remind the table to generate the post-game saga."""

    def test_end_reminder_names_narrator_and_command(self):
        import session
        msg = session.end_reminder(Path("games/2031-03-01-game1"))
        self.assertIn("narrator", msg.lower())
        self.assertIn("scripts/narrate.py games/2031-03-01-game1", msg)
        self.assertIn("saga", msg.lower())
