"""Eval ledger: player-count tracking + automatic process metrics.

Player count was previously buried in free-text notes only, so a 5p
game would silently contaminate the 3p per-model win-rate aggregate.
record() must capture it (auto from setup.json, override via --players)
and report() must never mix player counts in one aggregate row.

W2-A item 3: record() also stores a "shape" object computed from the
closed game folder via shape.compute() — cards bought per generation,
MC production vs the table median, VP slope, the repeatable-source
inventory, plus generations played. Numbers only, no flags, no
judgment. --no-shape is the escape hatch for corrupt folders.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import evalprotocol as ev


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = self.root / "evals.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _make_game(self, name: str, player_count: int, me: str = "Diana"):
        game_dir = self.root / "games" / name
        game_dir.mkdir(parents=True)
        players = [{"name": me, "isMe": True}]
        players += [{"name": f"P{i}", "isMe": False}
                    for i in range(player_count - 1)]
        (game_dir / "setup.json").write_text(
            json.dumps({"playerCount": player_count, "players": players}))
        return game_dir


class TestPlayersAutoDerived(Base):
    def test_players_pulled_from_setup_json(self):
        g = self._make_game("five-seat", 5)
        entry = ev.record(self.ledger, g, "Diana", 10, "sonnet-5", shape=False)
        self.assertEqual(entry["players"], 5)

    def test_players_defaults_none_without_setup(self):
        missing = self.root / "games" / "ghost"
        entry = ev.record(self.ledger, missing, "Diana", 10, "sonnet-5",
                          shape=False)
        self.assertIsNone(entry["players"])

    def test_explicit_players_overrides_setup_json(self):
        g = self._make_game("three-seat", 3)
        entry = ev.record(self.ledger, g, "Diana", 10, "sonnet-5", players=4,
                          shape=False)
        self.assertEqual(entry["players"], 4)


class TestReportSeparatesPlayerCounts(Base):
    def test_report_breaks_out_rows_by_model_and_players(self):
        three = self._make_game("three-seat", 3)
        five = self._make_game("five-seat", 5)
        ev.record(self.ledger, three, "Diana", 7, "sonnet-5", shape=False)
        ev.record(self.ledger, five, "Diana", -3, "sonnet-5", shape=False)
        out = ev.report(self.ledger)
        # two distinct rows for the same model, one per player count —
        # never averaged together into a single sonnet-5 row.
        self.assertIn("3p", out)
        self.assertIn("5p", out)
        lines = [l for l in out.splitlines() if "sonnet-5" in l]
        self.assertEqual(len(lines), 2)


class TestLedgerPath(unittest.TestCase):
    """The ledger is the player's data: it defaults to private/ (git-ignored);
    the env var / --ledger flag override it; --help documents the record."""

    def test_default_ledger_lives_under_private(self):
        root = Path(ev.__file__).resolve().parent.parent
        self.assertEqual(ev.DEFAULT_FILE, root / "private" / "evals.jsonl")

    def test_env_var_overrides_default(self):
        import os
        old = os.environ.get("PHOBOS_EVALS_LEDGER")
        os.environ["PHOBOS_EVALS_LEDGER"] = "/x/y/ledger.jsonl"
        try:
            self.assertEqual(ev.default_ledger(), Path("/x/y/ledger.jsonl"))
        finally:
            if old is None:
                del os.environ["PHOBOS_EVALS_LEDGER"]
            else:
                os.environ["PHOBOS_EVALS_LEDGER"] = old
        self.assertEqual(ev.default_ledger(), ev.DEFAULT_FILE)

    def test_ledger_flag_creates_parents(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "deep" / "er" / "evals.jsonl"
            r = subprocess.run(
                [sys.executable, str(ev.__file__), "--ledger", str(ledger),
                 "record", "--game", tmp, "--winner", "Diana",
                 "--margin", "3", "--model", "m", "--no-shape"],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(ledger.exists())
            self.assertEqual(json.loads(ledger.read_text())["margin"], 3)

    def test_help_documents_record_format(self):
        import subprocess
        r = subprocess.run([sys.executable, str(ev.__file__), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        for key in ("date", "winner", "me", "players", "margin", "model",
                    "bots", "notes", "private/evals.jsonl"):
            self.assertIn(key, r.stdout)


class TestShapeMetricsInLedger(Base):
    """W2-A item 3: process metrics from the closed game folder, stored
    as a "shape" object in the ledger row. Numbers only — no flags."""

    def _real_game(self, name="real-game"):
        """A minimal but complete game folder: Store.init + one research
        event so cards-bought-per-gen has data."""
        from tmlib import Store, Engine
        game_dir = self.root / "games" / name
        setup = {
            "playerCount": 3,
            "players": [
                {"name": "Zed", "color": "red", "isMe": True, "aliases": []},
                {"name": "Anna", "color": "green", "isMe": False, "aliases": []},
                {"name": "Ben", "color": "blue", "isMe": False, "aliases": []},
            ],
            "expansions": ["base", "corporateEra"],
            "map": "tharsis", "draft": False, "houseRules": [],
            "seatingOrder": ["Zed", "Anna", "Ben"],
            "firstPlayerGen1": "Zed",
        }
        Store(self.root, state_dir=game_dir).init(setup)
        eng = Engine(Store(self.root, state_dir=game_dir))
        eng.corp("Zed", "CrediCor", mc=57)
        eng.dealt(["Comet", "Birds", "Insects", "Moss"],
                  kept=["Comet", "Birds"])
        eng.research("Anna", kept=1)
        eng.research("Ben", kept=2)
        eng.prod("Zed", "mc", +3)
        return game_dir

    def test_record_stores_shape_numbers(self):
        g = self._real_game()
        entry = ev.record(self.ledger, g, "Zed", 5, "fable-5")
        s = entry["shape"]
        self.assertEqual(s["gens"], 1)
        self.assertEqual(s["cardsBought"]["mine"][1], 2)
        self.assertEqual(s["mcProd"]["mine"], 3)
        self.assertIn("vpSlope", s)
        self.assertIsInstance(s["repeatableSources"], list)
        self.assertNotIn("flags", s)                  # numbers, no judgment
        # …and the row on disk carries it too
        row = json.loads(self.ledger.read_text().splitlines()[-1])
        self.assertEqual(row["shape"]["mcProd"]["mine"], 3)

    def test_no_shape_records_without_metrics(self):
        g = self._real_game("skipped")
        entry = ev.record(self.ledger, g, "Zed", 5, "fable-5", shape=False)
        self.assertIsNone(entry["shape"])

    def test_corrupt_folder_refuses_and_names_the_escape_hatch(self):
        broken = self.root / "games" / "broken"
        broken.mkdir(parents=True)
        with self.assertRaises(ValueError) as ctx:
            ev.record(self.ledger, broken, "Zed", 5, "fable-5")
        self.assertIn("--no-shape", str(ctx.exception))
        self.assertFalse(self.ledger.exists())        # nothing half-written

    def test_cli_no_shape_flag(self):
        import subprocess
        g = self._real_game("cli-game")
        r = subprocess.run(
            [sys.executable, str(ev.__file__), "--ledger", str(self.ledger),
             "record", "--game", str(g), "--winner", "Zed", "--margin", "5",
             "--model", "m"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        row = json.loads(self.ledger.read_text().splitlines()[-1])
        self.assertEqual(row["shape"]["gens"], 1)

    def test_cli_corrupt_folder_errors_cleanly(self):
        import subprocess
        broken = self.root / "games" / "cli-broken"
        broken.mkdir(parents=True)
        r = subprocess.run(
            [sys.executable, str(ev.__file__), "--ledger", str(self.ledger),
             "record", "--game", str(broken), "--winner", "Zed",
             "--margin", "5", "--model", "m"],
            capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--no-shape", r.stderr)
