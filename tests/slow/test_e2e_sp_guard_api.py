"""E2E (the VERIFICATION RULE) — the zero-effect standard-project gate on
the path it actually guards: the API lane, against the local practice app.

A gate verified only by unit fixtures is UNVERIFIED: the fixtures drive
`apply.py`, live play drives `execute.py`. So this test creates a REAL
game on the local app (scripts/newgame.py + setup.py), plays the research
phase through `execute.py corp`, walks the seats until the app asks US for
an action, and only then arms the condition and runs `execute.py step`.

Arming the condition. The bug is a track that fills BETWEEN plan time and
execution — an opponent's raise during our wait. Making the app's own
temperature reach +8 °C would take dozens of scripted turns, so the track
is filled in the TRACKER (`apply.py sync temperature 8`, the same verb a
photo/screenshot reconciliation uses) while the app still reads −30. That
is the live-vs-plan disagreement the gate exists for, and it also proves
the gate reads the most advanced of the two views rather than only the
app's. What is real here is everything the gate touches: a real plan step,
a real `waitingFor` fetch, a real send decision, and a real assertion that
NOTHING reached the app.

SKIPS (never fails spuriously) when port 8080 is closed or a game is
already active in this checkout.
"""
from __future__ import annotations

import io
import json
import shutil
import socket
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import e2e_practice as E                            # noqa: E402
import newgame                                      # noqa: E402
from appapi import AppClient                        # noqa: E402
from tmlib import Store                             # noqa: E402

URL = newgame.BASE
ME, ME_COLOR = "Zed", "red"
OPPONENT, OPP_COLOR = "Anna", "green"
EXIT_ASK = 40


def _port_open(host: str = "127.0.0.1", port: int = 8080) -> bool:
    s = socket.socket()
    s.settimeout(1.0)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _verb(script: str, *args, stdin: str | None = None,
          timeout: float = 120) -> tuple[int, str]:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *map(str, args)]
    r = subprocess.run(cmd, cwd=str(ROOT), input=stdin, capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


@unittest.skipIf((ROOT / "state").exists(),
                 "a game is active in this checkout (state/ exists) — the "
                 "e2e refuses to touch it")
@unittest.skipUnless(_port_open(),
                     "the practice app is not listening on port 8080 "
                     "(python3 scripts/server.py)")
class TestZeroEffectStandardProjectGateOverTheApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        spec = f"{ME}={ME_COLOR},{OPPONENT}={OPP_COLOR}"
        resp = newgame.create(spec, url=URL)
        ids = {p["name"]: p["id"] for p in resp.get("players", [])}
        cls.pid, cls.opp_pid = ids[ME], ids[OPPONENT]
        rc, out = _verb("setup.py", stdin=E.setup_answers(
            ME, ME_COLOR, [(OPPONENT, OPP_COLOR)], URL, cls.pid))
        assert rc == 0, f"setup.py failed: {out[-800:]}"
        _verb("session.py", "link-player", OPPONENT, cls.opp_pid)
        cls.store = Store(str(ROOT))
        cls.game_dir = cls.store.state_dir.resolve()
        cls.client = AppClient(URL)

    @classmethod
    def tearDownClass(cls):
        _verb("session.py", "end", "--note", "e2e: SP zero-effect gate")
        if (ROOT / "state").exists() or (ROOT / "state").is_symlink():
            (ROOT / "state").unlink(missing_ok=True)
        if cls.game_dir.exists():
            shutil.rmtree(cls.game_dir, ignore_errors=True)

    # ── walking the seats to our own action prompt ──
    def _walk_to_action_menu(self) -> dict:
        for _ in range(40):
            view = self.client.player(self.pid)
            wf = view.get("waitingFor") or {}
            t = wf.get("type")
            if t == "or" and not E.is_first_action_menu(wf):
                return view
            if t == "initialCards":
                corp = E.first_corp(wf)
                self.assertIsNotNone(corp, "no corporation offered")
                rc, out = _verb("execute.py", "corp", corp)
                self.assertEqual(rc, 0, out[-800:])
            elif t == "card":
                rc, out = _verb("execute.py", "pick")
                self.assertEqual(rc, 0, out[-800:])
            elif t in ("or", None):
                # the app is waiting on the other seat (or on our corp's
                # mandatory first action, which this scenario avoids)
                if self.client.waiting_for(self.opp_pid).get("result") == "GO":
                    _verb("autoplay.py", "run", self.opp_pid, "--level", "passer")
                _verb("listen.py", "once")
            else:
                self.fail(f"unexpected prompt {t!r} at the app: "
                          f"{str(wf)[:200]}")
            _verb("listen.py", "once")
        self.fail("never reached our own action menu in 40 steps")

    def test_the_gate_refuses_before_the_app_ever_sees_the_asteroid(self):
        view = self._walk_to_action_menu()
        mc_before = int((view.get("thisPlayer") or {}).get("megacredits") or 0)

        # the track fills between plan time and execution
        rc, out = _verb("apply.py", "sync", "temperature", "8")
        self.assertEqual(rc, 0, out[-400:])

        plan = {"threats": E.THREATS, "exit": E.EXIT, "steps": [
            {"id": "1a", "volatility": "recheck", "summary": "SP asteroid",
             "events": [{"method": "standard", "args": [ME, "asteroid"],
                         "kwargs": {}}]},
            {"id": "1b", "volatility": "safe", "summary": "pass",
             "events": [], "passGate": True,
             "force": "e2e: the gate under test is the SP gate"}]}
        rc, out = _verb("planlib.py", "set", stdin=json.dumps(plan))
        self.assertEqual(rc, 0, out[-800:])

        rc, out = _verb("execute.py", "step", "1a")
        self.assertEqual(rc, EXIT_ASK, out[-1500:])
        self.assertIn("ZERO-EFFECT STANDARD PROJECT", out)
        self.assertIn("nothing sent", out)

        # NOTHING was transmitted: the app still asks the same question and
        # still holds our megacredits, and the plan step is still open
        after = self.client.player(self.pid)
        self.assertEqual(int((after.get("thisPlayer") or {}).get("megacredits") or 0),
                         mc_before, "14 M€ left the wallet — the gate leaked")
        self.assertEqual((after.get("waitingFor") or {}).get("type"), "or")
        rc, out = _verb("planlib.py", "show")
        self.assertIn("1a", out)
        self.assertNotIn("✅ 1a", out)

        # …and the SAME step goes through with an explicit, logged override
        why = "e2e: the app view is authoritative, the tracker is stale"
        rc, out = _verb("execute.py", "step", "1a", "--force", why)
        self.assertEqual(rc, 0, out[-1500:])
        self.assertIn("--force", out)
        log = (self.game_dir / "log.md").read_text()
        self.assertIn(why, log)
        self.assertIn("ZERO-EFFECT", log)


if __name__ == "__main__":
    unittest.main()
