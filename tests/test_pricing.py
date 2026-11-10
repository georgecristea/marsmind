"""ONE price model. The menu quotes exactly what `play` / `standard`
charge, because both read the same public pricing API on the engine
(Engine.price / Engine.standard_price, pure over the game dict). Formerly
menu.py carried its own discount table (5 sources) while the
engine's DISCOUNTS knew 10 plus the Indentured Workers next-card discount —
the menu could quote one price and the event charge another."""
import copy, re, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cards as cardlib
import menu
import tmlib
from tmlib import Engine, Store
from test_new_game import SETUP

CORPS = ["Teractor", "ThorGate", "CrediCor", None]
TABLEAU = [None, "Earth Catapult", "Research Outpost", "Space Station",
           "Earth Office"]
PAID = re.compile(r"paid (\d+) MC")
PRICE_KEYS = {"base", "discount", "notes", "price", "rebate", "rebateNotes",
              "next_card"}


def _playable(db):
    return [c for c in db["cards"] if c["type"] != "corporation"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.init(SETUP)
        self.eng = Engine(self.store)
        self.db = cardlib.load_db()

    def tearDown(self):
        self.tmp.cleanup()

    def game(self):
        return self.store.load_game()

    def state(self, hand, corp=None, tableau=None, mc=500):
        """Rich position: every production at 10 (no floor refusals),
        opponents likewise (decrease-any cards find a victim), no ores so
        the whole price is paid in MC."""
        g = self.game()
        me = g["me"]
        me["hand"] = list(hand)
        me["corporation"] = corp
        me["playedCards"] = ([{"name": tableau, "gen": 1}] if tableau else [])
        me.pop("nextCardDiscount", None)
        me["resources"] = {r: 0 for r in tmlib.RESOURCES}
        me["resources"]["mc"] = mc
        me["production"] = {r: 10 for r in tmlib.RESOURCES}
        for o in g["opponents"].values():
            o["production"] = {r: 10 for r in tmlib.RESOURCES}
        self.store.save_game(g)
        return g


class TestPriceApi(Base):
    def test_price_shape_and_purity(self):
        g = self.state(["Comet"], corp="CrediCor", tableau="Space Station")
        before = copy.deepcopy(g)
        q = Engine.price(g, "Zed", cardlib.find("Comet", self.db))
        self.assertEqual(set(q), PRICE_KEYS)
        self.assertEqual(q["base"], 21)
        self.assertEqual(q["discount"], 2)
        self.assertEqual(q["notes"], ["Space Station −2"])
        self.assertEqual(q["price"], 19)
        self.assertEqual(q["rebate"], 4)          # CrediCor keys on BASE ≥ 20
        self.assertFalse(q["next_card"])
        self.assertEqual(g, before)               # pure: no mutation
        # also reachable on an instance
        self.assertEqual(self.eng.price(g, "Zed", cardlib.find("Comet", self.db)), q)

    def test_price_never_below_zero(self):
        g = self.state(["Business Network"], corp="Teractor", tableau="Earth Office")
        q = Engine.price(g, "Zed", cardlib.find("Business Network", self.db))
        self.assertEqual(q["base"], 4)
        self.assertEqual(q["discount"], 6)
        self.assertEqual(q["price"], 0)

    def test_standard_price_shape(self):
        g = self.state([], corp="ThorGate")
        before = copy.deepcopy(g)
        q = Engine.standard_price(g, "Zed", "power_plant")
        self.assertEqual(set(q), PRICE_KEYS)
        self.assertEqual(q, {"base": 11, "discount": 3, "notes": ["ThorGate −3"],
                             "price": 8, "rebate": 0, "rebateNotes": [],
                             "next_card": False})
        self.assertEqual(g, before)
        g = self.state([], corp="CrediCor")
        q = Engine.standard_price(g, "Zed", "greenery")
        self.assertEqual((q["price"], q["rebate"]), (23, 4))
        q = Engine.standard_price(g, "Zed", "asteroid")
        self.assertEqual((q["price"], q["rebate"]), (14, 0))

    def test_unknown_player_refused(self):
        g = self.state(["Comet"])
        with self.assertRaises(tmlib.EventError):
            Engine.price(g, "Nobody", cardlib.find("Comet", self.db))


class TestMenuQuotesWhatPlayCharges(Base):
    """For every card × corp × tableau discount: the menu's quoted cost ==
    Engine.price == the 'paid N MC' line of the play trace, and the balance
    moves by price − rebate."""

    def test_every_card_every_corp_every_tableau(self):
        cards = _playable(self.db)
        listed_total = 0
        for corp in CORPS:
            for tab in TABLEAU:
                g = self.state([c["name"] for c in cards], corp=corp, tableau=tab)
                quoted = {i["name"]: i["cost"]
                          for i in menu.available_actions(g, SETUP, db=self.db)
                          if i["kind"] == "card"}
                listed_total += len(quoted)
                for card in cards:
                    ctx = f"{card['name']} / corp={corp} / tableau={tab}"
                    g = self.state([card["name"]], corp=corp, tableau=tab)
                    q = Engine.price(g, "Zed", card)
                    if card["name"] in quoted:
                        self.assertEqual(quoted[card["name"]], q["price"], ctx)
                    choice = 0 if (card.get("behavior") or {}).get("or") else None
                    msg = self.eng.play("Zed", card["name"],
                                        ignore_requirements="pricing test",
                                        choice=choice, no_effects=True)
                    paid = int(PAID.search(msg).group(1))
                    self.assertEqual(paid, q["price"], f"{ctx}: {msg}")
                    self.assertEqual(self.game()["me"]["resources"]["mc"],
                                     500 - q["price"] + q["rebate"], ctx)
        # the menu half is not vacuous: most cards are listed in this position
        self.assertGreater(listed_total, len(CORPS) * len(TABLEAU) * len(cards) // 2)

    def test_engine_only_sources_reach_the_menu(self):
        # Earth Office / Shuttles / Anti-Gravity were in the engine's table
        # but not in the menu's own — the exact bug class.
        for tab, card, expect in (("Earth Office", "Business Network", 1),
                                  ("Shuttles", "Comet", 19),
                                  ("Anti-Gravity Technology", "Comet", 19)):
            g = self.state([card], tableau=tab)
            item = next(i for i in menu.available_actions(g, SETUP, db=self.db)
                        if i["kind"] == "card" and i["name"] == card)
            self.assertEqual(item["cost"], expect, tab)
            self.assertIn(tab, item["detail"])

    def test_credicor_rebate_shown_on_card_items(self):
        g = self.state(["Comet"], corp="CrediCor")
        item = next(i for i in menu.available_actions(g, SETUP, db=self.db)
                    if i["kind"] == "card" and i["name"] == "Comet")
        self.assertIn("CrediCor +4", item["detail"])

    def test_standard_projects_quote_engine_price(self):
        for corp in CORPS:
            g = self.state([], corp=corp)
            items = {i["name"]: i for i in menu.available_actions(g, SETUP, db=self.db)
                     if i["kind"] == "standard"}
            for proj in tmlib.STANDARD_PROJECTS:
                if proj == "sell_patents":
                    continue
                q = Engine.standard_price(g, "Zed", proj)
                self.assertEqual(items[proj]["cost"], q["price"], (corp, proj))
                msg = self.eng.standard("Zed", proj)
                m = re.search(r"−(\d+) MC", msg)
                self.assertEqual(int(m.group(1)), q["price"], (corp, proj, msg))
                if q["rebate"]:
                    self.assertIn("CrediCor +4", items[proj]["detail"])
                    self.assertIn("+4 MC rebate", msg)
                self.state([], corp=corp)


class TestIndenturedWorkers(Base):
    def test_next_card_discount_quoted_then_consumed_once(self):
        self.state(["Indentured Workers", "Comet", "Big Asteroid"])
        self.eng.play("Zed", "Indentured Workers")
        g = self.game()
        q = Engine.price(g, "Zed", cardlib.find("Comet", self.db))
        self.assertTrue(q["next_card"])
        self.assertEqual((q["discount"], q["price"]), (8, 13))
        self.assertIn("Indentured Workers −8", q["notes"])
        quoted = {i["name"]: i["cost"]
                  for i in menu.available_actions(g, SETUP, db=self.db)
                  if i["kind"] == "card"}
        self.assertEqual(quoted["Comet"], 13)
        self.assertEqual(quoted["Big Asteroid"], 27 - 8)
        msg = self.eng.play("Zed", "Comet", no_effects=True)
        self.assertEqual(int(PAID.search(msg).group(1)), 13)
        g = self.game()
        q = Engine.price(g, "Zed", cardlib.find("Big Asteroid", self.db))
        self.assertFalse(q["next_card"])
        self.assertEqual((q["discount"], q["price"]), (0, 27))
        quoted = {i["name"]: i["cost"]
                  for i in menu.available_actions(g, SETUP, db=self.db)
                  if i["kind"] == "card"}
        self.assertEqual(quoted["Big Asteroid"], 27)
        msg = self.eng.play("Zed", "Big Asteroid", no_effects=True)
        self.assertEqual(int(PAID.search(msg).group(1)), 27)

    def test_next_card_discount_expires_with_the_generation(self):
        self.state(["Indentured Workers", "Comet"])
        self.eng.play("Zed", "Indentured Workers")
        self.eng.produce()
        g = self.game()
        q = Engine.price(g, "Zed", cardlib.find("Comet", self.db))
        self.assertFalse(q["next_card"])
        self.assertEqual(q["price"], 21)


class TestMenuHasNoPrivatePriceModel(unittest.TestCase):
    def test_menu_discount_table_deleted(self):
        self.assertFalse(hasattr(menu, "card_discount"))

    def test_menu_uses_engine_pool_helpers(self):
        self.assertIs(menu._zeros, tmlib._zeros)
        self.assertIs(menu.all_pools, tmlib.all_pools)
        self.assertIs(menu.player_pool, tmlib.player_pool)
        self.assertFalse(hasattr(menu, "_all_pools"))
        self.assertFalse(hasattr(menu, "_pool"))


if __name__ == "__main__":
    unittest.main()
