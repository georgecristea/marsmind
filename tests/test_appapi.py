"""appapi.py: the ONE HTTP client for the open-source terraforming-mars
app. Every fetcher (sparring, verify, gamecheck, turnwatch, advise,
planlib) goes through AppClient — one import, one code path. Served by
a tiny in-process http.server so the real urllib path is exercised."""
import http.server
import io
import json
import os
import sys
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import appapi
from appapi import AppClient, AppError, AppUnavailable, render_log_entry

FIXTURE_LOG = (Path(__file__).resolve().parent / "fixtures" / "replay-4p-wgt"
               / "applog.txt")


class CannedServer:
    """In-process server: each route maps to a list of (status, body)
    responses consumed in order (the last one repeats). A body may be a
    callable (path, request_body) -> (status, body) for scripted apps
    (tests/test_listen.py). Records every request (method, path, body)
    for assertions."""

    def __init__(self, routes: dict):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.requests: list[tuple[str, str, bytes]] = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):          # silence
                pass

            def _serve(self, body_in: bytes):
                path = self.path
                outer.requests.append((self.command, path, body_in))
                key = path.split("?")[0]
                queue = outer.routes.get(key)
                if not queue:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"no route")
                    return
                status, body = queue[0] if len(queue) == 1 else queue.pop(0)
                if callable(body):
                    status, body = body(path, body_in)
                if not isinstance(body, (bytes, str)):
                    body = json.dumps(body)
                if isinstance(body, str):
                    body = body.encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self._serve(b"")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self._serve(self.rfile.read(n))

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


PLAYER = {"thisPlayer": {"megacredits": 12, "terraformRating": 21},
          "game": {"generation": 3, "phase": "action"},
          "players": [{"name": "Anna", "color": "red"},
                      {"name": "Carl", "color": "blue"}],
          "waitingFor": None}


class ServerBase(unittest.TestCase):
    routes: dict = {}

    def setUp(self):
        self.srv = CannedServer(self.routes)
        self.sleeps: list[float] = []
        self.client = AppClient(self.srv.url, timeout=2, retries=3,
                                backoff=0.5, sleep=self.sleeps.append)

    def tearDown(self):
        self.srv.close()


class TestEndpoints(ServerBase):
    routes = {
        "/api/player": [(200, PLAYER)],
        "/api/waitingfor": [(200, {"result": "WAIT", "waitingFor": ["red"]})],
        "/api/game/logs": [(200, [{"message": "Generation ${0}", "type": 1,
                                   "data": [{"type": 1, "value": "3"}]}])],
        "/player/input": [(200, PLAYER)],
    }

    def test_player(self):
        d = self.client.player("p1")
        self.assertEqual(d["thisPlayer"]["megacredits"], 12)
        self.assertEqual(self.srv.requests[-1][:2], ("GET", "/api/player?id=p1"))

    def test_waiting_for_query_string(self):
        d = self.client.waiting_for("p1", game_age=7, undo_count=2)
        self.assertEqual(d["result"], "WAIT")
        self.assertEqual(self.srv.requests[-1][1],
                         "/api/waitingfor?id=p1&gameAge=7&undoCount=2")

    def test_game_logs_json(self):
        entries = self.client.game_logs("p1", generation=3)
        self.assertEqual(entries[0]["message"], "Generation ${0}")
        self.assertEqual(self.srv.requests[-1][1],
                         "/api/game/logs?id=p1&generation=3")
        self.client.game_logs("p1")
        self.assertEqual(self.srv.requests[-1][1], "/api/game/logs?id=p1")

    def test_send_posts_json_body(self):
        d = self.client.send("p1", {"type": "option"})
        self.assertEqual(d["game"]["generation"], 3)
        method, path, body = self.srv.requests[-1]
        self.assertEqual((method, path), ("POST", "/player/input?id=p1"))
        self.assertEqual(json.loads(body), {"type": "option"})

    def test_base_url_trailing_slash_is_tolerated(self):
        c = AppClient(self.srv.url + "/", timeout=2)
        c.player("p1")
        self.assertEqual(self.srv.requests[-1][1], "/api/player?id=p1")


class TestFullLog(ServerBase):
    routes = {"/api/game/logs": [(200, "Generation 1\nAnna kept 5 project cards")]}

    def test_full_returns_plain_text(self):
        text = self.client.game_logs("p1", full=True)
        self.assertEqual(text, "Generation 1\nAnna kept 5 project cards")
        self.assertEqual(self.srv.requests[-1][1], "/api/game/logs?id=p1&full")


class TestRetries(ServerBase):
    routes = {"/api/player": [(503, "busy"), (502, "bad"), (200, PLAYER)]}

    def test_5xx_retried_with_backoff_then_succeeds(self):
        d = self.client.player("p1")
        self.assertEqual(d["game"]["generation"], 3)
        self.assertEqual(len(self.srv.requests), 3)
        self.assertEqual(self.sleeps, [0.5, 1.0])      # linear backoff


class TestRetriesExhausted(ServerBase):
    routes = {"/api/player": [(500, "boom")]}

    def test_persistent_5xx_raises_app_error_with_body(self):
        with self.assertRaises(AppError) as cm:
            self.client.player("p1")
        self.assertEqual(cm.exception.status, 500)
        self.assertIn("boom", cm.exception.body)
        self.assertEqual(len(self.srv.requests), 3)     # retries=3 attempts


class TestClientErrors(ServerBase):
    routes = {"/player/input": [(400, '{"message":"Not a valid space"}')],
              "/api/player": [(404, "game not found")]}

    def test_4xx_is_not_retried(self):
        with self.assertRaises(AppError) as cm:
            self.client.send("p1", {"type": "space", "spaceId": "99"})
        self.assertEqual(cm.exception.status, 400)
        self.assertIn("Not a valid space", cm.exception.body)
        self.assertEqual(len(self.srv.requests), 1)
        self.assertEqual(self.sleeps, [])

    def test_404_carries_status(self):
        with self.assertRaises(AppError) as cm:
            self.client.player("p1")
        self.assertEqual(cm.exception.status, 404)
        self.assertIn("404", str(cm.exception))

    def test_app_error_is_an_http_error_for_legacy_handlers(self):
        """Callers that still catch urllib.error.URLError/HTTPError keep
        working — AppError subclasses HTTPError."""
        self.assertTrue(issubclass(AppError, urllib.error.HTTPError))


class TestUnavailable(unittest.TestCase):
    def test_connection_refused_raises_unavailable_after_retries(self):
        sleeps = []
        c = AppClient("http://127.0.0.1:9", timeout=1, retries=2,
                      backoff=0.1, sleep=sleeps.append)
        with self.assertRaises(AppUnavailable):
            c.player("p1")
        self.assertEqual(sleeps, [0.1])

    def test_unavailable_is_a_url_error(self):
        self.assertTrue(issubclass(AppUnavailable, urllib.error.URLError))


class TestFromSetup(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop("PHOBOS_APP_URL", None)

    def tearDown(self):
        if self._env is not None:
            os.environ["PHOBOS_APP_URL"] = self._env
        else:
            os.environ.pop("PHOBOS_APP_URL", None)

    def test_setup_app_url_wins(self):
        os.environ["PHOBOS_APP_URL"] = "http://envhost:8080"
        c = AppClient.from_setup({"appUrl": "http://setuphost:8080/"})
        self.assertEqual(c.base_url, "http://setuphost:8080")

    def test_env_is_the_fallback(self):
        os.environ["PHOBOS_APP_URL"] = "http://envhost:8080"
        self.assertEqual(AppClient.from_setup({}).base_url, "http://envhost:8080")

    def test_default_is_localhost_8080(self):
        self.assertEqual(AppClient.from_setup({}).base_url,
                         "http://localhost:8080")
        self.assertIsNone(appapi.configured_url({}))

    def test_kwargs_pass_through(self):
        c = AppClient.from_setup({}, timeout=2, retries=1)
        self.assertEqual((c.timeout, c.retries), (2, 1))


# ── log-entry rendering (route shape: LogMessage {message, data[], type?,
#    playerId?, timestamp}; data item {type: LogMessageDataType, value}) ──

NAMES = {"red": "Anna", "blue": "Carl", "green": "Hector"}
T = appapi.DataType


def entry(message, *data, **kw):
    return {"message": message, "data": [{"type": t, "value": v}
                                         for t, v in data],
            "timestamp": 1700000000000, **kw}


class TestRenderLogEntry(unittest.TestCase):
    def test_tile_placement_player_string_space(self):
        # LogHelper.logBoardTileAction: '${0} ${1} ${2} at ${3}'
        e = entry("${0} ${1} ${2} at ${3}", (T.PLAYER, "blue"),
                  (T.STRING, "placed"), (T.STRING, "ocean tile"),
                  (T.SPACE, "63"))
        self.assertEqual(render_log_entry(e, NAMES),
                         "Carl placed ocean tile at 63")

    def test_kept_cards_number_is_raw_string(self):
        # Player.ts: '${0} kept ${1} project cards' with .number()
        e = entry("${0} kept ${1} project cards", (T.PLAYER, "red"),
                  (T.RAW_STRING, "5"))
        self.assertEqual(render_log_entry(e, NAMES), "Anna kept 5 project cards")

    def test_ocean_adjacency_two_numbers(self):
        e = entry("${0} gained ${1} M€ from ${2} ocean(s)", (T.PLAYER, "green"),
                  (T.RAW_STRING, "2"), (T.RAW_STRING, "1"))
        self.assertEqual(render_log_entry(e, NAMES),
                         "Hector gained 2 M€ from 1 ocean(s)")

    def test_card_played_keeps_full_card_name(self):
        e = entry("${0} played ${1}", (T.PLAYER, "red"),
                  (T.CARD, "Earth Catapult"))
        self.assertEqual(render_log_entry(e, NAMES), "Anna played Earth Catapult")
        e = entry("${0} used ${1} standard project", (T.PLAYER, "blue"),
                  (T.CARD, "Power Plant:SP"))
        self.assertEqual(render_log_entry(e, NAMES),
                         "Carl used Power Plant:SP standard project")

    def test_cards_list_joins_with_commas_like_the_export(self):
        # LogHelper.logDrawnCards private form: '${0} drew ${1}' with
        # string('You') + cards([...]); JS Array.toString() = "a,b,c"
        e = entry("${0} drew ${1}", (T.STRING, "You"),
                  (T.CARDS, ["Io Mining Industries", "Anti-Gravity Technology",
                             "Predators"]), playerId="p-anna")
        self.assertEqual(render_log_entry(e, NAMES),
                         "You drew Io Mining Industries,Anti-Gravity Technology,Predators")

    def test_generation_marker(self):
        e = entry("Generation ${0}", (T.RAW_STRING, "4"), type=1)
        self.assertEqual(render_log_entry(e, NAMES), "Generation 4")

    def test_unknown_color_falls_back_to_color(self):
        e = entry("Good luck ${0}!", (T.PLAYER, "orange"))
        self.assertEqual(render_log_entry(e, NAMES), "Good luck orange!")
        self.assertEqual(render_log_entry(e), "Good luck orange!")

    def test_production_loss_because_of(self):
        e = entry("${0} lost ${1} ${2} production because of ${3}",
                  (T.PLAYER, "red"), (T.RAW_STRING, "1"), (T.STRING, "energy"),
                  (T.PLAYER, "blue"))
        self.assertEqual(render_log_entry(e, NAMES),
                         "Anna lost 1 energy production because of Carl")

    def test_award_milestone_values(self):
        e = entry("${0} funded ${1} award", (T.PLAYER, "red"), (T.AWARD, "Landlord"))
        self.assertEqual(render_log_entry(e, NAMES), "Anna funded Landlord award")
        e = entry("${0} claimed ${1} milestone", (T.PLAYER, "blue"),
                  (T.MILESTONE, "Mayor"))
        self.assertEqual(render_log_entry(e, NAMES), "Carl claimed Mayor milestone")

    def test_tile_type_enum_renders_as_name(self):
        # Game.ts: 'Drew and discarded ${0} to place a ${1}' with tileType(1)
        e = entry("Drew and discarded ${0} to place a ${1}", (T.CARD, "Algae"),
                  (T.TILE_TYPE, 1))
        self.assertEqual(render_log_entry(e, NAMES),
                         "Drew and discarded Algae to place a ocean")

    def test_missing_datum_renders_empty(self):
        e = entry("${0} passed ${1}", (T.PLAYER, "red"))
        self.assertEqual(render_log_entry(e, NAMES), "Anna passed ")
        self.assertEqual(render_log_entry({"message": "plain"}), "plain")

    def test_rendered_lines_parse_with_applog_parser(self):
        import applog_parser
        players = ["Anna", "Carl", "Hector"]
        lines = [
            render_log_entry(entry("${0} ${1} ${2} at ${3}", (T.PLAYER, "blue"),
                                   (T.STRING, "placed"), (T.STRING, "ocean tile"),
                                   (T.SPACE, "63")), NAMES),
            render_log_entry(entry("${0} kept ${1} project cards", (T.PLAYER, "red"),
                                   (T.RAW_STRING, "5")), NAMES),
            render_log_entry(entry("${0} gained ${1} M€ from ${2} ocean(s)",
                                   (T.PLAYER, "green"), (T.RAW_STRING, "2"),
                                   (T.RAW_STRING, "1")), NAMES),
        ]
        fixture = FIXTURE_LOG.read_text().splitlines()
        self.assertIn(lines[0], fixture)            # byte-identical to the export
        ev = [applog_parser.parse_line(l, players) for l in lines]
        self.assertEqual([e["kind"] for e in ev], ["placed", "kept", "gained"])
        self.assertEqual((ev[0]["player"], ev[0]["space"]), ("Carl", "63"))
        self.assertEqual((ev[2]["source"], ev[2]["oceans"]), ("ocean", 1))


class TestLogLines(ServerBase):
    routes = {
        "/api/player": [(200, PLAYER)],
        "/api/game/logs": [(200, [
            entry("Generation ${0}", (T.RAW_STRING, "3"), type=1),
            entry("${0} kept ${1} project cards", (T.PLAYER, "red"),
                  (T.RAW_STRING, "5")),
            entry("${0} ${1} ${2} at ${3}", (T.PLAYER, "blue"),
                  (T.STRING, "placed"), (T.STRING, "ocean tile"),
                  (T.SPACE, "63")),
        ])],
    }

    def test_log_lines_resolve_names_from_player_view(self):
        lines = appapi.log_lines(self.client, "p1", generation=3)
        self.assertEqual(lines, ["Generation 3", "Anna kept 5 project cards",
                                 "Carl placed ocean tile at 63"])
        paths = [r[1] for r in self.srv.requests]
        self.assertIn("/api/game/logs?id=p1&generation=3", paths)

    def test_log_lines_with_explicit_names_skips_player_fetch(self):
        appapi.log_lines(self.client, "p1", generation=3, names=NAMES)
        self.assertEqual([r[1] for r in self.srv.requests],
                         ["/api/game/logs?id=p1&generation=3"])


class TestCli(unittest.TestCase):
    def test_help_runs(self):
        import subprocess
        r = subprocess.run([sys.executable, str(Path(appapi.__file__)), "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("waitingfor", r.stdout)


if __name__ == "__main__":
    unittest.main()
