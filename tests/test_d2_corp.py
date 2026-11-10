"""D2 (Codex H2) — corporation IDENTITY on the listener's table sync.

The initial app sync adopted hands, resources, production and public
tableaus but left every player's `corporation` null, so operators ran
`apply.py corp` — the PHYSICAL-mode verb — which applied the starting
assets a second time (games/2026-08-29-game2/log.md lines 9-19: "Ares is
CrediCor (start 0 MC → 45)" then "(start 57 MC → 102)"; PhoboLog's
"+10 titanium" then a "-10 TITANIUM" compensation).

The sync reads tableau entry zero as the corporation and sets the
identity ONLY: the starting assets are already inside the adopted
resources. Me and every opponent alike; a second sync is a no-op. Only a
name cards/db.json knows as a corporation counts (a stub view's
placeholder or a project card in slot zero is skipped).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import listen                                   # noqa: E402
from appapi import AppClient                    # noqa: E402
from test_appapi import CannedServer            # noqa: E402
from tmlib import Store                         # noqa: E402

ME, ME_PID = "Codex", "p-codex"
HAND = ["Acquired Company", "Industrial Microbes", "Building Industries",
        "Standard Technology"]


def _setup(url: str = "http://fake") -> dict:
    return {"playerCount": 3,
            "players": [{"name": ME, "color": "green", "isMe": True,
                         "aliases": [], "playerId": ME_PID},
                        {"name": "Ares", "color": "red", "isMe": False, "aliases": []},
                        {"name": "Hellas", "color": "blue", "isMe": False, "aliases": []}],
            "expansions": ["base", "corporateEra"], "map": "tharsis",
            "draft": False, "houseRules": [],
            "seatingOrder": [ME, "Ares", "Hellas"], "firstPlayerGen1": ME,
            "gameMode": "app-online", "appUrl": url}


def _mat(name, color, corp, mc, plants=0, titanium=0, plant_prod=0):
    return {"name": name, "color": color, "megacredits": mc, "steel": 0,
            "titanium": titanium, "plants": plants, "energy": 0, "heat": 0,
            "terraformRating": 20, "megacreditProduction": 0,
            "steelProduction": 0, "titaniumProduction": 0,
            "plantProduction": plant_prod, "energyProduction": 0,
            "heatProduction": 0,
            "tableau": [{"name": corp, "resources": 0}]}


def codex_view(corp_names=("Ecoline", "CrediCor", "PhoboLog")) -> dict:
    """The /api/player payload right after the Codex game's corp choice
    (log lines 6-8): the STARTING ASSETS are already in the mats."""
    me, ares, hellas = corp_names
    players = [_mat(ME, "green", me, 24, plants=3, plant_prod=2),
               _mat("Ares", "red", ares, 45),
               _mat("Hellas", "blue", hellas, 14, titanium=10)]
    return {"thisPlayer": dict(players[0]),
            "cardsInHand": [{"name": c} for c in HAND],
            "game": {"generation": 1, "gameAge": 3, "undoCount": 0,
                     "phase": "action", "temperature": -30, "oxygenLevel": 0,
                     "oceans": 0, "milestones": [], "awards": []},
            "players": players}


class StaticClient:
    """Duck-typed AppClient: one frozen player view."""

    def __init__(self, view: dict):
        self.view = view
        self.calls = 0

    def player(self, pid: str) -> dict:
        self.calls += 1
        return json.loads(json.dumps(self.view))


class D2Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root, state_dir=root / "state")
        self.store.init(_setup())

    def tearDown(self):
        self.tmp.cleanup()

    def listener(self, view=None) -> "listen.Listener":
        return listen.Listener(self.store, StaticClient(view or codex_view()), ME_PID)

    def sync(self, L=None) -> tuple[str, str]:
        L = L or self.listener()
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            summary = L.sync_table()
        return summary, buf.getvalue()

    def game(self) -> dict:
        return self.store.load_game()

    def pool(self, name: str) -> dict:
        g = self.game()
        return g["me"] if g["me"]["name"] == name else g["opponents"][name]

    def log(self) -> str:
        return self.store.log_path.read_text()


class TestCorporationIdentity(D2Base):
    def test_initial_sync_sets_every_players_corporation(self):
        self.assertIsNone(self.game()["me"]["corporation"])
        summary, _ = self.sync()
        self.assertEqual(self.pool(ME)["corporation"], "Ecoline")
        self.assertEqual(self.pool("Ares")["corporation"], "CrediCor")
        self.assertEqual(self.pool("Hellas")["corporation"], "PhoboLog")
        self.assertIn("corporation", summary)
        for name in ("Ecoline", "CrediCor", "PhoboLog"):
            self.assertIn(name, summary)

    def test_identity_only_the_adopted_mats_are_untouched(self):
        # the Codex numbers: assets already inside the app's mats
        self.sync()
        me, ares, hellas = self.pool(ME), self.pool("Ares"), self.pool("Hellas")
        self.assertEqual(me["resources"]["mc"], 24)
        self.assertEqual(me["resources"]["plants"], 3)          # not 6
        self.assertEqual(me["production"]["plants"], 2)         # not 4
        self.assertEqual(ares["resources"]["mc"], 45)           # not 102
        self.assertEqual(hellas["resources"]["mc"], 14)         # not 37
        self.assertEqual(hellas["resources"]["titanium"], 10)   # not 20
        self.assertEqual(me["playedCards"], [])                 # corp ≠ tableau card
        self.assertEqual(sorted(me["hand"]), sorted(HAND))
        log = self.log()
        self.assertNotIn("(start ", log)                        # apply.py corp's wording
        self.assertNotIn("+10 titanium", log)

    def test_second_sync_is_a_noop(self):
        self.sync()
        game1, log1 = self.game(), self.log()
        summary, _ = self.sync()
        self.assertEqual(self.game(), game1)
        self.assertEqual(self.log(), log1)
        self.assertEqual(summary, "exact")

    def test_the_adoption_is_logged_once_per_player(self):
        self.sync()
        self.sync()
        log = self.log()
        for name, corp in ((ME, "Ecoline"), ("Ares", "CrediCor"), ("Hellas", "PhoboLog")):
            hits = [l for l in log.splitlines() if name in l and corp in l]
            self.assertEqual(len(hits), 1, (name, hits))

    def test_a_corporation_already_known_is_left_alone(self):
        # the drain's ingest lands "Codex played Ecoline" BEFORE the sync;
        # the sync must not re-log an identity it already holds
        game = self.game()
        game["me"]["corporation"] = "Ecoline"
        self.store.save_game(game)
        self.sync()
        log = self.log()
        self.assertEqual(self.pool(ME)["corporation"], "Ecoline")
        self.assertEqual(len([l for l in log.splitlines() if "Ecoline" in l]), 0)
        self.assertEqual(self.pool("Ares")["corporation"], "CrediCor")

    def test_a_project_card_in_slot_zero_is_never_a_corporation(self):
        # a stub tableau: a KNOWN non-corporation card is not an identity
        view = codex_view(("Acquired Company", "CrediCor", "PhoboLog"))
        self.sync(self.listener(view))
        self.assertIsNone(self.pool(ME)["corporation"])
        self.assertEqual(self.pool("Ares")["corporation"], "CrediCor")

    def test_a_placeholder_in_slot_zero_is_skipped(self):
        # a fake's stub tableau ("corp"): not a corporation the db knows
        view = codex_view(("corp", "CrediCor", "PhoboLog"))
        self.sync(self.listener(view))
        self.assertIsNone(self.pool(ME)["corporation"])
        self.assertEqual(self.pool("Ares")["corporation"], "CrediCor")

    def test_an_empty_tableau_is_skipped(self):
        view = codex_view()
        view["players"][1]["tableau"] = []
        self.sync(self.listener(view))
        self.assertIsNone(self.pool("Ares")["corporation"])
        self.assertEqual(self.pool("Hellas")["corporation"], "PhoboLog")


class TestSyncMeCli(unittest.TestCase):
    """`listen.py sync-me` — the exact command the Codex operator ran
    before `apply.py corp`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root, state_dir=root / "state")
        self.srv = CannedServer({"/api/player": [(200, lambda p, b: (200, codex_view()))]})
        self.store.init(_setup(self.srv.url))

    def tearDown(self):
        self.srv.close()
        self.tmp.cleanup()

    def test_sync_me_adopts_identity_not_assets(self):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = listen.main(["--state", str(self.store.state_dir), "sync-me"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("table synced:", out)
        game = self.store.load_game()
        self.assertEqual(game["me"]["corporation"], "Ecoline")
        self.assertEqual(game["opponents"]["Ares"]["corporation"], "CrediCor")
        self.assertEqual(game["opponents"]["Hellas"]["corporation"], "PhoboLog")
        self.assertEqual(game["me"]["resources"]["mc"], 24)
        self.assertEqual(game["opponents"]["Ares"]["resources"]["mc"], 45)
        self.assertEqual(game["opponents"]["Hellas"]["resources"]["titanium"], 10)
        # a real AppClient served the view — the import path is the CLI's
        self.assertIsInstance(listen.build(self.store).client, AppClient)


if __name__ == "__main__":
    unittest.main()
