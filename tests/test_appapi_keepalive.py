"""Connection reuse for the app API.

Evidence (experiments/2026-08-29-distant-neutron-surge/): appapi opened a
FRESH connection for every request. On a LAN that is ~5 ms of waste; over the
internet, which is how games are played from now on, it is the dominant cost.
Measured against the public host used for the previous online game night:

    fresh  connection: connect 120 ms + TLS 240 ms + transfer 115 ms = 480 ms
    reused connection:                                                 110 ms

~370 ms per request, and a twelve-generation game issues on the order of 1800
of them: ~14 min of transport against ~3 min.

Safety contract, in order of importance:
  * keep-alive is SKIPPED whenever urllib.request.urlopen has been patched,
    so every pre-existing test keeps exercising exactly the old code path and
    a mock can never be silently bypassed;
  * PHOBOS_NO_KEEPALIVE=1 disables it outright, mid-evening, without an edit;
  * any connection-level failure falls back to the urlopen path, so a server
    that will not speak keep-alive degrades to today's behaviour instead of
    breaking a live game;
  * a connection the server closed between requests (the normal keep-alive
    race) is retried once on a fresh socket, transparently.
"""
import http.server
import json
import os
import socket
import sys
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import appapi
from appapi import AppClient, AppError


class CountingServer:
    """Serves JSON and counts how many TCP connections were opened."""

    def __init__(self, close_after: int | None = None):
        self.connections = 0
        self.requests = 0
        self.close_after = close_after      # close the socket ONCE after N
        self.closed_once = False
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                outer.connections += 1
                super().setup()

            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests += 1
                if (outer.close_after is not None
                        and not outer.closed_once
                        and outer.requests > outer.close_after):
                    # the real race: the server drops ONE idle connection,
                    # a fresh one then works
                    outer.closed_once = True
                    self.close_connection = True
                    return
                body = json.dumps({"ok": True, "n": outer.requests}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


class TestConnectionReuse(unittest.TestCase):

    def setUp(self):
        os.environ.pop("PHOBOS_NO_KEEPALIVE", None)

    def test_many_requests_share_one_connection(self):
        with CountingServer() as srv:
            c = AppClient(srv.url)
            for _ in range(6):
                self.assertEqual(json.loads(c._request(c._url("/api/games")))["ok"],
                                 True)
            self.assertEqual(srv.requests, 6)
            self.assertEqual(srv.connections, 1,
                             "six requests must reuse ONE connection")

    def test_kill_switch_restores_one_connection_per_request(self):
        os.environ["PHOBOS_NO_KEEPALIVE"] = "1"
        try:
            with CountingServer() as srv:
                c = AppClient(srv.url)
                for _ in range(3):
                    c._request(c._url("/api/games"))
                self.assertEqual(srv.connections, 3,
                                 "kill-switch must restore fresh connections")
        finally:
            os.environ.pop("PHOBOS_NO_KEEPALIVE", None)

    def test_patched_urlopen_is_never_bypassed(self):
        """The whole existing suite depends on this."""
        with CountingServer() as srv:
            c = AppClient(srv.url)
            payload = json.dumps({"ok": "from-the-mock"}).encode()

            class R:
                def read(self): return payload
                def __enter__(self): return self
                def __exit__(self, *a): return False

            with mock.patch.object(appapi.urllib.request, "urlopen",
                                   return_value=R()) as m:
                out = c._request(c._url("/api/games"))
            self.assertEqual(json.loads(out)["ok"], "from-the-mock")
            m.assert_called_once()
            self.assertEqual(srv.connections, 0,
                             "a patched urlopen must not be bypassed")

    def test_server_closing_the_connection_is_retried_transparently(self):
        with CountingServer(close_after=2) as srv:
            c = AppClient(srv.url)
            for _ in range(4):
                self.assertTrue(json.loads(c._request(c._url("/api/games")))["ok"])
            self.assertGreater(srv.connections, 1,
                               "a closed connection must be re-established")

    def test_post_body_round_trips(self):
        with CountingServer() as srv:
            c = AppClient(srv.url)
            out = c._request(c._url("/player/input"), data=b'{"x":1}')
            self.assertTrue(json.loads(out)["ok"])

    def test_http_error_still_raises_AppError_with_the_body(self):
        class Boom(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *a): pass
            def do_GET(self):
                body = b"Not authorized"
                self.send_response(403)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Boom)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            c = AppClient(f"http://127.0.0.1:{httpd.server_address[1]}")
            with self.assertRaises(AppError) as ctx:
                c._request(c._url("/api/games"))
            self.assertEqual(ctx.exception.code, 403)
            self.assertIn("Not authorized", str(ctx.exception.reason))
        finally:
            httpd.shutdown(); httpd.server_close()

    def test_dead_host_still_raises_AppUnavailable(self):
        with socket.socket() as s:                 # a port nobody listens on
            s.bind(("127.0.0.1", 0))
            dead = s.getsockname()[1]
        c = AppClient(f"http://127.0.0.1:{dead}", retries=1, backoff=0)
        with self.assertRaises(appapi.AppUnavailable):
            c._request(c._url("/api/games"))


if __name__ == "__main__":
    unittest.main()
