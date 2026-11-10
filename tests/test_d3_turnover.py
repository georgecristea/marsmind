"""D3 — idempotent turnover. One property, three symptoms (Codex game
2026-08-29, diagnostic H1): THE SAME GENERATION BOUNDARY APPLIED TWICE IS
A NO-OP.

H1a  the listener adopted "Generation N" (produce ran) and produce.py then
     paid the income AGAIN → tracker a generation ahead of the app.
     produce.py refuses in app modes unless --force; physical unchanged.
H1b  a reflected own event (the app log echoing a step the executor sent)
     was applied a second time — the heat conversion changed temperature,
     TR and heat again before the sync repaired them. The engine's own log
     line is the receipt: it names the standard action the way the app
     does, so the listener's receipt scan matches it.
H1c  a generation-7 blue-card action reflected after the turnover marked
     generation 8's ledger used. use_action stamps the generation; a
     source generation older than the tracker's cannot consume the ledger.

The rig is test_listen's scripted app over the real 4-player WGT export.
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import listen                                   # noqa: E402
import produce                                  # noqa: E402
import triage                                   # noqa: E402
from appapi import AppClient                    # noqa: E402
from test_listen import FakeApp, LINES, ME_PID, _setup   # noqa: E402
from test_new_game import SETUP as PHYSICAL_SETUP        # noqa: E402
from tmlib import Engine, EventError, Store     # noqa: E402

PRODUCE_PY = ROOT / "scripts" / "produce.py"
GEN2_AT = LINES.index("Generation 2")            # index 53
OWN_ACTION_AT = LINES.index("Diana used Equatorial Magnetizer action")   # 49


class Rig:
    """One app-online game: store + scripted app + listener factory."""

    def __init__(self, mode: str = "app-online"):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root, state_dir=self.root / "state")
        setup = _setup()
        setup["gameMode"] = mode
        self.app = FakeApp(setup, self.store)
        setup["appUrl"] = self.app.url
        self.store.init(setup)
        self.eng = Engine(self.store)
        self.revealed = 0

    def close(self):
        self.app.close()
        self.tmp.cleanup()

    def listener(self) -> "listen.Listener":
        return listen.Listener(self.store,
                               AppClient(self.app.url, timeout=2, retries=1), ME_PID)

    def reveal_to(self, n: int):
        self.app.reveal(LINES[self.revealed:n])
        self.revealed = n

    def drain(self):
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            r = self.listener().drain()
        return r, buf.getvalue()

    def game(self) -> dict:
        return self.store.load_game()

    def log(self) -> str:
        return self.store.log_path.read_text()

    def feed(self) -> list[dict]:
        return triage.read_feed(triage.feed_path(self.store))

    def produce_py(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(PRODUCE_PY), *args],
                              cwd=self.root, capture_output=True, text=True)

    def receipts(self, step: str):
        """What execute.py leaves in the log after a step is sent."""
        gen = self.game()["generation"]
        self.store.log(f"G{gen}", f"Executed plan step(s): {step}")
        self.store.log(f"G{gen}", f"execute.py: {step} sent to the app, app-adopted")


class RigCase(unittest.TestCase):
    MODE = "app-online"

    def setUp(self):
        self.rig = Rig(self.MODE)
        self.addCleanup(self.rig.close)
        self.store, self.eng, self.app = self.rig.store, self.rig.eng, self.rig.app


# ── H1a: produce.py is the physical table's verb ──────────────────────

class TestProducePyModeGate(RigCase):
    def test_app_mode_produce_py_refuses_without_force(self):
        self.rig.reveal_to(GEN2_AT)                 # generation 1 fully drained
        self.rig.drain()
        before_game = self.store.game_path.read_bytes()
        before_log = self.rig.log()
        r = self.rig.produce_py()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("listener owns turnover", r.stderr + r.stdout)
        self.assertIn("listen.py once", r.stderr + r.stdout)
        self.assertEqual(self.store.game_path.read_bytes(), before_game)
        self.assertEqual(self.rig.log(), before_log)
        self.assertEqual(self.rig.game()["generation"], 1)

    def test_app_mode_turnover_function_refuses_too(self):
        # the same gate for callers that import produce.turnover
        with self.assertRaises(EventError) as cm:
            produce.turnover(self.store)
        self.assertIn("listener owns turnover", str(cm.exception))
        self.assertEqual(self.rig.game()["generation"], 1)

    def test_app_mode_produce_py_force_runs_once_and_logs_why(self):
        r = self.rig.produce_py("--force", "app down, closing by hand",
                                "--skip-wgt", "fixture has WGT on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Production (end of gen 1)", r.stdout)
        self.assertEqual(self.rig.game()["generation"], 2)
        self.assertIn("app down, closing by hand", self.rig.log())

    def test_listener_first_then_produce_py_is_a_noop(self):
        self.rig.reveal_to(GEN2_AT + 2)             # "Generation 2" + first player
        self.rig.drain()
        g = self.rig.game()
        self.assertEqual(g["generation"], 2)
        before = self.store.game_path.read_bytes()
        r = self.rig.produce_py()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.store.game_path.read_bytes(), before)
        self.assertEqual(self.rig.log().count("Production (end of gen 1)"), 1)

    def test_listener_first_and_produce_first_converge(self):
        # order A: the listener adopts "Generation 2" (produce inside)
        a = self.rig
        a.reveal_to(GEN2_AT)
        a.drain()
        a.reveal_to(GEN2_AT + 2)
        a.drain()
        # order B: produce first (what --force does), then the listener
        b = Rig(self.MODE)
        self.addCleanup(b.close)
        b.reveal_to(GEN2_AT)
        b.drain()
        b.eng.produce()
        b.reveal_to(GEN2_AT + 2)
        b.drain()
        ga, gb = a.game(), b.game()
        self.assertEqual(ga["generation"], 2)
        self.assertEqual(ga, gb)
        self.assertEqual(a.log().count("Production (end of gen 1)"), 1)
        self.assertEqual(b.log().count("Production (end of gen 1)"), 1)


class TestPhysicalModeUnchanged(unittest.TestCase):
    """The physical table has no listener: produce.py runs exactly as
    today — no flag, no refusal, income + turnover + standings."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.init(PHYSICAL_SETUP)             # no gameMode key = physical
        self.eng = Engine(self.store)

    def test_produce_py_runs_without_flags(self):
        self.eng.prod("Zed", "mc", +3)
        r = subprocess.run([sys.executable, str(PRODUCE_PY)], cwd=self.tmp.name,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Production (end of gen 1)", r.stdout)
        self.assertIn("Standings", r.stdout)
        self.assertNotIn("listener owns turnover", r.stdout + r.stderr)
        g = self.store.load_game()
        self.assertEqual(g["generation"], 2)
        self.assertEqual(g["me"]["resources"]["mc"], 23)    # TR 20 + prod 3

    def test_turnover_function_needs_no_force(self):
        out = produce.turnover(self.store)
        self.assertIn("Production (end of gen 1)", out)
        self.assertEqual(self.store.load_game()["generation"], 2)

    def test_explicit_physical_mode_is_the_same(self):
        setup = self.store.load_setup()
        setup["gameMode"] = "physical"
        Store._write_json(self.store.setup_path, setup)
        r = subprocess.run([sys.executable, str(PRODUCE_PY)], cwd=self.tmp.name,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.store.load_game()["generation"], 2)


# ── the log applied twice ─────────────────────────────────────────────

class TestReplayTwice(RigCase):
    def test_draining_the_same_log_twice_is_byte_identical(self):
        self.rig.reveal_to(80)                      # generations 1 and 2
        self.rig.drain()
        game, log, feed = (self.store.game_path.read_bytes(), self.rig.log(),
                           self.rig.feed())
        self.assertEqual(self.rig.game()["generation"], 2)
        r, out = self.rig.drain()                   # a new listener = new process
        self.assertFalse(r.new)
        self.assertEqual(self.store.game_path.read_bytes(), game)
        self.assertEqual(self.rig.log(), log)
        self.assertEqual(self.rig.feed(), feed)


# ── H1b: an own reflected event is absorbed, not re-applied ───────────

class TestOwnReflectionAbsorbed(RigCase):
    def setUp(self):
        super().setUp()
        self.app.reveal(["Generation 1", "Diana played Teractor"])
        self.rig.drain()                            # cursor + logMark set

    def test_executed_heat_conversion_is_not_reapplied(self):
        self.eng.res("Diana", "heat", +8)
        self.eng.convert("Diana", "heat")           # what execute.py applies
        self.rig.receipts("2a")
        g = self.rig.game()
        temp, tr, heat = g["globals"]["temperature"], g["me"]["tr"], g["me"]["resources"]["heat"]
        self.assertEqual((temp, tr, heat), (-28, 21, 0))
        self.app.reveal(["Diana used Convert Heat standard action"])
        r, out = self.rig.drain()
        g = self.rig.game()
        self.assertEqual((g["globals"]["temperature"], g["me"]["tr"],
                          g["me"]["resources"]["heat"]), (temp, tr, heat))
        self.assertIn("already applied", out)
        entry = self.rig.feed()[-1]
        self.assertEqual(entry["kind"], "used_standard")
        self.assertIn("already applied", entry["note"])
        self.assertEqual(self.rig.log().count("spent 8 heat"), 1)

    def test_executed_plant_conversion_split_from_its_placement_is_not_reapplied(self):
        # the placement line lands in a later drain, so the tile check
        # cannot vouch for the head — the receipt has to
        self.eng.res("Diana", "plants", +8)
        self.eng.convert("Diana", "plants")
        self.rig.receipts("2b")
        g = self.rig.game()
        want = (g["globals"]["oxygen"], g["me"]["tr"], g["me"]["resources"]["plants"])
        self.assertEqual(want, (1, 21, 0))
        self.app.reveal(["Diana used Convert Plants standard action"])
        r, out = self.rig.drain()
        g = self.rig.game()
        self.assertEqual((g["globals"]["oxygen"], g["me"]["tr"],
                          g["me"]["resources"]["plants"]), want)
        self.assertIn("already applied", out)
        self.assertEqual(self.rig.log().count("spent 8 plants"), 1)

    def test_a_conversion_the_tracker_never_saw_is_still_applied(self):
        # the player clicked it in the app; nothing in the log vouches for it
        self.eng.res("Diana", "heat", +8)
        self.app.reveal(["Diana used Convert Heat standard action"])
        r, out = self.rig.drain()
        g = self.rig.game()
        self.assertEqual(g["globals"]["temperature"], -28)
        self.assertEqual(g["me"]["resources"]["heat"], 0)
        self.assertIn("own action absorbed", out)


# ── H1c: the action ledger is generation-stamped ──────────────────────

class TestActionLedgerGeneration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.store.init(PHYSICAL_SETUP)
        self.eng = Engine(self.store)
        self.eng.register_action("Ironworks")       # spend 4 energy → +1 O2
        self.eng.res("Zed", "energy", +8)

    def ledger(self) -> dict:
        return self.store.load_game()["me"]["actionsThisGen"]["Ironworks"]

    def test_use_action_stamps_the_generation(self):
        self.eng.use_action("Ironworks")
        self.assertEqual(self.ledger(), {"used": True, "gen": 1})

    def test_produce_resets_the_ledger_and_drops_the_stamp(self):
        self.eng.use_action("Ironworks")
        self.eng.produce()
        self.assertEqual(self.ledger(), {"used": False})

    def test_a_stale_reflection_cannot_consume_the_new_ledger(self):
        self.eng.use_action("Ironworks")
        self.eng.produce()                          # → generation 2
        g = self.store.load_game()
        oxygen, energy, tr = (g["globals"]["oxygen"], g["me"]["resources"]["energy"],
                              g["me"]["tr"])
        msg = self.eng.use_action("Ironworks", gen=1)   # the gen-1 use, drained late
        self.assertIn("absorbed", msg)
        self.assertIn("generation 1", msg)
        self.assertEqual(self.ledger(), {"used": False})
        g = self.store.load_game()
        self.assertEqual((g["globals"]["oxygen"], g["me"]["resources"]["energy"],
                          g["me"]["tr"]), (oxygen, energy, tr))
        # the log line is narrative for the event-log replay: not a use
        last = self.store.log_path.read_text().splitlines()[-1]
        self.assertNotIn("Action used:", last)
        # the real generation-2 use still works (energy became heat at turnover)
        self.eng.res("Zed", "energy", +4)
        self.eng.use_action("Ironworks")
        self.assertEqual(self.ledger(), {"used": True, "gen": 2})

    def test_the_current_generation_as_source_is_a_normal_use(self):
        self.eng.produce()
        self.eng.res("Zed", "energy", +4)
        self.eng.use_action("Ironworks", gen=2)
        self.assertEqual(self.ledger(), {"used": True, "gen": 2})
        self.assertEqual(self.store.load_game()["globals"]["oxygen"], 1)

    def test_a_second_use_in_the_same_generation_is_still_refused(self):
        self.eng.use_action("Ironworks", gen=1)
        with self.assertRaises(EventError):
            self.eng.use_action("Ironworks", gen=1)

    def test_unuse_frees_the_slot_and_the_stamp(self):
        self.eng.use_action("Ironworks")
        self.eng.unuse_action("Ironworks")
        self.assertEqual(self.ledger(), {"used": False})


class TestOwnActionAcrossTheBoundary(RigCase):
    """Live: my last action of the generation is executed, then the app's
    tail (its echo, the WGT step, "Generation 2") drains in ONE pass. The
    echo is absorbed while the ledger still says used, the turnover runs
    once, and generation 2 opens with the action available."""

    def test_echo_then_turnover_leaves_the_new_ledger_available(self):
        self.rig.reveal_to(OWN_ACTION_AT)          # up to my action's echo
        self.rig.drain()
        g = self.rig.game()
        self.assertEqual(g["generation"], 1)
        self.assertIn("Equatorial Magnetizer", g["me"]["actionsThisGen"])
        self.eng.use_action("Equatorial Magnetizer")   # executor, generation 1
        self.rig.receipts("3a")
        g = self.rig.game()
        tr, mc = g["me"]["tr"], g["me"]["resources"]["mc"]
        self.assertEqual(g["me"]["actionsThisGen"]["Equatorial Magnetizer"],
                         {"used": True, "gen": 1})
        r = self.rig.produce_py()                   # H1a: refused, no double income
        self.assertNotEqual(r.returncode, 0)
        self.rig.reveal_to(GEN2_AT + 2)             # echo … "Generation 2", first player
        r, out = self.rig.drain()
        g = self.rig.game()
        self.assertEqual(g["generation"], 2)
        self.assertEqual(g["me"]["tr"], tr)          # the echo did not add a TR
        self.assertEqual(g["me"]["resources"]["mc"],
                         mc + tr + g["me"]["production"]["mc"])   # income once
        self.assertEqual(g["me"]["actionsThisGen"]["Equatorial Magnetizer"],
                         {"used": False})
        self.assertEqual(self.rig.log().count("Production (end of gen 1)"), 1)


if __name__ == "__main__":
    unittest.main()
