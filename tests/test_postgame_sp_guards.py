"""Post-game items 4b + 4c — standard projects.

4b. A standard project whose ONLY effect is raising a parameter that is
    already at its maximum buys nothing. In the practice game the
    temperature track filled during the opponent's turn between the plan
    being set and the steps executing; two SP Asteroids were transmitted,
    the app took 28 M€ and granted no TR. The menu must not offer such a
    project and — because the track fills BETWEEN plan and execution —
    the executor must re-check the live parameter before transmitting.

    The distinction that matters: SP Aquifer with the ocean track full is
    genuinely zero-effect (the app suppresses the tile too), while SP
    Greenery with oxygen maxed still places a tile worth VP.

4c. Standard projects must consult THE payment model (tmlib.split_payment,
    which already knows which corporations spend heat as megacredits), so
    the tracker never refuses an event the app accepts.
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tmlib import Engine, EventError, Store          # noqa: E402
import menu                                          # noqa: E402
import execute                                       # noqa: E402
from test_new_game import SETUP                      # noqa: E402
from test_execute import (ExecuteCase, root_menu, view_from_game,  # noqa: E402
                          PASS)

MAXED = {"temperature": 8, "oxygen": 14, "oceans": 9}


def _store(tmpdir, corp: str | None = None, mc: int = 40,
           heat: int = 0) -> Store:
    store = Store(tmpdir)
    store.init(copy.deepcopy(SETUP))
    eng = Engine(store)
    if corp:
        eng.corp("Zed", corp, mc=mc)
    else:
        eng.res("Zed", "mc", +mc)
    if heat:
        eng.res("Zed", "heat", +heat)
    return store


def _max(game: dict, *params: str) -> dict:
    for p in params:
        game["globals"][p] = MAXED[p]
    return game


# ── 4b (a): the menu ──────────────────────────────────────────

class TestMenuDropsZeroEffectStandardProjects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = _store(self.tmp.name, mc=60)
        self.addCleanup(self.tmp.cleanup)

    def _names(self, game):
        return {i["name"] for i in menu.available_actions(game, self.store.load_setup())
                if i["kind"] == "standard"}

    def _item(self, game, name):
        return next(i for i in menu.available_actions(game, self.store.load_setup())
                    if i["kind"] == "standard" and i["name"] == name)

    def test_asteroid_is_offered_while_the_temperature_track_has_room(self):
        self.assertIn("asteroid", self._names(self.store.load_game()))

    def test_asteroid_is_not_offered_once_the_temperature_track_is_full(self):
        game = _max(self.store.load_game(), "temperature")
        self.assertNotIn("asteroid", self._names(game),
                         "SP asteroid at +8 °C is 14 M€ for nothing")

    def test_aquifer_is_not_offered_once_the_ocean_track_is_full(self):
        # the app suppresses the tile as well ("oceans maxed at 9/9 — the
        # ocean is SUPPRESSED"), so nothing at all happens
        game = _max(self.store.load_game(), "oceans")
        self.assertNotIn("aquifer", self._names(game))

    def test_greenery_is_still_offered_with_oxygen_maxed_because_of_the_tile(self):
        game = _max(self.store.load_game(), "oxygen")
        self.assertIn("greenery", self._names(game),
                      "the greenery tile is VP even with no oxygen left to gain")
        detail = self._item(game, "greenery")["detail"].lower()
        self.assertIn("maxed", detail)

    def test_city_and_power_plant_are_unaffected_by_maxed_globals(self):
        game = _max(self.store.load_game(), "temperature", "oxygen", "oceans")
        names = self._names(game)
        self.assertIn("power_plant", names)
        self.assertIn("city", names)


# ── 4b (b): the executor guard ────────────────────────────────

class TestZeroEffectClassifier(unittest.TestCase):
    """The rule itself: which standard projects lose everything when their
    parameter is full."""

    def test_asteroid_at_max_temperature_is_zero_effect(self):
        self.assertTrue(execute.zero_effect_standard("asteroid", MAXED))

    def test_aquifer_at_max_oceans_is_zero_effect(self):
        self.assertTrue(execute.zero_effect_standard("aquifer", MAXED))

    def test_greenery_at_max_oxygen_still_places_a_tile(self):
        self.assertIsNone(execute.zero_effect_standard("greenery", MAXED))

    def test_city_and_power_plant_are_never_zero_effect(self):
        for proj in ("city", "power_plant", "sell_patents"):
            self.assertIsNone(execute.zero_effect_standard(proj, MAXED), proj)

    def test_nothing_is_zero_effect_while_the_tracks_have_room(self):
        open_ = {"temperature": -20, "oxygen": 4, "oceans": 3}
        for proj in ("asteroid", "aquifer", "greenery"):
            self.assertIsNone(execute.zero_effect_standard(proj, open_), proj)


SP_ASTEROID_STEP = {"id": "1a", "summary": "SP asteroid", "volatility": "safe",
                    "events": [{"method": "standard", "args": ["Zed", "asteroid"]}]}
SP_GREENERY_STEP = {"id": "1a", "summary": "SP greenery on C4",
                    "volatility": "recheck", "cue": "red greenery on C4",
                    "events": [{"method": "standard", "args": ["Zed", "greenery"]},
                               {"method": "place", "args": ["Zed", "greenery", "C4"]}]}


class TestExecuteRefusesAMaxedStandardProject(ExecuteCase):
    def setUp(self):
        super().setUp()
        eng = Engine(self.store)
        eng.res("Zed", "mc", +30)                 # 60 M€: affordability is not the issue

    def _maxed_view(self, param: str, wf=None):
        game = self.game()
        game["globals"][param] = MAXED[param]
        Store._write_json(self.store.game_path, game)
        return view_from_game(self.game(), wf or root_menu())

    def test_asteroid_is_refused_before_anything_is_sent(self):
        self.set_plan([SP_ASTEROID_STEP, PASS])
        view = self._maxed_view("temperature")
        app = self.start_app([view, view])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [], "the guard must refuse BEFORE transmitting")
        self.assertIn("nothing sent", out)
        self.assertIn("temperature", out.lower())
        self.assertFalse(self.plan_step("1a").get("done"))
        self.assertEqual(self.game()["me"]["resources"]["mc"], 60)

    def test_force_overrides_and_logs_the_reason(self):
        self.set_plan([SP_ASTEROID_STEP, PASS])
        view = self._maxed_view("temperature")
        app = self.start_app([view, view])
        rc, out = self.run_cli("step", "1a", "--force",
                               "app shows +6 °C, the tracker is stale")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1, "--force must transmit")
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("app shows +6 °C, the tracker is stale", log)

    def test_greenery_with_oxygen_maxed_is_still_sent(self):
        self.set_plan([SP_GREENERY_STEP, PASS])
        view = self._maxed_view("oxygen")
        app = self.start_app([view, view, view])
        rc, out = self.run_cli("step", "1a", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("ZERO-EFFECT", out)


# ── 4c: heat as megacredits for standard projects ─────────────

class TestStandardProjectPaysWithHeat(unittest.TestCase):
    """Item 4c: the tracker refused SP asteroid ('costs 14 M€, have 12')
    while the app took it — the corporation may spend heat as money. The
    rule lives in THE payment model, never in a corporation branch here."""

    def _engine(self, corp, mc, heat):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = _store(tmp.name, corp=corp, mc=mc, heat=heat)
        return Engine(store), store

    def test_a_heat_spending_corp_covers_the_shortfall_with_heat(self):
        eng, store = self._engine("Helion", mc=12, heat=10)
        msg = eng.standard("Zed", "asteroid")
        res = store.load_game()["me"]["resources"]
        self.assertEqual(res["mc"], 0, msg)
        self.assertEqual(res["heat"], 8, msg)     # 14 = 12 M€ + 2 heat
        self.assertIn("heat", msg)

    def test_the_same_corp_still_prefers_megacredits(self):
        eng, store = self._engine("Helion", mc=30, heat=10)
        eng.standard("Zed", "asteroid")
        res = store.load_game()["me"]["resources"]
        self.assertEqual(res["mc"], 16)
        self.assertEqual(res["heat"], 10, "heat is spent only for the shortfall")

    def test_a_normal_corp_with_the_same_wallet_is_still_refused(self):
        eng, _ = self._engine("Teractor", mc=12, heat=10)
        with self.assertRaises(EventError) as cm:
            eng.standard("Zed", "asteroid")
        self.assertIn("14", str(cm.exception))

    def test_a_heat_spending_corp_short_on_both_is_still_refused(self):
        eng, _ = self._engine("Helion", mc=5, heat=5)
        with self.assertRaises(EventError):
            eng.standard("Zed", "asteroid")

    def test_the_charge_matches_the_payload_the_executor_sends(self):
        eng, store = self._engine("Helion", mc=12, heat=10)
        game = store.load_game()
        pay = execute._payment_split(game, 14)
        eng.standard("Zed", "asteroid")
        res = store.load_game()["me"]["resources"]
        self.assertEqual(pay, {"mc": 12, "heat": 2})
        self.assertEqual(game["me"]["resources"]["mc"] - res["mc"], pay["mc"])
        self.assertEqual(game["me"]["resources"]["heat"] - res["heat"], pay["heat"])

    def test_the_menu_offers_a_standard_project_heat_can_pay_for(self):
        _, store = self._engine("Helion", mc=12, heat=10)
        game = store.load_game()
        names = {i["name"] for i in menu.available_actions(game, store.load_setup())
                 if i["kind"] == "standard"}
        self.assertIn("asteroid", names)


if __name__ == "__main__":
    unittest.main()
