#!/usr/bin/env python3
"""RACE TABLE — milestone and award metrics per player, from tracked state.

The threat block is GENERATED, not remembered: every generation the brief
prints who is how close to each unclaimed milestone and who leads / trails
each award, plus one RACE ALERT line for anything within 1 step. Metric
functions live in menu.py (milestone_metrics / award_metrics) so the
AVAILABLE ACTIONS menu and this table can never disagree.

Library:
    race_table(game, setup, db=None) -> dict
    render(table) -> str
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import menu
import tmlib
from menu import MILESTONE_METRIC, MILESTONE_NEED, award_metrics, milestone_metrics
from tmlib import AWARDS, AWARD_COSTS, MAX_MILESTONES, MILESTONES

AWARD_METRIC = {"Landlord": "tiles", "Banker": "MC prod",
                "Scientist": "science tags", "Thermalist": "heat",
                "Miner": "steel+Ti"}


def race_table(game: dict, setup: dict | None = None,
               db: dict | None = None) -> dict:
    db = menu._db(db)
    names = [game["me"]["name"]] + list((game.get("opponents") or {}))
    players = []
    for n in names:
        players.append({"name": n, "isMe": n == game["me"]["name"],
                        "milestones": milestone_metrics(game, n, db),
                        "awards": award_metrics(game, n, db)})
    claimed = game.get("milestonesClaimed") or {}
    funded = game.get("awardsFunded") or {}
    alerts: list[str] = []

    milestones = {}
    for ms in MILESTONES:
        need = MILESTONE_NEED[ms]
        rows = sorted(((p["name"], p["milestones"][ms]) for p in players
                       if p["milestones"][ms] is not None),
                      key=lambda t: -t[1])
        milestones[ms] = {"need": need, "claimedBy": claimed.get(ms),
                          "standings": rows}
        if ms in claimed or len(claimed) >= MAX_MILESTONES:
            continue
        for name, have in rows:
            if have >= need:
                alerts.append(f"{name} can claim {ms} NOW "
                              f"({MILESTONE_METRIC[ms]} {have}/{need})")
            elif have >= need - 1:
                alerts.append(f"{name} is 1 step from {ms} "
                              f"({MILESTONE_METRIC[ms]} {have}/{need})")

    awards = {}
    for a in AWARDS:
        rows = sorted(((p["name"], p["awards"][a] or 0) for p in players),
                      key=lambda t: -t[1])
        leader = rows[0]
        runner = rows[1] if len(rows) > 1 else (None, 0)
        gap = leader[1] - runner[1]
        status = "tie" if gap == 0 and leader[1] > 0 else (
            "nobody scores" if leader[1] == 0 else f"{leader[0]} +{gap}")
        awards[a] = {"leader": leader, "runnerUp": runner, "gap": gap,
                     "fundedBy": funded.get(a), "status": status,
                     "standings": rows}
        if a in funded and gap <= 1 and leader[1] > 0:
            alerts.append(f"{a} (funded by {funded[a]}) is contested: "
                          f"{leader[0]} {leader[1]} vs {runner[0]} {runner[1]}")
    me = game["me"]["name"]
    if len(funded) < len(AWARD_COSTS):
        price = AWARD_COSTS[len(funded)]
        # Funding is a LOCK test, not a lead test (strategy/02 + 04): the
        # lead only counts when it beats every rival's reachable max by
        # the last generation — menu.award_lock prices the horizon and
        # the unspent M€ that buys tiles / MC production.
        gens = menu.gens_left(game, setup)
        for a, row in awards.items():
            if a in funded or row["leader"][0] != me or row["gap"] < 1:
                continue
            lock = menu.award_lock(game, a, setup, db, gens=gens)
            if lock["lockable"]:
                alerts.append(f"{a} LOCKABLE: {lock['why']} "
                              f"(slot {len(funded) + 1} costs {price} MC)")
            elif row["gap"] >= 2:
                alerts.append(f"{a}: {me} leads by {row['gap']} but NOT "
                              f"lockable — {lock['why']}; do not fund a lead")
    return {"players": players, "milestones": milestones, "awards": awards,
            "alerts": alerts, "claimed": claimed, "funded": funded}


def render(table: dict) -> str:
    players = table["players"]
    lines = ["## RACES (milestone + award metrics from tracked state; "
             "opponents best effort — photos/snap refine)"]
    head = f"{'player':10}" + "".join(f"{ms[:6]:>8}" for ms in MILESTONES)
    lines.append(head + "   |" + "".join(f"{a[:6]:>8}" for a in AWARDS))
    need = "".join(f"{'≥' + str(MILESTONE_NEED[ms]):>8}" for ms in MILESTONES)
    lines.append(f"{'(need)':10}{need}   |" + "".join(
        f"{AWARD_METRIC[a][:7]:>8}" for a in AWARDS))
    for p in players:
        ms = "".join(f"{('?' if p['milestones'][m] is None else p['milestones'][m]):>8}"
                     for m in MILESTONES)
        aw = "".join(f"{(p['awards'][a] if p['awards'][a] is not None else '?'):>8}"
                     for a in AWARDS)
        tag = "*" if p["isMe"] else " "
        lines.append(f"{tag}{p['name'][:9]:9}{ms}   |{aw}")
    claimed = table["claimed"]
    funded = table["funded"]
    lines.append("Milestones claimed: " + (", ".join(
        f"{m} ({who})" for m, who in claimed.items()) or "none")
        + f" — {MAX_MILESTONES - len(claimed)} slot(s) open")
    aw_parts = []
    for a, row in table["awards"].items():
        f = f" [funded: {row['fundedBy']}]" if row["fundedBy"] else ""
        aw_parts.append(f"{a}: {row['leader'][0]} {row['leader'][1]} > "
                        f"{row['runnerUp'][0]} {row['runnerUp'][1]} (gap {row['gap']}){f}")
    lines.append("Awards: " + " · ".join(aw_parts)
                 + (f" — next slot {AWARD_COSTS[len(funded)]} MC"
                    if len(funded) < len(AWARD_COSTS) else " — all funded"))
    if table["alerts"]:
        lines.append("RACE ALERT: " + " | ".join(table["alerts"]))
    else:
        lines.append("RACE ALERT: none within 1 step")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Print the RACE TABLE for the "
                                "active game.")
    p.add_argument("--root", default=".", help="repo root (state/ = active game)")
    p.add_argument("--state", default=None,
                   help="a game folder (games/<date>-gameN) instead of state/")
    a = p.parse_args(argv)
    store = tmlib.Store(a.root, state_dir=a.state)
    try:
        game, setup = store.load_game(), store.load_setup()
    except FileNotFoundError as e:
        print(f"ERROR: {e} — is a game active?", file=sys.stderr)
        return 1
    print(render(race_table(game, setup)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
