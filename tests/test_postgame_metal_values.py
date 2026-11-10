"""Metal-value modifiers (D1) — from the blind 2p game.

tmlib prices metal with module constants (steel 2, titanium 3) and has no
hook for a tableau card that changes them. With Advanced Alloys in play
("each steel/titanium you have is worth 1 M€ extra") the harness built
payments at the wrong rate and the app accepted the overpayment: Ore
Processor cost 7 MC where 4 was due. The dangerous part is that
`verify: engine == app` still printed OK, BECAUSE BOTH SIDES USED THE SAME
WRONG NUMBER — reconciliation cannot catch an error it shares.

Two changes, neither of which alters behaviour when nothing supplies the
values:

1. split_payment honours per-player metal values off the pool
   (`steelValue` / `titaniumValue`), defaulting to the constants. The app
   publishes exactly these fields per player, so the eventual full fix is
   data-driven rather than card-specific (AGENTS.md forbids card branches).
2. adopt_app WARNS when the app's published metal values disagree with the
   engine's, so the leak is visible at the table instead of silent.
"""
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import execute
import tmlib
from tmlib import split_payment


def _game(steel=3, titanium=0, mc=20, extra=None):
    me = {"name": "Maxwell", "corporation": "Mining Guild",
          "resources": {"mc": mc, "steel": steel, "titanium": titanium,
                        "plants": 0, "energy": 0, "heat": 0},
          "production": {"mc": 0, "steel": 0, "titanium": 0, "plants": 0,
                         "energy": 0, "heat": 0}}
    me.update(extra or {})
    return {"me": me, "opponents": {}}


class TestPoolMetalValues(unittest.TestCase):

    def test_default_rates_are_unchanged(self):
        """No pool override: exactly today's arithmetic."""
        pay = split_payment(_game(), "Maxwell", 13, steel=3,
                            tags=["building"])
        self.assertEqual(pay["mc"], 13 - 3 * tmlib.STEEL_VALUE)   # 7

    def test_advanced_alloys_rate_from_the_pool(self):
        """The in-game case: Ore Processor, 13 MC, 3 steel worth 3 each."""
        g = _game(extra={"steelValue": 3})
        pay = split_payment(g, "Maxwell", 13, steel=3, tags=["building"])
        self.assertEqual(pay["mc"], 4, "13 - 3x3 = 4 MC, not 7")

    def test_titanium_rate_from_the_pool(self):
        g = _game(steel=0, titanium=4, extra={"titaniumValue": 4})
        pay = split_payment(g, "Maxwell", 21, titanium=4, tags=["space"])
        self.assertEqual(pay["mc"], 21 - 16)

    def test_auto_picked_metal_uses_the_pool_rate(self):
        """When the caller does not pin the ore, the picker must use it too."""
        g = _game(steel=5, mc=0, extra={"steelValue": 3})
        pay = split_payment(g, "Maxwell", 12, tags=["building"])
        self.assertEqual(pay["steel"], 4)          # 4x3 = 12, not 6x2
        self.assertEqual(pay["mc"], 0)


class TestAdoptWarnsOnMetalValueDrift(unittest.TestCase):

    class _Store:
        def __init__(self): self.g = _game()
        def load_game(self): return self.g

    def _adopt_warning(self, view):
        out = []
        execute.warn_metal_values(view, out.append)
        return " ".join(out)

    def test_warns_when_the_app_prices_metal_higher(self):
        view = {"thisPlayer": {"name": "Maxwell", "steelValue": 3,
                               "titaniumValue": 4}}
        msg = self._adopt_warning(view)
        self.assertIn("steel", msg.lower())
        self.assertIn("3", msg)
        self.assertTrue(msg.strip(), "the drift must be reported, not silent")

    def test_silent_when_the_app_agrees(self):
        view = {"thisPlayer": {"name": "Maxwell", "steelValue": 2,
                               "titaniumValue": 3}}
        self.assertEqual(self._adopt_warning(view).strip(), "")

    def test_silent_when_the_app_does_not_publish_them(self):
        self.assertEqual(self._adopt_warning({"thisPlayer": {}}).strip(), "")


if __name__ == "__main__":
    unittest.main()
