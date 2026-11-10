"""Regression tests from the 2p online game 'Distant Neutron Surge'.

Both fixes below are backed by evidence from BOTH seats' post-game
artifacts (experiments/2026-08-29-distant-neutron-surge/), not from
speculation:

1. mDNS transport penalty. state/setup.json carried an appUrl with a
   `.local` host. Measured on the game LAN: TCP connect 214 ms via the
   mDNS name against 4.9 ms via the resolved IPv4 literal, with DNS
   lookup only 5 ms of it -- i.e. dual-stack connect fallback, not
   resolution. The harness opens a fresh connection per request, so it
   paid that toll ~2000 times: 498 s of harness time against the
   opposing seat's 40 s on the same harness reaching the same host by
   IP. AppClient must resolve a `.local` host once and reuse the
   literal, falling back to the name if the literal stops answering
   (the LAN is DHCP).

2. Multi-tile cards only placed their first tile. Ice Asteroid and
   Giant Ice Asteroid each place TWO oceans; both seats stalled on
   "Select space for second ocean" and needed a manual
   `execute.py resolve <label> --space <hex>`. plan_actions already
   queued the extra placement as a separate ACTION, but
   _answer_follow_ups answers `space` once, so the second prompt was
   never covered. The extra placements must ride along as follow-ups of
   the action that opened them.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import appapi
import execute
from appapi import AppClient


class TestMdnsHostResolvedOnce(unittest.TestCase):
    """Fix 1 — a `.local` base URL is dialled by IPv4 literal."""

    def test_local_host_is_resolved_to_ipv4_literal(self):
        c = AppClient("http://tablehost.local:8080")
        with mock.patch.object(appapi.socket, "gethostbyname",
                               return_value="192.168.0.3") as g:
            self.assertEqual(c.dial_url("http://tablehost.local:8080/api/games"),
                             "http://192.168.0.3:8080/api/games")
            self.assertEqual(
                c.dial_url("http://tablehost.local:8080/api/player?id=x"),
                "http://192.168.0.3:8080/api/player?id=x")
        # resolved ONCE and cached, not per request
        self.assertEqual(g.call_count, 1)

    def test_non_local_hosts_are_untouched(self):
        for url in ("http://localhost:8080", "http://127.0.0.1:8080",
                    "http://192.168.0.3:8080", "http://example.test:8080"):
            c = AppClient(url)
            with mock.patch.object(appapi.socket, "gethostbyname") as g:
                self.assertEqual(c.dial_url(url + "/api/games"),
                                 url + "/api/games")
                g.assert_not_called()

    def test_unresolvable_local_host_falls_back_to_the_name(self):
        c = AppClient("http://nope.local:8080")
        with mock.patch.object(appapi.socket, "gethostbyname",
                               side_effect=OSError("no route")):
            self.assertEqual(c.dial_url("http://nope.local:8080/api/games"),
                             "http://nope.local:8080/api/games")

    def test_base_url_is_preserved_for_display(self):
        c = AppClient("http://tablehost.local:8080")
        with mock.patch.object(appapi.socket, "gethostbyname",
                               return_value="192.168.0.3"):
            c.dial_url("http://tablehost.local:8080/api/games")
        self.assertEqual(c.base_url, "http://tablehost.local:8080")
        self.assertIn("tablehost.local", repr(c))


class TestMultiTilePlacementsRideAlong(unittest.TestCase):
    """Fix 2 — every trailing `place` of one card is a follow-up."""

    ICE_ASTEROID = {
        "id": "1b",
        "events": [
            {"method": "play", "args": ["Maxwell", "Ice Asteroid"],
             "kwargs": {"titanium": 2}},
            {"method": "place", "args": ["Maxwell", "ocean", "28"]},
            {"method": "place", "args": ["Maxwell", "ocean", "13"]},
        ],
    }

    def test_two_oceans_are_one_action_with_a_space_queue(self):
        actions = execute.plan_actions(self.ICE_ASTEROID)
        self.assertEqual(len(actions), 1,
                         "both oceans belong to the single Ice Asteroid play")
        follow = actions[0]["follow"]
        self.assertEqual(follow["space"], "28")
        self.assertEqual(follow.get("spaceQueue"), ["13"])

    def test_place_only_step_still_becomes_its_own_action(self):
        """A step whose FIRST event is a place answers a pending prompt."""
        step = {"id": "2a", "events": [
            {"method": "place", "args": ["Maxwell", "greenery", "59"]}]}
        actions = execute.plan_actions(step)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["event"]["method"], "place")
        self.assertEqual(actions[0]["follow"]["space"], "59")

    def test_single_tile_card_is_unchanged(self):
        step = {"id": "1a", "events": [
            {"method": "play", "args": ["Maxwell", "Corporate Stronghold"],
             "kwargs": {"steel": 5}},
            {"method": "place", "args": ["Maxwell", "city", "53"]}]}
        actions = execute.plan_actions(step)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["follow"]["space"], "53")
        self.assertFalse(actions[0]["follow"].get("spaceQueue"))

    def test_follow_up_loop_answers_the_second_space_prompt(self):
        """The real failure: two consecutive `space` prompts, one action."""
        sent = []
        prompts = [
            {"type": "space", "title": "Select space for ocean",
             "spaces": ["28", "13", "04"]},
            {"type": "space", "title": "Select space for second ocean",
             "spaces": ["13", "04"]},
            None,                                   # NOT WAITING -> done
        ]

        class Client:
            def player(self, pid):
                return {"waitingFor": prompts.pop(0)} if prompts else {}

        with mock.patch.object(execute, "_send",
                               side_effect=lambda c, p, r, w, o: sent.append(r)):
            follow = {"space": "28", "spaceQueue": ["13"],
                      "or": None, "player": None, "card": None}
            execute._answer_follow_ups(Client(), "pid", follow, out=lambda *a: None)

        self.assertEqual([s.get("spaceId") for s in sent], ["28", "13"],
                         "both oceans must be placed without a manual resolve")


if __name__ == "__main__":
    unittest.main()
