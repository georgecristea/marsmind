"""Sparring driver: response builders for the open-source app's input API."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sparring


class TestResponseBuilders(unittest.TestCase):
    def test_option_response(self):
        self.assertEqual(sparring.option(), {"type": "option"})

    def test_or_wraps_index_and_child(self):
        r = sparring.or_choice(2, sparring.option())
        self.assertEqual(r, {"type": "or", "index": 2,
                             "response": {"type": "option"}})

    def test_card_selection(self):
        self.assertEqual(sparring.cards(["Comet"]),
                         {"type": "card", "cards": ["Comet"]})

    def test_project_card_with_payment(self):
        r = sparring.project_card("Comet", mc=21)
        self.assertEqual(r["type"], "projectCard")
        self.assertEqual(r["card"], "Comet")
        self.assertEqual(r["payment"]["megacredits"], 21)
        self.assertEqual(r["payment"]["steel"], 0)

    def test_space(self):
        self.assertEqual(sparring.space("28"), {"type": "space", "spaceId": "28"})

    def test_payment_only(self):
        r = sparring.payment(mc=14, steel=2)
        self.assertEqual(r["payment"]["steel"], 2)

    def test_find_or_index_matches_title_substring(self):
        wf = {"type": "or", "options": [
            {"title": "End Turn"}, {"title": "Standard projects"},
            {"title": "Pass for this generation"}]}
        self.assertEqual(sparring.find_option(wf, "standard"), 1)
        self.assertEqual(sparring.find_option(wf, "pass"), 2)
        with self.assertRaises(KeyError):
            sparring.find_option(wf, "sell")


class TestUrlFlag(unittest.TestCase):
    """--url / $PHOBOS_APP_URL pick the app; every verb goes through the
    one AppClient in scripts/appapi.py bound to that base."""

    def setUp(self):
        self._base = sparring.BASE

    def tearDown(self):
        sparring.BASE = self._base

    def test_url_flag_sets_base_for_the_whole_run(self):
        from unittest import mock
        seen = []
        with mock.patch.object(sparring, "describe_waiting",
                               side_effect=lambda pid: seen.append(sparring.BASE) or "x"), \
             mock.patch("sys.argv", ["sparring.py", "--url", "http://h:1/",
                                     "state", "p1"]):
            self.assertEqual(sparring.main(), 0)
        self.assertEqual(seen, ["http://h:1"])

    def test_client_is_bound_to_base(self):
        sparring.BASE = "http://h:2"
        c = sparring.client()
        self.assertIsInstance(c, sparring.AppClient)
        self.assertEqual(c.base_url, "http://h:2")


if __name__ == "__main__":
    unittest.main()


class TestPlayCardResponse(unittest.TestCase):
    """Callers had to hardcode the index of the 'Play project card'
    option, but the option list is BOARD-DEPENDENT — the moment a seat holds
    8+ plants the app prepends a 'Convert plants into greenery' option and
    every index shifts by one. That produced a silent HTTP 400 mid-game.
    The index must be looked up by title, never assumed."""

    WF_NO_CONVERT = {"options": [
        {"title": "Play project card", "type": "projectCard"},
        {"title": "Standard projects", "type": "projectCard"},
        {"title": "Pass for this generation", "type": "option"},
    ]}
    WF_WITH_CONVERT = {"options": [
        {"title": {"message": "Convert ${0} plants into greenery",
                   "data": [{"type": 1, "value": "7"}]}, "type": "space"},
        {"title": "Play project card", "type": "projectCard"},
        {"title": "Standard projects", "type": "projectCard"},
        {"title": "Pass for this generation", "type": "option"},
    ]}

    def test_index_shifts_when_a_convert_option_appears(self):
        self.assertEqual(sparring.find_option(self.WF_NO_CONVERT,
                                              "play project card"), 0)
        self.assertEqual(sparring.find_option(self.WF_WITH_CONVERT,
                                              "play project card"), 1)

    def test_play_card_builds_the_right_or_wrapped_response(self):
        r = sparring.play_card(self.WF_WITH_CONVERT, "Giant Ice Asteroid",
                               mc=34)
        self.assertEqual(r["type"], "or")
        self.assertEqual(r["index"], 1)
        self.assertEqual(r["response"]["type"], "projectCard")
        self.assertEqual(r["response"]["card"], "Giant Ice Asteroid")
        self.assertEqual(r["response"]["payment"]["megacredits"], 34)

    def test_play_card_carries_metal_payment(self):
        r = sparring.play_card(self.WF_NO_CONVERT, "Mining Rights",
                               mc=1, steel=4)
        self.assertEqual(r["index"], 0)
        self.assertEqual(r["response"]["payment"]["steel"], 4)
        self.assertEqual(r["response"]["payment"]["megacredits"], 1)


class TestPromptShapeBuilders(unittest.TestCase):
    """Seats lost hundreds of MC of plays to HTTP 400s because these
    prompt shapes had no verb. Shapes below are captured from the live app."""

    MENU = {"type": "or", "title": "Take action for action phase", "options": [
        {"title": "Play project card", "type": "projectCard"},
        {"title": "Claim a milestone", "type": "or", "options": [
            {"title": "Gardener", "type": "option"},
            {"title": "Mayor", "type": "option"}]},
        {"title": {"message": "Fund an award (${0} M€)",
                   "data": [{"type": 1, "value": "8"}]}, "type": "or",
         "options": [{"title": "Scientist", "type": "option"},
                     {"title": "Banker", "type": "option"}]},
        {"title": "Perform an action from a played card", "type": "card",
         "cards": [{"name": "Water Import From Europa"},
                   {"name": "Inventors' Guild"}]},
        {"title": "Standard projects", "type": "projectCard", "cards": [
            {"name": "Power Plant:SP"}, {"name": "Asteroid:SP"},
            {"name": "Aquifer", "isDisabled": True}]},
        {"title": "Pass for this generation", "type": "option"},
    ]}
    CHOICE = {"type": "or", "title": "Select one option", "options": [
        {"title": {"message": "Add resource to card ${0}",
                   "data": [{"type": 2, "value": "Viral Enhancers"}]},
         "type": "option"},
        {"title": "Gain plant", "type": "option"}]}

    def test_nested_or(self):
        self.assertEqual(sparring.nested_or(1, 0), {
            "type": "or", "index": 1, "response": {
                "type": "or", "index": 0, "response": {"type": "option"}}})

    def test_claim_milestone(self):
        self.assertEqual(sparring.claim_milestone(self.MENU, "Mayor"),
                         sparring.nested_or(1, 1))
        with self.assertRaisesRegex(KeyError, "Gardener"):
            sparring.claim_milestone(self.MENU, "Builder")

    def test_fund_award_matches_templated_title(self):
        self.assertEqual(sparring.fund_award(self.MENU, "banker"),
                         sparring.nested_or(2, 1))

    def test_card_action(self):
        self.assertEqual(
            sparring.card_action(self.MENU, "Inventors' Guild"),
            {"type": "or", "index": 3,
             "response": {"type": "card", "cards": ["Inventors' Guild"]}})
        with self.assertRaisesRegex(KeyError, "Water Import From Europa"):
            sparring.card_action(self.MENU, "Herbivores")

    def test_choose_by_index_or_title(self):
        self.assertEqual(sparring.choose(self.CHOICE, 1),
                         sparring.or_choice(1, sparring.option()))
        self.assertEqual(sparring.choose(self.CHOICE, "viral"),
                         sparring.or_choice(0, sparring.option()))

    def test_target_player(self):
        self.assertEqual(sparring.target_player("green"),
                         {"type": "player", "player": "green"})

    def test_shape_lists_type_title_and_option_titles(self):
        s = sparring.shape(self.MENU)
        self.assertIn("type: or | title: Take action", s)
        self.assertIn("[2] Fund an award (8 M€)", s)
        self.assertEqual(sparring.shape(None), "NOT WAITING (opponent's move)")


class TestFollowUp(unittest.TestCase):
    """After play/sp the NEXT waitingFor may be a space / or / player
    prompt; the flags answer one hop each, then stop."""

    def _run(self, states, **flags):
        it = iter(states)
        sent = []
        sparring.follow_up("p1", get=lambda pid: next(it),
                           post=lambda pid, r: sent.append(r), **flags)
        return sent

    def test_space_then_choice_then_stop(self):
        sp = {"waitingFor": {"type": "space", "title": "Select space for Mangrove",
                             "spaces": ["33", "34"]}}
        ch = {"waitingFor": TestPromptShapeBuilders.CHOICE}
        menu = {"waitingFor": TestPromptShapeBuilders.MENU}
        sent = self._run([sp, ch, menu], space_id="33", choice=1)
        self.assertEqual(sent, [sparring.space("33"),
                                sparring.or_choice(1, sparring.option())])

    def test_player_target(self):
        pl = {"waitingFor": {"type": "player", "title": {"message": "Select player"},
                             "players": ["red", "green"]}}
        sent = self._run([pl, {"waitingFor": None}], target="green")
        self.assertEqual(sent, [sparring.target_player("green")])

    def test_no_flag_sends_nothing(self):
        sp = {"waitingFor": {"type": "space", "spaces": ["33"]}}
        self.assertEqual(self._run([sp]), [])


class TestSend400(unittest.TestCase):
    def test_400_prints_current_shape_to_stderr(self):
        import io, urllib.error
        from unittest import mock
        err = urllib.error.HTTPError("u", 400, "Bad Request", {},
                                     io.BytesIO(b'{"message":"Not a valid space"}'))
        wf = {"type": "space", "title": "Select space", "spaces": ["33"]}
        buf = io.StringIO()
        with mock.patch.object(sparring.appapi.urllib.request, "urlopen",
                               side_effect=err), \
             mock.patch.object(sparring, "get_player",
                               return_value={"waitingFor": wf}), \
             mock.patch("sys.stderr", buf), \
             self.assertRaises(urllib.error.HTTPError):
            sparring.send("p1", sparring.space("99"))
        self.assertIn("Not a valid space", buf.getvalue())
        self.assertIn("type: space | title: Select space", buf.getvalue())


class TestChooseByPlayerName(unittest.TestCase):
    """P8 #21: on a removal prompt the option titles name the COLOR
    ('Remove 7 plants from red'), so `choose <pid> "Anna"` raised KeyError
    and the seat lost the action."""

    REMOVE = {"type": "or", "title": "Select one option", "options": [
        {"title": {"message": "Remove ${0} plants from ${1}",
                   "data": [{"type": 1, "value": "7"},
                            {"type": 1, "value": "red"}]}, "type": "option"},
        {"title": "Remove 2 plants from yellow", "type": "option"},
        {"title": "Do not remove plants", "type": "option"}]}
    PLAYERS = [{"name": "Anna", "color": "red"},
               {"name": "Ben", "color": "yellow"},
               {"name": "Zed", "color": "green"}]

    def test_player_name_matches_its_color_in_the_title(self):
        self.assertEqual(sparring.find_option(self.REMOVE, "Anna",
                                              players=self.PLAYERS), 0)
        self.assertEqual(sparring.find_option(self.REMOVE, "ben",
                                              players=self.PLAYERS), 1)

    def test_choose_accepts_a_player_name(self):
        self.assertEqual(sparring.choose(self.REMOVE, "Anna",
                                         players=self.PLAYERS),
                         sparring.or_choice(0, sparring.option()))

    def test_index_and_substring_matching_still_work(self):
        self.assertEqual(sparring.choose(self.REMOVE, 2),
                         sparring.or_choice(2, sparring.option()))
        self.assertEqual(sparring.choose(self.REMOVE, "yellow"),
                         sparring.or_choice(1, sparring.option()))
        self.assertEqual(sparring.choose(self.REMOVE, "do not remove"),
                         sparring.or_choice(2, sparring.option()))

    def test_color_word_is_matched_whole(self):
        wf = {"options": [{"title": "Do not remove plants", "type": "option"},
                          {"title": "Remove 3 plants from red", "type": "option"}]}
        self.assertEqual(sparring.find_option(wf, "Anna", players=self.PLAYERS), 1)

    def test_unknown_name_still_raises_with_the_option_titles(self):
        with self.assertRaisesRegex(KeyError, "Remove 2 plants from yellow"):
            sparring.find_option(self.REMOVE, "Carl", players=self.PLAYERS)

    def test_falls_back_to_setup_json_when_no_view_players(self):
        import json, tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            setup = Path(d) / "setup.json"
            setup.write_text(json.dumps({"players": self.PLAYERS}))
            with mock.patch.object(sparring, "SETUP_PATH", setup):
                self.assertEqual(sparring.find_option(self.REMOVE, "Anna"), 0)

    def test_missing_setup_file_is_not_an_error(self):
        from unittest import mock
        with mock.patch.object(sparring, "SETUP_PATH",
                               Path("/nonexistent/setup.json")):
            with self.assertRaises(KeyError):
                sparring.find_option(self.REMOVE, "Anna")

    def test_cli_choose_passes_the_view_players(self):
        import io
        from unittest import mock
        view = {"waitingFor": self.REMOVE, "players": self.PLAYERS,
                "thisPlayer": {}, "game": {"generation": 3}}
        sent = []
        with mock.patch.object(sparring, "get_player", return_value=view), \
             mock.patch.object(sparring, "send",
                               side_effect=lambda pid, r: sent.append(r)), \
             mock.patch("sys.argv", ["sparring.py", "choose", "p1", "Anna"]), \
             mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(sparring.main(), 0)
        self.assertEqual(sent, [sparring.or_choice(0, sparring.option())])


class TestScope(unittest.TestCase):
    """Seats played extra generations past their scope."""

    def test_scope_ended(self):
        self.assertFalse(sparring.scope_ended(
            {"game": {"generation": 5, "phase": "action"}}, 5))
        self.assertTrue(sparring.scope_ended(
            {"game": {"generation": 6, "phase": "action"}}, 5))
        self.assertTrue(sparring.scope_ended(
            {"game": {"generation": 5, "phase": "end"}}, 5))
        self.assertFalse(sparring.scope_ended(
            {"game": {"generation": 9, "phase": "action"}}, None))

    def test_wait_until_gen_exits_3(self):
        import io
        from unittest import mock
        d = {"waitingFor": {"type": "or", "options": []},
             "game": {"generation": 7, "phase": "action"}}
        buf = io.StringIO()
        with mock.patch.object(sparring, "get_player", return_value=d), \
             mock.patch("sys.argv", ["sparring.py", "wait", "p1",
                                     "--until-gen", "6"]), \
             mock.patch("sys.stdout", buf):
            self.assertEqual(sparring.main(), 3)
        self.assertIn("SCOPE END — generation 7 > 6", buf.getvalue())

    def test_describe_waiting_prefixes_generation(self):
        from unittest import mock
        d = {"waitingFor": {"type": "or", "title": "t", "options": []},
             "thisPlayer": {}, "game": {"generation": 4}}
        with mock.patch.object(sparring, "get_player", return_value=d):
            self.assertTrue(sparring.describe_waiting("p1").startswith("gen 4 | "))


class TestWaitForTurn(unittest.TestCase):
    """Speedup: `sparring.py wait <pid>` blocks server-side (silent 2s
    polls inside ONE tool call) instead of the old pattern of one model
    round-trip per poll — the dominant wall-clock cost of a game."""

    @staticmethod
    def _mk(states):
        """get_player stub yielding successive player dicts."""
        it = iter(states)
        return lambda pid: next(it)

    def test_returns_immediately_when_turn_is_live(self):
        d = {"waitingFor": {"type": "or"}, "game": {"phase": "action"}}
        out = sparring.wait_for_turn("p1", get=self._mk([d]),
                                     sleep=lambda s: None)
        self.assertEqual(out["waitingFor"], {"type": "or"})

    def test_polls_until_waiting_for_appears(self):
        idle = {"waitingFor": None, "game": {"phase": "action"}}
        live = {"waitingFor": {"type": "card"}, "game": {"phase": "action"}}
        naps = []
        out = sparring.wait_for_turn("p1",
                                     get=self._mk([idle, idle, live]),
                                     sleep=naps.append, interval=2)
        self.assertEqual(out["waitingFor"], {"type": "card"})
        self.assertEqual(naps, [2, 2])

    def test_returns_on_game_end_without_a_turn(self):
        idle = {"waitingFor": None, "game": {"phase": "action"}}
        ended = {"waitingFor": None, "game": {"phase": "end"}}
        out = sparring.wait_for_turn("p1", get=self._mk([idle, ended]),
                                     sleep=lambda s: None)
        self.assertEqual(out["game"]["phase"], "end")

    def test_times_out_to_none(self):
        idle = {"waitingFor": None, "game": {"phase": "action"}}
        t = iter(range(0, 1000, 100))          # fake clock: +100s per call
        out = sparring.wait_for_turn("p1", get=self._mk([idle] * 20),
                                     sleep=lambda s: None,
                                     clock=lambda: next(t), timeout=250)
        self.assertIsNone(out)
