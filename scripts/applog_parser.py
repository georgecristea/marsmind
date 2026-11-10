"""Parser for the online app's full log export.

Pure functions, no I/O — the replay (scripts/replay_applog.py) and, later,
the live online listener import this. Grammar examples:
tests/fixtures/replay-4p-wgt/applog.txt (a real export, names aliased).

parse_line(line, players)  → one event dict ({"kind": ..., ...})
parse_log(text, players)   → [event] with "line" numbers and "raw" text
group_blocks(events)       → [{"head": event, "tail": [consequence events]}]

Blocks: a HEAD line (a play, an action, a standard project, a research buy,
a WGT step, a milestone/award …) followed by the consequence lines the app
prints for it ("gained N …", "placed … tile at NN", "lost N plants because
of …"). Two quirks are folded in at grouping time:
  - "You bought A,B" / "You drew A,B" name the cards of the PREVIOUS
    "X bought/drew N card(s)" line (this export reveals them for everyone);
  - a World Government ocean prints "X placed ocean tile at NN" BEFORE
    "X acted as World Government and placed an ocean" — the placement is
    the WGT head's hex, not a consequence of whatever came before.
"""
from __future__ import annotations

import re

RESOURCE_WORDS = {
    "m€": "mc", "mc": "mc", "megacredits": "mc",
    "steel": "steel", "titanium": "titanium",
    "plant": "plants", "plants": "plants",
    "energy": "energy", "heat": "heat", "tr": "tr",
}

STANDARD_PROJECTS = {
    "power plant": "power_plant", "asteroid": "asteroid", "aquifer": "aquifer",
    "greenery": "greenery", "city": "city", "sell patents": "sell_patents",
    "convert heat": "convert_heat", "convert plants": "convert_plants",
}

WGT_WORDS = {"increased temperature": "temperature",
             "increased oxygen level": "oxygen",
             "placed an ocean": "oceans"}

IGNORE_PREFIXES = ("Good luck ", "This game id", "The project discard pile")

HEAD_KINDS = {"generation", "first_player", "played", "kept", "bought",
              "used_action", "used_standard", "funded", "claimed", "wgt",
              "passed", "ended_turn", "final_greenery", "first_action",
              "ignore", "unknown"}
# "drew" is never a head: every draw follows the line that caused it
# (Business Contacts, a Development Center action, a card-bonus hex, the
# Inventrix first action, "removed a resource from Olympus Conference").


def norm_resource(word: str) -> str:
    return RESOURCE_WORDS.get(word.strip().lower(), word.strip().lower())


def _player_pat(players) -> str:
    if players:
        names = sorted((re.escape(p) for p in players), key=len, reverse=True)
        return "(" + "|".join(names) + ")"
    return r"(\S+)"


def _compile(players):
    P = _player_pat(players)
    return [
        ("generation", re.compile(r"^Generation (?P<n>\d+)$")),
        ("first_player", re.compile(rf"^First player this generation is {P}$")),
        ("final_greenery", re.compile(r"^Final greenery placement$")),
        ("first_action", re.compile(rf"^{P} took the first action of (?P<card>.+) corporation$")),
        ("kept", re.compile(rf"^{P} kept (?P<n>\d+) project cards?$")),
        ("bought", re.compile(rf"^{P} bought (?P<n>\d+) card\(s\)$")),
        ("you_bought", re.compile(r"^You bought (?P<cards>.+)$")),
        ("drew", re.compile(rf"^{P} drew (?P<n>\d+) card\(s\)$")),
        ("you_drew", re.compile(r"^You drew (?P<cards>.+)$")),
        # A land claim is a MARKER, not a tile: the app prints it without the
        # word "tile", and no tile ever appears in the app's final board for
        # that hex unless the claimer later builds there. It reserves the hex
        # against every OTHER player (see the board note on "land_claim").
        ("land_claim", re.compile(rf"^{P} placed land claim at (?P<space>\d+)$")),
        ("placed", re.compile(rf"^{P} placed (?P<tile>.+?) tile at (?P<space>\d+)$")),
        # ── card flow: cards moving between deck, hand and discard ──
        # No state the tracker keeps changes on these lines; what matters is
        # that they parse, because an "unknown" line becomes a HEAD in
        # group_blocks() and orphans every consequence line behind it (the
        # draw, the gain, the placement). Line shapes only — never a card
        # name branch; the card is a capture group.
        ("revealed_discarded", re.compile(
            rf"^{P} revealed and discarded (?P<card>.+?)\.?$")),
        ("use_effect", re.compile(
            rf"^{P} is using their (?P<card>.+?) effect (?P<what>.+?)\.?$")),
        ("discarded", re.compile(rf"^{P} discarded (?P<card>.+?)\.?$")),
        # "X found life!" — the app announces the card resource without ever
        # numbering it (an "added N <res> to <Card>" line would have been
        # read as card_resource above). Neutral note, no state change.
        ("found", re.compile(rf"^{P} found (?P<what>.+?)!$")),
        ("gained_prod", re.compile(
            rf"^{P} gained (?P<n>\d+) (?P<res>.+?) production(?: because of (?P<source>.+))?$")),
        ("lost_prod", re.compile(
            rf"^{P} lost (?P<n>\d+) (?P<res>.+?) production(?: because of {P.replace('(', '(?P<by>', 1)})?$")),
        ("stole_prod", re.compile(rf"^{P} stole (?P<n>\d+) (?P<res>.+?) production from {P.replace('(', '(?P<from>', 1)}$")),
        ("stole", re.compile(rf"^{P} stole (?P<n>\d+) (?P<res>.+?) from {P.replace('(', '(?P<from>', 1)}$")),
        ("gained_ocean", re.compile(rf"^{P} gained (?P<n>\d+) (?P<res>M€|\w+) from (?P<k>\d+) ocean\(s\)$")),
        ("gained_from", re.compile(rf"^{P} gained (?P<n>\d+) (?P<res>M€|\w+) from (?P<source>.+)$")),
        # "X gained N <res> because of <Card>" — the trigger-card form
        # (Viral Enhancers, Arctic Algae). Unparsed until P7, so every such
        # line was silently dropped and the opponent under-tracked.
        ("gained_from", re.compile(
            rf"^{P} gained (?P<n>\d+) (?P<res>M€|\w+) because of (?P<source>.+)$")),
        ("gained", re.compile(rf"^{P} gained (?P<n>\d+) (?P<res>M€|\w+)$")),
        ("lost_because", re.compile(rf"^{P} lost (?P<n>\d+) (?P<res>M€|\w+) because of {P.replace('(', '(?P<by>', 1)}$")),
        # same clause naming a CARD rather than a player (the attacker form
        # above is tried first, so a known player still wins)
        ("lost_from", re.compile(
            rf"^{P} lost (?P<n>\d+) (?P<res>M€|\w+) because of (?P<source>.+)$")),
        ("lost", re.compile(rf"^{P} lost (?P<n>\d+) (?P<res>M€|\w+)$")),
        ("used_standard", re.compile(rf"^{P} used (?P<name>.+?)(?::SP)? standard (?:project|action)$")),
        ("used_action", re.compile(rf"^{P} used (?P<card>.+) action$")),
        ("sold", re.compile(rf"^{P} sold (?P<n>\d+) patents?$")),
        ("funded", re.compile(rf"^{P} funded (?P<award>.+) award$")),
        ("claimed", re.compile(rf"^{P} claimed (?P<milestone>.+) milestone$")),
        ("wgt", re.compile(rf"^{P} acted as World Government and (?P<what>.+)$")),
        ("added", re.compile(rf"^{P} added (?P<n>\d+) (?P<res>\w+)(?:\(s\))? to (?P<card>.+)$")),
        ("removed", re.compile(rf"^{P} removed (?P<n>\d+) resource\(s\) from (?P<card>.+)$")),
        ("removed_one", re.compile(rf"^{P} removed a resource from (?P<card>.+?) to draw a card$")),
        ("copied", re.compile(rf"^{P} copied (?P<card>.+) production with (?P<via>.+)$")),
        ("passed", re.compile(rf"^{P} passed$")),
        ("ended_turn", re.compile(rf"^{P} ended turn$")),
    ]


_CACHE: dict = {}


def _rules(players):
    key = tuple(players) if players else None
    if key not in _CACHE:
        _CACHE[key] = _compile(players)
    return _CACHE[key]


def _split_cards(s: str) -> list[str]:
    return [c.strip() for c in s.split(",") if c.strip()]


def parse_line(line: str, players=None) -> dict:
    """One export line → one event dict. Never raises; unknown grammar →
    {"kind": "unknown"}."""
    raw = line.strip()
    if not raw:
        return {"kind": "ignore"}
    if raw.startswith(IGNORE_PREFIXES):
        return {"kind": "ignore"}
    for kind, rx in _rules(players):
        m = rx.match(raw)
        if not m:
            continue
        g = m.groupdict()
        player = m.group(1) if kind not in ("generation", "you_bought",
                                            "you_drew", "final_greenery") else None
        if kind == "generation":
            return {"kind": "generation", "n": int(g["n"])}
        if kind == "final_greenery":
            return {"kind": "final_greenery"}
        if kind in ("you_bought", "you_drew"):
            return {"kind": kind, "cards": _split_cards(g["cards"])}
        if kind == "first_player":
            return {"kind": kind, "player": player}
        if kind == "first_action":
            return {"kind": kind, "player": player, "card": g["card"]}
        if kind in ("kept", "bought", "drew"):
            return {"kind": kind, "player": player, "n": int(g["n"]), "cards": None}
        if kind == "land_claim":
            return {"kind": "land_claim", "player": player, "space": g["space"]}
        if kind == "revealed_discarded":
            return {"kind": "card_flow", "player": player,
                    "verb": "reveal_discard", "card": g["card"].strip()}
        if kind == "use_effect":
            return {"kind": "card_flow", "player": player, "verb": "use_effect",
                    "card": g["card"].strip(), "what": g["what"].strip()}
        if kind == "discarded":
            return {"kind": "card_flow", "player": player, "verb": "discard",
                    "card": g["card"].strip()}
        if kind == "found":
            return {"kind": "note", "player": player,
                    "text": f"found {g['what'].strip()}"}
        if kind == "placed":
            tile = g["tile"]
            if tile.lower() in ("ocean", "city", "greenery"):
                tile = tile.lower()
            return {"kind": "placed", "player": player, "tile": tile, "space": g["space"]}
        if kind == "gained_prod":
            return {"kind": "gained_prod", "player": player,
                    "resource": norm_resource(g["res"]), "n": int(g["n"]),
                    "source": g.get("source")}
        if kind == "lost_prod":
            return {"kind": "lost_prod", "player": player,
                    "resource": norm_resource(g["res"]), "n": int(g["n"]),
                    "by": g.get("by")}
        if kind in ("stole_prod", "stole"):
            return {"kind": "stole", "player": player,
                    "resource": norm_resource(g["res"]), "n": int(g["n"]),
                    "from": g["from"], "prod": kind == "stole_prod"}
        if kind == "gained_ocean":
            return {"kind": "gained", "player": player,
                    "resource": norm_resource(g["res"]), "n": int(g["n"]),
                    "source": "ocean", "oceans": int(g["k"])}
        if kind == "gained_from":
            return {"kind": "gained", "player": player,
                    "resource": norm_resource(g["res"]), "n": int(g["n"]),
                    "source": g["source"]}
        if kind == "gained":
            return {"kind": "gained", "player": player,
                    "resource": norm_resource(g["res"]), "n": int(g["n"]),
                    "source": None}
        if kind in ("lost_because", "lost", "lost_from"):
            return {"kind": "lost", "player": player,
                    "resource": norm_resource(g["res"]), "n": int(g["n"]),
                    "by": g.get("by"),
                    "source": g["source"] if kind == "lost_from" else None}
        if kind == "used_standard":
            name = g["name"].strip().lower()
            return {"kind": "used_standard", "player": player,
                    "project": STANDARD_PROJECTS.get(name, name)}
        if kind == "used_action":
            return {"kind": "used_action", "player": player, "card": g["card"].strip()}
        if kind == "sold":
            return {"kind": "sold", "player": player, "n": int(g["n"])}
        if kind == "funded":
            return {"kind": "funded", "player": player, "award": g["award"].strip()}
        if kind == "claimed":
            return {"kind": "claimed", "player": player, "milestone": g["milestone"].strip()}
        if kind == "wgt":
            what = g["what"].strip()
            return {"kind": "wgt", "player": player,
                    "param": WGT_WORDS.get(what, what), "space": None}
        if kind == "added":
            return {"kind": "card_resource", "player": player, "verb": "add",
                    "n": int(g["n"]), "resource": g["res"], "card": g["card"].strip()}
        if kind == "removed":
            card = g["card"].strip()
            card = re.sub(r"^\S+'s ", "", card)          # "<name>'s Nitrite …"
            return {"kind": "card_resource", "player": player, "verb": "remove",
                    "n": int(g["n"]), "resource": None, "card": card}
        if kind == "removed_one":
            return {"kind": "card_resource", "player": player, "verb": "remove",
                    "n": 1, "resource": None, "card": g["card"].strip(),
                    "draws": True}
        if kind == "copied":
            return {"kind": "copied", "player": player, "card": g["card"].strip(),
                    "via": g["via"].strip()}
        if kind in ("passed", "ended_turn"):
            return {"kind": kind, "player": player}
        if kind == "played":
            return {"kind": "played", "player": player, "card": g["card"].strip()}
    # "X played Y" last: card names are free text, so any earlier grammar
    # that happens to contain " played " must win first.
    m = re.match(rf"^{_player_pat(players)} played (?P<card>.+)$", raw)
    if m:
        return {"kind": "played", "player": m.group(1), "card": m.group("card").strip()}
    return {"kind": "unknown", "raw": raw}


def parse_log(text: str, players=None) -> list[dict]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        ev = parse_line(line, players)
        ev["line"] = n
        ev["raw"] = line.strip()
        out.append(ev)
    return out


def group_blocks(events: list[dict]) -> list[dict]:
    """Head + consequence grouping (see module docstring).

    Consequence kinds: placed, gained, gained_prod, lost, lost_prod, stole,
    sold, card_resource, copied, drew (draws always follow a head that
    caused them), and a `bought` that follows a Business Network action.
    NEUTRAL consequences carry no state at all — `card_flow` (a reveal, a
    discard, an "is using their <Card> effect …" announcement), `note` ("X
    found life!", a card resource the app never numbers) and `land_claim`
    (a hex marker, not a tile). They exist so the head that caused them
    keeps its tail: an unrecognised line becomes a HEAD here, which orphans
    every consequence line printed after it.
    After "Final greenery placement" every placement is its own block
    ("final_placed" head: convert plants + place).
    """
    blocks: list[dict] = []
    final = False
    pending_placed: dict | None = None   # ocean placement waiting for a WGT line

    def cur():
        return blocks[-1] if blocks else None

    def push(head):
        blocks.append({"head": head, "tail": []})

    for ev in events:
        kind = ev["kind"]
        if kind == "ignore":
            continue
        if kind == "unknown":
            push(ev)
            continue
        if kind in ("you_bought", "you_drew"):
            want = "bought" if kind == "you_bought" else "drew"
            # attach to the most recent bought/drew event (head or tail)
            target = None
            for b in reversed(blocks):
                for e in [*reversed(b["tail"]), b["head"]]:
                    if e["kind"] == want and e.get("cards") is None:
                        target = e
                        break
                if target:
                    break
            if target is not None:
                target["cards"] = list(ev["cards"])
            else:
                push(dict(ev, kind="unknown"))
            continue
        if kind == "final_greenery":
            final = True
            push(ev)
            continue
        if kind == "placed" and ev["tile"] == "ocean" and pending_placed is None:
            # might be a WGT ocean (its WGT line follows) — hold it
            pending_placed = ev
            continue
        if kind == "wgt":
            if ev["param"] == "oceans" and pending_placed is not None:
                ev = dict(ev, space=pending_placed["space"], placed_line=pending_placed["line"])
                pending_placed = None
            push(ev)
            continue
        if pending_placed is not None:
            # not a WGT ocean after all → it was a consequence of the current block
            if cur() is not None:
                cur()["tail"].append(pending_placed)
            else:
                push(pending_placed)
            pending_placed = None
            if kind == "placed" and ev["tile"] == "ocean":
                pending_placed = ev
                continue
        if final and kind == "placed":
            push(dict(ev, kind="final_placed"))
            continue
        if kind == "bought" and cur() is not None and cur()["head"]["kind"] == "used_action":
            cur()["tail"].append(ev)
            continue
        if kind in HEAD_KINDS:
            push(ev)
            continue
        # consequence
        if cur() is None:
            push(ev)
        else:
            cur()["tail"].append(ev)
    if pending_placed is not None:
        if cur() is not None:
            cur()["tail"].append(pending_placed)
        else:
            push(pending_placed)
    return blocks
