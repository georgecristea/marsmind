#!/usr/bin/env python3
"""Seat report — composed from the seat's PUBLIC view only (D8 / Codex C2).

A seat never writes a report by hand. It runs

    python3 scripts/seat_report.py <pid> [--url U] [--generation N]
                                   [--note "<text>"] [--error "<text>"]...

and pastes the output verbatim. The report is built SOLELY from the public
projection of the seat's own `/api/player?id=<pid>` view (the fields every
opponent can see — PublicPlayerModel) plus the app's PUBLIC log lines:

    SEAT REPORT — <name> (<color>) gen <G>
    status: passed | active | waiting | GAME ENDED
    did: <one line of public actions this generation>
    mat: 💰 MC <n> · 🏆 TR <n> · hand <n> cards · tableau <n> cards
    note: <--note text>                     (only when given)
    ERROR: <--error text, verbatim>         (one per --error, separate channel)

Information firewall (the whole point of this script):
  * hand, dealt/drafted cards, prompts and reasoning are never read — the
    composer only ever receives `public_view()`, a whitelist projection;
  * any card name that is NOT in the seat's own public tableau is refused
    wherever it appears — `--note`, `--error`, or the app log: seat-supplied
    text refuses the WHOLE report (exit 2, `REFUSED: …` on stderr, nothing
    on stdout, and the reason never echoes the name); app log lines are
    withheld one by one and counted, since the seat did not write them;
  * private log entries (the app marks them with `playerId`) are dropped
    before anything else.

The `--error` channel is for exact technical errors (a rejected send, an
HTTP body) and passes through verbatim — redact a hidden card name to
`<card>` before passing it, or the report is refused.

Exit: 0 report printed · 2 refused (firewall) · 3 app unreachable/HTTP error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from appapi import (AppClient, AppError, AppUnavailable, DataType,  # noqa: E402
                    DEFAULT_URL, ENV_VAR, color_names, render_log_entry)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "cards" / "db.json"

# The ONLY fields the composer may see. Everything on the vendor's
# PlayerViewModel that is not here (cardsInHand, dealt*, drafted*,
# picked*, waitingFor, …) is structurally unreadable by the report.
PUBLIC_FIELDS = ("name", "color", "phase", "generation", "passed", "isActive",
                 "megacredits", "terraformRating", "cardsInHandNbr",
                 "actionsTakenThisRound", "actionsThisGeneration", "tableau",
                 "colorNames")
EXIT_REFUSED = 2
EXIT_APP = 3


class FirewallBreach(Exception):
    """A card name outside the seat's public tableau — the reason never
    carries the name itself."""


# ── public projection ────────────────────────────────────────

def public_view(view: dict) -> dict:
    """Whitelist projection of a /api/player payload: the seat's own
    PublicPlayerModel fields + the game's phase/generation/passed set.
    Hidden fields are not copied, so nothing downstream can read them."""
    me = view.get("thisPlayer") or {}
    game = view.get("game") or {}
    color = me.get("color")
    return {
        "name": me.get("name"),
        "color": color,
        "phase": game.get("phase"),
        "generation": game.get("generation"),
        "passed": color in (game.get("passedPlayers") or []),
        "isActive": bool(me.get("isActive")),
        "megacredits": me.get("megacredits"),
        "terraformRating": me.get("terraformRating"),
        "cardsInHandNbr": me.get("cardsInHandNbr"),
        "actionsTakenThisRound": me.get("actionsTakenThisRound"),
        "actionsThisGeneration": list(me.get("actionsThisGeneration") or []),
        "tableau": [c.get("name") if isinstance(c, dict) else str(c)
                    for c in (me.get("tableau") or [])],
        "colorNames": color_names(view),
    }


# ── firewall ─────────────────────────────────────────────────

def card_names() -> list[str]:
    db = json.loads(DB_PATH.read_text())
    return sorted({c["name"] for c in db["cards"]}, key=len, reverse=True)


def _pattern(names) -> re.Pattern:
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9]){alts}(?![A-Za-z0-9])", re.IGNORECASE)


def hidden_names(text: str, public: set[str], names: list[str]) -> list[str]:
    """Card names in `text` that are not in `public`. Public names are
    masked first so a public card whose name embeds a shorter card's name
    does not trip the scan."""
    if not text or not names:
        return []
    masked = _pattern(public).sub(" ", text) if public else text
    return sorted({m.group(0) for m in _pattern(names).finditer(masked)},
                  key=str.lower)


def _check(text: str, public: set[str], names: list[str], channel: str) -> None:
    hits = hidden_names(text, public, names)
    if hits:
        raise FirewallBreach(
            f"{channel} names {len(hits)} card(s) outside your public tableau "
            f"— hidden information never leaves a seat. Remove the name(s) "
            f"(an error text: replace the card name with <card>) and re-run.")


# ── composition ──────────────────────────────────────────────

def _status(pub: dict) -> str:
    if pub.get("phase") == "end":
        return "GAME ENDED"
    if pub.get("passed"):
        return "passed"
    return "active (my turn)" if pub.get("isActive") else "waiting"


def action_line(pub: dict, entries: list[dict], names: list[str]) -> tuple[str, int]:
    """One line of the seat's PUBLIC actions from the app log: private
    entries (playerId set) dropped, only entries where the seat is the
    actor, each line firewall-checked (withheld + counted on a hit)."""
    public = set(pub["tableau"])
    color = pub.get("color")
    lines, withheld = [], 0
    for e in entries or []:
        if e.get("playerId"):
            continue
        data = e.get("data") or []
        actors = [d.get("value") for d in data if isinstance(d, dict)
                  and d.get("type") == int(DataType.PLAYER)]
        if not actors or actors[0] != color:
            continue
        line = render_log_entry(e, pub.get("colorNames")).strip()
        if not line:
            continue
        if hidden_names(line, public, names):
            withheld += 1
            continue
        lines.append(line)
    if lines:
        return "; ".join(lines), withheld
    n = pub.get("actionsTakenThisRound")
    used = [a for a in pub.get("actionsThisGeneration") or [] if a in public]
    fallback = f"{n if n is not None else '?'} action(s) this round"
    if used:
        fallback += " · blue actions used: " + ", ".join(used)
    return fallback, withheld


def compose(pub: dict, entries: list[dict], note: str | None = None,
            errors: tuple[str, ...] = (), names: list[str] | None = None) -> str:
    """The report text, or FirewallBreach. `pub` MUST be public_view()."""
    names = card_names() if names is None else names
    public = set(pub["tableau"])
    if note:
        _check(note, public, names, "--note")
    for err in errors:
        _check(err, public, names, "--error")
    did, withheld = action_line(pub, entries, names)
    if withheld:
        did += (f" ({withheld} log line{'s' if withheld != 1 else ''} withheld:"
                " names a card outside the public tableau)")
    out = [
        f"SEAT REPORT — {pub.get('name')} ({pub.get('color')}) gen {pub.get('generation')}",
        f"status: {_status(pub)}",
        f"did: {did}",
        (f"mat: 💰 MC {pub.get('megacredits')} · 🏆 TR {pub.get('terraformRating')}"
         f" · hand {pub.get('cardsInHandNbr')} cards · tableau {len(public)} cards"),
    ]
    if note:
        out.append(f"note: {note.strip()}")
    out.extend(f"ERROR: {e}" for e in errors)
    text = "\n".join(out)
    # belt and braces: the assembled text passes the same scan
    _check(text, public, names, "report")
    return text


# ── CLI ──────────────────────────────────────────────────────

def main(argv=None, get=None, logs=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pid", help="YOUR OWN playerId (never another seat's)")
    p.add_argument("--url", default=None,
                   help=f"app URL (default ${ENV_VAR} or {DEFAULT_URL})")
    p.add_argument("--generation", type=int, default=None,
                   help="log generation to summarise (default: current)")
    p.add_argument("--note", default=None,
                   help="one optional line — public facts only, no hidden cards")
    p.add_argument("--error", action="append", default=[],
                   help="exact technical error, verbatim (repeatable)")
    a = p.parse_args(argv)

    if get is None or logs is None:
        base = (a.url or os.environ.get(ENV_VAR) or DEFAULT_URL).rstrip("/")
        client = AppClient(base)
        get = get or client.player
        logs = logs or client.game_logs
    try:
        pub = public_view(get(a.pid))
        gen = a.generation if a.generation is not None else pub.get("generation")
        entries = logs(a.pid, gen) or []
    except (AppError, AppUnavailable, urllib.error.URLError) as e:
        print(f"seat_report: {e}", file=sys.stderr)
        return EXIT_APP
    try:
        text = compose(pub, entries, note=a.note, errors=tuple(a.error))
    except FirewallBreach as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return EXIT_REFUSED
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
