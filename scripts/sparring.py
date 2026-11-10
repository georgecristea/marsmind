#!/usr/bin/env python3
"""Sparring driver (DEV TOOL — not part of the table engine).

Plays a seat on the open-source terraforming-mars app via its JSON API —
no browser. Used to drive the practice opponent ("Ana") fast during
development, per agents/sparring-partner.md.

    python3 scripts/sparring.py state <pid>                 # the decision view (below)
    python3 scripts/sparring.py wait <pid> [--until-gen N]  # exit 3 = SCOPE END
        both print ONE view from one fetch: `gen N | <prompt shape>`, your
        resources + production + TR, the globals, milestone/award slots
        (who took which), one PUBLIC row per opponent (TR, cities,
        greeneries, tableau size, MC) — no raw curl needed to decide.
        TIMEOUT (exit 2) prints the seconds waited and the run of
        consecutive timeouts. wait/send mark seats/<pid>/latency.jsonl
        (scripts/latency.py shape) so seat think-time is measured.
    python3 scripts/sparring.py play <pid> "<Card>" --mc 12 [--steel N --titanium N --heat N]
    python3 scripts/sparring.py sp <pid> <power|asteroid|aquifer|greenery|city>
        play/sp accept --space ID --choice N --target COLOR for the follow-up prompt
    python3 scripts/sparring.py action <pid> "<Card>"       # blue-card action
    python3 scripts/sparring.py claim <pid> <Milestone> | fund <pid> <Award>
        when there is nothing to send these print WHY — slots used and by
        whom, already taken, metric shortfall, or the fee — never silence
    python3 scripts/sparring.py choose <pid> <N|title> [--target COLOR|NAME] [--space HEX]
                                       [--cards "<Card>" ...] [--amount N]
        'or' prompt (Select one option). The SELECTED branch's TYPE decides
        the extra flag: a `player` branch needs --target, a `space` branch
        --space, a `card` branch --cards, an `amount` branch --amount; a plain
        `option` branch needs nothing. A missing flag is refused BEFORE
        transmit with the flag named — never a bare option into a typed branch
        (that was HTTP 400 "Not a valid SelectPlayerResponse"). A submenu
        branch is addressed with a dotted index: choose <pid> 1.0
    python3 scripts/sparring.py space <pid> <hex>           # 'space' prompt — ALSO the
        final-greenery prompt ("Place any final greenery from plants"), which
        the app wraps as an `or` around the space branch; the verb wraps it
    python3 scripts/sparring.py space <pid> --skip          # the "Don't place a greenery" branch
    python3 scripts/sparring.py target <pid> <color>        # 'player' prompt
    python3 scripts/sparring.py pick <pid> ["<Card>" ...]   # 'card' prompt; no names = none
    python3 scripts/sparring.py pass <pid> | send <pid> '<raw json>'

App URL: `--url U`, else $PHOBOS_APP_URL, else http://localhost:8080.
All HTTP goes through scripts/appapi.py (AppClient); every prompt response
is composed there too (appapi.or_branch_response — the SAME composer the
advisor's execute.py uses, so both paths accept the same prompts).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appapi
import latency
from appapi import AppClient, AppError, AppUnavailable, Ask
# the wire shapes and THE prompt composer live in appapi (D1: one composer,
# two callers — this seat driver and the advisor's execute.py)
from appapi import (option, or_choice, cards, space, target_player,
                    or_branch_response, space_prompt_response,
                    prompt_title as _title)
from tmlib import AWARD_COSTS, MAX_MILESTONES, MILESTONE_COST

BASE = os.environ.get(appapi.ENV_VAR) or appapi.DEFAULT_URL

# ── seat latency marks (S6 / speed-plan 3.1) ─────────────────
#
# The advisor's think-time per decision is reconstructed from the marks in
# state/latency.jsonl; a seat had no trace at all, so its time was a
# subtraction, not a measurement. `wait` marks the listen phase (its end
# note is the decision boundary: GO / TIMEOUT / SCOPE END / GAME ENDED)
# and `send` — which every verb goes through — marks the execute phase,
# both into the SEAT's own store, seats/<pid>/latency.jsonl (the folder
# session.py seat-init builds), in the advisor's file shape. A mark that
# cannot be written never stops a move.

SEATS_ROOT = Path(".")          # repo root; seats/<pid>/ lives under it
_now = time.monotonic
_LAST_GEN: int | None = None    # generation of the last view fetched


def seat_marks_path(pid: str) -> Path:
    return latency.seat_path(pid, root=SEATS_ROOT)


def seat_mark(pid: str, phase: str, edge: str, note: str = "",
              gen: int | None = None) -> dict | None:
    """One mark into the seat's store; never raises (a trace is not worth
    a lost move). `gen` defaults to the last view's generation, then to the
    seat folder's game.json."""
    try:
        return latency.mark_path(seat_marks_path(pid), phase, edge, note=note,
                                 gen=_LAST_GEN if gen is None else gen)
    except (OSError, ValueError):
        return None


def consecutive_timeouts(pid: str) -> int:
    """How many `wait` calls in a row ended in TIMEOUT (the current one
    included) — read off the seat's own listen marks, no extra file."""
    n = 0
    try:
        marks = latency.read_marks(seat_marks_path(pid))
    except OSError:
        return 1
    for m in reversed(marks):
        if m.get("phase") != "listen" or m.get("edge") != "end":
            continue
        if not str(m.get("note", "")).startswith("TIMEOUT"):
            break
        n += 1
    return n


PAYMENT_KEYS = ("megacredits", "steel", "titanium", "heat", "microbes",
                "floaters", "lunaArchivesScience", "spireScience", "seeds",
                "auroraiData", "kuiperAsteroids", "corruption", "graphene",
                "plants")


# ── response builders (pure; unit-tested) ────────────────────
# option / or_choice / cards / space / target_player: see appapi.

def _payment(mc=0, steel=0, titanium=0, heat=0) -> dict:
    p = {k: 0 for k in PAYMENT_KEYS}
    p.update({"megacredits": mc, "steel": steel, "titanium": titanium,
              "heat": heat})
    return p


def payment(mc=0, steel=0, titanium=0, heat=0) -> dict:
    return {"type": "payment", "payment": _payment(mc, steel, titanium, heat)}


def project_card(card: str, mc=0, steel=0, titanium=0, heat=0) -> dict:
    return {"type": "projectCard", "card": card,
            "payment": _payment(mc, steel, titanium, heat)}


def play_card(waiting_for: dict, card: str, mc=0, steel=0, titanium=0,
              heat=0) -> dict:
    """Build the or-wrapped response that plays `card` from hand.

    The index of the "Play project card" option is BOARD-DEPENDENT —
    the app prepends a "Convert N plants into greenery" option the moment
    the seat can convert, shifting every later index by one. Hardcoding 0
    produced a silent HTTP 400 mid-game, so the index is always looked up
    by title here.
    """
    return or_choice(find_option(waiting_for, "play project card"),
                     project_card(card, mc=mc, steel=steel,
                                  titanium=titanium, heat=heat))


SETUP_PATH = Path(__file__).resolve().parent.parent / "state" / "setup.json"


def _color_of(name: str, players: list[dict] | None = None) -> str | None:
    """A player NAME → their table COLOR. From the caller's /api/player
    view when it is at hand (players[].name/color), else state/setup.json.
    """
    rows = players
    if not rows:
        try:
            rows = json.loads(Path(SETUP_PATH).read_text()).get("players", [])
        except (OSError, json.JSONDecodeError):
            return None
    for p in rows or []:
        if str(p.get("name", "")).lower() == name.lower():
            return p.get("color")
    return None


def find_option(waiting_for: dict, needle: str,
                players: list[dict] | None = None) -> int:
    """Index of the option matching `needle`: a title substring, or — when
    nothing matches — a player NAME whose colour appears in a title.

    The app writes removal prompts by colour ("Remove 7 plants from red"),
    so `sparring.py choose <pid> "Anna"` raised KeyError and the seat lost
    the action (P8 #21).
    """
    titles = [_title(o) for o in waiting_for.get("options", [])]
    for i, title in enumerate(titles):
        if needle.lower() in title.lower():
            return i
    color = _color_of(str(needle), players)
    if color:
        pat = re.compile(rf"\b{re.escape(color)}\b", re.IGNORECASE)
        for i, title in enumerate(titles):
            if pat.search(title):
                return i
    raise KeyError(f"No option matching {needle!r}; have: {titles}")


def nested_or(outer: int, inner: int) -> dict:
    """Milestone claim / award funding: an `or` inside an `or`."""
    return or_choice(outer, or_choice(inner, option()))


def _sub_option(waiting_for: dict, menu: str, name: str) -> dict:
    i = find_option(waiting_for, menu)
    return nested_or(i, find_option(waiting_for["options"][i], name))


def claim_milestone(waiting_for: dict, name: str) -> dict:
    return _sub_option(waiting_for, "claim a milestone", name)


def fund_award(waiting_for: dict, name: str) -> dict:
    return _sub_option(waiting_for, "fund an award", name)


def card_action(waiting_for: dict, card_name: str) -> dict:
    """Blue-card action: a `card` response inside the action-menu `or`."""
    i = find_option(waiting_for, "perform an action")
    names = [c.get("name") for c in waiting_for["options"][i].get("cards", [])]
    if card_name not in names:
        raise KeyError(f"No action card {card_name!r}; have: {names}")
    return or_choice(i, cards([card_name]))


def _is_index_path(which) -> bool:
    return bool(re.fullmatch(r"\d+(\.\d+)*", str(which)))


def choose(waiting_for: dict, which, players: list[dict] | None = None,
           target=None, space=None, cards=None, amount=None) -> dict:
    """Answer an `or` prompt: the branch by index (int, or a dotted path
    "1.0" into a submenu), title substring, or a player NAME (matched to
    the colour the app prints in the title). The INNER response comes
    from the selected branch's own type via appapi.or_branch_response —
    an `option` branch needs nothing; player / space / card / amount
    branches take --target / --space / --cards / --amount, and a missing
    one raises Ask naming the flag (Codex H3a)."""
    idx = (which if isinstance(which, int) or _is_index_path(which)
           else find_option(waiting_for, which, players))
    response, _ = or_branch_response(waiting_for, idx, players=players,
                                     target=target, space=space, cards=cards,
                                     amount=amount)
    return response


def shape(wf) -> str:
    """One-line-per-item rendering of a waitingFor prompt."""
    if wf is None:
        return "NOT WAITING (opponent's move)"
    out = [f"type: {wf.get('type')} | title: {_title(wf)}"]
    for i, opt in enumerate(wf.get("options", [])):
        out.append(f"  [{i}] {_title(opt)} (type {opt.get('type')})")
    for k in ("cards", "spaces", "players"):
        if wf.get(k):
            vals = [c.get("name", c) if isinstance(c, dict) else c
                    for c in wf[k]][:12]
            out.append(f"  {k}: {vals}")
    return "\n".join(out)


def scope_ended(d: dict, until_gen) -> bool:
    g = d.get("game", {})
    return until_gen is not None and (
        g.get("phase") == "end" or (g.get("generation") or 0) > until_gen)


# ── HTTP layer ───────────────────────────────────────────────

def client() -> AppClient:
    """The one HTTP client (scripts/appapi.py), bound to BASE — set by
    --url / $PHOBOS_APP_URL, default localhost:8080."""
    return AppClient(BASE)


def _remember_gen(view: dict) -> dict:
    global _LAST_GEN
    g = (view or {}).get("game") or {}
    if isinstance(g.get("generation"), int):
        _LAST_GEN = g["generation"]
    return view


def get_player(pid: str) -> dict:
    return _remember_gen(client().player(pid))


def send(pid: str, response: dict) -> dict:
    """Transmit one response. Marks the execute phase around the HTTP call
    (start → end, note = the response type, or the error) so the seat's
    think time — GO mark to this start mark — is measurable."""
    seat_mark(pid, "execute", "start")
    try:
        out = client().send(pid, response)
    except AppError as e:
        seat_mark(pid, "execute", "end",
                  note=f"error {e.status} {response.get('type')}")
        if e.status == 400:      # show WHAT shape the seat got wrong
            wf = get_player(pid).get("waitingFor")
            lines = [f"HTTP 400 {e.body}", f"sent: {json.dumps(response)}",
                     "current prompt:", shape(wf)]
            hint = EXPECTED_SHAPE.get((wf or {}).get("type"))
            if hint:
                lines.append(f"expected shape: {hint}")
            if "unknown card name" in str(e.body).lower():
                # P7: this reads like a database fault and is not one. The
                # app lists ONLY cards that are affordable right now AND
                # whose requirements are met, so a card in hand that you
                # cannot pay for simply is not offered. A seat concluded
                # "the app cannot register purchased cards" and quit.
                lines.append(
                    "NOTE: 'Unknown card name' does NOT mean the card is "
                    "missing from the game. The prompt lists only cards you "
                    "can afford AND whose requirements are satisfied — so "
                    "the card is in hand but not playable right now. Check "
                    "your M€ and the global parameters, and play only names "
                    "the prompt actually offers.")
            print("\n".join(lines), file=sys.stderr)
        raise
    except Exception as e:
        seat_mark(pid, "execute", "end",
                  note=f"error {type(e).__name__} {response.get('type')}")
        raise
    seat_mark(pid, "execute", "end", note=f"send {response.get('type')}")
    return out


def follow_up(pid: str, space_id=None, choice=None, target=None,
              get=None, post=None):
    """Answer the follow-up prompt(s) after a play/sp/action — one hop per
    given flag (space → or → player at most), never a loop."""
    get, post = get or get_player, post or send
    answers = {"space": space_id, "or": choice, "player": target}
    for _ in range(3):
        d = get(pid)
        wf = d.get("waitingFor") or {}
        t = wf.get("type")
        if answers.get(t) is None:
            return
        v = answers.pop(t)
        if t == "space":
            post(pid, space(v))
        elif t == "player":
            post(pid, target_player(v))
        else:
            # the selected branch's type may consume the remaining flags
            # (`--choice 0 --target red` on an `or → player` branch)
            resp, used = or_branch_response(
                wf, v, players=d.get("players"), target=answers.get("player"),
                space=answers.get("space"))
            answers.pop(used, None)
            post(pid, resp)


def wait_for_turn(pid: str, timeout: float = 570, interval: float = 2.0,
                  get=None, sleep=None, clock=None):
    """Block until it is `pid`'s turn (waitingFor != None) or the game
    ends; return the player dict, or None on timeout.

    Speedup: polling as separate agent tool calls costs one model
    round-trip PER POLL — the dominant wall-clock sink of a sparring
    game. This loop runs silently server-side inside ONE call at a
    2s interval; the caller sees only the final state. Default timeout
    stays under the Bash tool's 600s ceiling.
    """
    import time as _t
    get = get or get_player
    sleep = sleep or _t.sleep
    clock = clock or _t.monotonic
    start = clock()
    while True:
        d = get(pid)
        if d.get("waitingFor") is not None:
            return d
        if d.get("game", {}).get("phase") == "end":
            return d
        if clock() - start >= timeout:
            return None
        sleep(interval)


def _mc(p: dict):
    return p.get("megacredits", p.get("megaCredits"))


def _tiles_by_color(game: dict) -> dict[str, dict[str, int]]:
    """{color: {"greeneries": n, "cities": n}} from the PUBLIC board
    (game.spaces: TileType enum + owner colour; colony spaces are
    off-Mars). Empty when the view carries no board."""
    out: dict[str, dict[str, int]] = {}
    import verify                       # the one TileType → class mapping
    for s in game.get("spaces") or []:
        t, color = s.get("tileType"), s.get("color")
        if t is None or not color or s.get("spaceType") == "colony":
            continue
        cls = verify._tile_class(verify._tile_name(t))
        if cls in ("greenery", "city"):
            row = out.setdefault(color, {"greeneries": 0, "cities": 0})
            row["greeneries" if cls == "greenery" else "cities"] += 1
    return out


def _slots_line(label: str, rows, total: int) -> str:
    """`milestones 1/3: Builder — Zed · Mayor — open …` (awards alike),
    from game.milestones / game.awards as the app writes them."""
    rows = [r for r in rows or [] if isinstance(r, dict)]
    used = sum(1 for r in rows if r.get("playerName"))
    items = [f"{r.get('name')} — {r.get('playerName') or 'open'}" for r in rows]
    return f"{label} {used}/{total}: " + (" · ".join(items) or "none in this game")


def describe_waiting(pid: str) -> str:
    """The seat's decision view, from ONE player fetch (S7 / speed-plan
    3.2): the prompt shape, own resources and production, TR, the
    globals, milestone/award slots and one PUBLIC row per opponent — so
    no seat needs a raw `curl` over the whole JSON to decide. The first
    line keeps its `gen N | <shape>` format; hands are never shown (the
    view carries only its own, and that stays with the seat)."""
    d = get_player(pid)
    game = d.get("game") or {}
    out = [f"gen {game.get('generation')} | " + shape(d.get("waitingFor"))]
    if d.get("waitingFor") is None:
        return out[0]
    t = d.get("thisPlayer") or {}
    my_color = t.get("color")
    hand_n = t.get("cardsInHandNbr")
    if hand_n is None and isinstance(d.get("cardsInHand"), list):
        hand_n = len(d["cardsInHand"])
    out.append(f"me: {t.get('name')} ({my_color}) · TR {t.get('terraformRating')} · "
               f"{_mc(t)} MC {t.get('steel')} steel {t.get('titanium')} titanium "
               f"{t.get('plants')} plants {t.get('energy')} energy {t.get('heat')} heat"
               + (f" · {hand_n} cards in hand" if hand_n is not None else ""))
    out.append(f"prod: MC {t.get('megacreditProduction')} steel {t.get('steelProduction')} "
               f"titanium {t.get('titaniumProduction')} plants {t.get('plantProduction')} "
               f"energy {t.get('energyProduction')} heat {t.get('heatProduction')}")
    if "temperature" in game or "oxygenLevel" in game or "oceans" in game:
        out.append(f"globals: temperature {game.get('temperature')} °C · "
                   f"oxygen {game.get('oxygenLevel')} % · oceans {game.get('oceans')}/9")
    if "milestones" in game:
        out.append(_slots_line("milestones", game.get("milestones"), MAX_MILESTONES))
    if "awards" in game:
        out.append(_slots_line("awards", game.get("awards"), len(AWARD_COSTS)))
    tiles = _tiles_by_color(game)
    for p in d.get("players") or []:
        if not isinstance(p, dict) or p.get("color") == my_color or (
                p.get("name") and p.get("name") == t.get("name")):
            continue
        mine = tiles.get(p.get("color"), {})
        cities = p.get("citiesCount", mine.get("cities", "?"))
        greens = mine.get("greeneries", "?" if not tiles else 0)
        tab = p.get("tableau")
        parts = [f"TR {p.get('terraformRating')}", f"cities {cities}",
                 f"greeneries {greens}"]
        if isinstance(tab, list):
            parts.append(f"tableau {max(len(tab) - 1, 0)}")     # [0] = corp
        if _mc(p) is not None:
            parts.append(f"{_mc(p)} MC")
        if p.get("cardsInHandNbr") is not None:
            parts.append(f"{p['cardsInHandNbr']} cards in hand")
        out.append(f"opp {p.get('name')} ({p.get('color')}): " + " · ".join(parts))
    return "\n".join(out)


# ── why claim / fund has nothing to send (P9 #11) ────────────
#
# The Anna seat ran `claim <pid> Gardener` all game, got only
# `ERROR: 'No option matching …'`, and concluded the harness was broken.
# It was not: the advisor had swept all three milestone slots, so the app
# correctly stopped offering "claim a milestone". Silence read as a defect
# and the seat abandoned the line — the exact failure agents/seat-kit.md
# warns against twice. Everything below is read from the player view
# (game.milestones / game.awards, thisPlayer), never from a table of names.

MA_KINDS = {
    "claim": {"menu": "claim a milestone", "key": "milestones",
              "noun": "milestone", "past": "claimed", "act": "CLAIM",
              "slots": MAX_MILESTONES},
    "fund": {"menu": "fund an award", "key": "awards",
             "noun": "award", "past": "funded", "act": "FUND",
             "slots": len(AWARD_COSTS)},
}


def ma_fee(kind: str, used: int):
    """What the NEXT claim/funding costs. Milestones are a flat fee; award
    funding climbs with the number already funded (8 / 14 / 20)."""
    if kind == "claim":
        return MILESTONE_COST
    return AWARD_COSTS[used] if used < len(AWARD_COSTS) else None


def _threshold(name: str):
    """(need, metric) for a milestone from the menu's own table, when it is
    importable. Enrichment only — the message stands without it, so an
    unknown or house-ruled milestone still reports the seat's own count."""
    try:
        import menu
        return menu.MILESTONE_NEED.get(name), menu.MILESTONE_METRIC.get(name)
    except Exception:                                   # pragma: no cover
        return None, None


def _my_score(row: dict, color) -> dict | None:
    for s in row.get("scores") or []:
        if s.get("color") == color:
            return s
    return None


def explain_unavailable(view: dict, kind: str, name: str) -> str:
    """Say WHY `claim`/`fund <name>` has no option in the current prompt.

    Distinguishes: every slot used (naming each taker), this one already
    taken, the metric not met (count vs threshold), the fee unaffordable —
    and otherwise prints the prompt actually on offer.
    """
    spec = MA_KINDS[kind]
    game = view.get("game") or {}
    rows = [r for r in (game.get(spec["key"]) or []) if isinstance(r, dict)]
    me = view.get("thisPlayer") or {}
    color = me.get("color")
    mc = me.get("megacredits", me.get("megaCredits"))
    taken = [(r.get("name"), r.get("playerName")) for r in rows
             if r.get("playerName")]
    used, total = len(taken), spec["slots"]
    fee = ma_fee(kind, used)
    row = next((r for r in rows
                if str(r.get("name", "")).lower() == str(name).lower()), None)
    taken_str = ", ".join(f"{n} ({p})" for n, p in taken) or "none yet"

    lines = [f"NO {spec['act']} AVAILABLE — {name}", ""]
    note = None
    if rows and row is None:
        reason = (f"no {spec['noun']} named {name!r} is in this game; it "
                  f"has: {', '.join(str(r.get('name')) for r in rows)}")
    elif used >= total:
        reason = (f"all {total} {spec['noun']} slots are already used — "
                  f"{taken_str}")
        note = (f"Only {total} {spec['noun']}s are ever {spec['past']} in a "
                f"game. With every slot gone the app stops offering "
                f"'{spec['menu']}' for the rest of the game: this is CORRECT "
                f"app behaviour, not a harness fault. Re-plan the VP — that "
                f"bucket is closed.")
    elif row is not None and row.get("playerName"):
        reason = (f"{row.get('name')} was already {spec['past']} by "
                  f"{row['playerName']}")
    else:
        mine = _my_score(row or {}, color)
        claimable = (mine or {}).get("claimable")
        if mine is not None and claimable is False:
            need, metric = _threshold(str(row.get("name")))
            have = f"{metric or 'score'} {mine.get('score')}"
            reason = (f"you do not meet {row.get('name')} yet — {have}"
                      + (f", need {need}" if need is not None else
                         " (the app reports it is not claimable for you)"))
        elif fee is not None and isinstance(mc, int) and mc < fee:
            reason = (f"you cannot afford the fee — {fee} M€ needed, "
                      f"{mc} M€ in hand")
        else:
            reason = (f"the current prompt offers no '{spec['menu']}' option "
                      f"— it appears only on your own action-phase menu, not "
                      f"inside a follow-up prompt")
            note = "prompt on offer:\n" + shape(view.get("waitingFor"))
    lines.append(f"reason: {reason}")
    lines.append(f"slots: {used} of {total} used — {taken_str}")
    if fee is not None and used < total:
        lines.append(f"fee: {fee} M€ · you hold: "
                     f"{mc if mc is not None else '?'} M€")
    if row is not None and (row.get("scores") or []):
        lines.append("scores: " + ", ".join(
            f"{s.get('color')}{' (you)' if s.get('color') == color else ''} "
            f"{s.get('score')}" for s in row["scores"]))
    if note:
        lines.append(note)
    lines.append("Diagnosis, not a defect: report the reason and keep "
                 "playing (agents/seat-kit.md).")
    return "\n".join(lines)


# What the app actually accepts per prompt type. The vendor's InputError
# names the response CLASS ("Not a valid SelectSpaceResponse") and never
# the shape — which cost a seat 31 minutes of guessing in the P7 game.
EXPECTED_SHAPE = {
    "space": '{"type": "space", "spaceId": "<hex>"}  (spaceId, NOT space)',
    "card": '{"type": "card", "cards": ["<Card>", …]}  ([] = take none)',
    "or": '{"type": "or", "index": <n>, "response": {…}}',
    "player": '{"type": "player", "player": "<color>"}',
    "option": '{"type": "option"}',
    "payment": '{"type": "payment", "payment": {"megacredits": <n>, …}}',
    "projectCard": '{"type": "projectCard", "card": "<Card>", "payment": {…}}',
    "amount": '{"type": "amount", "amount": <n>}',
}

VERBS = ("state", "wait", "send", "pass", "sp", "play", "claim", "fund",
         "action", "choose", "target", "space", "pick")


def main() -> int:
    global BASE
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=None,
                   help=f"app base URL (default: ${appapi.ENV_VAR} or "
                        f"{appapi.DEFAULT_URL})")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("state"); s.add_argument("pid")
    s = sub.add_parser("wait", help="block (silent 2s polls) until it is "
                                    "pid's turn or the game ends, then "
                                    "print the state ONCE — always use "
                                    "this instead of state-polling loops")
    s.add_argument("pid"); s.add_argument("--timeout", type=float, default=570)
    s.add_argument("--until-gen", type=int, default=None,
                   help="exit 3 (SCOPE END) once game.generation > N")
    s = sub.add_parser("send"); s.add_argument("pid"); s.add_argument("json")
    s = sub.add_parser("pass"); s.add_argument("pid")
    s = sub.add_parser("sp"); s.add_argument("pid"); s.add_argument("project")
    s2 = sub.add_parser("play", help="play a card from hand by NAME (the "
                                     "option index is looked up, never assumed)")
    s2.add_argument("pid"); s2.add_argument("card")
    for f in ("mc", "steel", "titanium", "heat"):
        s2.add_argument(f"--{f}", type=int, default=0)
    for s in (s, s2):        # follow-up prompt answers (one hop each)
        s.add_argument("--space", default=None)
        s.add_argument("--choice", type=int, default=None)
        s.add_argument("--target", default=None)
    for v in ("claim", "fund", "action", "target"):
        s = sub.add_parser(v); s.add_argument("pid"); s.add_argument("arg")
    s = sub.add_parser("choose", help="answer an 'or' prompt; the SELECTED "
                                      "branch's type decides the extra flag")
    s.add_argument("pid"); s.add_argument("arg", help="index, 'a.b' path, "
                                                      "title substring or player name")
    s.add_argument("--target", default=None, help="player branch: colour or name")
    s.add_argument("--space", default=None, help="space branch: hex (C4 or id)")
    s.add_argument("--cards", nargs="*", default=None,
                   help="card branch: the card names (none = decline)")
    s.add_argument("--amount", type=int, default=None, help="amount branch")
    s = sub.add_parser("space", help="answer a 'space' prompt, or the "
                                     "final-greenery `or` that wraps one")
    s.add_argument("pid"); s.add_argument("arg", nargs="?", default=None,
                                          help="hex (C4 or id)")
    s.add_argument("--skip", action="store_true",
                   help="take the \"Don't place\" branch of the wrapper")
    s = sub.add_parser("pick", help="answer a 'card' prompt; no names = none")
    s.add_argument("pid"); s.add_argument("names", nargs="*")
    a = p.parse_args()
    if a.url:
        BASE = a.url.rstrip("/")
    try:
        if a.cmd == "state":
            print(describe_waiting(a.pid))
        elif a.cmd == "wait":
            seat_mark(a.pid, "listen", "start")
            t0 = _now()
            d = wait_for_turn(a.pid, timeout=a.timeout)
            elapsed = _now() - t0
            if d is None:
                seat_mark(a.pid, "listen", "end", note="TIMEOUT")
                n = consecutive_timeouts(a.pid)
                print(f"TIMEOUT — still not your turn after {elapsed:.0f} s "
                      f"(timeout #{n} in a row; re-run wait)")
                return 2
            _remember_gen(d)
            if scope_ended(d, a.until_gen):
                seat_mark(a.pid, "listen", "end", note="SCOPE END")
                print(f"SCOPE END — generation "
                      f"{d.get('game', {}).get('generation')} > {a.until_gen}")
                return 3
            if d.get("waitingFor") is None:
                seat_mark(a.pid, "listen", "end", note="GAME ENDED")
                print("GAME ENDED (phase=end)")
            else:
                # the decision boundary: think time runs from here to the
                # next execute mark (the advisor's note ends in "GO" too)
                seat_mark(a.pid, "listen", "end", note=f"{elapsed:.0f} s GO")
                print(describe_waiting(a.pid))
        elif a.cmd == "send":
            send(a.pid, json.loads(a.json))
            print(describe_waiting(a.pid))
        elif a.cmd == "pass":
            wf = get_player(a.pid)["waitingFor"]
            idx = find_option(wf, "pass")
            send(a.pid, or_choice(idx, option()))
            print("passed")
        elif a.cmd == "play":
            wf = get_player(a.pid)["waitingFor"]
            send(a.pid, play_card(wf, a.card, mc=a.mc, steel=a.steel,
                                  titanium=a.titanium, heat=a.heat))
            follow_up(a.pid, a.space, a.choice, a.target)
            print(describe_waiting(a.pid))
        elif a.cmd == "space":
            wf = get_player(a.pid).get("waitingFor")
            send(a.pid, space_prompt_response(wf, a.arg, skip=a.skip))
            print(describe_waiting(a.pid))
        elif a.cmd in ("claim", "fund", "action", "choose"):
            d = get_player(a.pid)
            wf = d["waitingFor"]
            arg = int(a.arg) if a.cmd == "choose" and a.arg.isdigit() else a.arg
            if a.cmd == "choose":
                # the view's players[] resolve a NAME to the colour the app
                # prints in removal-prompt titles / expects in a player branch
                resp = choose(wf, arg, d.get("players"), target=a.target,
                              space=a.space, cards=a.cards, amount=a.amount)
            elif a.cmd in MA_KINDS:
                try:
                    resp = ({"claim": claim_milestone,
                             "fund": fund_award}[a.cmd])(wf or {}, arg)
                except (KeyError, AttributeError, TypeError):
                    # P9 #11: the menu option is missing — say WHY rather
                    # than leaving the seat to guess (it guessed "broken").
                    print(explain_unavailable(d, a.cmd, arg), file=sys.stderr)
                    return 1
            else:
                resp = card_action(wf, arg)
            send(a.pid, resp)
            print(describe_waiting(a.pid))
        elif a.cmd == "target":
            send(a.pid, target_player(a.arg))
            print(describe_waiting(a.pid))
        elif a.cmd == "pick":
            send(a.pid, cards(a.names))
            print(describe_waiting(a.pid))
        elif a.cmd == "sp":
            wf = get_player(a.pid)["waitingFor"]
            idx = find_option(wf, "standard")
            names = {"power": "Power Plant:SP", "asteroid": "Asteroid:SP",
                     "aquifer": "Aquifer", "greenery": "Greenery",
                     "city": "City"}
            cost = {"power": 11, "asteroid": 14, "aquifer": 18,
                    "greenery": 23, "city": 25}[a.project]
            send(a.pid, or_choice(idx, project_card(names[a.project], mc=cost)))
            follow_up(a.pid, a.space, a.choice, a.target)
            print(describe_waiting(a.pid))
        return 0
    except Ask as e:
        # the composer refused BEFORE transmitting: the flag it names is
        # the whole fix — nothing to guess, nothing went out
        lines = [f"ERROR: {e}", "nothing was sent."]
        if e.wf is not None:
            lines += ["current prompt:", shape(e.wf)]
        print("\n".join(lines), file=sys.stderr)
        return 1
    except (AppError, AppUnavailable, urllib.error.URLError, KeyError,
            json.JSONDecodeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
