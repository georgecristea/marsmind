"""Fixes from the 4p WGT practice game (games/2026-09-01-game3, lost 70-69).

Four findings, each priced in that game:

1. Plan `events` call Engine methods by name, but the PLAYBOOK documents the
   `apply.py` CLI verbs. Three differ, and each one aborted a LIVE set_plan
   with an AttributeError mid-turn: `freecity`, `sell`, `action`. The engine
   now answers to the documented names.

2. The award lock verdict was INJECTED but never interrupted. In gen 8 it read
   "mine 7 vs Ben 6 reachable +3 = 9 - not lockable"; the award was funded
   anyway for 8 MC, the rival tied the metric twice and took 1st. Unfunded the
   award scores NOBODY and the game is 67-65 the other way - the whole
   1-point margin. Funding against a not-lockable verdict now needs an
   explicit `awardAck` (the exitAck precedent), which is logged and audited.
   A LOCKABLE verdict stays frictionless: that half of the same gate paid 5 VP
   in the same game.

3. `execute.py` could not transmit a World Government Terraforming choice at
   all: the skill mandates an events-less WGT step and the executor refused it
   ("no app-executable event"). All three WGT steps went out by hand. WGT is
   now the default for every game, so this was on the critical path.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tmlib import Store, Engine, EventError  # noqa: E402
from test_new_game import SETUP  # noqa: E402
import execute  # noqa: E402
import menu  # noqa: E402
import planlib  # noqa: E402
import sparring  # noqa: E402

THREATS = "test threats block"
EXIT = "test exit: tile VP; repeatable: greenery from plant production"


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root)
        self.store.init(SETUP)
        self.eng = Engine(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def log(self) -> str:
        return (self.root / "state" / "log.md").read_text()


# ── 1. the documented verb names reach the engine ────────────────────

class TestEngineAliasesMatchThePlaybook(Fixture):
    def test_freecity_is_the_documented_name(self):
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        self.assertTrue(hasattr(self.eng, "freecity"))
        self.eng.freecity("Zed")
        self.assertEqual(self.store.load_game()["me"]["tiles"]["cities"], 1)

    def test_sell_is_the_documented_name(self):
        self.eng.corp("Zed", "Thorgate", mc=48)
        self.eng.hand_add(["Trees"])
        before = self.store.load_game()["me"]["resources"]["mc"]
        self.eng.sell(["Trees"])
        game = self.store.load_game()
        self.assertEqual(game["me"]["resources"]["mc"], before + 1)
        self.assertNotIn("Trees", game["me"]["hand"])

    def test_action_is_the_documented_name(self):
        self.assertTrue(hasattr(self.eng, "action"))
        self.assertEqual(self.eng.action, self.eng.use_action)

    def test_a_plan_written_with_the_documented_names_simulates(self):
        self.eng.corp("Zed", "Tharsis Republic", mc=40)
        steps = [{"id": "1a", "summary": "free city", "volatility": "safe",
                  "cue": "a red city on 35",
                  "events": [{"method": "freecity", "args": ["Zed"]},
                             {"method": "place", "args": ["Zed", "city", "35"]}]},
                 {"id": "1b", "summary": "pass", "volatility": "safe",
                  "events": [], "passGate": True}]
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)
        self.assertEqual(planlib.load_plan(self.store)["steps"][0]["id"], "1a")


# ── 2. a not-lockable award funding must be acknowledged ─────────────

class AwardFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.eng.corp("Zed", "Thorgate", mc=48)

    def steps(self, ack=None, award="Banker"):
        step = {"id": "1a", "summary": f"FUND {award} (8 MC).",
                "volatility": "recheck",
                "events": [{"method": "award", "args": ["Zed", award]}]}
        if ack:
            step["awardAck"] = ack
        return [step, {"id": "1b", "summary": "pass", "volatility": "safe",
                       "events": [], "passGate": True}]

    def make_lockable(self):
        g = self.store.load_game()
        g["declaredFinalGeneration"] = g["generation"]
        g["me"]["production"]["mc"] = 4
        self.store.save_game(g)

    def verdict(self, award="Banker") -> dict:
        return menu.award_lock(self.store.load_game(), award,
                               self.store.load_setup())


class TestAwardAckGate(AwardFixture):
    def test_not_lockable_funding_is_refused_without_an_ack(self):
        self.assertFalse(self.verdict()["lockable"])
        with self.assertRaises(EventError) as cm:
            planlib.set_plan(self.store, self.steps(), threats=THREATS,
                             exit_=EXIT)
        msg = str(cm.exception)
        self.assertIn("1a", msg)
        self.assertIn("awardAck", msg)
        # the refusal must state WHY funding is asymmetric, not just refuse
        self.assertIn("nobody", msg.lower())

    def test_the_refusal_is_logged_as_a_gate(self):
        with self.assertRaises(EventError):
            planlib.set_plan(self.store, self.steps(), threats=THREATS,
                             exit_=EXIT)
        self.assertIn("GATE award-ack REFUSED", self.log())

    def test_an_ack_lets_it_through_and_is_logged(self):
        planlib.set_plan(self.store, self.steps(ack="last generation, the "
                                                "8 MC is cheaper than the 2 VP"),
                         threats=THREATS, exit_=EXIT)
        step = planlib.load_plan(self.store)["steps"][0]
        self.assertIn("not lockable", step["lockVerdict"])
        self.assertIn("award-ack OVERRIDE", self.log())

    def test_a_lockable_verdict_needs_no_ack(self):
        self.make_lockable()
        self.assertTrue(self.verdict()["lockable"])
        planlib.set_plan(self.store, self.steps(), threats=THREATS, exit_=EXIT)
        self.assertIn("LOCKABLE", planlib.load_plan(self.store)["steps"][0]
                      ["lockVerdict"])

    def test_an_opponent_funding_is_not_my_claim(self):
        steps = [{"id": "1a", "summary": "Ana funds Banker.",
                  "volatility": "recheck",
                  "events": [{"method": "award", "args": ["Ana", "Banker"]}]},
                 {"id": "1b", "summary": "pass", "volatility": "safe",
                  "events": [], "passGate": True}]
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)

    def test_patch_enforces_it_too(self):
        planlib.set_plan(self.store, [{"id": "1a", "summary": "pass",
                                       "volatility": "safe", "events": [],
                                       "passGate": True}],
                         threats=THREATS, exit_=EXIT)
        with self.assertRaises(EventError):
            planlib.patch(self.store, {"insert_after":
                                            {"1a": [self.steps()[0]]}})


# ── 3. the executor can transmit a WGT choice ────────────────────────

WGT_PROMPT = {
    "title": "Select action for World Government Terraforming",
    "type": "or",
    "options": [{"title": "Increase temperature", "type": "option"},
                {"title": "Increase oxygen", "type": "option"},
                {"title": "Add an ocean", "type": "space",
                 "spaces": ["43", "44", "45"]}],
}


class TestExecuteWgt(Fixture):
    def step(self, param, space=None):
        kw = {"space_id": space} if space else {}
        return {"id": "2c", "summary": f"WGT {param}", "volatility": "recheck",
                "events": [{"method": "wgt", "args": [param], "kwargs": kw}]}

    def test_a_wgt_step_produces_an_app_action(self):
        actions = execute.plan_actions(self.step("temperature"))
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["event"]["method"], "wgt")

    def test_temperature_selects_the_named_branch(self):
        action = execute.plan_actions(self.step("temperature"))[0]
        resp = execute.build_primary(action, WGT_PROMPT, self.eng,
                                     self.store.load_game())
        self.assertEqual(resp["index"], 0)
        self.assertEqual(resp["response"]["type"], "option")

    def test_oxygen_selects_the_named_branch(self):
        action = execute.plan_actions(self.step("oxygen"))[0]
        resp = execute.build_primary(action, WGT_PROMPT, self.eng,
                                     self.store.load_game())
        self.assertEqual(resp["index"], 1)

    def test_oceans_carries_the_hex_into_the_space_branch(self):
        action = execute.plan_actions(self.step("oceans", space="43"))[0]
        resp = execute.build_primary(action, WGT_PROMPT, self.eng,
                                     self.store.load_game())
        self.assertEqual(resp["index"], 2)
        self.assertEqual(resp["response"]["spaceId"], "43")

    def test_oceans_without_a_hex_asks_rather_than_guessing(self):
        action = execute.plan_actions(self.step("oceans"))[0]
        with self.assertRaises(execute.Ask):
            execute.build_primary(action, WGT_PROMPT, self.eng,
                                  self.store.load_game())

    def test_a_wgt_step_is_not_refused_as_tracker_only(self):
        # the exact refusal that sent all three of the game's WGT steps out
        # by hand: "the step has no app-executable event"
        self.assertTrue(execute.plan_actions(self.step("temperature")))


# ── 4. a generation roll is not an "uncovered follow-up" ─────────────

class FakeClient:
    """Serves a scripted sequence of app views to _answer_follow_ups."""
    def __init__(self, views):
        self.views = list(views)
        self.sent = []

    def player(self, pid):
        return self.views.pop(0) if self.views else {"waitingFor": None}

    def send(self, pid, response):
        self.sent.append(response)


RESEARCH_WF = {"title": "Select card(s) to buy", "type": "card",
               "cards": [{"name": "Worms"}, {"name": "Moss"},
                         {"name": "Grass"}, {"name": "Kelp Farming"}]}


class TestGenerationRollIsNotAFollowUp(Fixture):
    """The last action of a generation resolves, every seat passes, and the
    app's next prompt is the NEXT generation's research offer. The executor
    read that as an uncovered 'card' follow-up of the step just sent and
    ASKed — which stopped the scripted rehearsal (and therefore the LIVE
    GATE) on three consecutive deals. Research belongs to `execute.py pick`
    and its buy-0 gate, never to a step's follow-up chain."""

    def follow(self):
        return {"space": None, "spaceQueue": [], "or": None, "orExpect": None,
                "player": None, "card": None}

    def test_research_phase_ends_the_follow_up_chain_quietly(self):
        client = FakeClient([{"waitingFor": RESEARCH_WF,
                              "game": {"phase": "research", "generation": 2}}])
        data = execute._answer_follow_ups(client, "p1", self.follow(),
                                          out=lambda *a: None,
                                          step={"id": "1a"},
                                          store=self.store)
        self.assertEqual(data["game"]["phase"], "research")
        self.assertEqual(client.sent, [])      # nothing answered on its behalf

    def test_a_real_uncovered_card_prompt_still_asks(self):
        # same prompt shape, but the app is still in the action phase: this
        # is the Inventors' Guild case and must keep ASKing
        client = FakeClient([{"waitingFor": RESEARCH_WF,
                              "game": {"phase": "action", "generation": 2}}])
        with self.assertRaises(execute.Ask):
            execute._answer_follow_ups(client, "p1", self.follow(),
                                       out=lambda *a: None,
                                       step={"id": "1a"}, store=self.store)
