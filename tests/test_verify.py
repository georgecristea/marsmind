"""verify.py: one-command tracker-vs-live-app reconciliation. Done by
hand this is ad-hoc python snippets and sign-error corrections-of-
corrections; this makes it a single audited command."""
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Store, Engine, EventError
from test_new_game import SETUP
import appapi  # noqa: F401  (patch target: the one HTTP path)
import verify

FIX = Path(__file__).resolve().parent / "fixtures" / "endgame-5p"

# 5-player table matching the endgame-5p players_end.json fixture.
FIXTURE_SETUP = {
    "playerCount": 5,
    "players": [
        {"name": "Zed", "color": "red", "isMe": True},
        {"name": "Ana", "color": "green", "isMe": False},
        {"name": "Ben", "color": "yellow", "isMe": False},
        {"name": "Carl", "color": "blue", "isMe": False},
        {"name": "Diana", "color": "black", "isMe": False},
    ],
    "expansions": ["base", "corporateEra"], "map": "tharsis", "draft": False,
    "houseRules": [], "seatingOrder": ["Zed", "Ana", "Ben", "Carl", "Diana"],
    "firstPlayerGen1": "Zed",
}


def fixture_urlopen(players=None, game=None):
    """Fake urllib.request.urlopen: /api/player?id=p-<name> → the real
    captured payload shape ({thisPlayer, game, players}) built from the
    captured fixtures, so the REAL _fetch_app parsing path is exercised."""
    players = players or json.loads((FIX / "players_end.json").read_text())
    game = game or json.loads((FIX / "globals_end.json").read_text())
    by_pid = {f"p-{p['name']}": p for p in players}

    def urlopen(url, timeout=None):
        pid = url.split("id=")[1]
        return io.BytesIO(json.dumps(
            {"thisPlayer": by_pid[pid], "game": game, "players": players}).encode())
    return urlopen


FAKE_APP = {
    "Zed": {"mc": 30, "tr": 25, "steel": 1, "titanium": 0, "plants": 2,
               "energy": 0, "heat": 3,
               "prod": {"mc": 5, "steel": 0, "titanium": 0, "plants": 1,
                        "energy": 1, "heat": 0}},
    "Anna": {"mc": 12, "tr": 22, "steel": 0, "titanium": 4, "plants": 0,
             "energy": 1, "heat": 0,
             "prod": {"mc": 3, "steel": 0, "titanium": 1, "plants": 0,
                      "energy": 1, "heat": 1}},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, name):
        return FAKE_APP[name]


class TestDiff(Base):
    def test_reports_every_field_drift(self):
        # tracker starts: Zed mc 20 tr 20, all prod 0
        rows = verify.diff(self.eng, ["Zed", "Anna"], fetch=self.fetch)
        g = next(r for r in rows if r["player"] == "Zed")
        self.assertEqual(g["drift"]["mc"], (0, 30))
        self.assertEqual(g["drift"]["tr"], (20, 25))
        self.assertEqual(g["drift"]["prod.mc"], (0, 5))

    def test_exact_match_has_empty_drift(self):
        self.eng.res("Zed", "mc", +30)
        self.eng.tr("Zed", +5)
        self.eng.res("Zed", "steel", +1)
        self.eng.res("Zed", "plants", +2)
        self.eng.res("Zed", "heat", +3)
        self.eng.prod("Zed", "mc", +5)
        self.eng.prod("Zed", "plants", +1)
        self.eng.prod("Zed", "energy", +1)
        rows = verify.diff(self.eng, ["Zed"], fetch=self.fetch)
        self.assertEqual(rows[0]["drift"], {})


class TestSync(Base):
    def test_sync_applies_all_drifts_through_engine(self):
        verify.sync(self.eng, ["Zed", "Anna"], fetch=self.fetch)
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 30)
        self.assertEqual(g["me"]["tr"], 25)
        self.assertEqual(g["me"]["production"]["mc"], 5)
        self.assertEqual(g["opponents"]["Anna"]["resources"]["titanium"], 4)
        self.assertEqual(g["opponents"]["Anna"]["tr"], 22)
        self.assertEqual(g["opponents"]["Anna"]["production"]["heat"], 1)

    def test_sync_is_idempotent(self):
        verify.sync(self.eng, ["Zed"], fetch=self.fetch)
        rows = verify.diff(self.eng, ["Zed"], fetch=self.fetch)
        self.assertEqual(rows[0]["drift"], {})


class TestFetchApp(unittest.TestCase):
    """_fetch_app must read the REAL API field names. A mocked
    fetch() (as used above) can't catch a wrong key — it always reads
    plantProduction (singular, the app's real field) as 0 via a
    misnamed 'plantsProduction' .get() fallback, silently zeroing
    every player's tracked plant production on every --sync."""

    def test_reads_plant_production_field(self):
        payload = {"thisPlayer": {
            "megacredits": 30, "steel": 1, "titanium": 0, "plants": 2,
            "energy": 0, "heat": 3, "terraformRating": 25,
            "megacreditProduction": 5, "steelProduction": 0,
            "titaniumProduction": 0, "plantProduction": 1,
            "energyProduction": 1, "heatProduction": 0,
        }}
        fake_response = io.BytesIO(json.dumps(payload).encode())
        with patch("appapi.urllib.request.urlopen", return_value=fake_response):
            out = verify._fetch_app("http://localhost:8080", "pid")
        self.assertEqual(out["prod"]["plants"], 1)

    def test_reads_globals_and_public_table_from_real_payload(self):
        """B + C: the same /api/player response carries game.temperature/
        oxygenLevel/oceans, milestones/awards and every player's tableau."""
        raw = (FIX / "me_end.json").read_bytes()
        with patch("appapi.urllib.request.urlopen",
                   return_value=io.BytesIO(raw)):
            out = verify._fetch_app("http://localhost:8080", "pid")
        self.assertEqual(out["globals"],
                         {"temperature": 8, "oxygen": 14, "oceans": 9})
        self.assertEqual(out["tableau"]["Ben"][0], "Callisto Penal Mines")  # corp skipped
        self.assertNotIn("CrediCor", out["tableau"]["Ben"])
        self.assertEqual(out["milestones"]["Mayor"], "Carl")
        self.assertEqual(out["awards"]["Landlord"], "Ben")
        self.assertNotIn("Builder", out["milestones"])  # unclaimed → absent


class FixtureBase(unittest.TestCase):
    """Tracker for the fixture table + fetch through the real parsing path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(FIXTURE_SETUP)
        self.eng = Engine(self.store)
        self.names = [p["name"] for p in FIXTURE_SETUP["players"]]
        self.patcher = patch("appapi.urllib.request.urlopen",
                             side_effect=fixture_urlopen())
        self.patcher.start()
        self.fetch = lambda name: verify._fetch_app("http://x", f"p-{name}")

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def log(self):
        return self.store.log_path.read_text()


class TestGlobalsSync(FixtureBase):
    def test_globals_row_first_with_drift(self):
        rows = verify.diff(self.eng, self.names, fetch=self.fetch)
        self.assertEqual(rows[0]["player"], "globals")
        self.assertEqual(rows[0]["drift"]["temperature"], (-30, 8))
        self.assertEqual(rows[0]["drift"]["oxygen"], (0, 14))
        self.assertEqual(rows[0]["drift"]["oceans"], (0, 9))

    def test_sync_adopts_globals_including_downward(self):
        self.eng.sync_global("temperature", 8)
        self.eng.sync_global("oxygen", 14)
        self.eng.sync_global("oceans", 9)
        # phantom raise beyond the app: tracker says more than the app → app wins
        game = json.loads((FIX / "globals_end.json").read_text())
        game["oxygenLevel"] = 12
        self.patcher.stop()
        self.patcher = patch("appapi.urllib.request.urlopen",
                             side_effect=fixture_urlopen(game=game))
        self.patcher.start()
        verify.sync(self.eng, self.names, fetch=self.fetch)
        g = self.store.load_game()["globals"]
        self.assertEqual(g, {"temperature": 8, "oxygen": 12, "oceans": 9})
        self.assertIn("Sync: oxygen = 12%", self.log())

    def test_sync_is_idempotent_for_globals(self):
        verify.sync(self.eng, self.names, fetch=self.fetch)
        rows = verify.diff(self.eng, self.names, fetch=self.fetch)
        self.assertEqual(rows[0]["drift"], {})
        n = self.log().count("Sync: oxygen")
        verify.sync(self.eng, self.names, fetch=self.fetch)
        self.assertEqual(self.log().count("Sync: oxygen"), n)


class TestObservePlay(FixtureBase):
    def test_appends_card_and_one_log_line_without_side_effects(self):
        before = self.store.load_game()["opponents"]["Ben"]
        msg = self.eng.observe_play("Ben", "Ants")
        after = self.store.load_game()["opponents"]["Ben"]
        self.assertEqual([c["name"] for c in after["playedCards"]], ["Ants"])
        self.assertEqual(after["resources"], before["resources"])
        self.assertEqual(after["production"], before["production"])
        self.assertEqual(after["tr"], before["tr"])
        self.assertEqual(self.store.load_game()["globals"]["oxygen"], 0)
        self.assertEqual(msg, "Ben played Ants [observed from app]")
        self.assertEqual(self.log().count("Ben played Ants [observed from app]"), 1)
        self.assertEqual(after["tagCounts"], {"microbe": 1})

    def test_refuses_me_and_duplicates(self):
        with self.assertRaises(EventError):
            self.eng.observe_play("Zed", "Ants")
        self.eng.observe_play("Ben", "Ants")
        with self.assertRaises(EventError):
            self.eng.observe_play("Ben", "Ants")


class TestTableauDiff(FixtureBase):
    BEN = ["Callisto Penal Mines", "Sponsors", "Phobos Space Haven",
           "Natural Preserve", "Import of Advanced GHG", "Asteroid",
           "Lagrange Observatory", "Titanium Mine", "Ants", "Energy Saving",
           "Fuel Factory"]

    def test_diff_lists_missing_cards_milestones_awards(self):
        self.eng.play("Ben", "Sponsors")
        self.eng.observe_play("Ben", "Ants")
        rows = {r["player"]: r["drift"] for r in
                verify.diff(self.eng, self.names, fetch=self.fetch)}
        self.assertEqual(rows["Ben"]["tableau"],
                         [c for c in self.BEN if c not in ("Sponsors", "Ants")])
        self.assertEqual(rows["Ben"]["award"], ["Landlord"])
        self.assertEqual(rows["Carl"]["milestone"], ["Mayor"])
        self.assertEqual(rows["Diana"]["award"], ["Miner"])
        self.assertNotIn("tableau", rows["Zed"])   # isMe never diffed
        self.assertNotIn("milestone", rows["Zed"])

    def test_sync_adopts_once_and_is_idempotent(self):
        self.eng.play("Ben", "Sponsors")
        verify.sync(self.eng, self.names, fetch=self.fetch)
        g = self.store.load_game()
        self.assertEqual([c["name"] for c in g["opponents"]["Ben"]["playedCards"]],
                         ["Sponsors"] + [c for c in self.BEN if c != "Sponsors"])
        self.assertEqual(g["me"]["playedCards"], [])
        self.assertEqual(g["milestonesClaimed"], {"Mayor": "Carl"})
        self.assertEqual(g["awardsFunded"], {"Landlord": "Ben", "Miner": "Diana"})
        # numbers come from the app, not from the observed plays
        self.assertEqual(g["opponents"]["Ben"]["resources"]["mc"], 240)
        self.assertEqual(g["opponents"]["Ben"]["tr"], 31)
        self.assertEqual(self.log().count("Ben played Ants [observed from app]"), 1)
        # second run: byte-exact, nothing re-added, nothing re-logged
        rows = verify.diff(self.eng, self.names, fetch=self.fetch)
        self.assertTrue(all(r["drift"] == {} for r in rows), rows)
        n = len(self.log())
        verify.sync(self.eng, self.names, fetch=self.fetch)
        self.assertEqual(len(self.log()), n)
        self.assertEqual(len(self.store.load_game()["opponents"]["Ben"]["playedCards"]), 11)

    def test_unknown_card_is_skipped_with_warning(self):
        players = json.loads((FIX / "players_end.json").read_text())
        ben = next(p for p in players if p["name"] == "Ben")
        ben["tableau"].append({"name": "Not A Card", "resources": 0})
        self.patcher.stop()
        self.patcher = patch("appapi.urllib.request.urlopen",
                             side_effect=fixture_urlopen(players=players))
        self.patcher.start()
        err = io.StringIO()
        with patch("sys.stderr", err):
            rows = {r["player"]: r["drift"] for r in
                    verify.diff(self.eng, self.names, fetch=self.fetch)}
        self.assertNotIn("Not A Card", rows["Ben"]["tableau"])
        self.assertIn("Not A Card", err.getvalue())


class TestGenerationGuard(Base):
    """P8 #17: `--sync` run between the generation-closing pass and
    `listen.py once` adopted the app's POST-production values; produce.py
    then added the income a second time (an opponent's simulated MC ran to
    100 against the app's 53). When the app's generation is AHEAD of the
    tracker's, resource adoption is refused — globals and tiles still sync."""

    def fetch_at(self, gen, phase="action", globals_=None):
        def fetch(name):
            app = dict(FAKE_APP[name], generation=gen, phase=phase)
            if globals_:
                app["globals"] = globals_
            return app
        return fetch

    def test_sync_refuses_resources_when_the_app_is_a_generation_ahead(self):
        out = verify.sync(self.eng, ["Zed", "Anna"], fetch=self.fetch_at(2))
        self.assertTrue(any("run listen.py once first (the app is at "
                            "generation 2, the tracker at 1)" in m for m in out),
                        out)
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 0)        # not adopted
        self.assertEqual(g["me"]["tr"], 20)
        self.assertEqual(g["opponents"]["Anna"]["resources"]["titanium"], 0)

    def test_globals_still_sync_when_the_app_is_ahead(self):
        fetch = self.fetch_at(2, globals_={"temperature": -20, "oxygen": 3,
                                           "oceans": 2})
        verify.sync(self.eng, ["Zed", "Anna"], fetch=fetch)
        g = self.store.load_game()
        self.assertEqual(g["globals"]["oxygen"], 3)            # adopted
        self.assertEqual(g["me"]["resources"]["mc"], 0)        # still refused

    def test_same_generation_syncs_normally(self):
        verify.sync(self.eng, ["Zed", "Anna"], fetch=self.fetch_at(1))
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 30)
        self.assertEqual(g["opponents"]["Anna"]["tr"], 22)

    def test_finished_game_is_exempt(self):
        """phase 'end': no further production can be added, and end-game
        reconciliation before scoring must keep working."""
        verify.sync(self.eng, ["Zed"], fetch=self.fetch_at(9, phase="end"))
        self.assertEqual(self.store.load_game()["me"]["resources"]["mc"], 30)

    def test_guard_message_is_none_when_not_ahead(self):
        self.assertIsNone(verify.generation_guard(
            self.eng, self.fetch_at(1), ["Zed"]))


class TestFetchAppSpaces(unittest.TestCase):
    """_fetch_app must carry the app's tile LOCATIONS (game.spaces) —
    id, tileType enum, owner color — resolved to tracker vocabulary."""

    def test_parses_tile_type_and_owner_from_the_real_payload(self):
        raw = (FIX / "me_end.json").read_bytes()
        with patch("appapi.urllib.request.urlopen",
                   return_value=io.BytesIO(raw)):
            out = verify._fetch_app("http://localhost:8080", "pid")
        sp = out["spaces"]
        self.assertEqual(sp["03"], {"tile": "city", "player": "Carl"})   # blue
        self.assertEqual(sp["04"], {"tile": "ocean", "player": None})    # nobody
        self.assertEqual(sp["05"], {"tile": "greenery", "player": "Carl"})
        self.assertNotIn("01", sp)          # colony (off-Mars) spaces skipped
        self.assertNotIn("02", sp)
        self.assertEqual(out["generation"], 17)
        self.assertEqual(out["phase"], "end")

    def test_special_tile_names_match_the_tracker_vocabulary(self):
        view = {"thisPlayer": {"megacredits": 0, "steel": 0, "titanium": 0,
                               "plants": 0, "energy": 0, "heat": 0,
                               "terraformRating": 20, "megacreditProduction": 0,
                               "steelProduction": 0, "titaniumProduction": 0,
                               "plantProduction": 0, "energyProduction": 0,
                               "heatProduction": 0},
                "players": [{"name": "Ben", "color": "yellow", "tableau": []}],
                "game": {"spaces": [
                    {"id": "11", "spaceType": "land", "tileType": 11,
                     "color": "yellow"},
                    {"id": "12", "spaceType": "land", "tileType": 6,
                     "color": "yellow"}]}}
        with patch("appapi.urllib.request.urlopen",
                   return_value=io.BytesIO(json.dumps(view).encode())):
            out = verify._fetch_app("http://x", "pid")
        self.assertEqual(out["spaces"]["11"]["tile"], "naturalpreserve")
        self.assertEqual(out["spaces"]["12"]["tile"], "industrialcenter")


class TestFromView(unittest.TestCase):
    """P9: ONE /api/player payload is the whole public table. players[]
    carries every seat's mat with the same field names as thisPlayer, so
    the listener syncs five players with one HTTP read."""

    def view(self) -> dict:
        return json.loads((FIX / "me_end.json").read_text())

    def test_every_player_gets_a_mat(self):
        table = verify.from_view(self.view())
        self.assertEqual(sorted(table), ["Ana", "Ben", "Carl", "Diana", "Zed"])
        self.assertEqual(table["Ana"]["mc"], 32)
        self.assertEqual(table["Ana"]["tr"], 30)
        self.assertEqual(table["Ana"]["prod"]["plants"], 1)

    def test_the_table_wide_blocks_ride_on_every_row(self):
        table = verify.from_view(self.view())
        for name in ("Zed", "Ben"):
            self.assertEqual(table[name]["globals"]["oxygen"], 14)
            self.assertEqual(table[name]["generation"], 17)
            self.assertIn("03", table[name]["spaces"])

    def test_only_my_row_carries_the_hand(self):
        table = verify.from_view(self.view())
        self.assertIn("Solar Power", table["Zed"]["hand"])
        self.assertNotIn("hand", table["Ben"])

    def test_card_resources_are_parsed_per_player(self):
        table = verify.from_view(self.view())
        self.assertEqual(table["Zed"]["cardResources"]["Zed"]["Tardigrades"], 14)
        self.assertEqual(table["Zed"]["cardResources"]["Ben"]["Ants"], 1)

    def test_a_stub_player_entry_is_skipped_not_crashed(self):
        view = {"thisPlayer": {"name": "Zed", "megacredits": 1, "steel": 0,
                               "titanium": 0, "plants": 0, "energy": 0,
                               "heat": 0, "terraformRating": 20,
                               "megacreditProduction": 0, "steelProduction": 0,
                               "titaniumProduction": 0, "plantProduction": 0,
                               "energyProduction": 0, "heatProduction": 0},
                "players": [{"name": "Anna", "color": "green"}]}
        self.assertEqual(list(verify.from_view(view)), ["Zed"])


class TestSyncTable(FixtureBase):
    """`sync_table` is the FULL adoption the app modes run on: mats,
    my hand and tableau, everyone's card resources, globals and tiles."""

    def table(self) -> dict:
        return verify.from_view(json.loads((FIX / "me_end.json").read_text()))

    def sync(self):
        t = self.table()
        names = [n for n in self.names if n in t]
        err = io.StringIO()
        with patch("sys.stderr", err):
            return verify.sync_table(self.eng, names, lambda n: t[n])

    def test_adopts_my_mat_hand_and_tableau(self):
        self.sync()
        me = self.store.load_game()["me"]
        self.assertEqual(me["tr"], 40)
        self.assertIn("Solar Power", me["hand"])
        played = [c["name"] for c in me["playedCards"]]
        self.assertIn("Tardigrades", played)
        self.assertIn("Predators", played)

    def test_my_tableau_is_bookkeeping_only(self):
        """The app already applied those cards' effects and the numeric
        adoption took the result — replaying them would double-count."""
        before = self.store.load_game()["globals"]["oxygen"]
        self.sync()
        g = self.store.load_game()
        self.assertEqual(g["globals"]["oxygen"], 14)       # the app's value
        self.assertNotEqual(before, 14)
        self.assertEqual(g["me"]["resources"]["mc"], 46)   # the app's value

    def test_card_resources_are_adopted_for_me_and_opponents(self):
        self.sync()
        g = self.store.load_game()
        self.assertEqual(g["me"]["cardResources"]["Tardigrades"], 14)
        self.assertEqual(g["me"]["cardResources"]["Birds"], 3)
        self.assertEqual(g["opponents"]["Ben"]["cardResources"]["Ants"], 1)

    def test_a_counter_the_app_shows_as_zero_is_removed(self):
        self.sync()
        game = self.store.load_game()
        game["me"]["cardResources"]["Birds"] = 9      # tracker drifted upward
        Store._write_json(self.store.game_path, game)
        parts = self.sync()
        self.assertEqual(
            self.store.load_game()["me"]["cardResources"]["Birds"], 3)
        self.assertTrue(any("Birds 9→3" in p for p in parts), parts)

    def test_opponent_public_mats_and_tiles_are_adopted(self):
        self.sync()
        g = self.store.load_game()
        self.assertEqual(g["opponents"]["Ben"]["resources"]["mc"], 240)
        self.assertEqual(g["board"]["03"], {"tile": "city", "player": "Carl"})
        self.assertEqual(g["opponents"]["Carl"]["tiles"]["cities"],
                         verify.board_counts(g, "Carl")["cities"])

    def test_is_idempotent(self):
        self.sync()
        parts = self.sync()
        self.assertEqual(parts, [], parts)

    def test_the_generation_guard_still_blocks_resource_values(self):
        t = self.table()
        for row in t.values():
            row["phase"] = "action"          # not the exempt end-of-game
            row["generation"] = 99
        names = [n for n in self.names if n in t]
        err = io.StringIO()
        with patch("sys.stderr", err):
            parts = verify.sync_table(self.eng, names, lambda n: t[n])
        g = self.store.load_game()
        self.assertEqual(g["me"]["resources"]["mc"], 0)      # NOT adopted
        self.assertEqual(g["opponents"]["Ben"]["resources"]["mc"], 0)
        self.assertEqual(g["globals"]["oxygen"], 14)         # globals still sync
        self.assertIn("Solar Power", g["me"]["hand"])        # hand too
        self.assertTrue(any(p.startswith("⚠") for p in parts), parts)


class TestTileLocationDrift(Base):
    """P8 #13: `apply.py spaces ocean` offered hex 33 as free while the app
    had an opponent's greenery there — verify.py reconciled tile COUNTERS
    only, so six misplaced greeneries were invisible all game."""

    def app(self, **spaces):
        return {sid: {"tile": t, "player": p} for sid, (t, p) in spaces.items()}

    def test_tile_the_app_has_and_the_tracker_lacks(self):
        rows = verify.location_drift(self.eng, self.app(**{"33": ("greenery", "Anna")}))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["space"], "33")
        self.assertEqual(rows[0]["kind"], "missing")
        self.assertEqual(rows[0]["app"], {"tile": "greenery", "player": "Anna"})
        self.assertIsNone(rows[0]["tracker"])

    def test_tile_the_tracker_has_and_the_app_lacks(self):
        self.eng.place("Anna", "greenery", "40")
        rows = verify.location_drift(self.eng, {})
        self.assertEqual(rows[0]["kind"], "phantom")
        self.assertEqual(rows[0]["space"], "40")

    def test_same_hex_different_owner_or_tile(self):
        self.eng.place("Anna", "greenery", "08")
        rows = verify.location_drift(
            self.eng, self.app(**{"08": ("greenery", "Zed")}))
        self.assertEqual(rows[0]["kind"], "mismatch")
        rows = verify.location_drift(
            self.eng, self.app(**{"08": ("city", "Anna")}))
        self.assertEqual(rows[0]["kind"], "mismatch")

    def test_matching_board_has_no_rows(self):
        self.eng.place("Anna", "greenery", "08")
        self.assertEqual(
            verify.location_drift(self.eng,
                                  self.app(**{"08": ("greenery", "Anna")})), [])

    def test_ocean_owner_is_not_a_mismatch(self):
        """The app gives oceans no color; the tracker records who placed
        one. Same hex + same tile = agreement."""
        self.eng.place("Anna", "ocean", "04")
        self.assertEqual(
            verify.location_drift(self.eng,
                                  self.app(**{"04": ("ocean", None)})), [])

    def test_lines_print_one_tile_location_row_each(self):
        self.eng.place("Anna", "greenery", "40")
        rows = verify.location_drift(self.eng, self.app(**{"33": ("greenery", "Anna")}))
        lines = verify.location_lines(rows)
        self.assertTrue(all(line.strip().startswith("TILE LOCATION")
                            for line in lines), lines)
        self.assertTrue(any("33" in line and "Anna greenery" in line
                            for line in lines), lines)

    def test_sync_moves_the_entry_to_the_app_location(self):
        self.eng.place("Anna", "greenery", "40")        # recorded on the wrong hex
        out = verify.sync_locations(self.eng,
                                    self.app(**{"33": ("greenery", "Anna")}))
        board = self.store.load_game()["board"]
        self.assertEqual(board["33"], {"tile": "greenery", "player": "Anna"})
        self.assertNotIn("40", board)
        self.assertTrue(any("40" in m and "33" in m for m in out), out)
        self.assertIn("TILE LOCATION", self.log())
        self.assertEqual(verify.location_drift(
            self.eng, self.app(**{"33": ("greenery", "Anna")})), [])

    def test_sync_adds_a_tile_the_tracker_never_recorded(self):
        verify.sync_locations(self.eng, self.app(**{"33": ("greenery", "Ben")}))
        self.assertEqual(self.store.load_game()["board"]["33"],
                         {"tile": "greenery", "player": "Ben"})

    def test_sync_removes_a_phantom_and_fixes_an_owner(self):
        self.eng.place("Anna", "greenery", "40")
        self.eng.place("Anna", "city", "08")
        verify.sync_locations(self.eng, self.app(**{"08": ("city", "Zed")}))
        board = self.store.load_game()["board"]
        self.assertNotIn("40", board)
        self.assertEqual(board["08"], {"tile": "city", "player": "Zed"})

    def log(self):
        return self.store.log_path.read_text()


if __name__ == "__main__":
    unittest.main()
