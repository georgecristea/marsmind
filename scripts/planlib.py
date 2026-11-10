#!/usr/bin/env python3
"""Turn-ID plan store: the generation plan as labeled steps (1a, 1b, 2a…).

The advisor writes the plan here as {"threats": "<per-opponent threats>",
"exit": "<the VP exit AND its repeatable component>", "steps": [...]}
(a live plan without a threats block or an exit field is refused; when
shape.py flags zero repeatable sources, an exit that acknowledges no
repeatable component needs "exitAck": "<reason>", logged);
the player reports "performed 1a" / "did both turn 1" and the advisor marks
steps done + applies the matching events. The pass step (passGate:true)
is refused while menu.py lists any available action — unless the step
pre-declares `"force": "<per-item reason>"` (S4: read exactly like
`--force`, logged OVERRIDDEN, and still refused when the live list holds
an item the reason does not mention; the command-line --force wins).
Labels survive session death (files are truth) and follow the turn-grouped
grammar ^[0-9]+[a-z]$ in order (1a, 1b, 2a…) — set_plan/patch refuse a
malformed or out-of-order label naming the offender. `show` (render) IS
the house-style plan block (✅ done / ▶️ NEXT / ⬜ todo, 🎯 EXIT, threats)
— paste it verbatim, never retype it. Volatility per step:
  safe    🔒 own-mat engine step — execute blind
  recheck 🔁 board-contested (tiles, milestones, windows) — confirm vs
             latest opponent events before executing

Cue gate: a step
whose events include `milestone`, `award` or `place`, or that carries
`"cueGated": true`, may only be marked done on ITS OWN execution cue —
never inferred from the player's report about a different step. Such steps
MUST carry `"cue": "<what the player SEES when it went right>"` (e.g. "your
marker sits on Terraformer", "green city on F2"); set_plan refuses the
plan otherwise, naming the step. `milestone`/`award` steps autofill
"your marker on <Name>" when no cue is given (same style as the
mapHighlight autofill for `place`); `place` and bare cueGated steps need
explicit text. `done <id>` on a cue-gated step refuses unless
`--confirm "<text>"` is present (any non-empty text = the player confirmed the
cue); one --confirm covers every cue-gated label in the same call.
`show` prints "cue: …" under every open cue-gated step.

Award lock verdict: a step that funds one of MY awards has menu.py's lock
test injected onto it as `lockVerdict` at set/patch time and rendered
verbatim as its own "⚖ lock test:" line by `show` (and so by `turn.py
done`). The summary never has to carry it. The only refusal left is the
contradiction — a summary claiming "locked" against a "not lockable"
verdict, scoped to the sentence naming that award.

Terse budget: while `judgment.py`'s `verbosity` dial is `terse` (the
default), set/patch refuse an open step whose summary exceeds
SUMMARY_BUDGET characters, naming the step and its length. Machine-required
text (the step's cue, and menu.py's award lock verdict on the rare
occasion a summary quotes it at all) is stripped before
measuring; a step may opt out with `"verbose": "<reason>"` (logged).

Patch (round loop, lane 2): `patch` edits the DRAFT — or the live plan,
with --live or automatically when NO draft exists (the sweep concludes
into patch on the player's own turn, where the plan is always live) — from
a JSON spec on stdin: {"replace": [step…] or {"<id>": step…},
"insert_after": {"<id>": [step…] or {"<id>": step…}}, "remove": ["<id>"…],
"threats": "…", "feed": [line…]}. Step collections take the list form or a
dict keyed by step id (the key names the step). A bad shape is a one-line
usage error, and ANY patch failure is stamped into plan.json as
"patchFailed" (shown by `show` / `turn.py go`, checked by execute.py)
until the next successful set/patch/promote clears it.
Executed steps (done:true) are untouchable; the open remainder is
re-simulated exactly like set_plan (cue gate, autofills, duplicate-effect
warnings); the feed lines given are marked handled (triage.handle) and
the log records which feed ids triggered the patch. An empty patch with
only "feed" concludes a sweep: "plan stands". A sweep in flight
(state/sweep-inflight, written by `advise.py --sweep`) is cleared by patch
and ABANDONED by promote — promote never blocks: it clears the flag,
records judgment.record_abandonment + a latency "abandoned" mark, proceeds.
The flag carries the feed cursor the sweep READ; a patch concluding a
sweep whose stamp the live feed has passed is refused STALE (the standing
plan stays executable, nothing is marked failed) — discard the verdict
and relaunch, or override with --stale-ok "<reason>" (logged).
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appapi
from tmlib import Engine, EventError, Store

VOLATILITY = {"safe": "🔒", "recheck": "🔁"}

# W2-B: turn-grouped label grammar. Labels are the contract the player
# reports by ("did 1a"), so set_plan/patch refuse a malformed or
# out-of-order label naming the offender — a mislabeled step surfaces at
# plan time, never as a mismatched report at the table.
LABEL_RE = re.compile(r"^[0-9]+[a-z]$")


def _validate_labels(steps: list[dict], strict: bool = True) -> None:
    """Every step id matches ^[0-9]+[a-z]$ (1a, 1b, 2a…), ids are unique,
    and turn numbers never regroup (a turn-1 step after a turn-2 step is
    refused). `strict` (set_plan: a freshly composed plan) additionally
    requires the full (turn, letter) order — 1a, 1b, 2a…, turn-number gaps
    legal. Patches keep letters positional: inserting 1c between 1a and 1b
    is the documented mid-generation edit, so only the turn grouping is
    enforced there."""
    seen: set[str] = set()
    prev_key, prev_id = None, None
    for s in steps:
        sid = str(s.get("id") or "")
        if not LABEL_RE.match(sid):
            raise EventError(
                f"Plan step id {sid!r} is malformed — labels are turn-grouped "
                f"and match ^[0-9]+[a-z]$ (1a, 1b, 2a…); the player reports "
                f"by label, so the grammar is a contract")
        if sid.lower() in seen:
            raise EventError(f"Plan step id {sid!r} appears twice — labels "
                             f"must be unique (the player reports by label)")
        seen.add(sid.lower())
        key = (int(sid[:-1]), sid[-1])
        if prev_key is not None:
            if strict and key <= prev_key:
                raise EventError(
                    f"Plan step {sid!r} is out of order after {prev_id!r} — "
                    f"labels run 1a, 1b, 2a… (turn number, then letter, "
                    f"strictly increasing)")
            if not strict and key[0] < prev_key[0]:
                raise EventError(
                    f"Plan step {sid!r} regroups turn {key[0]} after "
                    f"{prev_id!r} — turn numbers never decrease down the "
                    f"plan (letters may be positional in a patch insert)")
        prev_key, prev_id = key, sid

# Standard projects that ALWAYS place a tile → the tile type they place.
# A plan step using one without a `place` event is incomplete (P7 #5).
TILE_PROJECTS = {"aquifer": "ocean", "greenery": "greenery", "city": "city"}

GAME_MODES = ("physical", "app-practice", "app-online")
APP_MODES = ("app-practice", "app-online")

# A DRAFT plan lives in plan.json with "draft": true — there is no second
# file today. The sidecar name is the one place `patch` looks for a draft
# kept BESIDE a live plan, which is the only case where patching the live
# plan without --live is still refused (P8 #9).
DRAFT_SIDECAR = "plan-draft.json"


def game_mode(store: Store) -> str:
    """setup.json gameMode: physical | app-practice | app-online.

    Old games have no gameMode key — they are physical (default).
    """
    try:
        return store.load_setup().get("gameMode") or "physical"
    except FileNotFoundError:
        return "physical"


def _fetch_app(url: str, pid: str) -> dict:
    """GET the vendor app's player view via scripts/appapi.py. One
    attempt, 2s timeout — table play never waits."""
    return appapi.AppClient(url, timeout=2, retries=1).player(pid)


def verify_after_apply(store: Store) -> str | None:
    """After events are applied, diff tracker vs the app (app
    modes only). Returns a ⚠ block on mismatch, else None. NEVER raises
    and NEVER blocks: any network/parse error is a silent skip — the
    advisor decides what to do with a mismatch.
    """
    try:
        if game_mode(store) not in APP_MODES:
            return None
        setup = store.load_setup()
        url = appapi.configured_url(setup)
        me_player = next((p for p in setup.get("players", [])
                          if p.get("isMe")), None)
        pid = (me_player or {}).get("playerId") or setup.get("playerId")
        if not url or not pid:
            return None
        data = _fetch_app(str(url).rstrip("/"), pid)
        mat = data.get("thisPlayer") or {}
        app_globals = data.get("game") or {}
        game = store.load_game()
        me = game["me"]
        checks = [
            ("MC", me["resources"]["mc"], mat.get("megaCredits")),
            ("TR", me["tr"], mat.get("terraformRating")),
            ("plants", me["resources"]["plants"], mat.get("plants")),
            ("heat", me["resources"]["heat"], mat.get("heat")),
            ("temperature", game["globals"]["temperature"],
             app_globals.get("temperature")),
            ("oxygen", game["globals"]["oxygen"], app_globals.get("oxygenLevel")),
            ("oceans", game["globals"]["oceans"], app_globals.get("oceans")),
        ]
        deltas = [f"  {label}: tracker {trk} vs app {app} (Δ {trk - app:+d})"
                  for label, trk, app in checks
                  if isinstance(app, int) and trk != app]
        if not deltas:
            return None
        return ("⚠ VERIFY-AFTER-APPLY — tracker/app mismatch "
                "(advisor decides; nothing was rolled back):\n"
                + "\n".join(deltas))
    except Exception:
        return None                       # never break table play


def _print_verify(store: Store) -> None:
    block = verify_after_apply(store)
    if block:
        print(block)


def _path(store: Store) -> Path:
    return store.state_dir / "plan.json"


def _write_plan(store: Store, plan: dict) -> None:
    _path(store).write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")


def feed_cursor(store: Store) -> int:
    """The last feed line id at this moment — stamped into every plan as
    "feedCursor" so triage's plan-relative triggers (class d) only look at
    lines NEWER than the plan (P8 #14). 0 when there is no feed yet."""
    try:
        import triage                      # lazy: triage imports planlib
        entries = triage.read_feed(triage.feed_path(store))
        return max((int(e.get("line") or 0) for e in entries), default=0)
    except Exception:
        return 0


# ── sweep in-flight flag ─────────────────────────────────────
# `advise.py --sweep` raises it when a judgment sweep starts (the model is
# reasoning over the sweep brief); `patch` lowers it (the sweep concluded);
# `promote` lowers it as an ABANDONMENT (the player's turn came first).
SWEEP_INFLIGHT = "sweep-inflight"


def sweep_flag_path(store: Store) -> Path:
    return store.state_dir / SWEEP_INFLIGHT


def set_sweep_inflight(store: Store, lines: list[int], gen=None,
                       cursor: int | None = None) -> dict:
    """`cursor` (W2-C) is the last feed line the sweep READ — its verdict
    is valid only for that feed; `patch` refuses a conclusion as STALE
    once the live feed has advanced past the stamp."""
    import time
    if gen is None:
        try:
            gen = store.load_game().get("generation")
        except (FileNotFoundError, ValueError):
            gen = None
    info = {"ts": round(time.time(), 3), "gen": gen,
            "lines": [int(x) for x in lines]}
    if cursor is not None:
        info["cursor"] = int(cursor)
    sweep_flag_path(store).write_text(json.dumps(info) + "\n")
    return info


def clear_sweep_inflight(store: Store) -> dict | None:
    """Lower the flag; returns what it held, or None when it was not set."""
    p = sweep_flag_path(store)
    if not p.exists():
        return None
    try:
        info = json.loads(p.read_text())
    except ValueError:
        info = {}
    p.unlink()
    return info if isinstance(info, dict) else {}


def abandon_sweep(store: Store) -> dict | None:
    """The player's turn came while a sweep was in flight: lower the flag,
    count the abandonment (judgment streak / auto-degrade), mark the sweep
    phase "abandoned" in the latency log, log it. None when no sweep was
    in flight. Never raises — promote must not block on bookkeeping."""
    info = clear_sweep_inflight(store)
    if info is None:
        return None
    import judgment
    import latency
    result = {"streak": None, "degraded": None}
    try:
        result = judgment.record_abandonment(store)
        latency.mark("sweep", "end", note=latency.ABANDONED, store=store)
        lines = ", ".join(f"#{x}" for x in info.get("lines") or []) or "none"
        try:
            gen = store.load_game().get("generation")
        except (FileNotFoundError, ValueError):
            gen = "?"
        store.log(f"G{gen}", f"Sweep ABANDONED at promote (player's turn came "
                             f"first; feed {lines}); abandonment streak "
                             f"{result['streak']}"
                  + (f"; judgment level degraded to {result['degraded']}"
                     if result.get("degraded") else ""))
    except Exception:
        pass
    return {**result, "lines": info.get("lines") or []}


def simulate(store: Store, steps: list[dict]) -> None:
    """Run every step's events against a SANDBOX copy of the state.

    Raises EventError naming the first infeasible step. This is the
    affordability/legality gate: no plan reaches the player unless the engine
    itself would accept every step in sequence (net-cost mental math
    says 'playable' where the gross cost says no).
    """
    if not any(s.get("events") for s in steps):
        return
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "state"
        shutil.copytree(store.state_dir, sandbox)
        eng = Engine(Store(tmp, state_dir=sandbox))
        for step in steps:
            for ev in step.get("events", []):
                try:
                    getattr(eng, ev["method"])(*ev.get("args", []),
                                               **ev.get("kwargs", {}))
                except EventError as e:
                    raise EventError(
                        f"Plan step {step['id']} is not executable: {e}")


def _simulate_events(store: Store, steps: list[dict]) -> None:
    """Pre-flight for mark_done(apply_events=True): run the steps' events
    against a sandbox copy of the state and raise EventError naming the
    STEP and the EVENT that fails, before real state is touched."""
    if not any(s.get("events") for s in steps):
        return
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "state"
        shutil.copytree(store.state_dir, sandbox)
        eng = Engine(Store(tmp, state_dir=sandbox))
        for step in steps:
            for i, ev in enumerate(step.get("events", []), 1):
                try:
                    getattr(eng, ev["method"])(*ev.get("args", []),
                                               **ev.get("kwargs", {}))
                except EventError as e:
                    raise EventError(
                        f"Step {step['id']} NOT applied — event {i} of "
                        f"{len(step['events'])} "
                        f"({ev['method']}{tuple(ev.get('args', []))}) is "
                        f"illegal: {e}. Nothing was applied and the step "
                        "stays open — fix the state or patch the step "
                        "(planlib.py patch) and run done again")


# ── duplicate-effect guard ───────────────────────────────────
# `apply.py play` already applies a card's db.json behavior. A plan step
# that ALSO carries prod/res events for the same resource applies it
# twice — and the sandbox simulation cannot catch it, because double
# application is arithmetically legal (Cloud Seeding's MC and plant
# production landing twice is the canonical case). Bespoke effects the db
# does NOT encode (Nitrophilic Moss's "lose 2 plants", Cloud Seeding's
# hit on an OPPONENT's heat production) still need their own events, so
# this warns rather than refuses.

_DB_RES_KEY = {"megacredits": "mc", "mc": "mc", "steel": "steel",
               "titanium": "titanium", "plants": "plants",
               "energy": "energy", "heat": "heat"}

_CARD_DB = None


def _card(name: str) -> dict | None:
    """db.json lookup without needing an Engine instance. Fail-soft: an
    unreadable db means no warnings, never a broken set_plan."""
    global _CARD_DB
    import cards as _cards
    if _CARD_DB is None:
        try:
            _CARD_DB = _cards.load_db()
        except FileNotFoundError:
            _CARD_DB = {"cards": []}
    try:
        return _cards.find(name, _CARD_DB)
    except Exception:
        return None


def duplicate_effect_warnings(steps: list[dict]) -> list[str]:
    """One ⚠ line per plan step whose manual prod/res events repeat a
    resource the played card's db behavior already moves for that player."""
    out = []
    for st in steps:
        events = st.get("events") or []
        plays = [e for e in events if e.get("method") == "play"]
        if not plays:
            continue
        for play in plays:
            args = play.get("args") or []
            if len(args) < 2:
                continue
            player, card = str(args[0]), str(args[1])
            info = _card(card)
            beh = (info or {}).get("behavior") or {}
            covered = {"prod": set(), "res": set()}
            # _apply_behavior only AUTO-applies a plain-int production
            # delta (tmlib's `all(isinstance(v, int) ...)` gate) — a formula
            # value (e.g. Medical Lab's {"tag":"building","per":2}) falls
            # through to a manual "→ TABLE" step, so a plan step's own prod
            # event for that resource is correct, not a duplicate.
            for k, v in (beh.get("production") or {}).items():
                if k in _DB_RES_KEY and isinstance(v, int):
                    covered["prod"].add(_DB_RES_KEY[k])
            for k in (beh.get("stock") or {}):
                if k in _DB_RES_KEY:
                    covered["res"].add(_DB_RES_KEY[k])
            # A top-level `behavior["tr"]` plain int (e.g.
            # Nitrogen-Rich Asteroid) is ALSO auto-applied by
            # _apply_behavior — a manual `tr` event for the same player
            # duplicates it exactly like prod/res.
            tr_covered = isinstance(beh.get("tr"), int)
            for e in events:
                m = e.get("method")
                if m not in ("prod", "res", "tr"):
                    continue
                ea = e.get("args") or []
                if m == "tr":
                    if len(ea) < 1 or str(ea[0]).lower() != player.lower():
                        continue      # hitting an OPPONENT is bespoke
                    if tr_covered:
                        out.append(
                            f"⚠ step {st.get('id')}: {card} already moves "
                            f"TR via its card data — the extra tr event "
                            f"applies it TWICE. Drop it unless the card "
                            f"text has a second, bespoke TR change.")
                    continue
                if len(ea) < 2:
                    continue
                if str(ea[0]).lower() != player.lower():
                    continue          # hitting an OPPONENT is bespoke
                if str(ea[1]) in covered[m]:
                    out.append(
                        f"⚠ step {st.get('id')}: {card} already moves "
                        f"{ea[1]} via its card data — the extra "
                        f"{m} event applies it TWICE. Drop it unless the "
                        f"card text has a second, bespoke change.")
    return out


# ── cue gate ─────────────────────────────────────────────────
# Guard: a plan step marked done from a report about a DIFFERENT step
# (a milestone claim that never happened stays claimable on the screen
# for turns). Board-visible steps get their own confirmation cue.
CUE_GATED_METHODS = ("milestone", "award", "place")


def is_cue_gated(step: dict) -> bool:
    """True when the step's events include milestone/award/place, or the
    step carries `"cueGated": true` (any other board-visible action)."""
    if step.get("cueGated"):
        return True
    return any(ev.get("method") in CUE_GATED_METHODS
               for ev in step.get("events") or [])


def _cue_reason(step: dict) -> str:
    hits = sorted({ev.get("method") for ev in step.get("events") or []
                   if ev.get("method") in CUE_GATED_METHODS})
    return "/".join(hits) + " event" if hits else "cueGated: true"


def _autofill_cue(step: dict) -> str | None:
    """Mirror of the mapHighlight autofill for `place`: a milestone/award
    event yields "your marker on <Name>". `place` steps and bare
    cueGated steps get NO default — the advisor writes what the player should
    see on the board (grid ref + tile colour)."""
    for ev in step.get("events") or []:
        if ev.get("method") in ("milestone", "award") \
                and len(ev.get("args") or []) >= 2:
            return f"your marker on {ev['args'][1]}"
    return None


def _cue_refusal(step: dict) -> EventError:
    return EventError(
        f"Confirm the cue for {step['id']}: '{step.get('cue')}' → "
        f"done {step['id']} --confirm ok   (cue-gated step: the player must "
        f"SEE the result before it is marked done — never infer it from "
        f"a report about another step)")



THREATS_HINT = (
    'wrap the plan as {"threats": "<per-opponent threats — who is 1 step from '
    'which milestone, which award is contested, removal targets>", '
    '"steps": [...]} (threats may be a non-empty string or list)')

EXIT_HINT = (
    'add a top-level "exit": "<the VP exit this plan scores through AND its '
    'repeatable component>" (non-empty string) — the exit is re-stated every '
    'generation, exactly like the threats block')


def _exit_ok(exit_spec) -> bool:
    return isinstance(exit_spec, str) and bool(exit_spec.strip())


def _exit_gate(store: Store, exit_spec: str, exit_ack, generation) -> None:
    """W1-B item 2c: when shape.py reports ZERO repeatable VP/TR sources
    (the game5 failure: a tiles+milestones plan with no repeatable source
    after gen 3), a live plan whose exit string acknowledges no
    repeatable component is refused — unless the plan carries
    "exitAck": "<reason>", which is logged. Facts + evidence only; the
    gate never says what the exit should be. Fail-soft: if shape cannot
    compute (no log, no clock), the gate does not fire."""
    try:
        import shape
        flag = shape.compute(store)["flags"]["sources"]
    except Exception:
        return
    if not flag:
        return
    if "repeatable" in exit_spec.lower():
        return
    if isinstance(exit_ack, str) and exit_ack.strip():
        store.log(f"G{generation}",
                  f"Exit gate ACK ({flag}): {exit_ack.strip()}")
        return
    store.log(f"G{generation}", f"GATE exit REFUSED: {flag}; exit was "
                                f"{exit_spec!r}")
    raise EventError(
        f"PLAN REFUSED — shape.py: {flag}; the plan's \"exit\" "
        f"({exit_spec!r}) names no repeatable component (no \"repeatable\" "
        f"in it). Name the exit's repeatable component in \"exit\", or "
        f"acknowledge with \"exitAck\": \"<reason>\" (logged).")


# ── award-funding calibration guard (W1-B item 4, rewritten in B2) ───
# game5: the advisor restated menu.py's "not lockable" Landlord verdict
# as a lock. The first fix DEMANDED the verdict in the step summary
# ("lockable" in summary and "not lockable" not in summary) — and in the
# 2026-08-31 practice game that refused a CORRECT plan whose summary
# mentioned the OTHER awards as "not lockable". A crude gate teaches the
# operator to reflexively --force, which is how a gate becomes noise, and
# hand-copying a long verdict costs exactly the tokens terse mode saves.
#
# So the engine INJECTS the fact instead of demanding prose: `lockVerdict`
# is stored on the step here and rendered as its own line under it
# (render(), and therefore turn.py done). Machine-generated and verbatim
# is strictly stronger than asking the model to quote it — it cannot be
# paraphrased. The one refusal that remains is the contradiction check: a
# summary claiming "locked" against a "not lockable" verdict, SCOPED to
# the sentence naming this step's award so another award's status is safe
# to mention.

_LOCKED_CLAIM = re.compile(r"\block(?:ed|s)\b", re.IGNORECASE)
_LOCKED_EXCLUDE = re.compile(r"not\s+lockable|unlockable", re.IGNORECASE)
# sentence boundaries only — NOT the em-dash/comma clauses a trace uses
# ("fund Banker — not lockable, but effectively locked" is one claim).
_SENTENCE_SPLIT = re.compile(r"[.;!?\n]+")


def _claim_scope(summary: str, canon: str, awards) -> list[str]:
    """The sentences of `summary` that speak about THIS award: the ones
    naming it, or — when no sentence names any award at all — the whole
    summary (prose that names nothing is about the award being funded).
    Sentences that name only OTHER awards are somebody else's verdict."""
    sentences = [s for s in _SENTENCE_SPLIT.split(summary) if s.strip()]
    mine = [s for s in sentences if canon.lower() in s.lower()]
    if mine:
        return mine
    others = [s for s in sentences
              if any(a.lower() in s.lower() for a in awards
                     if a.lower() != canon.lower())]
    return [s for s in sentences if s not in others]


def _award_calibration(store: Store, steps: list[dict]) -> None:
    """Inject menu.py's lock verdict onto every step that funds one of MY
    awards; refuse only a summary that claims more than the verdict."""
    import menu
    import tmlib as _tmlib
    hits = [(st, ev) for st in steps if not st.get("done")
            for ev in st.get("events") or []
            if ev.get("method") == "award" and len(ev.get("args") or []) >= 2]
    for st in steps:                      # a step that no longer funds an
        if not st.get("done"):            # award must not keep a stale one
            st.pop("lockVerdict", None)
    if not hits:
        return
    game = store.load_game()
    try:
        setup = store.load_setup()
    except FileNotFoundError:
        setup = {}
    me = str(game["me"].get("name") or "").lower()
    for st, ev in hits:
        player, award = str(ev["args"][0]), str(ev["args"][1])
        if player.lower() not in (me, "me"):
            continue                       # an opponent's funding: not my claim
        canon = next((a for a in _tmlib.AWARDS
                      if a.lower() == award.lower()), None)
        if canon is None:
            continue                       # unknown award: simulate() refuses
        lock = menu.award_lock(game, canon, setup)
        summary = str(st.get("summary") or "")
        gen = game["generation"]
        line = f"{canon} — menu.py: {lock['why']}"
        st["lockVerdict"] = ("\n".join([*str(st.get("lockVerdict") or "")
                                        .splitlines(), line]).strip()
                             if st.get("lockVerdict") else line)
        # THE ASYMMETRY. Injecting the verdict was not enough: in a real
        # game it read "mine 7 vs Ben 6 reachable +3 = 9 - not lockable",
        # the award was funded anyway for 8 MC, the rival tied the metric
        # twice and took 1st place. Unfunded, an award scores NOBODY - the
        # counterfactual was 67-65 the funder's way instead of 70-69
        # against, the entire margin of the loss. The reasoning that lost
        # it ("second place still pays 2 VP") prices the wrong side: what
        # funding buys is a pot the RIVAL can win. So a not-lockable
        # funding now needs the sentence written down (the exitAck
        # precedent) - not a reflexive --force, an explicit field, logged
        # and audited in the postmortem like any override. A LOCKABLE
        # verdict stays frictionless: that half paid 5 VP in the same game.
        if not lock["lockable"]:
            ack = str(st.get("awardAck") or "").strip()
            if not ack:
                store.log(f"G{gen}", f"GATE award-ack REFUSED: step "
                                     f"{st.get('id')} funds {canon} against "
                                     f"verdict \"{lock['why']}\"")
                raise EventError(
                    f"Plan step {st.get('id')}: funding {canon} against "
                    f"\"{lock['why']}\". An unfunded award scores NOBODY, so "
                    f"the cost of funding is not your own second place - it "
                    f"is what the RIVAL collects from a pot you opened. Add "
                    f"\"awardAck\": \"<why funding still beats leaving it "
                    f"unfunded>\" to the step (logged, audited), or fund it "
                    f"once the verdict says LOCKABLE.")
            store.log(f"G{gen}", f"GATE award-ack OVERRIDE: step "
                                 f"{st.get('id')} funds {canon} against "
                                 f"\"{lock['why']}\" — {ack}")
        if not lock["lockable"] and any(
                _LOCKED_CLAIM.search(_LOCKED_EXCLUDE.sub(" ", s))
                for s in _claim_scope(summary, canon, _tmlib.AWARDS)):
            store.log(f"G{gen}", f"GATE award-calibration REFUSED: step "
                                 f"{st.get('id')} claims \"locked\" on "
                                 f"{canon} against verdict \"not lockable\"")
            raise EventError(
                f"Plan step {st.get('id')}: summary claims \"locked\" "
                f"({summary!r}) but the lock test says {lock['why']!r} — "
                f"the summary may not claim more than the verdict. (The "
                f"verdict itself is injected as the step's lockVerdict — "
                f"you never need to quote it.)")


# ── terse-mode summary budget ────────────────────────────────────────
# The advisor's own clock is generated tokens, and ~75% of a plan-step
# summary is KB citation, rejected alternatives and justification prose
# nobody reads. `judgment.py set verbosity terse|full` (terse = default)
# holds every OPEN step's summary to SUMMARY_BUDGET characters — a policy
# that is merely advisory erodes under time pressure, so it is a gate.
# Terse compresses PROSE ONLY: events, before→after numbers, the running
# balance, cues, threats and the exit field are untouched, and the strings
# other gates REQUIRE in the summary (the award lock verdict, the step's
# cue) are stripped before measuring so a machine-required quote can never
# push a step over. A step may opt out with "verbose": "<reason>" (logged).
SUMMARY_BUDGET = 200


def _verbosity(store: Store) -> str:
    try:
        import judgment
        return str(judgment.load(store).get("verbosity") or "terse")
    except (EventError, FileNotFoundError, ValueError, KeyError, ImportError):
        return "terse"


def _exempt_substrings(store: Store, step: dict) -> list[str]:
    """Strings a GATE requires inside this step's summary, which therefore
    never count against the budget: the step's cue, and menu.py's award
    lock verdict (the calibration guard refuses the step without it)."""
    out = [str(step.get("cue") or "")]
    awards = [ev for ev in step.get("events") or []
              if ev.get("method") == "award" and len(ev.get("args") or []) >= 2]
    if awards:
        try:
            import menu
            import tmlib as _tmlib
            game = store.load_game()
            try:
                setup = store.load_setup()
            except FileNotFoundError:
                setup = {}
            for ev in awards:
                canon = next((a for a in _tmlib.AWARDS
                              if a.lower() == str(ev["args"][1]).lower()), None)
                if canon:
                    out.append(menu.award_lock(game, canon, setup)["why"])
        except Exception:                       # never block a plan on this
            pass
    return [s for s in out if s.strip()]


def _budgeted_length(store: Store, step: dict) -> int:
    text = str(step.get("summary") or "")
    for sub in _exempt_substrings(store, step):
        text = re.sub(re.escape(sub), " ", text, flags=re.IGNORECASE)
    return len(" ".join(text.split()))


def _summary_budget(store: Store, steps: list[dict]) -> None:
    """Refuse an over-budget OPEN step while verbosity is terse."""
    if _verbosity(store) != "terse":
        return
    try:
        gen = store.load_game().get("generation")
    except (FileNotFoundError, ValueError):
        gen = "?"
    for st in steps:
        if st.get("done"):
            continue                    # written under an earlier dial
        n = _budgeted_length(store, st)
        if n <= SUMMARY_BUDGET:
            continue
        why = st.get("verbose")
        if isinstance(why, str) and why.strip():
            store.log(f"G{gen}", f"verbosity budget OVERRIDDEN: step "
                                 f"{st.get('id')} summary {n} chars > "
                                 f"{SUMMARY_BUDGET} — {why.strip()}")
            continue
        store.log(f"G{gen}", f"GATE verbosity REFUSED: step {st.get('id')} "
                             f"summary {n} chars > {SUMMARY_BUDGET}")
        raise EventError(
            f"PLAN REFUSED — step {st.get('id')} summary is {n} characters, "
            f"over the terse budget of {SUMMARY_BUDGET} (machine-required "
            f"text — the cue, the award lock verdict — is already excluded). "
            f"Cut the KB citation, the rejected alternatives and the "
            f"justification prose; keep the numbers. Opt this step out with "
            f"\"verbose\": \"<reason>\" (logged), or lift the budget for the "
            f"whole game with `judgment.py set verbosity full`.")


def _or_branch_titles(ev: dict) -> list[str]:
    """The branch titles the event's card offers, or [] when the event
    selects no branch. GENERIC: every string argument is looked up in the
    card db and the card's own or-behavior is read — no card is named
    here, and no per-card branch table exists anywhere (the fix this gate
    belongs to removed the second selector grammar rather than adding a
    lookup)."""
    import tmlib as _tmlib
    for arg in ev.get("args") or []:
        if not isinstance(arg, str):
            continue
        info = _card(arg)
        if not info:
            continue
        if ev.get("method") == "use_action":
            beh, text = info.get("actionBehavior"), info.get("action")
        else:
            beh, text = info.get("behavior"), info.get("effects")
        if not isinstance(beh, dict) or not isinstance(beh.get("or"), dict):
            continue
        branches = _tmlib.or_branches(info, behavior=beh, text=text)
        if len(branches) > 1:
            return [b["title"] for b in branches]
    return []


def _or_selector_gate(store: Store, steps: list[dict]) -> None:
    """A bare integer picking an or-branch is refused (fix plan item 2).

    An index is only meaningful in ONE ordering, and the app's live prompt
    is not that ordering — a plan that says `choice: 1` for "remove 3
    microbes" transmits "add 1 microbe" wherever the app hides or reorders
    a branch. A title substring means the same branch in both layers and
    is self-describing, so the safe form is also the shortest one: write
    `"choice": "<title substring>"`. An integer is still legal WITH a
    `choiceLabel`, which arms the executor's mismatch guard.

    The selector's two homes (the step's top level and the event's
    kwargs) are reconciled here as well — conflicting values are refused,
    and each half is then filed where it belongs: `choice` on the event
    (the engine's own argument, so the sandbox simulates the branch the
    app will execute) and `choiceLabel` on the step (it is a claim about
    the step, not an engine argument — passed as one it is a TypeError)."""
    game = store.load_game()
    for st in steps:
        if st.get("done"):
            continue
        for ev in st.get("events") or []:
            titles = _or_branch_titles(ev)
            if not titles:
                continue
            kw = ev.setdefault("kwargs", {})
            for key in ("choice", "choiceLabel"):
                top, inner = st.get(key), kw.get(key)
                if top is not None and inner is not None and top != inner:
                    store.log(f"G{game['generation']}",
                              f"GATE or-selector REFUSED: step {st.get('id')} "
                              f"has {key} {top!r} on the step and {inner!r} "
                              f"on the event")
                    raise EventError(
                        f"Plan step {st.get('id')}: {key} is {top!r} on the "
                        f"step but {inner!r} on the event — one selector, "
                        f"one value.")
                value = top if top is not None else inner
                if value is None:
                    continue
                if key == "choice":
                    kw["choice"] = value       # the engine's own argument
                    st.pop("choice", None)
                else:
                    st["choiceLabel"] = value  # a claim, not an argument
                    kw.pop("choiceLabel", None)
            choice, label = kw.get("choice"), st.get("choiceLabel")
            if isinstance(choice, bool) or not isinstance(choice, int):
                continue                      # a title, or no branch chosen
            if str(label or "").strip():
                continue                      # the guard is armed
            store.log(f"G{game['generation']}",
                      f"GATE or-selector REFUSED: step {st.get('id')} picks "
                      f"or-branch {choice} by bare index")
            listed = "; ".join(f"[{i}] {t}" for i, t in enumerate(titles))
            raise EventError(
                f"Plan step {st.get('id')}: \"choice\": {choice} is a bare "
                f"index into ONE ordering, and the app's live branch order "
                f"is not that ordering. Write the branch's title instead — "
                f'"choice": "<title substring>" — or keep the index and add '
                f'"choiceLabel": "<title substring>" so the executor can '
                f"refuse a mismatch before it transmits. Branches: {listed}")

def _threats_ok(threats) -> bool:
    if isinstance(threats, str):
        return bool(threats.strip())
    if isinstance(threats, list):
        return bool(threats) and all(
            (isinstance(t, str) and t.strip()) or isinstance(t, dict)
            for t in threats)
    return False


def _unpack_plan(plan_or_steps, draft: bool, threats, exit_spec=None,
                 exit_ack=None) -> tuple[list[dict], object, object, object]:
    """The plan JSON is either the legacy list of steps or an object
    {"threats": …, "exit": …, "steps": […]}. A NON-DRAFT plan without a
    threats block is refused — structurally, like the pass gate — because
    under tempo the threat analysis gets silently dropped otherwise. The
    same mechanics guard "exit" (W1-B 2c): a live plan must NAME its VP
    exit and the exit's repeatable component, every generation."""
    if isinstance(plan_or_steps, dict):
        steps = plan_or_steps.get("steps")
        if not isinstance(steps, list):
            raise EventError('plan object needs a "steps" list: '
                             '{"threats": …, "exit": …, "steps": […]}')
        if "threats" in plan_or_steps:
            threats = plan_or_steps["threats"]
        if "exit" in plan_or_steps:
            exit_spec = plan_or_steps["exit"]
        if "exitAck" in plan_or_steps:
            exit_ack = plan_or_steps["exitAck"]
    elif isinstance(plan_or_steps, list):
        steps = plan_or_steps
    else:
        raise EventError("plan must be a list of steps or an object "
                         '{"threats": …, "exit": …, "steps": […]}')
    if not draft and not _threats_ok(threats):
        shape = "legacy list" if isinstance(plan_or_steps, list) else "object"
        raise EventError(
            f"PLAN REFUSED — no threats block ({shape} without a non-empty "
            f"top-level \"threats\"): {THREATS_HINT}. Read the RACES block "
            "of the brief (advise.py) / scripts/races.py first.")
    if not draft and not _exit_ok(exit_spec):
        raise EventError(
            f"PLAN REFUSED — no exit field: {EXIT_HINT}. Mirror of the "
            "threats gate.")
    return steps, threats, exit_spec, exit_ack


def _prepare_steps(store: Store, steps: list[dict],
                   strict_labels: bool = True) -> list[str]:
    """The shared gate of set_plan and patch: volatility check, sandbox
    simulation of the OPEN steps, mapHighlight + cue autofill, cue gate,
    duplicate-effect warnings (returned). Mutates `steps` in place ONLY
    after the simulation passed. `strict_labels`: full 1a-1b-2a order for
    freshly composed plans; patches enforce grammar + turn grouping only
    (positional inserts stay legal)."""
    _validate_labels(steps, strict=strict_labels)
    for s in steps:
        if s.get("volatility") not in VOLATILITY:
            raise EventError(f"Step {s.get('id')}: volatility must be one of "
                             f"{list(VOLATILITY)}")
    # A standard project that ALWAYS places a tile needs its `place` event
    # in the same step. Without it the executor sends the project, then
    # meets an uncovered `space` follow-up with the input already
    # transmitted (P7 refusal #5, SP Aquifer) — knowable here, at plan time.
    for s in steps:
        if s.get("done"):
            continue
        evs = s.get("events") or []
        placed = {str((e.get("args") or [None, None])[1]).lower()
                  for e in evs if e.get("method") == "place"}
        for e in evs:
            if e.get("method") != "standard":
                continue
            project = str((e.get("args") or [None, ""])[1]).lower()
            tile = TILE_PROJECTS.get(project)
            if tile and tile not in placed:
                raise EventError(
                    f"Step {s.get('id')}: standard project {project!r} always "
                    f"places a {tile} tile, but the step has no matching "
                    f"`place` event. Add {{\"method\": \"place\", \"args\": "
                    f"[\"<player>\", \"{tile}\", \"<hex>\"]}} — otherwise the "
                    f"executor meets the space prompt with the project "
                    f"already sent.")
    # Award-funding calibration (W1-B item 4, rewritten in B2): inject
    # menu.py's lock verdict onto the step; refuse only a summary that
    # claims past it.
    _award_calibration(store, steps)
    # Or-branch selector: refuse a bare index, reconcile the selector's two
    # homes. It runs BEFORE the simulation on purpose — the sandbox must
    # see the same branch the app will.
    _or_selector_gate(store, steps)
    # Replans may carry already-executed steps as done:true — they are
    # stored done and EXCLUDED from simulation (their effects are already in
    # state; re-simulating them double-charges).
    simulate(store, [s for s in steps if not s.get("done")])
    for st in steps:
        if not st.get("mapHighlight"):
            for ev in st.get("events", []):
                if ev.get("method") == "place" and len(ev.get("args", [])) >= 3:
                    st["mapHighlight"] = str(ev["args"][2])
                    break
    # Cue gate: milestone/award/place (or cueGated:true) steps carry the
    # cue the player must SEE before `done` is legal. Executed steps in a
    # replan (done:true) are past the gate — not validated.
    for st in steps:
        if st.get("done") or not is_cue_gated(st):
            continue
        if not st.get("cue"):
            st["cue"] = _autofill_cue(st)          # milestone/award only
        if not str(st.get("cue") or "").strip():
            raise EventError(
                f"Plan step {st.get('id')} is cue-gated ({_cue_reason(st)}) "
                f"but has no \"cue\" — add cue: \"<what the player SEES when it "
                f"went right>\", e.g. \"your marker sits on Terraformer\", "
                f"\"green city on F2\"")
        st["cue"] = str(st["cue"]).strip()
    # Terse-mode prose budget, last: the cue is autofilled by now, so a
    # machine-required cue is exempt however it got there.
    _summary_budget(store, steps)
    return duplicate_effect_warnings([s for s in steps if not s.get("done")])


def set_plan(store: Store, steps, draft: bool = False,
             threats=None, exit_=None, exit_ack=None) -> dict:
    """`steps` is the legacy list of steps (then pass threats=…, exit_=…)
    or the object {"threats": …, "exit": …, "steps": […]}. Drafts may
    omit threats and exit; promote then requires them."""
    game = store.load_game()
    steps, threats, exit_spec, exit_ack = _unpack_plan(
        steps, draft, threats, exit_spec=exit_, exit_ack=exit_ack)
    if not draft:
        _exit_gate(store, exit_spec, exit_ack, game["generation"])
    warnings = _prepare_steps(store, steps)
    plan = {"generation": game["generation"], "draft": draft,
            "threats": threats, "exit": exit_spec,
            "feedCursor": feed_cursor(store),
            "steps": [{**s, "done": bool(s.get("done"))} for s in steps]}
    if isinstance(exit_ack, str) and exit_ack.strip():
        plan["exitAck"] = exit_ack.strip()
    if warnings:
        plan["warnings"] = warnings
    _write_plan(store, plan)
    kind = "Draft plan set (speculative — promote before executing)" \
        if draft else "Plan set"
    store.log(f"G{game['generation']}",
              f"{kind}: {', '.join(s['id'] for s in steps)}")
    return plan


def _step_id(step) -> str:
    sid = str((step or {}).get("id") or "").strip()
    if not sid:
        raise EventError("patch: every step needs an \"id\"")
    return sid


PATCH_USAGE = ('patch spec: {"replace": [step…] or {"<id>": step…}, '
               '"insert_after": {"<id>": [step…] or {"<id>": step…}}, '
               '"remove": ["<id>"…], "threats": "…", "exit": "…", '
               '"feed": [line…]}')
PATCH_FAILED = "patchFailed"


def _steps_arg(value, field: str) -> list[dict]:
    """A step collection in a patch spec: the LIST form, or a DICT keyed by
    step id (the key names the step and fills in a missing "id"). Both are
    natural to write, so both are accepted — the dict form used to raise a
    traceback and the chained executor then ran the UNPATCHED step (P8 #10).
    Any other shape is a one-line usage error."""
    if isinstance(value, dict):
        out = []
        for sid, st in value.items():
            if not isinstance(st, dict):
                raise EventError(f"patch: {field}[{sid!r}] must be a step "
                                 f"object, got {type(st).__name__} — "
                                 f"{PATCH_USAGE}")
            out.append({**st, "id": str(sid)})       # the key names the step
        return out
    if isinstance(value, list):
        for st in value:
            if not isinstance(st, dict):
                raise EventError(f"patch: {field} entries must be step objects, "
                                 f"got {type(st).__name__} — {PATCH_USAGE}")
        return [dict(s) for s in value]
    raise EventError(f"patch: {field} must be a list of steps or an object "
                     f"keyed by step id, got {type(value).__name__} — "
                     f"{PATCH_USAGE}")


def _ids_arg(value, field: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise EventError(f"patch: {field} must be a list of step ids — "
                         f"{PATCH_USAGE}")
    return value


def _draft_exists(store: Store) -> bool:
    """True when a DRAFT plan exists (plan.json marked draft, or a draft
    kept beside the live plan in the sidecar)."""
    try:
        if load_plan(store).get("draft"):
            return True
    except (EventError, ValueError):
        pass
    return (store.state_dir / DRAFT_SIDECAR).exists()


def _record_patch_failure(store: Store, message: str) -> None:
    """Stamp a failed patch into plan.json so the executor refuses to run
    the step the patch was meant to fix (execute.py reads `patchFailed`).
    Cleared by the next successful set / patch / promote."""
    try:
        plan = load_plan(store)
    except (EventError, ValueError, FileNotFoundError):
        return                                  # no plan: nothing to flag
    plan[PATCH_FAILED] = " ".join(str(message).split())
    try:
        _write_plan(store, plan)
    except OSError:
        pass


def _stale_sweep_guard(store: Store, stale_ok: str | None) -> None:
    """W2-C: a patch concluding an in-flight sweep must not land on a feed
    that moved past what the sweep read (state/sweep-inflight "cursor",
    stamped by advise.py --sweep). Refused as STALE — the standing plan is
    untouched and stays executable (no patchFailed stamp; the flag stays,
    so the retry is a RELAUNCHED sweep, not a blind re-run). Overridable
    with --stale-ok "<reason>", logged; a flag without a cursor stamp is
    left alone. Single-writer stays the main thread either way."""
    p = sweep_flag_path(store)
    if not p.exists():
        return
    try:
        info = json.loads(p.read_text())
    except ValueError:
        return
    stamp = (info or {}).get("cursor") if isinstance(info, dict) else None
    if not isinstance(stamp, int):
        return
    live_cursor = feed_cursor(store)
    if live_cursor <= stamp:
        return
    try:
        gen = store.load_game().get("generation")
    except (FileNotFoundError, ValueError):
        gen = "?"
    if isinstance(stale_ok, str) and stale_ok.strip():
        store.log(f"G{gen}",
                  f"STALE sweep patch OVERRIDDEN (sweep read to #{stamp}, "
                  f"feed now at #{live_cursor}): {stale_ok.strip()}")
        return
    store.log(f"G{gen}", f"Patch refused STALE (sweep read to #{stamp}, "
                         f"feed now at #{live_cursor})")
    raise EventError(
        f"PATCH REFUSED — STALE sweep: the feed is at #{live_cursor}, past "
        f"the in-flight sweep's stamp #{stamp}; events the sweep never saw "
        f"have landed. The standing plan is untouched and still executable — "
        f"discard this verdict and relaunch the sweep (advise.py --sweep), "
        f"or override with --stale-ok \"<reason>\" (logged).")


def patch(store: Store, spec: dict, live: bool = False,
          stale_ok: str | None = None) -> dict:
    """Edit the current DRAFT (or the live plan when `live`) by replacing /
    inserting / removing named steps — see the module docstring for the
    spec. Done steps are untouchable; the result is re-simulated like
    set_plan; nothing is written unless it passes. Returns the plan.

    A patch overtaken by the feed (stale sweep) is refused BEFORE anything
    else — that refusal never marks the plan failed. Any other failure is
    recorded as `patchFailed` in plan.json before it is raised, so a
    chained `turn.py go && execute.py` cannot run past it."""
    _stale_sweep_guard(store, stale_ok)
    try:
        return _patch(store, spec, live=live)
    except EventError as e:
        _record_patch_failure(store, str(e))
        raise


def _patch(store: Store, spec: dict, live: bool = False) -> dict:
    if not isinstance(spec, dict):
        raise EventError(f"patch needs a JSON object — {PATCH_USAGE}")
    plan = load_plan(store)
    if not plan.get("draft") and not live:
        # No draft anywhere: the live plan is the ONLY plan, and the sweep's
        # CONCLUDE runs patch on the player's own turn. Refusing there was a
        # dead end that silently dropped the patch (P8 #9).
        if _draft_exists(store):
            raise EventError("Plan is LIVE and a draft exists — patch edits "
                             "the draft; pass --live to modify the live plan "
                             "(done steps stay untouchable)")
        live = True
        print("ℹ no draft — patching the LIVE plan (done steps untouchable)")
    steps = [dict(s) for s in plan["steps"]]
    index = {s["id"].lower(): s for s in steps}

    def existing(sid: str, verb: str) -> dict:
        hit = index.get(sid.lower())
        if hit is None:
            raise EventError(f"patch: cannot {verb} {sid!r} — no such step; "
                             f"steps: {[s['id'] for s in steps]}")
        if hit.get("done"):
            raise EventError(f"patch: cannot {verb} {sid!r} — it is already "
                             f"executed (done); reopen it first if it was a "
                             f"phantom")
        return hit

    def fresh(st: dict) -> dict:
        if st.get("done"):
            raise EventError(f"patch: step {_step_id(st)!r} cannot be inserted "
                             f"as done:true — only execution marks steps done")
        return {**st, "done": False}

    removed = [_step_id({"id": r})
               for r in _ids_arg(spec.get("remove") or [], "remove")]
    for sid in removed:
        existing(sid, "remove")
    replaced: dict[str, dict] = {}
    for st in _steps_arg(spec.get("replace") or [], "replace"):
        sid = _step_id(st)
        existing(sid, "replace")
        replaced[sid.lower()] = fresh(st)
    inserts: dict[str, list[dict]] = {}
    # ids this patch frees are available again: replacing a step with a
    # differently-shaped one at the SAME label is the natural mid-generation
    # edit, and seeding `seen` with them made it a two-call dance (P7 E3)
    seen = set(index) - {r.lower() for r in removed}
    after = spec.get("insert_after") or {}
    if not isinstance(after, dict):
        raise EventError(f"patch: insert_after must be an object keyed by the "
                         f"anchor step id, got {type(after).__name__} — "
                         f"{PATCH_USAGE}")
    for anchor, new_steps in after.items():
        if str(anchor).lower() not in index:
            raise EventError(f"patch: insert_after {anchor!r} — no such step; "
                             f"steps: {[s['id'] for s in steps]}")
        for st in _steps_arg(new_steps, f"insert_after[{anchor!r}]"):
            sid = _step_id(st)
            if sid.lower() in seen:
                raise EventError(f"patch: inserted step id {sid!r} already exists")
            seen.add(sid.lower())
            inserts.setdefault(anchor.lower(), []).append(fresh(st))

    gone = {r.lower() for r in removed}
    merged: list[dict] = []
    for s in steps:
        key = s["id"].lower()
        if key not in gone:
            merged.append(replaced.get(key, s))
        merged.extend(inserts.get(key, []))

    threats = plan.get("threats")
    if "threats" in spec:
        threats = spec["threats"]
        if not plan.get("draft") and not _threats_ok(threats):
            raise EventError(f"patch: a live plan needs a non-empty threats "
                             f"block ({THREATS_HINT})")
    exit_spec = plan.get("exit")
    if "exit" in spec:
        exit_spec = spec["exit"]
        if not plan.get("draft") and not _exit_ok(exit_spec):
            raise EventError(f"patch: a live plan needs a non-empty exit "
                             f"field ({EXIT_HINT})")
    warnings = _prepare_steps(store, merged,          # raises → nothing written
                              strict_labels=False)

    plan["steps"] = [{**s, "done": bool(s.get("done"))} for s in merged]
    plan["threats"] = threats
    plan["exit"] = exit_spec
    if "exitAck" in spec:
        plan["exitAck"] = spec["exitAck"]
    plan.pop(PATCH_FAILED, None)                  # this patch succeeded
    if warnings:
        plan["warnings"] = warnings
    else:
        plan.pop("warnings", None)
    _write_plan(store, plan)

    changed = ([f"replaced {s['id']}" for s in replaced.values()]
               + [f"inserted {', '.join(x['id'] for x in v)} after {k}"
                  for k, v in inserts.items()]
               + ([f"removed {', '.join(removed)}"] if removed else [])
               + (["threats updated"] if "threats" in spec else [])
               + (["exit updated"] if "exit" in spec else []))
    touched_ids = ([s["id"] for s in replaced.values()]
                   + [x["id"] for v in inserts.values() for x in v] + removed)
    feed_lines = [int(x) for x in (spec.get("feed") or [])]
    game = store.load_game()
    kind = "draft" if plan.get("draft") else "live"
    what = "; ".join(changed) if changed else "no step changes (plan stands)"
    trig = (" — triggered by feed " + ", ".join(f"#{x}" for x in feed_lines)
            if feed_lines else "")
    store.log(f"G{game['generation']}", f"Plan patched ({kind}): {what}{trig}")
    if feed_lines:
        import triage
        note = (f"patched {', '.join(touched_ids)}" if touched_ids
                else "patched nothing — plan stands")
        triage.handle(triage.feed_path(store), feed_lines, note)
    clear_sweep_inflight(store)
    return plan


def load_plan(store: Store) -> dict:
    p = _path(store)
    if not p.exists():
        raise EventError("No plan stored — advisor sets one at generation start")
    return json.loads(p.read_text())


def _fetch_live_mat(store: Store) -> dict | None:
    """App modes: fetch the seat's live resources (a pass gate that
    only sees plan-time MC misses mid-generation rebates). Fail-soft."""
    try:
        setup = store.load_setup()
        if setup.get("gameMode", "physical") == "physical":
            return None
        pid = next((pl.get("playerId") for pl in setup.get("players", [])
                    if pl.get("isMe")), None)
        url = setup.get("appUrl")
        if not pid or not url:
            return None
        tp = (appapi.AppClient(url, timeout=4, retries=1).player(pid)
              .get("thisPlayer") or {})
        return {"mc": tp.get("megacredits"), "steel": tp.get("steel"),
                "titanium": tp.get("titanium"), "plants": tp.get("plants"),
                "heat": tp.get("heat")}
    except Exception:
        return None


# Pass gate: only FREE or always-positive items
# block a pass — 8-heat/8-plant conversions, unused free blue actions,
# claimable milestones (8 MC → 5 VP). Playable cards, standard projects
# and award funding are ADVISORY: the advisor prices them in the plan; a
# pass with money in hand is normal (saving for next generation).
GATE_KINDS = {"convert", "action", "milestone"}


def gate_line(item: dict) -> str:
    """One menu item as the gate prints it."""
    return f"{item['label']} — {item['detail']}"


def gate_items(store: Store) -> tuple[list[dict], list[dict]]:
    """(blocking items, advisory items) as menu.available_actions dicts,
    against the live mat when the app is reachable."""
    import menu
    game = store.load_game()
    live = _fetch_live_mat(store)
    if live:
        res = game["me"]["resources"]
        for k, v in live.items():
            if isinstance(v, int):
                res[k] = v
    gate, advisory = [], []
    for i in menu.available_actions(game, store.load_setup()):
        if i["name"] == "sell_patents":
            continue
        if i["kind"] in ("convert", "milestone"):
            gate.append(i)                     # free / always +5 VP
        elif i["kind"] == "action" and not i.get("cost"):
            gate.append(i)                     # free blue action (NRB, BN…)
        else:
            advisory.append(i)                 # costs MC: advisor's call
    return gate, advisory


def gate_split(store: Store) -> tuple[list[str], list[str]]:
    """(blocking items, advisory items) as printable lines."""
    gate, advisory = gate_items(store)
    return [gate_line(i) for i in gate], [gate_line(i) for i in advisory]


def uncovered_items(reason: str, items: list[dict]) -> list[str]:
    """The blocking items `reason` does not MENTION — by menu name
    ("Terraformer", "heat") or label ("claim Terraformer", "8 heat →
    temperature"), case-insensitive — as gate lines. A pre-declared reason
    (S4) has to name every item the LIVE list holds; anything else is
    refused exactly as a missing --force would be."""
    text = (reason or "").lower()
    out = []
    for i in items:
        names = [str(i.get("name") or ""), str(i.get("label") or "")]
        if not any(n and n.lower() in text for n in names):
            out.append(gate_line(i))
    return out


def gate_reason(step: dict | None, force: str | None) -> tuple[str | None, str]:
    """(override reason, source). The command-line --force wins ("cli");
    otherwise the step's own pre-declared "force" field ("step"); else
    (None, "")."""
    if force is not None:
        return force, "cli"
    field = (step or {}).get("force")
    if isinstance(field, str) and field.strip():
        return field.strip(), "step"
    return None, ""


def _apply_default(store: Store, apply_events: bool | None) -> bool:
    """None → physical: apply; app modes: don't — the
    advisor executed in the app first and logged as it went."""
    if apply_events is None:
        return game_mode(store) not in APP_MODES
    return apply_events


def mark_done(store: Store, label: str, apply_events: bool | None = None,
              force: str | None = None, verify: bool = True,
              confirm: str | None = None, step_force: bool = True) -> list[str]:
    """Mark step(s) executed. In physical mode ALSO applies each step's
    attached events to real state (they were sandbox-validated at plan
    time) — ticking the box without applying events silently desyncs
    state. App modes default to apply_events=False;
    pass True/False to override either way.

    Cue-gated steps (milestone/award/place, cueGated:true) refuse
    unless `confirm` is non-empty text — the player confirmed the step's cue.
    The refusal is raised BEFORE anything is applied or ticked.

    Pass gate (passGate:true steps): the override reason is `force`, else
    the step's own pre-declared "force" field (S4) — which must mention
    every item the live list holds, or the pass is refused naming the rest.
    `step_force=False` = do not read the field: execute.py's pre-send gate
    already consumed it and logged the override (its post-send call here
    keeps today's report, never a second OVERRIDDEN line)."""
    apply_events = _apply_default(store, apply_events)
    plan = load_plan(store)
    if plan.get("draft"):
        raise EventError(
            "Plan is a DRAFT (speculative, composed during the opponents' "
            "round) — run planlib.py promote first: it re-simulates against "
            "the CURRENT state and only then unlocks execution")
    label = label.strip().lower()
    hits = [s for s in plan["steps"]
            if s["id"].lower() == label
            or (label.isdigit()
                and s["id"].lower().rstrip("abcdefghijklmnopqrstuvwxyz") == label)]
    if not hits:
        raise EventError(
            f"No plan step {label!r}; steps: {[s['id'] for s in plan['steps']]}")
    already = [s["id"] for s in hits if s["done"]]
    if already:
        raise EventError(f"Already marked done: {already}")
    cue_steps = [s for s in hits if is_cue_gated(s)]
    confirmed = (confirm or "").strip()
    if cue_steps and not confirmed:
        raise _cue_refusal(cue_steps[0])
    gated = [s for s in hits if s.get("passGate")]
    if gated:
        blocking, advisory_items = gate_items(store)
        avail = [gate_line(i) for i in blocking]
        if advisory_items:
            print("ℹ also available (advisory, not blocking): "
                  + "; ".join(i["label"] for i in advisory_items))
        declared = (next((s for s in gated if s.get("force")), None)
                    if step_force else None)
        reason, source = gate_reason(declared, force)
        missing = uncovered_items(reason, blocking) if source == "step" else []
        if avail and (reason is None or missing):
            listed = "\n  ".join(missing or avail)
            if game_mode(store) not in APP_MODES:
                if missing:
                    raise EventError(
                        f"PASS REFUSED — the step's pre-declared reason "
                        f"({reason!r}) does not cover:\n  {listed}\nDo them, "
                        "extend the step's \"force\" field, or override with "
                        "an explicit per-item reason (done <id> --force "
                        "'<why each is bad>')")
                raise EventError(
                    f"PASS REFUSED — free/positive actions still available:"
                    f"\n  {listed}\nDo them, or override with an explicit "
                    "per-item reason (done <id> --force '<why each is bad>')")
            print(f"⚠ pass with available actions (app mode: reported, not "
                  f"refused — the app already took the pass):\n  {listed}")
        elif avail and reason:
            game = store.load_game()
            store.log(f"G{game['generation']}",
                      f"Pass with available actions OVERRIDDEN: {reason} "
                      f"({len(avail)} items)")
    if apply_events:
        # TRANSACTIONAL: every event of every hit step is run against a
        # SANDBOX copy first. Applying them one at a time committed each in
        # turn, so a step whose 3rd event was illegal left the first two
        # applied and the step NOT done — the worst state to recover from
        # at a table. Now the refusal names the step and the event, and
        # real state is untouched.
        _simulate_events(store, hits)
        eng = Engine(store)
        for s in hits:
            for ev in s.get("events", []):
                getattr(eng, ev["method"])(*ev.get("args", []),
                                           **ev.get("kwargs", {}))
    for s in hits:
        s["done"] = True
    _write_plan(store, plan)
    game = store.load_game()
    ids = [s["id"] for s in hits]
    entry = f"Executed plan step(s): {', '.join(ids)}"
    if cue_steps:
        cues = "; ".join(f"{s['id']} '{s.get('cue')}'" for s in cue_steps)
        entry += f" (cue confirmed by the player — {confirmed!r}: {cues})"
    store.log(f"G{game['generation']}", entry)
    if apply_events and verify:
        _print_verify(store)              # app modes only, advisory
    return ids


def mark_skipped(store: Store, label: str, reason: str) -> str:
    """Close a step that was NEVER executed (a force-done would otherwise apply a
    phantom tile). Marks done+skipped, applies NOTHING, logs the reason.
    """
    if not (reason or "").strip():
        raise EventError("skip needs --reason: why was this step not executed?")
    plan = load_plan(store)
    hits = [s for s in plan["steps"] if s["id"].lower() == label.strip().lower()]
    if not hits:
        raise EventError(
            f"No plan step {label!r}; steps: {[s['id'] for s in plan['steps']]}")
    if hits[0]["done"]:
        raise EventError(f"{label} already done")
    hits[0]["done"] = True
    hits[0]["skipped"] = True
    _write_plan(store, plan)
    game = store.load_game()
    store.log(f"G{game['generation']}",
              f"Plan step {hits[0]['id']} SKIPPED (events not applied): {reason}")
    return hits[0]["id"]


def mark_done_many(store: Store, labels: list[str],
                   apply_events: bool | None = None,
                   force: str | None = None,
                   confirm: str | None = None) -> list[str]:
    """Mark several labels in ONE invocation (kills round trips).

    Labels are processed in the given order, each committed exactly like a
    single `done` (events applied, plan written, log entry) before the next
    starts. On failure the run STOPS with an error naming the label that
    failed; labels already processed stay done — their state is committed.
    One `confirm` text covers every cue-gated label in the batch.
    """
    apply_events = _apply_default(store, apply_events)
    done: list[str] = []
    try:
        for label in labels:
            try:
                done.extend(mark_done(store, label, apply_events=apply_events,
                                      force=force, verify=False,
                                      confirm=confirm))
            except EventError as e:
                committed = ", ".join(done) if done else "none"
                raise EventError(
                    f"done stopped at {label!r} (committed before stop: "
                    f"{committed}): {e}")
    finally:
        if done and apply_events:
            _print_verify(store)          # one check for the whole batch
    return done


def next_step(store: Store) -> dict | None:
    plan = load_plan(store)
    return next((s for s in plan["steps"] if not s["done"]), None)


def promote(store: Store, threats=None, exit_=None, exit_ack=None) -> str:
    """Flip a DRAFT plan live. Re-runs the sandbox simulation
    against the CURRENT state — opponent actions since drafting (taken
    hexes, changed globals) surface here as a named failing step instead
    of at the table. On failure the plan STAYS draft; patch the named
    step(s) and set a fresh draft or plan. A live plan needs its
    threats block and its exit field — pass threats=… / exit_=… if the
    draft had none."""
    plan = load_plan(store)
    if not plan.get("draft"):
        raise EventError("Plan is already live — promote is for drafts")
    plan.pop(PATCH_FAILED, None)          # a fresh promotion clears the flag
    abandoned = abandon_sweep(store)      # the player's turn outranks a sweep
    if threats is not None:
        plan["threats"] = threats
    if not _threats_ok(plan.get("threats")):
        raise EventError("PROMOTE REFUSED — the draft has no threats block; "
                         "promote --threats '<per-opponent threats>' "
                         f"({THREATS_HINT})")
    if exit_ is not None:
        plan["exit"] = exit_
    if isinstance(exit_ack, str) and exit_ack.strip():
        plan["exitAck"] = exit_ack.strip()
    if not _exit_ok(plan.get("exit")):
        raise EventError("PROMOTE REFUSED — the draft has no exit field; "
                         "promote --exit '<VP exit + repeatable component>' "
                         f"({EXIT_HINT})")
    game = store.load_game()
    _exit_gate(store, plan["exit"], plan.get("exitAck"), game["generation"])
    simulate(store, [s for s in plan["steps"] if not s["done"]])
    plan["draft"] = False
    _write_plan(store, plan)
    game = store.load_game()
    store.log(f"G{game['generation']}",
              "Draft plan PROMOTED (re-simulated clean against current state)")
    if abandoned:
        return (f"promoted (in-flight sweep abandoned — streak "
                f"{abandoned.get('streak')}"
                + (f", judgment level degraded to {abandoned['degraded']}"
                   if abandoned.get("degraded") else "") + ")")
    return "promoted"


def reopen(store: Store, label: str) -> str:
    """Un-mark a step (recorded too eagerly / table diverged)."""
    plan = load_plan(store)
    label = label.strip().lower()
    hit = next((s for s in plan["steps"] if s["id"].lower() == label), None)
    if hit is None or not hit["done"]:
        raise EventError(f"Step {label!r} is not marked done")
    hit["done"] = False
    _write_plan(store, plan)
    game = store.load_game()
    store.log(f"G{game['generation']}", f"Reopened plan step: {hit['id']}")
    return hit["id"]


def patch_failed_lines(plan: dict) -> list[str]:
    """The ⚠ banner for a plan carrying an unresolved patch failure — the
    stored steps are NOT what the advisor last decided, so the executor
    refuses to run and `show` / `turn.py go` must say so (P8 #10)."""
    msg = (plan or {}).get(PATCH_FAILED)
    if not msg:
        return []
    return [f"⚠ PATCH FAILED — the last patch did NOT land: {msg}",
            "   The steps below are the UNPATCHED plan; execution is refused. "
            "Re-run planlib.py patch (fix the spec) or set a fresh plan."]


def render(store: Store) -> str:
    plan = load_plan(store)
    nxt = next((s["id"] for s in plan["steps"] if not s["done"]), None)
    header = f"Plan — generation {plan['generation']}"
    if plan.get("draft"):
        header += ("  [DRAFT — speculative, composed during opponents' "
                   "round; promote before executing]")
    lines = [header]
    lines.extend(patch_failed_lines(plan))
    threats = plan.get("threats")
    if _threats_ok(threats):
        lines.append("⚠ THREATS")
        for t in ([threats] if isinstance(threats, str) else threats):
            lines.append(f"  - {t if isinstance(t, str) else json.dumps(t, ensure_ascii=False)}")
    elif not plan.get("draft"):
        lines.append("⚠ no threats block — a live plan cannot be set without "
                     "one (planlib refuses); this plan predates the rule")
    if _exit_ok(plan.get("exit")):
        lines.append(f"🎯 EXIT: {plan['exit']}")
        if plan.get("exitAck"):
            lines.append(f"   exitAck: {plan['exitAck']}")
    elif not plan.get("draft"):
        lines.append("⚠ no exit field — a live plan cannot be set without "
                     "one (planlib refuses); this plan predates the rule")
    # The house-style glyphs (AGENTS.md output contract): this render IS
    # the plan block the player sees — pasted verbatim, never retyped.
    for s in plan["steps"]:
        if s["done"]:
            lines.append(f"✅ {s['id']}  {VOLATILITY[s['volatility']]} {s['summary']}")
        elif s["id"] == nxt:
            lines.append(f"▶️ NEXT {s['id']}  {VOLATILITY[s['volatility']]} {s['summary']}")
        else:
            lines.append(f"⬜ {s['id']}  {VOLATILITY[s['volatility']]} {s['summary']}")
        # The award lock verdict, verbatim from menu.py and injected at
        # set/patch time (B2 item 3): its own line, rendered done or not —
        # `turn.py done` marks the step and THEN renders, and the moment
        # the award is funded is exactly when the verdict must be visible.
        for verdict in str(s.get("lockVerdict") or "").splitlines():
            if verdict.strip():
                lines.append(f"   ⚖ lock test: {verdict.strip()}")
        if not s["done"] and is_cue_gated(s):
            lines.append(f"   👁 cue: {s.get('cue')}  — done {s['id']} only "
                         f"after the player confirms this (--confirm)")
        if not s["done"] and s.get("mapHighlight"):
            lines.append(f"   📍 ATTACH MAP IN THIS MESSAGE: run scripts/"
                         f"render_board.py --highlight {s['mapHighlight']} "
                         f"and SendUserFile it at step {s['id']} — a plan "
                         "message with this marker unsatisfied is INVALID; "
                         "never reference an earlier map")
    if nxt is None:
        lines.append("All steps complete — generation plan finished "
                     "(saturation check before passing).")
    if not any(s.get("passGate") for s in plan["steps"]):
        lines.append("⚠ no pass-gate step in this plan — end every "
                     "generation plan with a passGate:true step so the "
                     "engine can refuse an early pass")
    lines.extend(plan.get("warnings") or [])      # duplicate effects
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".", help="repo root (state/ = active game)")
    p.add_argument("--state", default=None,
                   help="a state folder instead of state/ (a seat's own — "
                        "session.py seat-init)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set", help='read plan JSON on stdin: {"threats": '
                       '"<per-opponent threats>", "exit": "<VP exit + its '
                       'repeatable component>", "steps": [{id, summary, '
                       "volatility, events…}]} — a live plan without a "
                       "non-empty threats block OR exit field is REFUSED "
                       "(a bare list of steps is only accepted with --draft); "
                       'when shape.py flags zero repeatable sources, an exit '
                       'naming none needs "exitAck": "<reason>" (logged)')
    s.add_argument("--draft", action="store_true",
                   help="speculative plan (opponents still acting); "
                        "requires promote before done; may omit threats/exit")
    pr = sub.add_parser("promote", help="re-simulate a draft against current "
                                        "state and unlock execution (needs "
                                        "a threats block and an exit field: "
                                        "--threats / --exit)")
    pr.add_argument("--threats", default=None,
                    help="threats block for a draft that had none")
    pr.add_argument("--exit", default=None, dest="exit_spec",
                    help="exit field (VP exit + repeatable component) for a "
                         "draft that had none")
    pr.add_argument("--exit-ack", default=None, dest="exit_ack",
                    help="acknowledge a zero-repeatable-sources flag when the "
                         "exit names no repeatable component (reason logged)")
    pa = sub.add_parser("patch", help='edit the plan from JSON on stdin: '
                        '{"replace": [step…] or {"<id>": step…}, '
                        '"insert_after": {"<id>": [step…]}, "remove": '
                        '["<id>"…], "threats": "…", "exit": "…", '
                        '"feed": [line…]} — done '
                        'steps untouchable, the rest re-simulated; feed lines '
                        'get marked handled')
    pa.add_argument("--live", action="store_true",
                    help="patch the LIVE plan (implied when no draft exists)")
    pa.add_argument("--stale-ok", default=None, dest="stale_ok",
                    metavar="REASON",
                    help="override a STALE-sweep refusal (the feed advanced "
                         "past the in-flight sweep's cursor stamp) with a "
                         "written reason; logged")
    sub.add_parser("show")
    d = sub.add_parser("done"); d.add_argument("labels", nargs="+",
        help="one or more step labels (1a 1b 2a…) or whole turn numbers, "
             "marked in order; on failure earlier labels stay committed")
    d.add_argument("--no-apply", action="store_true",
                   help="only tick the box, events already logged (the "
                        "default in app modes)")
    d.add_argument("--apply", action="store_true",
                   help="apply attached events (the default in physical mode)")
    d.add_argument("--force", default=None,
                   help="pass-gate override: reason each remaining item is bad "
                        "(physical mode only — app modes report, never refuse); "
                        "wins over the step's own \"force\" field")
    d.add_argument("--confirm", default=None, metavar="TEXT",
                   help="cue gate: the player confirmed the step's cue (what they "
                        "SEE — marker on the milestone/award, tile on the "
                        "hex). Required for milestone/award/place or "
                        "cueGated:true steps; one --confirm covers every "
                        "such label in this call")
    sk = sub.add_parser("skip", help="close a step that was NEVER executed "
                        "— applies nothing")
    sk.add_argument("label")
    sk.add_argument("--reason", required=True)
    r = sub.add_parser("reopen"); r.add_argument("label")
    a = p.parse_args(argv)
    store = Store(a.root, state_dir=a.state)

    def stdin_json():
        try:
            return json.load(sys.stdin)
        except ValueError as e:                   # never a traceback at the table
            hint = f" — {PATCH_USAGE}" if a.cmd == "patch" else ""
            raise EventError(f"{a.cmd}: stdin is not valid JSON ({e}){hint}")

    try:
        if a.cmd == "set":
            set_plan(store, stdin_json(), draft=a.draft)
            print(render(store))
        elif a.cmd == "promote":
            print(f"{promote(store, threats=a.threats, exit_=a.exit_spec, exit_ack=a.exit_ack)} — plan is live")
            print(render(store))
        elif a.cmd == "patch":
            patch(store, stdin_json(), live=a.live, stale_ok=a.stale_ok)
            print("patched — re-simulated clean")
            print(render(store))
        elif a.cmd == "show":
            print(render(store))
        elif a.cmd == "skip":
            sid = mark_skipped(store, a.label, a.reason)
            print(f"Skipped {sid} (no events applied)")
            print(render(store))
        elif a.cmd == "reopen":
            print(f"Reopened: {reopen(store, a.label)}")
            print(render(store))
        else:
            apply = True if a.apply else (False if a.no_apply else None)
            ids = mark_done_many(store, a.labels, apply_events=apply,
                                 force=a.force, confirm=a.confirm)
            print(f"Marked done: {', '.join(ids)}")
            print(render(store))
        return 0
    except (EventError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
