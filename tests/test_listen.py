"""listen.py — lane 1 of the judgment design: the mechanical online
listener. A scripted in-process app (CannedServer from test_appapi with
callable routes) serves /api/waitingfor, /api/game/logs and /api/player
from a slice of the real 4-player WGT export; the listener drains it into
the LIVE engine through the replay machinery and the triage feed."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import applog_parser as P                       # noqa: E402
import listen                                   # noqa: E402
import replay_applog as R                       # noqa: E402
import triage                                   # noqa: E402
from appapi import AppClient, AppUnavailable    # noqa: E402
from test_appapi import CannedServer            # noqa: E402
from tmlib import Engine, Store                 # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "replay-4p-wgt"
LINES = FIXTURE.joinpath("applog.txt").read_text().splitlines()[:80]
PLAYERS = ["Diana", "Anna", "Carl", "Ben"]
ME_PID = "p-diana"
GEN2_AT = LINES.index("Generation 2")            # 0-based index 53


def _setup() -> dict:
    s = json.loads((FIXTURE / "setup.json").read_text())
    s["gameMode"] = "app-online"
    for p in s["players"]:
        if p["isMe"]:
            p["playerId"] = ME_PID
    return s


class FakeApp:
    """The app as the listener sees it: revealed export lines split into
    per-generation views (GameLogs.getLogsForGeneration semantics: the
    'Generation N' marker opens generation N), a gameAge that moves with
    every reveal, an undo counter, a GO/WAIT/REFRESH prompt, and a player
    view that MIRRORS the engine's own state (plus planted `drift`)."""

    def __init__(self, setup: dict, store: Store):
        self.setup, self.store = setup, store
        self.players = setup["players"]
        self.me = next(p for p in self.players if p["isMe"])
        self.colors = {p["name"]: p["color"] for p in self.players}
        self.lines: list[str] = []
        self.game_age = 0
        self.undo = 0
        self.waiting: str | None = None
        self.drift: dict = {}
        self.opp_drift: dict = {}      # {player name: {app field: value}}
        self.gen_override: int | None = None
        self.hand_override: list[str] | None = None
        self.hand_at_top = False       # the real app: view.cardsInHand, not thisPlayer
        self.requests: list[str] = []
        self.srv = CannedServer({"/api/waitingfor": [(200, self.handle)],
                                 "/api/game/logs": [(200, self.handle)],
                                 "/api/player": [(200, self.handle)]})
        self.url = self.srv.url

    def close(self):
        self.srv.close()

    def reveal(self, lines):
        self.lines += list(lines)
        self.game_age += 1

    @property
    def generation(self) -> int:
        if self.gen_override is not None:
            return self.gen_override
        gens = [int(l.split()[1]) for l in self.lines if l.startswith("Generation ")]
        return max(gens) if gens else 1

    def gen_lines(self, g: int) -> list[str]:
        out, found = [], g == 1
        for line in self.lines:
            if line.startswith("Generation "):
                n = int(line.split()[1])
                if n == g:
                    found = True
                elif n == g + 1:
                    break
            if found:
                out.append(line)
        return out

    def entry(self, line: str) -> dict:
        for name, color in self.colors.items():
            if line.startswith(name + " "):
                return {"message": "${0}" + line[len(name):],
                        "data": [{"type": 2, "value": color}]}
        return {"message": line, "data": []}

    def public(self, game: dict, player: dict) -> dict:
        """A players[] entry: the PUBLIC mat the real PlayerModel serves
        for every seat (same field names as thisPlayer). It mirrors the
        tracker unless `opp_drift` plants a divergence."""
        name = player["name"]
        pool = game["me"] if game["me"]["name"] == name else game["opponents"][name]
        r, p = pool["resources"], pool["production"]
        entry = {"name": name, "color": player["color"],
                 "megacredits": r["mc"], "steel": r["steel"],
                 "titanium": r["titanium"], "plants": r["plants"],
                 "energy": r["energy"], "heat": r["heat"],
                 "terraformRating": pool["tr"],
                 "megacreditProduction": p["mc"], "steelProduction": p["steel"],
                 "titaniumProduction": p["titanium"],
                 "plantProduction": p["plants"], "energyProduction": p["energy"],
                 "heatProduction": p["heat"],
                 "tableau": [{"name": "corp", "resources": 0}]}
        entry.update(self.opp_drift.get(name, {}))
        return entry

    def view(self) -> dict:
        game = self.store.load_game()
        me = game["me"]
        res, prod = me["resources"], me["production"]
        tp = {"name": me["name"], "color": self.me["color"],
              "megacredits": res["mc"], "steel": res["steel"],
              "titanium": res["titanium"], "plants": res["plants"],
              "energy": res["energy"], "heat": res["heat"],
              "terraformRating": me["tr"],
              "megacreditProduction": prod["mc"], "steelProduction": prod["steel"],
              "titaniumProduction": prod["titanium"], "plantProduction": prod["plants"],
              "energyProduction": prod["energy"], "heatProduction": prod["heat"],
              "cardsInHand": [{"name": c} for c in
                              (self.hand_override if self.hand_override is not None
                               else me["hand"])]}
        tp.update(self.drift)
        top = {}
        if self.hand_at_top:
            top["cardsInHand"] = tp.pop("cardsInHand")
            tp["cardsInHandNbr"] = len(top["cardsInHand"])
        g = game["globals"]
        return {**top, "thisPlayer": tp,
                "game": {"generation": self.generation, "gameAge": self.game_age,
                         "undoCount": self.undo, "phase": "action",
                         "temperature": g["temperature"], "oxygenLevel": g["oxygen"],
                         "oceans": g["oceans"], "milestones": [], "awards": []},
                "players": [self.public(game, p) for p in self.players],
                "waitingFor": {"title": self.waiting} if self.waiting else None}

    def handle(self, path: str, body: bytes):
        self.requests.append(path)
        u = urllib.parse.urlparse(path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/api/waitingfor":
            if self.waiting:
                return 200, {"result": "GO", "waitingFor": [self.me["color"]]}
            if self.game_age > int(q.get("gameAge", 0)) or self.undo > int(q.get("undoCount", 0)):
                return 200, {"result": "REFRESH", "waitingFor": []}
            return 200, {"result": "WAIT", "waitingFor": []}
        if u.path == "/api/game/logs":
            g = q.get("generation")
            lines = self.gen_lines(int(g)) if g else self.lines[-50:]
            return 200, [self.entry(l) for l in lines]
        if u.path == "/api/player":
            return 200, self.view()
        return 404, "no route"


class ListenBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root, state_dir=root / "state")
        setup = _setup()
        self.app = FakeApp(setup, self.store)
        setup["appUrl"] = self.app.url
        self.store.init(setup)
        self.eng = Engine(self.store)
        self.revealed = 0

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def listener(self) -> "listen.Listener":
        return listen.Listener(self.store, AppClient(self.app.url, timeout=2, retries=1),
                               ME_PID)

    def reveal_to(self, n: int):
        self.app.reveal(LINES[self.revealed:n])
        self.revealed = n

    def drain(self, L=None):
        L = L or self.listener()
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            r = L.drain()
        return r, buf.getvalue()

    def main(self, *argv) -> tuple[int, str]:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = listen.main(["--state", str(self.store.state_dir), *argv])
        return code, buf.getvalue()

    def feed(self) -> list[dict]:
        return triage.read_feed(triage.feed_path(self.store))

    def game(self) -> dict:
        return self.store.load_game()

    def pool(self, name: str) -> dict:
        g = self.game()
        return g["me"] if g["me"]["name"] == name else g["opponents"][name]


# ── once: ingestion ───────────────────────────────────────────────────

class TestOnce(ListenBase):
    def test_once_ingests_exactly_the_new_lines(self):
        self.reveal_to(16)
        r, out = self.drain()
        self.assertTrue(r.new)
        feed = self.feed()
        # "Good luck …" lines are ignored; every other line has one entry
        self.assertEqual([e["raw"] for e in feed],
                         [l for l in LINES[:16] if not l.startswith("Good luck")])
        self.assertEqual([e["line"] for e in feed], [1, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
        self.reveal_to(30)
        r, out = self.drain()
        feed2 = self.feed()
        self.assertEqual(len(feed2), len(feed) + 14)
        self.assertEqual([e["line"] for e in feed2[len(feed):]], list(range(17, 31)))
        self.assertEqual(out.count("logged: "), 14)
        self.assertIn("logged: Carl played Ice Asteroid applied", out)

    def test_feed_entry_schema(self):
        self.reveal_to(16)
        self.drain()
        e = self.feed()[1]
        for key in ("ts", "gen", "line", "actor", "kind", "raw", "event", "applied",
                    "error", "trigger", "reasons", "handled"):
            self.assertIn(key, e)
        self.assertEqual((e["gen"], e["kind"], e["actor"], e["raw"]),
                         (1, "generation", None, "Generation 1"))
        self.assertTrue(e["applied"])
        self.assertIsNone(e["error"])
        self.assertFalse(e["handled"])
        self.assertIsInstance(e["reasons"], list)

    def test_nothing_new_is_a_noop_with_no_fetch_of_logs(self):
        self.reveal_to(16)
        self.drain()
        self.app.requests.clear()
        r, out = self.drain()
        self.assertFalse(r.new)
        self.assertEqual(r.result, "WAIT")
        self.assertEqual([p.split("?")[0] for p in self.app.requests], ["/api/waitingfor"])
        self.assertEqual(len(self.feed()), 12)

    def test_hidden_info_lines_fill_my_hand(self):
        self.reveal_to(28)
        self.drain()
        hand = self.game()["me"]["hand"]
        self.assertIn("Artificial Photosynthesis", hand)
        self.assertIn("GHG Producing Bacteria", hand)
        self.assertNotIn("Io Mining Industries", hand)      # Anna's draw, not mine

    def test_same_line_text_twice_is_applied_twice(self):
        self.app.reveal(["Generation 1", "Carl played ThorGate", "Carl gained 2 steel"])
        self.drain()
        self.assertEqual(self.pool("Carl")["resources"]["steel"], 2)
        self.app.reveal(["Carl gained 2 steel"])
        r, out = self.drain()
        self.assertEqual(out.count("logged: "), 1)
        self.assertEqual(self.pool("Carl")["resources"]["steel"], 4)
        self.assertEqual([e["line"] for e in self.feed()], [1, 2, 3, 4])

    def test_malformed_line_is_a_gap_and_the_drain_continues(self):
        self.app.reveal(["Generation 1", "Ben played CrediCor",
                         "Ben did something the grammar does not know",
                         "Ben gained 4 M€"])
        r, out = self.drain()
        feed = self.feed()
        bad = next(e for e in feed if e["kind"] == "unknown")
        self.assertFalse(bad["applied"])
        self.assertTrue(bad["error"])
        self.assertIn("GAP:", out)
        self.assertEqual(self.pool("Ben")["resources"]["mc"], 57 + 4)   # CrediCor 57
        self.assertTrue(feed[-1]["applied"])

    def test_cursor_resumes_mid_generation_without_double_applying(self):
        self.reveal_to(30)
        self.drain(self.listener())
        before = self.feed()
        self.assertEqual(self.pool("Carl")["resources"]["titanium"], 2)
        self.reveal_to(40)
        r, out = self.drain(self.listener())               # a NEW listener = new process
        after = self.feed()
        self.assertEqual([e["line"] for e in after[len(before):]], list(range(31, 41)))
        self.assertEqual(len({e["line"] for e in after}), len(after))
        self.assertEqual(self.pool("Carl")["resources"]["titanium"], 2)  # hex 63 once
        self.assertEqual(self.pool("Anna")["production"]["energy"], 1)   # Wave Power once
        cur = json.loads(listen.cursor_path(self.store).read_text())
        self.assertEqual((cur["generation"], cur["lastLine"], cur["gameAge"]),
                         (1, 40, self.app.game_age))

    def test_engine_state_matches_the_replay_for_the_same_slice(self):
        # cuts inside blocks (21: Ice Asteroid's tail; 30: Nuclear Power's
        # tail) exercise the late-consequence path
        for cut in (16, 21, 30, 53, 57, 66, 80):
            self.reveal_to(cut)
            self.drain(self.listener())
        ref_tmp = tempfile.TemporaryDirectory()
        try:
            ref = Store(ref_tmp.name, state_dir=Path(ref_tmp.name) / "state")
            ref.init(_setup())
            rp = R.Replayer(Engine(ref), R.Report(), verbose=False)
            for b in P.group_blocks(P.parse_log("\n".join(LINES), PLAYERS)):
                rp.block(b)
            want, got = ref.load_game(), self.game()
        finally:
            ref_tmp.cleanup()
        self.assertEqual(got["globals"], want["globals"])
        self.assertEqual(got["generation"], want["generation"])
        for name in PLAYERS:
            w = want["me"] if want["me"]["name"] == name else want["opponents"][name]
            g = self.pool(name)
            self.assertEqual((name, g["tr"]), (name, w["tr"]))
            self.assertEqual((name, g["resources"]["mc"]), (name, w["resources"]["mc"]))
            self.assertEqual((name, g["production"]), (name, w["production"]))
            self.assertEqual((name, g["resources"]), (name, w["resources"]))
        self.assertEqual(got["me"]["hand"], want["me"]["hand"])

    def test_own_action_already_applied_is_skipped_but_hand_lines_land(self):
        self.eng.corp("Diana", "Teractor", mc=60)
        self.eng.hand_add(["Business Contacts"])
        self.eng.play("Diana", "Business Contacts")
        mc = self.game()["me"]["resources"]["mc"]
        self.app.reveal(["Generation 1", "Diana played Teractor",
                         "Diana played Business Contacts", "Diana drew 2 card(s)",
                         "You drew Artificial Photosynthesis,GHG Producing Bacteria"])
        r, out = self.drain()
        self.assertEqual(self.game()["me"]["resources"]["mc"], mc)     # not charged twice
        self.assertEqual(self.game()["me"]["corporation"], "Teractor")
        notes = {e["raw"]: e.get("note") for e in self.feed()}
        self.assertIn("already applied", notes["Diana played Business Contacts"])
        self.assertIn("already applied", notes["Diana played Teractor"])
        self.assertIn("Artificial Photosynthesis", self.game()["me"]["hand"])
        self.assertEqual(len([c for c in self.game()["me"]["hand"]
                              if c == "GHG Producing Bacteria"]), 1)
        self.assertIn("own action, already applied", out)

    def test_own_action_not_reflected_is_absorbed_then_synced(self):
        self.app.reveal(["Generation 1", "Diana played Teractor"])
        r, out = self.drain()
        self.assertEqual(self.game()["me"]["corporation"], "Teractor")
        self.assertIn("own action absorbed", out)
        self.assertIn("table synced", out)                 # every drain syncs

    def test_own_line_mid_drain_still_syncs(self):
        # our corp pick lands in the SAME drain as the opponents' (the app
        # logs the whole initial phase at once); the hand the app holds
        # must land even though the last line is not ours
        self.app.hand_override = ["Comet", "Sponsors"]
        self.app.reveal(["Generation 1", "Diana played Teractor",
                         "Diana kept 2 project cards", "Anna played CrediCor"])
        r, out = self.drain()
        self.assertIn("table synced", out)
        self.assertEqual(sorted(self.game()["me"]["hand"]), ["Comet", "Sponsors"])

    def test_generation_boundary_runs_wgt_and_produce(self):
        self.reveal_to(53)
        self.drain()
        g = self.game()
        self.assertEqual((g["generation"], g.get("wgtDoneGen")), (1, 1))
        self.assertEqual(g["globals"]["temperature"], -28)
        mc = g["me"]["resources"]["mc"]
        self.reveal_to(55)
        r, out = self.drain()
        g = self.game()
        self.assertEqual(g["generation"], 2)
        self.assertEqual(g["firstPlayer"], "Carl")
        self.assertEqual(g["me"]["resources"]["mc"],
                         mc + g["me"]["tr"] + g["me"]["production"]["mc"])
        self.assertIn("TRIGGER:", out)                     # class f: turnover

    def test_generation_already_advanced_by_produce_py_is_not_run_twice(self):
        self.reveal_to(53)
        self.drain()
        self.eng.produce()                                 # produce.py ran first
        mc = self.game()["me"]["resources"]["mc"]
        self.reveal_to(55)
        r, out = self.drain()
        self.assertEqual(self.game()["generation"], 2)
        self.assertEqual(self.game()["me"]["resources"]["mc"], mc)
        e = next(e for e in self.feed() if e["kind"] == "generation" and e["event"]["n"] == 2)
        self.assertTrue(e["applied"])
        self.assertIn("already", e["note"])

    def test_triage_trigger_is_printed_and_recorded(self):
        self.reveal_to(80)                                 # gens 1 + 2 in one drain
        r, out = self.drain()
        e = next(e for e in self.feed() if e["kind"] == "stole")
        self.assertTrue(e["trigger"])
        self.assertTrue(any("attack" in x for x in e["reasons"]))
        self.assertIn("logged: Carl stole 1 energy production from Diana applied TRIGGER: attack",
                      out)
        self.assertEqual(self.game()["generation"], 2)
        cur = json.loads(listen.cursor_path(self.store).read_text())
        self.assertEqual(cur["generation"], 2)
        self.assertEqual(cur["seen"], {"1": GEN2_AT, "2": 80 - GEN2_AT})

    def test_undo_shrinks_the_view_without_crashing(self):
        self.reveal_to(16)
        self.drain()
        del self.app.lines[-2:]
        self.app.undo += 1
        self.app.game_age += 1
        r, out = self.drain()
        self.assertIn("undo", out.lower())
        cur = json.loads(listen.cursor_path(self.store).read_text())
        self.assertEqual((cur["seen"]["1"], cur["undoCount"]), (14, 1))
        self.revealed = 14
        self.reveal_to(16)                                 # replayed by the app
        r, out = self.drain()
        self.assertEqual(out.count("logged: "), 2)


# ── one action, two drains: card context and duplicate plays ──────────

class TestSplitDrains(ListenBase):
    """listen.py polls about once a second, so the log lines of ONE app
    action routinely land in different drains and the consequence lines
    reach the replayer as a `late_tail` head — with no card in scope."""

    def reveal_and_drain(self, lines):
        self.app.reveal(lines)
        return self.drain()

    def test_protected_valley_greenery_on_an_ocean_area_survives_a_split(self):
        # p8 #13: the play was drained at 23:58:50, the placement at
        # 23:58:58, so place() was called without card= and the greenery on
        # ocean-reserved 33 was refused. Ben's later greeneries next to it
        # (41, 42, 40, 50, 49) then failed the adjacency rule too.
        self.reveal_and_drain(["Ben played Protected Valley",
                               "Ben gained 2 M€ production"])
        _r, out = self.reveal_and_drain(["Ben placed greenery tile at 33",
                                         "Ben gained 2 plants"])
        self.assertNotIn("ocean-reserved", out)
        self.assertEqual(self.game().get("board", {}).get("33"),
                         {"tile": "greenery", "player": "Ben"})
        self.assertEqual(self.pool("Ben")["tiles"]["greeneries"], 1)
        self.assertTrue(all(e["applied"] for e in self.feed()))

    def test_a_late_placement_gets_no_exemption_from_an_unrelated_card(self):
        # the fallback must read the card's behavior, not merely "some card
        # was played" — an ocean-reserved hex stays illegal otherwise
        self.reveal_and_drain(["Ben played Ironworks"])
        _r, out = self.reveal_and_drain(["Ben placed greenery tile at 33"])
        self.assertNotIn("33", self.game().get("board", {}))
        self.assertIn("ocean-reserved", out)

    def test_a_corporations_first_action_still_places_its_tile(self):
        # Replayer.block() returned early on `first_action`, so the whole
        # block's tail was dropped: Tharsis Republic's free city never
        # reached the board in a whole-log replay (game 2, "Ben took the
        # first action of Tharsis Republic corporation" / "Ben placed city
        # tile at 14"). Live it survived only because the drain split
        # turned the placement into a `late_tail`.
        self.reveal_and_drain(["Ben took the first action of Tharsis Republic corporation",
                               "Ben placed city tile at 14",
                               "Ben gained 1 M€ production"])
        self.assertEqual(self.game().get("board", {}).get("14"),
                         {"tile": "city", "player": "Ben"})
        self.assertEqual(self.pool("Ben")["tiles"]["cities"], 1)
        self.assertEqual(self.pool("Ben")["production"]["mc"], 1)
        self.assertTrue(all(e["applied"] for e in self.feed()))

    def test_a_card_already_observed_in_the_tableau_is_not_played_twice(self):
        # p8 #18: verify.py --sync saw the card in the app tableau
        # (observe_play — bookkeeping only, followed by a numeric observe
        # that adopts the app's figures); the listener then drained the same
        # "played" line and appended a SECOND playedCards entry, so Media
        # Archives counted 14 events where the app paid 13.
        self.eng.res("Ben", "mc", 30)
        self.eng.observe_play("Ben", "Convoy From Europa")
        before = self.pool("Ben")["resources"]["mc"]
        self.reveal_and_drain(["Ben played Convoy From Europa"])
        names = [c["name"] for c in self.pool("Ben")["playedCards"]]
        self.assertEqual(names.count("Convoy From Europa"), 1)
        self.assertEqual(self.pool("Ben")["resources"]["mc"], before)
        self.assertTrue(all(e["applied"] for e in self.feed()))


# ── sync-me ───────────────────────────────────────────────────────────

class TestSyncMe(ListenBase):
    def test_sync_me_reconciles_planted_drift(self):
        self.eng.corp("Diana", "Teractor", mc=60)
        self.eng.hand_add(["Predators", "Ironworks"])
        self.app.drift = {"megacredits": 65, "heat": 3, "steelProduction": 1}
        self.app.hand_override = ["Ironworks", "Solar Wind Power"]
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            msg = self.listener().sync_me()
        me = self.game()["me"]
        self.assertEqual((me["resources"]["mc"], me["resources"]["heat"],
                          me["production"]["steel"]), (65, 3, 1))
        self.assertEqual(me["hand"], ["Ironworks", "Solar Wind Power"])
        self.assertIn("mc 60→65", msg)
        self.assertIn("Solar Wind Power", msg)
        self.assertIn("Predators", msg)

    def test_sync_me_reads_the_hand_at_the_view_top_level(self):
        # PlayerViewModel.cardsInHand (the real app) — thisPlayer only
        # carries cardsInHandNbr
        self.app.hand_at_top = True
        self.app.hand_override = ["Ironworks", "Solar Wind Power"]
        msg = self.listener().sync_me()
        self.assertIn("hand", msg)
        self.assertEqual(sorted(self.game()["me"]["hand"]),
                         ["Ironworks", "Solar Wind Power"])

    def test_sync_me_is_my_mat_only(self):
        """The narrow own-panel path stays narrow: an opponent's planted
        drift is the table sync's business, not sync-me's."""
        self.app.opp_drift = {"Anna": {"megacredits": 41}}
        msg = self.listener().sync_me()
        self.assertEqual(self.pool("Anna")["resources"]["mc"], 0)
        self.assertNotIn("Anna", msg)

    def test_sync_me_no_drift(self):
        self.eng.corp("Diana", "Teractor", mc=60)
        msg = self.listener().sync_me()
        self.assertIn("no drift", msg)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 60)

    def test_sync_me_cli_adopts_the_whole_table(self):
        # the CLI verb is the FULL adoption now (verify.sync_table): the
        # summary names the player, not just the field
        self.app.drift = {"megacredits": 9}
        code, out = self.main("sync-me")
        self.assertEqual(code, 0)
        self.assertIn("Diana MC 0→9", out)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 9)


# ── full-table sync (P9: the app is the state of record) ──────────────

class TestTableSync(ListenBase):
    """P9 phase 3. The log lines are the EVENT feed; the numbers come from
    /api/player. Before this, only my own mat was reconciled (and only
    after an own line) — every opponent effect the replayer cannot model
    drifted until somebody remembered `verify.py --sync`. Now every drain
    that gets past WAIT ends with the whole public table adopted."""

    def test_drain_adopts_every_opponents_public_mat(self):
        self.app.opp_drift = {"Anna": {"megacredits": 34, "plants": 9,
                                       "titaniumProduction": 2,
                                       "terraformRating": 23}}
        self.app.reveal(["Generation 1", "Ben played CrediCor"])
        r, out = self.drain()
        anna = self.pool("Anna")
        self.assertEqual(anna["resources"]["mc"], 34)
        self.assertEqual(anna["resources"]["plants"], 9)
        self.assertEqual(anna["production"]["titanium"], 2)
        self.assertEqual(anna["tr"], 23)
        self.assertIn("table synced: Anna MC 0→34", out)
        # and the drained line still applied: Ben's CrediCor MC stands
        self.assertEqual(self.pool("Ben")["resources"]["mc"], 57)

    def test_a_table_that_already_matches_reports_exact(self):
        self.app.reveal(["Generation 1", "Ben played CrediCor"])
        r, out = self.drain()
        self.assertIn("table synced: exact", out)

    def test_the_sync_runs_after_the_ingest_not_before(self):
        """Ordering: the view is re-fetched once the lines are applied —
        syncing the pre-ingest view would undo the whole drain."""
        self.app.reveal(["Generation 1", "Carl played ThorGate",
                         "Carl gained 2 steel"])
        r, out = self.drain()
        self.assertEqual(self.pool("Carl")["resources"]["steel"], 2)
        self.assertIn("table synced: exact", out)

    def test_my_card_resources_come_from_the_app(self):
        self.eng.corp("Diana", "Teractor", mc=60)
        self.eng.hand_add(["Predators"])
        self.eng.play("Diana", "Predators", ignore_requirements="test fixture")
        self.app.opp_drift = {"Diana": {"tableau": [
            {"name": "corp", "resources": 0},
            {"name": "Predators", "resources": 4}]}}
        self.app.reveal(["Generation 1", "Ben played CrediCor"])
        r, out = self.drain()
        self.assertEqual(self.game()["me"]["cardResources"]["Predators"], 4)
        self.assertIn("Predators 0→4", out)

    def test_generation_guard_refuses_post_production_values(self):
        """P8 #17 still holds: while the app's generation is AHEAD (the
        'Generation N' line has not been drained yet) resource values are
        post-production and adopting them would double the income."""
        self.app.reveal(["Generation 1", "Ben played CrediCor"])
        self.drain()
        self.app.gen_override = 2                      # app rolled, log not yet
        self.app.drift = {"megacredits": 77}
        self.app.opp_drift = {"Anna": {"megacredits": 99}}
        self.app.reveal(["Anna gained 1 M€"])
        r, out = self.drain()
        self.assertEqual(self.game()["me"]["resources"]["mc"], 0)
        self.assertEqual(self.pool("Anna")["resources"]["mc"], 1)   # drained line only
        self.assertIn("generation 2", out)
        self.assertEqual(self.game()["generation"], 1)


# ── exit codes / CLI ──────────────────────────────────────────────────

class TestExitCodes(ListenBase):
    def test_once_exit_codes(self):
        self.reveal_to(16)
        self.assertEqual(self.main("once")[0], 10)         # new events applied
        self.assertEqual(self.main("once")[0], 0)          # nothing new
        self.app.waiting = "Take your first action"
        self.assertEqual(self.main("once")[0], 20)         # GO, nothing new
        self.reveal_to(20)
        code, out = self.main("once")
        self.assertEqual(code, 30)                         # GO + events
        self.assertIn("GO — Take your first action", out)

    def test_once_refuses_physical_mode(self):
        setup = self.store.load_setup()
        setup["gameMode"] = "physical"
        Store._write_json(self.store.setup_path, setup)
        self.assertEqual(self.main("once")[0], 1)

    def test_app_down_is_exit_1(self):
        code, out = self.main("--url", "http://127.0.0.1:9", "once")
        self.assertEqual(code, 1)

    def test_init_marks_current_lines_seen_without_applying(self):
        self.reveal_to(30)
        code, out = self.main("init")
        self.assertEqual(code, 0)
        self.assertEqual(self.feed(), [])
        self.assertEqual(self.pool("Carl")["resources"]["titanium"], 0)
        self.reveal_to(33)
        code, out = self.main("once")
        self.assertEqual(code, 10)
        self.assertEqual([e["line"] for e in self.feed()], [31, 32, 33])

    def test_status_prints_cursor(self):
        self.reveal_to(16)
        self.main("once")
        code, out = self.main("status")
        self.assertEqual(code, 0)
        self.assertIn("generation 1", out)
        self.assertIn("lastLine 16", out)

    def test_latency_marks_listen_phase(self):
        import latency
        self.reveal_to(16)
        self.main("once")
        marks = latency.read_marks(latency.path_for(self.store))
        self.assertEqual([m["phase"] for m in marks], ["listen", "listen"])


# ── wait ──────────────────────────────────────────────────────────────

class TestWait(ListenBase):
    def _clock(self, step=1):
        t = [0]

        def clock():
            t[0] += step
            return t[0]
        return clock

    def test_wait_returns_20_on_go(self):
        self.reveal_to(16)
        self.drain()
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            if len(sleeps) == 3:
                self.app.waiting = "Select card(s) to buy"
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code, title = listen.wait(self.listener(), interval=1, idle=10, timeout=570,
                                      sleep=sleep, clock=self._clock())
        self.assertEqual(code, 20)
        self.assertEqual(title, "Select card(s) to buy")
        self.assertIn("GO — Select card(s) to buy", buf.getvalue())
        self.assertEqual(sleeps, [1, 2, 4])                 # backs off towards --idle

    def test_wait_returns_30_when_events_arrived_before_go(self):
        self.reveal_to(16)
        self.drain()
        n = [0]

        def sleep(s):
            n[0] += 1
            if n[0] == 1:
                self.reveal_to(20)
            if n[0] == 2:
                self.app.waiting = "Take your first action"
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code, title = listen.wait(self.listener(), interval=1, idle=10, timeout=570,
                                      sleep=sleep, clock=self._clock())
        self.assertEqual(code, 30)
        self.assertEqual(len(self.feed()), 16)

    def test_wait_backs_off_to_idle_and_times_out_with_3(self):
        self.reveal_to(16)
        self.drain()
        sleeps = []
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code, title = listen.wait(self.listener(), interval=1, idle=10, timeout=50,
                                      sleep=sleeps.append, clock=self._clock(5))
        self.assertEqual(code, 3)
        self.assertEqual(max(sleeps), 10)
        self.assertIn("TIMEOUT", buf.getvalue())

    def test_wait_cli(self):
        self.app.waiting = "Take your first action"
        code, out = self.main("wait", "--timeout", "5")
        self.assertEqual(code, 20)


if __name__ == "__main__":
    unittest.main()
