#!/usr/bin/env python3
"""Endgame optimizer: brute-force my own action lines for the last 1–2 gens.

Searches conversions, standard projects, and milestone claims (cards are
the advisor's job — this is the deterministic floor). Score = end-VP gain:
each TR step = 1 VP, each greenery = 1 TR + 1 VP. Respects parameter caps.
"""
import argparse
import json
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import MILESTONE_COST, PARAM_SCALE, STANDARD_PROJECTS

ASTEROID = STANDARD_PROJECTS["asteroid"]
AQUIFER = STANDARD_PROJECTS["aquifer"]
GREENERY_SP = STANDARD_PROJECTS["greenery"]
MILESTONE = MILESTONE_COST


def best_line(resources: dict, globals_: dict, gens: int = 1,
              tr: int = 0, production: dict | None = None,
              milestone_eligible: bool = False) -> dict:
    production = production or {"mc": 0, "heat": 0, "plants": 0}

    _T = PARAM_SCALE["temperature"]

    def temp_left(t):
        return (_T["max"] - t) // _T["step"]

    @lru_cache(maxsize=None)
    def search(mc, heat, plants, tleft, o2left, oceanleft,
               gens_remaining, milestone_open):
        best = (0, ())
        options = []
        if heat >= 8 and tleft > 0:
            options.append((1, "Convert 8 heat → temperature (+1 TR)",
                            (mc, heat - 8, plants, tleft - 1, o2left,
                             oceanleft, gens_remaining, milestone_open)))
        if plants >= 8:
            gain = 2 if o2left > 0 else 1  # tile VP always; TR only if O2 moves
            options.append((gain, "Convert 8 plants → greenery"
                            + (" (+1 TR, +1 VP)" if o2left else " (+1 VP)"),
                            (mc, heat, plants - 8, tleft,
                             max(0, o2left - 1), oceanleft,
                             gens_remaining, milestone_open)))
        if mc >= ASTEROID and tleft > 0:
            options.append((1, f"SP Asteroid ({ASTEROID} MC → +1 TR)",
                            (mc - ASTEROID, heat, plants, tleft - 1, o2left,
                             oceanleft, gens_remaining, milestone_open)))
        if mc >= AQUIFER and oceanleft > 0:
            options.append((1, f"SP Aquifer ({AQUIFER} MC → +1 TR)",
                            (mc - AQUIFER, heat, plants, tleft, o2left,
                             oceanleft - 1, gens_remaining, milestone_open)))
        if mc >= GREENERY_SP:
            gain = 2 if o2left > 0 else 1
            options.append((gain, f"SP Greenery ({GREENERY_SP} MC)",
                            (mc - GREENERY_SP, heat, plants, tleft,
                             max(0, o2left - 1), oceanleft,
                             gens_remaining, milestone_open)))
        if milestone_open and mc >= MILESTONE:
            options.append((5, f"Claim milestone ({MILESTONE} MC → 5 VP)",
                            (mc - MILESTONE, heat, plants, tleft, o2left,
                             oceanleft, gens_remaining, False)))
        for gain, label, state in options:
            sub_gain, sub_actions = search(*state)
            if gain + sub_gain > best[0]:
                best = (gain + sub_gain, (label,) + sub_actions)
        if gens_remaining > 1:
            # pass → production phase → next generation
            income_tr = tr + (temp_start_left - tleft) + (
                ocean_start_left - oceanleft) + (o2_start_left - o2left)
            nmc = mc + income_tr + production["mc"]
            nheat = heat + production["heat"]
            nplants = plants + production["plants"]
            sub_gain, sub_actions = search(
                nmc, nheat, nplants, tleft, o2left, oceanleft,
                gens_remaining - 1, milestone_open)
            if sub_gain > best[0]:
                best = (sub_gain,
                        (f"— produce (income {income_tr + production['mc']} MC) "
                         f"→ next generation —",) + sub_actions)
        return best

    temp_start_left = temp_left(globals_["temperature"])
    o2_start_left = PARAM_SCALE["oxygen"]["max"] - globals_["oxygen"]
    ocean_start_left = PARAM_SCALE["oceans"]["max"] - globals_["oceans"]
    gain, actions = search(resources["mc"], resources["heat"],
                           resources["plants"], temp_start_left,
                           o2_start_left, ocean_start_left,
                           gens, milestone_eligible)
    return {"vpGain": gain, "actions": list(actions)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default="state/game.json")
    p.add_argument("--gens", type=int, default=1, choices=(1, 2))
    p.add_argument("--milestone-eligible", action="store_true")
    a = p.parse_args()
    s = json.loads(Path(a.state).read_text())
    me = s["me"]
    r = best_line(resources={k: me["resources"][k] for k in ("mc", "heat", "plants")},
                  globals_=s["globals"], gens=a.gens, tr=me["tr"],
                  production={k: me["production"][k] for k in ("mc", "heat", "plants")},
                  milestone_eligible=a.milestone_eligible)
    print(f"Best deterministic line (+{r['vpGain']} VP):")
    for i, act in enumerate(r["actions"], 1):
        print(f"  {i}. {act}")
    if not r["actions"]:
        print("  (nothing gains VP without cards)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
