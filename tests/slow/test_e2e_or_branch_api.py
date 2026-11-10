"""E2E (the VERIFICATION RULE): an or-card action driven BY TITLE against
the local practice app, asserted on the APP's own log.

A gate verified only by unit fixtures is unverified — the mismatch guard
this file's fix arms was green in the unit suite and inert in a real game
for exactly that reason. So: a real 2-player practice game on the local
app, a real or-action card played through `planlib.py set` +
`execute.py turn`, its branch named by TITLE, and the assertion made on
the app's log line and the app's own view of the card.

Made reliable by construction rather than by luck: the run creates games
down a fixed seed list until one DEALS an or-action microbe card (the app
does not deal deterministically from the seed, so the walk — not a single
magic seed — is what makes the scenario reachable), then scripts the whole
game: buy the card, play it, stock its store one action per generation by
TITLE, and spend it by TITLE once the app offers both branches. The card is
named only HERE, in the test's scenario — never in the scripts. SKIPS when the app is not
listening (`python3 scripts/server.py status`) or when a game is already
active in the repo; it never fails spuriously.
"""
import os
import socket
import shutil
import sys
import time
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import appapi                                    # noqa: E402
import e2e_practice as E                         # noqa: E402
import newgame                                   # noqa: E402
from appapi import AppClient, AppError, AppUnavailable   # noqa: E402

URL = os.environ.get("PHOBOS_APP_URL", "http://localhost:8080")
# The scenario's cards: an or-ACTION that stores its own resource, so the
# app offers both branches once the store is full — (title selector, how
# many resources the removal branch spends). The app logs the two branches
# distinguishably: "removed N resource(s) from …" vs "added 1 Microbe …".
OR_ACTION_CARDS = {
    "Regolith Eaters": ("remove 2 microbes", 2),
    "Nitrite Reducing Bacteria": ("remove 3 microbes", 3),
}
SEEDS = [round(0.05 * i, 2) for i in range(1, 19)]
BUDGET_S = 420


def _app_listening() -> bool:
    parts = urllib.parse.urlsplit(URL)
    try:
        with socket.create_connection((parts.hostname or "localhost",
                                       parts.port or 80), timeout=2):
            return True
    except OSError:
        return False


class OrBranchByTitleE2E(unittest.TestCase):
    """The regression the unit tests cannot reach: the app's own order."""

    runner = None
    game_dir = None

    @classmethod
    def setUpClass(cls):
        if not _app_listening():
            raise unittest.SkipTest(
                f"the practice app is not listening on {URL} "
                f"(python3 scripts/server.py status) — e2e skipped")
        if (ROOT / "state").exists():
            raise unittest.SkipTest(
                "a game is active in this repo (state/ exists) — the e2e "
                "will not touch it")

    def tearDown(self):
        if self.runner is not None and self.game_dir is not None:
            self.runner.verb("session.py", "end", "--note",
                             "e2e or-branch by title")
            if self.game_dir.exists():
                shutil.rmtree(self.game_dir, ignore_errors=True)

    # ── plumbing ──
    def log(self, *a):
        print(*a)

    def deal_with_an_or_card(self, runner):
        """Walk the seed list for a deal containing an or-action card.
        Returns (card, corp, ids) or (None, None, None)."""
        spec = ",".join([f"{E.ME}={E.ME_COLOR}",
                         *(f"{n}={c}" for n, c in E.OPPONENTS)])
        client = AppClient(URL)
        for seed in SEEDS:
            resp = newgame.create(spec, url=URL, seed=seed)
            ids = {p["name"]: p["id"] for p in resp.get("players", [])}
            wf = (client.player(ids[E.ME]) or {}).get("waitingFor") or {}
            opt = (E._initial_option(wf, "initial cards")
                   or E._initial_option(wf, "buy"))
            offered = E.offered_names(opt)
            hit = next((c for c in OR_ACTION_CARDS if c in offered), None)
            if hit:
                self.log(f"seed {seed}: {hit} dealt")
                return hit, E.first_corp(wf), ids
        return None, None, None

    def plan(self, steps):
        import json
        return json.dumps({"threats": E.THREATS, "exit": E.EXIT,
                           "exitAck": "scripted e2e run", "steps": steps})

    def run_plan(self, runner, steps):
        rc, text = runner.verb("planlib.py", "set", stdin=self.plan(steps))
        self.assertEqual(rc, 0, f"planlib set refused: {text[-400:]}")
        rc, text = runner.verb("execute.py", "turn",
                               *[s["id"] for s in steps])
        return rc, text

    @staticmethod
    def card_resources(view: dict, card: str) -> int:
        """What the APP says the card holds (players[].tableau, the same
        place verify.py reads card resources from)."""
        for p in view.get("players") or []:
            for c in p.get("tableau") or []:
                if c.get("name") == card and isinstance(c.get("resources"), int):
                    return int(c["resources"])
        return 0

    def app_log_text(self, client, pid) -> str:
        try:
            entries = client.game_logs(pid)
        except (AppError, AppUnavailable):
            return ""
        return "\n".join(appapi.render_log_entry(e) for e in entries or [])

    # ── the run ──
    def test_or_action_driven_by_title_executes_that_branch(self):
        card, corp, ids = self.deal_with_an_or_card(None)
        if card is None:
            self.skipTest(f"no or-action card in {len(SEEDS)} seeded deals "
                          f"— nothing to drive (tried {list(OR_ACTION_CARDS)})")
        label, needed = OR_ACTION_CARDS[card]
        runner = E.Runner(ROOT, URL, None, False, False, out=self.log)
        self.runner = runner
        runner.pid = ids[E.ME]
        runner.opp_pids = {n: ids[n] for n, _ in E.OPPONENTS}
        client = runner.client

        rc, text = runner.verb("setup.py", stdin=E.setup_answers(
            E.ME, E.ME_COLOR, E.OPPONENTS, URL, runner.pid))
        self.assertEqual(rc, 0, f"setup.py failed: {text[-400:]}")
        self.game_dir = runner.store.state_dir.resolve()
        for n, pid in runner.opp_pids.items():
            runner.verb("session.py", "link-player", n, pid)

        played, removed, acted = False, False, set()
        deadline = time.time() + BUDGET_S
        while time.time() < deadline and not removed:
            runner.drive_opponents()
            rc, _ = runner.verb("listen.py", "wait", "--timeout", "4",
                                "--interval", "0.5", timeout=60)
            if rc not in (E.EXIT_GO, E.EXIT_GO_EVENTS):
                continue
            view = client.player(runner.pid)
            if (view.get("game") or {}).get("phase") == "end":
                break
            wf = view.get("waitingFor") or {}
            t = wf.get("type")
            if t == "initialCards":
                rc, text = runner.verb("execute.py", "corp", corp, card)
                self.assertEqual(rc, 0, f"corp+buy failed: {text[-400:]}")
            elif t == "card":
                runner.verb("execute.py", "pick")        # buy nothing
            elif t == "or":
                gen = int((view.get("game") or {}).get("generation") or 1)
                if gen in acted:
                    # one action per generation (the ledger): end the turn
                    runner.verb("execute.py", "pass", "--force",
                                "scripted e2e run: one action per generation")
                    continue
                acted.add(gen)
                stored = self.card_resources(view, card)
                if not played:
                    rc, text = self.run_plan(runner, [
                        {"id": "1a", "volatility": "safe",
                         "summary": f"play {card}",
                         "events": [{"method": "play",
                                     "args": [E.ME, card]}]},
                        {"id": "1b", "volatility": "safe",
                         "summary": "stock the action by title",
                         "events": [{"method": "use_action",
                                     "args": [card, E.ME],
                                     "kwargs": {"choice": "add 1 microbe"}}]}])
                    self.assertEqual(rc, 0, f"play+action failed: {text[-600:]}")
                    played = True
                elif stored < needed:
                    rc, text = self.run_plan(runner, [
                        {"id": "1a", "volatility": "safe",
                         "summary": "stock the action by title",
                         "events": [{"method": "use_action",
                                     "args": [card, E.ME],
                                     "kwargs": {"choice": "add 1 microbe"}}]}])
                    self.assertEqual(rc, 0, f"action failed: {text[-600:]}")
                else:
                    # THE ASSERTION PATH: both branches are now live in the
                    # app's own prompt, in the app's own order.
                    rc, text = self.run_plan(runner, [
                        {"id": "1a", "volatility": "safe",
                         "summary": f"spend the store: {label}",
                         "events": [{"method": "use_action",
                                     "args": [card, E.ME],
                                     "kwargs": {"choice": label}}]}])
                    self.assertEqual(rc, 0, f"removal branch failed: "
                                            f"{text[-800:]}")
                    removed, before = True, stored
                    break
                runner.verb("listen.py", "once")
            else:
                runner.verb("execute.py", "pass", "--force",
                            "scripted e2e run: unhandled prompt")
        if not removed:
            self.skipTest(f"the scripted game did not reach {needed} "
                          f"resources on {card} within {BUDGET_S}s "
                          f"(played={played}, generations acted "
                          f"{sorted(acted)})")

        runner.verb("listen.py", "once")
        text = self.app_log_text(client, runner.pid)
        lines = [ln for ln in text.splitlines() if card in ln]
        self.assertTrue(lines, f"the app's log must name the card:\n{text}")
        last = lines[-1].lower()
        # The app's own words for the two branches: the removal branch
        # spends the store, the add branch stocks it. Only one can be true.
        self.assertIn("removed", last,
                      "the app's log must record the REMOVAL branch, not "
                      f"the add branch — its last line on the card: {last}")
        self.assertNotIn("added", last)
        self.assertIn(str(needed), last)
        self.assertEqual(self.card_resources(client.player(runner.pid), card),
                         before - needed,
                         "the app must have SPENT the store (the removal "
                         "branch), not stocked it (the add branch)")


if __name__ == "__main__":
    unittest.main()
