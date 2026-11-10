#!/usr/bin/env python3
"""End-to-end proof of the API-play pipeline on the local app — NO model.

    e2e_practice.py [--gens N] [--greedy] [--url U] [--keep] [--root DIR]

Creates a 3-player game (Zed = us, Anna, Ben) with scripts/newgame.py,
drives scripts/setup.py through stdin (gameMode app-practice, appUrl, our
playerId) plus `session.py link-player` for the opponents, then loops:

  opponents  → `autoplay.py run <pid> --level greedy` whenever the app
               waits on them (the harness bot; hidden info never printed)
  our seat   → `listen.py wait` (lane 1: drains the LOG panel into the
               engine, exit 20/30 = GO) → the prompt decides the verb:
                 initialCards → `execute.py corp <first corp> [buys]`
                 card         → `execute.py pick [buys]`  (buys only --greedy)
                 action menu  → `execute.py pass`, or with --greedy a
                                one-step plan (`planlib.py set`: play one
                                follow-up-free card / SP asteroid / SP power
                                plant, then the passGate step) sent with
                                `execute.py turn 1a 1b`
  after every own turn → `listen.py once` (our own lines land only after
               the send), then `verify.py`: our seat and the globals must be
               exact (drift = incident: printed, the run stops); opponent-
               only drift is the replay's payment model (the app never
               prints how a card was paid) — adopted with `verify.py
               --sync` and counted as "opponent syncs";
               the engine's generation counter must equal the app's
               (the listener ingests "Generation N" and runs produce)
  game end / --gens reached → `session.py end`, feed + latency digest,
               the summary below; the game dir is deleted unless --keep.

Exit 0 only when drift stayed 0 and no ASK (40) / VERIFY (41) exit
occurred: 1 error, 2 drift, 3 refusal. Every verb runs as a subprocess
with cwd = the repo root — the same entry points the advisor uses.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import latency                                  # noqa: E402
import menu                                     # noqa: E402
import newgame                                  # noqa: E402
from appapi import AppClient, AppError, AppUnavailable   # noqa: E402
import tmlib                                    # noqa: E402
from tmlib import Store                         # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ME, ME_COLOR = "Zed", "red"
OPPONENTS = [("Anna", "green"), ("Ben", "yellow")]
THREATS = "e2e harness: dummy greedy seats, no threat model (scripted run)"
EXIT = ("e2e harness: scripted seat, no VP-exit model (repeatable: none — "
        "scripted run)")
BUY0_REASON = "e2e harness: scripted seat, no buying model"
EXIT_GO, EXIT_GO_EVENTS, EXIT_TIMEOUT = 20, 30, 3
EXIT_ASK, EXIT_VERIFY = 40, 41
# behavior keys the executor can send without a follow-up prompt and the
# engine verifies blind
SIMPLE_KEYS = {"production", "stock", "tr", "global", "titanumValue",
               "steelValue", "greeneryDiscount"}
# corporations whose generation-1 prompt is "Take first action … / Pass"
# (docs/actions.md): avoided when another corp is dealt. Derived from
# tmlib's one corporations table, never re-listed here.
FIRST_ACTION_CORPS = {n for n, r in tmlib.CORP_RULES.items()
                      if r.get("firstActionPrompt")}
VERIFY_ROW = re.compile(r"^\s*(\S+)\s+(exact|DRIFT\s+(.*))$")


# ── pure helpers ─────────────────────────────────────────────

def setup_answers(me: str, color: str, opponents: list[tuple[str, str]],
                  url: str, pid: str) -> str:
    """stdin for scripts/setup.py, one answer per prompt in its order:
    name, color, opponents, expansions, map, draft, seating, first player,
    the house-rules terminator, game mode, app URL, playerId."""
    opp = ",".join(f"{n}={c}" for n, c in opponents)
    return "\n".join([me, color, opp, "base,corporateEra,wgt", "", "", "",
                      "", "", "app-practice", url, pid]) + "\n"


def offered_names(opt: dict) -> list[str]:
    return [c.get("name") if isinstance(c, dict) else str(c)
            for c in (opt or {}).get("cards") or []]


def _initial_option(wf: dict, needle: str) -> dict | None:
    for opt in (wf or {}).get("options") or []:
        if needle in str(opt.get("title", "")).lower():
            return opt
    return None


def first_corp(wf: dict) -> str | None:
    """The first dealt corporation of an initialCards prompt — preferring
    one without a mandatory first action (its gen-1 prompt is covered only
    for Tharsis Republic's city, via a free_action_city step)."""
    opt = _initial_option(wf, "corporation")
    names = offered_names(opt) if opt else []
    plain = [n for n in names if n not in FIRST_ACTION_CORPS]
    return (plain or names or [None])[0]


def is_first_action_menu(wf: dict) -> bool:
    return isinstance(wf, dict) and wf.get("type") == "or" and any(
        "take first action" in str((o.get("title") or "")).lower()
        for o in wf.get("options") or [])


def is_wgt_prompt(wf: dict) -> bool:
    """The solar-phase World Government prompt. Also an `or`, but NOT the
    action menu — before WGT became the default this prompt never appeared
    in the rehearsal, and when newgame started defaulting it on the whole
    dryrun went RED on an unhandled ASK."""
    return isinstance(wf, dict) and wf.get("type") == "or" and \
        "world government" in str(wf.get("title") or "").lower()


def wgt_plan(me: str, wf: dict) -> dict:
    """Drive the WGT step as a real plan step, the way skills/turn-advisor
    writes it: one `wgt` event with the parameter, plus the hex when the
    branch is the ocean. Prefers a parameter that needs no space."""
    titles = [str(o.get("title") or "").lower() for o in wf.get("options") or []]
    param, kwargs = None, {}
    for name, needle in (("temperature", "increase temperature"),
                         ("oxygen", "increase oxygen")):
        if any(needle in t for t in titles):
            param = name
            break
    if param is None:
        ocean = next((o for o in wf.get("options") or []
                      if "add an ocean" in str(o.get("title") or "").lower()), None)
        spaces = (ocean or {}).get("spaces") or []
        if not spaces:
            return {}
        param, kwargs = "oceans", {"space_id": str(spaces[0])}
    hex_note = f" on {kwargs['space_id']}" if kwargs else ""
    return {"threats": THREATS, "exit": EXIT,
            "steps": [{"id": "1a", "volatility": "recheck",
                       "summary": f"WGT: raise {param}{hex_note} (no TR)",
                       "cue": f"{param} moved and no TR changed",
                       "events": [{"method": "wgt", "args": [param],
                                   "kwargs": kwargs}]}]}


def first_action_plan(me: str, corp: str | None, legal_city_spaces: list[str]) -> dict:
    """Generation 1 for a first-action corporation: Tharsis Republic places
    its free city on the first legal hex (free_action_city + place); any
    other corp's first action is not modelled — the plan is the pass."""
    steps = []
    if tmlib.corp_rule(corp, "freeFirstCity") and legal_city_spaces:
        ref = legal_city_spaces[0]
        steps.append({"id": "1a", "volatility": "recheck",
                      "summary": f"{corp} first action: free city on {ref}",
                      "cue": f"city on {ref}",
                      "events": [{"method": "free_action_city", "args": [me], "kwargs": {}},
                                 {"method": "place", "args": [me, "city", ref],
                                  "kwargs": {}}]})
    steps.append({"id": "1b" if steps else "1a", "volatility": "safe",
                  "summary": "pass", "events": [], "passGate": True})
    return {"threats": THREATS, "exit": EXIT, "steps": steps}


def simple_card(card: dict | None) -> bool:
    """A project card whose play needs no follow-up and whose effects the
    engine models exactly (production / stock / TR / global steps)."""
    if not card or card.get("type") == "corporation":
        return False
    beh = card.get("behavior") or {}
    if not beh:                      # no modelled behaviour = bespoke → follow-ups unknown
        return False
    return set(beh) <= SIMPLE_KEYS


def pick_buys(names: list[str], db_get, mc: int, limit: int = 2) -> list[str]:
    """--greedy research: the cheapest simple cards, 3 MC each, keeping
    enough cash to play the first of them."""
    picks = []
    budget = mc
    cands = sorted((c for c in (db_get(n) for n in names) if simple_card(c)),
                   key=lambda c: c.get("cost") or 0)
    for c in cands:
        if len(picks) >= limit:
            break
        if budget - 3 >= (c.get("cost") or 0):
            picks.append(c["name"])
            budget -= 3
    return picks


def greedy_plan(me: str, items: list[dict], db_get) -> dict:
    """A one-action plan from the engine's menu: the cheapest playable
    simple card, else SP asteroid, else SP power plant, then the pass
    step. Without an action the plan is the pass step alone."""
    action = None
    cards = sorted((it for it in items if it.get("kind") == "card"
                    and simple_card(db_get(it["name"]))),
                   key=lambda it: it.get("cost") or 0)
    if cards:
        it = cards[0]
        # "buy": false up front — some simple cards still open a "Select
        # card(s) to buy" follow-up when they resolve (a draw rider, a
        # corp trigger). Left undeclared it is an uncovered follow-up and
        # the rehearsal ASKs, which made the LIVE GATE flaky on the deal.
        action = {"summary": f"play {it['name']} ({it.get('cost')} MC)",
                  "buy": False,
                  "events": [{"method": "play", "args": [me, it["name"]], "kwargs": {}}]}
    else:
        sps = {it["name"]: it for it in items if it.get("kind") == "standard"}
        for proj in ("asteroid", "power_plant"):
            if proj in sps:
                action = {"summary": f"SP {proj} ({sps[proj].get('cost')} MC)",
                          "events": [{"method": "standard", "args": [me, proj],
                                      "kwargs": {}}]}
                break
    steps = []
    if action:
        steps.append({"id": "1a", "volatility": "safe", **action})
    steps.append({"id": "1b" if action else "1a", "volatility": "safe",
                  "summary": "pass", "events": [], "passGate": True})
    return {"threats": THREATS, "exit": EXIT, "steps": steps}


def feed_stats(path: Path) -> dict:
    out = {"lines": 0, "applied": 0, "gaps": 0, "gapLines": []}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        out["lines"] += 1
        if e.get("applied"):
            out["applied"] += 1
        else:
            out["gaps"] += 1
            out["gapLines"].append(str(e.get("error") or e.get("raw") or "?"))
    return out


def parse_verify(text: str) -> dict:
    """verify.py's table → {player: "" (exact) | drift text}."""
    rows = {}
    for line in text.splitlines():
        m = VERIFY_ROW.match(line)
        if m:
            rows[m.group(1)] = (m.group(3) or "").strip()
    return rows


@dataclass
class Summary:
    generations: int = 0
    own_turns: int = 0
    opponent_runs: int = 0
    wall: float = 0.0
    feed: dict = field(default_factory=lambda: {"lines": 0, "applied": 0,
                                                "gaps": 0, "gapLines": []})
    drift_incidents: list = field(default_factory=list)
    opponent_syncs: list = field(default_factory=list)
    refusals: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    latency: dict = field(default_factory=latency.empty_digest)
    game_dir: str = ""
    ended: str = ""

    def exit_code(self) -> int:
        if self.errors:
            return 1
        if self.drift_incidents:
            return 2
        if self.refusals:
            return 3
        return 0


def format_summary(s: Summary) -> str:
    lines = ["=== e2e summary ===",
             f"generations played: {s.generations}",
             f"own turns: {s.own_turns}",
             f"opponent bot runs: {s.opponent_runs}",
             f"feed lines: {s.feed['lines']} applied {s.feed['applied']} "
             f"gaps {s.feed['gaps']}",
             f"drift incidents: {len(s.drift_incidents)} (own seat + globals)",
             f"opponent syncs: {len(s.opponent_syncs)} (payment-model estimate, "
             f"verify.py --sync)",
             f"refusals (ASK/VERIFY): {len(s.refusals)}",
             f"errors: {len(s.errors)}",
             f"wall-clock: {s.wall:.1f}s",
             f"ended: {s.ended or '-'}   game dir: {s.game_dir or '-'}"]
    for label, items in (("gap", s.feed.get("gapLines") or []),
                         ("drift", s.drift_incidents),
                         ("opp-sync", s.opponent_syncs),
                         ("refusal", s.refusals), ("error", s.errors)):
        for it in items[:20]:
            lines.append(f"  {label}: {it}")
    lines.append(latency.format_digest(s.latency))
    lines.append(f"exit: {s.exit_code()}")
    return "\n".join(lines)


# ── the runner ───────────────────────────────────────────────

class Runner:
    def __init__(self, root: Path, url: str, gens: int | None, greedy: bool,
                 keep: bool, out=print):
        self.root, self.url, self.gens, self.greedy, self.keep = root, url, gens, greedy, keep
        self.out = out
        self.client = AppClient(url)
        self.store = Store(root)
        self.summary = Summary()
        self.pid = ""
        self.opp_pids: dict[str, str] = {}
        self.game_dir: Path | None = None

    # ── subprocess plumbing ──
    def verb(self, script: str, *args, stdin: str | None = None,
             timeout: float = 300) -> tuple[int, str]:
        cmd = [sys.executable, str(self.root / "scripts" / script), *map(str, args)]
        r = subprocess.run(cmd, cwd=str(self.root), input=stdin, capture_output=True,
                           text=True, timeout=timeout)
        text = (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()
        self.out(f"$ {script} {' '.join(map(str, args))}  → exit {r.returncode}")
        for ln in text.splitlines()[-12:]:
            self.out(f"    {ln}")
        return r.returncode, text

    # ── phases ──
    def create(self) -> None:
        spec = ",".join([f"{ME}={ME_COLOR}", *(f"{n}={c}" for n, c in OPPONENTS)])
        resp = newgame.create(spec, url=self.url)
        ids = {p["name"]: p["id"] for p in resp.get("players", [])}
        self.pid = ids[ME]
        self.opp_pids = {n: ids[n] for n, _ in OPPONENTS}
        self.out(f"game {resp.get('id')}: " + ", ".join(f"{n}={i}" for n, i in ids.items()))
        rc, _ = self.verb("setup.py", stdin=setup_answers(ME, ME_COLOR, OPPONENTS,
                                                         self.url, self.pid))
        if rc:
            raise RuntimeError("setup.py failed")
        for n, pid in self.opp_pids.items():
            rc, _ = self.verb("session.py", "link-player", n, pid)
            if rc:
                raise RuntimeError(f"link-player {n} failed")
        self.game_dir = self.store.state_dir.resolve()
        self.summary.game_dir = str(self.game_dir)

    def view(self) -> dict:
        return self.client.player(self.pid)

    def drive_opponents(self) -> bool:
        """Run the greedy bot for every opponent the app waits on. Returns
        True when at least one bot acted."""
        acted = False
        for name, pid in self.opp_pids.items():
            if self.client.waiting_for(pid).get("result") == "GO":
                rc, _ = self.verb("autoplay.py", "run", pid, "--level", "greedy")
                self.summary.opponent_runs += 1
                acted = True
                if rc:
                    self.summary.errors.append(f"autoplay {name} exit {rc}")
        return acted

    def own_turn(self, view: dict) -> None:
        wf = view.get("waitingFor") or {}
        t = wf.get("type")
        mc = int((view.get("thisPlayer") or {}).get("megacredits") or 0)
        import cards as cardlib
        if t == "initialCards":
            corp = first_corp(wf)
            if corp is None:
                self.summary.refusals.append("initialCards prompt without a corporation option")
                return
            buys = []
            if self.greedy:
                opt = _initial_option(wf, "initial cards") or _initial_option(wf, "buy")
                corp_mc = int((cardlib.find(corp) or {}).get("cost") or 0)
                buys = pick_buys(offered_names(opt), cardlib.find, mc=corp_mc, limit=3)
            rc, text = self.verb("execute.py", "corp", corp, *buys)
        elif t == "card":
            buys = pick_buys(offered_names(wf), cardlib.find, mc=mc, limit=2) \
                if self.greedy else []
            # the scripted seat may buy nothing generation after generation;
            # the buy-0 gate refuses that BEFORE sending, so the harness
            # declares its reason once, like any operator override
            gate = [] if buys else ["--override", BUY0_REASON]
            rc, text = self.verb("execute.py", "pick", *buys, *gate)
        elif t == "or" and is_wgt_prompt(wf):
            plan = wgt_plan(ME, wf)
            if not plan:
                self.summary.refusals.append("WGT prompt offered no usable branch")
                return
            rc, text = self.verb("planlib.py", "set", stdin=json.dumps(plan))
            if rc:
                self.summary.refusals.append(
                    f"planlib set refused (wgt): {text.splitlines()[-1]}")
                return
            rc, text = self.verb("execute.py", "step", "1a")
        elif t == "or":
            if self.greedy:
                game, setup = self.store.load_game(), self.store.load_setup()
                if is_first_action_menu(wf):
                    from tmlib import Engine, space_to_grid
                    corp = game["me"].get("corporation")
                    spaces = [space_to_grid(str(r["id"]))
                              for r in Engine(self.store).legal_spaces("city")] \
                        if tmlib.corp_rule(corp, "freeFirstCity") else []
                    plan = first_action_plan(ME, corp, spaces)
                else:
                    items = menu.available_actions(game, setup)
                    plan = greedy_plan(ME, items, cardlib.find)
                rc, text = self.verb("planlib.py", "set", stdin=json.dumps(plan))
                if rc:
                    self.summary.refusals.append(f"planlib set refused: {text.splitlines()[-1]}")
                    return
                labels = [s["id"] for s in plan["steps"]]
                rc, text = self.verb("execute.py", "turn", *labels)
            else:
                rc, text = self.verb("execute.py", "pass")
        else:
            self.summary.refusals.append(f"unhandled prompt type {t!r}: "
                                         f"{str(wf.get('title'))[:60]}")
            return
        self.summary.own_turns += 1
        if rc in (EXIT_ASK, EXIT_VERIFY):
            tag = "ASK" if rc == EXIT_ASK else "VERIFY"
            lines = text.splitlines()
            k = next((n for n, ln in enumerate(lines) if ln.startswith(tag)), None)
            detail = "\n      ".join(lines[k:k + 12]) if k is not None else text[-600:]
            self.summary.refusals.append(f"G{view.get('game', {}).get('generation')} "
                                         f"{t}: {detail}")
        elif rc:
            self.summary.errors.append(f"execute exit {rc}: {text[-200:]}")

    def check_drift(self, gen: int) -> None:
        """Own seat + globals must be byte-exact (the pipeline's proof).
        Opponent-only drift is the replay's payment model (the app never
        prints how a card was paid): adopted with `verify.py --sync`, the
        documented turnover step, and counted separately."""
        rc, text = self.verb("verify.py")
        rows = parse_verify(text)
        opp_only = True
        for player, drift in rows.items():
            if not drift:
                continue
            if player in (ME, "globals"):
                opp_only = False
                self.summary.drift_incidents.append(f"G{gen} {player}: {drift}")
            else:
                self.summary.opponent_syncs.append(f"G{gen} {player}: {drift}")
        if rc not in (0, 2):
            self.summary.errors.append(f"verify.py exit {rc}: {text[-200:]}")
        elif rc == 2 and opp_only:
            rc2, text2 = self.verb("verify.py", "--sync")
            if rc2:
                self.summary.errors.append(f"verify.py --sync exit {rc2}: {text2[-200:]}")

    def check_generation(self, app_gen: int) -> None:
        eng_gen = int(self.store.load_game().get("generation") or 0)
        if eng_gen != app_gen:
            self.summary.drift_incidents.append(
                f"generation counter: engine {eng_gen} vs app {app_gen} "
                f"(produce did not follow the 'Generation {app_gen}' line)")

    def loop(self) -> None:
        idle = 0
        while True:
            v = self.view()
            g = v.get("game") or {}
            app_gen = int(g.get("generation") or 1)
            self.summary.generations = max(self.summary.generations, app_gen)
            if g.get("phase") == "end":
                self.summary.ended = f"game over (phase end) in generation {app_gen}"
                self.verb("listen.py", "once")
                return
            if self.gens and app_gen > self.gens:
                self.summary.ended = f"--gens {self.gens} reached (app in generation {app_gen})"
                self.summary.generations = self.gens
                return
            self.drive_opponents()
            rc, _ = self.verb("listen.py", "wait", "--timeout", "4", "--interval", "0.5",
                              timeout=60)
            if rc in (EXIT_GO, EXIT_GO_EVENTS):
                idle = 0
                v = self.view()
                app_gen = int((v.get("game") or {}).get("generation") or app_gen)
                self.check_generation(app_gen)
                if self.gens and app_gen > self.gens:
                    continue                       # the head of the loop ends the run
                self.own_turn(v)
                # the app logs our own lines (and the whole table's initial
                # corp picks) only after the send — drain before verifying
                self.verb("listen.py", "once")
                self.check_drift(app_gen)
                if self.summary.drift_incidents or self.summary.errors:
                    self.summary.ended = "stopped on incident"
                    return
                if self.summary.refusals:
                    self.summary.ended = "stopped on refusal"
                    return
            elif rc == EXIT_TIMEOUT:
                idle += 1
                if idle > 30:
                    self.summary.errors.append("nobody moved for 30 waits — stuck")
                    return
            else:
                self.summary.errors.append(f"listen.py wait exit {rc}")
                return

    def finish(self) -> None:
        if self.game_dir is None:
            return
        self.summary.feed = feed_stats(self.game_dir / "feed.jsonl")
        self.summary.latency = latency.digest(self.game_dir / latency.FILENAME)
        self.verb("session.py", "end", "--note", f"e2e: {self.summary.ended}")
        if not self.keep and self.game_dir.exists():
            shutil.rmtree(self.game_dir)
            self.summary.game_dir += " (deleted; --keep retains it)"

    def run(self) -> int:
        start = time.monotonic()
        try:
            self.create()
            self.loop()
        except (AppError, AppUnavailable, RuntimeError, OSError,
                subprocess.SubprocessError, KeyError) as e:
            self.summary.errors.append(f"{type(e).__name__}: {e}")
        finally:
            self.summary.wall = time.monotonic() - start
            try:
                self.finish()
            except Exception as e:                 # the summary must print
                self.summary.errors.append(f"finish: {type(e).__name__}: {e}")
        self.out(format_summary(self.summary))
        return self.summary.exit_code()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gens", type=int, default=None,
                   help="stop when the app enters generation N+1 (default: game end)")
    p.add_argument("--greedy", action="store_true",
                   help="buy and play one simple card per generation via a plan")
    p.add_argument("--url", default=newgame.BASE)
    p.add_argument("--keep", action="store_true", help="keep the game dir")
    p.add_argument("--root", default=str(ROOT), help="repo root (state/ lives here)")
    a = p.parse_args(argv)
    root = Path(a.root).resolve()
    if (root / "state").exists():
        print(f"ERROR: a game is active ({root / 'state'}) — end it first", file=sys.stderr)
        return 1
    return Runner(root, a.url.rstrip("/"), a.gens, a.greedy, a.keep).run()


if __name__ == "__main__":
    sys.exit(main())
