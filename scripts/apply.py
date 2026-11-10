#!/usr/bin/env python3
"""Apply one validated game event to state/game.json (and log it).

Every state change goes through here (or produce.py / setup.py) — never by hand.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import Engine, EventError, Store


def batch(eng: Engine, stream) -> int:
    """Apply JSON-lines events from `stream` in order.

    Each line: {"method": "<engine method>", "args": [...], "kwargs": {...}}
    — the same shape as plan step events. Every line is applied and
    committed before the next is read; on the first EventError the run
    stops with a nonzero exit naming the line number, and state from the
    lines BEFORE the failure remains committed.
    """
    for n, raw in enumerate(stream, 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError as e:
                raise EventError(f"bad JSON: {e}")
            if not isinstance(ev, dict) or "method" not in ev:
                raise EventError(
                    'each line needs {"method": ..., "args": [...], '
                    '"kwargs": {...}}')
            name = str(ev["method"])
            fn = getattr(eng, name, None) if not name.startswith("_") else None
            if not callable(fn):
                raise EventError(f"unknown engine method {name!r}")
            msg = fn(*ev.get("args", []), **ev.get("kwargs", {}))
            print(msg if msg is not None else f"{name}: ok")
        except EventError as e:
            print(f"ERROR: line {n}: {e}", file=sys.stderr)
            return 1
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("res", help="adjust a player's resource stock")
    s.add_argument("player"); s.add_argument("resource"); s.add_argument("delta", type=int)

    s = sub.add_parser("prod", help="adjust a player's production")
    s.add_argument("player"); s.add_argument("resource"); s.add_argument("delta", type=int)

    s = sub.add_parser("tr", help="adjust a player's TR directly")
    s.add_argument("player"); s.add_argument("delta", type=int)

    s = sub.add_parser("raise", help="player raises a global parameter (+1 TR)")
    s.add_argument("param", choices=["temperature", "oxygen", "oceans"])
    s.add_argument("player")

    s = sub.add_parser("sync", help="adopt an observed global value "
                                    "(sync temperature -20), or MY panel "
                                    "(sync me --mc 30 --prod-mc 5 --tr 22; "
                                    "— opponents use observe)")
    s.add_argument("--force", action="store_true",
                   help="allow downward correction of a phantom raise")
    s.add_argument("param", help="temperature | oxygen | oceans | me")
    s.add_argument("value", type=int, nargs="?", default=None)
    for f in ("tr", "mc", "steel", "titanium", "plants", "energy", "heat",
              "prod-mc", "prod-steel", "prod-titanium", "prod-plants",
              "prod-energy", "prod-heat"):
        s.add_argument(f"--{f}", type=int, default=None)

    s = sub.add_parser("wgt", help="World Government Terraforming step: first "
                                   "player raises a parameter, NO TR/bonuses "
                                   "(oceans need --hex)")
    s.add_argument("param", choices=["temperature", "oxygen", "oceans"])
    s.add_argument("--hex", default=None, help="ocean hex: grid ref (C4) or id")

    s = sub.add_parser("convert", help="8 heat→temperature or 8 plants→greenery")
    s.add_argument("player"); s.add_argument("kind", choices=["heat", "plants"])

    s = sub.add_parser("play", help="a card is played")
    s.add_argument("player"); s.add_argument("card")
    s.add_argument("--cost", type=int); s.add_argument("--steel", type=int, default=0)
    s.add_argument("--titanium", type=int, default=0)
    s.add_argument("--heat", type=int, default=0, help="Helion: spend heat as MC")
    s.add_argument("--choice", type=int, default=None,
                   help="or-choice cards: index of the branch the player "
                        "picked, counted in the ORDER THE CARD TEXT lists "
                        "them (0 = first option). Omit it once: the error "
                        "prints every branch with its index")
    s.add_argument("--ignore-requirements", nargs="?", const="no reason given",
                   default=False, metavar="WHY",
                   help="waive a closed/expired requirement window and log "
                        "WHY (Inventrix ±2, Adaptation Technology). Put it "
                        "AFTER the card name: play Anna 'Wave Power' "
                        "--ignore-requirements 'Inventrix ±2'")
    s.add_argument("--target", default=None,
                   help="victim for steal/remove cards (Power Supply "
                        "Consortium, Sabotage, asteroids' plant removal)")
    s.add_argument("--copy", default=None,
                   help="Robotic Workforce: the building card whose "
                        "production box is copied")
    s.add_argument("--olympus", choices=["add", "draw"], default=None,
                   help="Olympus Conference trigger on a science tag: add a "
                        "resource (default) or remove one to draw")
    s.add_argument("--no-effects", action="store_true",
                   help="charge the cost + record the card/tags, apply NO db "
                        "effects (then log res/prod events by hand)")

    s = sub.add_parser("action", help="blue-card action: the ledger plus the "
                                      "card's own effect, applied from the "
                                      "db's actionBehavior (cost, gains, "
                                      "globals, card resources)")
    s.add_argument("verb", choices=["register", "use"]); s.add_argument("name")
    s.add_argument("--player", default=None,
                   help="use: an OPPONENT's action (effect only, no ledger)")
    s.add_argument("--choice", default=None,
                   help="use: which branch of an 'X, or Y' action — a "
                        "TITLE SUBSTRING ('remove 3 microbes'), which means "
                        "the same branch in the app and in the sandbox, or "
                        "an index in card-text order (the refusal lists "
                        "them); a single executable branch auto-resolves")
    s.add_argument("--steel", type=int, default=0,
                   help="use: steel paid towards the action's MC cost "
                        "(1 ore = 2 MC; only where the card allows it)")
    s.add_argument("--titanium", type=int, default=0,
                   help="use: titanium paid towards the action's MC cost "
                        "(1 ore = 3 MC; only where the card allows it)")
    s.add_argument("--from-card", default=None, dest="from_card",
                   help="use: the card a 'remove 1 X from any card' action "
                        "took its resource from (tracked when it is the "
                        "actor's own card)")
    s.add_argument("--target", default=None, dest="action_target",
                   help="use: the victim of an action that hits a player")

    s = sub.add_parser("hand", help="manage my hand (ordered = play order)")
    s.add_argument("verb", choices=["add", "remove", "reorder"])
    s.add_argument("cards", nargs="+",
                   help="quote multi-word names: hand remove 'Giant Ice Asteroid'")

    s = sub.add_parser("dealt", help="research: 4 dealt (initial deal: 10), "
                                     "some kept (3 MC each)")
    s.add_argument("cards", nargs="+")
    s.add_argument("--kept", nargs="*", default=[])
    s.add_argument("--drafted", action="store_true",
                   help="draft variant: the cards were picked 1-pass-3; "
                        "logged as 'drafted A,B,C,D → kept X,Y'")
    s.add_argument("--override", default=None, metavar="WHY",
                   help="buy-0 gate: record a SECOND consecutive zero-kept "
                        "research anyway; the reason is logged")

    s = sub.add_parser("standard", help="standard project")
    s.add_argument("player")
    s.add_argument("project", choices=["sell_patents", "power_plant", "asteroid",
                                       "aquifer", "greenery", "city"])
    s.add_argument("--cards", nargs="*", default=None, help="cards to sell")

    s = sub.add_parser("sell", help="SELL PATENTS: discard cards from MY hand "
                                    "for 1 MC each (one event; the standard "
                                    "project sell_patents)")
    s.add_argument("cards", nargs="+",
                   help="quote multi-word names: sell 'Giant Ice Asteroid'")

    s = sub.add_parser("corp", help="record a player's corporation + starting MC")
    s.add_argument("player"); s.add_argument("name"); s.add_argument("--mc", type=int, required=True)

    s = sub.add_parser("milestone", help="claim a milestone (8 MC)")
    s.add_argument("player"); s.add_argument("name")

    s = sub.add_parser("award", help="fund an award (8/14/20 MC escalating)")
    s.add_argument("player"); s.add_argument("name")

    s = sub.add_parser("freecity", help="corp's free first-action city "
                       "(Tharsis Republic) — tile counter + corp trigger "
                       "only, no MC cost; still call place() for the hex")
    s.add_argument("player")

    s = sub.add_parser("place", help="record a tile on a board hex (position only)")
    s.add_argument("player"); s.add_argument("tile",
        choices=["city", "greenery", "ocean", "special"])
    s.add_argument("space", help="board.json space id (31) or grid ref (E3) "
                                 "— the online app's log prints grid refs")
    s.add_argument("--card", default=None,
                   help="card that produced a SPECIAL tile — required when it "
                        "is placed on an ocean-reserved area (Mohole Area)")

    s = sub.add_parser("spaces", help="list legal hexes for a tile type")
    s.add_argument("tile", choices=["city", "greenery", "ocean", "special"])
    s.add_argument("--sort", choices=["mine", "oceans", "bonus"], default=None,
                   help="order rows: mine (adjMine desc) | oceans (adjOceans "
                        "desc) | bonus (bonus-tile count desc); "
                        "default: engine order")

    s = sub.add_parser("observe", help="between-gen opponent mat snapshot (reconcile)")
    s.add_argument("player")
    for f in ("tr", "mc", "steel", "titanium", "plants", "energy", "heat",
              "prod-mc", "prod-steel", "prod-titanium", "prod-plants",
              "prod-energy", "prod-heat"):
        s.add_argument(f"--{f}", type=int, default=None)

    s = sub.add_parser("research", help="opponent kept N cards at research (-3 MC each)")
    s.add_argument("player"); s.add_argument("--kept", type=int, required=True)

    s = sub.add_parser("first", help="first-player exception (table override)")
    s.add_argument("player")

    s = sub.add_parser("gen", help="CORRECTION: force the generation counter "
                       "(e.g. undo a premature produce.py) — never for normal "
                       "turnover, that's produce.py's job")
    s.add_argument("n", type=int)

    s = sub.add_parser(
        "snap",
        help="opponent public-anchor absorption: set observed absolute "
             "value (tr, a resource, or card:<Card Name> for resources ON "
             "a card — animals, microbes, fighters; they are VP at scoring)")
    s.add_argument("player"); s.add_argument("field"); s.add_argument("value", type=int)
    s = sub.add_parser("unplace", help="remove a wrongly recorded tile: "
                       "unplace <player> <space> (owner verified) or the "
                       "older unplace <space>")
    s.add_argument("args", nargs="+", metavar="[player] space",
                   help="space = board id (63) or grid ref (I5 / app J5)")
    s = sub.add_parser("unplay", help="remove a wrongly recorded card play")
    s.add_argument("player"); s.add_argument("card")
    s = sub.add_parser("attack", help="removal vs a player; attacker may be unknown")
    s.add_argument("target"); s.add_argument("resource"); s.add_argument("n", type=int)
    s.add_argument("--by", default=None, help="attacker if known")
    s = sub.add_parser("attribute", help="resolve a pending attack attribution")
    s.add_argument("index", type=int); s.add_argument("attacker")
    sub.add_parser("final", help="table declared THIS generation final")
    s = sub.add_parser("note", help="free-text log entry")
    s.add_argument("text")

    sub.add_parser(
        "batch",
        help="apply JSON-lines events from stdin, one engine call per line",
        description='Read JSON lines from stdin, each '
                    '{"method": "<engine method>", "args": [...], '
                    '"kwargs": {...}} — the same shape as plan step events — '
                    "and apply them in order, printing each result line. "
                    "Every line is applied and COMMITTED before the next is "
                    "read: on the first bad line the run stops with a "
                    "nonzero exit naming the line number, and state changes "
                    "from the lines before the failure REMAIN committed "
                    "(re-run only the lines from the failure onward).")

    a = p.parse_args(argv)
    try:
        eng = Engine(Store())
        if a.cmd == "batch":
            return batch(eng, sys.stdin)
        if a.cmd == "res":
            msg = eng.res(a.player, a.resource, a.delta)
        elif a.cmd == "prod":
            msg = eng.prod(a.player, a.resource, a.delta)
        elif a.cmd == "tr":
            msg = eng.tr(a.player, a.delta)
        elif a.cmd == "raise":
            msg = eng.raise_param(a.param, by=a.player)
        elif a.cmd == "sync":
            if a.param in ("temperature", "oxygen", "oceans"):
                if a.value is None:
                    raise EventError(f"sync {a.param} needs the observed value")
                msg = eng.sync_global(a.param, a.value, force=a.force)
            else:                                  # sync me --mc N …
                msg = eng.sync_own(
                    a.param, tr=a.tr, mc=a.mc, steel=a.steel, titanium=a.titanium,
                    plants=a.plants, energy=a.energy, heat=a.heat,
                    prod_mc=a.prod_mc, prod_steel=a.prod_steel,
                    prod_titanium=a.prod_titanium, prod_plants=a.prod_plants,
                    prod_energy=a.prod_energy, prod_heat=a.prod_heat)
        elif a.cmd == "wgt":
            msg = eng.wgt(a.param, space_id=a.hex)
        elif a.cmd == "convert":
            msg = eng.convert(a.player, a.kind)
        elif a.cmd == "play":
            msg = eng.play(a.player, a.card, cost=a.cost, steel=a.steel,
                           titanium=a.titanium, heat=a.heat, choice=a.choice,
                           ignore_requirements=a.ignore_requirements,
                           target=a.target, copy=a.copy, olympus=a.olympus,
                           no_effects=a.no_effects)
        elif a.cmd == "action":
            if a.verb == "register":
                msg = eng.register_action(a.name)
            else:
                msg = eng.use_action(a.name, player=a.player,
                                     choice=a.choice, steel=a.steel,
                                     titanium=a.titanium,
                                     from_card=a.from_card,
                                     target=a.action_target)
        elif a.cmd == "hand":
            if a.verb == "add":
                msg = eng.hand_add(a.cards)
            elif a.verb == "remove":
                msg = "\n".join(eng.hand_remove(c) for c in a.cards)
            else:
                msg = eng.hand_reorder(a.cards)
        elif a.cmd == "dealt":
            msg = eng.dealt(a.cards, kept=a.kept, drafted=a.drafted,
                            override=a.override)
        elif a.cmd == "standard":
            msg = eng.standard(a.player, a.project, cards=a.cards)
        elif a.cmd == "sell":
            # the app's own Sell patents option: hand removal + 1 MC per
            # card, ONE logged event (P9 #2 — there was no verb for it)
            msg = eng.standard(eng.store.load_game()["me"]["name"],
                               "sell_patents", cards=a.cards)
        elif a.cmd == "corp":
            msg = eng.corp(a.player, a.name, mc=a.mc)
        elif a.cmd == "observe":
            msg = eng.observe(
                a.player, tr=a.tr, mc=a.mc, steel=a.steel, titanium=a.titanium,
                plants=a.plants, energy=a.energy, heat=a.heat,
                prod_mc=a.prod_mc, prod_steel=a.prod_steel,
                prod_titanium=a.prod_titanium, prod_plants=a.prod_plants,
                prod_energy=a.prod_energy, prod_heat=a.prod_heat)
        elif a.cmd == "milestone":
            msg = eng.milestone(a.player, a.name)
        elif a.cmd == "award":
            msg = eng.award(a.player, a.name)
        elif a.cmd == "research":
            msg = eng.research(a.player, kept=a.kept)
        elif a.cmd == "first":
            msg = eng.set_first_player(a.player)
        elif a.cmd == "gen":
            msg = eng.set_generation(a.n)
        elif a.cmd == "freecity":
            msg = eng.free_action_city(a.player)
        elif a.cmd == "place":
            msg = eng.place(a.player, a.tile, a.space, card=a.card)
        elif a.cmd == "spaces":
            rows = eng.legal_spaces(a.tile)
            me = eng.store.load_game()["me"]["name"]
            # own city/greenery/special tiles adjacent to each free hex —
            # placed oceans are owned by no one (official rule), so they
            # never count toward adjMine even when I placed them.
            for r in rows:
                r["_mine"] = [
                    (hx, t["tile"]) for hx, t in r["adjacentTiles"].items()
                    if t.get("player") == me and t.get("tile") != "ocean"]
            if a.sort == "mine":
                rows.sort(key=lambda r: len(r["_mine"]), reverse=True)
            elif a.sort == "oceans":
                rows.sort(key=lambda r: r["adjacentOceans"], reverse=True)
            elif a.sort == "bonus":
                rows.sort(key=lambda r: len(r.get("bonus") or []), reverse=True)
            lines = []
            for r in rows:
                line = (f"{r['id']:>3} {r['name'] or '':<20} bonus={r['bonus']} "
                        f"adjOceans={r['adjacentOceans']}")
                if r["adjacentTiles"]:
                    mine = r["_mine"]
                    line += f" adjMine={len(mine)}"
                    if mine:
                        line += " (" + ", ".join(
                            f"{t} {hx}" for hx, t in mine) + ")"
                    line += (" adj="
                             f"{ {k: v['tile'] for k, v in r['adjacentTiles'].items()} }")
                lines.append(line)
            msg = "\n".join(lines)
        elif a.cmd == "snap":
            msg = eng.snap(a.player, a.field, a.value)
        elif a.cmd == "unplace":
            if len(a.args) == 1:
                msg = eng.unplace(a.args[0])
            elif len(a.args) == 2:
                msg = eng.unplace(a.args[1], player=a.args[0])
            else:
                raise EventError("unplace takes <player> <space> or <space>, "
                                 f"got {a.args}")
        elif a.cmd == "unplay":
            msg = eng.unplay(a.player, a.card)
        elif a.cmd == "attack":
            msg = eng.attack(a.target, a.resource, a.n, by=a.by)
        elif a.cmd == "attribute":
            msg = eng.attribute(a.index, a.attacker)
        elif a.cmd == "final":
            msg = eng.declare_final()
        elif a.cmd == "note":
            game = eng.store.load_game()
            eng.store.log(f"G{game['generation']}", a.text)
            msg = f"Noted: {a.text}"
        print(msg)
        return 0
    except (EventError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
