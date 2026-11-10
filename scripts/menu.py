#!/usr/bin/env python3
"""AVAILABLE ACTIONS menu — the online app's action menu, recomputed from
state (derived, never hand-maintained).

Pure functions over the game/setup dicts + cards/db.json. The menu lists
ONLY what the player can do right now: an item whose prerequisite fails is
not listed at all (a hand-maintained saturation list once listed Equatorial
Magnetizer at 0 energy production while missing NRB / Business Network /
Underground Detonations — hence derived from state per plan step).

Kinds: card (hand card playable now), action (blue-card action open this
generation), standard (standard project), milestone (claimable), award
(fundable, with the player's metric vs the best opponent AND the lock test),
convert (8 heat / 8 plants), warning (not an action — a hoard/exposure the
pass gate must carry). Consumers: advise.py brief, planlib's pass gate, turn.py done,
and the CLI (`python3 scripts/menu.py`) for GO messages.

Library:
    available_actions(game, setup, db=None, free_land=None) -> list[dict]
    render(items, game, app=None) -> str      # the AVAILABLE ACTIONS block
    summary(items) -> str                     # 'available: …, pass'
    tag_counts(game, name, db=None) -> dict   # persisting tags incl. corp
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cards as cardlib
import research
import tmlib
from tmlib import (AWARDS, AWARD_COSTS, CARD_KEEP_COST, MAX_MILESTONES,
                   MILESTONE_COST, MILESTONES, PARAM_SCALE, RESOURCES,
                   SPEND_RESOURCES, STANDARD_PROJECTS, STEEL_VALUE,
                   TITANIUM_VALUE, _zeros, all_pools, player_pool,
                   split_payment)

MILESTONE_NEED = {"Terraformer": 35, "Mayor": 3, "Gardener": 3,
                  "Builder": 8, "Planner": 16}
MILESTONE_METRIC = {"Terraformer": "TR", "Mayor": "cities",
                    "Gardener": "greeneries", "Builder": "building tags",
                    "Planner": "cards in hand"}
# card-table: prose-actions
# The ONLY blue-card actions this menu cannot price from cards/db.json.
# The first four are implemented as TypeScript `action()`/`canAct()` in the
# vendor (their db entry lists them under bespokeMethods), so the db holds
# prose and no `actionBehavior`. The last two DO have an actionBehavior
# (drawCard) but their real price is the CARD OFFER — 3 MC to buy the card
# that is revealed — which is not part of the behavior.
# `cost` is the price the app's log never prints, so the replayer charges
# it from here too (it used to carry its own copy as a per-card branch
# chain): a number, or "@mcGained" for a variable spend equal to the MC the
# log shows arriving. `min` is what the action needs to be OFFERED at all,
# `tr`/`gain` what it produces.
UNMI = "United Nations Mars Initiative"
PROSE_ACTIONS: dict[str, dict] = {
    "Extreme-Cold Fungus": {
        "detail": "gain 1 plant, or 2 microbes to ANOTHER card"},
    "Power Infrastructure": {
        "cost": {"energy": "@mcGained"}, "min": {"energy": 1}, "gain": "mc",
        "detail": "spend any amount of energy → that many MC"},
    "Search For Life": {
        "cost": {"mc": 1}, "detail": "1 MC: reveal the top card; microbe tag → "
                                     "a science resource here"},
    UNMI: {"cost": {"mc": 3}, "tr": 1,
           "detail": "3 MC → +1 TR, only if TR was raised this "
                     "generation (not tracked — check)"},
    # look-and-buy: TAKING the action costs nothing (you may discard what
    # you see), so it stays a free action for the pass gate; the MC is the
    # price of KEEPING the card, which is not part of the behavior.
    "Business Network": {
        "detail": f"look at the top card: buy ({CARD_KEEP_COST} MC) or discard"},
    "Inventors' Guild": {
        "detail": f"look at the top card: buy ({CARD_KEEP_COST} MC) or discard"},
}
# card-table: end

# Adaptation Technology / Inventrix widen every global requirement ±2 steps
# — both are vendor hooks, kept in tmlib's two card tables.
REQ_WIDENERS = tmlib.REQUIREMENT_WIDENERS

_TAG_REQ = re.compile(r"^(\d+)\s+([a-z]+)\s+tags?$", re.IGNORECASE)
_MULTI_TAG_REQ = re.compile(r"^(?:\d+\s+[a-z]+\s+tags?)(?:,\s*\d+\s+[a-z]+\s+tags?)+$",
                            re.IGNORECASE)
_CITIES_REQ = re.compile(r"^min\s+(\d+)\s+cit", re.IGNORECASE)
_GREENERY_REQ = re.compile(r"^min\s+(\d+)\s+greener", re.IGNORECASE)


# ── state accessors (fog-tolerant: missing fields read as zero) ──────────
# Pools come from tmlib (player_pool / all_pools / _zeros) — one lookup.

def _res(pool: dict) -> dict:
    return {**_zeros(), **(pool.get("resources") or {})}


def _prod(pool: dict) -> dict:
    return {**_zeros(), **(pool.get("production") or {})}


def _tiles(pool: dict) -> dict:
    return {"cities": 0, "greeneries": 0, "special": 0, **(pool.get("tiles") or {})}


def _db(db: dict | None) -> dict:
    if db is not None:
        return db
    try:
        return cardlib.load_db()
    except FileNotFoundError:
        return {"cards": []}


def _card(name: str, db: dict) -> dict | None:
    try:
        return cardlib.find(name, db)
    except Exception:
        return None


def tag_counts(game: dict, name: str, db: dict | None = None) -> dict:
    """Persisting tags of a player — THE tag counter
    (`tmlib.persisting_tags`): played cards minus events, plus the
    corporation's own tags (Mining Guild = 2 building), falling back to the
    tracked tagCounts for an opponent whose tableau is unknown."""
    return tmlib.persisting_tags(game, name, _db(db))


def _played_names(pool: dict) -> set[str]:
    return {str(e.get("name", "")).lower() for e in pool.get("playedCards") or []}


# ── card pricing: the ONLY price model is the engine's
# (tmlib.Engine.price / standard_price — cardDiscount read from the db,
# NEXT_CARD_DISCOUNT + the CrediCor rebate from tmlib's corporations
# table). The menu quotes exactly what `play` / `standard` charge; the
# notes name every source so a mismatch with the app/table is visible.

def _rebate_note(quote: dict) -> str:
    return f"CrediCor +{quote['rebate']} MC rebate" if quote.get("rebate") else ""


def affordable(game: dict, cost: int) -> bool:
    """Can I put `cost` MC on the table right now? THE splitter's rule —
    MC plus heat for a heat-as-MC corporation — asked once, so a milestone,
    an award and a standard project never disagree about the same wallet."""
    return split_payment(game, game["me"].get("name") or "", cost,
                         pool=game["me"])["shortfall"] == 0


def payment(cost: int, res: dict, tags: list | None, corp: str | None,
            allow_steel: bool | None = None,
            allow_ti: bool | None = None) -> tuple[bool, str]:
    """Can the cost be covered by MC + steel (building) + titanium (space) +
    heat (a heat-as-MC corporation)? Returns (affordable, 'pay …' text).

    The mix is THE splitter's (`tmlib.split_payment`), never the menu's own
    arithmetic — the menu quotes exactly what `play`/`standard` charge and
    what the executor sends the app. allow_steel/allow_ti override the tag
    rule for the callers that price a non-card (a standard project).
    """
    tags = list(tags or [])
    use_steel_ok = allow_steel if allow_steel is not None else "building" in tags
    use_ti_ok = allow_ti if allow_ti is not None else "space" in tags
    heat_ok = bool(tmlib.corp_rule(corp, "heatAsMC"))
    pay = split_payment(None, "", cost,
                        pool={"resources": res, "corporation": corp},
                              tags=(["building"] if use_steel_ok else [])
                                   + (["space"] if use_ti_ok else []))
    if pay["shortfall"]:
        return False, (f"needs {cost} MC — have {res['mc']} MC"
                       + (f" + {res['steel']} steel" if use_steel_ok else "")
                       + (f" + {res['titanium']} Ti" if use_ti_ok else "")
                       + (f" + {res['heat']} heat" if heat_ok else ""))
    parts = []
    if pay["steel"]:
        parts.append(f"{pay['steel']} steel")
    if pay["titanium"]:
        parts.append(f"{pay['titanium']} Ti")
    if pay["mc"] or not parts:
        parts.append(f"{pay['mc']} MC")
    if pay["heat"]:
        parts.append(f"{pay['heat']} heat")
    return True, "pay " + " + ".join(parts)


# ── requirement windows ──────────────────────────────────────────────────

def _widened(game: dict, db: dict) -> bool:
    me = game["me"]
    if tmlib.corp_rule(me.get("corporation"), "widensRequirements"):
        return True
    played = _played_names(me)
    return any(w.lower() in played for w in REQ_WIDENERS)


def requirement_check(req: str | None, game: dict, db: dict,
                      widened: bool = False) -> tuple[bool | None, str]:
    """(ok, detail) for a db requirement string against state. ok=None →
    the harness cannot judge it (list the card, say so). `widened` = the
    player has Inventrix / Adaptation Technology (global thresholds ±2
    steps, their choice)."""
    if not req:
        return True, ""
    req = req.strip()
    g = game["globals"]
    m = research._REQ.match(req)
    if m:
        kind, val, unit = m.group(1).lower(), int(m.group(2)), m.group(3).lower()
        if "o2" in unit:
            param = "oxygen"
        elif "°c" in unit:
            param = "temperature"
        elif "ocean" in unit:
            param = "oceans"
        else:
            param = None
        if param:
            cur = g[param]
            unit_s = PARAM_SCALE[param]["unit"]
            slack = 2 * PARAM_SCALE[param]["step"] if widened else 0
            if kind == "min":
                ok = cur >= val - slack
            else:
                ok = cur <= val + slack
            tail = f"{req} ✓ (now {cur}{unit_s}" + (", ±2 window)" if widened else ")")
            if not ok:
                tail = f"{req} ✗ (now {cur}{unit_s})"
            return ok, tail
    me = game["me"]
    tags = tag_counts(game, me["name"], db)
    m = _TAG_REQ.match(req)
    if m:
        n, tag = int(m.group(1)), m.group(2).lower()
        have = tags.get(tag, 0)
        return have >= n, f"{req} {'✓' if have >= n else '✗'} (have {have})"
    if _MULTI_TAG_REQ.match(req):
        oks = []
        for part in req.split(","):
            mm = _TAG_REQ.match(part.strip())
            oks.append(tags.get(mm.group(2).lower(), 0) >= int(mm.group(1)))
        return all(oks), f"{req} {'✓' if all(oks) else '✗'}"
    m = _CITIES_REQ.match(req)
    if m:
        n = int(m.group(1))
        have = tmlib.cities_in_play(game)
        return have >= n, f"{req} {'✓' if have >= n else '✗'} (in play {have})"
    m = _GREENERY_REQ.match(req)
    if m:
        n = int(m.group(1))
        have = tmlib.tile_counts(game, me["name"], me)["greeneries"]
        return have >= n, f"{req} {'✓' if have >= n else '✗'} (have {have})"
    low = req.lower()
    if low.endswith("production"):
        r = low.replace("production", "").strip()
        if r in RESOURCES:
            have = _prod(me)[r]
            return have > 0, f"{req} {'✓' if have > 0 else '✗'} ({have})"
    return None, f"requirement not machine-checked: {req}"


# ── card playability ─────────────────────────────────────────────────────

def _production_legal(behavior: dict | None, game: dict) -> tuple[bool, str]:
    """Plain-int production deltas must respect the floors (MC −5, else 0);
    'decrease any production' needs a player with that much."""
    if not behavior:
        return True, ""
    me = game["me"]
    prod = _prod(me)
    alias = {"megacredits": "mc"}
    for r, d in (behavior.get("production") or {}).items():
        r = alias.get(r, r)
        if r in RESOURCES and isinstance(d, int) and d < 0:
            floor = -5 if r == "mc" else 0
            if prod[r] + d < floor:
                return False, f"{r} production {prod[r]}{d:+} < floor {floor}"
    dec = behavior.get("decreaseAnyProduction")
    if isinstance(dec, dict):
        r = alias.get(dec.get("type"), dec.get("type"))
        n = dec.get("count", 1)
        if r in RESOURCES and isinstance(n, int):
            if not any(_prod(p)[r] >= n for _, p in all_pools(game)):
                return False, f"nobody has {n} {r} production to decrease"
    return True, ""


def _card_item(name: str, game: dict, db: dict, widened: bool) -> dict | None:
    me, res = game["me"], _res(game["me"])
    corp = me.get("corporation")
    info = _card(name, db)
    if info is None:
        ok, pay = payment(0, res, [], corp)
        return {"kind": "card", "name": name, "label": f"play {name}",
                "cost": None, "ok": True,
                "detail": "NOT IN DB — check cost/requirements manually"}
    if info.get("type") == "corporation":
        return None
    quote = tmlib.Engine.price(game, me["name"], info)
    cost, notes = quote["price"], list(quote["notes"])
    if _rebate_note(quote):
        notes.append(_rebate_note(quote))
    ok, pay = payment(cost, res, info.get("tags"), corp)
    if not ok:
        return None
    req_ok, req_detail = requirement_check(info.get("requirements"), game, db,
                                           widened)
    if req_ok is False:
        return None
    beh = info.get("behavior") or {}
    branches = []
    if isinstance(beh.get("or"), dict):
        branches = (beh["or"] or {}).get("behaviors") or []
        legal = []
        for i, b in enumerate(branches):
            merged = {k: v for k, v in beh.items() if k != "or"}
            merged.update({k: v for k, v in b.items() if k != "title"})
            legal.append(_production_legal(merged, game)[0])
        if branches and not any(legal):
            return None
    else:
        legal_ok, why = _production_legal(beh, game)
        if not legal_ok:
            return None
    tile_ok, _why = _tile_playable(info, game)
    if not tile_ok:
        return None
    parts = [pay + (f" ({', '.join(notes)})" if notes else "")]
    if req_detail:
        parts.append(req_detail)
    if branches:
        parts.append("or-choice: " + " / ".join(
            f"choice={i} {b.get('title') or json.dumps({k: v for k, v in b.items() if k != 'title'})}"
            for i, b in enumerate(branches)))
    tags = ", ".join(info.get("tags") or []) or "no tags"
    parts.append(f"[{info.get('type')}; {tags}]")
    if info.get("bespoke"):
        parts.append("BESPOKE — read the card text")
    return {"kind": "card", "name": info["name"], "label": f"play {info['name']}",
            "cost": cost, "ok": True, "detail": " · ".join(parts)}



# ── tile placement feasibility (live e2e finding) ────────────────────────
# A tile card is playable only if a legal hex exists NOW. Cards whose db
# entry has no tile behavior but which place a tile with a special rule are
# listed here by name.
_NAMED_TILE_RULES = {
    "mining area": "adjacent_own_metal",     # own non-ocean tile, adjacent hex with steel/ti bonus
    "mining rights": "metal",                # any free hex with steel/ti bonus
}


def _tile_playable(info: dict, game: dict) -> tuple[bool, str]:
    from tmlib import Engine
    board = Engine._board()
    occupied = game.get("board", {}) or {}
    me = game["me"]["name"]
    beh = info.get("behavior") or {}
    rule = _NAMED_TILE_RULES.get(info["name"].lower())
    on = (beh.get("tile") or {}).get("on") if isinstance(beh.get("tile"), dict) else None
    if rule is None and on is None:
        return True, ""
    free = {sid: sp for sid, sp in board.items()
            if not sp.get("offMap") and sid not in occupied}
    def metal(sp):
        return any(b in ("steel", "titanium") for b in sp.get("bonus", []))
    if rule == "metal":
        ok = any(metal(sp) and not sp.get("oceanReserved") for sp in free.values())
        return ok, "no free steel/titanium hex"
    if rule == "adjacent_own_metal":
        own = {sid for sid, t in occupied.items()
               if t.get("player") == me and t.get("tile") != "ocean"}
        ok = any(metal(sp) and not sp.get("oceanReserved")
                 and any(a in own for a in sp.get("adjacent", []))
                 for sp in free.values())
        return ok, "no own tile with a free adjacent steel/titanium hex"
    if on == "ocean":
        ok = any(sp.get("oceanReserved") for sp in free.values())
        return ok, "no free ocean slot"
    if on == "volcanic":
        names = {"tharsis tholus", "ascraeus mons", "pavonis mons", "arsia mons"}
        ok = any((sp.get("name") or "").lower() in names for sp in free.values())
        return ok, "no free volcanic hex"
    if on == "isolated":
        ok = any(not sp.get("oceanReserved")
                 and not any(a in occupied for a in sp.get("adjacent", []))
                 for sp in free.values())
        return ok, "no isolated hex left"
    if on in ("land", "city"):
        ok = any(not sp.get("oceanReserved") for sp in free.values())
        return ok, "board full"
    return True, ""

# ── blue-card action availability, derived from the db ───────────────────
# An action is listed when at least one branch of its `actionBehavior` can
# be PAID now and still DOES something (a global raise at the cap does not).
# The 35-entry hand table this replaced went stale every time a new card
# reached the table; the vendor's own action data cannot.

class _S:
    """Snapshot the availability derivation reads."""

    def __init__(self, game: dict, free_land: int):
        me = game["me"]
        self.res = _res(me)
        self.prod = _prod(me)
        self.globals = game["globals"]
        self.corp = me.get("corporation")
        self.heat_as_mc = bool(tmlib.corp_rule(self.corp, "heatAsMC"))
        self.card_res = me.get("cardResources") or {}
        self.free_land = free_land
        self.oceans_left = PARAM_SCALE["oceans"]["max"] - game["globals"]["oceans"]
        self.o2_left = PARAM_SCALE["oxygen"]["max"] - game["globals"]["oxygen"]
        self.temp_left = PARAM_SCALE["temperature"]["max"] - game["globals"]["temperature"]

    def cash(self) -> int:
        return self.res["mc"] + (self.res["heat"] if self.heat_as_mc else 0)


def _param_left(s: _S, param: str) -> int:
    return PARAM_SCALE[param]["max"] - s.globals[param]


def _spend_payable(spend: dict, card: str, s: _S) -> tuple[bool, int, str]:
    """(payable, MC part of the price, why-not) for one `spend` block."""
    mc_due = 0
    for key, val in spend.items():
        if key in ("canUseSteel", "canUseTitanium") or not isinstance(val, int):
            continue
        if key == "resourcesHere":
            have = s.card_res.get(card, 0)
            if have < val:
                return False, 0, f"needs {val} on the card (have {have})"
            continue
        r = SPEND_RESOURCES.get(key)
        if r is None:
            continue
        if r == "mc":
            pot = s.cash()
            if spend.get("canUseSteel"):
                pot += s.res["steel"] * STEEL_VALUE
            if spend.get("canUseTitanium"):
                pot += s.res["titanium"] * TITANIUM_VALUE
            if pot < val:
                return False, val, f"needs {val} MC (have {pot})"
            mc_due = val
        elif s.res[r] < val:
            return False, mc_due, f"needs {val} {r} (have {s.res[r]})"
    return True, mc_due, ""


def _effect_alive(branch: dict, s: _S) -> bool:
    """Does the branch still DO something? A global raise at the cap and an
    ocean with none left are dead; a branch that also gains a resource is
    not. A production DECREASE the player cannot pay for is impossible."""
    for r, d in (branch.get("production") or {}).items():
        r = SPEND_RESOURCES.get(r, r)
        floor = -5 if r == "mc" else 0
        if isinstance(d, int) and d < 0 and s.prod.get(r, 0) + d < floor:
            return False
    gains = {k: v for k, v in branch.items()
             if k not in ("spend", "title", "index", "textOrder")}
    if not gains:
        return True
    dead = 0
    for key, val in gains.items():
        if key == "global" and isinstance(val, dict):
            if all(_param_left(s, p) <= 0 for p in val if p in PARAM_SCALE):
                dead += 1
        elif key == "ocean" and s.oceans_left <= 0:
            dead += 1
        elif key == "greenery" and s.free_land <= 0:
            dead += 1
    return dead < len(gains)


def _behavior_action(info: dict, s: _S) -> tuple[bool, str, int] | None:
    """(available, detail, MC cost) from the card's `actionBehavior`, or
    None when the db has no structured action for it."""
    beh = info.get("actionBehavior")
    if not isinstance(beh, dict):
        return None
    card = info["name"]
    inner = beh.get("or")
    branches = (tmlib.or_branches(info, behavior=beh, text=info.get("action"))
                if isinstance(inner, dict) else [beh])
    costs, whynot = [], []
    for b in branches:
        payable, mc_due, why = _spend_payable(b.get("spend") or {}, card, s)
        if not payable:
            whynot.append(why)
            continue
        if not _effect_alive(b, s):
            whynot.append("nothing left to raise")
            continue
        costs.append(mc_due)
    detail = (info.get("action") or "").strip()
    if not costs:
        return False, "; ".join(whynot) or detail, 0
    return True, detail, min(costs)


def prose_cost(spec: dict, mc_gained: int = 0) -> dict:
    """{resource: amount} an action in PROSE_ACTIONS costs — resolving the
    "@mcGained" variable spend against the MC the app's log shows arriving.
    The menu prices the action with it; the replayer charges it."""
    out = {}
    for r, n in (spec.get("cost") or {}).items():
        out[r] = mc_gained if n == "@mcGained" else int(n)
    return out


def _prose_action(canon: str, spec: dict, s: _S) -> tuple[bool, str, int]:
    """The handful of actions PROSE_ACTIONS covers."""
    need = {**prose_cost(spec), **(spec.get("min") or {})}
    mc = need.get("mc", 0)
    if mc and s.cash() < mc:
        return False, f"needs {mc} MC (have {s.cash()})", mc
    energy = need.get("energy", 0)
    if energy and s.res["energy"] < energy:
        return False, f"needs {energy} energy (have {s.res['energy']})", mc
    return True, spec["detail"], mc


def _action_items(game: dict, db: dict, free_land: int) -> list[dict]:
    me = game["me"]
    ledger = me.get("actionsThisGen") or {}
    s = _S(game, free_land)
    out = []
    seen = set()
    for key, entry in ledger.items():
        seen.add(key.lower())
        if (entry or {}).get("used"):
            continue
        item = _one_action(key, entry or {}, s, db)
        if item:
            out.append(item)
    # played active cards with an action that never reached the ledger:
    # the menu is derived from state, and playedCards IS state — surface
    # them flagged rather than hide a possibly-open action.
    for entry in me.get("playedCards") or []:
        info = _card(entry.get("name", ""), db)
        if not info or info.get("type") != "active" or not info.get("action"):
            continue
        if info["name"].lower() in seen:
            continue
        seen.add(info["name"].lower())
        item = _one_action(info["name"], {}, s, db)
        if item:
            item["detail"] += " · ⚠ not in ledger (use this gen unknown) — apply.py action register/use"
            out.append(item)
    corp = me.get("corporation") or ""
    boost = tmlib.corp_rule(corp, "trBoostCost")
    if boost and UNMI.lower() not in seen and s.cash() >= boost:
        ok, detail, cost = _prose_action(UNMI, PROSE_ACTIONS[UNMI], s)
        out.append({"kind": "action", "name": UNMI, "label": "UNMI action",
                    "cost": cost, "ok": True, "detail": detail})
    return out


def _one_action(name: str, entry: dict, s: _S, db: dict) -> dict | None:
    info = _card(name, db)
    canon = info["name"] if info else name
    spec = PROSE_ACTIONS.get(canon)
    derived = None
    if spec is not None:
        derived = _prose_action(canon, spec, s)
    elif info is not None:
        derived = _behavior_action(info, s)
    if derived is not None:
        ok, detail, cost = derived
        if not ok:
            return None
        if entry.get("mcCost") is not None:
            cost = entry["mcCost"]
    else:
        # a card the db does not know: fall back to the ledger's parsed
        # costs, else list it open with the prereq flagged
        mc_cost, heat_cost = entry.get("mcCost", 0), entry.get("heatCost", 0)
        if isinstance(mc_cost, int) and mc_cost > s.cash():
            return None
        if isinstance(heat_cost, int) and heat_cost > s.res["heat"]:
            return None
        cost = entry.get("mcCost") or 0
        detail = ((info or {}).get("action") or "prereq unknown") + \
            " · prereq unknown"
    return {"kind": "action", "name": canon, "label": f"{canon} action",
            "cost": cost, "ok": True, "detail": detail}


# ── standard projects, milestones, awards, conversions ───────────────────

def _standard_items(game: dict, free_land: int) -> list[dict]:
    me, res = game["me"], _res(game["me"])
    corp = me.get("corporation") or ""
    g = game["globals"]
    out = []
    if me.get("hand"):
        out.append({"kind": "standard", "name": "sell_patents",
                    "label": "sell patents", "cost": 0, "ok": True,
                    "detail": f"{len(me['hand'])} card(s) × 1 MC — endgame cash only"})
    for proj in STANDARD_PROJECTS:
        if proj == "sell_patents":
            continue
        quote = tmlib.Engine.standard_price(game, me["name"], proj)
        cost = quote["price"]
        detail = ", ".join(quote["notes"])
        # ZERO-EFFECT on a full track: the asteroid is a temperature step
        # and nothing else, and with 9/9 oceans the app suppresses the
        # aquifer's TILE too ("oceans maxed at 9/9 — the ocean is
        # SUPPRESSED") — both buy nothing, so neither is an action. The
        # greenery below keeps its tile (VP) and stays on the menu, just
        # degraded. execute.py runs the same rule pre-send, because the
        # track can fill between plan time and execution.
        if proj == "asteroid" and g["temperature"] >= PARAM_SCALE["temperature"]["max"]:
            continue
        if proj == "aquifer" and g["oceans"] >= PARAM_SCALE["oceans"]["max"]:
            continue
        if proj in ("greenery", "city") and free_land <= 0:
            continue
        if proj == "greenery" and g["oxygen"] >= PARAM_SCALE["oxygen"]["max"]:
            detail = "O2 maxed: tile VP only, no TR"
        if not affordable(game, cost):
            continue
        if _rebate_note(quote):
            detail = (detail + " · " if detail else "") + _rebate_note(quote)
        gain = {"power_plant": "+1 energy prod", "asteroid": "+1 temp, +1 TR",
                "aquifer": "ocean, +1 TR", "greenery": "greenery tile, +1 O2/TR",
                "city": "city tile, +1 MC prod"}[proj]
        out.append({"kind": "standard", "name": proj, "label": f"SP {proj}",
                    "cost": cost, "ok": True,
                    "detail": gain + (f" · {detail}" if detail else "")})
    return out


def milestone_metrics(game: dict, name: str, db: dict | None = None) -> dict:
    """{'Terraformer': TR, 'Mayor': cities, 'Gardener': greeneries,
    'Builder': building tags, 'Planner': hand size or None (opponents)}."""
    pool = player_pool(game, name)
    tiles = tmlib.tile_counts(game, name, pool)     # THE tile counter
    me = name == game["me"].get("name")
    hand = len(pool.get("hand") or []) if me else pool.get("handSize")
    return {"Terraformer": pool.get("tr", 0), "Mayor": tiles["cities"],
            "Gardener": tiles["greeneries"],
            "Builder": tag_counts(game, name, db).get("building", 0),
            "Planner": hand if isinstance(hand, int) else None}


def _milestone_items(game: dict, db: dict) -> list[dict]:
    me, res = game["me"], _res(game["me"])
    claimed = game.get("milestonesClaimed") or {}
    if len(claimed) >= MAX_MILESTONES:
        return []
    if not affordable(game, MILESTONE_COST):
        return []
    metrics = milestone_metrics(game, me["name"], db)
    out = []
    for ms in MILESTONES:
        if ms in claimed:
            continue
        have = metrics[ms]
        if have is not None and have >= MILESTONE_NEED[ms]:
            out.append({"kind": "milestone", "name": ms,
                        "label": f"claim {ms}", "cost": MILESTONE_COST,
                        "ok": True,
                        "detail": f"{MILESTONE_METRIC[ms]} {have}/{MILESTONE_NEED[ms]} "
                                  f"— 5 VP for {MILESTONE_COST} MC, "
                                  f"{MAX_MILESTONES - len(claimed)} slot(s) left"})
    return out


def award_metrics(game: dict, name: str, db: dict | None = None) -> dict:
    """{'Landlord': tiles, 'Banker': MC prod, 'Scientist': science tags,
    'Thermalist': heat, 'Miner': steel+titanium} — THE award metric
    (`tmlib.award_metrics`), the same one score.py ranks with."""
    return tmlib.award_metrics(game, name, _db(db))


# ── award LOCK test ──────────────────────────────────────────────────────
# strategy/04-card-tiers.md: "award funding is a LOCK test, not a lead
# test: fund only when no rival's reachable max (incl. last-gen production
# cards) beats you"; strategy/02 says the same and adds the failure it
# invites (Banker funded gen 2, flipped by a gen-10 Zeppelins: 8 MC bought
# 2 VP, not 5). So a lead is priced against every rival's REACHABLE max by
# the last generation: their metric now + ~1 step per generation still to
# play (02 race margins: assume ~1 step of progress per unobserved
# opponent turn) + what their UNSPENT M€ buys on the cash-convertible
# metrics, all capped at 2 actions per generation.
CASH_PER_STEP = {"Landlord": 23, "Banker": 10}   # greenery SP; ~1 MC prod
ACTIONS_PER_GEN = 2


def gens_left(game: dict, setup: dict | None = None) -> int:
    """Generations still to play AFTER this one — clock.py's estimate (a
    table-declared final generation or maxed parameters → 0)."""
    import clock
    setup = setup or {}
    history = [h for h in game.get("history") or []
               if h.get("generation", 0) < game["generation"] - 1]
    est = clock.estimate(game["globals"], game["generation"],
                         players=setup.get("playerCount") or 5,
                         declared_final=game.get("declaredFinalGeneration"),
                         history=history, wgt=tmlib.wgt_enabled(setup))
    return est["gensLeft"]


def award_lock(game: dict, award: str, setup: dict | None = None,
               db: dict | None = None, gens: int | None = None) -> dict:
    """LOCK test for one award: can the metric still be taken from me?
    {'lockable', 'why', 'my', 'best', 'reachBy', 'reach', 'gensLeft'} —
    lockable only when my metric beats every rival's reachable max."""
    db = _db(db)
    if gens is None:
        gens = gens_left(game, setup)
    turns = gens + 1                       # this generation still has actions
    my = award_metrics(game, game["me"]["name"], db).get(award) or 0
    per_step = CASH_PER_STEP.get(award)
    best = (None, 0)
    top: dict | None = None
    for n in (game.get("opponents") or {}):
        now = award_metrics(game, n, db).get(award) or 0
        cash = _res(player_pool(game, n))["mc"]
        growth = min(turns + (cash // per_step if per_step else 0),
                     ACTIONS_PER_GEN * turns)
        row = {"name": n, "now": now, "growth": growth, "reach": now + growth,
               "cash": cash}
        if best[0] is None or now > best[1]:
            best = (n, now)
        if top is None or row["reach"] > top["reach"]:
            top = row
    if top is None:
        return {"lockable": False, "my": my, "best": (None, 0), "reachBy": None,
                "reach": 0, "gensLeft": gens,
                "why": "no opponents tracked — the lock cannot be priced"}
    horizon = ("final generation" if gens == 0 else f"{gens} gen(s) left")
    bank = (f", {top['cash']} MC unspent ≈ +{top['cash'] // per_step}"
            if per_step and top["cash"] >= per_step else "")
    lockable = my > top["reach"]
    return {"lockable": lockable, "my": my, "best": best,
            "reachBy": top["name"], "reach": top["reach"], "gensLeft": gens,
            "why": f"mine {my} vs {top['name']} {top['now']} reachable "
                   f"+{top['growth']} = {top['reach']} ({horizon}{bank}) — "
                   + ("LOCKABLE" if lockable else "not lockable")}


def _award_items(game: dict, db: dict, setup: dict | None = None) -> list[dict]:
    me, res = game["me"], _res(game["me"])
    funded = game.get("awardsFunded") or {}
    if len(funded) >= len(AWARD_COSTS):
        return []
    price = AWARD_COSTS[len(funded)]
    if not affordable(game, price):
        return []
    mine = award_metrics(game, me["name"], db)
    opp_metrics = {n: award_metrics(game, n, db) for n in (game.get("opponents") or {})}
    gens = gens_left(game, setup)
    out = []
    for a in AWARDS:
        if a in funded:
            continue
        my = mine[a] or 0
        best_name, best = None, -1
        for n, m in opp_metrics.items():
            v = m[a] or 0
            if v > best:
                best_name, best = n, v
        lock = award_lock(game, a, setup, db, gens=gens)
        if best_name is None:
            status = "no opponents tracked"
        elif my > best:
            status = (f"LEADING by {my - best}"
                      + (" (LOCKABLE)" if lock["lockable"] else " (lead only)"))
        elif my == best:
            status = "TIED"
        else:
            status = f"trailing by {best - my}"
        out.append({"kind": "award", "name": a, "label": f"fund {a}",
                    "cost": price, "ok": True,
                    "detail": f"{me['name']} {my} vs best opp "
                              f"{best_name or '—'} {max(best, 0)} — {status}; "
                              f"lock test: {lock['why']}; "
                              f"slot {len(funded) + 1} costs {price} MC"})
    return out


def _convert_items(game: dict, free_land: int) -> list[dict]:
    me, res = game["me"], _res(game["me"])
    g = game["globals"]
    out = []
    if res["heat"] >= 8 and g["temperature"] < PARAM_SCALE["temperature"]["max"]:
        out.append({"kind": "convert", "name": "heat", "label": "8 heat → temperature",
                    "cost": 8, "ok": True,
                    "detail": f"have {res['heat']} heat — +1 temp, +1 TR"})
    need = tmlib.greenery_plant_cost(me.get("corporation"))
    if res["plants"] >= need and free_land > 0:
        maxed = g["oxygen"] >= PARAM_SCALE["oxygen"]["max"]
        out.append({"kind": "convert", "name": "plants",
                    "label": f"{need} plants → greenery", "cost": need, "ok": True,
                    "detail": f"have {res['plants']} plants — "
                              + ("O2 maxed: tile VP only, no TR"
                                 if maxed else "+1 O2, +1 TR, +1 VP tile")})
        warn = _plant_exposure(game, res, need)
        if warn:
            out.append(warn)
    return out


# A plant hoard is not an action — it is a WARNING item (kind 'warning'),
# so the pass gate, the menu block and every GO line carry it. strategy/02:
# "convert the turn you reach 8 and never carry 8+ plants (7 at 2+ plant
# prod) across an opponent's turn when asteroid holders sit at the table"
# (observed: 9 plants held into the opponents' turns, Deimos Down removed
# 8 ≈ 19 MC of greenery; an Asteroid took 3 more two generations later).

def _plant_exposure(game: dict, res: dict, need: int) -> dict | None:
    plants = res["plants"]
    prod = _prod(game["me"])["plants"]
    if plants < 8 and not (plants >= 7 and prod >= 2):
        return None
    return {"kind": "warning", "name": "plant_exposure",
            "label": f"⚠ {plants} plants exposed to removal — convert NOW",
            "cost": None, "ok": True,
            "detail": f"{plants} plants (+{prod} prod) carried across the "
                      f"opponents' turns is one Asteroid / Deimos Down from "
                      f"gone (≈ 2 VP + 1 TR per denied greenery) — convert "
                      f"{need} plants → greenery this turn; price the risk "
                      f"with scripts/odds.py removal"}


# ── public API ───────────────────────────────────────────────────────────

def available_actions(game: dict, setup: dict | None = None,
                      db: dict | None = None,
                      free_land: int | None = None) -> list[dict]:
    """Everything the player can do RIGHT NOW, from state only. Items whose
    prerequisites fail are not listed. `free_land` overrides the tracker's
    board count (app modes pass the exact number)."""
    db = _db(db)
    if free_land is None:
        try:
            free_land = tmlib.free_land(tmlib.occupied_space_ids(game))
        except Exception:
            free_land = 1
    widened = _widened(game, db)
    items: list[dict] = []
    for name in game["me"].get("hand") or []:
        it = _card_item(name, game, db, widened)
        if it:
            items.append(it)
    items += _action_items(game, db, free_land)
    items += _standard_items(game, free_land)
    items += _milestone_items(game, db)
    items += _award_items(game, db, setup)
    items += _convert_items(game, free_land)
    return items


def _short(it: dict) -> str:
    cost = f" ({it['cost']})" if isinstance(it.get("cost"), int) and it["cost"] else ""
    if it["kind"] == "card":
        return f"play {it['name']}{cost}"
    if it["kind"] == "action":
        return f"{it['name']} action{cost}"
    if it["kind"] == "standard":
        return "sell patents" if it["name"] == "sell_patents" else f"SP {it['name']}{cost}"
    if it["kind"] == "milestone":
        return f"claim {it['name']}{cost}"
    if it["kind"] == "award":
        return f"fund {it['name']}{cost}"
    return it["label"]


def summary(items: list[dict]) -> str:
    """One line for every GO message: 'available: …, pass' — warnings ride
    at the end (they are not actions, and the line still starts with the
    menu the executor reads)."""
    warn = [i["label"] for i in items if i["kind"] == "warning"]
    acts = [i for i in items if i["kind"] != "warning"]
    line = ("available: " + ", ".join(_short(i) for i in acts) + ", pass"
            if acts else "available: nothing — pass is legal")
    return line + (" · " + " · ".join(warn) if warn else "")


def used_actions(game: dict) -> list[str]:
    return [k for k, e in (game["me"].get("actionsThisGen") or {}).items()
            if (e or {}).get("used")]


def render(items: list[dict], game: dict, app: dict | None = None) -> str:
    """The AVAILABLE ACTIONS block (brief + CLI). `app` = my /api/player
    payload when available: its availableBlueCardActionCount vs the ledger
    catches an un-logged `action use`."""
    res = _res(game["me"])
    lines = [f"## AVAILABLE ACTIONS (engine-derived — the app's menu, from state; "
             f"💰 {res['mc']} MC · steel {res['steel']} · Ti {res['titanium']} · "
             f"🌱 {res['plants']} · 🔥 {res['heat']} · ⚡ {res['energy']})"]
    if not items:
        lines.append("(nothing available — pass is legal)")
    order = ("warning", "card", "action", "convert", "milestone", "award",
             "standard")
    for kind in order:
        for it in items:
            if it["kind"] != kind:
                continue
            if kind == "warning":
                lines.append(f"{it['label']} — {it['detail']}")
                continue
            cost = f"{it['cost']} MC" if isinstance(it.get("cost"), int) else "?"
            if it["kind"] == "convert":
                cost = f"{it['cost']} {it['name']}"
            lines.append(f"▢ {it['label']} — {cost} — {it['detail']}")
    used = used_actions(game)
    if used:
        lines.append(f"✓ used this generation: {', '.join(used)}")
    n_app = ((app or {}).get("thisPlayer") or {}).get("availableBlueCardActionCount")
    n_ledger = sum(1 for i in items if i["kind"] == "action")
    if isinstance(n_app, int) and n_app < n_ledger:
        lines.append(f"⚠ ledger drift: app offers {n_app} blue action(s), the "
                     f"menu lists {n_ledger} — a use was not logged "
                     "(`action use …`) or a prerequisite the table does not "
                     "track; trust the app")
    lines.append(summary(items))
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Print the engine-derived "
                                "AVAILABLE ACTIONS menu for the active game.")
    p.add_argument("--root", default=".", help="repo root (state/ = active game)")
    p.add_argument("--state", default=None,
                   help="a game folder (games/<date>-gameN) instead of state/")
    p.add_argument("--json", action="store_true", help="items as JSON")
    a = p.parse_args(argv)
    store = tmlib.Store(a.root, state_dir=a.state)
    try:
        game, setup = store.load_game(), store.load_setup()
    except FileNotFoundError as e:
        print(f"ERROR: {e} — is a game active?", file=sys.stderr)
        return 1
    items = available_actions(game, setup)
    if a.json:
        print(json.dumps(items, indent=2, ensure_ascii=False))
    else:
        print(render(items, game))
    return 0


if __name__ == "__main__":
    sys.exit(main())
