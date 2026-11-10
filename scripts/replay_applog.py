#!/usr/bin/env python3
"""Replay an online-app log export through the Engine.

    replay_applog.py <applog.txt> --setup <setup.json> --out <dir>
                     [--expect <final-state.json>] [--quiet]

Builds a fresh game session under <dir>/state/ (Store.init, the same path the
tests use) and feeds every export line to the Engine as events, in order,
printing a per-line trace and a final summary. The point is REGRESSION: the
app's final state is truth, the engine's drift from it is the to-do list.

Design rules:
- Prefer the engine's own verbs: "X played Y" → Engine.play (db cost),
  "used … standard project" → Engine.standard, conversions → Engine.convert,
  tiles → Engine.place (bonuses + ocean adjacency), WGT → Engine.wgt,
  "Generation N" → Engine.produce, milestones/awards → their verbs.
- Every explicit "gained / lost / stole / lost … because of" line is
  AUTHORITATIVE: after the engine verb(s) of a block, every (player, stat)
  delta is compared with what the log stated and the difference is applied
  as a correction and recorded as a GAP ("Zeppelins: db +6 MC prod, log +7").
  Costs the app never prints (MC paid for cards, steel/titanium payments,
  8 plants / 8 heat for conversions) are taken from the engine call itself —
  so MC drifts by exactly the discounts/rebates the engine does not model.
  That drift is the fixture's payload: it is collected, never hidden.
- A verb the engine lacks (blue-card action effects, TR from an unmodelled
  card, opponent card sales) is emulated with primitives (res/prod/tr/raise)
  and recorded as a gap of kind "emulated".
- Shortfalls (the engine would refuse a payment/conversion the app accepted)
  are topped up and recorded ("topup") — the total per player is reported so
  "engine MC net of top-ups" can be compared with the app's number.
- Unknown lines never crash: they are recorded ("unknown") and skipped.

The parser lives in scripts/applog_parser.py (pure functions) so the future
online listener can import it.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import applog_parser as P                     # noqa: E402
import tmlib                                  # noqa: E402
from tmlib import (AWARD_COSTS, CARD_KEEP_COST, MILESTONE_COST,   # noqa: E402
                   PARAM_SCALE, RESOURCES, STANDARD_PROJECTS, Engine,
                   EventError, Store, grid_to_space, split_payment)

STAT_KINDS = ("res", "prod")


class Report:
    def __init__(self):
        self.gaps: list[dict] = []
        self.notes: list[dict] = []
        self.unknown_lines: list[dict] = []
        self.topups: dict = defaultdict(lambda: defaultdict(int))
        self.lines_seen = 0
        self.trace: list[str] = []
        self.game: dict | None = None
        self.final_production_done = False

    def gap(self, kind: str, line: int, label: str, what: str, **extra):
        entry = {"kind": kind, "line": line, "label": label, "what": what, **extra}
        self.gaps.append(entry)
        return entry

    def note(self, line: int, label: str, what: str):
        self.notes.append({"line": line, "label": label, "what": what})

    # ── rendering ────────────────────────────────────────────
    def summary(self, expect: dict | None = None) -> str:
        g = self.game
        out = ["", "=== REPLAY SUMMARY ==="]
        out.append(f"lines: {self.lines_seen}, gaps: {len(self.gaps)}, "
                   f"unknown lines: {len(self.unknown_lines)}")
        out.append(f"globals: {g['globals']} generation {g['generation']}")
        pools = {g["me"]["name"]: g["me"], **g["opponents"]}
        for name, pool in pools.items():
            top = self.topups.get(name, {})
            out.append(f"  {name:7} TR {pool['tr']:3}  res {pool['resources']}  "
                       f"prod {pool['production']}"
                       + (f"  topups {dict(top)}" if top else ""))
        out.append(f"tiles: {len(g.get('board', {}))} on board")
        if expect:
            out.append("")
            out.append("=== ENGINE vs APP FINAL STATE ===")
            eg = expect["globals"]
            for k in ("temperature", "oxygen", "oceans"):
                mark = "ok " if g["globals"][k] == eg[k] else "DIFF"
                out.append(f"  {mark} {k}: engine {g['globals'][k]} app {eg[k]}")
            for name, pool in pools.items():
                ep = expect["players"][name]
                mark = "ok " if pool["tr"] == ep["tr"] else "DIFF"
                out.append(f"  {mark} {name} TR: engine {pool['tr']} app {ep['tr']}")
                for r in RESOURCES:
                    a, b = pool["production"][r], ep["production"][r]
                    if a != b:
                        out.append(f"  DIFF {name} {r} prod: engine {a} app {b}")
                for r in RESOURCES:
                    a, b = pool["resources"][r], ep["resources"][r]
                    top = self.topups.get(name, {}).get(r, 0)
                    if a != b or top:
                        net = f" (net of top-ups {a - top})" if top else ""
                        out.append(f"  {'ok ' if a == b else 'DIFF'} {name} {r} stock: "
                                   f"engine {a} app {b}{net}")
            exp_tiles = {sid: t for sid, t, _ in expect["tiles"]}
            got = set(g.get("board", {}))
            missing = sorted(set(exp_tiles) - got)
            extra = sorted(got - set(exp_tiles))
            out.append(f"  tiles: {'ok ' if not missing and not extra else 'DIFF'} "
                       f"missing {missing} extra {extra}")
        out.append("")
        out.append("=== GAPS (engine vs log) ===")
        by_kind = defaultdict(list)
        for gp in self.gaps:
            by_kind[gp["kind"]].append(gp)
        for kind in sorted(by_kind):
            out.append(f"-- {kind} ({len(by_kind[kind])})")
            for gp in by_kind[kind]:
                out.append(f"  L{gp['line']:<4} {gp['label']}: {gp['what']}")
        if self.topups:
            out.append("-- top-up totals per player")
            for name, d in self.topups.items():
                out.append(f"  {name}: {dict(d)}")
        return "\n".join(out)


class Replayer:
    def __init__(self, engine: Engine, report: Report, verbose: bool = True,
                 pay_metals: bool = True):
        self.eng = engine
        self.rep = report
        self.verbose = verbose
        self.pay_metals = pay_metals
        self.me = next(p["name"] for p in engine.setup["players"] if p["isMe"])
        self.players = [p["name"] for p in engine.setup["players"]]
        self.final_mode = False
        # The generation the lines being replayed belong to: set by every
        # "Generation N" head, or by block(gen=…) from a caller that reads
        # the app's log per generation (listen.py). None = unknown, the
        # engine then assumes the current generation. Own blue-card actions
        # pass it into Engine.use_action so an echo of an OLDER generation
        # is absorbed (D3 / H1c) instead of consuming the current ledger.
        self.gen: int | None = None

    # ── helpers ─────────────────────────────────────────────
    def game(self) -> dict:
        return self.eng.store.load_game()

    def pool(self, game: dict, name: str) -> dict:
        return game["me"] if name == self.me else game["opponents"][name]

    def snapshot(self) -> dict:
        g = self.game()
        return {
            "players": {n: {"tr": self.pool(g, n)["tr"],
                            "res": dict(self.pool(g, n)["resources"]),
                            "prod": dict(self.pool(g, n)["production"]),
                            "cards": dict(self.pool(g, n).get("cardResources")
                                          or {}),
                            "tiles": dict(self.pool(g, n)["tiles"])}
                        for n in self.players},
            "globals": dict(g["globals"]),
        }

    def out(self, msg: str, indent: int = 4):
        first = msg.splitlines()[0] if msg else ""
        line = " " * indent + first
        self.rep.trace.append(line)
        if self.verbose:
            print(line)

    def call(self, label: str, line: int, fn, *args, **kwargs):
        """Engine verb with error capture: EventError → gap, returns None."""
        try:
            msg = fn(*args, **kwargs)
            self.out(msg)
            return msg
        except EventError as e:
            self.rep.gap("refused", line, label, f"{fn.__name__}{args}: {e}")
            self.out(f"REFUSED {fn.__name__}{args}: {e}")
            return None

    def ensure(self, player: str, res: str, need: int, line: int, label: str) -> int:
        """Top up a stock so the app-accepted payment/conversion can be
        applied; returns the top-up amount (0 if none)."""
        have = self.pool(self.game(), player)["resources"][res]
        if have >= need:
            return 0
        deficit = need - have
        self.eng.res(player, res, deficit)
        self.rep.topups[player][res] += deficit
        self.rep.gap("topup", line, label,
                     f"{player} {res} {have} < {need} needed — topped up {deficit} "
                     f"(untracked discount/rebate/payment drift)")
        self.out(f"TOP-UP {player} {res} +{deficit} (had {have}, needs {need})")
        return deficit

    def ensure_in_hand(self, card: str, line: int, label: str) -> None:
        g = self.game()
        if card in g["me"]["hand"]:
            return
        info = self.eng.card(card)
        canon = info["name"] if info else card
        if canon in g["me"]["hand"]:
            return
        self.eng.hand_add([canon])
        self.rep.note(line, label, f"{canon} not in tracked hand (initial 10-card "
                                   "deal and sold cards are not named by the "
                                   "export) — added")

    # ── block driver ─────────────────────────────────────────
    def run(self, blocks: list[dict]) -> None:
        for b in blocks:
            self.block(b)
        if not self.rep.final_production_done:
            self.final_production(0)
        self.rep.game = self.game()

    def block(self, b: dict, gen: int | None = None) -> None:
        """gen: the generation this block's lines were logged in, when the
        caller knows it (the listener drains the app's log per
        generation); a "Generation N" head sets it as well."""
        head, tail = b["head"], b["tail"]
        line = head.get("line", 0)
        if gen is not None:
            self.gen = int(gen)
        if self.verbose:
            print(f"[L{line}] {head.get('raw', head['kind'])}")
            for e in tail:
                print(f"[L{e.get('line', 0)}]   {e.get('raw', e['kind'])}")
        kind = head["kind"]
        if kind == "unknown":
            self.rep.unknown_lines.append(head)
            self.rep.gap("unknown", line, "?", head.get("raw", ""))
            return
        if kind == "generation":
            self.gen = int(head["n"])
            if head["n"] > 1:
                self.call("produce", line, self.eng.produce)
            return
        if kind == "first_player":
            g = self.game()
            if g["firstPlayer"] != head["player"]:
                self.rep.gap("rotation", line, "first player",
                             f"engine {g['firstPlayer']}, app {head['player']}")
                self.call("first player", line, self.eng.set_first_player, head["player"])
            return
        if kind == "final_greenery":
            self.final_production(line)
            self.final_mode = True
            return
        if kind in ("passed", "ended_turn", "ignore"):
            return

        # ── a state-changing block: snapshot, apply, reconcile ──
        before = self.snapshot()
        known = defaultdict(int)          # (player, kind, stat) → delta
        label = self.label(head)
        actor = head.get("player")
        if kind == "played":
            self.do_play(head, tail, known)
        elif kind == "kept":
            self.do_keep(head, known)
        elif kind == "bought":
            self.do_buy(head, known)
        elif kind == "used_action":
            self.do_action(head, tail, known)
        elif kind == "used_standard":
            self.do_standard(head, tail, known)
        elif kind == "funded":
            self.do_award(head, known)
        elif kind == "claimed":
            self.do_milestone(head, known)
        elif kind == "wgt":
            self.call(label, line, self.eng.wgt, head["param"], space_id=head.get("space"))
        elif kind == "final_placed":
            self.do_final_placed(head, known)
        elif kind == "drew":
            pass
        elif kind == "first_action":
            # A corporation's free first action (Tharsis Republic's city,
            # Inventrix's draw, Valley Trust's prelude). The head itself
            # costs nothing and the app's own consequence lines carry the
            # whole effect — but the block used to RETURN here, so that
            # tail was dropped and the free city never reached the board.
            pass
        elif kind == "late_tail":
            # the live listener (scripts/listen.py): consequence lines of a
            # head applied in an earlier drain — tail + reconciliation only
            pass
        else:
            self.rep.gap("unknown", line, label, f"no handler for head kind {kind!r}")
        # consequence lines that are engine verbs of their own
        self.do_tail(head, tail, known)
        self.tile_counters(head, tail, before)
        self.ocean_counter(head, tail)
        self.oxygen_bonus(head, before)
        self.reconcile(head, tail, before, known)

    def label(self, head: dict) -> str:
        k = head["kind"]
        if k == "played":
            return head["card"]
        if k == "used_action":
            return f"{head['card']} action"
        if k == "used_standard":
            return f"SP {head['project']}"
        if k == "wgt":
            return f"WGT {head['param']}"
        if k == "final_placed":
            return "final greenery"
        if k in ("funded", "claimed"):
            return f"{k} {head.get('award') or head.get('milestone')}"
        if k in ("kept", "bought"):
            return f"research {k}"
        if k == "late_tail":
            return "late consequences"
        return k

    # ── heads ────────────────────────────────────────────────
    def in_tableau(self, player: str, card: str) -> bool:
        """Is this card already recorded in the player's tableau?"""
        try:
            pool = self.pool(self.game(), player)
        except KeyError:
            return False
        return any((c.get("name") or "").lower() == card.lower()
                   for c in pool.get("playedCards") or [])

    def do_play(self, head: dict, tail: list, known: dict) -> None:
        player, card, line = head["player"], head["card"], head["line"]
        info = self.eng.card(card)
        if (player != self.me and (info or {}).get("type") != "corporation"
                and self.in_tableau(player, (info or {}).get("name") or card)):
            # verify.py --sync diffs the app's public tableau and records
            # what it finds with Engine.observe_play (bookkeeping only),
            # then adopts the app's TR/stock/production and the app's
            # globals wholesale. Replaying the same "X played Y" line
            # afterwards appended a SECOND playedCards entry and charged
            # the card again: Media Archives counted 14 events where the
            # app paid 13 (p8 #18, Convoy From Europa twice in gen 10).
            # The log's own consequence lines still run (do_tail /
            # reconcile) — only the play itself is not repeated.
            self.rep.gap("already-recorded", line, (info or {}).get("name") or card,
                         f"{player} already holds this card in playedCards "
                         "(verify.py --sync observed the app tableau and adopted "
                         "the app's figures) — the play is NOT applied twice")
            self.out(f"ALREADY RECORDED {card} for {player} — play skipped")
            return
        if info is None:
            self.rep.gap("unknown-card", line, card, "not in cards/db.json — "
                         "played with cost 0, effects from the log only")
            if player == self.me:
                self.ensure_in_hand(card, line, card)
            self.call(card, line, self.eng.play, player, card, cost=0)
            return
        card = info["name"]
        if info["type"] == "corporation":
            self.call(card, line, self.eng.corp, player, card, mc=info["cost"])
            known[(player, "res", "mc")] += info["cost"]
            return
        cost = info["cost"]
        # The engine applies corp/tableau discounts inside play(); the
        # replay must budget the same discounted price, not the printed one.
        try:
            disc, _notes, _next = self.eng._card_discount(self.game(), player, info)
            cost = max(0, cost - disc)
        except Exception:                      # engine without discounts
            pass
        if player == self.me:
            self.ensure_in_hand(card, line, card)
        # the log names every card-resource add/remove for EVERY player,
        # so a played accumulator card's count is known (explicit 0) even
        # when the session's setup says physical (aliased fixtures)
        kwargs = {"count_known": True}
        # metals off the PRINTED cost (the app's dialog pre-fills them
        # before the discount lands: the 4p fixture's final titanium only
        # matches this way), MC off the discounted one.
        steel, titanium, heat = self.metal_payment(player, info)
        mc_due = split_payment(self.game(), player, cost, steel=steel,
                               titanium=titanium, heat=heat)["mc"]
        if steel:
            kwargs["steel"] = steel
            known[(player, "res", "steel")] -= steel
        if titanium:
            kwargs["titanium"] = titanium
            known[(player, "res", "titanium")] -= titanium
        if heat:
            kwargs["heat"] = heat
            known[(player, "res", "heat")] -= heat
        known[(player, "res", "mc")] += self.ensure(player, "mc", mc_due, line, card)
        choice = self.pick_choice(info, player, tail)
        if choice is not None:
            kwargs["choice"] = choice
        # "X copied <Card> production with Robotic Workforce" → play(copy=)
        for e in tail:
            if e["kind"] == "copied" and e.get("player") == player and e.get("card"):
                kwargs["copy"] = e["card"]
                break
        try:
            msg = self.eng.play(player, card, **kwargs)
        except EventError as e:
            if "requirement not met" in str(e):
                self.rep.gap("requirement", line, card,
                             f"engine refused ({e}); the app allowed it — replayed "
                             "with ignore_requirements")
                kwargs["ignore_requirements"] = True
                msg = self.call(card, line, self.eng.play, player, card, **kwargs)
            else:
                msg = None
                if "--target" in str(e) or "--choice" in str(e):
                    # An attack/choice card (Sabotage, Predators, Power
                    # Supply Consortium). The APP already resolved the
                    # interaction and its own follow-up lines carry the
                    # effect, so the missing interactive args are not an
                    # error: record the card and charge the price the
                    # engine quoted.
                    #
                    # This used to apply to OPPONENTS only; my own such
                    # play was a plain "refused" and the card never
                    # reached playedCards at all — the P8 replay lost two
                    # of my own cards (and their VP) from the tableau.
                    self.call(card, line, self.eng.observe_play, player, card,
                              allow_me=(player == self.me))
                    if mc_due:
                        self.call(card, line, self.eng.res, player, "mc", -mc_due)
                        known[(player, "res", "mc")] -= mc_due
                    for r, n in (("steel", steel), ("titanium", titanium),
                                 ("heat", heat)):
                        if n:
                            self.call(card, line, self.eng.res, player, r, -n)
                    self.rep.gap("observed", line, card,
                                 f"choice card recorded without its "
                                 f"interactive args ({e}); the log's own "
                                 f"consequence lines carry the effect")
                    return
                self.rep.gap("refused", line, card, f"play: {e}")
                if player != self.me:
                    self.call(card, line, self.eng.observe_play, player, card)
                    self.rep.note(line, card, "bookkeeping-only observe_play fallback")
        if msg is not None:
            self.out(msg)
            known[(player, "res", "mc")] -= mc_due
            for st in msg.splitlines()[1:]:
                if "→ TABLE" in st or "BESPOKE" in st:
                    self.rep.note(line, card, st.strip())
        else:
            # play refused: the metal/heat payment was never taken
            known[(player, "res", "steel")] += steel
            known[(player, "res", "titanium")] += titanium
            known[(player, "res", "heat")] += heat

    def metal_payment(self, player: str, info: dict,
                      cost: int | None = None) -> tuple[int, int, int]:
        """The export never prints what a card was paid with. The app's
        payment dialog pre-fills the maximum steel (building tag) and
        titanium (space tag) — this models players accepting that default:
        as many metals as the cost absorbs, from the tracked stock. The
        final steel/titanium counts in the report say how good the model is.
        Off with pay_metals=False.

        A corporation that spends HEAT as MC (`heatAsMC`) pays the rest of
        the bill out of the heat pile when the cash is short — the app does
        it silently, and modelling it as an MC top-up instead left that
        player holding heat they had already spent (P8: 39 heat, 33 MC of
        top-ups on one seat). Returns (steel, titanium, heat).

        The mix itself is THE splitter's (`tmlib.split_payment`) — the
        replayer used to prefer titanium and carried no heat term at all,
        so it disagreed with the menu and the engine on the same play.
        """
        if not self.pay_metals:
            return 0, 0, 0
        pay = split_payment(self.game(), player,
                            info["cost"] if cost is None else cost,
                            tags=info.get("tags"))
        return pay["steel"], pay["titanium"], pay["heat"]

    def pick_choice(self, info: dict, player: str, tail: list):
        beh = info.get("behavior") or {}
        if "or" not in beh:
            return None
        stated = defaultdict(int)
        for e in tail:
            if e["kind"] in ("gained_prod", "lost_prod") and e["player"] == player:
                stated[e["resource"]] += e["n"] if e["kind"] == "gained_prod" else -e["n"]
        branches = (beh["or"] or {}).get("behaviors", [])
        for i, br in enumerate(branches):
            prod = {("mc" if k == "megacredits" else k): v
                    for k, v in (br.get("production") or {}).items()}
            if prod and all(stated.get(k) == v for k, v in prod.items()):
                return i
        self.rep.gap("or-choice", tail[0]["line"] if tail else 0, info["name"],
                     f"no branch matches the log's production lines {dict(stated)} "
                     "— branch 0 used")
        return 0

    def do_keep(self, head: dict, known: dict) -> None:
        player, n, line = head["player"], head["n"], head["line"]
        cost = CARD_KEEP_COST * n
        if player == self.me:
            known[(player, "res", "mc")] += self.ensure(player, "mc", cost, line, "initial keep")
            self.call("initial keep", line, self.eng.res, player, "mc", -cost)
            self.rep.note(line, "initial keep", f"{n} cards kept, names not exported "
                                                "— hand unknown, −{cost} MC via res")
        else:
            self.call("initial keep", line, self.eng.research, player, kept=n)
        known[(player, "res", "mc")] -= cost

    def do_buy(self, head: dict, known: dict) -> None:
        player, n, line = head["player"], head["n"], head["line"]
        cards = head.get("cards") or []
        cost = CARD_KEEP_COST * n
        if n == 0:
            return
        if player == self.me and len(cards) == n:
            known[(player, "res", "mc")] += self.ensure(player, "mc", cost, line, "research")
            self.call("research", line, self.eng.dealt, cards, kept=cards)
        elif player == self.me:
            known[(player, "res", "mc")] += self.ensure(player, "mc", cost, line, "research")
            self.call("research", line, self.eng.res, player, "mc", -cost)
            self.rep.note(line, "research", f"{n} bought, names missing — −{cost} MC via res")
        else:
            known[(player, "res", "mc")] += self.ensure(player, "mc", cost, line, "research")
            self.call("research", line, self.eng.research, player, kept=n)
        known[(player, "res", "mc")] -= cost

    # blue-card actions: Engine.use_action drives every card whose db entry
    # carries an `actionBehavior` (the vendor's own ActionCard block). The
    # log never prints an action's COST, so the stock is topped up first and
    # the reconciliation treats the engine's charge as an unlogged cost.
    def action_choice(self, info: dict, player: str, tail: list):
        """Which or-branch the app took, read off the log's own consequence
        lines: 'removed N <resource>' = the branch that spends N resources
        from the card; anything else = the branch that adds one."""
        beh = (info or {}).get("actionBehavior") or {}
        if not isinstance(beh.get("or"), dict):
            return None
        removed = sum(e["n"] for e in tail
                      if e["kind"] == "card_resource" and e["verb"] == "remove"
                      and e["player"] == player)
        branches = tmlib.or_branches(info, behavior=beh,
                                     text=info.get("action"))
        for b in branches:
            need = (b.get("spend") or {}).get("resourcesHere")
            if removed and need == removed:
                return b["index"]
        if removed:
            return None
        for b in branches:
            if b.get("addResources") and not b.get("spend"):
                return b["index"]
        return None

    def action_topup(self, player: str, info: dict, choice, line: int,
                     label: str, known: dict) -> None:
        """Top up every stock the action's `spend` block will charge (the app
        accepted the action, so a tracker gap must not refuse it) and record
        the charge in `known` — the log never prints an action's cost, so the
        reconciliation would otherwise read it as engine drift."""
        options = tmlib.action_spend_options(info)
        if not options:
            return
        spend = options[choice] if choice is not None and \
            0 <= choice < len(options) else options[0]
        for key, val in spend.items():
            r = tmlib.SPEND_RESOURCES.get(key)
            if r and isinstance(val, int) and val > 0:
                known[(player, "res", r)] += self.ensure(player, r, val,
                                                         line, label)
                known[(player, "res", r)] -= val

    def do_action(self, head: dict, tail: list, known: dict) -> None:
        player, card, line = head["player"], head["card"], head["line"]
        label = f"{card} action"
        info = self.eng.card(card)
        canon = info["name"] if info else card
        if isinstance((info or {}).get("actionBehavior"), dict):
            choice = self.action_choice(info, player, tail)
            g = self.game()
            # an own action echoed from an OLDER generation than the
            # tracker's: its use was counted when that generation closed —
            # the engine absorbs it (use_action gen=…), so neither the
            # spend top-up nor the ledger reopening below may run
            stale = (player == self.me and self.gen is not None
                     and self.gen < g["generation"])
            if not stale:
                self.action_topup(player, info, choice, line, label, known)
            if player == self.me and not stale:
                # the replay never saw the `play` that registered the action
                # (and a second use in one generation is legal in the app's
                # own log only across generations) — reopen the ledger slot
                key = self.eng._ledger_key(g, canon)
                entry = (g["me"]["actionsThisGen"] or {}).get(key)
                if entry is None or entry.get("used"):
                    self.eng.register_action(canon)
            kwargs = {} if player == self.me else {"player": player}
            if choice is not None:
                kwargs["choice"] = choice
            if player == self.me and self.gen is not None:
                kwargs["gen"] = self.gen
            self.call(label, line, self.eng.use_action, canon, **kwargs)
            return
        # The actions the vendor implements as TypeScript (action() /
        # canAct()) instead of an ActionCard block: there is no db behavior
        # to drive, so the price comes from menu.PROSE_ACTIONS — ONE table,
        # the same one the menu quotes (this used to be a per-card branch
        # chain here, the last one in the tree).
        import menu
        spec = menu.PROSE_ACTIONS.get(canon)
        if spec is None:
            self.rep.gap("unmodelled-action", line, label,
                         "no actionBehavior in cards/db.json for this action "
                         "— only the log's explicit lines were applied")
            return
        mc_gained = sum(e["n"] for e in tail
                        if e["kind"] == "gained" and e["resource"] == "mc"
                        and e["player"] == player)
        paid = []
        for res, n in menu.prose_cost(spec, mc_gained).items():
            if not n:
                continue
            known[(player, "res", res)] += self.ensure(player, res, n, line, label)
            self.call(label, line, self.eng.res, player, res, -n)
            known[(player, "res", res)] -= n
            paid.append(f"{n} {res}")
        gain = spec.get("gain")
        if gain and mc_gained:
            self.call(label, line, self.eng.res, player, gain, mc_gained)
        if spec.get("tr"):
            self.call(label, line, self.eng.tr, player, +int(spec["tr"]))
        self.rep.gap("emulated", line, label,
                     "no engine verb for blue-card action effects — "
                     + (f"paid {' + '.join(paid)} (not in the log)" if paid
                        else "the log's own lines carry it")
                     + (f", +{spec['tr']} TR" if spec.get("tr") else "")
                     + (f", +{mc_gained} {gain}" if gain and mc_gained else ""))

    def do_standard(self, head: dict, tail: list, known: dict) -> None:
        player, project, line = head["player"], head["project"], head["line"]
        label = f"SP {project}"
        if project in ("convert_heat", "convert_plants"):
            kind = "heat" if project == "convert_heat" else "plants"
            need = 8 if kind == "heat" else tmlib.greenery_plant_cost(
                self.eng._corp_of(self.game(), player))
            known[(player, "res", kind)] += self.ensure(player, kind, need,
                                                        line, label)
            if self.call(label, line, self.eng.convert, player, kind) is not None:
                known[(player, "res", kind)] -= need
                return
            # convert() also REFUSES a conversion that gains nothing (the
            # parameter is already maxed) — good advice at the table, but
            # the app accepted it and burned the resource, and this is a
            # replay of the app. Take the cost, keep the advice.
            # (P7 gen 12: a seat converted heat twice into a maxed
            # temperature; without this the replay held 8 heat the app
            # did not.)
            self.call(label, line, self.eng.res, player, kind, -need)
            known[(player, "res", kind)] -= need
            self.rep.gap("emulated", line, label,
                         f"the engine refuses a conversion that gains nothing; "
                         f"the app took the {need} {kind} anyway — charged via res")
            return
        if project == "sell_patents":
            sold = sum(e["n"] for e in tail if e["kind"] == "sold" and e["player"] == player)
            if sold:
                self.call(label, line, self.eng.res, player, "mc", +sold)
                known[(player, "res", "mc")] += sold
            self.rep.gap("emulated", line, label,
                         f"sold {sold} card(s) for {sold} MC via res (card names not "
                         "exported; standard(sell_patents) needs them)")
            return
        if project not in STANDARD_PROJECTS:
            self.rep.gap("unknown", line, label, "unknown standard project")
            return
        cost = STANDARD_PROJECTS[project]
        try:
            off, _n = self.eng._standard_discount(self.game(), player, project)
            cost = max(0, cost - off)
        except Exception:
            pass
        # a heatAsMC corporation pays the shortfall out of the heat pile
        # (the app does; the export prints neither half) — THE splitter
        pay = split_payment(self.game(), player, cost)
        heat, mc_due = pay["heat"], pay["mc"]
        known[(player, "res", "mc")] += self.ensure(player, "mc", mc_due, line, label)
        before_prod = dict(self.pool(self.game(), player)["production"])
        if self.call(label, line, self.eng.standard, player, project,
                     heat=heat) is not None:
            known[(player, "res", "mc")] -= mc_due
            known[(player, "res", "heat")] -= heat
            # A standard project's OWN production step can be SILENT in the
            # export: the vendor adds it with player.production.add() and no
            # log option, so the Power Plant's +1 energy never appears — and
            # in the local server's log neither does the City's +1 M€.
            # (The online build the game-night export came from DOES print
            # the City step, so the rule cannot be per project.)
            #
            # The export is all-or-nothing per block: either it names the
            # actor's production changes or it names none of them. So credit
            # the engine's own step ONLY when the block printed no production
            # line for the actor at all; otherwise the log wins, exactly as
            # for every other event.
            #
            # Before this, the silent step was read as engine drift and
            # REMOVED: in the P7 game two opponents finished the replay 2 M€
            # production light (two City standard projects each) and the
            # third 1 light, so every income projection and the Banker race
            # read low from gen 4 on.
            if not any(e.get("player") == player
                       and e["kind"] in ("gained_prod", "lost_prod")
                       for e in tail):
                after_prod = self.pool(self.game(), player)["production"]
                for r in RESOURCES:
                    silent = after_prod[r] - before_prod[r]
                    if silent:
                        known[(player, "prod", r)] += silent

    def do_award(self, head: dict, known: dict) -> None:
        player, line = head["player"], head["line"]
        g = self.game()
        slot = len(g.get("awardsFunded", {}))
        cost = AWARD_COSTS[slot] if slot < len(AWARD_COSTS) else 0
        label = f"funded {head['award']}"
        known[(player, "res", "mc")] += self.ensure(player, "mc", cost, line, label)
        if self.call(label, line, self.eng.award, player, head["award"]) is not None:
            known[(player, "res", "mc")] -= cost

    def do_milestone(self, head: dict, known: dict) -> None:
        player, line = head["player"], head["line"]
        label = f"claimed {head['milestone']}"
        known[(player, "res", "mc")] += self.ensure(player, "mc", MILESTONE_COST, line, label)
        msg = self.call(label, line, self.eng.milestone, player, head["milestone"])
        if msg is not None:
            known[(player, "res", "mc")] -= MILESTONE_COST
            if "⚠" in msg:
                self.rep.gap("eligibility", line, label, msg.split("⚠", 1)[1].strip())

    def do_final_placed(self, head: dict, known: dict) -> None:
        player, line = head["player"], head["line"]
        label = "final greenery"
        need = tmlib.greenery_plant_cost(
            self.eng._corp_of(self.game(), player))
        known[(player, "res", "plants")] += self.ensure(player, "plants", need, line, label)
        if self.call(label, line, self.eng.convert, player, "plants") is not None:
            known[(player, "res", "plants")] -= need
        self.place(player, "greenery", head["space"], None, line, label)

    def final_production(self, line: int) -> None:
        """The app runs the production phase before the final greenery
        placement and game end (Game.ts gotoProductionPhase → gotoEndGeneration
        → gotoFinalGreeneryPlacement)."""
        if self.rep.final_production_done:
            return
        self.call("final production", line, self.eng.produce)
        self.rep.final_production_done = True

    # ── consequences ─────────────────────────────────────────
    def do_tail(self, head: dict, tail: list, known: dict) -> None:
        label = self.label(head)
        card = head.get("card") if head["kind"] == "played" else None
        for e in tail:
            line = e.get("line", 0)
            k = e["kind"]
            if k == "placed":
                self.place(e["player"], e["tile"], e["space"], card, line, label)
            elif k == "stole":
                if e["prod"]:
                    self.call(label, line, self.eng.prod, e["from"], e["resource"], -e["n"])
                    if self.steal_credits_thief(head, e["resource"]):
                        self.call(label, line, self.eng.prod, e["player"],
                                  e["resource"], +e["n"])
                else:
                    self.call(label, line, self.eng.attack, e["from"], e["resource"],
                              e["n"], by=e["player"])
                    self.call(label, line, self.eng.res, e["player"], e["resource"], +e["n"])
                self.rep.gap("emulated", line, label,
                             f"stole {e['n']} {e['resource']}{' prod' if e['prod'] else ''} "
                             f"from {e['from']} via attack/res/prod")
            elif k == "lost" and e.get("by"):
                self.call(label, line, self.eng.attack, e["player"], e["resource"],
                          e["n"], by=e["by"])
            elif k == "lost_prod" and e.get("by"):
                self.call(label, line, self.eng.prod, e["player"], e["resource"], -e["n"])
                self.rep.gap("emulated", line, label,
                             f"{e['player']} −{e['n']} {e['resource']} prod because of "
                             f"{e['by']} via prod (decreaseAnyProduction not modelled)")
            elif k == "drew":
                if e["player"] == self.me and e.get("cards"):
                    self.call(label, line, self.eng.hand_add, list(e["cards"]))
            elif k == "bought":
                self.do_buy(e, known)
            elif k == "land_claim":
                # a reservation marker: no tile, no bonus, no card — it
                # only stops every OTHER player building on that hex
                self.call(label, line, self.eng.place, e["player"],
                          tmlib.LAND_CLAIM, e["space"])
            elif k == "sold" and head["kind"] != "used_standard":
                self.call(label, line, self.eng.res, e["player"], "mc", +e["n"])
                known[(e["player"], "res", "mc")] += e["n"]
            # gained / gained_prod / lost_prod / lost(no attacker) /
            # card_resource / copied: log-side deltas only (see reconcile)

    # db behavior key ↔ engine resource name (only MC differs)
    BEHAVIOR_RESOURCE = {"mc": "megacredits"}

    def steal_credits_thief(self, head: dict, resource: str) -> bool:
        """Does a "X stole N <res> production from Y" line ALSO give X the
        production, or only take it from Y?

        In the app a production steal is one deferred action that decreases
        the VICTIM and logs the "stole" sentence; the thief's matching step
        is separate. Some cards grant it invisibly (the deferred gain is
        logged off) — then the steal line is the only evidence and the
        thief must be credited. Others declare it in the card's own
        production box, which the app logs as its own "gained N …
        production" line AND the engine has already applied from the db —
        crediting the steal line as well counted it twice (P8: the Tharsis
        seat finished the replay 2 M€ production over the app, which is a
        whole award metric).

        So: credit the thief unless the played card's `behavior.production`
        already grants that resource. Read from the db, never per card.
        """
        if head.get("kind") != "played":
            return True
        info = self.eng.card(head.get("card") or "")
        prod = ((info or {}).get("behavior") or {}).get("production") or {}
        if not isinstance(prod, dict):
            return True
        key = self.BEHAVIOR_RESOURCE.get(resource, resource)
        return not prod.get(key)

    def ocean_area_card(self, player: str, tile: str, space: str) -> str | None:
        """The tableau card that makes an ocean-reserved hex legal for a
        plain greenery, when the `placed` line has no card in scope.

        listen.py polls about once a second, so the lines of ONE app action
        routinely split across drains: the head ("Ben played Protected
        Valley") is applied in drain N and the consequence ("Ben placed
        greenery tile at 33") arrives in drain N+1 as a `late_tail` head,
        whose block carries no card. place() was then called without
        card=, the engine refused the ocean-reserved hex, and every later
        greenery adjacent to that tile failed the adjacency rule as well —
        six of Ben's tiles never reached the tracker (p8 #13).

        Only a card whose db behavior actually grants the placement
        ("ON AN AREA RESERVED FOR OCEAN": behavior.greenery.on == "ocean")
        is used, so an unrelated play never buys an exemption. Special
        tiles need no fallback: their card is named in the log line itself.
        """
        if tile != "greenery":
            return None
        try:
            sp = Engine._board().get(grid_to_space(space))
        except (EventError, TypeError, ValueError):
            return None
        if not sp or not sp.get("oceanReserved"):
            return None
        try:
            played = self.pool(self.game(), player).get("playedCards") or []
        except KeyError:
            return None
        for entry in reversed(played):
            beh = (self.eng.card(entry.get("name")) or {}).get("behavior") or {}
            grant = beh.get("greenery")
            if isinstance(grant, dict) and grant.get("on") == "ocean":
                return entry.get("name")
        return None

    def place(self, player: str, tile: str, space: str, card: str | None,
              line: int, label: str) -> None:
        kw = {}
        if tile in ("ocean", "city", "greenery"):
            if not card:
                card = self.ocean_area_card(player, tile, space)
                if card:
                    self.rep.note(line, label,
                                  f"{tile} on ocean-reserved {space} attributed to "
                                  f"{card} (its 'played' line was drained earlier)")
            if card:
                kw["card"] = card
        else:                                   # "<Card Name> tile"
            card = tile
            info = self.eng.card(card)
            beh = (info or {}).get("behavior") or {}
            ttype = (beh.get("tile") or {}).get("type") if isinstance(beh.get("tile"), dict) else None
            if not ttype:
                ttype = "".join(ch for ch in card.lower() if ch.isalnum())
                self.rep.gap("db-tile", line, card,
                             f"db has no behavior.tile for this special tile — "
                             f"type {ttype!r} inferred from the card name")
            tile = ttype
            kw["card"] = card
        msg = self.call(label, line, self.eng.place, player, tile, space, **kw)
        if msg is None and tile == "greenery":
            self.rep.gap("placement", line, label,
                         f"greenery on {space} refused by the engine's adjacency rule")

    TILE_KEY = {"city": "cities", "greenery": "greeneries"}

    def tile_counters(self, head: dict, tail: list, before: dict) -> None:
        """Reconcile the owner's tile counters against `game["board"]`.

        The board is the authoritative record in API replay: the app emits a
        `placed <tile> at <hex>` line for every tile, so every tile a player
        owns has a recorded position. The counters are derived, and before
        P7 they were reconciled against a per-BLOCK delta instead — which
        double-counted whenever the counter bump (the card play or the
        standard project) and the `placed` line arrived in DIFFERENT drains:
        the later block saw no movement and force-added the tile again.

        Observed in the first full-autopilot game: two opponents each showed 3
        cities against a board holding 2, which inverted the Landlord race,
        fired a false Mayor alert, and corrupted Greenhouses' per-city
        arithmetic. Counting from the board cannot drift either way.
        """
        placed = {e["player"] for e in ([*tail, head] if head["kind"] == "final_placed"
                                        else tail)
                  if e["kind"] in ("placed", "final_placed") and e.get("player")}
        if not placed:
            return
        g = self.game()
        board = g.get("board") or {}
        for player in sorted(placed):
            owned = [v["tile"] for v in board.values() if v["player"] == player]
            pool = self.pool(g, player)["tiles"]
            for tile_kind, key in (("city", "cities"), ("greenery", "greeneries")):
                truth = sum(1 for t in owned if t == tile_kind)
                if key == "cities":
                    # reserved-area cities (Ganymede Colony, Phobos Space
                    # Haven) are off-Mars and never reach the board
                    truth += pool.get("citiesOffMars", 0)
                if pool.get(key, 0) != truth:
                    was = pool.get(key, 0)
                    self.call(self.label(head), head["line"],
                              self.eng.tiles_fix, player, key, truth)
                    self.rep.gap("tile-counter", head["line"], self.label(head),
                                 f"{player} {key} counter {was} ≠ board {truth} "
                                 f"— reconciled to the board")
            # everything that is not a city, greenery or ocean is a SPECIAL
            # tile (oceans belong to no one and never score for Landlord)
            special = sum(1 for t in owned
                          if t not in ("city", "greenery", "ocean"))
            if special and pool.get("special", 0) != special:
                was = pool.get("special", 0)
                self.call(self.label(head), head["line"],
                          self.eng.tiles_fix, player, "special", special)
                self.rep.gap("tile-counter", head["line"], self.label(head),
                             f"{player} special counter {was} ≠ board {special} "
                             f"— reconciled to the board")

    def ocean_counter(self, head: dict, tail: list) -> None:
        """The oceans PARAMETER is the ocean tiles on the board — reconcile
        it after every block, the same way tile_counters reconciles the
        per-player counters.

        Some ocean placements reach the engine as a bare `place`: the
        temperature track's 0°C bonus ocean prints "log place + raise oceans
        events" and hands the raise back to the human, and a card whose db
        behavior has the tile but not the parameter does the same. In a
        replay nobody answers that prompt, so the tile landed on the board
        while the track — and the placer's TR for it — did not move.
        Observed in three practice games (oceans 8 against a board of 9,
        one player a full TR light, which also refused the Terraformer
        milestone claim that followed).
        """
        placer = None
        for e in ([head, *tail] if head["kind"] in ("placed", "final_placed")
                  else tail):
            if e["kind"] in ("placed", "final_placed") and e.get("tile") == "ocean":
                placer = e.get("player")
        if placer is None:
            return
        g = self.game()
        on_board = sum(1 for v in (g.get("board") or {}).values()
                       if v["tile"] == "ocean")
        while g["globals"]["oceans"] < on_board:
            self.call(self.label(head), head.get("line", 0),
                      self.eng.raise_param, "oceans", by=placer)
            self.rep.gap("ocean-counter", head.get("line", 0), self.label(head),
                         f"oceans track {g['globals']['oceans']} < {on_board} "
                         f"ocean tiles on the board — raised for {placer}")
            g = self.game()

    def oxygen_bonus(self, head: dict, before: dict) -> None:
        """Tharsis O2 track: reaching 8% raises temperature one step for the
        player who raised it (+1 TR).

        Engine._bump_param chains this itself now (P9 issue 5), so the
        emulation only covers a crossing the engine never saw — an oxygen
        value that arrived as an adopted/observed figure rather than as a
        raise. A temperature that already moved during this event is the
        engine having done it: emulating on top would double the step and
        push the whole temperature track a generation early."""
        if head["kind"] == "wgt":
            return
        g = self.game()
        was, now = before["globals"]["oxygen"], g["globals"]["oxygen"]
        if was < 8 <= now:
            if g["globals"]["temperature"] != before["globals"]["temperature"]:
                return                       # already chained by the engine
            actor = head.get("player")
            if g["globals"]["temperature"] < PARAM_SCALE["temperature"]["max"]:
                self.call(self.label(head), head["line"], self.eng.raise_param,
                          "temperature", by=actor)
            self.rep.gap("emulated", head["line"], self.label(head),
                         "O2 reached 8% → temperature +1 step for the raiser "
                         "(the oxygen value was adopted, not raised) — "
                         "applied via raise_param")

    # ── reconciliation ───────────────────────────────────────
    def reconcile(self, head: dict, tail: list, before: dict, known: dict) -> None:
        after = self.snapshot()
        label = self.label(head)
        line = head.get("line", 0)
        actor = head.get("player")
        logd = defaultdict(int)             # (player, kind, stat) → delta
        mentioned = set()
        sources = defaultdict(list)         # (player, kind, stat) → ["Arctic Algae +2"]
        tr_lines = defaultdict(int)
        for e in tail:
            k = e["kind"]
            if k == "gained":
                if e["resource"] == "tr":
                    tr_lines[e["player"]] += e["n"]
                    continue
                logd[(e["player"], "res", e["resource"])] += e["n"]
                mentioned.add((e["player"], "res", e["resource"]))
                if e.get("source"):
                    sources[(e["player"], "res", e["resource"])].append(
                        f"{e['source']} +{e['n']}")
            elif k == "lost":
                logd[(e["player"], "res", e["resource"])] -= e["n"]
                mentioned.add((e["player"], "res", e["resource"]))
            elif k == "gained_prod":
                logd[(e["player"], "prod", e["resource"])] += e["n"]
                mentioned.add((e["player"], "prod", e["resource"]))
            elif k == "lost_prod":
                logd[(e["player"], "prod", e["resource"])] -= e["n"]
                mentioned.add((e["player"], "prod", e["resource"]))
            elif k == "stole":
                kind = "prod" if e["prod"] else "res"
                if not e["prod"] or self.steal_credits_thief(head, e["resource"]):
                    logd[(e["player"], kind, e["resource"])] += e["n"]
                    mentioned.add((e["player"], kind, e["resource"]))
                logd[(e["from"], kind, e["resource"])] -= e["n"]
                mentioned.add((e["from"], kind, e["resource"]))
            # "sold N patents" is applied as a known res(+N) in do_standard /
            # do_tail — not a log-side delta, or it would count twice
        keys = set(logd) | set(known)
        for p in self.players:
            for kind in STAT_KINDS:
                for r in RESOURCES:
                    if before["players"][p][kind][r] != after["players"][p][kind][r]:
                        keys.add((p, kind, r))
        for key in sorted(keys):
            p, kind, r = key
            if r not in RESOURCES:
                continue
            eng = after["players"][p][kind][r] - before["players"][p][kind][r]
            exp = known.get(key, 0) + logd.get(key, 0)
            diff = exp - eng
            if diff == 0:
                continue
            if (kind == "res" and p == actor and key not in mentioned and diff > 0
                    and key not in known):
                # the engine charged a cost the app does not print (Moss's
                # plant, a db stock cost) — the engine is trusted for costs
                self.rep.note(line, label, f"{p} {r} stock: engine {eng:+} (unlogged "
                                           "cost, kept)")
                continue
            applied = self.correct(p, kind, r, diff)
            what = (f"{p} {r} {'production' if kind == 'prod' else 'stock'}: "
                    f"engine {eng:+}, log {exp:+} → corrected {applied:+}")
            if applied != diff:
                what += f" (wanted {diff:+}, floor)"
            if sources.get(key):
                what += " [log sources: " + ", ".join(sources[key]) + "]"
            self.rep.gap("mismatch", line, label, what)
        self.reconcile_card_resources(head, tail, before, after)
        # TR: engine-driven (parameter raises are never printed); an explicit
        # "gained N TR" line the engine did not produce is applied.
        for p, n in tr_lines.items():
            eng = after["players"][p]["tr"] - before["players"][p]["tr"]
            if eng < n:
                self.call(label, line, self.eng.tr, p, n - eng)
                self.rep.gap("mismatch", line, label,
                             f"{p} TR: engine {eng:+}, log +{n} → corrected {n - eng:+}")

    def reconcile_card_resources(self, head: dict, tail: list,
                                 before: dict, after: dict) -> None:
        """The app names every animal / microbe / science resource it puts on
        or takes off a card ("X added 3 Microbe(s) to Y", "X removed 3
        resource(s) from X's Y"). Those lines are as authoritative as the
        stock lines, and they were the only ones the replay dropped.

        It matters twice over: the counts are VP at scoring time, and an
        action that SPENDS them ("remove 3 microbes → +1 TR") is refused
        when the tracker thinks the card is short. In one practice game the
        card was stocked twice by OTHER cards, which the engine never sees,
        so two of those actions were refused and the player finished the
        replay 2 TR under the app.
        """
        stated: dict[tuple[str, str], int] = {}
        for e in tail:
            if e["kind"] != "card_resource":
                continue
            info = self.eng.card(e["card"])
            canon = info["name"] if info else e["card"]
            key = (e["player"], canon)
            stated[key] = stated.get(key, 0) + (e["n"] if e["verb"] == "add"
                                                else -e["n"])
        if not stated:
            return
        for (player, card), delta in sorted(stated.items()):
            if player not in self.players:
                continue
            was = before["players"][player]["cards"].get(card, 0)
            now = after["players"][player]["cards"].get(card, 0)
            want = max(0, was + delta)
            if now == want:
                continue
            self.call(self.label(head), head.get("line", 0),
                      self.eng.sync_card_resources, player, {card: want})
            self.rep.gap("mismatch", head.get("line", 0), self.label(head),
                         f"{player} {card} resources: engine {now - was:+}, "
                         f"log {delta:+} → set to {want}")

    def correct(self, player: str, kind: str, res: str, diff: int) -> int:
        fn = self.eng.res if kind == "res" else self.eng.prod
        try:
            fn(player, res, diff)
            return diff
        except EventError:
            g = self.game()
            cur = self.pool(g, player)["resources" if kind == "res" else "production"][res]
            floor = -5 if (kind == "prod" and res == "mc") else 0
            allowed = max(diff, floor - cur)
            if allowed:
                fn(player, res, allowed)
            return allowed


def replay(applog: Path, setup_path: Path, out_dir: Path,
           verbose: bool = True, pay_metals: bool = True) -> Report:
    setup = json.loads(Path(setup_path).read_text())
    players = [p["name"] for p in setup["players"]]
    store = Store(Path(out_dir))
    store.init(copy.deepcopy(setup))
    eng = Engine(store)
    rep = Report()
    text = Path(applog).read_text()
    events = P.parse_log(text, players)
    rep.lines_seen = len(text.splitlines())
    blocks = P.group_blocks(events)
    Replayer(eng, rep, verbose=verbose, pay_metals=pay_metals).run(blocks)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("applog")
    ap.add_argument("--setup", required=True)
    ap.add_argument("--out", required=True, help="fresh session dir (state/ created inside)")
    ap.add_argument("--expect", default=None, help="final-state.json to diff against")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    ap.add_argument("--no-metals", action="store_true",
                    help="do not model steel/titanium payments (the export "
                         "never prints them; default = the app's max-metal "
                         "payment default)")
    a = ap.parse_args(argv)
    try:
        rep = replay(Path(a.applog), Path(a.setup), Path(a.out),
                     verbose=not a.quiet, pay_metals=not a.no_metals)
    except FileExistsError as e:
        print(f"ERROR: {e} — give --out a fresh directory", file=sys.stderr)
        return 1
    expect = json.loads(Path(a.expect).read_text()) if a.expect else None
    print(rep.summary(expect))
    return 0


if __name__ == "__main__":
    sys.exit(main())
