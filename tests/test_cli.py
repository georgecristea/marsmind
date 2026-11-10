"""CLI smoke tests: thin wrappers must wire args → tmlib and print results."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def run(args, cwd, stdin=""):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / args[0]), *args[1:]],
        cwd=cwd, input=stdin, capture_output=True, text=True,
    )


SETUP_ANSWERS = "\n".join([
    "Zed",          # your name
    "red",             # your color
    "Anna=green, Felix=blue",  # opponents
    "",                # expansions (default base,corporateEra)
    "",                # map (default tharsis)
    "",                # draft (default no)
    "",                # seating order (default: listed order)
    "Anna",            # first player gen 1
    "",                # house rules (done)
]) + "\n"


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = self.tmp.name
        r = run(["setup.py"], self.cwd, stdin=SETUP_ANSWERS)
        assert r.returncode == 0, r.stderr

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return json.loads((Path(self.cwd) / "state" / "game.json").read_text())


class TestSetupCLI(CLITest):
    def test_creates_session_and_state(self):
        assert (Path(self.cwd) / "state" / "game.json").exists()
        games = list((Path(self.cwd) / "games").iterdir())
        self.assertEqual(len(games), 1)
        setup = json.loads((Path(self.cwd) / "state" / "setup.json").read_text())
        self.assertEqual(setup["playerCount"], 3)
        self.assertEqual(setup["firstPlayerGen1"], "Anna")
        self.assertEqual(setup["map"], "tharsis")
        self.assertEqual([p["name"] for p in setup["players"]],
                         ["Zed", "Anna", "Felix"])
        self.assertTrue(setup["players"][0]["isMe"])

    def test_refuses_second_game_while_active(self):
        r = run(["setup.py"], self.cwd, stdin=SETUP_ANSWERS)
        self.assertNotEqual(r.returncode, 0)


class TestApplyCLI(CLITest):
    def test_res_and_prod(self):
        r = run(["apply.py", "res", "Zed", "mc", "+30"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MC", r.stdout)
        run(["apply.py", "prod", "zed", "energy", "+2"], self.cwd)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 30)
        self.assertEqual(g["me"]["production"]["energy"], 2)

    def test_play_and_opponent_event(self):
        run(["apply.py", "res", "Zed", "mc", "+30"], self.cwd)
        run(["apply.py", "hand", "add", "Comet"], self.cwd)
        r = run(["apply.py", "play", "Zed", "Comet", "--cost", "21"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = run(["apply.py", "play", "blue", "Mining Rights"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        g = self.game()
        self.assertEqual(g["me"]["playedCards"][0]["name"], "Comet")
        self.assertEqual(g["opponents"]["Felix"]["playedCards"][0]["name"],
                         "Mining Rights")

    def test_illegal_event_exits_nonzero_with_message(self):
        r = run(["apply.py", "res", "Zed", "steel", "-1"], self.cwd)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("negative", r.stderr)

    def test_convert_and_globals(self):
        run(["apply.py", "res", "Zed", "heat", "+8"], self.cwd)
        run(["apply.py", "convert", "Zed", "heat"], self.cwd)
        run(["apply.py", "sync", "oxygen", "3"], self.cwd)
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["globals"]["oxygen"], 3)


class TestProduceCLI(CLITest):
    def test_produce_advances_generation(self):
        r = run(["produce.py"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["generation"], 2)

    def test_help_does_not_run_production(self):
        """`produce.py --help` used to FALL THROUGH into a real
        turnover (no argparse at all) — an accidental generation advance
        mid-game. Help must print and change nothing."""
        r = run(["produce.py", "--help"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("usage", r.stdout.lower())
        self.assertEqual(self.game()["generation"], 1)

    def test_unknown_flag_refuses_instead_of_producing(self):
        r = run(["produce.py", "--dry-run"], self.cwd)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.game()["generation"], 1)


class TestSetupCLI(CLITest):
    def test_help_does_not_start_a_game(self):
        """setup.py had no parser either — `setup.py --help` fell
        through to the interactive prompts and, on EOF, would create a
        game session from the defaults. Help must print and create nothing."""
        run(["session.py", "end", "--note", "done"], self.cwd)
        r = run(["setup.py", "--help"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("usage", r.stdout.lower())
        assert not (Path(self.cwd) / "state").exists(), \
            "setup.py --help created a game session"


class TestSessionCLI(CLITest):
    def test_list_shows_active_game(self):
        r = run(["session.py", "list"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("game1", r.stdout)
        self.assertIn("ACTIVE", r.stdout)

    def test_end_then_new_game_starts_fresh(self):
        r = run(["session.py", "end", "--note", "Anna won"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        assert not (Path(self.cwd) / "state").exists()
        r = run(["setup.py"], self.cwd, stdin=SETUP_ANSWERS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["generation"], 1)
        self.assertEqual(len(list((Path(self.cwd) / "games").iterdir())), 2)

    def test_alias_added_and_usable(self):
        r = run(["session.py", "alias", "Felix", "az"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        run(["apply.py", "res", "az", "mc", "+5"], self.cwd)
        self.assertEqual(self.game()["opponents"]["Felix"]["resources"]["mc"], 5)


if __name__ == "__main__":
    unittest.main()


class TestObserveCLI(CLITest):
    def test_observe_full_mat_snapshot(self):
        r = run(["apply.py", "observe", "green", "--tr", "24", "--mc", "12",
                 "--steel", "3", "--plants", "5", "--prod-mc", "4"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        anna = self.game()["opponents"]["Anna"]
        self.assertEqual(anna["tr"], 24)
        self.assertEqual(anna["resources"]["mc"], 12)
        self.assertEqual(anna["production"]["mc"], 4)
        self.assertFalse(anna["estimated"])
        self.assertIn("drift", r.stdout.lower())


class TestPlaceCardFlagCLI(CLITest):
    """The --card flag must hang off `place`, not `spaces` — the first
    patch attached it to the wrong subparser and `apply.py place ... --card`
    died on 'unrecognized arguments'."""

    def test_place_accepts_card_flag_for_ocean_area_special(self):
        r = run(["apply.py", "place", "Anna", "special", "13",
                 "--card", "Mohole Area"], self.cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.game()["board"]["13"]["tile"], "moholearea")

    def test_place_without_card_still_refuses_ocean_area(self):
        r = run(["apply.py", "place", "Anna", "special", "13"], self.cwd)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ocean-reserved", r.stderr)
