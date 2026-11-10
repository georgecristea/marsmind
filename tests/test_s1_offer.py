"""S1 (speed plan) — the listener's GO line carries the card offer.

`GO — Select card(s) to buy` alone cost the advisor a whole extra model
round-trip (curl + a cards/db.json lookup) to see the four cards. When
the prompt is a card offer (`waitingFor.type == "card"` with a `cards`
list, or the `initialCards` shape) the listener prints one line per
offered card from the view it already holds: name, play cost (the app's
calculatedCost when present), tags, requirement, one-line effect text.
Output only — a non-card GO prints exactly what it printed before.
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import listen                                   # noqa: E402
from test_listen import FakeApp, ListenBase, _setup   # noqa: E402
from tmlib import Engine, Store                 # noqa: E402

BUY = {"type": "card", "title": "Select card(s) to buy",
       "cards": [{"name": "Comet", "calculatedCost": 18},
                 {"name": "Sponsors"}, {"name": "Nuclear Power"},
                 {"name": "Ants"}],
       "min": 0, "max": 4}
INITIAL = {"type": "initialCards", "title": " ", "options": [
    {"type": "card", "title": "Select corporation",
     "cards": [{"name": "Helion"}, {"name": "Teractor"}], "min": 1, "max": 1},
    {"type": "card", "title": "Select initial cards to buy",
     "cards": [{"name": "Comet"}, {"name": "Sponsors"}], "min": 0, "max": 10}]}
ACTION = {"type": "or", "title": "Take your first action",
          "options": [{"title": "Pass for this generation", "type": "option"}]}


class PromptApp(FakeApp):
    """FakeApp whose GO prompt is a full waitingFor dict."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.prompt: dict | None = None

    def view(self) -> dict:
        v = super().view()
        if self.prompt is not None:
            v["waitingFor"] = self.prompt
        return v


class OfferBase(ListenBase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = Store(root, state_dir=root / "state")
        setup = _setup()
        self.app = PromptApp(setup, self.store)
        setup["appUrl"] = self.app.url
        self.store.init(setup)
        self.eng = Engine(self.store)
        self.revealed = 0

    def go(self, prompt: dict) -> str:
        self.app.prompt = prompt
        self.app.waiting = listen._title(prompt) or "prompt"
        code, out = self.main("once")
        self.assertIn(code, (20, 30))
        return out

    @staticmethod
    def card_lines(out: str) -> list[str]:
        go = next(i for i, l in enumerate(out.splitlines()) if l.startswith("GO — "))
        return out.splitlines()[go + 1:]


class TestCardOffer(OfferBase):
    def test_a_buy_prompt_lists_every_card_with_cost_tags_requirement_effect(self):
        out = self.go(BUY)
        self.assertIn("GO — Select card(s) to buy", out)
        lines = self.card_lines(out)
        self.assertEqual(len(lines), 4, out)
        by_name = {l.split("—")[0].strip(" •·"): l for l in lines}
        self.assertEqual(list(by_name), ["Comet", "Sponsors", "Nuclear Power", "Ants"])
        comet = by_name["Comet"]
        self.assertIn("18 MC", comet)                    # the app's calculatedCost
        self.assertIn("21", comet)                       # the printed cost, still visible
        self.assertIn("space, event", comet)
        self.assertIn("Raise temperature 1 step and place an ocean tile.", comet)
        ants = by_name["Ants"]
        self.assertIn("9 MC", ants)
        self.assertIn("microbe", ants)
        self.assertIn("min 4% O2", ants)                 # the requirement
        sponsors = by_name["Sponsors"]
        self.assertIn("6 MC", sponsors)
        self.assertIn("earth", sponsors)
        self.assertNotIn("requires", sponsors)           # none: nothing printed
        self.assertIn("Increase your M€ production 2 steps.", sponsors)

    def test_the_initial_cards_prompt_lists_corporations_and_cards(self):
        out = self.go(INITIAL)
        lines = self.card_lines(out)
        names = [l.split("—")[0].strip(" •·") for l in lines if "—" in l]
        for n in ("Helion", "Teractor", "Comet", "Sponsors"):
            self.assertIn(n, names, out)
        helion = next(l for l in lines if l.lstrip(" •·").startswith("Helion"))
        self.assertIn("42 MC", helion)
        self.assertIn("You may use heat as M€.", helion)
        # both option titles are visible so the operator knows the two groups
        self.assertIn("Select corporation", out)
        self.assertIn("Select initial cards to buy", out)

    def test_an_unknown_card_still_prints_its_name(self):
        out = self.go(dict(BUY, cards=[{"name": "Not A Card:XX", "calculatedCost": 5},
                                       {"name": "Sponsors"}]))
        lines = self.card_lines(out)
        self.assertEqual(len(lines), 2, out)
        self.assertIn("Not A Card:XX", lines[0])
        self.assertIn("5 MC", lines[0])

    def test_a_non_card_go_prints_exactly_the_title_line(self):
        out = self.go(ACTION)
        self.assertEqual(out.splitlines()[-1], "GO — Take your first action")
        self.assertEqual(self.card_lines(out), [])
        self.assertEqual(sum(1 for l in out.splitlines() if l.startswith("GO — ")), 1)

    def test_a_bare_title_prompt_is_unchanged(self):
        self.app.waiting = "Select card(s) to buy"       # no type, no cards (old fakes)
        code, out = self.main("once")
        self.assertIn(code, (20, 30))
        self.assertEqual(out.splitlines()[-1], "GO — Select card(s) to buy")

    def test_wait_prints_the_offer_too(self):
        self.app.prompt = BUY
        self.app.waiting = BUY["title"]
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code, title = listen.wait(self.listener(), sleep=lambda s: None)
        self.assertEqual(code, 20)
        self.assertEqual(title, "Select card(s) to buy")
        self.assertEqual(len(self.card_lines(buf.getvalue())), 4)


class TestOfferLines(unittest.TestCase):
    """The pure renderer, no app."""

    def test_card_offer(self):
        lines = listen.offer_lines(BUY)
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].lstrip(" •·").startswith("Comet"))

    def test_not_an_offer(self):
        self.assertEqual(listen.offer_lines(ACTION), [])
        self.assertEqual(listen.offer_lines({"title": "x"}), [])
        self.assertEqual(listen.offer_lines(None), [])
        self.assertEqual(listen.offer_lines({"type": "card", "title": "t"}), [])

    def test_calculated_cost_wins_over_the_printed_cost(self):
        [line] = listen.offer_lines({"type": "card", "title": "t",
                                     "cards": [{"name": "Comet", "calculatedCost": 18}]})
        self.assertIn("18 MC", line)
        self.assertIn("printed 21", line)
        [line] = listen.offer_lines({"type": "card", "title": "t",
                                     "cards": [{"name": "Comet"}]})
        self.assertIn("21 MC", line)
        self.assertNotIn("printed", line)


if __name__ == "__main__":
    unittest.main()
