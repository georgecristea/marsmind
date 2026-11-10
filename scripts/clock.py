#!/usr/bin/env python3
"""Game-length estimator: parameter fill rate → predicted end generation.

Drives phase switching (economy → transition → points). 42 total steps:
temperature 19 (2°C each, −30→+8), oxygen 14, oceans 9.

Model: fill RATE GROWS roughly linearly with generation as engines
mature — a typical 5p table averages ~2.4 steps/gen over gens 1-5, then
~6 steps/gen over gens 6-10. A flat-average × constant-acceleration
projection says "end ~gen 16" at gen 6 of a game that ends at gen 10,
and the advisor over-buys economy on payback horizons that never exist.
The current model fits rate(g) = c·g to the observed cumulative fill
(steps ≈ c·G(G+1)/2) and projects when the cumulative curve crosses 42 —
on such a gen-6 state it predicts end gen 10 exactly. Early generations
(≤2 elapsed) have too little signal for any fit: use the player-count
prior outright.

Range (a 17-gen 5p table is the counter-example: the model said "~1 gen
left" from gen 12 on because it assumes the rate keeps accelerating; the
table stalled instead): when `history` (start-of-
generation globals for the preceding generations) is given, a second
projection extends the OBSERVED rate over the last 2 completed
generations (1 if only one is known). `endGeneration` stays the earlier
of the two (KB 05: plan on the short clock), `endRange`/`gensLeftRange`
carry both. Without history the range collapses to the point estimate —
except where a stall or a fast fill (below) keeps it open regardless.

PLAYER COUNT (issue #22). Fewer players fill the 42 steps with fewer
engines, so a small table runs longer. That is a RULES fact and it lives
in one place: the gen-1 prior, PRIOR_END, with a band (prior-1 … prior+2)
because a prior is a guess and "range 11-11" before any fill has been
observed is a lie, not an estimate.

STALLED PARAMETERS (P9 issue 7). The quadratic is fitted to the WHOLE
42-step track, so a parameter that has not moved at all is extrapolated
over the tail as if it were merely slow: a 3p game with oxygen at 0% for
six generations printed "end ~gen 20; range 20-20" at gen 5 and ended at
gen 13. Two things are wrong with that and one is right. Right: the fill
rate really was 0.2 steps/gen and the alarm should fire. Wrong: a
zero-width range is read downstream (menu.award_lock) as certainty, at
the moment the estimate is least certain; and a stall is not a rate — it
breaks the turn someone finally plays a greenery, so it cannot justify
pricing 15 more generations of game.

So when any parameter shows NO fill at all, `stalledParams` names it, the
note says `parameter-stalled: <p>`, the long projection is kept as the
UPPER bound (the alarm), and the rules-derived prior comes back as the
short clock (KB 05: plan on the short clock). The interval is floored to
a real width there — but only outside the last two generations, where the
collapse is deliberate, and never over a table-declared final generation
or a maxed board, which collapse before any of this runs.

FAST FILL (Codex game H7, the mirror of the stall above). One unusually
fast generation can pull the whole-track fit AND the last-2-gen observed
rate both well below the player-count prior at once: a live 3p table
(prior 13-14 gens) printed "end ~gen 9; range 9-10" at generation ~7
after one fast generation, and the game actually ended at generation 11.
The short projection is real signal and stays `endGeneration` (KB 05:
plan on the short clock) — but one table's one fast generation is not
proof the rules-derived prior was wrong, and a range that has collapsed
to essentially a single reading is read downstream the same way a
zero-width stall range is: as certainty. So when the projection undercuts
the prior, the prior comes back as the upper bound and the note names the
assumption (`fast-fill projection <end> vs prior <prior>`) — again only
outside the last two generations, where the collapse stays deliberate.

It does NOT live in the projection. A per-player-count multiplier on the
projected tail (3p ×1.30, 4p ×1.15 …) was fitted to TWO logged games and
removed: two games cannot calibrate a per-count coefficient, and a fitted
constant hides the uncertainty instead of showing it. Once there is
fill to measure, the spread between the two projections — the quadratic
model and THIS table's observed rate — is the honest range, and the
pessimistic bound stays the headline (KB 05: plan on the short clock).
Widen PRIOR_END from real games, not the tail.
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import PARAM_SCALE, wgt_enabled

TOTALS = {p: (s["max"] - s["min"]) // s["step"] for p, s in PARAM_SCALE.items()}
# gen-1 prior by player count (6p: online app). 3p/4p from the logged
# games 2026-08-28-game2 (3p, ended gen 14) and -game1 (4p, ended gen 12);
# 5p/6p unchanged.
PRIOR_END = {2: 14, 3: 13, 4: 11, 5: 9, 6: 8}
PRIOR_BAND = (-1, 2)  # the prior is a central guess, not a bound: tables
#                       stall more often than they sprint, hence asymmetric


def remaining_steps(globals_: dict) -> dict:
    return {p: (s["max"] - globals_[p]) // s["step"]
            for p, s in PARAM_SCALE.items()}


def estimate(globals_: dict, generation: int, players: int = 5,
             declared_final: int | None = None,
             history: list[dict] | None = None,
             wgt: bool = False) -> dict:
    """wgt: World Government Terraforming adds one free step per generation
    (~+20% fill rate at 5-6p) — the gen-1 prior moves one generation earlier;
    the observed fill rate absorbs it automatically from gen 3 on."""
    left = remaining_steps(globals_)
    # a table vote overrides every estimate
    if declared_final is not None and generation >= declared_final:
        return {"stepsDone": sum(TOTALS.values()) - sum(left.values()),
                "stepsLeft": sum(left.values()), "gensLeft": 0,
                "endGeneration": declared_final, "finalGeneration": True,
                "endRange": [declared_final] * 2, "gensLeftRange": [0, 0],
                "stalledParams": [], "phase": "points", "remaining": left,
                "note": f"plan to gen {declared_final} — TABLE-DECLARED "
                        "final generation — pure VP mode."}
    steps_left = sum(left.values())
    steps_done = sum(TOTALS.values()) - steps_left
    if steps_left == 0:
        return {"stepsDone": steps_done, "stepsLeft": 0, "gensLeft": 0,
                "endGeneration": generation, "finalGeneration": True,
                "endRange": [generation] * 2, "gensLeftRange": [0, 0],
                "stalledParams": [], "phase": "points",
                "note": f"plan to gen {generation} — all parameters maxed: "
                        "this is the final generation."}
    gens_elapsed = generation - 1
    prior = PRIOR_END.get(players, 10) - (1 if wgt else 0)
    total = sum(TOTALS.values())
    if gens_elapsed <= 2 or steps_done == 0:
        # 1-2 fill samples are pure noise ("20 gens left" at gen 2; a
        # whole-game flat average is misleading even at gen 6) —
        # the player-count prior is the best signal this early. It is a
        # guess, and the band says so rather than printing "11-11".
        end = prior
        end_lo = max(generation, end + PRIOR_BAND[0])
        end_hi = max(end_lo + 1, end + PRIOR_BAND[1])
        stalling = False
        stalled = []
        fast_fill = False
    else:
        # rate(g) = c·g  →  cumulative steps after G gens = c·G(G+1)/2.
        # Fit c to what we've observed, then find the elapsed-gen count E
        # at which the cumulative curve crosses the 42-step total.
        c = steps_done / (gens_elapsed * (gens_elapsed + 1) / 2)
        e = (-1 + math.sqrt(1 + 8 * total / c)) / 2
        end = max(generation, math.ceil(e))
        # a slow start still projects long off 3 samples: cap at prior+1
        if gens_elapsed <= 3 and end > prior + 1:
            end = prior + 1
        # Observed rate over the last 2 completed gens (1 if that is all
        # we know); compare with the model's rate over the SAME window.
        recent = [total - sum(remaining_steps(h).values())
                  for h in (history or [])[-2:]]
        n = len(recent)
        rate = (steps_done - recent[0]) / n if n else 0
        end_obs = (generation + math.ceil(steps_left / rate) - 1
                   if rate > 0 else end)
        end_lo, end_hi = min(end, end_obs), max(end, end_obs)
        # A parameter with zero fill after 3+ generations is not a slow
        # rate, it is an unstarted track: the fit spreads its untouched
        # steps over the tail and returns a long, confident-looking game.
        # Keep that as the pessimistic bound and restore the prior as the
        # short clock — the stall breaks the turn someone starts the track.
        stalled = [p for p, v in left.items() if v == TOTALS[p]]
        if stalled:
            end_lo = min(end_lo, max(generation, prior))
        if (n or stalled) and end_lo - generation > 1:
            # two projections agreeing to the generation is coincidence,
            # not knowledge: outside the last two generations the range
            # is never a single number. With a stalled parameter the
            # estimate is unbounded above, so it is never one either.
            end_hi = max(end_hi, end_lo + 1)
        # The mirror of the stall case: one fast generation can pull BOTH
        # the whole-track fit and the observed-rate projection well below
        # the player-count prior (H7 — Codex's game: 13-14 gen prior to an
        # exact "generation 9" at generation ~7, real end generation 11).
        # A short projection is real signal — it stays the short clock,
        # KB 05 — but it is one table's one fast generation, not proof the
        # rules-derived prior was wrong. Outside the last two generations
        # the prior comes back as the upper bound (the alarm this
        # direction raises), never collapsing to a single reading.
        fast_fill = end_lo < prior and end_lo - generation > 1
        if fast_fill:
            end_hi = max(end_hi, prior)
        model_rate = c * (generation - (n + 1) / 2)
        stalling = n > 0 and rate < 0.7 * model_rate
        end = end_lo
    gens_left = max(0, end - generation)
    if gens_left <= 4 or min(
        (v for k, v in left.items() if v > 0), default=0
    ) <= 2 and sum(1 for v in left.values() if v <= 2) >= 2:
        phase = "points"
    elif gens_left <= 6:
        phase = "transition"
    else:
        phase = "economy"
    # W1-B item 3 (game5: printed range 7-9, planned to the point estimate
    # 7, the game ended at gen 9): the PLANNING HORIZON is the RANGE TOP.
    # The note leads with it; the point estimate is a parenthetical.
    note = (f"plan to gen {end_hi} — range {end_lo}-{end_hi} "
            f"(point estimate: end ~gen {end}, ~{gens_left} gens left). "
            f"Phase: {phase}. Production cards stop paying ~3-4 gens before end.")
    if stalled:
        note += (f" — parameter-stalled: {', '.join(stalled)} (no fill in "
                 f"{gens_elapsed} gens), so the upper bound is a floor, not "
                 f"a bound: the end gen is unbounded until that track starts")
    if stalling:
        note += (" — table fill-rate below model (opponents stalling?); "
                 "do not lengthen the prior")
    if fast_fill:
        note += (f" — fast-fill projection {end_lo} vs prior {prior} — "
                 f"range {end_lo}-{end_hi}")
    return {"stepsDone": steps_done, "stepsLeft": steps_left,
            "gensLeft": gens_left, "endGeneration": end,
            "stalledParams": stalled,
            "endRange": [end_lo, end_hi],
            "gensLeftRange": [max(0, end_lo - generation),
                              max(0, end_hi - generation)],
            "finalGeneration": False, "phase": phase,
            "remaining": left, "note": note}


def estimate_inputs(game: dict, setup: dict | None = None) -> dict:
    """ONE CLOCK (AGENTS.md): the single place the estimator's inputs are
    derived from tracked state — player count, history, a table-declared
    final generation, WGT.

    B2 item 4d. `research.py` printed "plan to gen 28 | range 10-28" while
    `clock.py` printed "plan to gen 14 — range 10-14" from the SAME state.
    Not a second estimator: a second INPUT SET. Every in-process caller
    fed `history` (so the observed-rate projection widened the range) and
    this module's own CLI fed none, defaulting to the model projection
    alone. An estimator with two input sets is two clocks.

    History: entry k = globals when generation k closed = the start of
    generation k+1, so the entry that IS the current start is excluded."""
    setup = setup or {}
    generation = game["generation"]
    return {
        "globals_": game["globals"],
        "generation": generation,
        # setup.json is the authority; opponents{} counts only those seen
        "players": (setup.get("playerCount")
                    or 1 + len(game.get("opponents") or {})),
        "declared_final": game.get("declaredFinalGeneration"),
        "history": [h for h in game.get("history") or []
                    if h.get("generation", 0) < generation - 1],
        "wgt": wgt_enabled(setup),
    }


def estimate_for_game(game: dict, setup: dict | None = None,
                      **overrides) -> dict:
    """`estimate` fed from game + setup state. The ONLY entry point a
    caller with a loaded game should use — `estimate` itself takes loose
    arguments and is where two input sets came from."""
    return estimate(**{**estimate_inputs(game, setup), **overrides})


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default="state/game.json",
                   help="read globals/generation from game state")
    p.add_argument("--players", type=int, default=None)
    p.add_argument("--setup", default="state/setup.json",
                   help="playerCount authority when --players is absent")
    p.add_argument("--history", default=None, metavar="JSON",
                   help='start-of-generation globals for earlier gens, e.g. '
                        '"[[-30,0,0],[-28,1,0]]" (temp, O2, oceans)')
    a = p.parse_args()
    state = json.loads(Path(a.state).read_text())
    setup_path = Path(a.setup)
    setup = json.loads(setup_path.read_text()) if setup_path.exists() else {}
    # ONE CLOCK: the CLI reads the SAME inputs the in-process callers build
    # (estimate_inputs) — its own flags are overrides, not a second set.
    overrides: dict = {}
    if a.players is not None:
        overrides["players"] = a.players
    if a.history:
        overrides["history"] = [
            dict(zip(("temperature", "oxygen", "oceans"), h))
            for h in json.loads(a.history)]
    print(json.dumps(estimate_for_game(state, setup, **overrides), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
