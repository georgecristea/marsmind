#!/usr/bin/env python3
"""One-shot research-phase evaluator.

Collapses the table-hot research plumbing — card lookup, requirement
windows vs the clock, production payback, canonical prices — into ONE
call. The advisor keeps only the judgment layer (synergy, threats,
budget, keep/reject), per skills/research-phase.

    python3 scripts/research.py "Card A" "Card B" "Card C" "Card D"

Draft fast path: 2-4 names with no --tableau/--hand/
--resources (or --quick) print ONE compact line per card — cost+keep,
window vs the live clock, payback or VP density, verdict tag — in well
under a second. --full forces the long report.

ONE clock: the generation estimate comes from clock.estimate with
the same inputs advise.py / clock.py use (player count from setup.json
or the opponent count, start-of-generation history, table-declared
final generation) — never a private estimator.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cards
import clock
import payback
import tmlib          # free_land / occupied_space_ids hook
from tmlib import PARAM_SCALE

# canonical MC prices (strategy/04, incl. 3 MC keep)
PRICE = {"temperature": 10, "oceans": 14, "oxygen": 10, "tr": 10, "vp": 5}

# One-shot (windfall) resources — strategy/04 "1 plant = 1 steel =
# 1 titanium = 1 card = 2 heat = 2 MC", strategy/01 confirms the 2 MC
# opportunity rate. NOT the build value of steel/titanium (2/3 MC) and not
# the per-generation production rate (payback.MC_PER_GEN).
WINDFALL = {"mc": 1, "steel": 2, "titanium": 2, "plants": 2, "heat": 1,
            "energy": 1, "cards": 2}

# display names for a production requirement message
_PRODNAME = {"mc": "MC", "steel": "steel", "titanium": "titanium",
             "plants": "plant", "energy": "energy", "heat": "heat"}

_PRODKEY = {"megacredits": "mc", "mc": "mc", "steel": "steel",
            "titanium": "titanium", "plants": "plants", "heat": "heat",
            "energy": "energy"}

_REQ = re.compile(r"^(min|max)\s+(-?\d+)\s*(%\s*O2|°C|oceans?|greener\w*)",
                  re.IGNORECASE)

# Non-global requirement clauses (D10 gate). Tag counts ("2 science tags",
# "1 plant tag, 1 animal tag, 1 microbe tag"), a production floor ("steel
# production"), a city count ("min 2 cities (any player)"). Anything else
# is unverifiable → unresolved.
_TAGREQ = re.compile(r"^(\d+)\s+([a-z]+)\s+tags?$", re.I)
_PRODREQ = re.compile(r"^([a-z]+)\s+production$", re.I)
_CITYREQ = re.compile(r"^min\s+(\d+)\s+cit(?:y|ies)\b", re.I)
_GREENREQ = re.compile(r"^min\s+(\d+)\s+greener", re.I)

# per-tag conditional effects ("for every 2 microbe tags",
# "for each plant tag") — machine-flag the current multiplier.
_SCALE = re.compile(r"for (?:every|each) (?:(\d+)\s+)?([A-Za-z]+) tags?",
                    re.IGNORECASE)
_TAGS = {"animal", "building", "city", "earth", "jovian", "microbe",
         "plant", "power", "science", "space", "event"}

# "when/after you play a X tag|card" clause
_TRIG = re.compile(r"\b(?:when|after)\b(.*?)\b(tags?|cards?|tiles?)\b", re.I)


def _activations(card: dict, hand: list[str]) -> dict | None:
    """Which HAND cards trigger this card's play/place effect."""
    text = card.get("effects") or ""
    m = _TRIG.search(text) if re.search(r"\bpla(?:y|ce)", text, re.I) else None
    if not m:
        return None
    clause = m.group(1).lower()
    tags = sorted(t for t in _TAGS if re.search(rf"\b{t}\b", clause))
    any_ = not tags and m.group(2).lower().startswith("card")
    hits = [n for n in hand                  # skipped: "place a greenery tile"
            if (tags or any_) and (c := _resolve(n)) and c["name"] != card["name"]
            and (any_ or set(c.get("tags", [])) & set(tags))]
    return {"tags": tags, "any": any_, "cards": hits} if tags or any_ else None


def _vp_formula(card: dict, have: int | None) -> dict | None:
    """Per-resource VP from the db's structured `vpData` (the vendor's own
    victoryPoints object): {"resourcesHere": {}, "each": 2} = 2 VP each,
    {"resourcesHere": {}, "per": 2} = 1 VP per 2. Adds the next threshold
    when the count on the card is known. Board formulas (vpData null with
    prose VP) are not resource formulas and return None."""
    data = card.get("vpData")
    if not isinstance(data, dict) or "resourcesHere" not in data:
        return None
    per, each = data.get("per", 1), data.get("each", 1)
    if not isinstance(per, int) or not isinstance(each, int) or per < 1:
        return None
    f = {"points": each, "per": per,
         "unit": (card.get("resourceType") or "resource") + "s"}
    if have is not None:
        f.update(now=have, vpNow=have // per * each,
                 nextAt=(have // per + 1) * per)
    return f


def _resolve(name: str) -> dict | None:
    card = cards.find(name)
    if card is None:
        hits = cards.fuzzy(name, limit=1)
        if hits and hits[0][1] >= 0.85:
            card = hits[0][0]
    return card


def _scaling(card: dict, tableau: list[str]) -> dict | None:
    """Multiplier of a per-tag conditional effect at the given tableau.

    Approximate: counts db.json tags of the named played cards (+ the
    evaluated card itself when it carries the tag). The official rule
    that EVENT cards' tags stop counting once played is NOT modeled.
    """
    m = _SCALE.search(card.get("effects") or "")
    if not m:
        return None
    tag = m.group(2).lower()
    if tag not in _TAGS:
        return None
    per = int(m.group(1) or 1)
    count = sum(1 for name in tableau
                for t in (_resolve(name) or {}).get("tags", [])
                if t == tag)
    if tag in card.get("tags", []):
        count += 1                        # "including this"
    mult = count // per
    return {"tag": tag, "per": per, "tagCount": count,
            "multiplier": mult, "zeroEffect": mult == 0, "approx": True}


def _window_info(req: str | None, globals_: dict) -> dict:
    """Requirement window vs current globals — structured.

    status: none | open | closed | closing | expired | manual;
    steps: raises until it opens (closed) / until it expires (closing);
    text: the long-report sentence."""
    if not req:
        return {"status": "none", "text": "open — no requirement"}
    m = _REQ.match(req.strip())
    if not m:
        return {"status": "manual", "req": req,       # tag/city counts etc.
                "text": f"manual check ({req})"}
    kind, val, unit = m.group(1).lower(), int(m.group(2)), m.group(3).lower()
    if "o2" in unit:
        param, label = "oxygen", f"{globals_['oxygen']}%"
    elif "°c" in unit:
        param, label = "temperature", f"{globals_['temperature']}°C"
    elif "ocean" in unit:
        param, label = "oceans", str(globals_["oceans"])
    else:                                     # greeneries — board-dependent
        return {"status": "manual", "req": req, "text": f"manual check ({req})"}
    cur, step = globals_[param], PARAM_SCALE[param]["step"]
    info = {"param": param, "req": req, "now": label}
    if kind == "min":
        if cur >= val:
            info.update(status="open", text=f"open (met: {req}, now {label})")
        else:
            info.update(status="closed", steps=-(-(val - cur) // step),
                        text=f"closed — opens later ({req}, now {label})")
    elif cur > val:
        info.update(status="expired", text=f"EXPIRED ({req}, now {label})")
    else:
        info.update(status="closing", steps=(val - cur) // step + 1,
                    text=f"open but CLOSING ({req}, now {label})")
    return info


def _window(req: str | None, globals_: dict) -> str:
    """Classify a requirement window against current globals (text)."""
    return _window_info(req, globals_)["text"]


def _persistent_tags(game: dict, tableau: list[str] | None,
                     own: str) -> dict:
    """{tag: count} of MY persisting tags — the tags a pre-play
    requirement is checked against.

    Vendor rule (src/server/cards/requirements/TagCardRequirement.ts →
    Tags.count → Tags.rawCount reads playedCards.tags, never
    playedCards.eventTags; Player.canPlay runs CardRequirements.satisfies
    BEFORE Player.playCard pushes the card into playedCards): corp + green
    + blue cards in play; events excluded; the card being evaluated never
    counts toward its own requirement. State (`tmlib.persisting_tags`) and
    the `--tableau` list are two views of the same tableau: per tag the
    larger count wins, never the sum (no double counting).
    """
    pool = game.get("me") or {}
    counts = dict(tmlib.persisting_tags(game, pool.get("name") or "", pool=pool))
    if tableau:
        names = [n for n in tableau if (_resolve(n) or {}).get("name") != own]
        for t, n in tmlib.tags_of_cards(names, resolve=_resolve).items():
            counts[t] = max(counts.get(t, 0), n)
    return counts


def _fmt(counts: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items()) or "—"


def requirement_gate(req: str, game: dict, card: dict,
                     tableau: list[str] | None = None,
                     confirmed: bool = False) -> dict:
    """D10 hard gate for a NON-global requirement.

    Returns {"req", "required", "have", "missing", "verdict", "text"}:
    verdict = met | refused | confirmed. A clause the evaluator cannot
    verify from state has have "?" and counts as missing — UNRESOLVED is
    refused, never a soft "manual check" (Codex S5: a 3-tag card was bought
    with none of its tags because the advisor assumed the card's own tags
    satisfied its own pre-play requirement). `confirmed` = the operator
    passed --confirm-requirement for this card; the gap is still printed.
    """
    required: dict[str, int] = {}
    have: dict[str, int | str] = {}
    tags = None
    for clause in (c.strip() for c in req.split(",")):
        if m := _TAGREQ.match(clause):
            tag, n = m.group(2).lower(), int(m.group(1))
            if tags is None:
                tags = _persistent_tags(game, tableau, card["name"])
            required[tag] = required.get(tag, 0) + n
            have[tag] = tags.get(tag, 0)
        elif m := _PRODREQ.match(clause):
            key = f"{m.group(1).lower()} production"
            prod = (game.get("me") or {}).get("production")
            required[key] = 1
            res = _PRODKEY.get(m.group(1).lower(), m.group(1).lower())
            have[key] = prod.get(res, 0) if isinstance(prod, dict) else "?"
        elif m := _GREENREQ.match(clause):
            pool = game.get("me") or {}
            required["greeneries"] = int(m.group(1))
            have["greeneries"] = tmlib.tile_counts(
                game, pool.get("name") or "", pool=pool)["greeneries"]
        elif m := _CITYREQ.match(clause):
            required["cities (any player)"] = int(m.group(1))
            have["cities (any player)"] = sum(
                tmlib.tile_counts(game, n, pool=p)["cities"]
                for n, p in tmlib.all_pools(game))
        else:
            required[clause] = 1
            have[clause] = "?"                       # unverifiable clause
    missing = {k: (required[k] if have[k] == "?"
                   else required[k] - have[k])
               for k in required if have[k] == "?" or have[k] < required[k]}
    note = ("persistent tags only: corp + green + blue; event tags and the "
            "card's own tags never count")
    detail = (f"required {_fmt(required)} · have {_fmt(have)} · "
              f"missing {_fmt(missing)}")
    if not missing:
        verdict, text = "met", f"open (requirement met: {req} — have {_fmt(have)})"
    elif confirmed:
        verdict = "confirmed"
        text = (f"CONFIRMED by operator (--confirm-requirement) — {req}: "
                f"{detail} ({note})")
    else:
        verdict = "refused"
        text = (f"REFUSED — requirement unmet ({req}): {detail} ({note}); "
                f"manual override: --confirm-requirement \"{card['name']}\"")
    return {"req": req, "required": required, "have": have,
            "missing": missing, "verdict": verdict, "text": text}


def _prod_blocked(prod: dict, have: dict | None) -> list[dict]:
    """Production DECREASES the player cannot pay for.

    A card that lowers one of your own productions is unplayable until the
    production exists (Food Factory: plant production −1). The evaluator
    rated it KEEP for a player at 0 plant production — a card that cannot
    be played is worth nothing this generation, whatever the rate says.
    `have` None (a state without a production block) = unknown: never
    claim unplayable.
    """
    if have is None:
        return []
    out = []
    for res, delta in prod.items():
        if delta < 0 and have.get(res, 0) < -delta:
            out.append({"resource": res, "need": -delta,
                        "have": have.get(res, 0)})
    return out


def _blocked_text(blocked: list[dict]) -> str:
    return "; ".join(
        f"needs {_PRODNAME.get(b['resource'], b['resource'])} production ≥ "
        f"{b['need']} (have {b['have']}) — unplayable now" for b in blocked)


def clock_estimate(game: dict, setup: dict | None = None) -> dict:
    """ONE clock — and the ONE place it is built is clock.estimate_for_game.

    This used to assemble its own argument list (player count, history,
    declared final generation) and it drifted: it omitted `wgt`, and the
    clock's own CLI omitted `history`, so at generation 4 of the
    2026-08-31 game the header said "plan to gen 28 | range 10-28" while
    clock.py said "plan to gen 14 — range 10-14" from the same state. Two
    input sets are two clocks; there is now one."""
    return clock.estimate_for_game(game, setup)


def evaluate(game: dict, names: list[str],
             tableau: list[str] | None = None,
             hand: list[str] | None = None,
             resources: dict[str, int] | None = None,
             setup: dict | None = None,
             confirm: list[str] | None = None) -> list[dict]:
    globals_ = game["globals"]
    confirmed = {(_resolve(n) or {}).get("name", n) for n in confirm or []}
    gens_left = clock_estimate(game, setup)["gensLeft"]
    fl = getattr(tmlib, "free_land", None)           # free-land hook (optional)
    free = fl(tmlib.occupied_space_ids(game)) if fl else None
    out = []
    for raw in names:
        card = _resolve(raw)
        if card is None:
            out.append({"name": raw, "unknown": True})
            continue
        e = {"name": card["name"], "cost": card["cost"],
             "totalCost": card["cost"] + 3,
             "tags": card.get("tags", []), "vp": card.get("vp"),
             "type": card.get("type"), "effects": card.get("effects"),
             "action": card.get("action"),
             "actionBehavior": card.get("actionBehavior"),
             "windowInfo": _window_info(card.get("requirements"), globals_),
             "globals": dict(globals_)}
        if e["windowInfo"]["status"] == "manual":       # D10 hard gate
            gate = requirement_gate(card["requirements"], game, card,
                                    tableau=tableau,
                                    confirmed=card["name"] in confirmed)
            e["requirement"] = gate
            e["windowInfo"] = {
                "status": {"met": "open", "refused": "unresolved",
                           "confirmed": "confirmed"}[gate["verdict"]],
                "req": gate["req"], "text": gate["text"]}
        e["window"] = e["windowInfo"]["text"]
        prod_raw = (card.get("behavior") or {}).get("production") or {}
        prod = {_PRODKEY[k]: v for k, v in prod_raw.items()
                if k in _PRODKEY and isinstance(v, int)}
        manual = [k for k in prod_raw
                  if k not in _PRODKEY or not isinstance(prod_raw[k], int)]
        if prod:
            e["payback"] = payback.evaluate(card["cost"], prod, gens_left)
            e["payback"]["gensLeft"] = gens_left
            blocked = _prod_blocked(prod, (game.get("me") or {}).get("production"))
            if blocked:
                e["prodBlocked"] = blocked
                e["prodBlockedText"] = _blocked_text(blocked)
        if manual:
            e["prodManual"] = manual
        if isinstance(card.get("vpData"), int) and card["vpData"]:
            e["vpValue"] = card["vpData"] * PRICE["vp"]
        elif f := _vp_formula(card, (resources or {}).get(card["name"])):
            e["vpFormula"] = f
        if tableau is not None:
            sc = _scaling(card, tableau)
            if sc:
                e["scaling"] = sc
        if hand is not None and (act := _activations(card, hand)):
            e["activates"] = act
        b = card.get("behavior") or {}
        if free is not None and free <= 1 + len(game.get("opponents", {})) and (
                any(k in b for k in ("greenery", "city", "tile"))
                or prod.get("plants", 0) > 0):
            e["landWarning"] = free
        out.append(e)
    return out


def summary(game: dict, entries: list[dict],
            setup: dict | None = None) -> dict:
    est = clock_estimate(game, setup)
    return {"generation": game["generation"], "gensLeft": est["gensLeft"],
            "endGeneration": est["endGeneration"],
            "endRange": est.get("endRange", [est["endGeneration"]] * 2),
            "phase": est["phase"], "mc": game["me"]["resources"]["mc"],
            "keepCostAll": 3 * sum(1 for e in entries
                                   if not e.get("unknown"))}


# ---------------------------------------------------------------- quick
_GLOBAL_MC = {"temperature": PRICE["temperature"], "oxygen": PRICE["oxygen"]}

# "Gain 3 plants, …" — a one-shot gain the db's behavior block does not
# carry (bespoke cards like Imported Hydrogen, whose behavior is the ocean
# only). Anchored at the start of the text so a TRIGGER clause ("when you
# play a plant tag … gain 1 plant") is never mistaken for a windfall.
_GAIN = re.compile(r"^gain (\d+) (plant|steel|titanium|heat|card)s?\b", re.I)
_GAINKEY = {"plant": "plants", "steel": "steel", "titanium": "titanium",
            "heat": "heat", "card": "cards"}


def _windfall(card: dict) -> dict:
    """One-shot resource gains, priced at the KB windfall rate.

    P8 #5: Imported Hydrogen was quoted as "ocean ×1 = 14 → PASS" — the
    3 plants it also gains (6 MC) were invisible, and the card is a KEEP
    with them. Sources: behavior.stock, the best branch of an `or`, drawn
    cards, and the leading "Gain N x" clause when db.json carries none.
    """
    b = card.get("behavior") or {}
    gains: dict[str, int] = {}

    def add(stock):
        for k, v in (stock or {}).items():
            key = _PRODKEY.get(k, k)
            if key in WINDFALL and isinstance(v, int) and v > 0:
                gains[key] = gains.get(key, 0) + v

    add(b.get("stock"))
    branches = (b.get("or") or {}).get("behaviors") or []
    if branches:                       # price the best branch, not the sum
        best, best_val = None, 0
        for br in branches:
            val = sum(WINDFALL[_PRODKEY.get(k, k)] * v
                      for k, v in (br.get("stock") or {}).items()
                      if _PRODKEY.get(k, k) in WINDFALL and isinstance(v, int)
                      and v > 0)
            if val > best_val:
                best, best_val = br, val
        add((best or {}).get("stock"))
    draw = b.get("drawCard")
    if isinstance(draw, dict):
        draw = draw.get("keep", draw.get("count", 0))
    if isinstance(draw, int) and draw > 0:
        gains["cards"] = gains.get("cards", 0) + draw
    if not gains:
        m = _GAIN.match((card.get("effects") or "").strip())
        if m:
            gains[_GAINKEY[m.group(2).lower()]] = int(m.group(1))
    return gains


def _machine_value(card: dict, e: dict, gens_left: int) -> tuple[int, list[str], bool]:
    """MC-equivalent of what db.json can price: production over the clock,
    global steps, oceans, TR, stock, greeneries, fixed VP. Returns
    (value, parts, modeled) — modeled=False = effect/action-only card."""
    b = card.get("behavior") or {}
    value, parts, modeled = 0, [], False
    # A global step with no room left on its track is worth NOTHING. One
    # recorded game tagged an ocean card KEEP after the ocean track was
    # already full — the mistake costs most in the endgame research where
    # cards are scarcest. Callers that do not pass globals keep full price.
    g_now = e.get("globals") or {}

    def _full(param: str) -> bool:
        return (param in g_now
                and g_now[param] >= PARAM_SCALE[param]["max"])
    if "payback" in e:
        p = e["payback"]
        value += p["totalReturn"]
        modeled = True
    for k, n in (b.get("global") or {}).items():
        if k in _GLOBAL_MC and isinstance(n, int):
            if _full(k):
                parts.append(f"{k[:4]} maxed ×0")
            else:
                value += _GLOBAL_MC[k] * n
                parts.append(f"{k[:4]} +{n}")
            modeled = True
    if "ocean" in b:
        o = b["ocean"]
        n = o.get("count", 1) if isinstance(o, dict) else 1
        if _full("oceans"):
            parts.append("ocean maxed ×0")
        else:
            value += PRICE["oceans"] * n
            parts.append(f"ocean ×{n}")
        modeled = True
    if isinstance(b.get("tr"), int):
        value += PRICE["tr"] * b["tr"]
        parts.append(f"TR +{b['tr']}")
        modeled = True
    if "greenery" in b:
        value += PRICE["oxygen"] + PRICE["vp"]
        parts.append("greenery")
        modeled = True
    for res, n in _windfall(card).items():
        value += WINDFALL[res] * n
        parts.append(f"{res} ×{n}")
        modeled = True
    if isinstance(card.get("vpData"), int):
        value += PRICE["vp"] * card["vpData"]
        modeled = True
    return value, parts, modeled


def _quick_verdict(e: dict, card: dict, gens_left: int) -> tuple[str, str]:
    """(tag, reason): KEEP / PASS / DENY-only / JUDGE."""
    w = e["windowInfo"]
    if w["status"] == "unresolved":                 # D10: never a silent keep
        r = e["requirement"]
        return "REFUSED", (f"requirement unmet — missing {_fmt(r['missing'])}; "
                           f"--confirm-requirement \"{e['name']}\" to override")
    if w["status"] == "expired":
        return "PASS", "window gone"
    if w["status"] == "closed" and w["steps"] > gens_left:
        return "PASS", f"opens in {w['steps']} steps, {gens_left} gens left"
    if e.get("prodBlocked"):        # cannot be played at all right now (#4)
        return "JUDGE", e["prodBlockedText"]
    if e.get("scaling", {}).get("zeroEffect"):
        return "DENY-only", f"×0 at your tableau ({e['scaling']['tag']} tags)"
    value, _, modeled = _machine_value(card, e, gens_left)
    if not modeled:
        return "JUDGE", "effect/action card — no machine value, read the text"
    net = value - e["totalCost"]
    if net >= 0 and "landWarning" in e:
        return "DENY-only", f"board nearly full (free land {e['landWarning']})"
    if net >= 0:
        return "KEEP", f"{net:+d} MC net"
    return "PASS", f"{net:+d} MC net"


def _quick_window(e: dict) -> str:
    w = e["windowInfo"]
    st = w["status"]
    if st == "none":
        return "no req"
    if st == "unresolved":
        r = e["requirement"]
        return (f"REFUSED req ({w['req']}): required {_fmt(r['required'])} · "
                f"have {_fmt(r['have'])} · missing {_fmt(r['missing'])}")
    if st == "confirmed":
        r = e["requirement"]
        return (f"req confirmed by operator ({w['req']}: missing "
                f"{_fmt(r['missing'])})")
    if st == "open":
        return f"open ({w['req']})"
    if st == "closed":
        return f"closed, opens in {w['steps']} steps ({w['req']}, now {w['now']})"
    if st == "closing":
        return f"open, CLOSES in {w['steps']} steps ({w['req']}, now {w['now']})"
    return f"EXPIRED ({w['req']}, now {w['now']})"


def quick_lines(game: dict, names: list[str],
                tableau: list[str] | None = None,
                hand: list[str] | None = None,
                resources: dict[str, int] | None = None,
                setup: dict | None = None,
                confirm: list[str] | None = None) -> list[str]:
    """Draft fast path: one compact line per card."""
    gens_left = clock_estimate(game, setup)["gensLeft"]
    lines = []
    for e in evaluate(game, names, tableau=tableau, hand=hand,
                      resources=resources, setup=setup, confirm=confirm):
        if e.get("unknown"):
            lines.append(f"?? {e['name']} · NOT IN DB — ask for the exact name "
                         f"→ JUDGE (unknown card)")
            continue
        card = _resolve(e["name"])
        bits = [e["name"] + (f" ({', '.join(e['tags'])})" if e["tags"] else ""),
                f"{e['cost']}+3={e['totalCost']}",
                _quick_window(e)]
        value, parts, modeled = _machine_value(card, e, gens_left)
        if "payback" in e:
            p = e["payback"]
            bits.append(f"{p['perGen']:+d}/gen × {gens_left} = {p['totalReturn']} "
                        f"vs {e['totalCost']} → {p['net']:+d}")
        elif parts:
            bits.append("value ≈ " + " + ".join(parts) + f" = {value}")
        if isinstance(e.get("vp"), int) and e["vp"]:
            bits.append(f"{e['vp']} VP = {e['totalCost'] / e['vp']:.1f} MC/VP")
        elif f := e.get("vpFormula"):
            now = f" (now {f['now']} → next at {f['nextAt']})" if "now" in f else ""
            bits.append(f"VP {f['points']} per {f['per']} {f['unit']}{now}")
        if e.get("prodManual"):
            bits.append(f"formula prod ({', '.join(e['prodManual'])})")
        if e.get("prodBlocked"):
            bits.append("⚠ " + e["prodBlockedText"])
        if sc := e.get("scaling"):
            bits.append(f"×{sc['multiplier']} at tableau")
        if act := e.get("activates"):
            bits.append(f"activates {len(act['cards'])} in hand")
        b = card.get("behavior") or {}
        if "removeAnyPlants" in b:
            bits.append(f"attack −{b['removeAnyPlants']} plants")
        if "landWarning" in e:
            bits.append(f"⚠ free land {e['landWarning']}")
        tag, why = _quick_verdict(e, card, gens_left)
        lines.append(" · ".join(bits) + f" → {tag} ({why})")
    return lines


def header(s: dict) -> str:
    lo, hi = s["endRange"]
    rng = f"end ~gen {s['endGeneration']}" + (f", range {lo}-{hi}" if lo != hi else "")
    return (f"GEN {s['generation']} | plan to gen {hi} | "
            f"{s['gensLeft']} gens left ({rng}; "
            f"{s['phase']}) | {s['mc']} MC | keep-all cost {s['keepCostAll']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="+", help="1-4 dealt card names")
    ap.add_argument("--state", default="state/game.json")
    ap.add_argument("--tableau", default=None,
                    help="comma-separated played card names — flags "
                         "per-tag conditional effects (×K, zero-effect)")
    ap.add_argument("--hand", default=None,
                    help="comma-separated cards already in hand — counts "
                         "which of them a trigger/effect card activates")
    ap.add_argument("--resources", default=None,
                    help='"Tardigrades=7,Herbivores=3" — resource counts on '
                         "played accumulator cards (next-VP threshold)")
    ap.add_argument("--confirm-requirement", action="append", default=[],
                    metavar="CARD",
                    help="operator confirms a NON-global requirement the "
                         "evaluator refused (tag counts etc.) — lifts the "
                         "REFUSED verdict for that card; the gap stays printed")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true",
                      help="draft fast path: one line per card (auto for 2-4 "
                           "names without --tableau/--hand/--resources)")
    mode.add_argument("--full", action="store_true",
                      help="force the long report")
    a = ap.parse_args()
    game = json.loads(Path(a.state).read_text())
    setup_path = Path(a.state).with_name("setup.json")
    setup = json.loads(setup_path.read_text()) if setup_path.exists() else None
    split = lambda s: [t.strip() for t in s.split(",") if t.strip()]
    tableau = split(a.tableau) if a.tableau is not None else None
    hand = split(a.hand) if a.hand is not None else None
    resources = {(_resolve(k) or {}).get("name", k): int(v)
                 for k, v in (kv.split("=") for kv in split(a.resources or ""))}
    context = any(x is not None for x in (a.tableau, a.hand, a.resources))
    quick = a.quick or (not a.full and not context and 2 <= len(a.names) <= 4)
    entries = evaluate(game, a.names, tableau=tableau, hand=hand,
                       resources=resources, setup=setup,
                       confirm=a.confirm_requirement)
    print(header(summary(game, entries, setup=setup)))
    if quick:
        for line in quick_lines(game, a.names, tableau=tableau, hand=hand,
                                resources=resources, setup=setup,
                                confirm=a.confirm_requirement):
            print(line)
        return 0
    for e in entries:
        print("=" * 60)
        if e.get("unknown"):
            print(f"?? {e['name']} — NOT IN DB (iron rule: ask for exact name)")
            continue
        vp = f" | {e['vp']} VP (={e.get('vpValue', '?')} MC)" if e.get("vp") else ""
        print(f"{e['name']}  [{e['type']}]  {e['cost']} MC "
              f"(+3 keep = {e['totalCost']}){vp}")
        if e["tags"]:
            print(f"  tags: {', '.join(e['tags'])}")
        print(f"  window: {e['window']}")
        if (r := e.get("requirement")) and r["verdict"] != "met":
            print(f"  ⚠ keep verdict {r['verdict'].upper()} — required "
                  f"{_fmt(r['required'])} / have {_fmt(r['have'])} / missing "
                  f"{_fmt(r['missing'])}")
        print(f"  {e['effects']}")
        if e.get("action"):
            print(f"  action: {e['action']}")
        if "payback" in e:
            p = e["payback"]
            print(f"  payback: {p['perGen']} MC/gen × {p['gensLeft']} gens = "
                  f"{p['totalReturn']} vs {p['totalCost']} total → net "
                  f"{p['net']:+d} MC — {p['verdict']}")
        if e.get("prodBlocked"):
            print(f"  ⚠ {e['prodBlockedText']}")
        if e.get("prodManual"):
            print(f"  ⚠ formula production ({', '.join(e['prodManual'])}) — "
                  f"evaluate manually")
        if e.get("scaling"):
            s = e["scaling"]
            zero = " — ZERO-EFFECT at your tableau" if s["zeroEffect"] else ""
            print(f"  ⚠ effect scales: currently ×{s['multiplier']}{zero} "
                  f"({s['tagCount']} {s['tag']} tag(s), per {s['per']}; "
                  f"approx — played-event tags not excluded)")
        if f := e.get("vpFormula"):
            now = (f" — now {f['now']} ({f['vpNow']} VP) → next VP at "
                   f"{f['nextAt']}" if "now" in f else "")
            print(f"  vp formula: {f['points']} per {f['per']} {f['unit']}{now}")
        if act := e.get("activates"):
            print(f"  activates in hand: {len(act['cards'])} " + (
                f"— {', '.join(act['cards'])}" if act["cards"]
                else "(deck-rate only)"))
        if "landWarning" in e:
            print(f"  ⚠ board nearly full (free land {e['landWarning']}) — "
                  f"tile/plant value discounted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
