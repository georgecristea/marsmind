#!/usr/bin/env python3
"""Extract base + Corporate Era card data from the vendored terraforming-mars repo.

Source of truth: vendor/terraforming-mars (https://github.com/terraforming-mars/terraforming-mars).
Module membership comes from src/server/cards/StandardCardManifests.ts
(BASE_CARD_MANIFEST + CORP_ERA_CARD_MANIFEST), so no prelude/Venus/colonies/
turmoil/promo cards can leak in. Card fields are parsed from the declarative
TypeScript card classes (cost, tags, requirements, victoryPoints, metadata
description and CardRenderer text strings).

Declarative blocks are emitted as DATA so the engine can interpret cards
generically instead of hand-modelling them one at a time:
  behavior        the `behavior:` block (+ curated BEHAVIOR_PATCHES)
  actionBehavior  the ActionCard `action:` block (`action` stays prose)
  vpData          the `victoryPoints:` descriptor (`vp` stays prose)
  cardDiscount    price modifiers ({"amount": N, "tag"?: t, "per"?: p})
  resourceType    the card resource this card holds
  cardCost        corporations that change the price of project cards
  bespoke/bespokeMethods  the TS hooks the class overrides = the mechanics
                  no declarative block expresses; audit_db.py lists them.

Deterministic: same vendor checkout -> byte-identical cards/db.json.

Usage: python3 scripts/extract_cards.py [--vendor PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "terraforming-mars"
OUT = ROOT / "cards" / "db.json"

TAG_MAP = {
    "BUILDING": "building", "SPACE": "space", "SCIENCE": "science",
    "POWER": "power", "EARTH": "earth", "JOVIAN": "jovian", "VENUS": "venus",
    "PLANT": "plant", "MICROBE": "microbe", "ANIMAL": "animal", "CITY": "city",
    "MOON": "moon", "MARS": "mars", "WILD": "wild", "EVENT": "event",
    "CLONE": "clone", "CRIME": "crime",
}

RESOURCE_NAME = {
    "MICROBE": "microbe", "ANIMAL": "animal", "FIGHTER": "fighter resource",
    "SCIENCE": "science resource", "FLOATER": "floater", "ASTEROID": "asteroid",
    "PRESERVATION": "preservation", "DATA": "data",
}

# Cards whose machine-rendered text is icons-only (or too fragmentary) in the
# source; effect/action text below is the official card text.
OVERRIDES: dict[str, dict[str, str]] = {
    "Business Network": {
        "action": "Look at the top card of the deck and either buy it or discard it.",
    },
    "Inventors' Guild": {
        "action": "Look at the top card of the deck and either buy it or discard it.",
    },
    "Protected Habitats": {
        "effects": "Effect: Opponents may not remove your plants, animals or microbes.",
    },
    "Pets": {
        "effects": "Gain 1 animal to this card. Effect: Animals may not be removed "
                   "from this card. When any city tile is placed, add an animal to this card.",
    },
    "Hackers": {
        "effects": "Decrease your energy production 1 step and any M€ production 2 steps. "
                   "Increase your M€ production 2 steps.",
    },
    "Land Claim": {
        "effects": "Place your marker on a non-reserved area. Only you may place a tile there.",
    },
    "Trans-Neptune Probe": {
        "effects": "No effect; played for its science and space tags and 1 VP.",
    },
    "Security Fleet": {
        "vp_note": "1 per fighter resource",
    },
}


# Curated mechanical deltas for bespoke-code cards (base + Corporate Era).
# Keys use the engine's behavior vocabulary. Cards flagged bespoke WITHOUT
# a patch keep behavior possibly-partial — audit_db.py lists them and the
# engine emits a TABLE fallback step at play time.
BEHAVIOR_PATCHES: dict[str, dict] = {
    "Flooding": {"ocean": {}},                    # place 1 ocean (+TR)
    "Moss": {"stock": {"plants": -1}},            # pays 1 plant
    "Lake Marineris": {"ocean": {"count": 2}},    # already declarative; keep
    "Martian Rails": {},                           # action-only bespoke
    "Predators": {},                               # action-only bespoke
    # Bespoke cards whose effects the engine/CLI apply explicitly. The
    # "when a city is placed" effect of Immigrant City lives in
    # tmlib.CITY_TRIGGERS; target/choice/copy come from the CLI.
    "Immigrant City": {"production": {"energy": -1, "megacredits": -2},
                       "city": {}},
    "Power Supply Consortium": {"stealProduction": {"type": "energy", "count": 1}},
    "Sabotage": {"removeAny": {"options": [{"titanium": 3}, {"steel": 4},
                                           {"megacredits": 7}]}},
    "Terraforming Ganymede": {"tr": {"tag": "jovian"}},
    "Robotic Workforce": {"copyProduction": "building"},
    # onStandardProject hook (vendor StandardTechnology.ts): "After you pay
    # for a standard project, except selling patents, you gain 3 M€" — the
    # same shape as the corporation rebate (tmlib CORP_RULES "rebate"),
    # keyed by the engine's own project names; `except` lists the
    # projects the refund skips. Engine.standard applies every source.
    "Standard Technology": {"standardProjectRebate": {
        "amount": 3, "except": ["sell_patents"]}},
    # Or-choices the vendor implements in TypeScript, so the declarative
    # `behavior` holds only the non-optional part (Imported Hydrogen: the
    # ocean). Branches in CARD-TEXT order, in the engine's own vocabulary
    # (`addResourcesToAnother` — resources on somebody else's card are a
    # TABLE step) so tmlib.OR_CHOICE_PATCHES becomes dead code.
    "Imported Hydrogen": {"or": {"behaviors": [
        {"title": "Gain 3 plants", "stock": {"plants": 3}},
        {"title": "Add 3 microbes to ANOTHER card",
         "addResourcesToAnother": {"type": "microbes", "count": 3}},
        {"title": "Add 2 animals to ANOTHER card",
         "addResourcesToAnother": {"type": "animals", "count": 2}},
    ]}},
    # "Decrease any steel production 1 step and increase your own 1 step":
    # the vendor defers DecreaseAnyProduction(STEEL) + GainProduction(STEEL)
    # and only the first half reached the engine (P9 issue 4).
    "Great Escarpment Consortium": {
        "decreaseAnyProduction": {"type": "steel", "count": 1},
        "production": {"steel": 1},
    },
    # MiningCard.spaceSelected: the hex's own placement bonus decides which
    # production goes up, and the app asks for it (SelectResourceTypeDeferred)
    # AFTER the play — so it is an or-choice the engine cannot make at play
    # time. `deferred` says exactly that: no choice is a TABLE step naming
    # the menu, never a refusal and never a guess.
    "Mining Rights": {"or": {"deferred": True, "behaviors": [
        {"title": "Steel production 1 step", "production": {"steel": 1}},
        {"title": "Titanium production 1 step", "production": {"titanium": 1}},
    ]}},
    "Mining Area": {"or": {"deferred": True, "behaviors": [
        {"title": "Steel production 1 step", "production": {"steel": 1}},
        {"title": "Titanium production 1 step", "production": {"titanium": 1}},
    ]}},
}


# TypeScript hooks a card class can override. A card that overrides any of
# them carries mechanics its declarative blocks do NOT express — that, and
# nothing else, is what `bespoke` means. Helper methods a card defines for
# its own use (private one-offs, getters) are deliberately absent.
BESPOKE_HOOKS = frozenset({
    # play / playability
    "play", "canPlay", "bespokePlay", "bespokeCanPlay", "initialAction",
    "getVictoryPoints", "productionBox", "computeTr", "getAvailableSpaces",
    # blue-card action
    "action", "canAct", "bespokeAction", "bespokeCanAct",
    # persistent triggers
    "onCardPlayed", "onCardPlayedByAnyPlayer", "onCardPlayedFromAnyPlayer",
    "onTilePlaced", "onStandardProject", "onProductionPhase",
    "onNonCardTagAdded", "onNonCardTagAddedByAnyPlayer", "onScienceTagAdded",
    "onColonyAdded", "onColonyAddedToColony", "onDiscard", "onResourceAdded",
    "onGlobalParameterIncrease",
    # pricing
    "getCardDiscount", "getStandardProjectDiscount",
})

METHOD_RE = re.compile(
    r"^  (?:public |private |protected )?(?:override )?(?:async )?(\w+)\s*\(",
    re.M)


def bespoke_methods(body: str) -> list[str]:
    """Hook methods THIS card's class body defines. The class body only:
    the shared bases (ActionCard, CorporationCard) define action/canAct as
    generic dispatchers over the declarative `action` block, so counting
    them would flag every action card and every corporation. Sorted and
    deduplicated: deterministic."""
    return sorted({m.group(1) for m in METHOD_RE.finditer(body)}
                  & BESPOKE_HOOKS)


def die(msg: str) -> None:
    sys.exit(f"extract_cards: {msg}")


def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, respecting string literals."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in ("'", '"', "`"):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                ch = src[i]
                out.append(ch)
                if ch == "\\":
                    if i + 1 < n:
                        out.append(src[i + 1])
                    i += 2
                    continue
                i += 1
                if ch == quote:
                    break
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def balanced(src: str, start: int) -> str:
    """Return the balanced {...} or [...] chunk starting at src[start]."""
    open_ch = src[start]
    close_ch = {"{": "}", "[": "]", "(": ")"}[open_ch]
    depth = 0
    i = start
    n = len(src)
    while i < n:
        c = src[i]
        if c in ("'", '"', "`"):
            quote = c
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == quote:
                    break
                i += 1
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    die(f"unbalanced braces at offset {start}")
    return ""  # unreachable


def unescape(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\\'", "'").replace('\\"', '"')).strip()


STRING_RE = r"'((?:[^'\\]|\\.)*)'"


def parse_cardnames(vendor: Path) -> dict[str, str]:
    src = (vendor / "src/common/cards/CardName.ts").read_text(encoding="utf-8")
    names = dict(re.findall(rf"^\s*([A-Z0-9_]+)\s*=\s*{STRING_RE},?\s*$", src, re.M))
    if not names:
        die("could not parse CardName.ts")
    return {k: v.replace("\\'", "'") for k, v in names.items()}


def parse_manifests(vendor: Path) -> tuple[dict[str, Path], list[tuple[str, str, str, str]]]:
    """Returns (class -> file path, [(module, section, cardname_key, class)])."""
    manifest_path = vendor / "src/server/cards/StandardCardManifests.ts"
    src = manifest_path.read_text(encoding="utf-8")

    imports: dict[str, Path] = {}
    for cls, rel in re.findall(r"import \{(\w+)\} from '(\./[^']+)';", src):
        imports[cls] = (manifest_path.parent / (rel + ".ts")).resolve()

    entries: list[tuple[str, str, str, str]] = []
    for module_match in re.finditer(r"new ModuleManifest\(\{", src):
        block = balanced(src, src.index("{", module_match.start()))
        module = re.search(r"module: '(\w+)'", block).group(1)
        for section in ("projectCards", "corporationCards"):
            sec_match = re.search(rf"{section}: \{{", block)
            if not sec_match:
                continue
            sec = balanced(block, block.index("{", sec_match.start()))
            for key, cls in re.findall(r"\[CardName\.([A-Z0-9_]+)\]: \{Factory: (\w+)\}", sec):
                entries.append((module, section, key, cls))
    return imports, entries


def parse_requirement_item(item: str) -> str:
    """One requirement descriptor {...} -> human-readable text."""
    body = item.strip()[1:-1]
    parts = [p.strip() for p in body.split(",") if p.strip()]
    kv: dict[str, str] = {}
    flags: set[str] = set()
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            kv[k.strip()] = v.strip()
        else:
            flags.add(p)
    bound = "max" if "max" in flags else "min"

    if "oxygen" in kv:
        return f"{bound} {kv['oxygen']}% O2"
    if "temperature" in kv:
        return f"{bound} {kv['temperature']}°C"
    if "oceans" in kv:
        n = kv["oceans"]
        return f"{bound} {n} ocean{'s' if n != '1' else ''}"
    if "tag" in kv:
        tag = TAG_MAP[kv["tag"].split(".")[1]]
        n = int(kv.get("count", "1"))
        return f"{n} {tag} tag{'s' if n > 1 else ''}"
    if "production" in kv:
        res = kv["production"].split(".")[1].lower()
        n = int(kv.get("count", "1"))
        return f"{res} production" if n == 1 else f"{n} {res} production"
    if "greeneries" in kv:
        n = kv["greeneries"]
        return f"{bound} {n} greener{'ies' if n != '1' else 'y'}"
    if "cities" in kv:
        n = kv["cities"]
        who = " (any player)" if "all" in flags else ""
        return f"{bound} {n} cit{'ies' if n != '1' else 'y'}{who}"
    if "tr" in kv:
        return f"{bound} TR {kv['tr']}"
    die(f"unknown requirement descriptor: {item}")
    return ""


def parse_requirements(expr: str) -> str | None:
    expr = expr.strip()
    if expr.startswith("["):
        items = re.findall(r"\{[^}]*\}", expr)
        return ", ".join(parse_requirement_item(i) for i in items)
    return parse_requirement_item(expr)


def parse_vp(expr: str, resource: str | None, card_name: str):
    expr = expr.strip().rstrip(",")
    if re.fullmatch(r"-?\d+", expr):
        return int(expr)
    res = RESOURCE_NAME.get(resource or "", "resource")

    if expr.startswith("{"):
        body = expr[1:-1]
        kv: dict[str, str] = {}
        for m in re.finditer(r"(\w+):\s*(\{[^}]*\}|[^,]+)", body):
            kv[m.group(1)] = m.group(2).strip()
        if "resourcesHere" in kv:
            each = int(kv.get("each", "1"))
            per = int(kv.get("per", "1"))
            unit = res if per == 1 else f"{per} {res}s"
            return f"{each} per {unit}" if each != 1 else f"1 per {unit}"
        if "tag" in kv:
            tag = TAG_MAP[kv["tag"].split(".")[1]]
            per = int(kv.get("per", "1"))
            each = int(kv.get("each", "1"))
            unit = f"{tag} tag" if per == 1 else f"{per} {tag} tags"
            return f"{each} per {unit}" if each != 1 else f"1 per {unit}"
        if "cities" in kv:
            if "nextToThis" in kv:
                return "1 per adjacent city tile"
            per = int(kv.get("per", "1"))
            scope = " in play" if kv.get("all") == "true" else ""
            return f"1 per {per} cities{scope}" if per != 1 else f"1 per city{scope}"
        if "oceans" in kv:
            if "nextToThis" in kv:
                return "1 per adjacent ocean tile"
            return "1 per ocean"
    m = re.match(r"oceans\((\d+),\s*(\d+)\)", expr)
    if m:
        return f"{m.group(1)} per adjacent ocean tile"
    m = re.match(r"cities\((\d+),\s*(\d+)", expr)
    if m:
        return f"{m.group(1)} per adjacent city tile"
    if expr == "searchForLife()" or expr == "'special'":
        if card_name == "Search For Life":
            return "3 if this card has one or more science resources on it"
        return "special"
    die(f"unknown victoryPoints expression on {card_name}: {expr}")


def parse_vp_data(expr: str):
    """The `victoryPoints` property as DATA (prose stays in `vp`).

    int, or the vendor's descriptor object ({"resourcesHere": {}, "each": 2},
    {"tag": "jovian", "per": 1}, {"cities": {}, "each": 1}, ...). Function
    forms the vendor computes in code (searchForLife(), oceans(1, 1)) have no
    declarative form -> None, and the card is flagged bespoke instead."""
    expr = expr.strip().rstrip(",")
    if re.fullmatch(r"-?\d+", expr):
        return int(expr)
    if expr.startswith("{"):
        return ts_object_to_data(expr)
    return None


def field_value(src: str, key: str) -> str | None:
    """First top-level-ish `key: <value>` in src; value returned raw."""
    m = re.search(rf"\b{key}:\s*", src)
    if not m:
        return None
    start = m.end()
    if src[start] in "{[(":
        return balanced(src, start)
    call = re.match(r"\w+\s*\(", src[start:])
    if call:
        return src[start:start + call.end() - 1] + balanced(src, start + call.end() - 1)
    m2 = re.match(rf"{STRING_RE}|[^,\n]+", src[start:])
    return m2.group(0)


def ts_object_to_data(expr: str):
    """Convert a declarative TS object literal (a card `behavior` block) to
    plain Python data. Enum refs (Tag.X, CardResource.X, TileType.X, ...)
    become lowercase strings; unsupported constructs (functions, template
    strings, arithmetic) return None so callers fall back to manual steps."""
    if any(tok in expr for tok in ("=>", "function", "`", "...")):
        return None
    py = expr
    py = re.sub(r"\b[A-Z]\w*\.([A-Z_][A-Z_0-9]*)\b",
                lambda m: "'" + m.group(1).lower().replace("_", "") + "'", py)
    py = re.sub(r"([\{,]\s*)([A-Za-z_]\w*)\s*:", r"\1'\2':", py)
    py = py.replace("true", "True").replace("false", "False")
    # bare identifiers (variable refs like `adjacencyBonus`) → dynamic marker,
    # so one dynamic field no longer discards the whole behavior block
    py = re.sub(r":\s*([A-Za-z_]\w*)\s*([,}\]])",
                lambda m: ": '@dynamic'" + m.group(2)
                if m.group(1) not in ("True", "False", "None") else m.group(0),
                py)
    py = re.sub(r",\s*([}\]])", r"\1", py)  # trailing commas
    try:
        import ast
        return ast.literal_eval(py)
    except (ValueError, SyntaxError):
        return None


UNIT_RESOURCES = ("megacredits", "steel", "titanium", "plants", "energy", "heat")


def parse_reserve_units(expr: str) -> dict[str, int]:
    """The constructor property `reserveUnits` -> the engine's `spend` map.

    The vendor states a card's play-time resource COST as a sibling of
    `behavior`, never inside it (`reserveUnits: {heat: 5}` on Local Heat
    Trapping, `{steel: 2}` on the Moon road cards), so reading `behavior`
    alone drops the cost entirely. Accepts the bare object literal and the
    `Units.of({...})` / `Units.EMPTY` wrappers; non-literal amounts (a
    player-dependent count) are skipped rather than guessed."""
    expr = (expr or "").strip().rstrip(",")
    if not expr:
        return {}
    if expr.startswith("Units."):
        inner = expr[expr.index("(") + 1:expr.rindex(")")].strip() \
            if "(" in expr else ""
        expr = inner            # Units.EMPTY -> "" ; Units.of({...}) -> {...}
    if not expr.startswith("{"):
        return {}
    data = ts_object_to_data(expr)
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if k in UNIT_RESOURCES and isinstance(v, int) and v > 0}


def parse_card(path: Path, official_name: str, is_corp: bool) -> dict:
    raw = path.read_text(encoding="utf-8")
    src = strip_comments(raw)
    # Restrict to the class body (single card class per file).
    cls = re.search(r"export (?:abstract )?class \w+", src)
    body = src[cls.start():]
    # Constructor properties only: `metadata` holds the card RENDERER, whose
    # builder calls (b.action(...), b.vpText(...)) reuse the property names.
    # New fields are read from `props` so a renderer call can never be
    # mistaken for a declarative block.
    meta = re.search(r"^\s+metadata:\s*\{", body, re.M)
    props = body[:meta.start()] if meta else body

    card: dict = {"name": official_name}

    # Some cards (e.g. Mining Rights, Ecological Zone) take cost/type/tags via
    # constructor defaults or a shared parent class rather than `key: value`.
    parent_body = ""
    ext = re.search(r"export (?:abstract )?class \w+ extends (\w+)", src)
    if ext:
        parent_path = path.parent / f"{ext.group(1)}.ts"
        if parent_path.exists():
            parent_body = strip_comments(parent_path.read_text(encoding="utf-8"))

    if is_corp:
        card["type"] = "corporation"
        msc = field_value(body, "startingMegaCredits")
        card["cost"] = int(msc)
    else:
        ctype = (re.search(r"type:\s*CardType\.(\w+)", body)
                 or re.search(r"type:\s*CardType\.(\w+)", parent_body))
        card["type"] = ctype.group(1).lower()
        cost = field_value(body, "cost")
        if cost is None or not re.fullmatch(r"\s*\d+\s*", cost):
            m = (re.search(r"\bcost\s*=\s*(\d+)", body)
                 or re.search(r"super\(\s*name,\s*(\d+)", body))
            cost = m.group(1)
        card["cost"] = int(cost)

    tags_expr = field_value(body, "tags") or field_value(parent_body, "tags") or "[]"
    tags = [TAG_MAP[t] for t in re.findall(r"Tag\.([A-Z_]+)", tags_expr)]
    if card["type"] == "event" and "event" not in tags:
        tags.append("event")  # physical event cards carry the event tag
    card["tags"] = tags

    req = field_value(body, "requirements")
    card["requirements"] = parse_requirements(req) if req else None

    beh_expr = field_value(body, "behavior") or field_value(parent_body, "behavior")
    card["behavior"] = ts_object_to_data(beh_expr) if beh_expr else None

    # Bespoke-code detection: cards implementing effects in TS methods carry
    # mechanics the declarative blocks miss. `bespoke` is exactly "this class
    # overrides a hook", and `bespokeMethods` says which — so the audit can
    # show what is not modelled instead of one opaque flag.
    # Merge curated patches for known mechanical deltas so the engine
    # auto-applies them (Flooding's ocean, Moss's plant, ...).
    hooks = bespoke_methods(body)
    if hooks:
        card["bespoke"] = True
        card["bespokeMethods"] = hooks
    # A curated patch applies whether or not THIS class declares a hook: a
    # card can inherit its whole bespoke play from a base class (Mining
    # Rights extends MiningCard) and so carry no hook of its own, while its
    # mechanics are just as absent from the declarative block.
    patch = BEHAVIOR_PATCHES.get(official_name)
    if patch:
        merged = dict(card["behavior"] or {})
        for k, v in patch.items():
            if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        card["behavior"] = merged

    # `reserveUnits` is the vendor's play-time COST, declared beside
    # `behavior` instead of inside it. Fold it into the behavior block as
    # the engine's own `spend` so the interpreter charges it generically;
    # curated/declarative spend entries win on a collision.
    reserve = parse_reserve_units(
        field_value(props, "reserveUnits")
        or field_value(parent_body, "reserveUnits") or "")
    if reserve:
        merged = dict(card["behavior"] or {})
        merged["spend"] = {**reserve, **(merged.get("spend") or {})}
        card["behavior"] = merged

    resource = None
    rt = re.search(r"resourceType:\s*CardResource\.(\w+)", body)
    if rt:
        resource = rt.group(1)
    card["resourceType"] = resource.lower() if resource else None

    vp_expr = field_value(body, "victoryPoints")
    card["vp"] = parse_vp(vp_expr, resource, official_name) if vp_expr else None
    card["vpData"] = parse_vp_data(vp_expr) if vp_expr else None

    # Declarative price modifiers: tmlib.DISCOUNTS as vendor data.
    card["cardDiscount"] = ts_object_to_data(
        field_value(props, "cardDiscount") or "") or None
    cc = field_value(props, "cardCost")
    card["cardCost"] = int(cc) if cc and re.fullmatch(r"\s*-?\d+\s*", cc) else None

    num = re.search(rf"cardNumber:\s*{STRING_RE}", body)
    card["number"] = num.group(1) if num else None

    # --- human-readable text ---
    desc = None
    dm = re.search(r"description:\s*", body)
    if dm:
        start = dm.end()
        if body[start] == "{":
            chunk = balanced(body, start)
            tm = re.search(rf"text:\s*{STRING_RE}", chunk)
            desc = unescape(tm.group(1)) if tm else None
        else:
            sm = re.match(STRING_RE, body[start:])
            if sm:
                desc = unescape(sm.group(1))

    texts = {"effect": [], "action": [], "plainText": [], "text": []}
    for m in re.finditer(rf"\.(effect|action|plainText|text)\(\s*{STRING_RE}", body):
        kind, s = m.group(1), unescape(m.group(2))
        if s and s not in texts[kind]:
            texts[kind].append(s)

    actions = list(texts["action"])
    long_texts = []
    for kind in ("plainText", "text"):
        for s in texts[kind]:
            if s.startswith("(") and s.endswith(")"):
                s = s[1:-1]
            if s.startswith("Action: "):
                if s[8:] not in actions:
                    actions.append(s[8:])
            elif kind == "plainText" or len(s) >= 30:
                long_texts.append(s)

    effect_parts = []
    if desc:
        effect_parts.append(desc)
    effect_parts += long_texts
    effect_parts += [f"Effect: {t}" for t in texts["effect"]]
    card["effects"] = " ".join(effect_parts) if effect_parts else None
    # `action` stays PROSE: research.py, menu.py, cards.py and
    # tmlib._action_costs all parse it as text. The ActionCard `action:`
    # object literal goes into `actionBehavior` beside it, so phase 2 can
    # drive `use_action` generically without breaking any reader.
    card["action"] = "; ".join(actions) if actions else None
    card["actionBehavior"] = ts_object_to_data(field_value(props, "action") or "")

    ov = OVERRIDES.get(official_name, {})
    if "effects" in ov:
        card["effects"] = ov["effects"]
    if "action" in ov:
        card["action"] = ov["action"]
    if "vp_note" in ov:
        card["vp"] = ov["vp_note"]
    return card


def vendor_commit(vendor: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(vendor), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", type=Path, default=VENDOR)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    vendor = args.vendor
    if not (vendor / "src/server/cards/StandardCardManifests.ts").exists():
        die(f"vendor clone not found at {vendor}; run:\n"
            "  git clone --depth 1 https://github.com/terraforming-mars/terraforming-mars "
            "vendor/terraforming-mars")

    cardnames = parse_cardnames(vendor)
    imports, entries = parse_manifests(vendor)

    cards: list[dict] = []
    problems: list[str] = []
    for module, section, key, cls in entries:
        official = cardnames[key]
        if key == "BEGINNER_CORPORATION":
            continue  # not a real corporation; excluded from the 12
        path = imports.get(cls)
        if path is None or not path.exists():
            problems.append(f"missing source file for {official}")
            continue
        card = parse_card(path, official, is_corp=(section == "corporationCards"))
        card["module"] = {"base": "base", "corpera": "corporateEra"}[module]
        if not card["effects"] and not card["action"]:
            problems.append(f"no text extracted for {official}")
        cards.append(card)

    if problems:
        die("extraction problems:\n  " + "\n  ".join(problems))

    cards.sort(key=lambda c: (c["type"] == "corporation", c["name"].lower()))
    n_proj = sum(1 for c in cards if c["type"] != "corporation")
    n_corp = len(cards) - n_proj

    db = {
        "source": "https://github.com/terraforming-mars/terraforming-mars",
        "commit": vendor_commit(vendor),
        "modules": ["base", "corporateEra"],
        "counts": {"projectCards": n_proj, "corporations": n_corp},
        "cards": cards,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(db, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {n_proj} project cards, {n_corp} corporations")


if __name__ == "__main__":
    main()
