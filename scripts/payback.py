#!/usr/bin/env python3
"""Payback calculator: is this production card worth it with N gens left?

MC-equivalents per generation (strategy/01, validated vs BGG 1847708):
mc 1, steel 2, titanium 3, plants 2, heat 1, energy 1.
"""
import argparse
import math
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent))
from tmlib import CARD_KEEP_COST

MC_PER_GEN = {"mc": 1, "steel": 2, "titanium": 3, "plants": 2,
              "heat": 1, "energy": 1}
KEEP_COST = CARD_KEEP_COST


def evaluate(cost: int, prod: dict, gens_left: int, keep_cost: int = KEEP_COST) -> dict:
    per_gen = sum(MC_PER_GEN[k] * v for k, v in prod.items())
    total_cost = cost + keep_cost
    total_return = per_gen * gens_left
    net = total_return - total_cost
    break_even = math.ceil(total_cost / per_gen) if per_gen > 0 else None
    if break_even is not None and break_even <= gens_left and net > 0:
        margin = "comfortable" if net >= total_cost * 0.3 else "thin"
        verdict = (f"pays back in {break_even} gens ({margin} margin, "
                   f"+{net} MC net over {gens_left} gens)")
    elif break_even is None:
        verdict = "no production return — evaluate on VP/TR/effects instead, or skip"
    else:
        verdict = (f"skip on production value alone ({net:+} MC net; needs "
                   f"{break_even} gens, only {gens_left} left)")
    return {"totalCost": total_cost, "perGen": per_gen,
            "totalReturn": total_return, "net": net,
            "breakEvenGens": break_even, "verdict": verdict}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cost", type=int, required=True, help="printed card cost")
    horizon = p.add_mutually_exclusive_group(required=True)
    horizon.add_argument("--gens-left", type=int)
    horizon.add_argument("--gens-range", type=int, nargs=2, metavar=("LOW", "HIGH"),
                         help="clock.py gensLeftRange: verdict at the midpoint, "
                              "net printed at both bounds")
    p.add_argument("--no-keep-cost", action="store_true",
                   help="card already in hand: 3 MC keep cost is sunk")
    p.add_argument("prod", nargs="*", metavar="res=+n",
                   help="production deltas, e.g. mc=3 heat=2")
    a = p.parse_args()
    prod = {}
    for item in a.prod:
        k, _, v = item.partition("=")
        if k not in MC_PER_GEN:
            print(f"ERROR: unknown resource {k!r}", file=sys.stderr)
            return 1
        prod[k] = int(v)
    keep = 0 if a.no_keep_cost else KEEP_COST
    gens_left = a.gens_left
    if a.gens_range:
        lo, hi = a.gens_range
        gens_left = (lo + hi) // 2
        nets = [evaluate(a.cost, prod, g, keep_cost=keep)["net"] for g in (lo, hi)]
        print(f"horizon {lo}-{hi} gens (verdict at midpoint {gens_left}): "
              f"net {nets[0]:+} MC at {lo}, {nets[1]:+} MC at {hi}")
    r = evaluate(a.cost, prod, gens_left, keep_cost=keep)
    print(f"per-gen value {r['perGen']} MC | total cost {r['totalCost']} | "
          f"return {r['totalReturn']} | net {r['net']:+} MC")
    print(r["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
