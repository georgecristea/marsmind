#!/usr/bin/env python3
"""TRIAGE — the hard-trigger classifier of the event feed (lane 1 of the
judgment design). Pure functions + a small CLI; no model, no network.

The listener (P1) appends one entry per app-log line to state/feed.jsonl;
this module decides, from the entry + tracked state + the current plan,
whether the advisor must LOOK at it now. Over-trigger is intentional:
a missed attack costs a game, a spurious look costs seconds. Plain
production / resource gains that touch nothing stay silent.

FEED ENTRY SCHEMA (state/feed.jsonl, one JSON object per line — P1 writes
the first ten fields via `new_entry`, triage owns the last three):
    ts       str        ISO timestamp of ingestion
    gen      int        generation the line belongs to
    line     int        1-based line number in the app log export (the key
                        `pending` / `handle` address entries by)
    actor    str|null   the acting player's canonical name (null for
                        "Generation N", "You bought …", ignore/unknown)
    kind     str        applog_parser event kind (played, placed, gained,
                        lost, stole, claimed, funded, wgt, used_standard,
                        used_action, first_player, generation, …)
    raw      str        the raw log line
    event    dict       the applog_parser.parse_line() dict
    applied  bool       whether the listener applied it to the engine
    error    str|null   the engine's refusal text when applied is false
    trigger  bool       triage verdict (recomputed by `annotate` while the
                        entry is unhandled)
    reasons  [str]      one line per trigger class that fired
    handled  bool       the advisor looked at it (`handle <line>…`);
                        a handled entry is never re-annotated
    handledNote str     optional — the note given to `handle`, or the
                        auto-resolve note of a stale generation trigger

TRIGGER CLASSES (classify):
  a  attack / removal / steal targeting me (resources, production, plants)
  b  any milestone claim or award funding by anyone
  c  any global parameter step (temperature / oxygen / oceans, WGT too) —
     the reason names the remaining clock steps and the hand cards whose
     requirement window that parameter closes. SUPPRESSED when the raising
     player is me and the change is the visible result of a plan step this
     generation that is already EXECUTED (done, not skipped): that step
     priced the change when it was written, so the banner is pure noise
     (P9 #8). An UNPLANNED own change still fires.
  d  the event references a hex, card, milestone/award or race metric that
     an OPEN 🔁 (volatility "recheck") step of the current plan or draft
     names (step summary, cue, event args, mapHighlight). SCOPED to feed
     lines newer than the plan itself (plan["feedCursor"], written by
     planlib at set time; generation fallback for older plans) and never
     fired by my own actions — see plan_in_scope
  e  an opponent crossing a race threshold: within 1 step of an unclaimed
     milestone, or reaching / overtaking me on a funded award (races.py
     before vs after when game_before is given; otherwise the current
     table gated on the event touching that metric). Funding an award
     re-evaluates its race for the WHOLE table: that is ONE fact, emitted
     on the funding line itself, and award races are never back-dated onto
     lines older than the funding (`context["decidedAt"]`, built by
     `feed_context` — P9 #9)
  f  first-player change / generation turnover — the one generation-SCOPED
     class: `triage_feed` auto-resolves such an entry once its generation is
     over (stale_gen_trigger), so gen-1 turnovers never crowd the gen-8 list
  g  an opponent reaching 7+ plants (asteroid target rule, KB 06)

AUTO-RESOLUTION (a pending entry that stops being pending on its own):
  · a generation-scoped class-f trigger once its generation is over
    (stale_gen_trigger)
  · an entry whose EVERY reason has a dead premise (dead_premise, P9 #10):
    a race line for a milestone already claimed (or with no slot left) or
    for a funded award I now lead again, and a requirement-window line
    whose named cards have left my hand — plus a parameter line from a
    past generation that names no card still in hand. Unbounded backlog
    was 32 entries by generation 11 in the P9 game, and the banner only
    ever names the newest few.
Both keep trigger + reasons (the feed is a record) and set handled +
handledNote, in `triage_feed` AND in `pending(path, game, …)` — the
listener banner and `turn.py go` read the feed without re-classifying.

Library:
    classify(entry, game, setup, plan, game_before=None, db=None,
             context=None) -> (bool, [str])
    new_entry(event, line, gen, raw, ts=None, applied=True, error=None)
    triage_feed(path, game, setup, plan) -> [entry]   (annotates in place)
    read_feed(path) / pending(path, game, setup) / handle(path, lines, note)
CLI:
    triage.py annotate [--feed F]      classify every unhandled entry
    triage.py pending  [--feed F]      "#<line> <actor> <kind>: <reasons>"
    triage.py handle <line>… [--note N]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import clock
import menu
import planlib
import races
import tmlib
from menu import MILESTONE_METRIC, MILESTONE_NEED
from tmlib import AWARDS, AWARD_COSTS, MAX_MILESTONES, MILESTONES, EventError

PLANT_TARGET = 7                      # asteroid-target rule (strategy/06)
AUTO_PREFIX = "auto-resolved:"
AUTO_RESOLVED = "auto-resolved: generation-scoped trigger"
DEAD_PREMISE = "auto-resolved: premise dead"
GLOBAL_PARAMS = ("temperature", "oxygen", "oceans")
_STANDARD_GLOBAL = {"asteroid": "temperature", "convert_heat": "temperature"}
_DB_GLOBAL_KEY = {"temperature": "temperature", "oxygen": "oxygen"}
_ALL_RACES = tuple(MILESTONES) + tuple(AWARDS)
_GRID_REF = re.compile(r"\b([A-J])(\d)\b")


# ── entry construction (shared with the listener) ────────────────────
def new_entry(event: dict, line: int, gen: int, raw: str | None = None,
              ts: str | None = None, applied: bool = True,
              error: str | None = None) -> dict:
    """One feed entry in the documented schema (see module docstring)."""
    kind = event.get("kind", "unknown")
    return {"ts": ts or _dt.datetime.now().isoformat(timespec="seconds"),
            "gen": gen, "line": line,
            "actor": event.get("player"), "kind": kind,
            "raw": raw if raw is not None else event.get("raw", ""),
            "event": {k: v for k, v in event.items() if k not in ("line", "raw")},
            "applied": applied, "error": error,
            "trigger": False, "reasons": [], "handled": False}


# ── helpers ──────────────────────────────────────────────────────────
def _me(game: dict) -> str:
    return game["me"]["name"]


def _is_opponent(game: dict, name) -> bool:
    return bool(name) and name != _me(game)


def _pool(game: dict, name):
    try:
        return tmlib.player_pool(game, name)
    except EventError:
        return None


def _card(name: str, db: dict) -> dict | None:
    return menu._card(name or "", db)


def _space(ref) -> str | None:
    """Numeric ids and grid refs (C4) → the board's space id, or None."""
    if ref is None:
        return None
    s = str(ref).strip()
    if s.isdigit():
        return str(int(s))          # "04" and "4" are the same hex
    try:
        return str(int(tmlib.grid_to_space(s)))
    except (EventError, ValueError):
        return None


def _flatten(obj) -> list[str]:
    if isinstance(obj, dict):
        return [t for v in obj.values() for t in _flatten(v)]
    if isinstance(obj, (list, tuple)):
        return [t for v in obj for t in _flatten(v)]
    if obj is None or isinstance(obj, bool):
        return []
    return [str(obj)]


def _global_steps(event: dict, db: dict) -> dict:
    """{param: steps} the event raises (WGT, tile, standard project, card)."""
    kind = event.get("kind")
    if kind == "wgt":
        p = event.get("param")
        return {p: 1} if p in GLOBAL_PARAMS else {}
    if kind in ("placed", "final_placed"):
        tile = str(event.get("tile", "")).lower()
        if tile == "ocean":
            return {"oceans": 1}
        if tile == "greenery":
            return {"oxygen": 1}
        return {}
    if kind == "used_standard":
        p = _STANDARD_GLOBAL.get(event.get("project"))
        return {p: 1} if p else {}
    if kind == "played":
        info = _card(event.get("card"), db)
        if not info:
            return {}
        out = {}
        for k, n in ((info.get("behavior") or {}).get("global") or {}).items():
            if k in _DB_GLOBAL_KEY and isinstance(n, int) and n > 0:
                out[_DB_GLOBAL_KEY[k]] = n
        # oceans print their own "placed ocean tile" line — not counted here
        return out
    return {}


def _window_cards(game: dict, param: str, db: dict) -> tuple[list[str], list[str]]:
    """(min-window cards, max-window cards) in hand whose requirement text
    references `param`. A RAISE opens a `min` window and closes a `max`
    one — saying "closing" for both was P8 #8."""
    needles = {"temperature": ("°c", "temperature"),
               "oxygen": ("o2", "%", "oxygen"),
               "oceans": ("ocean",)}[param]
    mins, maxes = [], []
    for name in game["me"].get("hand") or []:
        info = _card(name, db)
        req = str((info or {}).get("requirements") or "").lower()
        if not req or not any(n in req for n in needles):
            continue
        label = f"{info['name']} ({info['requirements']})"
        (maxes if req.lstrip().startswith("max") else mins).append(label)
    return mins, maxes


def _metrics_touched(event: dict, db: dict) -> set[str]:
    """Milestones/awards whose metric the actor's event moves."""
    kind = event.get("kind")
    res = event.get("resource")
    t: set[str] = set()
    if kind == "played":
        info = _card(event.get("card"), db) or {}
        tags = info.get("tags") or []
        beh = info.get("behavior") or {}
        if info.get("type") != "event":
            if "building" in tags:
                t.add("Builder")
            if "science" in tags:
                t.add("Scientist")
        if "city" in beh:
            t |= {"Mayor", "Landlord"}
        if "tile" in beh:
            t.add("Landlord")
        if beh.get("global"):
            t.add("Terraformer")
        mcp = (beh.get("production") or {}).get("megacredits")
        if mcp and (not isinstance(mcp, int) or mcp > 0):   # dicts = @dynamic
            t.add("Banker")
        stock = beh.get("stock") or {}
        if stock.get("heat"):
            t.add("Thermalist")
        if stock.get("steel") or stock.get("titanium"):
            t.add("Miner")
    elif kind in ("placed", "final_placed"):
        tile = str(event.get("tile", "")).lower()
        if tile == "city":
            t |= {"Mayor", "Landlord"}
        elif tile == "greenery":
            t |= {"Gardener", "Landlord", "Terraformer"}
        elif tile == "ocean":
            t.add("Terraformer")
        else:
            t.add("Landlord")
    elif kind == "used_standard":
        proj = event.get("project")
        if proj in _STANDARD_GLOBAL or proj in ("aquifer", "greenery", "convert_plants"):
            t.add("Terraformer")
        if proj == "city":
            t |= {"Mayor", "Landlord"}
        if proj in ("greenery", "convert_plants"):
            t |= {"Gardener", "Landlord"}
    elif kind in ("gained", "stole"):
        if res == "tr":
            t.add("Terraformer")
        elif res == "heat":
            t.add("Thermalist")
        elif res in ("steel", "titanium"):
            t.add("Miner")
        if kind == "stole" and event.get("prod") and res == "mc":
            t.add("Banker")
    elif kind == "gained_prod" and res == "mc":
        t.add("Banker")
    elif kind in ("kept", "bought", "drew"):
        t.add("Planner")
    return t


# ── trigger classes ──────────────────────────────────────────────────
def _attack(entry: dict, game: dict) -> list[str]:
    ev, me = entry["event"], _me(game)
    kind = ev.get("kind")
    n, res = ev.get("n"), ev.get("resource")
    if kind == "lost" and ev.get("player") == me and ev.get("by"):
        return [f"attack: {ev['by']} removed {n} {res} from you"]
    if kind == "lost_prod" and ev.get("player") == me and ev.get("by"):
        return [f"attack: {ev['by']} cut your {res} production by {n}"]
    if kind == "stole" and ev.get("from") == me:
        what = f"{res} production" if ev.get("prod") else res
        return [f"attack: {ev.get('player')} stole {n} {what} from you"]
    return []


def _claims(entry: dict, game: dict) -> list[str]:
    ev = entry["event"]
    if ev.get("kind") == "claimed":
        claimed = dict(game.get("milestonesClaimed") or {})
        left = max(0, MAX_MILESTONES - len(claimed | {ev.get("milestone"): 1}))
        return [f"milestone: {ev.get('player')} claimed {ev.get('milestone')} "
                f"— {left} slot(s) left"]
    if ev.get("kind") == "funded":
        funded = dict(game.get("awardsFunded") or {})
        k = len(funded | {ev.get("award"): 1})
        nxt = (f"next slot {AWARD_COSTS[k]} MC" if k < len(AWARD_COSTS)
               else "all award slots used")
        return [f"award: {ev.get('player')} funded {ev.get('award')} — {nxt}; "
                "re-read the RACES block"]
    return []


def _step_tokens(step: dict) -> tuple[set[str], set[str]]:
    """(lowercased event arguments, board spaces) a plan step names. Only
    the step's OWN events and mapHighlight — never the prose summary, which
    would match half the log."""
    args: list[str] = []
    for e in step.get("events") or []:
        args += _flatten(e.get("args")) + _flatten(e.get("kwargs"))
    if step.get("mapHighlight"):
        args.append(str(step["mapHighlight"]))
    return {a.lower() for a in args}, {_space(a) for a in args} - {None}


def executed_step(entry: dict, plan: dict | None, game: dict) -> str | None:
    """The id of the EXECUTED plan step this own feed line is the visible
    result of, or None. A step that is done (and not skipped) already
    priced its own parameter change in its summary, so re-raising it as a
    judgment trigger costs a round-trip for nothing (P9 #8).

    Matching is by the step's own event ARGUMENTS: the hex a `place` names,
    the card a `play` / `use_action` names, the project a `standard` names.
    Only this generation's plan counts — hexes and card names are unique,
    but "greenery" is not."""
    if not plan or not isinstance(plan.get("steps"), list):
        return None
    if not entry.get("actor") or entry["actor"] != _me(game):
        return None
    pgen, egen = plan.get("generation"), entry.get("gen")
    if isinstance(pgen, int) and isinstance(egen, int) and pgen != egen:
        return None
    ev = entry["event"]
    kind = ev.get("kind")
    space = _space(ev.get("space")) if kind in ("placed", "final_placed") else None
    names = [str(ev[k]).lower() for k in ("card", "project", "milestone", "award")
             if ev.get(k)]
    if not space and not names:
        return None
    for step in plan["steps"]:
        if not step.get("done") or step.get("skipped"):
            continue
        args, spaces = _step_tokens(step)
        if (space and space in spaces) or any(n in args for n in names):
            return str(step.get("id"))
    return None


def _globals(entry: dict, game: dict, db: dict,
             plan: dict | None = None) -> list[str]:
    steps = _global_steps(entry["event"], db)
    if not steps:
        return []
    if executed_step(entry, plan, game):
        return []                         # my own priced plan step (P9 #8)
    left = clock.remaining_steps(game["globals"])
    out = []
    for param, n in steps.items():
        who = entry.get("actor") or "World Government"
        via = " (WGT, no TR)" if entry["event"].get("kind") == "wgt" else ""
        mins, maxes = _window_cards(game, param, db)
        parts = ([f"windows opening: {', '.join(mins)}"] if mins else []) + \
                ([f"windows closing: {', '.join(maxes)}"] if maxes else [])
        win = "; ".join(parts) or f"no hand requirement windows on {param}"
        out.append(f"global: {who} raised {param} +{n}{via} → {left[param]} "
                   f"steps left on {param} (clock shortens; re-run clock.py); "
                   f"{win}")
    return out


def plan_in_scope(entry: dict, plan: dict | None, game: dict | None = None) -> bool:
    """Plan-relative reasons (class d) are about what happened SINCE the
    plan was composed. `plan["feedCursor"]` is the last feed line at set
    time (planlib writes it); older lines are history the advisor already
    priced in — re-matching them against every new plan produced 15-22
    stale "plan:" triggers per generation (P8 #14). Plans written before
    the cursor existed fall back to the plan's generation. My OWN actions
    never disrupt my own plan."""
    if not plan:
        return False
    if game is not None and entry.get("actor") and entry["actor"] == _me(game):
        return False
    cursor, line = plan.get("feedCursor"), entry.get("line")
    if isinstance(cursor, int) and isinstance(line, int):
        return line > cursor
    pgen, egen = plan.get("generation"), entry.get("gen")
    if isinstance(pgen, int) and isinstance(egen, int):
        return egen >= pgen
    return True


def _plan_hits(entry: dict, plan: dict | None, db: dict,
               game: dict | None = None) -> list[str]:
    if not plan or not isinstance(plan.get("steps"), list):
        return []
    if not plan_in_scope(entry, plan, game):
        return []
    ev = entry["event"]
    kind = ev.get("kind")
    card = ev.get("card") if kind in ("played", "used_action", "card_resource",
                                      "copied", "first_action") else None
    space = _space(ev.get("space")) if kind in ("placed", "final_placed", "wgt") else None
    named = ev.get("milestone") or ev.get("award")
    touched = _metrics_touched(ev, db)
    out = []
    for step in plan["steps"]:
        if step.get("done") or step.get("volatility") != "recheck":
            continue
        texts = [str(step.get("summary") or ""), str(step.get("cue") or "")]
        args: list[str] = []
        for e in step.get("events") or []:
            args += _flatten(e.get("args")) + _flatten(e.get("kwargs"))
        if step.get("mapHighlight"):
            args.append(str(step["mapHighlight"]))
        blob = " ".join(texts + args).lower()
        spaces = {_space(a) for a in args} - {None}
        for m in _GRID_REF.finditer(" ".join(texts).upper()):
            s = _space(m.group(0))
            if s:
                spaces.add(s)
        for a in re.findall(r"\b(?:hex|space|on)\s+(\d{1,2})\b", " ".join(texts).lower()):
            spaces.add(str(int(a)))
        sid = step.get("id")
        if space and space in spaces:
            out.append(f"plan: 🔁 step {sid} targets hex {space} — "
                       f"{entry.get('actor')} just placed {ev.get('tile')} there")
        if card and card.lower() in blob:
            out.append(f"plan: 🔁 step {sid} names {card} — {entry.get('actor')} "
                       f"{kind.replace('_', ' ')} it")
        if named and named.lower() in blob:
            out.append(f"plan: 🔁 step {sid} names {named} — "
                       f"{entry.get('actor')} {kind} it")
        for race in _ALL_RACES:
            if race in touched and race.lower() in blob and race != named:
                out.append(f"plan: 🔁 step {sid} races {race} — "
                           f"{entry.get('actor')}'s {kind.replace('_', ' ')} moves "
                           f"that metric")
    return out


def _row(table: dict, name: str) -> dict | None:
    return next((p for p in table["players"] if p["name"] == name), None)


def _award_row(table: dict, name: str, award: str) -> int:
    row = _row(table, name)
    return ((row or {}).get("awards") or {}).get(award) or 0


def _funding_race(entry: dict, game: dict, setup: dict, db: dict) -> list[str]:
    """The award race, re-evaluated ONCE at the moment the award is funded.

    Funding turns a metric nobody was scoring into a scored one, so every
    earlier play on that metric suddenly "crosses" — in the P9 game one
    Scientist funding back-dated the same race onto five plays from four
    generations (P9 #9). The fact belongs to the funding line."""
    ev = entry["event"]
    if ev.get("kind") != "funded":
        return []
    award = ev.get("award")
    funded = game.get("awardsFunded") or {}
    if award not in AWARDS or award not in funded:
        return []
    table = races.race_table(game, setup or {}, db)
    me = _me(game)
    mine = _award_row(table, me, award)
    out = []
    for p in table["players"]:
        if p["name"] == me:
            continue
        opp = p["awards"].get(award) or 0
        if opp <= 0 or opp < mine:
            continue
        rel = "ties you" if opp == mine else "overtakes you"
        out.append(f"race: {p['name']} {rel} on {award} (funded by "
                   f"{funded[award]}): {opp} vs your {mine}")
    return out


def _races(entry: dict, game: dict, setup: dict, game_before: dict | None,
           db: dict, context: dict | None = None) -> list[str]:
    actor, ev = entry.get("actor"), entry["event"]
    if not _is_opponent(game, actor) or _pool(game, actor) is None:
        return []
    touched = _metrics_touched(ev, db)
    if not touched:
        return []
    after = races.race_table(game, setup, db)
    before = races.race_table(game_before, setup, db) if game_before else None
    row_a, row_b = _row(after, actor), _row(before, actor) if before else None
    if row_a is None:
        return []
    me = _me(game)
    me_a, me_b = _row(after, me), _row(before, me) if before else None
    out = []
    claimed = game.get("milestonesClaimed") or {}
    if len(claimed) < MAX_MILESTONES:
        for ms in MILESTONES:
            if ms in claimed or ms not in touched:
                continue
            have, need = row_a["milestones"].get(ms), MILESTONE_NEED[ms]
            if have is None or have < need - 1:
                continue
            if row_b is not None:
                hb = row_b["milestones"].get(ms)
                if hb is not None and hb >= need - 1:
                    continue                      # was already close
            state = "can claim NOW" if have >= need else "is 1 step from"
            out.append(f"race: {actor} {state} {ms} ({MILESTONE_METRIC[ms]} "
                       f"{have}/{need})")
    funded = game.get("awardsFunded") or {}
    decided = (context or {}).get("decidedAt") or {}
    for a in AWARDS:
        if a not in funded or a not in touched:
            continue
        at, line = decided.get(a), entry.get("line")
        if isinstance(at, int) and isinstance(line, int) and line < at:
            continue                # the award did not exist yet (P9 #9)
        opp, mine = row_a["awards"].get(a) or 0, (me_a or {}).get("awards", {}).get(a) or 0
        if opp <= 0 or opp < mine:
            continue
        if row_b is not None and me_b is not None:
            ob, mb = row_b["awards"].get(a) or 0, me_b["awards"].get(a) or 0
            if ob > 0 and ob >= mb:
                continue                          # already level/ahead before
        rel = "ties you" if opp == mine else "overtakes you"
        out.append(f"race: {actor} {rel} on {a} (funded by {funded[a]}): "
                   f"{opp} vs your {mine}")
    return out


def _turn_order(entry: dict) -> list[str]:
    ev = entry["event"]
    if ev.get("kind") == "first_player":
        return [f"turn order: first player is now {ev.get('player')}"]
    if ev.get("kind") == "generation":
        return [f"generation {ev.get('n')} starts — turn order rotates, "
                "re-run produce/advise"]
    return []


def stale_gen_trigger(entry: dict, game: dict) -> str | None:
    """Class f is scoped to ONE generation: once the table has moved on,
    "generation 2 starts" and "first player is now Anna" are history, not
    live triggers, and they dilute the list the judgment lane reads. Returns
    the auto-resolve note, or None when the entry still matters — any other
    reason (a race, an open 🔁 step) keeps the entry pending forever."""
    reasons = entry.get("reasons") or []
    scoped = _turn_order(entry)
    if not scoped or not reasons or any(r not in scoped for r in reasons):
        return None
    egen, gen = entry.get("gen"), game.get("generation")
    if not isinstance(egen, int) or not isinstance(gen, int) or egen >= gen:
        return None
    return f"{AUTO_RESOLVED} — generation {egen} is over (generation {gen} now)"


# ── dead premises (P9 #10) ───────────────────────────────────────────
def _dead_race(reason: str, entry: dict, game: dict, setup: dict | None,
               db: dict | None) -> str | None:
    """A race line whose race is over. Milestones: claimed by anyone, or no
    slot left — nobody can claim it again. Awards: the opponent the line
    names no longer reaches me on that metric."""
    if not (reason.startswith("race: ") or reason.startswith("plan: ")):
        return None
    claimed = game.get("milestonesClaimed") or {}
    for ms in MILESTONES:
        if f" {ms} (" not in reason and f"races {ms} " not in reason:
            continue
        if ms in claimed:
            return (f"{ms} was claimed by {claimed[ms]} — nobody can claim "
                    "it again")
        if len(claimed) >= MAX_MILESTONES:
            return f"every milestone slot is used — {ms} is unreachable"
        return None
    funded = game.get("awardsFunded") or {}
    actor = entry.get("actor")
    for a in AWARDS:
        if f" on {a} (funded by" not in reason:
            continue
        if a not in funded:
            return f"{a} is not funded"
        if not _is_opponent(game, actor) or _pool(game, actor) is None:
            return None
        table = races.race_table(game, setup or {}, db)
        opp, mine = _award_row(table, actor, a), _award_row(table, _me(game), a)
        if opp > 0 and opp >= mine:
            return None
        return f"{actor} no longer reaches you on {a} ({opp} vs your {mine})"
    return None


def _dead_window(reason: str, entry: dict, game: dict) -> str | None:
    """A parameter line whose requirement window is gone: the cards it named
    were sold or played, so the window it warned about can never be used.

    Only the WINDOW is a dead premise — a parameter line without one still
    carries the clock, and pruning those would silence a generation's global
    steps the moment the generation turned over (that is the narrower
    stale_gen_trigger's job, class f only)."""
    if not reason.startswith("global:"):
        return None
    if "windows opening:" not in reason and "windows closing:" not in reason:
        return None
    hand = [c for c in (game["me"].get("hand") or []) if c]
    if any(c in reason for c in hand):
        return None
    return "the requirement-window cards it names have left my hand"


def dead_premise(entry: dict, game: dict, setup: dict | None = None,
                 db: dict | None = None) -> str | None:
    """The auto-resolve note when EVERY reason of a pending entry rests on a
    premise that cannot come back, else None. One live reason keeps the whole
    entry pending — over-trigger stays the safe direction."""
    reasons = entry.get("reasons") or []
    if not reasons:
        return None
    why = []
    for r in reasons:
        d = (_dead_race(r, entry, game, setup, db)
             or _dead_window(r, entry, game))
        if not d:
            return None
        why.append(d)
    seen = list(dict.fromkeys(why))
    return f"{DEAD_PREMISE} — " + "; ".join(seen)


def auto_resolve(entry: dict, game: dict, setup: dict | None = None,
                 db: dict | None = None) -> str | None:
    """Every reason a pending entry stops being pending without the advisor:
    its generation is over, or its premise is dead."""
    try:
        return (stale_gen_trigger(entry, game)
                or dead_premise(entry, game, setup, db))
    except Exception:
        return None                       # never drop a trigger over a bug


def _plants(entry: dict, game: dict) -> list[str]:
    actor, ev = entry.get("actor"), entry["event"]
    if not _is_opponent(game, actor):
        return []
    if not (ev.get("kind") in ("gained", "stole") and ev.get("resource") == "plants"):
        return []
    pool = _pool(game, actor)
    have = ((pool or {}).get("resources") or {}).get("plants")
    if isinstance(have, int) and have >= PLANT_TARGET:
        return [f"asteroid target: {actor} holds {have} plants (≥{PLANT_TARGET}) "
                "— plant-removal cards are live"]
    return []


def classify(entry: dict, game: dict, setup: dict | None, plan: dict | None,
             game_before: dict | None = None, db: dict | None = None,
             context: dict | None = None) -> tuple[bool, list[str]]:
    """The hard-trigger verdict for one feed entry. `game` is the tracked
    state AFTER the event (the listener applied it); `game_before` enables
    true before/after race crossings; `context` is the feed-wide knowledge
    a single entry cannot have (`feed_context`: where each award was funded,
    so a re-derived race is never back-dated onto older lines)."""
    ev = entry.get("event") or {}
    if ev.get("kind") in ("ignore", "unknown", None):
        return False, []
    db = menu._db(db)
    reasons: list[str] = []
    reasons += _attack(entry, game)
    reasons += _claims(entry, game)
    reasons += _globals(entry, game, db, plan)
    reasons += _plan_hits(entry, plan, db, game)
    reasons += _funding_race(entry, game, setup or {}, db)
    reasons += _races(entry, game, setup or {}, game_before, db, context)
    reasons += _turn_order(entry)
    reasons += _plants(entry, game)
    return bool(reasons), reasons


# ── feed store ───────────────────────────────────────────────────────
def feed_path(store: tmlib.Store) -> Path:
    return store.state_dir / "feed.jsonl"


def read_feed(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for raw in p.read_text().splitlines():
        if raw.strip():
            out.append(json.loads(raw))
    return out


def write_feed(path, entries: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))
    tmp.replace(p)


def feed_context(entries: list[dict]) -> dict:
    """The feed-wide facts a single entry cannot see. Today: `decidedAt`,
    the line where each award was funded / milestone claimed — the date a
    re-derived race trigger must carry, instead of one copy per historical
    play (P9 #9)."""
    at: dict[str, int] = {}
    for e in entries:
        ev = e.get("event") or {}
        kind = ev.get("kind")
        name = (ev.get("award") if kind == "funded" else
                ev.get("milestone") if kind == "claimed" else None)
        line = e.get("line")
        if name and isinstance(line, int) and name not in at:
            at[name] = line
    return {"decidedAt": at}


def triage_feed(path, game: dict, setup: dict | None, plan: dict | None,
                db: dict | None = None) -> list[dict]:
    """Annotate every UNHANDLED entry in place (trigger + reasons against
    the current state and plan). Handled entries are frozen. Idempotent.
    A trigger that resolves itself — its generation is over, or its premise
    is dead — is auto-resolved here: trigger and reasons are kept (the feed
    is a record), it just stops being pending."""
    entries = read_feed(path)
    context = feed_context(entries)
    for e in entries:
        e.setdefault("handled", False)
        if e["handled"]:
            e.setdefault("trigger", False); e.setdefault("reasons", [])
            continue
        trig, reasons = classify(e, game, setup, plan, db=db, context=context)
        e["trigger"], e["reasons"] = trig, reasons
        note = auto_resolve(e, game, setup, db) if trig else None
        if note:
            e["handled"], e["handledNote"] = True, note
    write_feed(path, entries)
    return entries


def pending(path, game: dict | None = None, setup: dict | None = None,
            db: dict | None = None) -> list[dict]:
    """Unhandled hard triggers. With `game`, a trigger that resolves itself
    (generation over, premise dead) is auto-resolved here too (persisted
    with its note), so the listener banner and `turn.py go` — which read the
    feed without re-classifying — see the same list as the sweep. Without
    `setup` the award-standings premise is left alone; the milestone and
    requirement-window premises need no setup."""
    entries = read_feed(path)
    if game is not None:
        changed = False
        for e in entries:
            if e.get("trigger") and not e.get("handled"):
                note = auto_resolve(e, game, setup, db)
                if note:
                    e["handled"], e["handledNote"] = True, note
                    changed = True
        if changed:
            write_feed(path, entries)
    return [e for e in entries if e.get("trigger") and not e.get("handled")]


def render_pending(entries: list[dict]) -> list[str]:
    return [f"#{e['line']} {e.get('actor') or '-'} {e.get('kind')}: "
            + "; ".join(e.get("reasons") or [])
            for e in entries]


def handle(path, lines, note: str = "") -> int:
    """Mark the entries with these line numbers handled; returns the count."""
    want = {int(x) for x in lines}
    entries = read_feed(path)
    n = 0
    for e in entries:
        if e.get("line") in want and not e.get("handled"):
            e["handled"] = True
            e["handledNote"] = note or None
            n += 1
    write_feed(path, entries)
    return n


# ── CLI ──────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Hard-trigger triage of the "
                                "event feed (state/feed.jsonl).")
    def common(parser, top: bool) -> None:
        # the same options before OR after the subcommand; a subparser's
        # SUPPRESS default never clobbers a value given at the top level
        d = (lambda v: v) if top else (lambda v: argparse.SUPPRESS)
        parser.add_argument("--root", default=d("."),
                            help="repo root (state/ = active game)")
        parser.add_argument("--state", default=d(None),
                            help="a game folder (games/<date>-gameN) instead of state/")
        parser.add_argument("--feed", default=d(None),
                            help="feed file (default state/feed.jsonl)")
    common(p, True)
    sub = p.add_subparsers(dest="cmd", required=True)
    common(sub.add_parser("annotate", help="classify every unhandled entry"), False)
    common(sub.add_parser("pending", help="trigger and not handled, one line each"), False)
    h = sub.add_parser("handle", help="mark entries handled")
    common(h, False)
    h.add_argument("lines", nargs="+", type=int)
    h.add_argument("--note", default="")
    a = p.parse_args(argv)

    store = tmlib.Store(a.root, state_dir=a.state)
    path = Path(a.feed) if a.feed else feed_path(store)
    if a.cmd == "annotate":
        try:
            game, setup = store.load_game(), store.load_setup()
        except FileNotFoundError as e:
            print(f"ERROR: {e} — is a game active?", file=sys.stderr)
            return 1
        try:
            plan = planlib.load_plan(store)
        except EventError:
            plan = None
        entries = triage_feed(path, game, setup, plan)
        pend = [e for e in entries if e.get("trigger") and not e.get("handled")]
        auto = [e for e in entries
                if str(e.get("handledNote") or "").startswith(AUTO_PREFIX)]
        print(f"annotated {len(entries)} entries — {len(pend)} pending"
              + (f", {len(auto)} auto-resolved (generation-scoped / dead "
                 f"premise)" if auto else ""))
        for line in render_pending(pend):
            print(line)
        return 0
    if a.cmd == "pending":
        rows = render_pending(pending(path))
        print("\n".join(rows) if rows else "no pending triggers")
        return 0
    if a.cmd == "handle":
        n = handle(path, a.lines, a.note)
        try:
            gen = store.load_game().get("generation", "?")
            store.log(f"G{gen}", f"triage: handled #{', #'.join(str(x) for x in a.lines)}"
                      + (f" — {a.note}" if a.note else ""))
        except FileNotFoundError:
            pass
        print(f"handled {n} entr{'y' if n == 1 else 'ies'}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
