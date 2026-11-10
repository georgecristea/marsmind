"""ONE payment splitter — `tmlib.split_payment`.

The audit found four independent implementations that already disagreed:
menu.py tried steel first, replay_applog.py titanium first and had no heat
term at all (so every Helion replay drifted), execute.py owned the MC→heat
split, and the engine did its own arithmetic inside `play`/`standard`.
Every caller now asks tmlib the same question and gets the same answer:

  MC first, the remainder from heat, and heat ONLY for a corporation whose
  rule says it spends heat as money (a `corp_rule` capability, never a
  name). Steel pays only for a building tag, titanium only for a space tag,
  unless the caller passes the amounts explicitly.
"""
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import execute
import menu
import replay_applog as R
import tmlib
from tmlib import Engine, Store
from test_new_game import SETUP


def _fresh():
    tmp = tempfile.TemporaryDirectory()
    store = Store(Path(tmp.name))
    store.init(SETUP)
    return Engine(store), tmp


ME = SETUP["players"][0]["name"]


class SplitPaymentTest(unittest.TestCase):
    def setUp(self):
        self.eng, self.tmp = _fresh()
        self.addCleanup(self.tmp.cleanup)

    def game(self):
        return self.eng.store.load_game()

    def stock(self, mc=0, heat=0, steel=0, titanium=0, corp=None):
        if corp:
            self.eng.corp(ME, corp, mc)
        else:
            r = self.game()["me"]["resources"]
            self.eng.res(ME, "mc", mc - r["mc"])
        for r, n in (("heat", heat), ("steel", steel), ("titanium", titanium)):
            if n:
                self.eng.res(ME, r, n)
        return self.game()

    def split(self, game, price, **kw):
        return tmlib.split_payment(game, ME, price, **kw)

    # ── the rule ────────────────────────────────────────────────────────
    def test_mc_only_without_a_heat_corporation(self):
        game = self.stock(mc=30, heat=20)
        self.assertEqual(self.split(game, 14),
                         {"mc": 14, "steel": 0, "titanium": 0, "heat": 0,
                          "shortfall": 0})

    def test_p8_helion_pays_an_asteroid_entirely_in_heat(self):
        game = self.stock(mc=0, heat=23, corp="Helion")
        self.assertEqual(self.split(game, 14),
                         {"mc": 0, "steel": 0, "titanium": 0, "heat": 14,
                          "shortfall": 0})

    def test_p8_helion_greenery_is_mc_first_then_heat(self):
        game = self.stock(mc=21, heat=18, corp="Helion")
        self.assertEqual(self.split(game, 23),
                         {"mc": 21, "steel": 0, "titanium": 0, "heat": 2,
                          "shortfall": 0})

    def test_heat_is_a_corp_rule_not_a_corp_name(self):
        game = self.stock(mc=0, heat=23, corp="Teractor")
        self.assertEqual(self.split(game, 14)["heat"], 0)
        self.assertEqual(self.split(game, 14)["shortfall"], 14)

    def test_steel_only_for_a_building_tag(self):
        game = self.stock(mc=20, steel=5, titanium=5)
        self.assertEqual(self.split(game, 12, tags=["building"]),
                         {"mc": 2, "steel": 5, "titanium": 0, "heat": 0,
                          "shortfall": 0})
        self.assertEqual(self.split(game, 12, tags=["science"])["steel"], 0)

    def test_titanium_only_for_a_space_tag(self):
        game = self.stock(mc=20, steel=5, titanium=5)
        self.assertEqual(self.split(game, 12, tags=["space"]),
                         {"mc": 0, "steel": 0, "titanium": 4, "heat": 0,
                          "shortfall": 0})
        self.assertEqual(self.split(game, 12, tags=["science"])["titanium"], 0)

    def test_explicit_amounts_are_honoured_untouched(self):
        game = self.stock(mc=20, steel=5, titanium=5)
        self.assertEqual(self.split(game, 12, steel=2, titanium=1),
                         {"mc": 5, "steel": 2, "titanium": 1, "heat": 0,
                          "shortfall": 0})

    def test_one_extra_ore_rather_than_not_playing(self):
        # 4 steel covers 8 of 9 and there is no MC for the last one: the
        # table over-pays with a fifth steel (the app allows it).
        game = self.stock(mc=0, steel=5)
        self.assertEqual(self.split(game, 9, tags=["building"]),
                         {"mc": 0, "steel": 5, "titanium": 0, "heat": 0,
                          "shortfall": 0})

    def test_shortfall_is_reported_never_hidden(self):
        game = self.stock(mc=3, heat=1, corp="Helion")
        pay = self.split(game, 14)
        self.assertEqual((pay["mc"], pay["heat"]), (13, 1))
        self.assertEqual(pay["shortfall"], 10)

    def test_the_split_is_deterministic(self):
        game = self.stock(mc=7, steel=4, titanium=4, heat=9, corp="Helion")
        first = self.split(game, 20, tags=["building", "space"])
        for _ in range(5):
            self.assertEqual(self.split(game, 20,
                                        tags=["building", "space"]), first)

    def test_a_card_can_be_named_instead_of_its_tags(self):
        game = self.stock(mc=20, steel=5)
        self.assertEqual(self.split(game, 9, card="Mining Rights"),
                         self.split(game, 9, tags=["building"]))


class EveryCallerAgreesTest(unittest.TestCase):
    """The same inputs, the same split, from all four callers."""

    def setUp(self):
        self.eng, self.tmp = _fresh()
        self.addCleanup(self.tmp.cleanup)

    def game(self):
        return self.eng.store.load_game()

    def test_heat_split_agrees_across_menu_executor_replayer_engine(self):
        self.eng.corp(ME, "Helion", 16)
        self.eng.res(ME, "heat", 5)
        game = self.game()
        info = self.eng.card("Power Grid")          # 18 MC, no metal tag
        want = tmlib.split_payment(game, ME, info["cost"], tags=info["tags"])
        self.assertEqual((want["mc"], want["heat"]), (16, 2))

        # executor (the app payload)
        self.assertEqual(execute._payment_split(game, info["cost"]),
                         {"mc": want["mc"], "heat": want["heat"]})
        # menu (the affordability line)
        ok, text = menu.payment(info["cost"], game["me"]["resources"],
                                info["tags"], "Helion")
        self.assertTrue(ok)
        self.assertEqual(text, "pay 16 MC + 2 heat")
        # replayer (the app's silent default)
        rp = R.Replayer(self.eng, R.Report(), verbose=False)
        self.assertEqual(rp.metal_payment(ME, info), (0, 0, want["heat"]))
        # engine (what actually leaves the pool)
        self.eng.hand_add(["Power Grid"])
        self.eng.play(ME, "Power Grid", heat=want["heat"])
        res = self.game()["me"]["resources"]
        self.assertEqual((res["mc"], res["heat"]), (0, 3))

    def test_metal_split_agrees_across_menu_replayer_engine(self):
        r = self.game()["me"]["resources"]
        self.eng.res(ME, "mc", 3 - r["mc"])
        self.eng.res(ME, "steel", 5)
        game = self.game()
        info = self.eng.card("Mining Rights")        # 9 MC, building tag
        want = tmlib.split_payment(game, ME, info["cost"], tags=info["tags"])
        self.assertEqual(want, {"mc": 1, "steel": 4, "titanium": 0,
                                "heat": 0, "shortfall": 0})

        ok, text = menu.payment(info["cost"], game["me"]["resources"],
                                info["tags"], None)
        self.assertTrue(ok)
        self.assertEqual(text, "pay 4 steel + 1 MC")
        rp = R.Replayer(self.eng, R.Report(), verbose=False)
        self.assertEqual(rp.metal_payment(ME, info),
                         (want["steel"], want["titanium"], want["heat"]))
        self.eng.hand_add(["Mining Rights"])
        self.eng.play(ME, "Mining Rights", steel=want["steel"])
        res = self.game()["me"]["resources"]
        self.assertEqual((res["mc"], res["steel"]), (2, 1))

    def test_the_replayer_no_longer_prefers_titanium_over_steel(self):
        # the one card with both tags: every caller spends the cheaper ore
        # first so titanium stays for the space cards only it can pay.
        r = self.game()["me"]["resources"]
        self.eng.res(ME, "mc", 30 - r["mc"])
        self.eng.res(ME, "steel", 6)
        self.eng.res(ME, "titanium", 6)
        game = self.game()
        info = self.eng.card("Space Elevator")
        want = tmlib.split_payment(game, ME, info["cost"], tags=info["tags"])
        rp = R.Replayer(self.eng, R.Report(), verbose=False)
        self.assertEqual(rp.metal_payment(ME, info),
                         (want["steel"], want["titanium"], want["heat"]))
        self.assertEqual(want["steel"], 6)

    def test_standard_project_split_agrees_engine_and_replayer(self):
        self.eng.corp(ME, "Helion", 10)
        self.eng.res(ME, "heat", 20)
        game = self.game()
        want = tmlib.split_payment(game, ME, 14)      # asteroid
        self.assertEqual((want["mc"], want["heat"]), (10, 4))
        rep = R.Report()
        rp = R.Replayer(self.eng, rep, verbose=False)
        rp.do_standard({"kind": "used_standard", "player": ME,
                        "project": "asteroid", "line": 1}, [], defaultdict(int))
        res = self.game()["me"]["resources"]
        self.assertEqual((res["mc"], res["heat"]), (0, 16))
        self.assertEqual(rep.topups, {})


if __name__ == "__main__":
    unittest.main()
