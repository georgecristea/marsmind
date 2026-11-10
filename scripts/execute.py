#!/usr/bin/env python3
"""The one-call executor: a plan step → app inputs, sent and verified.

    execute.py step <label> [--dry-run] [--no-done] [--pid P] [--url U]
    execute.py turn <label> [<label> …] [--dry-run] [--no-done] [--pid P]
    execute.py pick ["<Card>" …]      # the current `card` prompt (buy/draft);
                                      # a payment follow-up is paid MC first,
                                      # then heat (Helion); the tracker hand
                                      # is charged 3 MC per bought card
    execute.py corp "<Corp>" ["<Card>" …]   # the initial corp + cards prompt
    execute.py sell "<Card>" ["<Card>" …]   # SELL PATENTS: discard cards from
                                      # hand for 1 MC each, charged to the
                                      # tracker (a plan step says it as
                                      # standard <me> sell_patents --cards …)
    execute.py pass                   # "Pass for this generation"
    --state <dir>  a seat's own state folder (session.py seat-init) instead
                   of state/ — seats never touch the advisor's tracker
    --force REASON one string, three overrides, each logged: a plan whose
                   last patch failed; the pass gate (S4: a passGate step
                   may pre-declare it as "force": "<per-item reason>" —
                   read like --force, still refused when the live list has
                   an item it does not mention; --force wins); and the S5
                   trigger guard below

TRIGGER SURFACE (S5). Before `step`/`turn`/`pass` transmit anything they
call the listener's pending list (turn._pending → triage.pending, the
same list `turn.py go` reads) and print `go`'s JUDGMENT banner while it
is non-empty. It WARNS, it does not refuse — `turn.py go`'s contract
("warns, not refuses, so the loop cannot deadlock"): turnover triggers
arrive every generation, so a hard block deadlocks every boundary.
`--force '<why>'` suppresses the banner and logs the reason. A dry run
says nothing. `turn.py go` stays for the draft-promote path; it is no
longer required between `listen.py wait` and execute.

LATENCY (S6). Every invocation is ONE latency.timed("execute") block whose
end note is "<verb> <labels> rc=<n>" — per-decision timing without a
hand-placed mark.

`step` reads the plan step (scripts/planlib.py), fetches the seat's
waitingFor tree (scripts/appapi.py), CHECKS the tree offers what the step
needs, builds the input with the scripts/sparring.py helpers, sends it,
answers the follow-ups the step covers (space from a `place` event,
`choice`/`target` kwargs, the MC-only payment prompt after a claim/fund)
and then reconciles with the app view.

IN APP MODES THE APP IS THE RULES ENGINE (P9). The step's events are
applied to the tracker (they carry the ledger and plan semantics), then
the app view is ADOPTED for my mat — resources, production, TR, hand,
tableau, card resources — plus the globals and the board
(verify.sync_table). The sandbox simulation of the step is still run, but
only to PRINT what it predicted: each difference is an `ℹ` line, never a
refusal. In the P8 game the old refusal fired six times on correct steps
whose card effects the engine does not model (blue-card actions, an
or-choice card, an ocean bonus), each costing a manual `planlib done
--apply` + `verify --sync` recovery. The step is marked done with
`confirm="app-adopted"`. In PHYSICAL mode there is no app to adopt, so
the simulation is the only check and a blocking mismatch still exits 41.

Exit codes
    0   sent, reconciled, marked done (or dry-run)
    40  ASK — unknown/mismatched prompt, an uncovered follow-up, the app
        rejected the input (HTTP 400), or the app accepted a step whose
        events the tracker then refused (the view is adopted first, so the
        numbers are right and only the plan box is left to tick): the tree
        is printed; when nothing was sent the plan is untouched
    41  VERIFY — physical mode ONLY: the sandbox expectation disagrees
        with the view; both are printed, the plan is NOT marked done
    1   any other error (no plan, no playerId, app unreachable …)

`turn` runs `step` per label in order and stops at the first non-zero
exit, honouring judgment.executor (scripts/judgment.py): manual → always
dry-run plus a reminder that the player clicks; assist → prints what it
will send, then sends; auto → sends. The trigger guard runs ONCE for the
whole turn.

Step events → app inputs (docs/actions.md is the audited action space):
    play            → "Play project card" (projectCard); payment from
                      the step's cost (else card_price) minus the steel/
                      titanium/heat split in kwargs; MC only otherwise
    standard        → "Standard projects" sub-card (Power Plant:SP …);
                      sell_patents → the "Sell patents" card prompt
    convert heat    → "Convert 8 heat into temperature"
    convert plants  → "Convert N plants into greenery" + the place hex
    use_action      → "Perform an action from a played card"
    milestone/award → "Claim a milestone" / "Fund an award" sub-option
    free_action_city→ "Take first action of <corp> corporation" (the gen-1
                      prompt of Tharsis Republic) + the place hex
    place           → the `space` follow-up of the preceding action
    passGate step   → "Pass for this generation"
    res/prod/tr/hand_*/note … → tracker-only, no app input
Prompts REFUSED (exit 40): anything not an action-phase `or` root for a
step; follow-ups of type card/amount/payment-with-alternatives/and/
productionToLose/party/delegate/colony; a research/draft `card` prompt
where a step is expected (use `pick`); `initialCards` (use `corp`).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appapi
from appapi import AppClient, AppError, AppUnavailable
from appapi import Ask, offered_names as _offered_names, or_branch_response as _or_branch_response, player_color as _player_color  # D1: ONE composer (appapi), two callers
import judgment
import latency
import planlib
import sparring
import turn                       # S5: the ONE trigger guard (_pending, _judgment_warning)
import verify
from tmlib import (BUY0_REFUSED, buy0_override_tag, CARD_KEEP_COST, Engine,
                   EventError, PARAM_SCALE, Store, card_price, grid_to_space,
                   split_payment, standard_project_price,
                   STEEL_VALUE, TITANIUM_VALUE)
EXIT_ASK = 40
EXIT_VERIFY = 41

ACTIONABLE = ("play", "standard", "convert", "milestone", "award",
              "use_action", "free_action_city", "wgt", "pass")
# World Government Terraforming: the app's branch titles, by parameter.
# The skills/turn-advisor WGT step used to carry no events at all, so the
# executor refused it ("no app-executable event") and every WGT choice of
# a whole game went out by hand through sparring.send. WGT is the DEFAULT
# now, so the step is a real event and this is its selector.
WGT_BRANCH = {"temperature": "increase temperature",
              "oxygen": "increase oxygen",
              "oceans": "add an ocean"}
SP_CARD = {"power_plant": "Power Plant:SP", "asteroid": "Asteroid:SP",
           "aquifer": "Aquifer", "greenery": "Greenery", "city": "City"}
ROOT_MARKERS = ("pass for this generation", "standard projects")
BLOCKING_FIELDS = ("mc", "steel", "titanium", "plants", "energy", "heat",
                   "tr", "prod.mc", "prod.steel", "prod.titanium",
                   "prod.plants", "prod.energy", "prod.heat", "hand")


# A standard project whose ONLY effect is a global step buys NOTHING once
# that track is full. `SP_PARAM` is the parameter each project raises;
# `SP_PARAM_ONLY` is the ones with nothing left over when it cannot rise:
#   asteroid  — temperature step and nothing else
#   aquifer   — the app suppresses the tile as well when oceans are maxed
#               ("oceans maxed at 9/9 — the ocean is SUPPRESSED")
# SP greenery keeps its TILE (VP, adjacency, placement bonus) at 14 % O2,
# so it is NOT zero-effect; city and power plant raise no parameter.
SP_PARAM = {"asteroid": "temperature", "aquifer": "oceans",
            "greenery": "oxygen"}
SP_PARAM_ONLY = ("asteroid", "aquifer")


class VerifyMismatch(Exception):
    """Exit 41."""


# ── step → actions (pure) ────────────────────────────────────

def is_action_menu(wf) -> bool:
    """The action-phase root `or` (Player.getActions): it always carries
    "Standard projects" and "Pass for this generation"."""
    if not isinstance(wf, dict) or wf.get("type") != "or":
        return False
    titles = [sparring._title(o).lower() for o in wf.get("options", [])]
    return any(m in t for m in ROOT_MARKERS for t in titles)


def _space_of(place_event: dict) -> str | None:
    args = place_event.get("args") or []
    if len(args) < 3:
        return None
    return grid_to_space(args[2])


def _selector(step: dict, kw: dict) -> tuple[object, object]:
    """THE one place the or-branch selector is read. `choice` and
    `choiceLabel` have two plausible homes — the STEP's top level and the
    EVENT's kwargs — and reading only one of them is how the mismatch
    guard came to be silently unarmed for a whole game (the step carried
    the label, execute read the kwargs, `expect` was None and the wrong
    branch went out). Both homes are read, the step level wins, and two
    DIFFERENT values are refused here, before anything is transmitted."""
    out = []
    for key in ("choice", "choiceLabel"):
        top, inner = step.get(key), kw.get(key)
        if top is not None and inner is not None and top != inner:
            raise Ask(f"step {step.get('id')}: {key} is {top!r} on the step "
                      f"but {inner!r} on the event — one selector, one "
                      f"value. Fix the plan step (planlib.py patch); "
                      f"nothing was sent.")
        out.append(top if top is not None else inner)
    return out[0], out[1]


def plan_actions(step: dict) -> list[dict]:
    """Group a step's events into app actions: each ACTIONABLE event plus
    the follow-up answers it covers — `space` from the `place` events that
    follow it, `or`/`player` from its choice/target kwargs, `card` from a
    sell_patents card list. Tracker-only events (res/prod/tr/hand_* …)
    produce nothing. A passGate step without an actionable event is the
    pass action."""
    actions: list[dict] = []
    for ev in step.get("events") or []:
        m = ev.get("method")
        if m in ACTIONABLE:
            kw = ev.get("kwargs") or {}
            or_choice, or_label = _selector(step, kw)
            follow = {"space": None, "spaceQueue": [],
                      "or": or_choice,
                      "orExpect": or_label,
                      "player": kw.get("target"), "card": None}
            if m == "standard" and (ev.get("args") or [None, None])[1] == "sell_patents":
                follow["card"] = list(kw.get("cards") or
                                      (ev.get("args")[2] if len(ev["args"]) > 2 else []))
            actions.append({"event": ev, "follow": follow})
        elif m == "place":
            sid = _space_of(ev)
            if actions and actions[-1]["follow"]["space"] is None:
                actions[-1]["follow"]["space"] = sid
            elif actions:
                # A SECOND tile from the same card (Ice Asteroid and Giant
                # Ice Asteroid each place two oceans). The app asks
                # "Select space for second ocean" as another follow-up of
                # the play that is already in flight, not as a new action —
                # both seats of one recorded game stalled here and needed a
                # manual `execute.py resolve <label> --space <hex>`.
                actions[-1]["follow"].setdefault("spaceQueue", []).append(sid)
            else:
                # a place-only step: answer a pending `space` prompt
                actions.append({"event": {"method": "place", "args": ev.get("args")},
                                "follow": {"space": sid, "spaceQueue": [],
                                           "or": None, "orExpect": None,
                                           "player": None, "card": None}})
    if not actions and step.get("passGate"):
        actions.append({"event": {"method": "pass", "args": []},
                        "follow": {"space": None, "spaceQueue": [],
                                   "or": None, "orExpect": None,
                                   "player": None, "card": None}})
    return actions


def _me(setup: dict) -> dict:
    return next(p for p in setup.get("players", []) if p.get("isMe"))


def _payment_split(game: dict, price: int) -> dict:
    """The app payload shape — {"mc": …, "heat": …} — of THE splitter
    (`tmlib.split_payment`: MC first, the rest from heat, heat only for a
    corporation whose rule spends it as money).

    P8 #16/#19: every builder sent megacredits=price, so as Helion with MC
    below the price the app answered HTTP 400 "You do not have that many
    resources" and left a dangling payment prompt (card buys G10, standard
    projects G13/G14). When even MC+heat cannot cover it the payload stays
    MC-only: the app's refusal (or the engine's EventError) is the right
    answer, not a half-payment. Steel/titanium stay explicit step kwargs.
    """
    price = max(0, int(price))
    me = game.get("me") or {}
    pay = split_payment(game, me.get("name") or "", price, pool=me)
    if pay["shortfall"]:
        return {"mc": price, "heat": 0}
    return {"mc": pay["mc"], "heat": pay["heat"]}


def zero_effect_standard(project: str, globals_: dict | None) -> str | None:
    """The reason a standard project would buy NOTHING right now, or None.

    Only projects in SP_PARAM_ONLY qualify: their whole effect is a step on
    a track that is already at its maximum. Every other project keeps a
    tile, a production step or a card, so a full track only degrades it.
    """
    if project not in SP_PARAM_ONLY or not globals_:
        return None
    param = SP_PARAM[project]
    scale = PARAM_SCALE[param]
    try:
        cur = int(globals_.get(param))
    except (TypeError, ValueError):
        return None
    if cur < scale["max"]:
        return None
    return (f"{param} is already at its maximum "
            f"({cur}{scale['unit']} of {scale['max']}{scale['unit']})")


def _live_globals(game: dict, view: dict | None) -> dict:
    """The most advanced reading of each track: the tracker's globals and
    the app's live view, whichever is further along. A track only ever
    goes up, so the higher number is the newer one — and the guard must
    fire on the value the APP will price the project at, even when the
    tracker has not drained the opponent's raise yet (that is exactly the
    gap that fired: the track filled between plan time and execution)."""
    out = dict((game or {}).get("globals") or {})
    g = (view or {}).get("game") or {}
    for param, key in (("temperature", "temperature"), ("oxygen", "oxygenLevel"),
                       ("oceans", "oceans")):
        v = g.get(key)
        if isinstance(v, int):
            out[param] = max(v, out.get(param, v))
    return out


def standard_zero_effect_gate(actions: list[dict], game: dict,
                              view: dict | None) -> tuple[str, str] | None:
    """(project, reason) for the first `standard` event in `actions` whose
    only effect cannot happen — the pre-send half of the menu's rule."""
    live = _live_globals(game, view)
    for action in actions:
        ev = action.get("event") or {}
        if ev.get("method") != "standard":
            continue
        args = ev.get("args") or []
        project = str(args[1]) if len(args) > 1 else ""
        why = zero_effect_standard(project, live)
        if why:
            return project, why
    return None


def _card_offered(option: dict, name: str) -> dict | None:
    for c in option.get("cards") or []:
        cname = c.get("name") if isinstance(c, dict) else c
        if str(cname).lower() == name.lower():
            return c if isinstance(c, dict) else {"name": c}
    return None


def build_primary(action: dict, wf, eng: Engine, game: dict) -> dict:
    """The input answering the CURRENT prompt for `action`. Raises Ask when
    the prompt does not offer it."""
    ev = action["event"]
    m = ev["method"]
    args = ev.get("args") or []
    kw = ev.get("kwargs") or {}
    if wf is None:
        raise Ask("NOT WAITING — it is not this seat's move (sparring.py wait)", wf)
    if m == "place":
        if wf.get("type") != "space":
            raise Ask(f"step is a bare place but the app asks {wf.get('type')!r}", wf)
        sid = action["follow"]["space"]
        if wf.get("spaces") and str(sid) not in [str(s) for s in wf["spaces"]]:
            raise Ask(f"space {sid} is not among the app's legal spaces", wf)
        action["follow"]["space"] = None
        return sparring.space(sid)
    if m == "wgt":
        return _build_wgt(args, kw, wf)
    if not is_action_menu(wf):
        raise Ask(f"expected the action-phase menu for a {m} step, the app asks "
                  f"{wf.get('type')!r} '{sparring._title(wf)}'", wf)
    try:
        if m == "play":
            return _build_play(args, kw, wf, eng, game)
        if m == "standard":
            return _build_standard(args, kw, wf, eng, game)
        if m == "convert":
            return _build_convert(args, action, wf)
        if m == "milestone":
            return sparring.claim_milestone(wf, args[1])
        if m == "award":
            return sparring.fund_award(wf, args[1])
        if m == "use_action":
            info = eng.card(args[0])
            return sparring.card_action(wf, info["name"] if info else args[0])
        if m == "free_action_city":
            # generation 1, a corporation with a mandatory first action:
            # the app offers only "Take first action of <corp>" + pass
            return sparring.choose(wf, "take first action")
        if m == "pass":
            return sparring.choose(wf, "pass for this generation")
    except KeyError as e:                      # find_option / card_action
        raise Ask(f"the app does not offer it: {e.args[0]}", wf)
    raise Ask(f"no app input for event {m!r}", wf)


def _build_wgt(args, kw, wf) -> dict:
    """Answer the solar-phase World Government prompt. `oceans` needs the
    hex the step already names (`space_id`); without one this ASKS rather
    than picking a space for the player."""
    param = str(args[0]).lower() if args else ""
    needle = WGT_BRANCH.get(param)
    if needle is None:
        raise Ask(f"unknown WGT parameter {param!r} — one of "
                  f"{', '.join(WGT_BRANCH)}", wf)
    if wf.get("type") != "or" or "world government" not in \
            str(sparring._title(wf)).lower():
        raise Ask(f"expected the World Government Terraforming prompt, the "
                  f"app asks {wf.get('type')!r} '{sparring._title(wf)}'", wf)
    try:
        return sparring.choose(wf, needle,
                               space=kw.get("space_id") or kw.get("hex"))
    except KeyError as e:
        raise Ask(f"the app does not offer it: {e.args[0]}", wf)


def _build_play(args, kw, wf, eng: Engine, game: dict) -> dict:
    player, card = args[0], args[1]
    info = eng.card(card)
    name = info["name"] if info else card
    idx = sparring.find_option(wf, "play project card")
    opt = wf["options"][idx]
    offered = _card_offered(opt, name)
    if offered is None:
        raise Ask(f"{name!r} is not among the playable cards the app lists: "
                  f"{[c.get('name') for c in opt.get('cards') or []]}", wf)
    if kw.get("cost") is not None:
        price = int(kw["cost"])
    elif info is not None:
        price = card_price(game, eng.resolve_player(player), info)["price"]
    else:
        raise EventError(f"{card!r} not in cards/db.json and the step gives no cost")
    app_cost = offered.get("calculatedCost")
    if isinstance(app_cost, int) and app_cost != price:
        raise Ask(f"price disagreement for {name}: engine/step {price} MC vs app "
                  f"calculatedCost {app_cost} — fix the step's cost (a discount "
                  f"the engine does not model?) before sending", wf)
    steel, ti, heat = (int(kw.get(k) or 0) for k in ("steel", "titanium", "heat"))
    # the step's own metal/heat amounts, priced by THE splitter — the step
    # is the contract with the engine, so the payload never invents a
    # payment the tracker did not charge.
    pay = split_payment(game, eng.resolve_player(player), price,
                        steel=steel, titanium=ti, heat=heat)
    return sparring.or_choice(idx, sparring.project_card(
        name, mc=pay["mc"], steel=steel, titanium=ti, heat=heat))


def _build_standard(args, kw, wf, eng: Engine, game: dict) -> dict:
    player, project = args[0], args[1]
    if project == "sell_patents":
        idx = sparring.find_option(wf, "sell patents")
        names = list(kw.get("cards") or (args[2] if len(args) > 2 else []))
        return sparring.or_choice(idx, sparring.cards(names))
    if project not in SP_CARD:
        raise EventError(f"Unknown standard project {project!r}: {list(SP_CARD)}")
    idx = sparring.find_option(wf, "standard projects")
    opt = wf["options"][idx]
    offered = _card_offered(opt, SP_CARD[project])
    if offered is None:
        raise Ask(f"standard project {SP_CARD[project]!r} not listed by the app", wf)
    if offered.get("isDisabled"):
        raise Ask(f"the app lists {SP_CARD[project]!r} as DISABLED (no legal "
                  f"space / not affordable)", wf)
    price = standard_project_price(game, eng.resolve_player(player), project)["price"]
    app_cost = offered.get("calculatedCost")
    if isinstance(app_cost, int) and app_cost != price:
        raise Ask(f"price disagreement for {SP_CARD[project]}: engine {price} vs "
                  f"app {app_cost}", wf)
    pay = _payment_split(game, price)             # Helion: MC first, then heat
    return sparring.or_choice(idx, sparring.project_card(
        SP_CARD[project], mc=pay["mc"], heat=pay["heat"]))


def _build_convert(args, action, wf) -> dict:
    kind = args[1]
    if kind == "heat":
        return sparring.choose(wf, "convert 8 heat")
    if kind == "plants":
        sid = action["follow"]["space"]
        if sid is None:
            raise Ask("plants → greenery needs the hex: add a place event "
                      "(place <me> greenery <ref>) to the step", wf)
        idx = sparring.find_option(wf, "plants into greenery")
        action["follow"]["space"] = None
        return sparring.or_choice(idx, sparring.space(sid))
    raise EventError(f"Unknown conversion {kind!r}")


# ── verification (sandbox vs app) ────────────────────────────

_View = verify.ViewClient      # one implementation, verify.py's


def _hand_size(view: dict) -> int | None:
    tp = view.get("thisPlayer") or {}
    n = tp.get("cardsInHandNbr")
    if isinstance(n, int):
        return n
    cards = tp.get("cardsInHand")
    return len(cards) if isinstance(cards, list) else None


def _drift(eng: Engine, name: str, view: dict) -> dict:
    """{field: (tracker, app)} for `name` — verify.diff's row plus the
    hand size."""
    fetch = lambda _n: verify._fetch_app(_View(view), "")
    rows = verify.diff(eng, [name], fetch)
    d = dict(next(r["drift"] for r in rows if r["player"] == name))
    hand = _hand_size(view)
    mine = len(eng.store.load_game()["me"]["hand"])
    if hand is not None and hand != mine:
        d["hand"] = (mine, hand)
    return d


def verify_step(store: Store, step: dict, pre: dict, post: dict,
                block: bool = True) -> list[str]:
    """Simulate the step in a sandbox and compare with the app's post
    view. Returns the report lines; raises VerifyMismatch when a blocking
    field's drift is NEW (drift the tracker already had before the send
    is reported as pre-existing, never blocks).

    `block=False` (app modes) turns the refusal into reporting: the
    differences are printed as `ℹ` lines and the caller adopts the app's
    values. Physical mode keeps block=True — there is no app to adopt, so
    the simulation is the only check there is.
    """
    name = _me(store.load_setup())["name"]
    pre_drift = _drift(Engine(store), name, pre)
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp) / "state"
        shutil.copytree(store.state_dir, sandbox)
        eng = Engine(Store(tmp, state_dir=sandbox))
        for ev in step.get("events") or []:
            getattr(eng, ev["method"])(*ev.get("args", []), **ev.get("kwargs", {}))
        post_drift = _drift(eng, name, post)
        g = eng.store.load_game()
        # Cards that DRAW (cards/db.json behavior.drawCard) leave the app's
        # hand larger than the engine's: the engine cannot know which card
        # was drawn, so it does not model it. Before P7 that made every
        # draw card exit 41 on a step where nothing was wrong (Convoy From
        # Europa, refusal #4) and cost three recovery calls each time.
        drawers = []
        for ev in step.get("events") or []:
            args = ev.get("args") or []
            if ev.get("method") == "play":
                cname = args[1] if len(args) > 1 else None
                beh = ((eng.card(cname) or {}).get("behavior") or {}) if cname else {}
                if beh.get("drawCard"):
                    drawers.append(cname)
            elif ev.get("method") == "place" and len(args) > 2:
                # P8: a hex whose placement bonus is cards (13/B6 pays +2)
                # grows the app's hand the same way a draw card does — the
                # engine grants the bonus but cannot name the cards.
                spaces = eng._board()
                try:
                    sid = str(grid_to_space(str(args[2]), spaces))
                except Exception:
                    sid = str(args[2])
                n = (spaces.get(sid) or {}).get("bonus", []).count("card")
                if n:
                    drawers.append(f"{args[1]} on {sid} (+{n} card bonus)")
    lines, blocking = [], []
    for field, (expect, app) in post_drift.items():
        if not isinstance(expect, int) or not isinstance(app, int):
            continue
        delta = app - expect
        pre_pair = pre_drift.get(field)
        pre_delta = (pre_pair[1] - pre_pair[0]) if pre_pair else 0
        if delta == pre_delta:
            lines.append(f"  ℹ {field}: pre-existing drift tracker {expect} vs app "
                         f"{app} (Δ {delta:+d} before the step too — verify.py --sync)")
        elif field == "hand" and drawers and app > expect:
            lines.append(f"  ℹ hand: engine {expect} vs app {app} — "
                         f"{', '.join(drawers)} draws; the engine cannot know "
                         f"which card, so hand size is not blocking here "
                         f"(listen.py once lands the drawn card)")
        elif field in BLOCKING_FIELDS and block:
            blocking.append(f"  ✗ {field}: engine expects {expect}, app shows {app}")
        elif field in BLOCKING_FIELDS:
            lines.append(f"  ℹ {field}: sandbox predicted {expect}, app shows "
                         f"{app} (Δ {delta:+d}) — the app is adopted")
        else:
            lines.append(f"  ⚠ {field}: engine {expect} vs app {app} (not blocking)")
    r = g["me"]["resources"]
    verdict = "✗ MISMATCH" if blocking else "✓ engine == app"
    if not blocking and not block and any("sandbox predicted" in ln for ln in lines):
        verdict = "ℹ sandbox ≠ app (the app rules)"
    summary = (f"verify: {verdict} "
               f"(MC {r['mc']}, TR {g['me']['tr']}, prod MC "
               f"{g['me']['production']['mc']}, hand {len(g['me']['hand'])})")
    if blocking:
        raise VerifyMismatch("\n".join([summary, *blocking, *lines]))
    return [summary, *lines]


def report_prediction(store: Store, step: dict, pre: dict, post: dict,
                      adopting: bool, out=print) -> None:
    """Print the sandbox-vs-app report. In app modes a sandbox that cannot
    even SIMULATE the step (the engine refuses a cost/requirement the app
    allowed) is a missing prediction, not a table stop — the send already
    happened and the app view is about to be adopted."""
    try:
        for line in verify_step(store, step, pre, post, block=not adopting):
            out(line)
    except EventError as e:
        if not adopting:
            raise
        out(f"verify: ℹ no sandbox prediction — the engine cannot simulate "
            f"this step ({e}); the app took it, so its view is adopted")


def app_mode(store: Store) -> bool:
    """app-practice / app-online — where the APP is the rules engine."""
    return planlib.game_mode(store) in planlib.APP_MODES


def warn_metal_values(view: dict, out=print) -> None:
    """Report it LOUDLY when the app prices metal differently from the engine.

    tmlib's STEEL_VALUE / TITANIUM_VALUE are constants; a tableau card can
    raise them (Advanced Alloys). When that happened in a recorded game the
    harness built payments at the low rate and the app accepted the
    OVERPAYMENT — and `verify: engine == app` still printed OK, because both
    sides used the same wrong number. A shared error is invisible to
    reconciliation, so it is surfaced here instead.
    """
    me = view.get("thisPlayer") or {}
    drift = [(r, int(me[k]), c)
             for r, k, c in (("steel", "steelValue", STEEL_VALUE),
                             ("titanium", "titaniumValue", TITANIUM_VALUE))
             if isinstance(me.get(k), int) and int(me[k]) != c]
    if not drift:
        return
    detail = "; ".join(f"{r} {app} MC (engine {eng})" for r, app, eng in drift)
    out(f"⚠ METAL PRICING: the app values {detail}. The tracker prices metal "
        f"at the engine rate, so a step paid in ore may OVERPAY by ~1 MC per "
        f"ore and set_plan may refuse an affordable step. State GROSS card "
        f"costs and prefer cash where it is close.")


def adopt_app(store: Store, view: dict, out=print) -> None:
    """Overwrite the tracker's numbers with the app's post-send view.

    My mat (resources, production, TR), my hand and tableau, everyone's
    card resources, the globals and the board — verify.sync_table, the
    same machinery `listen.py` and `verify.py --sync` use. The step's
    events were applied first, so the ledger (actionsThisGen) and the
    plan's done state are already recorded; adoption only replaces
    numbers, and never touches either.
    """
    try:
        table = verify.from_view(view)
    except (KeyError, TypeError) as e:            # a view we cannot parse
        out(f"ℹ app view not adopted ({type(e).__name__}: {e}) — run "
            f"listen.py once / verify.py --sync")
        return
    me = store.load_game()["me"]["name"]
    if me not in table:
        out("ℹ app view carries no mat for me — nothing adopted "
            "(listen.py once / verify.py --sync)")
        return
    warn_metal_values(view, out)
    parts = verify.sync_table(Engine(store), [me], lambda n: table[n])
    out("app adopted: " + (", ".join(parts) if parts
                           else "exact (the tracker already matched)"))


# ── the executor ─────────────────────────────────────────────

def _client_and_pid(store: Store, url: str | None, pid: str | None):
    setup = store.load_setup()
    base = url or appapi.configured_url(setup)
    if not base:
        raise EventError("no app URL: state/setup.json appUrl, $PHOBOS_APP_URL or --url")
    pid = pid or _me(setup).get("playerId") or setup.get("playerId")
    if not pid:
        raise EventError("no playerId for me in state/setup.json (session.py "
                         "link-player) — or pass --pid")
    return AppClient(base), pid


def _check_patch_failed(store: Store, force: str | None, out) -> None:
    """P8 #10: a `planlib.py patch` that RAISED leaves the plan unpatched.
    In the P8 game the advisor chained `turn.py go && execute.py turn` past
    the error and executed the stale step (Physics Complex instead of the
    SP power plant, ≈2 VP). planlib records the failure on the plan as
    `patchFailed`; while it stands the executor refuses to run anything.
    Defensive: no key (older plans, planlib without the flag) = no refusal.
    """
    try:
        stale = planlib.load_plan(store).get("patchFailed")
    except Exception:                            # no plan → _find_step reports
        return
    if not isinstance(stale, str) or not stale.strip():
        return
    if force:
        out(f"⚠ running with a FAILED patch on the plan (--force): {stale}")
        return
    raise Ask(f"PLAN PATCH FAILED — the last planlib.py patch did not apply, "
              f"so this plan is NOT the one you just decided on:\n  {stale}\n"
              f"Re-run the patch (planlib.py patch … — add --live for a live "
              f"plan), or override with --force '<why this step is unaffected>'")


def _trigger_guard(store: Store, force: str | None, out,
                   dry_run: bool = False) -> None:
    """S5: the unhandled-trigger surface at the TRANSMIT point.

    Until P9 the only surface was `turn.py go` — with a live plan every
    generation its promote was a no-op 38 times, the call existing purely
    to run this check (~10 s each). The list is the listener's verdicts
    (turn._pending → triage.pending, no re-classification) and the banner
    is `go`'s own.

    It WARNS; it does not refuse. That is `turn.py go`'s contract verbatim
    ("it warns, not refuses, so the loop cannot deadlock" —
    skills/turn-advisor), and the reason is concrete: turnover triggers
    (generation, first_player) arrive EVERY generation, so a hard block
    deadlocks the loop at every boundary — the scripted e2e proof stopped
    dead on exactly that. The speed win is unaffected: the banner reaches
    the advisor at transmit time, so `turn.py go` is no longer needed
    between `listen.py wait` and `execute.py` on the fast path.

    `--force '<why>'` still suppresses the banner and logs the reason, for
    a caller that has read the triggers and wants that on the record. A dry
    run transmits nothing, so it says nothing.
    """
    if dry_run:
        return
    pend = turn._pending(store)
    if not pend:
        return
    gen = store.load_game()["generation"]
    if force:
        store.log(f"G{gen}", f"execute.py: {len(pend)} unhandled trigger(s) "
                             f"OVERRIDDEN: {force}")
        out(f"⚠ executing with {len(pend)} unhandled trigger(s) (--force): {force}")
        return
    for row in turn._judgment_warning(pend):
        out(row)
    out("  → read them, then `triage.py handle <line>… --note` or "
        "`advise.py --sweep`; execution continues (the loop never deadlocks)")


def _find_step(store: Store, label: str) -> dict:
    plan = planlib.load_plan(store)
    if plan.get("draft"):
        raise EventError("Plan is a DRAFT — planlib.py promote first")
    want = label.strip().lower()
    hit = next((s for s in plan["steps"] if s["id"].lower() == want), None)
    if hit is None:
        raise EventError(f"No plan step {label!r}; steps: "
                         f"{[s['id'] for s in plan['steps']]}")
    if hit.get("done"):
        raise EventError(f"{hit['id']} is already marked done")
    return hit


def _send(client: AppClient, pid: str, response: dict, wf, out) -> None:
    out(f"send: {json.dumps(response, ensure_ascii=False)}")
    try:
        client.send(pid, response)
    except AppError as e:
        if e.status == 400:
            raise Ask(f"the app REJECTED the input (HTTP 400 {e.body[:200]})", wf)
        raise


def _answer_follow_ups(client: AppClient, pid: str, follow: dict, out,
                       step: dict | None = None,
                       store: Store | None = None) -> dict:
    """After a send: answer the follow-up prompts the step covers, stop at
    the next action menu / NOT WAITING; anything else → Ask (sent=True)."""
    step = step or {}
    for _ in range(6):
        data = client.player(pid)
        wf = data.get("waitingFor")
        if wf is None or is_action_menu(wf):
            return data
        # THE GENERATION ROLLED while this step resolved: the last action
        # of a generation lands, every seat passes, and the app's next
        # prompt is the NEXT generation's research offer. That is the
        # research lane's business (execute.py pick, and its buy-0 gate),
        # never a follow-up of the action just sent — reading it as one
        # ASKed on a step that had in fact succeeded, and stopped the
        # scripted rehearsal (and so the LIVE GATE) on three deals running.
        if str((data.get("game") or {}).get("phase") or "").lower() == "research":
            return data
        t = wf.get("type")
        if t == "space" and (follow.get("space") is not None
                             or follow.get("spaceQueue")):
            sid = (follow.pop("space") if follow.get("space") is not None
                   else follow["spaceQueue"].pop(0))
            if wf.get("spaces") and str(sid) not in [str(s) for s in wf["spaces"]]:
                raise Ask(f"space {sid} is not among the app's legal spaces "
                          f"{wf['spaces'][:12]}", wf, sent=True)
            _send(client, pid, sparring.space(sid), wf, out)
        elif t == "or" and (follow.get("or") is not None
                            or follow.get("player") is not None):
            # the inner response comes from the SELECTED BRANCH's type, and
            # consumes the step kwarg that feeds it (P9 #1)
            chosen = follow.pop("or", None)
            if chosen is None:
                # Removal cards wrap the victim selector in a MENU rather
                # than offering the bare `player` prompt follow["player"]
                # answers, so a correct target went unused on Comet and
                # Giant Ice Asteroid. Exactly one player branch selects
                # itself; more than one is ambiguous and refuses.
                pbranches = [i for i, o in enumerate(wf.get("options") or [])
                             if (o.get("type") or "option") == "player"]
                if len(pbranches) != 1:
                    raise Ask(
                        f"step targets {follow['player']!r} but this `or` has "
                        f"{len(pbranches)} player branches — pass an explicit "
                        f"choice (index or title substring)", wf, sent=True)
                chosen = pbranches[0]
            try:
                response, used = _or_branch_response(
                    wf, chosen, store=store, cards=follow.get("card"),
                    space=follow.get("space"), target=follow.get("player"),
                    expect=follow.pop("orExpect", None))
            except Ask as e:
                raise Ask(str(e), e.wf if e.wf is not None else wf, sent=True)
            if used:
                follow.pop(used, None)
            _send(client, pid, response, wf, out)
        elif t == "player" and follow.get("player") is not None:
            # the app identifies players by COLOR (P8 #15)
            color = _player_color(store, follow.pop("player"))
            _send(client, pid, sparring.target_player(color), wf, out)
        elif t == "card" and follow.get("card") is not None:
            _send(client, pid, sparring.cards(follow.pop("card")), wf, out)
        elif t == "card" and "buy" in step and not wf.get("min"):
            # A blue-card action can open an OPTIONAL card offer whose
            # contents nobody can know at plan time (Inventors' Guild).
            # A step may declare the policy up front: buy:false declines,
            # buy:"<Card>" takes it when offered. P7 E1.
            policy = step["buy"]
            offered = _offered_names(wf)
            if policy in (False, None, "none", []):
                _send(client, pid, sparring.cards([]), wf, out)
            elif isinstance(policy, str) and policy.lower() in {
                    o.lower() for o in offered}:
                _send(client, pid, sparring.cards([policy]), wf, out)
            else:
                raise Ask(
                    f"step declares buy={policy!r} but the offer is {offered} "
                    f"— resolve it with: execute.py resolve {step.get('id')} "
                    f"[--cards \"<Card>\"]", wf, sent=True)
        elif t == "payment" and isinstance(wf.get("amount"), int):
            # "Select how to pay for milestone/award/action" and "Select
            # how to spend N M€ for K cards": MC first, then heat for a
            # corporation that spends heat as money (P8 #16). Steel /
            # titanium alternatives stay the player's call, never guessed.
            pay = _payment_split(store.load_game() if store else {},
                                 wf["amount"])
            _send(client, pid, sparring.payment(mc=pay["mc"],
                                                heat=pay["heat"]), wf, out)
        elif t == "card":
            raise Ask(
                f"the app asks an uncovered 'card' follow-up "
                f"('{sparring._title(wf)}'), offering {_offered_names(wf)}. "
                f"Close it in ONE call: execute.py resolve "
                f"{step.get('id', '<label>')} [--cards \"<Card>\"] "
                f"(no --cards = decline). Declare it up front next time with "
                f'"buy": false or "buy": "<Card>" on the step.',
                wf, sent=True)
        else:
            raise Ask(f"the app asks a {t!r} follow-up ('{sparring._title(wf)}') "
                      f"the step does not cover — answer it with sparring.py, "
                      f"then planlib.py done", wf, sent=True)
    raise Ask("follow-up chain longer than 6 prompts — stopping", None, sent=True)


def run_step(store: Store, label: str, client: AppClient, pid: str,
             dry_run: bool = False, no_done: bool = False, out=print,
             force: str | None = None, guard: bool = True) -> int:
    """One plan step end to end. Returns the exit code; prints the trace.
    `guard=False` = the caller (run_turn) already ran the trigger guard."""
    try:
        _check_patch_failed(store, force, out)
        step = _find_step(store, label)
        actions = plan_actions(step)
        out(f"▶ {step['id']}  {step.get('summary', '')}")
        if not actions:
            raise Ask("the step has no app-executable event (tracker-only "
                      "events) — planlib.py done marks it")
        if guard:
            _trigger_guard(store, force, out, dry_run=dry_run)
        # THE PASS GATE, PRE-SEND. planlib's gate runs in mark_done —
        # i.e. after execute has already transmitted — so in app mode it
        # could only report, never refuse. In the P7 game that cost a real
        # VP: an SP Aquifer revived Kelp Farming (1 printed VP, affordable)
        # and the advisory arrived after the pass was gone. With
        # executor=auto the only useful moment is BEFORE the send.
        # S4: the reason may be pre-declared on the step ("force" field);
        # it is read like --force, logged the same, and still refused when
        # the LIVE list holds an item it does not mention. --force wins.
        if step.get("passGate") and not dry_run:
            blocking, advisory = planlib.gate_items(store)
            avail = [planlib.gate_line(i) for i in blocking]
            if advisory:
                out("ℹ also available (advisory, not blocking): "
                    + "; ".join(i["label"] for i in advisory))
            reason, source = planlib.gate_reason(step, force)
            missing = (planlib.uncovered_items(reason, blocking)
                       if source == "step" else [])
            if avail and missing:
                listed = "\n  ".join(missing)
                raise Ask(f"PASS REFUSED — the step's pre-declared reason "
                          f"({reason!r}) does not cover:\n  {listed}\nDo them, "
                          "extend the step's \"force\" field, or override with "
                          "an explicit per-item reason "
                          "(execute.py step <id> --force '<why each is bad>')")
            if avail and not reason:
                listed = "\n  ".join(avail)
                raise Ask("PASS REFUSED — free/positive actions still "
                          f"available:\n  {listed}\nDo them, or override with "
                          "an explicit per-item reason "
                          "(execute.py step <id> --force '<why each is bad>')")
            if avail and reason:
                gen = store.load_game()["generation"]
                store.log(f"G{gen}", f"execute.py: pass with {len(avail)} "
                                     f"available action(s) OVERRIDDEN: {reason}")
                out(f"⚠ passing with {len(avail)} action(s) available "
                    f"({'--force' if source == 'cli' else 'step force'}): {reason}")
        eng = Engine(store)
        game = store.load_game()
        data = client.player(pid)
        wf = data.get("waitingFor")
        out("prompt:\n" + _indent(sparring.shape(wf)))
        pre = data
        # THE ZERO-EFFECT GATE, PRE-SEND. A standard project whose whole
        # effect is a step on a full track buys nothing, and the track can
        # fill between plan time and execution (an opponent's raise during
        # our wait). In the practice game two SP Asteroids went into a
        # +8 °C track: 28 M€, 0 TR, and an SP Greenery would have been 1 VP.
        # menu.py drops such a project when the plan is written; this is
        # the same rule at the only moment that can still catch it.
        zero = standard_zero_effect_gate(actions, game, data) if not dry_run else None
        if zero:
            project, why = zero
            if not force:
                raise Ask(f"ZERO-EFFECT STANDARD PROJECT — SP {project} would "
                          f"buy nothing: {why}. Spend the action on something "
                          f"that scores (SP greenery still places a tile), or "
                          f"override with "
                          f"`execute.py step {step['id']} --force '<why>'`")
            gen = store.load_game()["generation"]
            store.log(f"G{gen}", f"execute.py: ZERO-EFFECT SP {project} "
                                 f"({why}) OVERRIDDEN: {force}")
            out(f"⚠ sending SP {project} although {why} (--force): {force}")
        for i, action in enumerate(actions):
            if i and not dry_run:
                wf = data.get("waitingFor")
                out("prompt:\n" + _indent(sparring.shape(wf)))
            response = build_primary(action, wf, eng, game)
            if dry_run:
                out(f"would send: {json.dumps(response, ensure_ascii=False)}")
                planned = {k: v for k, v in action["follow"].items() if v is not None}
                if planned:
                    out(f"would answer follow-ups: {json.dumps(planned)}")
                continue
            _send(client, pid, response, wf, out)
            if action["event"]["method"] == "pass":
                # a pass has no follow-ups: whatever the app shows next
                # (nothing, the next seat's turn, the NEXT generation's
                # research prompt) is a new phase, not a question to us
                data = client.player(pid)
            else:
                data = _answer_follow_ups(client, pid, action["follow"], out,
                                          step=step, store=store)
        if dry_run:
            out("dry-run: nothing sent, plan untouched")
            return 0
        adopting = app_mode(store)
        rolled = _generation_rolled(pre, data)
        if rolled:
            out(f"verify: skipped — the pass closed generation "
                f"{(pre.get('game') or {}).get('generation')}; the app already "
                f"paid the income (listen.py once ingests 'Generation N' and "
                f"runs produce)")
        else:
            report_prediction(store, step, pre, data, adopting, out)
        if no_done:
            out(f"--no-done: {step['id']} stays open (its events are NOT "
                f"applied, so the app view is not adopted either)")
        else:
            confirm = "app-adopted" if adopting else "app-verified"
            try:
                _mark_done(store, step, out,
                           skip_gate_report=rolled and bool(step.get("passGate")),
                           confirm=confirm)
            except EventError as e:
                if not adopting:
                    raise
                # The app ACCEPTED the action (it is the rules engine) and
                # the tracker's replay of the step's events refused it — a
                # discount, a trigger or a choice the engine does not
                # model. Leaving the tracker stale here is exactly the P8
                # recovery cost: adopt the app's numbers, then ask.
                out(f"ℹ the tracker refused the step's events ({e}) — the app "
                    f"took the action, so its view is adopted anyway")
                adopt_app(store, data, out)
                raise Ask(f"the app accepted {step['id']} but the tracker's "
                          f"event replay refused it: {e}\nThe numbers are "
                          f"adopted from the app; close the step with: "
                          f"planlib.py done {step['id']} --no-apply", sent=True)
            if adopting and not rolled:
                # the app settled the rules; the tracker takes its numbers
                adopt_app(store, data, out)
            elif adopting:
                out("ℹ app view NOT adopted — the pass closed the generation "
                    "and the app has already paid the income; listen.py once "
                    "runs produce and then syncs the table")
            gen = store.load_game()["generation"]
            store.log(f"G{gen}", f"execute.py: {step['id']} sent to the app, "
                                 f"{confirm}")
            out(f"done: {step['id']} ({confirm}, events applied to the tracker)")
        out("next prompt:\n" + _indent(sparring.shape(data.get("waitingFor"))))
        return 0
    except Ask as e:
        out(f"ASK: {e}" + (" [input already sent — plan NOT marked done]"
                           if e.sent else " [nothing sent]"))
        if e.wf is not None:
            out(_indent(sparring.shape(e.wf)))
        return EXIT_ASK
    except VerifyMismatch as e:
        out(f"VERIFY MISMATCH — plan NOT marked done; check the app, then "
            f"verify.py --sync or fix the step:\n{e}")
        return EXIT_VERIFY


GATE_REPORT_MARKERS = ("⚠ pass with available actions",
                       "ℹ also available (advisory")


def _mark_done(store: Store, step: dict, out, skip_gate_report: bool = False,
               confirm: str = "app-verified") -> None:
    """planlib.mark_done for an app-verified step.

    P8 #3: mark_done's saturation gate re-reads LIVE state, and after the
    pass that closed the generation the app has already paid the income —
    so it reported the NEXT generation's options as missed ones ("8 heat →
    temperature — have 8 heat" when heat was 3 at pass time, G2/G11/G12).
    The pre-send gate in run_step is the real gate; here the report is
    noise, so it is filtered out of mark_done's stdout (mark_done has no
    kwarg to skip its gate; verify=False silences everything else it
    prints).
    S4: `step_force=False` — the pre-send gate consumed the step's
    pre-declared "force" field and logged the override; mark_done keeps
    its post-send report but never writes a second OVERRIDDEN line.
    """
    call = lambda: planlib.mark_done(store, step["id"], apply_events=True,
                                     verify=False, confirm=confirm,
                                     step_force=False)
    if not skip_gate_report:
        call()
        return
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        call()
    dropped = False
    for line in buf.getvalue().splitlines():
        if any(line.startswith(m) for m in GATE_REPORT_MARKERS):
            dropped = True
            continue
        if dropped and line.startswith("  "):        # its indented items
            continue
        dropped = False
        out(line)
    out("ℹ post-send pass gate skipped — the pass closed the generation, so "
        "the tracker/app now hold post-production values; the pre-send gate "
        "already ruled on this pass")


def _indent(text: str) -> str:
    return "\n".join("  " + ln for ln in text.splitlines())


def _generation_rolled(pre: dict, post: dict) -> bool:
    """The send closed the generation (every seat passed): the post view
    is a later generation / the research or end phase."""
    g0, g1 = pre.get("game") or {}, post.get("game") or {}
    gen0, gen1 = g0.get("generation"), g1.get("generation")
    if isinstance(gen0, int) and isinstance(gen1, int) and gen1 > gen0:
        return True
    return g1.get("phase") in ("research", "end") and g0.get("phase") not in (
        "research", "end")


def run_turn(store: Store, labels: list[str], client: AppClient, pid: str,
             dry_run: bool = False, no_done: bool = False, out=print,
             force: str | None = None) -> int:
    executor = judgment.load(store).get("executor", "assist")
    if executor == "manual":
        out("executor=manual: the player CLICKS in the app — dry-run only, "
            "nothing is sent; mark with planlib.py done once executed")
        dry_run = True
    elif executor == "assist" and not dry_run:
        out("executor=assist: sending each input right after printing it")
    # S5: ONE trigger guard for the whole turn (one banner, one override
    # log line), so the steps run with guard=False. The latency mark is
    # main's — one "execute" block per invocation, never nested (S6).
    try:
        _trigger_guard(store, force, out, dry_run=dry_run)
    except Ask as e:
        out(f"ASK: {e} [nothing sent]")
        return EXIT_ASK
    for label in labels:
        rc = run_step(store, label, client, pid, dry_run=dry_run,
                      no_done=no_done, out=out, force=force, guard=False)
        if rc:
            return rc
    return 0


# ── prompt verbs (not plan steps) ────────────────────────────

def run_resolve(store: Store, label: str, client: AppClient, pid: str,
                cards=None, space=None, choice=None, target=None,
                amount=None, out=print) -> int:
    """Answer the follow-up prompt an already-SENT step left open, verify,
    and mark the step done — in ONE call.

    P7 E1: a blue-card action can open a prompt whose contents nobody knows
    at plan time (Inventors' Guild's card offer). The action is consumed by
    the first send, so the step cannot simply be retried; before this verb
    recovery took three calls (sparring.py pick → listen.py once →
    planlib.py done --confirm), five times in one game.
    """
    try:
        step = _find_step(store, label)
        pre = client.player(pid)
        wf = pre.get("waitingFor")
        if wf is None or is_action_menu(wf):
            raise Ask(f"nothing to resolve for {label}: the app is not asking "
                      f"a follow-up (it shows "
                      f"{'no prompt' if wf is None else 'the action menu'})", wf)
        t = wf.get("type")
        out(f"▶ resolve {step['id']}  {step.get('summary', '')}")
        out("prompt:\n" + _indent(sparring.shape(wf)))
        if t == "card":
            names = list(cards or [])
            offered = {o.lower(): o for o in _offered_names(wf)}
            unknown = [n for n in names if n.lower() not in offered]
            if unknown:
                raise Ask(f"{unknown} not offered; the app offers "
                          f"{list(offered.values())}", wf)
            response = sparring.cards([offered[n.lower()] for n in names])
        elif t == "space":
            if space is None:
                raise Ask("this is a `space` prompt — pass --space <hex>", wf)
            sid = grid_to_space(str(space))
            if wf.get("spaces") and sid not in [str(x) for x in wf["spaces"]]:
                raise Ask(f"space {sid} is not among {wf['spaces'][:12]}", wf)
            response = sparring.space(sid)
        elif t == "or":
            if choice is None:
                raise Ask("this is an `or` prompt — pass --choice <n> (the "
                          "SELECTED BRANCH's type decides the extra flag: "
                          "--target for a player branch, --space for a space, "
                          "--cards for a card, --amount for an amount)", wf)
            response, used = _or_branch_response(
                wf, choice, store=store, cards=cards, space=space,
                target=target, amount=amount)
            if used == "space":
                space = None                 # consumed: never re-sent below
        elif t == "player":
            if target is None:
                raise Ask("this is a `player` prompt — pass --target "
                          "<name|color>", wf)
            response = sparring.target_player(_player_color(store, target))
        elif t == "amount":
            if amount is None:
                raise Ask("this is an `amount` prompt — pass --amount <n>", wf)
            response = {"type": "amount", "amount": int(amount)}
        else:
            raise Ask(f"no resolver for a {t!r} prompt — use sparring.py, "
                      f"then planlib.py done {label} --confirm '<cue>'", wf)
        _send(client, pid, response, wf, out)
        data = _answer_follow_ups(client, pid,
                                  {"space": space, "or": None, "player": None,
                                   "card": None}, out, step=step, store=store)
        adopting = app_mode(store)
        report_prediction(store, step, pre, data, adopting, out)
        confirm = "app-adopted" if adopting else "app-verified"
        try:
            _mark_done(store, step, out, confirm=confirm)
        except EventError as e:
            if not adopting:
                raise
            out(f"ℹ the tracker refused the step's events ({e}) — the app "
                f"took the action, so its view is adopted anyway")
            adopt_app(store, data, out)
            raise Ask(f"the app accepted {step['id']} but the tracker's event "
                      f"replay refused it: {e}\nThe numbers are adopted from "
                      f"the app; close the step with: planlib.py done "
                      f"{step['id']} --no-apply", sent=True)
        if adopting:
            adopt_app(store, data, out)
        gen = store.load_game()["generation"]
        store.log(f"G{gen}", f"execute.py resolve: {step['id']} follow-up "
                             f"answered, {confirm}")
        out(f"done: {step['id']} (resolved + {confirm})")
        out("next prompt:\n" + _indent(sparring.shape(data.get("waitingFor"))))
        return 0
    except Ask as e:
        out(f"ASK: {e}")
        if e.wf is not None:
            out(_indent(sparring.shape(e.wf)))
        return EXIT_ASK
    except VerifyMismatch as e:
        out(f"VERIFY MISMATCH — plan NOT marked done:\n{e}")
        return EXIT_VERIFY


def _buy0_gate(store: Store | None, names: list[str], out,
               override: str | None, wf=None) -> str:
    """The buy-0 gate on the API lane: keeping ZERO cards when the previous
    generation's research also kept zero refuses BEFORE transmitting (the
    pass gate's shape), unless `--override "<why>"` carries a reason, which
    is logged. Returns the log suffix ('' or the OVERRIDDEN tag).

    The gate lived in `Engine.dealt` only, which the API lane never calls —
    so across a 12-generation game with three consecutive zero-buy
    generations it fired exactly never (fix-plan item 4a)."""
    if names or store is None:
        return ""
    try:
        evidence = Engine(store).zero_buy_evidence()
    except (FileNotFoundError, KeyError):
        return ""
    if evidence is None:
        return ""
    gen = store.load_game()["generation"]
    if override and override.strip():
        store.log(f"G{gen}", f"buy-0 gate OVERRIDDEN: {evidence} "
                             f"({override.strip()})")
        out(f"⚠ buy-0 gate OVERRIDDEN: {override.strip()}")
        return buy0_override_tag(override)
    store.log(f"G{gen}", BUY0_REFUSED + evidence)
    raise Ask(f"RESEARCH kept=0 REFUSED — {evidence}. Buy a card, or send "
              f"the empty pick anyway with --override \"<reason>\" "
              f"(the reason is logged)", wf)


def run_pick(client: AppClient, pid: str, names: list[str], out=print,
             store: Store | None = None, override: str | None = None) -> int:
    wf = client.player(pid).get("waitingFor")
    try:
        if wf is None or wf.get("type") != "card":
            raise Ask(f"no `card` prompt to answer (the app asks "
                      f"{None if wf is None else wf.get('type')!r})"
                      + (" — use `corp` for the initial prompt"
                         if wf and wf.get("type") == "initialCards" else ""), wf)
        offered = _offered_names(wf)
        missing = [n for n in names if n not in offered]
        if missing:
            raise Ask(f"{missing} not among the offered cards {offered}", wf)
        gate_tag = _buy0_gate(store, names, out, override, wf)
        _send(client, pid, sparring.cards(list(names)), wf, out)
        # a corporation that pays with heat (Helion) gets "Select how to
        # spend N M€ for K cards" — split MC then heat (_payment_split)
        data = _answer_follow_ups(client, pid, {}, out, store=store)
        # Tell the tracker what we just bought AND charge it. Without the
        # hand line, composing the generation plan right after the buy
        # fails with "<Card> is not in hand" (P7, gen 11); without the
        # charge the tracker runs 3 MC per card high until sync-me (P8
        # #6) — and the listener never fixes it: once the cards are in
        # hand its "Zed bought N card(s)" block is OWN_REFLECTED
        # (listen.reflected, kind "bought") and is skipped whole, so
        # there is no double charge either. pick knows what it sent.
        # The research line itself (`Engine.note_research`, the same
        # composer `apply.py dealt` uses) is written for EVERY research —
        # buys and declines alike: shape.py reads my cards-bought series
        # out of it and the buy-0 gate reads that series (item 4a).
        if store is not None:
            try:
                eng = Engine(store)
                game = eng.store.load_game()
                hand = set(game["me"]["hand"])
                fresh = [n for n in names if n not in hand]
                charged = 0
                if fresh:
                    eng.hand_add(fresh)
                    price = CARD_KEEP_COST * len(fresh)
                    pay = _payment_split(game, price)
                    who = game["me"]["name"]
                    if pay["mc"]:
                        eng.res(who, "mc", -pay["mc"])
                    if pay["heat"]:
                        eng.res(who, "heat", -pay["heat"])
                    charged = pay["mc"]
                    paid = f"−{pay['mc']} MC" + (f" −{pay['heat']} 🔥"
                                                 if pay["heat"] else "")
                    out(f"tracker: hand += {', '.join(fresh)} ({paid} "
                        f"for {len(fresh)} card(s))")
                eng.note_research(offered, list(names), charged,
                                  suffix=gate_tag)
            except Exception as exc:              # never block the table
                out(f"note: could not sync/charge the hand ({exc}); "
                    f"run listen.py sync-me before planning")
    except Ask as e:
        out(f"ASK: {e}" + (" [cards sent — answer the follow-up with sparring.py]"
                           if e.sent else " [nothing sent]"))
        if e.wf is not None:
            out(_indent(sparring.shape(e.wf)))
        return EXIT_ASK
    out(sparring.shape(data.get("waitingFor")))
    return 0


def run_corp(client: AppClient, pid: str, corp: str, cards: list[str],
             out=print) -> int:
    wf = client.player(pid).get("waitingFor")
    try:
        if wf is None or wf.get("type") != "initialCards":
            raise Ask(f"no `initialCards` prompt (the app asks "
                      f"{None if wf is None else wf.get('type')!r})", wf)
        responses = []
        for opt in wf.get("options") or []:
            title = sparring._title(opt).lower()
            if "corporation" in title:
                offered = _offered_names(opt)
                if offered and corp not in offered:
                    raise Ask(f"{corp!r} not among the dealt corporations {offered}", wf)
                responses.append(sparring.cards([corp]))
            elif "initial cards" in title:
                offered = _offered_names(opt)
                missing = [c for c in cards if offered and c not in offered]
                if missing:
                    raise Ask(f"{missing} not among the dealt cards {offered}", wf)
                responses.append(sparring.cards(list(cards)))
            else:
                raise Ask(f"initial prompt part {sparring._title(opt)!r} is not "
                          f"supported (preludes/CEOs)", wf)
        _send(client, pid, {"type": "initialCards", "responses": responses}, wf, out)
    except Ask as e:
        out(f"ASK: {e} [nothing sent]")
        if e.wf is not None:
            out(_indent(sparring.shape(e.wf)))
        return EXIT_ASK
    out(sparring.shape(client.player(pid).get("waitingFor")))
    return 0


def run_sell(store: Store, client: AppClient, pid: str, names: list[str],
             out=print) -> int:
    """SELL PATENTS: discard cards from hand for 1 MC each.

    P9 #2: the app offers it as its own action-menu option (a SelectCard
    over the hand) and advise.py lists it, but nothing could express it. In
    generation 8, with 4 MC left after a Sabotage and an 8 MC Mayor claim
    that had to happen that generation, the sale went out as raw JSON
    through sparring.py send. A PLAN step says the same action as
    {"method": "standard", "args": [<me>, "sell_patents"],
     "kwargs": {"cards": [...]}} — which the sandbox simulates; this verb
    is the ad-hoc form, sent and charged to the tracker in one call.
    """
    data = None
    try:
        if not names:
            raise Ask('name the card(s) to sell: execute.py sell "<Card>" …')
        wf = client.player(pid).get("waitingFor")
        if not is_action_menu(wf):
            raise Ask(f"expected the action-phase menu, the app asks "
                      f"{None if wf is None else wf.get('type')!r}", wf)
        try:
            idx = sparring.find_option(wf, "sell patents")
        except KeyError:
            raise Ask("the app does not offer 'Sell patents' right now "
                      "(an empty hand, or not my action phase)", wf)
        offered = _offered_names(wf["options"][idx])
        canon = {n.lower(): n for n in offered}
        missing = [n for n in names if n.lower() not in canon]
        if missing:
            raise Ask(f"{missing} not among the cards the app lists as "
                      f"sellable {offered}", wf)
        picked = [canon[n.lower()] for n in names]
        _send(client, pid, sparring.or_choice(idx, sparring.cards(picked)),
              wf, out)
        data = _answer_follow_ups(client, pid, {}, out, store=store)
        eng = Engine(store)
        me = eng.store.load_game()["me"]["name"]
        try:
            out(eng.standard(me, "sell_patents", cards=picked))
        except EventError as e:
            out(f"ℹ the tracker refused the sale ({e}) — the app took it, so "
                f"its view is adopted anyway")
        if app_mode(store):
            adopt_app(store, data, out)
    except Ask as e:
        out(f"ASK: {e}" + (" [cards sent — the tracker was NOT charged]"
                           if e.sent else " [nothing sent]"))
        if e.wf is not None:
            out(_indent(sparring.shape(e.wf)))
        return EXIT_ASK
    out("next prompt:\n" + _indent(sparring.shape(data.get("waitingFor"))))
    return 0


def run_pass(client: AppClient, pid: str, out=print,
             store: Store | None = None, force: str | None = None) -> int:
    """The bare pass — no plan step, no saturation gate (that is the
    passGate step's), but the S5 trigger guard when a store is given."""
    wf = client.player(pid).get("waitingFor")
    try:
        if store is not None:
            _trigger_guard(store, force, out)
        if not is_action_menu(wf):
            raise Ask("no action menu with 'Pass for this generation'", wf)
        _send(client, pid, sparring.choose(wf, "pass for this generation"), wf, out)
    except Ask as e:
        out(f"ASK: {e} [nothing sent]")
        if e.wf is not None:
            out(_indent(sparring.shape(e.wf)))
        return EXIT_ASK
    out("passed")
    return 0


# ── CLI ──────────────────────────────────────────────────────

def main(argv=None, store: Store | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=None, help="app base URL (default: "
                   "state/setup.json appUrl, then $PHOBOS_APP_URL)")
    p.add_argument("--pid", default=None, help="my app playerId (default: "
                   "the isMe player's playerId in setup.json)")
    p.add_argument("--root", default=".", help="repo root (state/ = active game)")
    p.add_argument("--state", default=None,
                   help="a state folder instead of state/ — a seat's own "
                        "(session.py seat-init), never the advisor's")
    sub = p.add_subparsers(dest="cmd", required=True)
    for verb, nargs in (("step", None), ("turn", "+")):
        s = sub.add_parser(verb)
        s.add_argument("labels", nargs=nargs or 1, metavar="label")
        s.add_argument("--dry-run", action="store_true",
                       help="print the inputs + prompt tree, send nothing")
        s.add_argument("--no-done", action="store_true",
                       help="send + verify, do not mark the step done")
        s.add_argument("--force", default=None, metavar="REASON",
                       help="pass anyway with actions still available — a "
                            "per-item reason, logged (the pass gate refuses "
                            "BEFORE sending without it); also overrides the "
                            "refusal to run a plan whose last patch failed")
    s = sub.add_parser("resolve", help="answer the follow-up an already-sent "
                                      "step left open, then mark it done")
    s.add_argument("label")
    s.add_argument("--cards", nargs="*", default=None,
                   help="cards to take (omit entirely to decline)")
    s.add_argument("--space", default=None)
    s.add_argument("--choice", default=None,
                   help="branch index of an `or` prompt (0.1 = a submenu's "
                        "second entry); the BRANCH's own type decides which "
                        "of --target/--space/--cards/--amount it also needs")
    s.add_argument("--target", default=None)
    s.add_argument("--amount", default=None,
                   help="answer an `amount` prompt (or an amount branch)")
    s = sub.add_parser("pick", help="answer the current `card` prompt")
    s.add_argument("names", nargs="*")
    s.add_argument("--override", default=None, metavar="REASON",
                   help="keep ZERO cards for the second generation running "
                        "— a reason, logged (the buy-0 gate refuses BEFORE "
                        "sending without it)")
    s = sub.add_parser("corp", help="answer the initial corp + cards prompt")
    s.add_argument("corp"); s.add_argument("names", nargs="*")
    s = sub.add_parser("sell", help="SELL PATENTS: discard cards from hand "
                                    "for 1 MC each (tracker charged too)")
    s.add_argument("names", nargs="+")
    s = sub.add_parser("pass")
    s.add_argument("--force", default=None, metavar="REASON",
                   help="pass with unhandled triggers in the feed — a reason, "
                        "logged (the trigger guard refuses BEFORE sending "
                        "without it)")
    a = p.parse_args(argv)
    store = store or Store(a.root, state_dir=a.state)

    def dispatch() -> int:
        client, pid = _client_and_pid(store, a.url, a.pid)
        if a.cmd == "step":
            executor = judgment.load(store).get("executor", "assist")
            dry = a.dry_run or executor == "manual"
            if executor == "manual" and not a.dry_run:
                print("executor=manual: the player CLICKS in the app — dry-run "
                      "only, nothing is sent")
            return run_step(store, a.labels[0], client, pid, dry_run=dry,
                            no_done=a.no_done, force=a.force)
        if a.cmd == "turn":
            return run_turn(store, a.labels, client, pid, dry_run=a.dry_run,
                            no_done=a.no_done, force=a.force)
        if a.cmd == "resolve":
            return run_resolve(store, a.label, client, pid, cards=a.cards,
                               space=a.space, choice=a.choice,
                               target=a.target, amount=a.amount)
        if a.cmd == "pick":
            return run_pick(client, pid, a.names, store=store,
                            override=a.override)
        if a.cmd == "corp":
            return run_corp(client, pid, a.corp, a.names)
        if a.cmd == "sell":
            return run_sell(store, client, pid, a.names)
        if a.cmd == "pass":
            return run_pass(client, pid, store=store, force=a.force)
        return 2

    # S6: EVERY invocation is one "execute" latency block — the decision
    # boundary, marked without anyone remembering. The end note names the
    # verb, its labels and the exit code, so the digest reads per decision.
    what = " ".join([a.cmd] + [str(x) for x in (
        getattr(a, "labels", None) or ([a.label] if getattr(a, "label", None) else [])
        or getattr(a, "names", None) or [])])
    try:
        with latency.timed("execute", store=store) as t:
            t.note = what
            rc = dispatch()
            t.note = f"{what} rc={rc}"
            return rc
    except (EventError, FileNotFoundError, AppError, AppUnavailable,
            urllib.error.URLError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
