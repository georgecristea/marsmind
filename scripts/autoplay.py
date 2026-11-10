#!/usr/bin/env python3
"""Sparring autopilot with information firewall.

DEV/TRAINING TOOL — drives opponent seats on the vendored app so practice
games run fast. The end system plays PHYSICAL tables; this exists to
train the advisor. See agents/sparring-partner.md and
agents/seat-kit.md.

Firewall: everything printed is PUBLIC-table information only — played
cards, tile placements, TR, standard projects. Hidden info (research
deals, keeps, hand) is reported as counts. The advisor must never learn
an opponent's hand from this tool. (--reveal exists for debugging only.)

    python3 scripts/autoplay.py run <pid> [--max-steps 40] [--reveal]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cards as cardlib
import clock
import payback
import sparring


LEVELS = ("passer", "greedy", "competitive")


class CompetitiveSeat(Exception):
    """Raised when a competitive-level seat is asked to autopilot."""


def _gens_left(game: dict, players: int = 3) -> int:
    """Clock-derived horizon — a hardcoded gens_left=4 made
    every production card score negative, so bots kept nothing and passed
    all game. Uses the same estimator as the advisor."""
    globals_ = {"temperature": game.get("temperature", -30),
                "oxygen": game.get("oxygenLevel", game.get("oxygen", 0)),
                "oceans": game.get("oceans", 0)}
    est = clock.estimate(globals_, generation=game.get("generation", 1),
                         players=players)
    return max(1, est["gensLeft"])


# ── value model (greedy v1; KB canonical prices) ─────────────

def _card_value(card: dict, globals_: dict, gens_left: int) -> float:
    """Rough net MC value of buying+playing a card now (KB canonical)."""
    if card is None:
        return -99
    val = -(card.get("cost") or 0) - 3
    beh = card.get("behavior") or {}
    prod = {k: v for k, v in (beh.get("production") or {}).items()
            if isinstance(v, int)}
    per_gen = {"megacredits": 1, "mc": 1, "steel": 2, "titanium": 3,
               "plants": 2, "heat": 1, "energy": 1}
    val += sum(per_gen.get(k, 0) * v for k, v in prod.items()) * gens_left
    # heat/energy are dead once temperature is maxed
    if globals_.get("temperature", -30) >= 8:
        val -= sum(per_gen.get(k, 0) * v for k, v in prod.items()
                   if k in ("heat", "energy")) * gens_left
    vp = card.get("vp")
    if isinstance(vp, int):
        val += 5 * vp
    if isinstance(beh.get("tr"), int):
        val += 10 * beh["tr"]
    if "ocean" in beh and globals_.get("oceans", 0) < 9:
        val += 14
    if "global" in beh and isinstance(beh["global"], dict):
        for p, n in beh["global"].items():
            maxed = (p == "temperature" and globals_.get("temperature", -30) >= 8) or \
                    (p == "oxygen" and globals_.get("oxygen", 0) >= 14)
            if not maxed and isinstance(n, int):
                val += 10 * n
    if "greenery" in beh:
        val += 19 if globals_.get("oxygen", 0) < 14 else 9
    return val


def _requirement_met(card: dict, globals_: dict) -> bool:
    import research
    w = research._window(card.get("requirements"), globals_)
    return not (w.startswith("closed") or w.startswith("EXPIRED"))


# ── decisions ────────────────────────────────────────────────

def decide_research(wf: dict, mat: dict, globals_: dict,
                    gens_left: int, level: str = "greedy") -> dict:
    """Pick keeps: positive-value cards, budget-capped (3 MC each).
    level='passer' keeps nothing (pure harness bot)."""
    if level == "passer":
        return sparring.cards([])
    mc = mat.get("megacredits") or 0
    names = [c["name"] if isinstance(c, dict) else c
             for c in wf.get("cards", [])]
    scored = []
    for n in names:
        card = cardlib.find(n)
        if card is None:
            continue
        v = _card_value(card, globals_, gens_left)
        if v > 0 and _requirement_met(card, globals_):
            scored.append((v, n))
    scored.sort(reverse=True)
    keeps: list[str] = []
    budget = mc
    for v, n in scored:
        if budget >= 3:
            keeps.append(n)
            budget -= 3
    return sparring.cards(keeps)


def _corp_value(corp: dict) -> float:
    """Starting MC + priced assets (KB 01 rates) — crude but ordinal."""
    if corp is None:
        return -99
    val = corp.get("cost") or 0
    beh = corp.get("behavior") or {}
    stock = beh.get("stock") or {}
    per = {"steel": 2, "titanium": 3, "plants": 2, "heat": 1}
    val += sum(per.get(k, 1) * v for k, v in stock.items()
               if isinstance(v, int))
    prod = beh.get("production") or {}
    val += sum(5 * v for v in prod.values() if isinstance(v, int))
    return val


def decide_initial(wf: dict, globals_: dict, gens_left: int) -> dict:
    """Corp + initial buys for the initialCards prompt (base/CE only:
    no prelude/ceo sub-options). Corp = richest by _corp_value; buys =
    positive-value cards, 3 MC each, keeping a 9 MC play cushion."""
    corp_opt = buy_opt = None
    for opt in wf.get("options", []):
        t = (opt.get("title") or "").lower()
        if "corporation" in t:
            corp_opt = opt
        elif "initial cards" in t or "buy" in t:
            buy_opt = opt
    corps = [c["name"] if isinstance(c, dict) else c
             for c in (corp_opt or {}).get("cards", [])]
    best_corp = max(corps, key=lambda n: _corp_value(cardlib.find(n)))
    budget = (cardlib.find(best_corp) or {}).get("cost") or 0
    fake_mat = {"megacredits": max(0, budget - 9)}
    buys = decide_research(buy_opt or {}, fake_mat, globals_, gens_left)
    return {"type": "initialCards",
            "responses": [sparring.cards([best_corp]), buys]}


def decide_action(wf: dict, mat: dict, globals_: dict,
                  gens_left: int = 4, level: str = "greedy") -> dict | None:
    """Greedy action pick from an or-menu. Returns {'index': i, 'response': ...}
    or None when only pass remains sensible (caller sends pass).
    level='passer' always passes."""
    if level == "passer":
        return None
    opts = wf.get("options", [])
    titles = [sparring._title(o).lower() for o in opts]

    def idx(needle):
        for i, t in enumerate(titles):
            if needle in t:
                return i
        return None

    # 1. plant conversion (always good: TR or endgame VP)
    i = idx("convert") if idx("convert") is not None else None
    for i, t in enumerate(titles):
        if "plants into greenery" in t:
            spaces = opts[i].get("spaces") or []
            resp = sparring.space(spaces[0]) if spaces else {"type": "option"}
            return {"index": i, "response": resp}
    # 2. heat conversion only below max temperature
    for i, t in enumerate(titles):
        if "heat into temperature" in t and globals_.get("temperature", -30) < 8:
            return {"index": i, "response": {"type": "option"}}
    # 3. claim milestone (engine only offers when eligible)
    for i, t in enumerate(titles):
        if "claim a milestone" in t:
            return {"index": i,
                    "response": {"type": "or", "index": 0,
                                 "response": {"type": "option"}}}
    # 4. best positive-value affordable project card (mc-only payment)
    mc = mat.get("megacredits") or 0
    for i, t in enumerate(titles):
        if "play project card" in t:
            best, best_v = None, 0.0
            for entry in opts[i].get("cards", []):
                n = entry["name"] if isinstance(entry, dict) else entry
                card = cardlib.find(n)
                if card is None or (card.get("cost") or 0) > mc:
                    continue
                v = _card_value(card, globals_, gens_left)
                if v > best_v and _requirement_met(card, globals_):
                    best, best_v = card, v
            if best is not None:
                return {"index": i,
                        "response": sparring.project_card(
                            best["name"], mc=best["cost"])}
    # 5. standard projects — a rich bot terraforms instead of banking
    #    (without an SP branch hundreds of MC sit idle all game)
    for i, t in enumerate(titles):
        if "standard projects" in t:
            mc = mat.get("megacredits") or 0
            ladder = [("Asteroid:SP", 14,
                       globals_.get("temperature", -30) < 8),
                      ("Aquifer", 18, globals_.get("oceans", 0) < 9),
                      ("Greenery", 23, globals_.get("oxygen", 0) < 14)]
            offered = {c["name"] if isinstance(c, dict) else c
                       for c in opts[i].get("cards", [])}
            for name, cost, useful in ladder:
                # keep a cushion so research keeps stay affordable
                if useful and name in offered and mc >= cost + 6:
                    return {"index": i,
                            "response": sparring.project_card(name, mc=cost)}
            break
    # 6. pass
    i = idx("pass for this generation")
    if i is not None:
        return {"index": i, "response": {"type": "option"}}
    i = idx("end turn")
    if i is not None:
        return {"index": i, "response": {"type": "option"}}
    return None


def summary_for_action(title: str) -> str:
    """Public log line for a chosen or-menu option (pass used to be
    mislabelled 'converted: Pass for this generation')."""
    t = title.lower()
    if "pass for this generation" in t or t == "end turn":
        return "PASSED"
    if "standard project" in t or ":sp" in t or title in ("Aquifer", "Greenery"):
        return f"standard project: {title}"
    if "convert" in t or "into greenery" in t or "into temperature" in t:
        return f"converted: {title}"
    return f"action: {title}"


# ── information firewall ─────────────────────────────────────

def public_summary(kind: str, **kw) -> str:
    """Log line containing ONLY public-table information."""
    if kind == "research":
        n = len(kw.get("kept", []))
        return f"research: kept {n} card(s) (−{kw.get('cost', 3*n)} MC) [names withheld — firewall]"
    if kind == "play":
        return f"played {kw['card']} ({kw.get('cost', '?')} MC)"
    if kind == "convert":
        return f"converted: {kw.get('what')}"
    if kind == "pass":
        return "PASSED"
    if kind == "initial":
        n = len(kw.get("kept", []))
        return (f"initial: corp {kw.get('corp')} (public), bought {n} "
                f"card(s) (\u2212{3 * n} MC) [names withheld \u2014 firewall]")
    return f"{kind}: [details withheld \u2014 firewall]"


# ── loop ─────────────────────────────────────────────────────

def decide_payment(wf: dict) -> dict:
    """Answer a `payment` prompt MC-only (research buys under Helion/Credicor,
    paid card actions): amount from the model, else parsed from the title."""
    import re
    amount = wf.get("amount")
    if not isinstance(amount, int):
        m = re.search(r"spend (\d+)", str(wf.get("title", "")))
        amount = int(m.group(1)) if m else 0
    return sparring.payment(mc=amount)


def run(pid: str, max_steps: int = 40, reveal: bool = False,
        delay: float = 0.2, level: str = "greedy") -> list[str]:
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}, got {level!r}")
    if level == "competitive":
        raise CompetitiveSeat(
            "competitive seats are NOT autopiloted — dispatch a "
            "sparring-partner subagent for this seat (see "
            "agents/sparring-partner.md: it reads only its own playerId, "
            "decides at model level, executes via scripts/sparring.py, and "
            "reports public info only)")
    log: list[str] = []
    for _ in range(max_steps):
        d = sparring.get_player(pid)
        wf = d.get("waitingFor")
        if wf is None:
            break
        mat = d.get("thisPlayer", {})
        globals_ = {"temperature": d["game"].get("temperature"),
                    "oxygen": d["game"].get("oxygenLevel"),
                    "oceans": d["game"].get("oceans")}
        t = sparring._title(wf).lower()
        gens_left = _gens_left(d["game"])
        if wf.get("type") == "initialCards":
            resp = decide_initial(wf, globals_, gens_left=gens_left)
            sparring.send(pid, resp)
            corp = resp["responses"][0]["cards"][0]
            kept = resp["responses"][1]["cards"]
            line = public_summary("initial", corp=corp, kept=kept)
            if reveal:
                line += f"  [reveal: {kept}]"
            log.append(line)
        elif wf.get("type") == "card" and "buy" in t or "keep" in t:
            resp = decide_research(wf, mat, globals_, gens_left=gens_left,
                                   level=level)
            sparring.send(pid, resp)
            line = public_summary("research", kept=resp["cards"])
            if reveal:
                line += f"  [reveal: {resp['cards']}]"
            log.append(line)
        elif wf.get("type") == "or":
            act = decide_action(wf, mat, globals_, gens_left=gens_left,
                                level=level)
            if act is None:
                i = None
                titles_ = [sparring._title(o).lower()
                           for o in wf.get("options", [])]
                for j, t_ in enumerate(titles_):
                    if "pass for this generation" in t_ or t_ == "end turn":
                        i = j
                        break
                if i is None:
                    break
                sparring.send(pid, {"type": "or", "index": i,
                                    "response": {"type": "option"}})
                log.append("PASSED")
                break
            sparring.send(pid, {"type": "or", "index": act["index"],
                                "response": act["response"]})
            chosen = sparring._title(wf.get("options")[act["index"]])
            resp_card = act["response"].get("card") \
                if isinstance(act["response"], dict) else None
            log.append(summary_for_action(
                f"Standard projects: {resp_card}" if resp_card
                and "standard" in chosen.lower() else chosen))
        elif wf.get("type") == "space":
            spaces = wf.get("spaces") or []
            if not spaces:
                break
            sparring.send(pid, sparring.space(spaces[0]))
            log.append(f"placed tile on {spaces[0]} (public)")
        elif wf.get("type") == "payment":
            resp = decide_payment(wf)
            sparring.send(pid, resp)
            log.append(f"paid {resp['payment']['megacredits']} MC")
        else:
            break
        time.sleep(delay)
    for line in log:
        print(line)
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("pid")
    r.add_argument("--max-steps", type=int, default=40)
    r.add_argument("--reveal", action="store_true")
    r.add_argument("--level", default="greedy", choices=LEVELS,
                   help="passer=harness-only, greedy=heuristic v2, "
                        "competitive=refuses (subagent seat)")
    a = ap.parse_args()
    try:
        run(a.pid, a.max_steps, a.reveal, level=a.level)
    except CompetitiveSeat as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
