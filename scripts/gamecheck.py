#!/usr/bin/env python3
"""One-call whole-game status: who is the app currently waiting on.

Every kind of 'the game seems stuck' incident (a premature produce.py
call, a missed generation redispatch, an unchecked own turn) traces
back to the same root cause: reading ONE player's waitingFor in isolation and
inferring something about the WHOLE game from it. This script removes
that inference — it always prints every configured player's status
side by side, so there is nothing left to misread.

Hard rule (agents/sparring-partner.md): run this BEFORE telling the
user anything about game progress or stall status, before calling
produce.py, and before considering a generation's reports complete.
"""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from appapi import AppClient

def get_player(pid: str, base: str | None = None) -> dict:
    """One /api/player view via scripts/appapi.py. `base` = app URL;
    None = $PHOBOS_APP_URL or localhost:8080 (main() passes the
    setup.json-bound client's .player instead)."""
    client = AppClient(base) if base else AppClient.from_setup(None)
    return client.player(pid)


def check_all_full(players: list[dict], get=None) -> list[dict]:
    """players: [{"name": ..., "playerId": ...}, ...] (skip entries with
    no playerId — e.g. a not-yet-app-linked seat). Never raises: a
    fetch failure becomes an explicit ERROR row, not a silent drop, so
    a down app/agent shows up in the table instead of vanishing from it.

    Carries two extra fields past the check_all() contract — "phase"
    (game.phase off this player's own /api/player view) and "players"
    (the app's whole-table player list, victoryPointsBreakdown included)
    — so find_ended() can tell a genuinely-finished game apart from an
    ambiguous idle table without a second round of fetches. Every /api/
    player view carries the same whole-game state regardless of which
    seat is queried (score.py's app_final_table relies on the identical
    assumption), so any one successful row is enough."""
    get = get or get_player
    rows = []
    for p in players:
        name = p["name"]
        try:
            d = get(p["playerId"])
            wf = d.get("waitingFor")
            rows.append({"name": name, "waiting": wf is not None,
                        "title": (wf or {}).get("title") if wf else None,
                        "phase": (d.get("game") or {}).get("phase"),
                        "players": d.get("players")})
        except Exception as e:
            rows.append({"name": name, "waiting": None,
                        "title": f"ERROR: {e}", "phase": None,
                        "players": None})
    return rows


def check_all(players: list[dict], get=None) -> list[dict]:
    """Back-compat view onto check_all_full: name/waiting/title only —
    the shape every existing caller (summarize, render, older tests)
    already depends on."""
    return [{"name": r["name"], "waiting": r["waiting"], "title": r["title"]}
            for r in check_all_full(players, get=get)]


def find_ended(rows: list[dict]) -> list[dict] | None:
    """None unless one of `rows` (from check_all_full) shows the app
    itself reports the game over: game.phase == "end" AND a non-empty
    "players" list came through with it. When found, return the app's
    own victoryPointsBreakdown totals, one entry per player, sorted by
    total descending — authoritative, nothing re-derived. A phase of
    "end" with no players data (fetch partially failed) is NOT treated
    as ended — fall through to the ambiguous-table path rather than
    fabricate a totals table."""
    for r in rows:
        if r.get("phase") == "end" and r.get("players"):
            totals = [{"name": p.get("name"),
                       "total": (p.get("victoryPointsBreakdown") or {}).get("total", 0)}
                      for p in r["players"]]
            return sorted(totals, key=lambda t: -t["total"])
    return None


def render_end(totals: list[dict]) -> str:
    lines = ["GAME ENDED"]
    for t in totals:
        lines.append(f"  {t['name']:<10} {t['total']}")
    return "\n".join(lines)


@dataclass
class Report:
    waiting_on: list
    anomaly: bool
    headline: str


def summarize(rows: list[dict]) -> Report:
    errored = [r["name"] for r in rows if r["waiting"] is None]
    waiting_on = [r["name"] for r in rows if r["waiting"] is True]
    if errored:
        return Report(waiting_on, True,
                      f"COULD NOT REACH: {', '.join(errored)} — app may be "
                      "down; this is NOT evidence the game is fine")
    if len(waiting_on) == 0:
        return Report(waiting_on, True,
                      "nobody is waiting — mid-production/between "
                      "generations, or genuinely stuck; check "
                      "state/log.md's last event and app generation "
                      "counter before assuming either")
    if len(waiting_on) > 1:
        titles = {r["title"] for r in rows if r["waiting"] is True}
        if len(titles) == 1:
            # research/card-buy: the one phase every player acts in
            # parallel — same title for all is expected, not a stall.
            return Report(waiting_on, False,
                          f"simultaneous phase ({titles.pop()}) — "
                          f"waiting on {', '.join(waiting_on)}")
        return Report(waiting_on, True,
                      f"MULTIPLE players waiting on DIFFERENT things: "
                      f"{', '.join(waiting_on)} — shouldn't happen in "
                      "synchronous turn order, investigate before acting")
    return Report(waiting_on, False, f"waiting on {waiting_on[0]}")


def render(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        if r["waiting"] is None:
            tag = "ERROR"
        elif r["waiting"]:
            tag = "WAITING"
        else:
            tag = "idle"
        title = f" — {r['title']}" if r["title"] else ""
        lines.append(f"  {r['name']:<10} {tag}{title}")
    return "\n".join(lines)


def run(players: list[dict], get=None) -> tuple[int, str]:
    """Full check-and-report cycle, decoupled from setup.json/AppClient so
    it's directly testable against stubbed player views. Game-end takes
    priority over the ambiguous-idle-table check: an all-idle row set that
    is actually a finished game must never be reported as an anomaly."""
    rows = check_all_full(players, get=get)
    ended = find_ended(rows)
    if ended is not None:
        return 0, render_end(ended)
    plain_rows = [{"name": r["name"], "waiting": r["waiting"], "title": r["title"]}
                  for r in rows]
    text = render(plain_rows)
    report = summarize(plain_rows)
    if report.anomaly:
        return 2, f"{text}\n\n⚠ {report.headline}"
    return 0, text


def main() -> int:
    setup = json.loads((Path(__file__).resolve().parent.parent
                        / "state" / "setup.json").read_text())
    players = [p for p in setup["players"] if p.get("playerId")]
    if not players:
        print("No app playerIds in state/setup.json — not an app-mode game.")
        return 1
    code, text = run(players, get=AppClient.from_setup(setup).player)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
