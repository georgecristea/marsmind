"""P4: scripts/execute.py — the one-call executor. A plan step becomes app
inputs (built with the sparring helpers), each send is followed by a
re-fetch, follow-ups the step covers are answered, the result is verified
against a sandbox simulation of the step, and only then is the step
marked done. Anything the prompt tree does not match → exit 40 with the
tree and NOTHING sent; engine/app disagreement → exit 41, plan untouched.

The fake app below is a scripted in-process http.server (same pattern as
test_appapi.CannedServer) whose GET /api/player view advances one state
per POST /player/input — so the sequence of prompts the executor sees is
exactly the scripted one, no matter how often it re-fetches."""
import copy
import http.server
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from tmlib import Engine, EventError, Store, grid_to_space
from test_new_game import SETUP
import execute
import judgment
import planlib
import sparring

THREATS = "test threats block"
EXIT = "test exit: card VP; repeatable: greenery from plant production"
PID = "p-zed"


# ── scripted app ─────────────────────────────────────────────

class ScriptedApp:
    """GET /api/player → states[i]; POST /player/input records the body
    and advances i (the last state repeats). `reject` = answer every POST
    with HTTP 400 and do not advance (what the real app does on a wrong
    shape)."""

    def __init__(self, states: list[dict], reject: bool = False):
        self.states = list(states)
        self.i = 0
        self.posts: list[dict] = []
        self.reject = reject
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, status, body):
                raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path.startswith("/api/player"):
                    self._reply(200, outer.states[min(outer.i, len(outer.states) - 1)])
                else:
                    self._reply(404, b"no route")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if outer.reject:
                    self._reply(400, b'{"message":"Not a valid response"}')
                    return
                outer.posts.append(body)
                outer.i = min(outer.i + 1, len(outer.states) - 1)
                self._reply(200, {})

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ── prompt shapes (from common/models/PlayerInputModel.ts + Player.getActions) ──

def root_menu(cards=("Sponsors", "Power Plant"), calculated=None,
              milestones=("Terraformer", "Builder"), awards=("Banker", "Scientist"),
              heat=True, plants=False, actions=("Water Import From Europa",),
              sp_disabled=()):
    """The action-phase `or` root: the same options the live app builds,
    in the app's order (claim, convert plants, convert heat, action cards,
    play project card, fund award, standard projects, pass)."""
    calculated = calculated or {}
    opts = []
    if milestones:
        opts.append({"title": "Claim a milestone", "type": "or",
                     "options": [{"title": m, "type": "option"} for m in milestones]})
    if plants:
        opts.append({"title": {"message": "Convert ${0} plants into greenery",
                               "data": [{"type": 1, "value": "8"}]},
                     "type": "space", "spaces": ["17", "18"]})
    if heat:
        opts.append({"title": "Convert 8 heat into temperature", "type": "option"})
    if actions:
        opts.append({"title": "Perform an action from a played card", "type": "card",
                     "cards": [{"name": a} for a in actions], "min": 1, "max": 1})
    if cards:
        opts.append({"title": "Play project card", "type": "projectCard",
                     "cards": [{"name": c, "calculatedCost": calculated.get(c)}
                               for c in cards],
                     "paymentOptions": {"heat": False}})
    if awards:
        opts.append({"title": {"message": "Fund an award (${0} M€)",
                               "data": [{"type": 1, "value": "8"}]},
                     "type": "or",
                     "options": [{"title": a, "type": "option"} for a in awards]})
    opts.append({"title": "Standard projects", "type": "projectCard", "cards": [
        {"name": "Power Plant:SP", "calculatedCost": 11},
        {"name": "Asteroid:SP", "calculatedCost": 14},
        {"name": "Aquifer", "calculatedCost": 18,
         "isDisabled": "Aquifer" in sp_disabled},
        {"name": "Greenery", "calculatedCost": 23},
        {"name": "City", "calculatedCost": 25, "isDisabled": "City" in sp_disabled}]})
    opts.append({"title": "Pass for this generation", "type": "option"})
    return {"type": "or", "title": "Take your first action", "options": opts}


SPACE_PROMPT = {"type": "space", "title": "Select space for city tile",
                "spaces": ["15", "16", "17", "18"]}
BUY_PROMPT = {"type": "card", "title": "Select cards to buy",
              "cards": [{"name": "Comet"}, {"name": "Sponsors"},
                        {"name": "Power Plant"}, {"name": "Nuclear Power"}],
              "min": 0, "max": 4}
INITIAL_PROMPT = {"type": "initialCards", "title": " ", "options": [
    {"type": "card", "title": "Select corporation",
     "cards": [{"name": "Helion"}, {"name": "Teractor"}], "min": 1, "max": 1},
    {"type": "card", "title": "Select initial cards to buy",
     "cards": [{"name": "Comet"}, {"name": "Sponsors"}], "min": 0, "max": 10}]}


def view_from_game(game: dict, wf, tableau=("Beginner Corporation",)) -> dict:
    """The /api/player payload the app would serve for the tracker's `me`
    (field names from common/models/PlayerModel.ts, the ones verify.py
    reads)."""
    me = game["me"]
    r, p = me["resources"], me["production"]
    tp = {"name": me["name"], "color": "red",
          "megacredits": r["mc"], "steel": r["steel"], "titanium": r["titanium"],
          "plants": r["plants"], "energy": r["energy"], "heat": r["heat"],
          "terraformRating": me["tr"],
          "megacreditProduction": p["mc"], "steelProduction": p["steel"],
          "titaniumProduction": p["titanium"], "plantProduction": p["plants"],
          "energyProduction": p["energy"], "heatProduction": p["heat"],
          "cardsInHandNbr": len(me["hand"]),
          "cardsInHand": [{"name": c} for c in me["hand"]],
          "tableau": [{"name": t} for t in tableau]}
    g = game["globals"]
    return {"thisPlayer": tp,
            "game": {"generation": game["generation"], "phase": "action",
                     "temperature": g["temperature"], "oxygenLevel": g["oxygen"],
                     "oceans": g["oceans"],
                     "milestones": [{"name": m, "playerName": who}
                                    for m, who in game["milestonesClaimed"].items()],
                     "awards": [{"name": a, "playerName": who}
                                for a, who in game.get("awardsFunded", {}).items()]},
            "players": [{"name": n, "color": c, "tableau": [{"name": "Corp"}]}
                        for n, c in (("Zed", "red"), ("Anna", "green"),
                                     ("Felix", "blue"))],
            "waitingFor": wf}


def after(store: Store, events: list[dict]) -> dict:
    """The game dict after `events` run in a sandbox copy of the store —
    i.e. what the app SHOULD show once the step landed."""
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "state"
        shutil.copytree(store.state_dir, sandbox)
        eng = Engine(Store(tmp, state_dir=sandbox))
        for ev in events:
            getattr(eng, ev["method"])(*ev.get("args", []), **ev.get("kwargs", {}))
        return eng.store.load_game()


# ── base fixture ─────────────────────────────────────────────

class ExecuteCase(unittest.TestCase):
    STEPS: list[dict] = []
    mode = "app-practice"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.app = None
        setup = copy.deepcopy(SETUP)
        setup["gameMode"] = self.mode
        setup["players"][0]["playerId"] = PID
        setup["appUrl"] = "http://127.0.0.1:1"          # replaced by start_app
        self.store.init(setup)
        eng = Engine(self.store)
        eng.res("Zed", "mc", +30)
        eng.res("Zed", "steel", +2)
        eng.res("Zed", "heat", +8)
        eng.hand_add(["Sponsors", "Power Plant"])
        eng.tr("Zed", +15)                       # TR 35: Terraformer claimable

    def tearDown(self):
        if self.app:
            self.app.close()
        self.tmp.cleanup()

    def set_plan(self, steps):
        planlib.set_plan(self.store, steps, threats=THREATS, exit_=EXIT)

    def start_app(self, states, reject=False):
        self.app = ScriptedApp(states, reject=reject)
        setup = self.store.load_setup()
        setup["appUrl"] = self.app.url
        Store._write_json(self.store.setup_path, setup)
        return self.app

    def run_cli(self, *argv) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = execute.main(list(argv), store=self.store)
        return rc, out.getvalue() + err.getvalue()

    def game(self):
        return self.store.load_game()

    def plan_step(self, label):
        return next(s for s in planlib.load_plan(self.store)["steps"]
                    if s["id"] == label)


PLAY_SPONSORS = {"id": "1a", "summary": "Play Sponsors", "volatility": "safe",
                 "events": [{"method": "play", "args": ["Zed", "Sponsors"],
                             "kwargs": {"cost": 6}}]}
PLAY_PP_STEEL = {"id": "1b", "summary": "Play Power Plant with 2 steel",
                 "volatility": "safe",
                 "events": [{"method": "play", "args": ["Zed", "Power Plant"],
                             "kwargs": {"cost": 4, "steel": 2}}]}
SP_ASTEROID = {"id": "2a", "summary": "SP asteroid", "volatility": "safe",
               "events": [{"method": "standard", "args": ["Zed", "asteroid"]}]}
CLAIM_TERRAFORMER = {"id": "2b", "summary": "Claim Terraformer", "volatility": "recheck",
               "events": [{"method": "milestone", "args": ["Zed", "Terraformer"]}]}
CONVERT_HEAT = {"id": "3a", "summary": "Convert 8 heat", "volatility": "safe",
                "events": [{"method": "convert", "args": ["Zed", "heat"]}]}
SP_CITY_C4 = {"id": "3b", "summary": "SP city on C4", "volatility": "recheck",
              "cue": "red city on C4",
              "events": [{"method": "standard", "args": ["Zed", "city"]},
                         {"method": "place", "args": ["Zed", "city", "C4"]}]}
PASS = {"id": "4a", "summary": "Pass", "volatility": "safe", "passGate": True,
        "events": []}
FREECITY_C4 = {"id": "1a", "summary": "Tharsis first action: city on C4",
               "volatility": "recheck", "cue": "red city on C4",
               "events": [{"method": "free_action_city", "args": ["Zed"]},
                          {"method": "place", "args": ["Zed", "city", "C4"]}]}
# generation 1 for a corporation with a mandatory first action: the app
# offers ONLY "Take first action of <corp> corporation" and the pass
FIRST_ACTION_MENU = {"type": "or", "title": "Select one option", "options": [
    {"title": "Take first action of Tharsis Republic corporation", "type": "option"},
    {"title": "Pass for this generation", "type": "option"}]}


# ── play ─────────────────────────────────────────────────────

class TestPlayStep(ExecuteCase):
    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PLAY_PP_STEEL, PASS])

    def test_play_sends_project_card_with_mc_payment_and_marks_done(self):
        before = view_from_game(self.game(), root_menu(calculated={"Sponsors": 6}))
        landed = view_from_game(after(self.store, PLAY_SPONSORS["events"]),
                                root_menu(cards=("Power Plant",)))
        app = self.start_app([before, landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        sent = app.posts[0]
        idx = sparring.find_option(before["waitingFor"], "play project card")
        self.assertEqual(sent, sparring.or_choice(
            idx, sparring.project_card("Sponsors", mc=6)))
        self.assertTrue(self.plan_step("1a")["done"])
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 24)      # events applied
        self.assertEqual(g["me"]["production"]["mc"], 2)
        self.assertNotIn("Sponsors", g["me"]["hand"])
        # app mode: the app is the rules engine, so the step is app-ADOPTED
        self.assertIn("app-adopted", (Path(self.tmp.name) / "state" / "log.md").read_text())

    def test_play_with_steel_split_pays_steel_and_the_mc_remainder(self):
        before = view_from_game(self.game(), root_menu(calculated={"Power Plant": 4}))
        landed = view_from_game(after(self.store, PLAY_PP_STEEL["events"]),
                                root_menu(cards=("Sponsors",)))
        app = self.start_app([before, landed])
        rc, out = self.run_cli("step", "1b")
        self.assertEqual(rc, 0, out)
        pay = app.posts[0]["response"]["payment"]
        self.assertEqual((pay["steel"], pay["megacredits"], pay["titanium"]),
                         (2, 0, 0))
        self.assertEqual(self.game()["me"]["resources"]["steel"], 0)

    def test_app_calculated_cost_disagreeing_with_engine_price_asks(self):
        """The app prices Sponsors at 3 (a discount the engine does not
        model) — sending 6 would overpay / 400. Ask, send nothing."""
        before = view_from_game(self.game(), root_menu(calculated={"Sponsors": 3}))
        app = self.start_app([before])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])
        self.assertIn("ASK", out)
        self.assertFalse(self.plan_step("1a")["done"])

    def test_card_not_offered_by_the_app_asks(self):
        before = view_from_game(self.game(), root_menu(cards=("Power Plant",)))
        app = self.start_app([before])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])
        self.assertIn("Sponsors", out)


# ── corp first action (generation 1) ─────────────────────────

class TestFirstActionStep(ExecuteCase):
    """A `freecity` step (Tharsis Republic's free city) answers the gen-1
    first-action prompt and its space follow-up; a pass step is legal on
    the same prompt."""

    def setUp(self):
        super().setUp()
        self.set_plan([FREECITY_C4, PASS])

    def test_freecity_takes_the_first_action_and_places(self):
        before = view_from_game(self.game(), FIRST_ACTION_MENU)
        asking = view_from_game(self.game(), SPACE_PROMPT)
        landed = view_from_game(after(self.store, FREECITY_C4["events"]), root_menu())
        app = self.start_app([before, asking, landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[0], sparring.choose(FIRST_ACTION_MENU,
                                                       "take first action"))
        self.assertEqual(app.posts[1], sparring.space(grid_to_space("C4")))
        self.assertTrue(self.plan_step("1a")["done"])
        self.assertIn("17", self.game()["board"])
        self.assertEqual(self.game()["me"]["tiles"]["cities"], 1)

    def test_pass_on_the_first_action_prompt(self):
        before = view_from_game(self.game(), FIRST_ACTION_MENU)
        app = self.start_app([before, view_from_game(self.game(), None)])
        rc, out = self.run_cli("step", "4a", "--force", "gate covered by TestPassGateRefusesBeforeSending")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.choose(FIRST_ACTION_MENU,
                                                     "pass for this generation")])

    def test_freecity_without_the_prompt_asks(self):
        before = view_from_game(self.game(), root_menu())
        app = self.start_app([before])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])
        self.assertIn("first action", out.lower())


# ── standard project / claim / convert / place ───────────────

class TestOtherSteps(ExecuteCase):
    def setUp(self):
        super().setUp()
        Engine(self.store).res("Zed", "mc", +40)     # 70: the whole plan is affordable
        self.set_plan([SP_ASTEROID, CLAIM_TERRAFORMER, CONVERT_HEAT, SP_CITY_C4, PASS])

    def test_standard_project_sends_the_sp_card_with_its_price(self):
        before = view_from_game(self.game(), root_menu())
        landed = view_from_game(after(self.store, SP_ASTEROID["events"]), root_menu())
        app = self.start_app([before, landed])
        rc, out = self.run_cli("step", "2a")
        self.assertEqual(rc, 0, out)
        idx = sparring.find_option(before["waitingFor"], "standard projects")
        self.assertEqual(app.posts, [sparring.or_choice(
            idx, sparring.project_card("Asteroid:SP", mc=14))])
        g = self.game()
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["me"]["tr"], 36)                # 35 + 1
        self.assertTrue(self.plan_step("2a")["done"])

    def test_claim_sends_nested_or_and_cue_gate_is_the_app_state(self):
        before = view_from_game(self.game(), root_menu())
        landed = view_from_game(after(self.store, CLAIM_TERRAFORMER["events"]),
                                root_menu(milestones=()))
        app = self.start_app([before, landed])
        rc, out = self.run_cli("step", "2b")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.claim_milestone(before["waitingFor"], "Terraformer")])
        self.assertTrue(self.plan_step("2b")["done"])       # no --confirm needed
        self.assertEqual(self.game()["milestonesClaimed"], {"Terraformer": "Zed"})

    def test_claim_not_offered_asks(self):
        before = view_from_game(self.game(), root_menu(milestones=("Builder",)))
        app = self.start_app([before])
        rc, out = self.run_cli("step", "2b")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])

    def test_convert_heat_chooses_the_convert_option(self):
        before = view_from_game(self.game(), root_menu())
        landed = view_from_game(after(self.store, CONVERT_HEAT["events"]),
                                root_menu(heat=False))
        app = self.start_app([before, landed])
        rc, out = self.run_cli("step", "3a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.choose(before["waitingFor"],
                                                     "convert 8 heat")])
        self.assertEqual(self.game()["me"]["resources"]["heat"], 0)

    def test_place_follow_up_answers_the_space_prompt(self):
        before = view_from_game(self.game(), root_menu())
        asking = view_from_game(self.game(), SPACE_PROMPT)
        landed = view_from_game(after(self.store, SP_CITY_C4["events"]), root_menu())
        app = self.start_app([before, asking, landed])
        rc, out = self.run_cli("step", "3b")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 2)
        self.assertEqual(app.posts[0]["response"]["card"], "City")
        self.assertEqual(app.posts[1], sparring.space(grid_to_space("C4")))
        self.assertTrue(self.plan_step("3b")["done"])
        self.assertIn("17", self.game()["board"])

    def test_uncovered_follow_up_after_send_asks_and_does_not_mark_done(self):
        before = view_from_game(self.game(), root_menu())
        asking = view_from_game(self.game(), {"type": "player", "title": "Select player",
                                              "players": ["green", "blue"]})
        app = self.start_app([before, asking])
        rc, out = self.run_cli("step", "2a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(len(app.posts), 1)            # the SP itself went out
        self.assertIn("player", out)
        self.assertFalse(self.plan_step("2a")["done"])

    def test_pass_that_closes_the_generation_is_done_without_follow_ups(self):
        # every other seat had passed: the app rolls the generation and the
        # very next prompt is research ("Select card(s) to buy") with the
        # income already paid — not a follow-up of the pass, and not a
        # verify mismatch (listen.py once runs produce afterwards)
        before = view_from_game(self.game(), root_menu())
        rolled = view_from_game(self.game(), BUY_PROMPT)
        rolled["game"]["generation"] += 1
        rolled["game"]["phase"] = "research"
        rolled["thisPlayer"]["megacredits"] += 25
        app = self.start_app([before, rolled])
        rc, out = self.run_cli("step", "4a", "--force", "gate covered by TestPassGateRefusesBeforeSending")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.choose(before["waitingFor"],
                                                     "pass for this generation")])
        self.assertTrue(self.plan_step("4a")["done"])
        self.assertIn("generation", out.lower())

    def test_pass_step_sends_pass(self):
        before = view_from_game(self.game(), root_menu())
        landed = view_from_game(self.game(), None)
        app = self.start_app([before, landed])
        # 4a is the pass gate; earlier steps stay open — the executor only
        # runs the label asked for.
        rc, out = self.run_cli("step", "4a", "--force", "gate covered by TestPassGateRefusesBeforeSending")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.choose(before["waitingFor"],
                                                     "pass for this generation")])
        self.assertTrue(self.plan_step("4a")["done"])


# ── safety: mismatch / verify / dry-run ──────────────────────

class TestSafety(ExecuteCase):
    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PASS])

    def test_research_prompt_for_a_play_step_is_a_mismatch_nothing_sent(self):
        before = view_from_game(self.game(), BUY_PROMPT)
        app = self.start_app([before])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])
        self.assertIn("ASK", out)
        self.assertIn("Select cards to buy", out)       # the tree is printed
        self.assertFalse(self.plan_step("1a")["done"])

    def test_not_my_turn_is_a_mismatch(self):
        before = view_from_game(self.game(), None)
        app = self.start_app([before])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])
        self.assertIn("NOT WAITING", out)

    def test_app_rejecting_the_input_asks_with_the_tree(self):
        before = view_from_game(self.game(), root_menu())
        app = self.start_app([before], reject=True)
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertIn("400", out)
        self.assertFalse(self.plan_step("1a")["done"])

    def test_pre_existing_drift_is_reported_not_blocking(self):
        """The tracker was already 3 MC off before the step; the step's
        own effect matches → success, drift flagged for verify --sync."""
        pre = self.game()
        pre["me"]["resources"]["mc"] += 3
        post = after(self.store, PLAY_SPONSORS["events"])
        post["me"]["resources"]["mc"] += 3
        app = self.start_app([view_from_game(pre, root_menu()),
                              view_from_game(post, root_menu())])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertIn("pre-existing", out)
        self.assertTrue(self.plan_step("1a")["done"])

    def test_dry_run_prints_the_inputs_and_sends_nothing(self):
        before = view_from_game(self.game(), root_menu())
        app = self.start_app([before])
        rc, out = self.run_cli("step", "1a", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [])
        self.assertIn('"projectCard"', out)
        self.assertIn("Play project card", out)          # prompt tree
        self.assertFalse(self.plan_step("1a")["done"])

    def test_no_done_sends_and_verifies_but_leaves_the_plan_open(self):
        before = view_from_game(self.game(), root_menu())
        landed = view_from_game(after(self.store, PLAY_SPONSORS["events"]), root_menu())
        app = self.start_app([before, landed])
        rc, out = self.run_cli("step", "1a", "--no-done")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertFalse(self.plan_step("1a")["done"])

    def test_unknown_label_is_an_error(self):
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "9z")
        self.assertEqual(rc, 1)
        self.assertEqual(app.posts, [])


# ── P9: in app modes the APP is the rules engine ─────────────

class TestAppIsTheRulesEngine(ExecuteCase):
    """P9 phase 3. The executor used to refuse (exit 41) whenever its
    sandbox simulation of the step disagreed with the app view. In the P8
    game that fired six times on CORRECT steps whose card effects the
    engine does not model (blue-card actions, an or-choice card, an ocean
    bonus), each costing a manual `planlib done --apply` + `verify --sync`
    recovery. In app modes the app settles the rules: the step's events go
    to the tracker (ledger + plan semantics), the app view is then ADOPTED
    over the numbers, and the sandbox prediction is printed as ℹ lines."""

    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PASS])

    def _skewed(self, **overrides):
        """The app view after the step, skewed the way an unmodelled card
        effect skews it: plants and energy the engine never granted, plus
        a card in hand it cannot know about."""
        landed = after(self.store, PLAY_SPONSORS["events"])
        view = view_from_game(landed, root_menu(cards=("Power Plant",)))
        tp = view["thisPlayer"]
        tp["plants"], tp["energy"] = 3, 2
        tp["cardsInHand"] = [{"name": "Power Plant"}, {"name": "Birds"}]
        tp["cardsInHandNbr"] = 2
        tp.update(overrides)
        return view

    def _run(self, **overrides):
        before = view_from_game(self.game(), root_menu(calculated={"Sponsors": 6}))
        app = self.start_app([before, self._skewed(**overrides)])
        return app, self.run_cli("step", "1a")

    def test_the_step_is_marked_done_and_the_tracker_equals_the_app(self):
        app, (rc, out) = self._run()
        self.assertEqual(rc, 0, out)
        self.assertTrue(self.plan_step("1a")["done"])
        g = self.game()
        r = g["me"]["resources"]
        self.assertEqual((r["plants"], r["energy"]), (3, 2))
        self.assertEqual(sorted(g["me"]["hand"]), ["Birds", "Power Plant"])
        self.assertEqual(r["mc"], 24)          # the step's own effect stands
        self.assertEqual(g["me"]["production"]["mc"], 2)

    def test_the_prediction_is_printed_as_info_lines_never_a_refusal(self):
        app, (rc, out) = self._run()
        self.assertNotIn("VERIFY MISMATCH", out)
        self.assertNotIn("✗", out)
        self.assertIn("ℹ plants: sandbox predicted 0, app shows 3", out)
        self.assertIn("app adopted:", out)

    def test_a_resource_the_engine_over_counted_is_adopted_downward(self):
        app, (rc, out) = self._run(megacredits=20)     # app charged 4 more
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 20)
        self.assertIn("Zed MC 24→20", out)

    def test_globals_are_adopted_too(self):
        before = view_from_game(self.game(), root_menu(calculated={"Sponsors": 6}))
        landed = self._skewed()
        landed["game"]["oxygenLevel"] = 4              # an effect we never saw
        self.start_app([before, landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.game()["globals"]["oxygen"], 4)

    def test_the_log_records_app_adopted(self):
        self._run()
        log = (Path(self.tmp.name) / "state" / "log.md").read_text()
        self.assertIn("execute.py: 1a sent to the app, app-adopted", log)

    def test_a_generation_closing_pass_does_not_adopt_post_income_values(self):
        """The app has already paid the income; produce.py has not run.
        Adopting there is the P8 #17 double-count — listen.py once does it
        after ingesting 'Generation N'."""
        self.set_plan([PASS])
        before = view_from_game(self.game(), root_menu())
        rolled = view_from_game(self.game(), BUY_PROMPT)
        rolled["game"]["generation"] += 1
        rolled["game"]["phase"] = "research"
        rolled["thisPlayer"]["megacredits"] += 25
        self.start_app([before, rolled])
        rc, out = self.run_cli("step", "4a", "--force", "last seat to pass")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.game()["me"]["resources"]["mc"], 30)   # not +25
        self.assertIn("NOT adopted", out)


class TestTrackerRefusesWhatTheAppAllowed(ExecuteCase):
    """The app is the rules engine, so it can accept what the tracker's
    replay refuses (a discount / trigger / choice the engine does not
    model). The send already happened: leaving the tracker stale is the
    P8 recovery cost, so the app view is adopted anyway and the step is
    handed back as an ASK with the one command that closes it."""

    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PASS])       # affordable when composed
        Engine(self.store).res("Zed", "mc", -28)   # 2 MC left by execution time

    def test_the_app_view_is_still_adopted_and_the_step_stays_open(self):
        before = view_from_game(self.game(), root_menu(calculated={"Sponsors": 6}))
        landed = copy.deepcopy(before)
        landed["thisPlayer"]["megacredits"] = 0        # the app charged it
        landed["thisPlayer"]["megacreditProduction"] = 2
        self.start_app([before, landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], 0)          # adopted
        self.assertEqual(g["me"]["production"]["mc"], 2)         # adopted
        self.assertFalse(self.plan_step("1a")["done"])
        self.assertIn("--no-apply", out)


class TestAdoptionKeepsLedgerAndPlan(ExecuteCase):
    """Adoption replaces NUMBERS. The action ledger (actionsThisGen) and
    the plan's done state come from the step's events and must survive it
    — otherwise the same blue-card action could be taken twice."""

    def setUp(self):
        super().setUp()
        eng = Engine(self.store)
        eng.hand_add(["Inventors' Guild"])
        eng.play("Zed", "Inventors' Guild", cost=9)
        step = copy.deepcopy(USE_GUILD)
        step["buy"] = False
        self.set_plan([step, PASS])

    def test_ledger_entry_and_done_flag_survive_the_adoption(self):
        menu_view = view_from_game(self.game(), root_menu(
            actions=("Inventors' Guild",)))
        offer = copy.deepcopy(menu_view)
        offer["waitingFor"] = GUILD_OFFER
        settled = copy.deepcopy(menu_view)
        settled["thisPlayer"]["plants"] = 5        # unmodelled effect
        self.start_app([menu_view, offer, settled])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["plants"], 5)      # adopted
        ledger = g["me"]["actionsThisGen"]
        self.assertTrue(ledger, "the action ledger was cleared by adoption")
        self.assertTrue(any(v.get("used") for v in ledger.values()), ledger)
        self.assertTrue(self.plan_step("1a")["done"])
        self.assertIn("Inventors' Guild",
                      [c["name"] for c in g["me"]["playedCards"]])


class TestPhysicalModeStillRefuses(ExecuteCase):
    """Exit 41 survives where there is no app to adopt: in physical mode
    the sandbox simulation is the only check there is, so a disagreement
    still refuses to mark the step done."""

    mode = "physical"

    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PASS])

    def test_verify_mismatch_exits_41_and_leaves_the_plan_open(self):
        before = view_from_game(self.game(), root_menu())
        wrong = after(self.store, PLAY_SPONSORS["events"])
        wrong["me"]["resources"]["mc"] -= 4                 # app shows 20, not 24
        app = self.start_app([before, view_from_game(wrong, root_menu())])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_VERIFY, out)
        self.assertEqual(len(app.posts), 1)
        self.assertIn("24", out)
        self.assertIn("20", out)
        self.assertFalse(self.plan_step("1a")["done"])
        self.assertEqual(self.game()["me"]["resources"]["mc"], 30)   # untouched

    def test_a_matching_view_is_marked_app_verified(self):
        before = view_from_game(self.game(), root_menu())
        landed = view_from_game(after(self.store, PLAY_SPONSORS["events"]),
                                root_menu(cards=("Power Plant",)))
        self.start_app([before, landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertIn("app-verified", out)
        self.assertNotIn("app adopted", out)


# ── turn + executor modes ────────────────────────────────────

class TestTurn(ExecuteCase):
    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PLAY_PP_STEEL, PASS])
        self.before = view_from_game(self.game(), root_menu(
            calculated={"Sponsors": 6, "Power Plant": 4}))
        mid_game = after(self.store, PLAY_SPONSORS["events"])
        self.mid = view_from_game(mid_game, root_menu(cards=("Power Plant",),
                                                      calculated={"Power Plant": 4}))
        with tempfile.TemporaryDirectory() as tmp:      # both steps landed
            sandbox = Path(tmp) / "state"
            shutil.copytree(self.store.state_dir, sandbox)
            eng = Engine(Store(tmp, state_dir=sandbox))
            for st in (PLAY_SPONSORS, PLAY_PP_STEEL):
                for ev in st["events"]:
                    getattr(eng, ev["method"])(*ev["args"], **ev.get("kwargs", {}))
            self.end = view_from_game(eng.store.load_game(), root_menu(cards=()))

    def test_turn_runs_the_labels_in_order_auto_mode_sends(self):
        app = self.start_app([self.before, self.mid, self.end])
        rc, out = self.run_cli("turn", "1a", "1b")
        self.assertEqual(rc, 0, out)
        self.assertEqual([p["response"]["card"] for p in app.posts],
                         ["Sponsors", "Power Plant"])
        self.assertTrue(self.plan_step("1a")["done"])
        self.assertTrue(self.plan_step("1b")["done"])
        marks = (Path(self.tmp.name) / "state" / "latency.jsonl").read_text()
        self.assertIn('"phase": "execute"', marks)

    def test_turn_stops_at_the_first_failure(self):
        # second prompt lacks Power Plant → 1b asks; 1a stays done
        mid = view_from_game(after(self.store, PLAY_SPONSORS["events"]),
                             root_menu(cards=()))
        app = self.start_app([self.before, mid])
        rc, out = self.run_cli("turn", "1a", "1b")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(len(app.posts), 1)
        self.assertTrue(self.plan_step("1a")["done"])
        self.assertFalse(self.plan_step("1b")["done"])

    def test_manual_executor_dry_runs_with_a_reminder(self):
        judgment.set_value(self.store, "executor", "manual")
        app = self.start_app([self.before])
        rc, out = self.run_cli("turn", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [])
        self.assertIn("manual", out)
        self.assertIn("click", out.lower())
        self.assertFalse(self.plan_step("1a")["done"])

    def test_assist_executor_prints_then_sends(self):
        judgment.set_value(self.store, "executor", "assist")
        app = self.start_app([self.before, self.mid])
        rc, out = self.run_cli("turn", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertIn("assist", out)
        self.assertLess(out.index("send:"), out.index("verify"))


# ── research / corp / pass verbs ─────────────────────────────

class TestPromptVerbs(ExecuteCase):
    def test_pick_sends_the_card_list(self):
        app = self.start_app([view_from_game(self.game(), BUY_PROMPT),
                              view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick", "Comet", "Sponsors")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.cards(["Comet", "Sponsors"])])

    def test_pick_nothing_sends_an_empty_list(self):
        app = self.start_app([view_from_game(self.game(), BUY_PROMPT),
                              view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.cards([])])

    def test_pick_answers_a_payment_follow_up_with_mc(self):
        # Helion (heat as money): buying research cards raises "Select how
        # to spend 6 M€ for 2 cards" — answered MC-only, never guessed
        paying = {"type": "payment", "title": "Select how to spend 6 M€ for 2 cards",
                  "amount": 6, "paymentOptions": {"heat": True}}
        app = self.start_app([view_from_game(self.game(), BUY_PROMPT),
                              view_from_game(self.game(), paying),
                              view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick", "Comet", "Sponsors")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.cards(["Comet", "Sponsors"]),
                                     sparring.payment(mc=6)])

    def test_state_flag_selects_the_seat_store(self):
        # a seat runs the executor against ITS OWN state dir (never the
        # advisor's state/): --state replaces the cwd default
        before = view_from_game(self.game(), root_menu())
        app = self.start_app([before, view_from_game(self.game(), None)])
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = execute.main(["--state", str(self.store.state_dir), "pass"])
        self.assertEqual(rc, 0, out.getvalue() + err.getvalue())
        self.assertEqual(len(app.posts), 1)

    def test_pick_on_a_non_card_prompt_asks(self):
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("pick", "Comet")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])

    def test_pick_refuses_a_card_the_prompt_does_not_offer(self):
        app = self.start_app([view_from_game(self.game(), BUY_PROMPT)])
        rc, out = self.run_cli("pick", "Birds")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])

    def test_corp_sends_initial_cards_with_corp_and_buys(self):
        app = self.start_app([view_from_game(self.game(), INITIAL_PROMPT),
                              view_from_game(self.game(), None)])
        rc, out = self.run_cli("corp", "Helion", "Comet")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [{"type": "initialCards", "responses": [
            sparring.cards(["Helion"]), sparring.cards(["Comet"])]}])

    def test_corp_on_a_non_initial_prompt_asks(self):
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("corp", "Helion")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])

    def test_pass_verb(self):
        before = view_from_game(self.game(), root_menu())
        app = self.start_app([before, view_from_game(self.game(), None)])
        rc, out = self.run_cli("pass")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts, [sparring.choose(before["waitingFor"],
                                                     "pass for this generation")])

    def test_pass_when_not_offered_asks(self):
        app = self.start_app([view_from_game(self.game(), BUY_PROMPT)])
        rc, out = self.run_cli("pass")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [])


# ── pure builders ────────────────────────────────────────────

class TestBuilders(unittest.TestCase):
    def test_action_menu_detection(self):
        self.assertTrue(execute.is_action_menu(root_menu()))
        self.assertFalse(execute.is_action_menu(SPACE_PROMPT))
        self.assertFalse(execute.is_action_menu(
            {"type": "or", "title": "Select one option",
             "options": [{"title": "A", "type": "option"}]}))
        self.assertFalse(execute.is_action_menu(None))

    def test_plan_actions_groups_follow_ups_under_their_action(self):
        acts = execute.plan_actions(SP_CITY_C4)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["event"]["method"], "standard")
        self.assertEqual(acts[0]["follow"]["space"], grid_to_space("C4"))

    def test_plan_actions_carries_choice_and_target_from_kwargs(self):
        step = {"id": "x", "events": [
            {"method": "play", "args": ["Zed", "Comet"],
             "kwargs": {"cost": 21, "choice": 1, "target": "green"}},
            {"method": "place", "args": ["Zed", "ocean", "B2"]}]}
        acts = execute.plan_actions(step)
        f = acts[0]["follow"]
        self.assertEqual((f["or"], f["player"], f["space"]),
                         (1, "green", grid_to_space("B2")))

    def test_tracker_only_events_yield_no_action(self):
        step = {"id": "x", "events": [{"method": "res", "args": ["Zed", "mc", 2]}]}
        self.assertEqual(execute.plan_actions(step), [])

    def test_pass_gate_step_is_a_pass_action(self):
        acts = execute.plan_actions(PASS)
        self.assertEqual(acts[0]["event"]["method"], "pass")


if __name__ == "__main__":
    unittest.main()


# ── P7: the pass gate must refuse BEFORE the pass is transmitted ──

class TestPassGateRefusesBeforeSending(ExecuteCase):
    """P7 (the first full-autopilot practice game): the saturation gate lived only in
    planlib.mark_done, which runs AFTER execute.py has already sent the
    pass — so in app mode it degraded to a printed advisory and protected
    nothing. It cost a real VP in the final generation: my own SP Aquifer
    took oceans to 9, which revived Kelp Farming (min 6 oceans, 1 printed
    VP, affordable), and the gate only said so once the pass was gone.

    With executor=auto the check has to run pre-send and REFUSE."""

    def setUp(self):
        super().setUp()
        self.set_plan([PASS])

    def test_pass_with_available_actions_is_refused_and_nothing_sent(self):
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "4a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertEqual(app.posts, [], "the pass must NOT reach the app")
        self.assertFalse(self.plan_step("4a")["done"])
        self.assertIn("PASS REFUSED", out)

    def test_refusal_names_the_available_items(self):
        self.start_app([view_from_game(self.game(), root_menu())])
        _, out = self.run_cli("step", "4a")
        self.assertIn("Sponsors", out)

    def test_force_sends_the_pass(self):
        app = self.start_app([view_from_game(self.game(), root_menu())])
        rc, out = self.run_cli("step", "4a", "--force",
                               "everything left is negative this late")
        self.assertEqual(rc, 0)
        self.assertEqual(len(app.posts), 1)
        self.assertTrue(self.plan_step("4a")["done"])

    def test_saturated_board_passes_without_force(self):
        """Nothing available → the pass goes through untouched."""
        empty = root_menu(cards=(), milestones=(), awards=(), heat=False,
                          actions=(), sp_disabled=("Aquifer", "City"))
        eng = Engine(self.store)
        eng.res("Zed", "mc", -30)          # broke: no SP, no cards
        eng.res("Zed", "heat", -8)
        eng.hand_remove("Sponsors")
        eng.hand_remove("Power Plant")
        app = self.start_app([view_from_game(self.game(), empty)])
        rc, _ = self.run_cli("step", "4a")
        self.assertEqual(rc, 0)
        self.assertEqual(len(app.posts), 1)


# ── P7: a card that DRAWS must not fail verification on hand size ──

PLAY_CONVOY = {"id": "1a", "summary": "Play Convoy From Europa",
               "volatility": "recheck", "cue": "ocean on 04",
               "events": [{"method": "play", "args": ["Zed", "Convoy From Europa"],
                           "kwargs": {"cost": 15}},
                          {"method": "place", "args": ["Zed", "ocean", "04"]}]}


class TestDrawCardVerification(ExecuteCase):
    """P7 refusal #4: Convoy From Europa places an ocean AND draws a card.
    The engine does not model the draw, so `hand` came back one short and
    execute exited 41 on a step where nothing was actually wrong. Recovery
    cost three extra calls every time. cards/db.json already records
    behavior.drawCard, so the executor can stop treating hand size as
    blocking for a card that declares a draw."""

    def setUp(self):
        super().setUp()
        eng = Engine(self.store)
        eng.res("Zed", "mc", +20)
        eng.hand_add(["Convoy From Europa"])
        self.set_plan([PLAY_CONVOY, PASS])

    def _post_view(self, step, extra_hand=0, **overrides):
        """The app view after the step really happened: a sandbox
        simulation of the step's own events, plus any deliberate skew."""
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp) / "state"
            shutil.copytree(self.store.state_dir, sandbox)
            eng = Engine(Store(tmp, state_dir=sandbox))
            for ev in step["events"]:
                getattr(eng, ev["method"])(*ev.get("args", []), **ev.get("kwargs", {}))
            g = eng.store.load_game()
        view = view_from_game(g, root_menu())
        tp = view["thisPlayer"]
        tp["cardsInHandNbr"] += extra_hand
        tp["cardsInHand"] += [{"name": f"Drawn {i}"} for i in range(extra_hand)]
        tp.update(overrides)
        return view

    def test_draw_does_not_block_the_step(self):
        step = self.plan_step("1a")
        pre = view_from_game(self.game(), root_menu())
        post = self._post_view(step, extra_hand=1)
        lines = execute.verify_step(self.store, step, pre, post)
        self.assertTrue(any("engine == app" in ln for ln in lines), lines)

    def test_the_relaxation_is_reported_not_silent(self):
        step = self.plan_step("1a")
        pre = view_from_game(self.game(), root_menu())
        post = self._post_view(step, extra_hand=1)
        lines = execute.verify_step(self.store, step, pre, post)
        self.assertTrue(any("draw" in ln.lower() for ln in lines), lines)

    def test_a_real_resource_mismatch_still_blocks(self):
        """The relaxation must be scoped to hand size only."""
        step = self.plan_step("1a")
        pre = view_from_game(self.game(), root_menu())
        post = self._post_view(step, extra_hand=1, megacredits=999)
        with self.assertRaises(execute.VerifyMismatch):
            execute.verify_step(self.store, step, pre, post)

    def test_hand_still_blocks_for_a_card_that_does_not_draw(self):
        self.set_plan([PLAY_SPONSORS, PASS])
        step = self.plan_step("1a")
        pre = view_from_game(self.game(), root_menu())
        post = self._post_view(step, extra_hand=1)
        with self.assertRaises(execute.VerifyMismatch):
            execute.verify_step(self.store, step, pre, post)


# ── P7 E1: blue-card actions whose follow-up is an unknown card offer ──

USE_GUILD = {"id": "1a", "summary": "Use Inventors' Guild",
             "volatility": "safe",
             "events": [{"method": "use_action", "args": ["Inventors' Guild"]}]}
GUILD_OFFER = {"type": "card", "title": "Select card(s) to buy",
               "cards": [{"name": "Birds"}], "min": 0, "max": 1}


class TestActionCardFollowUp(ExecuteCase):
    """P7 E1 — the most frequent friction of the run (5 refusals). The
    Inventors' Guild action opens a 'Select card(s) to buy' prompt whose
    contents cannot be known at plan time, so the step never covers it: the
    action was CONSUMED, the step stayed open, and recovery took three
    calls (sparring.py pick → listen.py once → planlib done --confirm).

    Two fixes: a step may DECLARE the policy up front (`buy`), and when it
    cannot, `execute.py resolve` closes the whole thing in ONE call."""

    def setUp(self):
        super().setUp()
        eng = Engine(self.store)
        eng.hand_add(["Inventors' Guild"])
        eng.play("Zed", "Inventors' Guild", cost=9)   # registers the action

    def _plan(self, step):
        self.set_plan([step, PASS])

    def test_refusal_names_the_offer_and_the_recovery_command(self):
        self._plan(USE_GUILD)
        menu_view = view_from_game(self.game(), root_menu(
            actions=("Inventors' Guild",)))
        offer = copy.deepcopy(menu_view)
        offer["waitingFor"] = GUILD_OFFER
        self.start_app([menu_view, offer])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK)
        self.assertIn("Birds", out)
        self.assertIn("resolve", out)

    def test_declared_decline_answers_it_in_one_call(self):
        step = copy.deepcopy(USE_GUILD)
        step["buy"] = False          # executor directive, not an engine arg
        self._plan(step)
        menu_view = view_from_game(self.game(), root_menu(
            actions=("Inventors' Guild",)))
        offer = copy.deepcopy(menu_view)
        offer["waitingFor"] = GUILD_OFFER
        settled = copy.deepcopy(menu_view)
        app = self.start_app([menu_view, offer, settled])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[-1], sparring.cards([]))
        self.assertTrue(self.plan_step("1a")["done"])

    def test_resolve_closes_an_open_step_in_one_call(self):
        self._plan(USE_GUILD)
        menu_view = view_from_game(self.game(), root_menu(
            actions=("Inventors' Guild",)))
        offer = copy.deepcopy(menu_view)
        offer["waitingFor"] = GUILD_OFFER
        settled = copy.deepcopy(menu_view)
        app = self.start_app([menu_view, offer, settled])
        self.run_cli("step", "1a")                    # consumes the action
        self.assertFalse(self.plan_step("1a")["done"])
        rc, out = self.run_cli("resolve", "1a", "--cards", "Birds")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[-1], sparring.cards(["Birds"]))
        self.assertTrue(self.plan_step("1a")["done"])

    def test_resolve_with_no_cards_declines(self):
        self._plan(USE_GUILD)
        menu_view = view_from_game(self.game(), root_menu(
            actions=("Inventors' Guild",)))
        offer = copy.deepcopy(menu_view)
        offer["waitingFor"] = GUILD_OFFER
        settled = copy.deepcopy(menu_view)
        app = self.start_app([menu_view, offer, settled])
        self.run_cli("step", "1a")
        rc, _ = self.run_cli("resolve", "1a")
        self.assertEqual(rc, 0)
        self.assertEqual(app.posts[-1], sparring.cards([]))
        self.assertTrue(self.plan_step("1a")["done"])


class TestPickSyncsTheHand(ExecuteCase):
    """P7 gen-11 friction: `execute.py pick` sent the buy but did not tell
    the tracker, so composing the plan immediately afterwards failed with
    "'Permafrost Extraction' is not in hand" — the cards WERE bought, the
    tracker just did not know yet. set_plan then aborted, leaving the
    previous generation's plan live and the next execute reporting
    '1a is already marked done'. pick knows exactly what it sent."""

    def setUp(self):
        super().setUp()
        self.set_plan([PASS])

    def test_bought_cards_land_in_the_tracker_hand(self):
        offer = {"type": "card", "title": "Select card(s) to buy",
                 "cards": [{"name": "Comet"}, {"name": "Birds"}],
                 "min": 0, "max": 2}
        before = view_from_game(self.game(), offer)
        settled = view_from_game(self.game(), None)
        self.start_app([before, settled])
        rc, out = self.run_cli("pick", "Comet")
        self.assertEqual(rc, 0, out)
        self.assertIn("Comet", self.game()["me"]["hand"])

    def test_declining_changes_nothing(self):
        offer = {"type": "card", "title": "Select card(s) to buy",
                 "cards": [{"name": "Comet"}], "min": 0, "max": 1}
        before = view_from_game(self.game(), offer)
        self.start_app([before, view_from_game(self.game(), None)])
        hand = list(self.game()["me"]["hand"])
        rc, _ = self.run_cli("pick")
        self.assertEqual(rc, 0)
        self.assertEqual(self.game()["me"]["hand"], hand)


# ── P8: a PLACEMENT whose hex bonus is cards must not fail on hand size ──

SP_AQUIFER_ON_13 = {"id": "1a", "summary": "SP Aquifer, ocean on 13 (+2 cards)",
                    "volatility": "recheck", "cue": "ocean on 13",
                    "events": [{"method": "standard", "args": ["Zed", "aquifer"],
                                "kwargs": {}},
                               {"method": "place", "args": ["Zed", "ocean", "13"]}]}


class TestPlacementCardBonusVerification(TestDrawCardVerification):
    """P8 issue #2: hex 13 (B6) pays +2 cards on placement. The engine
    records the bonus but cannot know which cards were drawn, so the app's
    hand came back 2 larger and execute exited 41 on a correct step; the
    tracker was left stale (MC/TR not applied) and needed a hand recovery.
    The same relaxation that covers behavior.drawCard cards must cover a
    `place` event on a hex whose bonus list contains 'card'."""

    def setUp(self):
        ExecuteCase.setUp(self)
        eng = Engine(self.store)
        eng.res("Zed", "mc", +20)
        self.set_plan([SP_AQUIFER_ON_13, PASS])

    def test_draw_does_not_block_the_step(self):
        step = self.plan_step("1a")
        pre = view_from_game(self.game(), root_menu())
        post = self._post_view(step, extra_hand=2)
        lines = execute.verify_step(self.store, step, pre, post)
        self.assertTrue(any("engine == app" in ln for ln in lines), lines)

    def test_the_relaxation_is_reported_not_silent(self):
        step = self.plan_step("1a")
        pre = view_from_game(self.game(), root_menu())
        post = self._post_view(step, extra_hand=2)
        lines = execute.verify_step(self.store, step, pre, post)
        self.assertTrue(any("ℹ hand" in ln and "13" in ln for ln in lines), lines)


# ── P8 #6: `pick` must charge the tracker 3 MC per bought card ──

BUY_TWO = {"type": "card", "title": "Select card(s) to buy",
           "cards": [{"name": "Comet"}, {"name": "Birds"}], "min": 0, "max": 2}


class TestPickChargesTheCards(ExecuteCase):
    """P8 issue #6: `execute.py pick` landed the bought cards in the tracker
    hand but never paid for them, so the tracker ran 3 MC per card high from
    the buy until the next `listen.py sync-me` repaired it — every single
    generation of the P8 game. The listener cannot fix it either: once the
    cards are in hand its "Zed bought N card(s)" block is OWN_REFLECTED
    (listen.reflected, kind "bought") and is skipped whole, so nothing ever
    charges the MC. pick knows exactly what it bought — it pays."""

    def setUp(self):
        super().setUp()
        self.set_plan([PASS])

    def _helion(self, mc: int, heat: int) -> None:
        eng = Engine(self.store)
        eng.corp("Zed", "Helion", 0)
        r = self.game()["me"]["resources"]
        eng.res("Zed", "mc", mc - r["mc"])
        eng.res("Zed", "heat", heat - r["heat"])

    def test_two_bought_cards_cost_six_mc(self):
        mc = self.game()["me"]["resources"]["mc"]
        self.start_app([view_from_game(self.game(), BUY_TWO),
                        view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick", "Comet", "Birds")
        self.assertEqual(rc, 0, out)
        g = self.game()
        self.assertEqual(g["me"]["resources"]["mc"], mc - 6)
        self.assertIn("Comet", g["me"]["hand"])
        self.assertIn("Birds", g["me"]["hand"])

    def test_declining_costs_nothing(self):
        mc = self.game()["me"]["resources"]["mc"]
        self.start_app([view_from_game(self.game(), BUY_TWO),
                        view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.game()["me"]["resources"]["mc"], mc)

    def test_a_card_the_listener_already_landed_is_not_charged_twice(self):
        Engine(self.store).hand_add(["Comet"])       # listen.py got there first
        mc = self.game()["me"]["resources"]["mc"]
        self.start_app([view_from_game(self.game(), BUY_TWO),
                        view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick", "Comet")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.game()["me"]["resources"]["mc"], mc)

    def test_helion_pays_the_remainder_of_the_card_price_with_heat(self):
        self._helion(mc=3, heat=8)
        self.start_app([view_from_game(self.game(), BUY_TWO),
                        view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick", "Comet", "Birds")
        self.assertEqual(rc, 0, out)
        r = self.game()["me"]["resources"]
        self.assertEqual((r["mc"], r["heat"]), (0, 5))


# ── P8 #15: a `player` follow-up wants the COLOR, not the name ──

PLAY_HEAT_TRAPPERS = {
    "id": "1a", "summary": "Play Heat Trappers on Anna", "volatility": "safe",
    "events": [{"method": "play", "args": ["Zed", "Heat Trappers"],
                "kwargs": {"cost": 6, "target": "Anna"}}]}
PLAYER_PROMPT = {"type": "player", "title": "Select player to remove heat "
                                            "production from",
                 "players": ["green", "blue"]}


class TestPlayerTargetIsSentAsColor(ExecuteCase):
    """P8 issue #15: a step's {"target": "Ben"} was transmitted as
    {"type":"player","player":"Ben"} and the app answered HTTP 400 "Player
    not available" (Heat Trappers G9, Power Supply Consortium G11) — the app
    identifies players by COLOR. setup.json holds name/color/aliases, so the
    executor resolves it before sending; a color given directly still
    passes through."""

    def setUp(self):
        super().setUp()
        eng = Engine(self.store)
        eng.hand_add(["Heat Trappers"])
        eng.prod("Anna", "heat", +2)              # something to remove
        self.set_plan([PLAY_HEAT_TRAPPERS, PASS])

    def _run(self, target: str):
        step = copy.deepcopy(PLAY_HEAT_TRAPPERS)
        step["events"][0]["kwargs"]["target"] = target
        self.set_plan([step, PASS])
        before = view_from_game(self.game(), root_menu(
            cards=("Heat Trappers",), calculated={"Heat Trappers": 6}))
        asking = view_from_game(self.game(), PLAYER_PROMPT)
        landed = view_from_game(after(self.store, step["events"]), root_menu())
        app = self.start_app([before, asking, landed])
        return app, self.run_cli("step", "1a")

    def test_a_player_name_is_resolved_to_the_app_color(self):
        app, (rc, out) = self._run("Anna")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[1], sparring.target_player("green"))
        self.assertTrue(self.plan_step("1a")["done"])

    def test_an_alias_is_resolved_too(self):
        app, (rc, out) = self._run("ana")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[1], sparring.target_player("green"))

    def test_a_color_passes_through_unchanged(self):
        app, (rc, out) = self._run("green")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[1], sparring.target_player("green"))

    def test_resolve_target_also_takes_a_name(self):
        self.set_plan([PLAY_HEAT_TRAPPERS, PASS])
        asking = view_from_game(self.game(), PLAYER_PROMPT)
        landed = view_from_game(after(self.store, PLAY_HEAT_TRAPPERS["events"]),
                                root_menu())
        app = self.start_app([asking, landed])
        rc, out = self.run_cli("resolve", "1a", "--target", "Anna")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[0], sparring.target_player("green"))


# ── P8 #16 + #19: every payment builder splits MC then Helion heat ──

class TestHelionPayments(ExecuteCase):
    """P8 issues #16 and #19: the payment builders sent megacredits=<price>
    unconditionally. As Helion (heat IS money) with MC below the price the
    app answered HTTP 400 "You do not have that many resources" and left a
    dangling "Select how to spend" prompt — on card buys (G10) and on
    standard projects (G13, G14), each costing a hand-written recovery
    payment. One splitter feeds every builder: MC first, the remainder from
    heat, and only for Helion."""

    def _helion(self, mc: int, heat: int) -> tuple[Engine, dict]:
        eng = Engine(self.store)
        eng.corp("Zed", "Helion", 0)
        r = self.game()["me"]["resources"]
        eng.res("Zed", "mc", mc - r["mc"])
        eng.res("Zed", "heat", heat - r["heat"])
        return Engine(self.store), self.game()

    def test_split_pays_mc_first_then_heat(self):
        _, game = self._helion(21, 18)
        self.assertEqual(execute._payment_split(game, 23), {"mc": 21, "heat": 2})

    def test_split_is_mc_only_for_a_price_the_mc_covers(self):
        _, game = self._helion(30, 18)
        self.assertEqual(execute._payment_split(game, 23), {"mc": 23, "heat": 0})

    def test_standard_asteroid_paid_entirely_with_heat(self):
        eng, game = self._helion(0, 23)
        resp = execute._build_standard(["Zed", "asteroid"], {}, root_menu(),
                                       eng, game)
        pay = resp["response"]["payment"]
        self.assertEqual((pay["megacredits"], pay["heat"]), (0, 14))

    def test_standard_greenery_splits_mc_then_heat(self):
        eng, game = self._helion(21, 18)
        resp = execute._build_standard(["Zed", "greenery"], {}, root_menu(),
                                       eng, game)
        pay = resp["response"]["payment"]
        self.assertEqual((pay["megacredits"], pay["heat"]), (21, 2))

    def test_a_non_helion_corp_never_pays_with_heat(self):
        eng = Engine(self.store)
        eng.res("Zed", "mc", -self.game()["me"]["resources"]["mc"])   # broke
        game = self.game()
        self.assertEqual(execute._payment_split(game, 14), {"mc": 14, "heat": 0})
        resp = execute._build_standard(["Zed", "asteroid"], {}, root_menu(),
                                       eng, game)
        pay = resp["response"]["payment"]
        self.assertEqual((pay["megacredits"], pay["heat"]), (14, 0))
        with self.assertRaises(EventError):      # and the tracker refuses it
            eng.standard("Zed", "asteroid")

    def test_card_buy_payment_prompt_splits_mc_and_heat(self):
        self._helion(3, 8)
        paying = {"type": "payment", "amount": 6,
                  "title": "Select how to spend 6 M€ for 2 cards",
                  "paymentOptions": {"heat": True}}
        app = self.start_app([view_from_game(self.game(), BUY_PROMPT),
                              view_from_game(self.game(), paying),
                              view_from_game(self.game(), None)])
        rc, out = self.run_cli("pick", "Comet", "Nuclear Power")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[1], sparring.payment(mc=3, heat=3))

    def test_resolve_card_offer_payment_splits_mc_and_heat(self):
        eng = Engine(self.store)
        eng.hand_add(["Inventors' Guild"])
        eng.play("Zed", "Inventors' Guild", cost=9)
        self._helion(1, 8)
        self.set_plan([USE_GUILD, PASS])
        menu = root_menu(actions=("Inventors' Guild",))
        paying = {"type": "payment", "amount": 3,
                  "title": "Select how to spend 3 M€ for 1 cards",
                  "paymentOptions": {"heat": True}}
        app = self.start_app([view_from_game(self.game(), GUILD_OFFER),
                              view_from_game(self.game(), paying),
                              view_from_game(self.game(), menu)])
        rc, out = self.run_cli("resolve", "1a", "--cards", "Birds")
        self.assertEqual(rc, 0, out)
        self.assertEqual(app.posts[1], sparring.payment(mc=1, heat=2))


# ── P8 #3: no stale saturation report after a generation-closing pass ──

class TestPassGatePostSendReport(ExecuteCase):
    """P8 issue #3 (G2, G11, G12): after the pass that CLOSED the generation
    the executor printed "⚠ pass with available actions … 8 heat →
    temperature — have 8 heat" although heat was 3 when the pass was sent.
    planlib.mark_done's gate re-reads live state, and by then the app had
    already paid the income — it reports the NEXT generation's options as
    missed ones. The pre-send gate is the real gate; when the send rolled
    the generation the after-the-fact report is noise and is skipped."""

    def setUp(self):
        super().setUp()
        self.set_plan([PASS])
        self.before = view_from_game(self.game(), root_menu())

    def _rolled(self):
        v = view_from_game(self.game(), BUY_PROMPT)
        v["game"]["generation"] += 1
        v["game"]["phase"] = "research"
        v["thisPlayer"]["megacredits"] += 25          # income already paid
        v["thisPlayer"]["heat"] += 5
        return v

    def test_generation_closing_pass_skips_the_stale_report(self):
        app = self.start_app([self.before, self._rolled()])
        rc, out = self.run_cli("step", "4a", "--force", "last seat to pass")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("pass with available actions (app mode", out)
        self.assertTrue(self.plan_step("4a")["done"])
        self.assertEqual(len(app.posts), 1)

    def test_the_skip_is_explained_not_silent(self):
        self.start_app([self.before, self._rolled()])
        _, out = self.run_cli("step", "4a", "--force", "last seat to pass")
        self.assertIn("post-send", out.lower())

    def test_a_mid_generation_pass_still_reports(self):
        app = self.start_app([self.before, view_from_game(self.game(), None)])
        rc, out = self.run_cli("step", "4a", "--force", "nothing worth doing")
        self.assertEqual(rc, 0, out)
        self.assertIn("pass with available actions (app mode", out)


# ── P8 #10 (execute side): refuse to run a plan whose last patch failed ──

class TestPatchFailedRefusal(ExecuteCase):
    """P8 issue #10: a `planlib.py patch` raised (dict spec where a list was
    expected) and the chained `execute.py turn` ran the UNPATCHED step —
    Physics Complex instead of the SP power plant, ≈2 VP. planlib records
    the failure on the plan (`patchFailed`); the executor refuses to run any
    step while it stands, unless the player overrides."""

    def setUp(self):
        super().setUp()
        self.set_plan([PLAY_SPONSORS, PASS])
        self.before = view_from_game(self.game(),
                                     root_menu(calculated={"Sponsors": 6}))
        self.landed = view_from_game(after(self.store, PLAY_SPONSORS["events"]),
                                     root_menu(cards=("Power Plant",)))

    def _flag(self, msg="patch spec must be a LIST of steps"):
        p = self.store.state_dir / "plan.json"
        plan = json.loads(p.read_text())
        plan["patchFailed"] = msg
        p.write_text(json.dumps(plan))

    def test_step_refuses_while_the_last_patch_is_unapplied(self):
        self._flag()
        app = self.start_app([self.before])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])
        self.assertIn("LIST", out)
        self.assertFalse(self.plan_step("1a")["done"])

    def test_turn_refuses_too(self):
        self._flag()
        app = self.start_app([self.before])
        rc, out = self.run_cli("turn", "1a")
        self.assertEqual(rc, execute.EXIT_ASK, out)
        self.assertEqual(app.posts, [])

    def test_force_runs_it_anyway(self):
        self._flag()
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a", "--force", "1a is unaffected")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
        self.assertTrue(self.plan_step("1a")["done"])

    def test_without_the_key_nothing_is_refused(self):
        app = self.start_app([self.before, self.landed])
        rc, out = self.run_cli("step", "1a")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(app.posts), 1)
