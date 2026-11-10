#!/usr/bin/env python3
"""LISTEN — lane 1 of the judgment design: the mechanical online listener.

Drains the app's LOG panel into the LIVE engine (state/, the default
Store) through the replay machinery (scripts/replay_applog.py — the same
per-line apply + reconciliation the regression replay uses: explicit
"gained / lost / stole" lines are truth), appends one triage feed entry
per line to state/feed.jsonl (scripts/triage.py schema + hard-trigger
verdict) and keeps a cursor so nothing is applied twice. No model, no
strategy: the advisor reads the feed; this script only keeps it current.

    listen.py once  [--pid P]                    one drain
    listen.py wait  [--interval 1] [--idle 10] [--timeout 570]
                                                 loop `once` until it is OUR turn
    listen.py paste [--file F]                   ingest pasted LOG text (stdin)
                                                 — screenshot mode, no API
    listen.py sync-me                            adopt the whole table from /api/player
    listen.py init                               cursor = the app's current log, nothing applied
    listen.py status                             print the cursor

EXIT CODES
    once:  0 nothing new · 10 new events applied · 20 GO (our turn, nothing
           new) · 30 GO and events · 1 error (app down, config, physical mode)
    wait:  20 / 30 as above when GO arrives · 3 timeout · 1 error
    paste: 0 nothing new · 10 new events applied · 1 error (physical mode…)
    sync-me / init / status: 0 ok · 1 error

CURSOR (state/feed-cursor.json): {gameAge, undoCount, generation, lastLine,
seen: {"<gen>": lines ingested}, logMark: state/log.md line count}. Lines
are skipped by COUNT per generation (the same text may legitimately appear
twice); `lastLine` numbers the feed like the export (1-based, all lines).

PASTE (screenshot mode — the online app WITHOUT the API opt-in): the
player pastes the app's LOG panel text at arbitrary granularity
(half-turns included) and `paste` sends it through the SAME lane as a
drain: per-line replay apply, one feed entry per line, hard-trigger
verdicts, own lines reconciled against what the tracker already holds —
never applied by hand via apply.py, which double-counts every effect the
engine auto-applies. Needs NO appUrl and never touches the network.

PASTE DEDUP (state/paste-cursor.json): the app log is append-only and the
same TEXT can repeat legitimately across a game, so a content hash of a
line is the wrong key. The cursor stores the full CONSUMED-LINE LIST; a
new paste is anchored against it: a paste found verbatim anywhere in the
consumed stream is an exact repeat (nothing applied); otherwise the
LONGEST suffix of the consumed stream that is a prefix of the paste marks
where the new lines start, and only the remainder is ingested. A paste
with no overlap at all is treated as all-new with a loud note (a window
skipped between pastes cannot be detected — paste overlapping windows).
The ambiguity floor: a paste consisting ONLY of a line identical to the
consumed tail is read as overlap, not as a new event — when a real
repeat crosses the boundary, paste a longer window. Do not mix `paste`
with API drains in one game: the API cursor counts the app's own log
lines and cannot see what paste consumed.

JUDGMENT BANNER (lane 2 from inside lane 1): `wait` is a BLOCKING call
that sleeps through every opponent turn and wakes on a finished batch, so
"after each opponent's turn" never happens for the advisor. Instead the
listener surfaces the judgment lane itself: a drain that ends with
unhandled hard triggers in the feed prints a loud JUDGMENT NEEDED block
naming them and the exact commands (advise.py --sweep / triage.py handle).
Quiet rounds print nothing, the blocking wait is untouched, and triggers
that have resolved themselves are pruned so the list stays signal: turnover
triggers from PAST generations, and any entry whose every reason rests on a
dead premise — a race for a milestone already claimed, a requirement window
whose cards left my hand (triage.auto_resolve, P9 #10). The banner names
only the newest ten, so a backlog nobody can prune is a backlog nobody
reads (32 unhandled entries by generation 11 in the P9 game).

STALL DIAGNOSTIC: a `wait` TIMEOUT also names the seat the app is waiting
on (`who_blocks`) — a dead seat freezes the table and used to need a
hand investigation. Best effort: it never raises inside the wait loop.

OWN LINES: an own head that the engine already reflects (card in
playedCards / corporation, action ledger used, milestone/award ours, tile
on the hex, cards in hand, "Research:" logged since the last drain) is
noted "own action, already applied" and skipped (its hidden-info lines
still fill the hand); otherwise it is applied ("own action absorbed").

THE APP IS THE STATE OF RECORD: every drain that gets past WAIT ends with
a FULL-TABLE sync from /api/player (verify.sync_table) — my mat, hand,
tableau and card resources, every opponent's public mat, tableau,
milestones/awards and card resources, the globals and the tile positions
— and prints one `table synced: …` line. The log lines stay the EVENT
feed (triggers, threats, attribution); the numbers are the API's. The
view is re-fetched after the ingest so "Generation N" (produce) lands
first; while the app is still a generation ahead the guard refuses
resource values (post-production) and syncs the rest.

CORPORATION IDENTITY (D2, Codex H2): the table sync also reads tableau
entry zero of every player as the corporation and sets the IDENTITY only
— never the starting assets, which are already inside the adopted mat.
Before this the initial sync left `corporation` null and operators ran
`apply.py corp` (the physical-mode verb: identity + starting assets) on
top of the synced numbers, doubling them ("Ares is CrediCor (start 0 MC →
45)" then "(start 57 MC → 102)"; PhoboLog's "+10 titanium" compensated by
a "-10 TITANIUM"). A player whose identity is already known is left alone.

THE GO LINE CARRIES THE OFFER (S1): when the prompt is a card offer
(`waitingFor.type == "card"` with a `cards` list, or the `initialCards`
shape) the GO line is followed by one line per offered card — name, play
cost (the app's calculatedCost when present), tags, requirement, effect
text — from the view the listener already holds and cards/db.json. The
advisor used to spend a whole model round-trip (curl + a db lookup) to see
the four research cards. Output only; a non-card GO is unchanged.

Every drain that finds work is wrapped in latency.timed("listen").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import appapi                                   # noqa: E402
import applog_parser as P                       # noqa: E402
import latency                                  # noqa: E402
import planlib                                  # noqa: E402
import replay_applog as R                       # noqa: E402
import triage                                   # noqa: E402
import verify                                   # noqa: E402
from appapi import AppClient, AppError, AppUnavailable   # noqa: E402
from tmlib import Engine, EventError, Store, card_info   # noqa: E402

CURSOR_FILE = "feed-cursor.json"
PASTE_CURSOR_FILE = "paste-cursor.json"
APP_MODES = ("app-online", "app-practice")
ERROR_GAPS = ("unknown", "refused")
HIDDEN_KINDS = ("you_bought", "you_drew")
OWN_REFLECTED = "own action, already applied"
OWN_ABSORBED = "own action absorbed"
BANNER_MAX = 10                                   # triggers listed in full

EXIT_NOTHING, EXIT_EVENTS, EXIT_GO, EXIT_GO_EVENTS, EXIT_TIMEOUT = 0, 10, 20, 30, 3


class ListenError(Exception):
    pass


@dataclass
class DrainResult:
    result: str                  # WAIT | REFRESH | GO
    entries: list = field(default_factory=list)
    go: bool = False
    title: str = ""
    new: bool = False
    waiting: dict | None = None  # the GO prompt itself (offer_lines reads it)

    @property
    def exit_code(self) -> int:
        if self.go:
            return EXIT_GO_EVENTS if self.new else EXIT_GO
        return EXIT_EVENTS if self.new else EXIT_NOTHING


# ── cursor ───────────────────────────────────────────────────────────

def cursor_path(store: Store) -> Path:
    return store.state_dir / CURSOR_FILE


def load_cursor(store: Store) -> dict | None:
    p = cursor_path(store)
    if not p.exists():
        return None
    c = json.loads(p.read_text())
    c.setdefault("seen", {})
    c.setdefault("logMark", 0)
    return c


def save_cursor(store: Store, cursor: dict) -> None:
    Store._write_json(cursor_path(store), cursor)


def _log_len(store: Store) -> int:
    try:
        return len(store.log_path.read_text().splitlines())
    except FileNotFoundError:
        return 0


def paste_cursor_path(store: Store) -> Path:
    return store.state_dir / PASTE_CURSOR_FILE


def load_paste_cursor(store: Store) -> dict:
    p = paste_cursor_path(store)
    if not p.exists():
        return {"consumed": []}
    c = json.loads(p.read_text())
    c.setdefault("consumed", [])
    return c


def save_paste_cursor(store: Store, cursor: dict) -> None:
    Store._write_json(paste_cursor_path(store), cursor)


def paste_overlap(consumed: list[str], lines: list[str]) -> int:
    """How many leading `lines` of a paste are already consumed (see the
    module docstring's PASTE DEDUP). Returns len(lines) for a paste found
    verbatim anywhere in the consumed stream (an exact repeat of an older
    window); otherwise the length of the LONGEST suffix of `consumed`
    that is a prefix of `lines` (the overlap of a tail window); 0 when
    nothing anchors (a gap — the caller ingests everything, loudly)."""
    n, m = len(consumed), len(lines)
    if m == 0 or n == 0:
        return 0
    for i in range(n - m, -1, -1):                 # exact repeat anywhere
        if consumed[i:i + m] == lines:
            return m
    for k in range(min(n, m), 0, -1):              # longest suffix ∩ prefix
        if consumed[n - k:] == lines[:k]:
            return k
    return 0


_GEN_LINE = re.compile(r"^Generation (\d+)$")


def _title(wf) -> str:
    if not isinstance(wf, dict):
        return ""
    t = wf.get("title", "")
    if isinstance(t, dict):
        m = str(t.get("message", ""))
        for i, d in enumerate(t.get("data") or []):
            m = m.replace("${%d}" % i, str((d or {}).get("value")))
        return m
    return str(t)


_CachedClient = verify.ViewClient      # one implementation, verify.py's


# ── the listener ─────────────────────────────────────────────────────

class _LiveReplayer(R.Replayer):
    """The replayer with the SOURCE generation of the block it is applying.
    A drained blue-card action line carries the generation of the log it
    came from; `Engine.use_action(gen=…)` absorbs one older than the
    tracker's generation instead of consuming the current ledger (D3: a
    generation-7 echo drained after the turnover marked generation 8's
    slot used). Every other verb is untouched."""
    source_gen: int | None = None

    def call(self, label: str, line: int, fn, *args, **kwargs):
        if self.source_gen is not None and fn == self.eng.use_action:
            kwargs.setdefault("gen", self.source_gen)
        return super().call(label, line, fn, *args, **kwargs)


class Listener:
    def __init__(self, store: Store, client: AppClient, pid: str):
        self.store, self.client, self.pid = store, client, pid
        self.setup = store.load_setup()
        self.eng = Engine(store)
        self.rep = R.Report()
        self.replayer = _LiveReplayer(self.eng, self.rep, verbose=False)
        self.players = [p["name"] for p in self.setup["players"]]
        self.me = next(p["name"] for p in self.setup["players"] if p.get("isMe"))
        self._hidden: dict[int, dict] = {}
        self._last_actor: str | None = None

    # ── state helpers ──
    def game(self) -> dict:
        return self.store.load_game()

    def cursor(self) -> dict:
        c = load_cursor(self.store)
        if c is None:
            c = {"gameAge": 0, "undoCount": 0, "generation": self.game()["generation"],
                 "lastLine": 0, "seen": {}, "logMark": _log_len(self.store)}
        return c

    def plan(self) -> dict | None:
        try:
            return planlib.load_plan(self.store)
        except (EventError, ValueError, OSError):
            return None

    def log_since(self, mark: int) -> list[str]:
        try:
            return self.store.log_path.read_text().splitlines()[mark:]
        except FileNotFoundError:
            return []

    # ── one drain ──
    def drain(self) -> DrainResult:
        cur = self.cursor()
        wf = self.client.waiting_for(self.pid, cur["gameAge"], cur["undoCount"])
        result = str(wf.get("result", "WAIT"))
        if result == "WAIT":
            return DrainResult(result)
        with latency.timed("listen", store=self.store) as t:
            view = self.client.player(self.pid)
            g = view.get("game") or {}
            age = int(g.get("gameAge") or cur["gameAge"] or 0)
            undo = int(g.get("undoCount") or 0)
            app_gen = int(g.get("generation") or cur["generation"])
            names = appapi.color_names(view)
            if undo > cur["undoCount"]:
                msg = (f"undo detected (undoCount {cur['undoCount']} → {undo}): the app "
                       "rolled back a move; the engine is NOT reversed — check the next "
                       "lines and run listen.py sync-me / verify.py")
                print(msg)
                self.store.log(f"G{self.game()['generation']}", f"listen: {msg}")
            entries: list[dict] = []
            self._last_actor = None
            for gen in range(cur["generation"], max(cur["generation"], app_gen) + 1):
                lines = appapi.log_lines(self.client, self.pid, gen, names)
                seen = int(cur["seen"].get(str(gen), 0))
                if len(lines) < seen:
                    print(f"log of generation {gen} shrank {seen} → {len(lines)} (undo) "
                          "— cursor reset to the app's view")
                    seen = len(lines)
                new = lines[seen:]
                if new:
                    entries += self.ingest(new, gen, cur)
                cur["seen"][str(gen)] = len(lines)
                cur["generation"] = gen
            # THE APP IS THE STATE OF RECORD (P9): the log lines above are
            # the event feed (triggers, threats, attribution); the numbers
            # come from the API. The view is re-fetched AFTER the ingest —
            # "Generation N" (produce) has to land before any post-
            # production value is adopted, or the guard blocks the sync.
            print(f"table synced: {self.sync_table()}")
            go = result == "GO"
            waiting = view.get("waitingFor") if go else None
            title = _title(waiting) if go else ""
            cur["gameAge"], cur["undoCount"] = age, undo
            cur["logMark"] = _log_len(self.store)
            save_cursor(self.store, cur)          # last: a crash before here replays
            t.note = f"{len(entries)} entries" + (" GO" if go else "")
        if entries or go:
            for line in banner(triage.pending(triage.feed_path(self.store),
                                              self.game(), self.setup),
                               self.store.state_dir):
                print(line)
        return DrainResult(result, entries, go, title, bool(entries),
                           waiting if isinstance(waiting, dict) else None)


    # ── pasted LOG text (screenshot mode, no API) ──
    def paste(self, text: str) -> DrainResult:
        """Ingest pasted app-LOG text through the SAME lane as a drain —
        per-line replay apply, one feed entry per line, hard-trigger
        verdicts, own-line reconciliation — deduplicated against the
        consumed-line list (module docstring: PASTE DEDUP). No network."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            print("paste: no lines in the pasted text")
            return DrainResult("PASTE")
        pc = load_paste_cursor(self.store)
        consumed = list(pc.get("consumed") or [])
        skip = paste_overlap(consumed, lines)
        new = lines[skip:]
        if not new:
            print(f"paste: {len(lines)} line(s), all already consumed — "
                  "nothing applied")
            return DrainResult("PASTE")
        if skip == 0 and consumed:
            print("paste: no overlap with the consumed log — every line "
                  "treated as new (a window skipped between pastes cannot be "
                  "detected; paste overlapping windows)")
        entries: list[dict] = []
        with latency.timed("listen", store=self.store) as t:
            cur = self.cursor()
            gen = int(cur.get("generation") or self.game()["generation"])
            chunks: list[tuple[int, list[str]]] = []
            buf: list[str] = []
            for line in new:                # a "Generation N" line OPENS gen N
                m = _GEN_LINE.match(line)
                if m:
                    if buf:
                        chunks.append((gen, buf))
                    gen, buf = int(m.group(1)), [line]
                else:
                    buf.append(line)
            if buf:
                chunks.append((gen, buf))
            for g, chunk in chunks:
                entries += self.ingest(chunk, g, cur)
                cur["generation"] = max(int(cur["generation"]), g)
            cur["logMark"] = _log_len(self.store)
            save_cursor(self.store, cur)
            pc["consumed"] = consumed + new
            save_paste_cursor(self.store, pc)   # last: a crash before here replays
            t.note = f"paste {len(new)} lines ({skip} overlapped)"
        print(f"paste: {len(lines)} line(s) — {skip} already consumed, "
              f"{len(new)} ingested")
        if entries:
            for line in banner(triage.pending(triage.feed_path(self.store),
                                              self.game(), self.setup),
                               self.store.state_dir):
                print(line)
        return DrainResult("PASTE", entries, False, "", bool(entries))

    # ── lines → blocks → engine ──
    def ingest(self, new_lines: list[str], gen: int, cur: dict) -> list[dict]:
        events = []
        for line in new_lines:
            cur["lastLine"] += 1
            ev = P.parse_line(line, self.players)
            ev["line"] = cur["lastLine"]
            ev["raw"] = line.strip()
            events.append(ev)
        self._hidden = {ev["line"]: ev for ev in events if ev["kind"] in HIDDEN_KINDS}
        entries: list[dict] = []
        for block in self.normalize(P.group_blocks(events)):
            entries += self.apply_block(block, gen)
        return entries

    def normalize(self, blocks: list[dict]) -> list[dict]:
        """Live drains cut the export anywhere: consequence lines whose head
        was applied in an earlier drain become a `late_tail` block (tail +
        reconciliation only); an unparsed head never swallows the
        consequences that follow it."""
        out = []

        def late(evs: list[dict], entry_events=None) -> dict:
            head = {"kind": "late_tail", "player": evs[0].get("player"),
                    "line": evs[0]["line"], "raw": evs[0].get("raw", "")}
            return {"head": head, "tail": list(evs), "events": entry_events}

        for b in blocks:
            head, tail = b["head"], b["tail"]
            k = head["kind"]
            if k == "unknown" and head.get("cards"):
                # an orphaned "You drew/bought …" (its "X drew N" line was in
                # the previous drain): hand only, never a second payment
                orig = "you_bought" if "bought" in head.get("raw", "") else "you_drew"
                ev = {"kind": "drew", "player": self.me, "n": len(head["cards"]),
                      "cards": list(head["cards"]), "line": head["line"],
                      "raw": head.get("raw", "")}
                out.append(late([ev], entry_events=[dict(head, kind=orig)]))
                if tail:
                    out.append(late(tail))
            elif k == "unknown":
                out.append({"head": head, "tail": []})
                if tail:
                    out.append(late(tail))
            elif k not in P.HEAD_KINDS and k != "final_placed":
                out.append(late([head, *tail]))
            else:
                out.append(b)
        return out

    def apply_block(self, b: dict, gen: int) -> list[dict]:
        head, tail = b["head"], b["tail"]
        evs = b.get("events") or ([head] if head["kind"] != "late_tail" else []) + list(tail)
        game_before = self.game()
        note = self.reflected(b, game_before)
        errors: dict[int, str] = {}
        notes: dict[int, list[str]] = defaultdict(list)
        if note:
            for msg in self.absorb_hidden(b, game_before):
                notes[head["line"]].append(msg)
        else:
            n0 = len(self.rep.gaps)
            self.replayer.source_gen = gen        # D3: an old echo is absorbed
            try:
                self.replayer.block(b)
            except Exception as e:                       # engine bug ≠ table stop
                errors[head["line"]] = f"{type(e).__name__}: {e}"
            for gp in self.rep.gaps[n0:]:
                line = int(gp.get("line") or head["line"])
                if gp["kind"] in ERROR_GAPS:
                    what = ("unparsed: no grammar for this line" if gp["label"] == "?"
                            else gp["what"])
                    errors.setdefault(line, f"{gp['kind']}: {what}")
                else:
                    notes[line].append(f"{gp['kind']}: {gp['what']}")
            if head.get("player") == self.me and head["kind"] not in ("passed", "ended_turn"):
                note = OWN_ABSORBED
        game_after = self.game()
        setup, plan = self.setup, self.plan()
        entries = []
        for ev in self._with_hidden(evs):
            err = errors.get(ev["line"])
            entry = triage.new_entry(ev, ev["line"], gen, ev.get("raw", ""),
                                     applied=err is None, error=err)
            parts = ([note] if note else []) + notes.get(ev["line"], [])
            entry["note"] = "; ".join(parts) or None
            try:
                trig, reasons = triage.classify(entry, game_after, setup, plan,
                                                game_before=game_before)
            except Exception as e:                       # over-trigger, never hide
                trig, reasons = True, [f"triage error: {type(e).__name__}: {e}"]
            entry["trigger"], entry["reasons"] = trig, reasons
            self.append_feed(entry)
            print(render(entry))
            entries.append(entry)
        self._last_actor = head.get("player")
        return entries

    def _with_hidden(self, evs: list[dict]) -> list[dict]:
        out = []
        for ev in evs:
            out.append(ev)
            if ev["kind"] in ("drew", "bought"):
                h = self._hidden.get(ev["line"] + 1)
                if h is not None:
                    out.append(h)
        return out

    # ── own-line heuristics ──
    def reflected(self, b: dict, game: dict) -> str | None:
        """A note when the engine already holds this block's effect."""
        head, tail = b["head"], b["tail"]
        kind, actor = head["kind"], head.get("player")
        if kind == "generation":
            if head["n"] > 1 and game["generation"] >= head["n"]:
                return f"generation {head['n']} already advanced (produce.py ran)"
            return None
        if kind == "wgt":
            pending = bool(game.get("wgtBonusOceanPending"))
            if game.get("wgtDoneGen") == game["generation"] and not (
                    head.get("param") == "oceans" and pending):
                return "WGT step already logged"
            return None
        if actor != self.me:
            return None
        me = game["me"]
        if kind == "played":
            info = self.eng.card(head["card"])
            canon = info["name"] if info else head["card"]
            if info and info.get("type") == "corporation":
                return OWN_REFLECTED if me.get("corporation") == canon else None
            played = {c["name"] for c in me.get("playedCards") or []}
            return OWN_REFLECTED if canon in played else None
        if kind == "used_action":
            try:
                key = self.eng._ledger_key(game, head["card"])
            except Exception:
                key = head["card"]
            entry = (me.get("actionsThisGen") or {}).get(key)
            return OWN_REFLECTED if entry and entry.get("used") else None
        if kind == "claimed":
            return (OWN_REFLECTED
                    if (game.get("milestonesClaimed") or {}).get(head["milestone"]) == self.me
                    else None)
        if kind == "funded":
            return (OWN_REFLECTED
                    if (game.get("awardsFunded") or {}).get(head["award"]) == self.me
                    else None)
        placed = [e for e in tail if e["kind"] == "placed" and e.get("player") == self.me]
        if kind == "final_placed":
            placed = [head]
        if kind in ("used_standard", "final_placed", "late_tail") and placed:
            board = game.get("board") or {}
            if all(self._owned(board, e["space"]) for e in placed):
                return OWN_REFLECTED
            return None
        if kind == "used_standard":
            needle = f"{self.me}: standard project {head['project']}"
            conv = {"convert_heat": "heat", "convert_plants": "plants"}.get(head["project"])
            for line in self.log_since(self.cursor().get("logMark", 0)):
                if needle in line or (conv and self.me in line and "convert" in line.lower()
                                      and conv in line.lower()):
                    return OWN_REFLECTED
            return None
        if kind in ("kept", "bought"):
            cards = head.get("cards")
            if cards:
                return OWN_REFLECTED if all(c in me["hand"] for c in cards) else None
            if head.get("n", 0) == 0:
                return None
            for line in self.log_since(self.cursor().get("logMark", 0)):
                if "Research:" in line:
                    return OWN_REFLECTED
            return None
        return None

    @staticmethod
    def _owned(board: dict, space, owner=None) -> bool:
        sid = str(int(space)) if str(space).isdigit() else str(space)
        hit = board.get(sid) or board.get(str(space))
        return bool(hit) and (owner is None or hit.get("player") == owner)

    def absorb_hidden(self, b: dict, game: dict) -> list[str]:
        """Own reflected block: its 'You drew/bought …' lines are our own
        view of hidden information — land the cards the hand lacks."""
        msgs = []
        hand = list(game["me"]["hand"])
        for ev in [b["head"], *b["tail"]]:
            if ev["kind"] in ("drew", "bought") and ev.get("player") == self.me and ev.get("cards"):
                missing = [c for c in ev["cards"] if c not in hand]
                if missing:
                    self.eng.hand_add(missing)
                    hand += missing
                    msgs.append("hand +" + ", ".join(missing))
        return msgs

    # ── feed ──
    def append_feed(self, entry: dict) -> None:
        p = triage.feed_path(self.store)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── own-state sync ──
    def sync_me(self, view: dict | None = None) -> str:
        """Reconcile OUR resources / production / TR / hand (and the public
        globals) with /api/player: verify.diff + the `apply.py sync me`
        engine calls. Returns the drift summary ("no drift" when exact).

        My mat only — `sync_table` is the whole table and is what every
        drain ends with; this stays the narrow own-panel path."""
        view = view or self.client.player(self.pid)
        app = verify._fetch_app(_CachedClient(view), self.pid)
        parts: list[str] = []
        for row in verify.diff(self.eng, [self.me], lambda _n: app):
            if not row["drift"]:
                continue
            if row["player"] == "globals":
                for param, (cur, live) in row["drift"].items():
                    self.eng.sync_global(param, live, force=True)
                    parts.append(f"{param} {cur}→{live}")
                continue
            kw = {}
            for fld, (tracked, live) in row["drift"].items():
                if fld == "tr":
                    kw["tr"] = live
                elif fld.startswith("prod."):
                    kw["prod_" + fld[5:]] = live
                elif fld in verify.FIELDS:
                    kw[fld] = live
                else:
                    continue
                parts.append(f"{fld} {tracked}→{live}")
            if kw:
                self.eng.sync_own(**kw)
        parts += verify.sync_own_hand(self.eng, app.get("hand"))
        if parts:
            self.store.log(f"G{self.game()['generation']}",
                           "listen sync-me: " + ", ".join(parts))
        return ", ".join(parts) if parts else "no drift"

    def sync_table(self, view: dict | None = None) -> str:
        """FULL-TABLE adoption from the API (verify.sync_table): my mat,
        hand, tableau and card resources, every opponent's PUBLIC mat,
        tableau, milestones/awards and card resources, the globals and the
        tile positions.

        The app is the rules engine in app modes: the LOG lines are the
        event feed (triggers, threats, attribution) but the numbers are
        the API's. Before this, opponents drifted all game between the
        occasional `verify.py --sync` — every card effect the replayer
        cannot model left the tracker a little further from the truth.
        """
        view = view or self.client.player(self.pid)
        table = verify.from_view(view)
        names = [n for n in self.players if n in table]
        if not names:
            return "no player mats in the app view"
        parts = verify.sync_table(self.eng, names, lambda n: table[n])
        parts += self.adopt_corporations(view)
        return ", ".join(parts) if parts else "exact"

    def adopt_corporations(self, view: dict) -> list[str]:
        """Corporation IDENTITY from tableau entry zero, for me and every
        opponent whose identity is still null. Identity ONLY: the starting
        MC / stock / production are already inside the mat the numeric
        adoption just took, so `Engine.corp` (identity + assets, the
        physical-table verb) is exactly the wrong call here — it doubled
        every starting asset in the Codex game (H2).

        Slot zero is the corporation in the app's tableau model (verify's
        `_fetch_app` drops it for the same reason). Only a name cards/db.json
        knows as a corporation is an identity: a project card or a
        placeholder there is a stub view and is skipped (the db is built
        from the vendor source, so a real corporation is always known)."""
        slots: dict[str, object] = {}
        for p in view.get("players") or []:
            tab = p.get("tableau")
            if p.get("name") and isinstance(tab, list) and tab:
                slots[p["name"]] = tab[0]
        tp = view.get("thisPlayer") or {}
        tab = tp.get("tableau")
        if tp.get("name") and isinstance(tab, list) and tab:
            slots.setdefault(tp["name"], tab[0])
        parts: list[str] = []
        for name in self.players:
            slot = slots.get(name)
            raw = slot.get("name") if isinstance(slot, dict) else slot
            if not raw:
                continue
            info = self.eng.card(str(raw))
            if not info or info.get("type") != "corporation":
                continue
            corp = info["name"]
            game = self.game()
            pool = game["me"] if self.eng._is_me(name) else (game.get("opponents") or {}).get(name)
            if pool is None or pool.get("corporation"):
                continue
            pool["corporation"] = corp
            self.eng._commit(game, f"{name} is {corp} — identity adopted from the app "
                                   "tableau (starting assets already in the synced mat)")
            parts.append(f"{name} corporation {corp}")
        return parts

    # ── stall diagnostic ──
    def who_blocks(self) -> str:
        """WHO the table is waiting on, for a `wait` TIMEOUT. Five seat
        terminations in one game each froze the table until the
        orchestrator hand-diagnosed the blocking seat (p7 brief §8); the
        app already knows. Two cheap reads, and it NEVER raises — a
        diagnostic must not break the wait loop."""
        try:
            cur = self.cursor()
            wf = self.client.waiting_for(self.pid, cur["gameAge"], cur["undoCount"])
            view = self.client.player(self.pid)
            names = appapi.color_names(view)
            g = view.get("game") or {}
            who = [str(names.get(c, c)) for c in (wf.get("waitingFor") or [])]
            if not who:                      # no colors: fall back to isActive
                who = [str(p.get("name")) for p in (view.get("players") or [])
                       if p.get("isActive") and p.get("name")]
            passed = [str(names.get(c, c)) for c in (g.get("passedPlayers") or [])]
            tail = f"; passed this generation: {', '.join(passed)}" if passed else ""
            if not who:
                return (f"nobody — the app names no seat (phase "
                        f"{g.get('phase', '?')}, generation "
                        f"{g.get('generation', '?')}, gameAge {g.get('gameAge', '?')})"
                        + tail)
            return (", ".join(who) + " — the app is waiting on that seat" + tail
                    + "; if its agent has stopped, restart it (the table is "
                      "frozen until it moves)")
        except Exception as e:               # never break the loop over a hint
            return f"unknown — the app could not be read ({type(e).__name__}: {e})"

    # ── cursor from the live app, nothing applied ──
    def init(self) -> dict:
        view = self.client.player(self.pid)
        g = view.get("game") or {}
        app_gen = int(g.get("generation") or self.game()["generation"])
        names = appapi.color_names(view)
        seen, total = {}, 0
        for gen in range(1, app_gen + 1):
            n = len(appapi.log_lines(self.client, self.pid, gen, names))
            seen[str(gen)] = n
            total += n
        cur = {"gameAge": int(g.get("gameAge") or 0), "undoCount": int(g.get("undoCount") or 0),
               "generation": app_gen, "lastLine": total, "seen": seen,
               "logMark": _log_len(self.store)}
        save_cursor(self.store, cur)
        return cur


def banner(pend: list[dict], state_dir: Path | None = None) -> list[str]:
    """The JUDGMENT block a drain ends with when the feed carries unhandled
    hard triggers. The blocking wait is asleep through the opponents'
    turns, so this is the ONE moment lane 2 can be entered — name the
    triggers and the exact commands, or the loop shortcuts straight to
    execute (p7 brief §7.3: the sweep fired once in twelve generations)."""
    if not pend:
        return []
    rule = "─" * 64
    shown = pend[:BANNER_MAX]
    state = ""
    if state_dir is not None and Path(state_dir).name != "state":
        state = f" --state {state_dir}"
    out = [rule,
           f"⚠ JUDGMENT NEEDED — {len(pend)} unhandled trigger(s) in the feed:"]
    out += ["  " + row for row in triage.render_pending(shown)]
    if len(pend) > len(shown):
        out.append(f"  … {len(pend) - len(shown)} more "
                   f"(python3 scripts/triage.py{state} pending)")
    out += ["  → sweep:   python3 scripts/advise.py --sweep",
            f"  → dismiss: python3 scripts/triage.py{state} handle "
            + " ".join(str(e["line"]) for e in shown)
            + ' --note "why the plan still stands"',
            rule]
    return out


def describe_offer(card) -> str:
    """One line for an offered card: name — cost · tags · requirement ·
    effect. The app's calculatedCost (discounts applied) is the price;
    the printed cost stays visible when it differs. Data only — the db
    entry is read, never a card name."""
    name = card.get("name") if isinstance(card, dict) else str(card)
    app_cost = card.get("calculatedCost") if isinstance(card, dict) else None
    info = card_info(str(name or "")) or {}
    printed = info.get("cost")
    if isinstance(app_cost, int):
        cost = f"{app_cost} MC"
        if isinstance(printed, int) and printed != app_cost:
            cost += f" (printed {printed})"
    elif isinstance(printed, int):
        cost = f"{printed} MC"
    else:
        cost = "cost ?"
    bits = [cost]
    if info.get("tags"):
        bits.append(", ".join(info["tags"]))
    if info.get("requirements"):
        bits.append(f"requires {info['requirements']}")
    effect = " ".join(str(info.get("effects") or "").split())
    if effect:
        bits.append(effect)
    if not info:
        bits.append("not in cards/db.json")
    if isinstance(card, dict) and card.get("isDisabled"):
        bits.append("DISABLED by the app")
    return f"{info.get('name') or name} — " + " · ".join(bits)


def offer_lines(wf) -> list[str]:
    """The card lines under a GO when the prompt is a card offer: a
    `card` prompt with a `cards` list (research buys, a card pick), or the
    `initialCards` shape (corporations + the first hand, one group each).
    Anything else — an `or` action menu, a bare title — renders nothing."""
    if not isinstance(wf, dict):
        return []
    groups: list[tuple[str, list]] = []
    kind = wf.get("type")
    if kind == "card" and isinstance(wf.get("cards"), list) and wf["cards"]:
        groups.append(("", wf["cards"]))
    elif kind == "initialCards":
        for opt in wf.get("options") or []:
            if (isinstance(opt, dict) and opt.get("type") == "card"
                    and isinstance(opt.get("cards"), list) and opt["cards"]):
                groups.append((_title(opt), opt["cards"]))
    out: list[str] = []
    for title, cards in groups:
        if title.strip():
            out.append(f"  {title.strip()}:")
        out += ["  • " + describe_offer(c) for c in cards]
    return out


def go_lines(r: DrainResult) -> list[str]:
    return [f"GO — {r.title}", *offer_lines(r.waiting)]


def render(entry: dict) -> str:
    status = "applied" if entry["applied"] else f"GAP: {entry['error']}"
    if entry["applied"] and entry.get("note") and (
            entry["note"].startswith("own action") or "already" in entry["note"]):
        status += f" ({entry['note'].split(';')[0]})"
    line = f"logged: {entry['raw']} {status}"
    if entry.get("trigger"):
        line += " TRIGGER: " + "; ".join(entry.get("reasons") or [])
    return line


# ── wait loop ────────────────────────────────────────────────────────

def wait(listener: Listener, interval: float = 1.0, idle: float = 10.0,
         timeout: float = 570.0, sleep=None, clock=None) -> tuple[int, str]:
    """Drain until it is OUR turn. Polls every `interval` while the game
    age moves, backs off geometrically to `idle` while nothing happens.
    Returns (exit code, waitingFor title): 20 GO, 30 GO after events,
    3 timeout."""
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    start = clock()
    idle_polls, any_new = 0, False
    while True:
        r = listener.drain()
        any_new = any_new or r.new
        if r.go:
            print("\n".join(go_lines(r)))
            return (EXIT_GO_EVENTS if any_new else EXIT_GO), r.title
        if r.new:
            idle_polls = 0
        if clock() - start >= timeout:
            print("TIMEOUT — not our turn yet; nothing wrong, re-run listen.py wait")
            print(f"WAITING ON: {listener.who_blocks()}")
            return EXIT_TIMEOUT, ""
        if r.new:
            delay = interval
        else:
            delay = min(idle, interval * (2 ** idle_polls))
            idle_polls += 1
        sleep(delay)


# ── construction / CLI ───────────────────────────────────────────────

def build(store: Store, pid: str | None = None, url: str | None = None,
          **client_kw) -> Listener:
    try:
        setup = store.load_setup()
    except FileNotFoundError:
        raise ListenError(f"no game active ({store.setup_path} missing)")
    mode = setup.get("gameMode", "physical")
    if mode not in APP_MODES:
        raise ListenError(f"listen needs an app mode (gameMode app-online|app-practice), "
                          f"got {mode!r} — the API is forbidden at the physical table")
    if not pid:
        me = next((p for p in setup["players"] if p.get("isMe")), None)
        pid = (me or {}).get("playerId")
        if not pid:
            raise ListenError("no playerId for the isMe player in setup.json "
                              "(scripts/session.py link-player) — or pass --pid")
    client = AppClient(url, **client_kw) if url else AppClient.from_setup(setup, **client_kw)
    return Listener(store, client, pid)


def build_offline(store: Store) -> Listener:
    """A listener for `paste` — needs an app mode but NO appUrl and NO
    playerId (screenshot mode: the pasted LOG panel is the only channel)."""
    try:
        setup = store.load_setup()
    except FileNotFoundError:
        raise ListenError(f"no game active ({store.setup_path} missing)")
    mode = setup.get("gameMode", "physical")
    if mode not in APP_MODES:
        raise ListenError(
            f"paste needs an app mode (the pasted LOG panel is the app's), "
            f"got {mode!r} — at a physical table events go through apply.py "
            "(skills/event-logging)")
    return Listener(store, None, "")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=".", help="repo root (state/ = active game)")
    p.add_argument("--state", default=None,
                   help="a game folder (games/<date>-gameN) instead of state/")
    p.add_argument("--pid", default=None, help="our app player id (default: setup.json)")
    p.add_argument("--url", default=None, help="app base URL (default: setup.json appUrl)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once", help="one drain; exit 0 nothing / 10 events / 20 GO / 30 GO+events")
    w = sub.add_parser("wait", help="loop once until GO; exit 20/30, timeout 3")
    w.add_argument("--interval", type=float, default=1.0, help="poll seconds while active")
    w.add_argument("--idle", type=float, default=10.0, help="poll seconds when idle")
    w.add_argument("--timeout", type=float, default=570.0,
                   help="seconds before a clean exit 3 (under the tool's 600 s cap)")
    pp = sub.add_parser("paste", help="ingest pasted app-LOG text (stdin by "
                                      "default) through the same lane as "
                                      "once; overlap-safe — re-pasting a "
                                      "window applies nothing twice; exit 0 "
                                      "nothing new / 10 events")
    pp.add_argument("--file", default=None,
                    help="read the pasted text from a file instead of stdin")
    sub.add_parser("sync-me", help="reconcile OUR mat/hand/TR with /api/player")
    sub.add_parser("init", help="cursor = the app's current log; nothing applied")
    sub.add_parser("status", help="print the cursor")
    a = p.parse_args(argv)
    store = Store(a.root, state_dir=a.state)
    try:
        if a.cmd == "status":
            cur = load_cursor(store)
            if cur is None:
                print("no cursor yet (listen.py once|init)")
            else:
                print(f"cursor: generation {cur['generation']}, lastLine {cur['lastLine']}, "
                      f"gameAge {cur['gameAge']}, undoCount {cur['undoCount']}, "
                      f"seen {cur['seen']}")
            return 0
        if a.cmd == "paste":
            listener = build_offline(store)
            text = Path(a.file).read_text() if a.file else sys.stdin.read()
            return listener.paste(text).exit_code
        listener = build(store, pid=a.pid, url=a.url)
        if a.cmd == "once":
            r = listener.drain()
            if r.go:
                print("\n".join(go_lines(r)))
            elif not r.new:
                print("nothing new")
            return r.exit_code
        if a.cmd == "wait":
            code, _title = wait(listener, interval=a.interval, idle=a.idle,
                                timeout=a.timeout)
            return code
        if a.cmd == "sync-me":
            print(f"table synced: {listener.sync_table()}")
            return 0
        if a.cmd == "init":
            cur = listener.init()
            print(f"cursor initialised from the app: generation {cur['generation']}, "
                  f"{cur['lastLine']} lines marked seen, nothing applied")
            return 0
        return 1
    except (ListenError, EventError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except (AppError, AppUnavailable) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
