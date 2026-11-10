"""P7 autopilot game (2026-08-28) — regression tests for every defect the
first full API-autopilot game surfaced. Each test names the observed
symptom so a future reader can tie it back to that game's log.

The tracking cluster is the important one: per-player tile COUNTERS drifted
away from `game["board"]`, which was correct in every observed case. The
drift inverted an award race, produced a false milestone alert, and
corrupted a card's arithmetic.
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import applog_parser as P                        # noqa: E402
import menu                                      # noqa: E402
import replay_applog as R                        # noqa: E402
from tmlib import Engine, Store                  # noqa: E402
from test_new_game import SETUP                  # noqa: E402


def _setup() -> dict:
    s = json.loads(json.dumps(SETUP))
    s["gameMode"] = "app-practice"
    return s


class ReplayCase(unittest.TestCase):
    """Drives the real replayer over parsed app-log lines, exactly as the
    listener does — one `feed()` call per drain."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(_setup())
        self.eng = Engine(self.store)
        self.rep = R.Report()
        self.replayer = R.Replayer(self.eng, self.rep, verbose=False)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _normalize(blocks: list[dict]) -> list[dict]:
        """Mirror of listen.Listener.normalize for the branch these tests
        exercise: a drain that starts with a consequence line (its head was
        applied in an earlier drain) becomes a `late_tail` block."""
        out = []
        for b in blocks:
            head, tail = b["head"], b["tail"]
            if head["kind"] not in P.HEAD_KINDS and head["kind"] != "final_placed":
                out.append({"head": {"kind": "late_tail",
                                     "player": head.get("player"),
                                     "line": head["line"],
                                     "raw": head.get("raw", "")},
                            "tail": [head, *tail], "events": None})
            else:
                out.append(b)
        return out

    def feed(self, *lines: str) -> None:
        """One drain: parse these lines and replay every block, through the
        same normalize step the live listener applies."""
        players = [p["name"] for p in self.store.load_setup()["players"]]
        events = P.parse_log("\n".join(lines), players)
        for b in self._normalize(P.group_blocks(events)):
            with redirect_stdout(io.StringIO()):
                self.replayer.block(b)

    def game(self):
        return self.store.load_game()

    def pool(self, name):
        g = self.game()
        return g["me"] if name == g["me"]["name"] else g["opponents"][name]

    def board_count(self, name, tile):
        return sum(1 for v in (self.game().get("board") or {}).values()
                   if v["player"] == name and v["tile"] == tile)


class TestTileCounterDoubleCount(ReplayCase):
    """T1 — observed: 'Carl used City standard project' then, in a LATER
    drain, 'Carl placed city tile at 15' left the tracker on 2 cities while
    the board held exactly 1. replay_applog.tile_counters() compared a
    per-BLOCK delta, so a placement whose counter bump happened in an
    earlier block looked unaccounted for and was force-added again."""

    def test_standard_city_then_place_in_a_later_drain_counts_once(self):
        self.feed("Anna used City standard project")
        self.feed("Anna placed city tile at 15")
        self.assertEqual(self.board_count("Anna", "city"), 1)
        self.assertEqual(self.pool("Anna")["tiles"]["cities"], 1)

    def test_played_city_card_then_place_in_a_later_drain_counts_once(self):
        self.feed("Anna played Cupola City")
        self.feed("Anna placed city tile at 15")
        self.assertEqual(self.board_count("Anna", "city"), 1)
        self.assertEqual(self.pool("Anna")["tiles"]["cities"], 1)

    def test_same_block_placement_still_counts_once(self):
        """The already-working path must not regress."""
        self.feed("Anna played Cupola City", "Anna placed city tile at 15")
        self.assertEqual(self.pool("Anna")["tiles"]["cities"], 1)

    def test_greenery_across_drains_counts_once(self):
        self.feed("Anna used Greenery standard project")
        self.feed("Anna placed greenery tile at 15")
        self.assertEqual(self.pool("Anna")["tiles"]["greeneries"], 1)

    def test_two_real_cities_count_two(self):
        """Reconciliation must not clamp genuine growth."""
        self.feed("Anna used City standard project")
        self.feed("Anna placed city tile at 15")
        self.feed("Anna used City standard project")
        self.feed("Anna placed city tile at 35")
        self.assertEqual(self.board_count("Anna", "city"), 2)
        self.assertEqual(self.pool("Anna")["tiles"]["cities"], 2)


class TestSpecialTileCounter(ReplayCase):
    """T2 — observed: me.tiles.special stayed 0 while board['38'] held my
    Commercial District. Landlord is sum(tiles.values()), so an uncounted
    special tile silently deflates the award metric."""

    def test_special_tile_reaches_the_counter(self):
        self.feed("Anna played Commercial District",
                  "Anna placed Commercial District tile at 15")
        self.assertEqual(self.pool("Anna")["tiles"].get("special", 0), 1)

    def test_landlord_metric_includes_special_tiles(self):
        self.feed("Anna played Commercial District",
                  "Anna placed Commercial District tile at 15")
        m = menu.award_metrics(self.game(), "Anna")
        self.assertEqual(m["Landlord"], 1)

    def test_landlord_is_not_inverted_by_counter_drift(self):
        """T3 — the exact inversion seen in game 1: the brief printed
        'Landlord: Anna 2 > Zed 1' when the truth was Zed 2 > Anna 1."""
        self.feed("Zed played Commercial District",
                  "Zed placed Commercial District tile at 15")
        self.feed("Zed used City standard project")
        self.feed("Zed placed city tile at 35")
        self.feed("Anna played Cupola City")
        self.feed("Anna placed city tile at 03")
        g = self.game()
        self.assertGreater(menu.award_metrics(g, "Zed")["Landlord"],
                           menu.award_metrics(g, "Anna")["Landlord"])


class TestCitiesInPlayArithmetic(ReplayCase):
    """T4 — the escalation. Greenhouses grants 1 plant per city tile IN
    PLAY. With Anna and Carl each double-counted the engine computed 6
    cities where the board held 4, so `execute.py` exited 41 on a card
    whose arithmetic was simply wrong. Any tile-count-driven effect
    (Immigrant City, Zeppelins, city-count production) had the same flaw."""

    def test_cities_in_play_matches_the_board(self):
        self.feed("Anna used City standard project")
        self.feed("Anna placed city tile at 15")
        self.feed("Felix used City standard project")
        self.feed("Felix placed city tile at 35")
        g = self.game()
        board_cities = sum(1 for v in (g.get("board") or {}).values()
                           if v["tile"] == "city")
        self.assertEqual(board_cities, 2)
        self.assertEqual(self.eng._cities_in_play(g), 2)


class TestFeedGrammarBecauseOfCard(unittest.TestCase):
    """T5 — 'Ben gained 1 plant because of Viral Enhancers' was unparsed
    and silently dropped (seen twice). The bare 'X gained N plants' form
    already parsed; only the trailing cause clause was unhandled."""

    PLAYERS = ["Zed", "Anna", "Felix"]

    def test_gained_with_because_of_clause_parses(self):
        ev = P.parse_line("Anna gained 1 plant because of Viral Enhancers",
                          self.PLAYERS)
        self.assertEqual(ev["kind"], "gained")
        self.assertEqual(ev["player"], "Anna")
        self.assertEqual(ev["n"], 1)
        self.assertEqual(ev["resource"], "plants")
        self.assertEqual(ev["source"], "Viral Enhancers")

    def test_lost_with_because_of_clause_parses(self):
        """'Zed lost 8 plants because of Carl' — the attack form, which
        names a PLAYER rather than a card as the cause."""
        ev = P.parse_line("Zed lost 8 plants because of Anna", self.PLAYERS)
        self.assertEqual(ev["kind"], "lost")
        self.assertEqual(ev["n"], 8)
        self.assertEqual(ev["resource"], "plants")

    def test_from_card_clause_still_parses(self):
        ev = P.parse_line("Anna gained 2 plants from Arctic Algae",
                          self.PLAYERS)
        self.assertEqual(ev["kind"], "gained")
        self.assertEqual(ev["n"], 2)
        self.assertEqual(ev["resource"], "plants")

    def test_plain_form_still_parses(self):
        ev = P.parse_line("Anna gained 3 plants", self.PLAYERS)
        self.assertEqual(ev["kind"], "gained")
        self.assertEqual(ev["n"], 3)


class TestGainedBecauseOfIsApplied(ReplayCase):
    def test_resource_reaches_the_tracker(self):
        before = self.pool("Anna")["resources"]["plants"]
        self.feed("Anna gained 2 plants because of Viral Enhancers")
        self.assertEqual(self.pool("Anna")["resources"]["plants"], before + 2)


class TestVerifyTileReconciliation(ReplayCase):
    """The fix that matters most at a PHYSICAL table. verify.py compared
    only MC / TR / production / hand, so the whole tile-counter class was
    invisible to it — and at a real table there is no app to diff against.
    `board_drift` is an INTERNAL consistency check: the tracker's own board
    record versus its own derived counters, so it needs no app at all."""

    def _corrupt(self, player, key, value):
        g = self.game()
        pool = g["me"] if player == g["me"]["name"] else g["opponents"][player]
        pool["tiles"][key] = value
        self.store.save_game(g)

    def test_clean_state_reports_no_drift(self):
        import verify
        self.feed("Anna played Cupola City", "Anna placed city tile at 15")
        self.assertEqual(verify.board_drift(self.eng, ["Anna"]), [])

    def test_inflated_city_counter_is_reported(self):
        import verify
        self.feed("Anna played Cupola City", "Anna placed city tile at 15")
        self._corrupt("Anna", "cities", 2)
        rows = verify.board_drift(self.eng, ["Anna"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["player"], "Anna")
        self.assertEqual(rows[0]["drift"]["tiles.cities"], (2, 1))

    def test_uncounted_special_tile_is_reported(self):
        import verify
        self.feed("Anna played Commercial District",
                  "Anna placed Commercial District tile at 15")
        self._corrupt("Anna", "special", 0)
        rows = verify.board_drift(self.eng, ["Anna"])
        self.assertEqual(rows[0]["drift"]["tiles.special"], (0, 1))

    def test_sync_repairs_the_counter(self):
        import verify
        self.feed("Anna played Cupola City", "Anna placed city tile at 15")
        self._corrupt("Anna", "cities", 5)
        verify.sync_board(self.eng, ["Anna"])
        self.assertEqual(self.pool("Anna")["tiles"]["cities"], 1)
        self.assertEqual(verify.board_drift(self.eng, ["Anna"]), [])

    def test_oceans_are_owned_by_nobody(self):
        """Landlord must not count oceans — they belong to no player."""
        import verify
        self.feed("Anna used Aquifer standard project",
                  "Anna placed ocean tile at 01")
        rows = verify.board_drift(self.eng, ["Anna"])
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()


class PlanCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(_setup())
        eng = Engine(self.store)
        eng.res("Zed", "mc", +60)

    def tearDown(self):
        self.tmp.cleanup()

    def steps(self):
        import planlib
        return [s["id"] for s in planlib.load_plan(self.store)["steps"]]


class TestPatchRemoveBeforeInsert(PlanCase):
    """E3 — observed twice while replanning mid-generation: a patch that
    replaces a step with a differently-shaped one at the SAME label is the
    natural edit, but `seen` was seeded with every existing id before the
    removes were applied, so re-using the freed label raised
    'inserted step id 2b already exists' and cost a wasted round trip."""

    def setUp(self):
        super().setUp()
        import planlib
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "note", "volatility": "safe", "events": []},
            {"id": "2b", "summary": "old pass", "volatility": "safe",
             "events": [], "passGate": True}],
            threats="t", exit_="e; repeatable: n/a")

    def test_remove_then_reinsert_same_label(self):
        import planlib
        planlib.patch(self.store, {
            "remove": ["2b"],
            "insert_after": {"1a": [
                {"id": "2b", "summary": "new step", "volatility": "safe",
                 "events": [], "passGate": True}]}}, live=True)
        self.assertEqual(self.steps(), ["1a", "2b"])
        plan = planlib.load_plan(self.store)
        self.assertEqual(plan["steps"][1]["summary"], "new step")

    def test_duplicate_without_a_remove_still_refused(self):
        import planlib
        from tmlib import EventError
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"insert_after": {"1a": [
                {"id": "2b", "summary": "dupe", "volatility": "safe",
                 "events": []}]}}, live=True)


class TestStandardProjectNeedsItsPlacement(PlanCase):
    """P7 refusal #5: an SP Aquifer step carried {standard: aquifer} with
    no `place` event, so the executor discovered the uncovered `space`
    follow-up mid-send — with the input ALREADY transmitted. Aquifer,
    greenery and city ALWAYS place a tile, so the plan is knowably
    incomplete at set time and should be refused then."""

    def test_sp_aquifer_without_place_is_refused(self):
        import planlib
        from tmlib import EventError
        with self.assertRaises(EventError) as cm:
            planlib.set_plan(self.store, [
                {"id": "1a", "summary": "SP aquifer", "volatility": "recheck",
                 "events": [{"method": "standard", "args": ["Zed", "aquifer"]}]}],
                threats="t", exit_="e; repeatable: n/a")
        self.assertIn("place", str(cm.exception).lower())

    def test_sp_greenery_without_place_is_refused(self):
        import planlib
        from tmlib import EventError
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, [
                {"id": "1a", "summary": "SP greenery", "volatility": "recheck",
                 "events": [{"method": "standard", "args": ["Zed", "greenery"]}]}],
                threats="t", exit_="e; repeatable: n/a")

    def test_sp_with_place_is_accepted(self):
        import planlib
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "SP aquifer on 04", "volatility": "recheck",
             "cue": "ocean on 04",
             "events": [{"method": "standard", "args": ["Zed", "aquifer"]},
                        {"method": "place", "args": ["Zed", "ocean", "04"]}]}],
            threats="t", exit_="e; repeatable: n/a")
        self.assertEqual(self.steps(), ["1a"])

    def test_sp_without_a_tile_is_unaffected(self):
        import planlib
        planlib.set_plan(self.store, [
            {"id": "1a", "summary": "SP power plant", "volatility": "safe",
             "events": [{"method": "standard", "args": ["Zed", "power_plant"]}]}],
            threats="t", exit_="e; repeatable: n/a")
        self.assertEqual(self.steps(), ["1a"])


class TestSparringSpaceVerb(unittest.TestCase):
    """S1 — the single defect that produced the whole 'Haiku seats are
    inert' symptom. `--space` existed only as a FLAG on play/sp, so when
    the app asked for a board space as its OWN prompt a seat had no verb
    and had to hand-write raw JSON. Carl guessed {"space": "15"},
    {"type":"space","space":"15"} and nested or-forms for 79 tool calls /
    31 minutes, all rejected, then forfeited two generations. The only
    valid shape is {"type": "space", "spaceId": "15"}."""

    def test_space_helper_uses_spaceId(self):
        import sparring
        self.assertEqual(sparring.space("15"),
                         {"type": "space", "spaceId": "15"})

    def test_space_is_a_cli_verb(self):
        import sparring
        self.assertIn("space", sparring.VERBS)

    def test_choice_and_target_are_verbs_too(self):
        import sparring
        self.assertIn("choose", sparring.VERBS)
        self.assertIn("target", sparring.VERBS)

    def test_grid_ref_is_accepted(self):
        """Seats think in the app's grid labels, not internal hex ids."""
        import sparring
        self.assertEqual(sparring.space("C4")["spaceId"],
                         __import__("tmlib").grid_to_space("C4"))


class TestRejectionMessagesAreActionable(unittest.TestCase):
    """S2 — the app names the response CLASS it wanted, never the shape.
    'Not a valid SelectSpaceResponse' cost 31 minutes of guessing, and
    'Unknown card name X' convinced a seat the app was broken and ended
    its game. In truth the play prompt lists ONLY cards that are currently
    affordable AND requirement-satisfied, so that error means 'not
    playable right now'."""

    def _send_400(self, body: bytes, wf: dict, response: dict) -> str:
        import urllib.error
        from unittest import mock
        import sparring
        err = urllib.error.HTTPError("u", 400, "Bad Request", {},
                                     io.BytesIO(body))
        buf = io.StringIO()
        with mock.patch.object(sparring.appapi.urllib.request, "urlopen",
                               side_effect=err), \
             mock.patch.object(sparring, "get_player",
                               return_value={"waitingFor": wf}), \
             mock.patch("sys.stderr", buf), \
             self.assertRaises(urllib.error.HTTPError):
            sparring.send("p1", response)
        return buf.getvalue()

    def test_space_rejection_prints_the_expected_shape(self):
        import sparring
        out = self._send_400(b'{"message":"Not a valid SelectSpaceResponse"}',
                             {"type": "space", "title": "Select space",
                              "spaces": ["33"]},
                             {"space": "33"})
        self.assertIn('"spaceId"', out)

    def test_unknown_card_name_is_explained(self):
        import sparring
        out = self._send_400(b'{"message":"Unknown card name Livestock"}',
                             {"type": "or", "title": "Take your first action",
                              "options": []},
                             {"type": "or", "index": 0})
        low = out.lower()
        self.assertTrue("afford" in low or "requirement" in low, out)
        self.assertIn("not", low)


class TestOpponentChoiceCardIsRecorded(ReplayCase):
    """Feed gap #3 — 'Ben played Sabotage' was REFUSED by the replayer
    ('needs a victim: --target ... and a resource: --choice ...') so the
    card never entered Ben's tableau, even though the app's own follow-up
    line applied the effect. Opponent plays are OBSERVATIONAL: the log
    already carries the consequences, so the card must be recorded even
    when its interactive args are unknown."""

    def test_choice_card_enters_the_tableau(self):
        self.feed("Anna played Sabotage", "Felix lost 7 M€ because of Anna")
        played = [c["name"] if isinstance(c, dict) else c
                  for c in self.pool("Anna").get("playedCards", [])]
        self.assertIn("Sabotage", played)

    def test_the_consequence_still_applies(self):
        self.eng.res("Felix", "mc", +20)
        before = self.pool("Felix")["resources"]["mc"]
        self.feed("Anna played Sabotage", "Felix lost 7 M€ because of Anna")
        self.assertEqual(self.pool("Felix")["resources"]["mc"], before - 7)

    def test_it_is_not_reported_as_an_error(self):
        """The feed said applied:false on a line that was fine."""
        import listen
        self.feed("Anna played Sabotage", "Felix lost 7 M€ because of Anna")
        kinds = {g["kind"] for g in self.rep.gaps}
        self.assertNotIn("refused", kinds)
        self.assertTrue(kinds & {"observed"}, self.rep.gaps)
        self.assertFalse(kinds & set(listen.ERROR_GAPS), self.rep.gaps)
