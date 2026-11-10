#!/usr/bin/env python3
"""ONE client for the open-source terraforming-mars app's HTTP API.

Every script that talks to the app (sparring, verify, gamecheck,
turnwatch, advise, planlib, score) imports this — one code path, one
place for timeouts, retries and error shapes. Pure stdlib (urllib).

Endpoints (verified in vendor/terraforming-mars/src/server/routes/):
  GET  /api/waitingfor?id=<pid>&gameAge=<n>&undoCount=<n>
       → {"result": "GO"|"WAIT"|"REFRESH", "waitingFor": [colors]}
  GET  /api/game/logs?id=<pid>[&generation=<n>]
       → JSON list of LogMessage {message, data[], type?, playerId?, timestamp}
       (no generation = the last 50 entries visible to <pid>)
  GET  /api/game/logs?id=<pid>&full → text/plain export (phase == end only)
  GET  /api/player?id=<pid> → the player's own view
  POST /player/input?id=<pid>  body = the input response

Prompt responses are composed here as well — the wire shapes (option /
or_choice / cards / space / target_player) and `or_branch_response`, THE
composer that builds an `or` prompt's inner response from the selected
branch's own type. execute.py (advisor) and sparring.py (seats) both import
it; there is no second implementation (D1).

CLI (debug aid):
    python3 scripts/appapi.py waitingfor <pid> [--url U]
    python3 scripts/appapi.py logs <pid> [--generation N] [--full] [--json]
    python3 scripts/appapi.py player <pid>
    python3 scripts/appapi.py send <pid> '<raw json>'
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import http.client
import io
import socket
import urllib.error
import urllib.parse
import urllib.request
from enum import IntEnum

DEFAULT_URL = "http://localhost:8080"
ENV_VAR = "PHOBOS_APP_URL"


# ── errors ───────────────────────────────────────────────────

class AppError(urllib.error.HTTPError):
    """A non-2xx response. Subclasses HTTPError so callers that still
    catch urllib.error.URLError/HTTPError keep working."""

    def __init__(self, status: int, body: str, url: str = ""):
        super().__init__(url, status, body, {}, io.BytesIO(body.encode()))
        self.body = body          # .status/.code = HTTP status (HTTPError)

    def __str__(self) -> str:
        return f"HTTP {self.status} {self.body[:200]}"


class AppUnavailable(urllib.error.URLError):
    """Connection refused / timeout / reset after every retry."""

    def __init__(self, reason, url: str = ""):
        super().__init__(reason)
        self.url = url

    def __str__(self) -> str:
        return f"app unreachable at {self.url}: {self.reason}"


# ── URL resolution ───────────────────────────────────────────

def configured_url(setup: dict | None) -> str | None:
    """setup.json appUrl, else $PHOBOS_APP_URL, else None (NO default —
    callers that must not touch the network without explicit config
    check for None)."""
    url = (setup or {}).get("appUrl") or os.environ.get(ENV_VAR)
    return str(url).rstrip("/") if url else None


# The stdlib urlopen as imported. Connection reuse is skipped whenever this
# is no longer the function urllib exposes — i.e. a test has patched it — so
# a mock can never be silently bypassed by the keep-alive path.
_STDLIB_URLOPEN = urllib.request.urlopen


# ── client ───────────────────────────────────────────────────

class AppClient:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 10,
                 retries: int = 3, backoff: float = 0.5, sleep=None):
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.backoff = backoff
        self._sleep = sleep or time.sleep
        self._dial: str | None | bool = False   # False = not looked up yet
        self._conn: http.client.HTTPConnection | None = None
        self._conn_key: tuple | None = None

    @classmethod
    def from_setup(cls, setup: dict | None, **kw) -> "AppClient":
        return cls(configured_url(setup) or DEFAULT_URL, **kw)

    def __repr__(self) -> str:
        return f"AppClient({self.base_url!r})"

    # ── transport ──
    def _url(self, path: str, query: dict | None = None,
             flag: str | None = None) -> str:
        q = urllib.parse.urlencode({k: v for k, v in (query or {}).items()
                                    if v is not None})
        if flag:
            q = f"{q}&{flag}" if q else flag
        return f"{self.base_url}{path}" + (f"?{q}" if q else "")

    # ── connection reuse ──
    def _keepalive_on(self) -> bool:
        """Reuse connections unless a test has patched urlopen or the
        player has set PHOBOS_NO_KEEPALIVE=1."""
        return (urllib.request.urlopen is _STDLIB_URLOPEN
                and not os.environ.get("PHOBOS_NO_KEEPALIVE"))

    def _close_conn(self) -> None:
        conn, self._conn, self._conn_key = self._conn, None, None
        if conn is not None:
            try:
                conn.close()
            except Exception:                     # already dead: nothing owed
                pass

    def _ka_fetch(self, url: str, data: bytes | None) -> bytes:
        """One request on a KEPT-ALIVE connection — a drop-in for urlopen.

        Raises exactly what urlopen raises (HTTPError for >=400 with a
        readable fp, OSError for anything at the connection level) so the
        caller's error handling is untouched.

        Over the internet a fresh connection costs a TCP handshake plus a
        TLS handshake before every request: measured 480 ms against 110 ms
        reused on the public host, ~370 ms x ~1800 requests a game.
        """
        parts = urllib.parse.urlsplit(url)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        headers = {"Connection": "keep-alive"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        key = (parts.scheme, parts.hostname, parts.port)
        for attempt in (1, 2):        # the server may have closed an idle one
            if self._conn is None or self._conn_key != key:
                self._close_conn()
                cls = (http.client.HTTPSConnection if parts.scheme == "https"
                       else http.client.HTTPConnection)
                self._conn = cls(parts.hostname, parts.port,
                                 timeout=self.timeout)
                self._conn_key = key
            try:
                self._conn.request("POST" if data is not None else "GET",
                                   target, body=data, headers=headers)
                resp = self._conn.getresponse()
                body = resp.read()
            except (http.client.HTTPException, OSError):
                self._close_conn()
                if attempt == 2:
                    raise
                continue              # re-establish once, then give up
            if resp.status >= 400:
                if resp.status >= 500:
                    self._close_conn()
                raise urllib.error.HTTPError(
                    url, resp.status, resp.reason, resp.headers,
                    io.BytesIO(body))
            return body
        raise AppUnavailable("keep-alive exhausted", url)   # unreachable

    def dial_url(self, url: str) -> str:
        """`url` with an mDNS `.local` host swapped for its IPv4 literal.

        A `.local` name costs ~214 ms of TCP connect per request against
        ~5 ms for the literal (measured on the game LAN; DNS lookup is
        5 ms either way, so the cost is dual-stack connect fallback, not
        resolution). The harness opens a fresh connection per request, so
        the toll is paid thousands of times a game — 498 s of harness
        time in one recorded game against 40 s for the same harness
        reaching the same host by IP.

        Resolved ONCE and cached. Anything that is not a `.local` name is
        returned untouched, and a name that will not resolve falls back
        to itself so a DHCP change can never harden into a dead address.
        """
        host = urllib.parse.urlsplit(self.base_url).hostname or ""
        if not host.lower().endswith(".local"):
            return url
        if self._dial is False:
            try:
                self._dial = socket.gethostbyname(host)
            except OSError:
                self._dial = None
        if not self._dial:
            return url
        return url.replace(host, self._dial, 1)

    def redial(self) -> None:
        """Forget a cached literal so the next request re-resolves the
        name — the DHCP escape hatch when a cached address stops answering."""
        self._dial = False

    def _request(self, url: str, data: bytes | None = None) -> bytes:
        """GET (data None) or POST JSON. 5xx and connection errors are
        retried `retries` times with linear backoff; 4xx raise at once."""
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            if attempt > 1:
                self._sleep(self.backoff * (attempt - 1))
            try:
                dialled = self.dial_url(url)
                if self._keepalive_on():
                    return self._ka_fetch(dialled, data)
                if data is None:
                    # plain string first arg: mocks that inspect the URL
                    # (tests) and the fakes in older tests keep working
                    resp = urllib.request.urlopen(dialled, timeout=self.timeout)
                else:
                    req = urllib.request.Request(
                        dialled, data=data,
                        headers={"Content-Type": "application/json"})
                    resp = urllib.request.urlopen(req, timeout=self.timeout)
                with resp as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace") if e.fp else str(e.reason)
                err = AppError(e.code, body, url)
                if e.code < 500:
                    raise err from None
                last = err
            except OSError as e:          # URLError, timeouts, refused
                # a cached IPv4 literal that stopped answering (DHCP moved
                # the host) must not harden: re-resolve on the next attempt
                self._close_conn()
                self.redial()
                last = AppUnavailable(getattr(e, "reason", e), url)
        assert last is not None
        raise last

    def _get_json(self, url: str):
        return json.loads(self._request(url))

    # ── endpoints ──
    def waiting_for(self, pid: str, game_age: int = 0,
                    undo_count: int = 0) -> dict:
        return self._get_json(self._url("/api/waitingfor", {
            "id": pid, "gameAge": game_age, "undoCount": undo_count}))

    def game_logs(self, pid: str, generation: int | None = None,
                  full: bool = False):
        """JSON list of LogMessage entries (see render_log_entry), or the
        plain-text export when full=True (the app serves it only once
        game.phase == 'end'; otherwise HTTP 400)."""
        if full:
            return self._request(self._url("/api/game/logs", {"id": pid},
                                           flag="full")).decode()
        return self._get_json(self._url("/api/game/logs", {
            "id": pid, "generation": generation}))

    def player(self, pid: str) -> dict:
        return self._get_json(self._url("/api/player", {"id": pid}))

    def send(self, pid: str, response: dict) -> dict:
        return json.loads(self._request(self._url("/player/input", {"id": pid}),
                                        data=json.dumps(response).encode()))


# ── prompt responses: the wire shapes and THE composer ───────
#
# One place builds what POST /player/input accepts. Both callers — the
# advisor's executor (scripts/execute.py) and the seat driver
# (scripts/sparring.py) — import from here; neither keeps a second
# implementation (D1 invariant: one composer, two callers).

class Ask(Exception):
    """The prompt does not match / needs an argument the caller did not
    give. The executor maps it to exit 40; the seat driver prints it.
    `wf` = the prompt in question; `sent` = an input already went out."""

    def __init__(self, msg: str, wf=None, sent: bool = False):
        super().__init__(msg)
        self.wf = wf
        self.sent = sent


def option() -> dict:
    return {"type": "option"}


def or_choice(index: int, response: dict) -> dict:
    return {"type": "or", "index": index, "response": response}


def cards(names: list[str]) -> dict:
    return {"type": "card", "cards": list(names)}


def target_player(color: str) -> dict:
    return {"type": "player", "player": color}


def amount_response(n: int) -> dict:
    return {"type": "amount", "amount": int(n)}


def space(space_id: str) -> dict:
    """The ONLY valid shape for a standalone board-space prompt. Accepts a
    grid ref ("C4") or an internal hex id ("17").

    P7 S1: a seat with no verb for this prompt hand-wrote raw JSON, tried
    {"space": …} and nested or-forms for 79 tool calls, and forfeited two
    generations. The key is `spaceId` — nothing else is accepted.
    """
    return {"type": "space", "spaceId": space_ref(space_id)}


def space_ref(space_id) -> str:
    """"C4" → "17"; unknown refs pass through (the app rules on them)."""
    try:
        from tmlib import grid_to_space          # lazy: appapi stays light
        return str(grid_to_space(str(space_id)))
    except Exception:
        return str(space_id)


# the composer's `cards=` / `space=` ARGUMENTS shadow the builders above
_space_response, _cards_response = space, cards


def prompt_title(prompt: dict) -> str:
    """A prompt's / option's title as the app renders it (templated titles
    are {message, data} — the ${n} slots are filled)."""
    t = (prompt or {}).get("title", "")
    if isinstance(t, dict):
        m = t.get("message", "")
        for i, d in enumerate(t.get("data", [])):
            m = m.replace("${%d}" % i, str(d.get("value")))
        return m
    return str(t)


def offered_names(prompt: dict) -> list[str]:
    """The card names a `card` prompt / branch offers."""
    return [c.get("name") if isinstance(c, dict) else str(c)
            for c in (prompt or {}).get("cards") or []]


def player_color(store, ref, players: list[dict] | None = None) -> str:
    """A player NAME (or alias) → the COLOR the app identifies them by.

    P8 #15: a step's {"target": "Ben"} went out as
    {"type":"player","player":"Ben"} and the app answered HTTP 400 "Player
    not available" (Heat Trappers G9, Power Supply Consortium G11). The
    lookup takes the caller's /api/player rows (players[].name/color) when
    given, else the store's setup.json (name, color, aliases). A colour
    given directly, or a reference nobody knows, passes through unchanged
    — the app rules on it.
    """
    ref = str(ref)
    want = ref.strip().lower()
    rows = list(players or [])
    if store is not None:
        try:
            rows += (store.load_setup() or {}).get("players") or []
        except Exception:                        # never block the table
            pass
    for p in rows:
        names = [p.get("name"), p.get("color"), *(p.get("aliases") or [])]
        if want in [str(n).strip().lower() for n in names if n]:
            return str(p.get("color") or ref)
    return ref


def match_branch(titles: list[str], selector) -> int:
    """THE or-branch matcher, shared by every layer that resolves a branch
    selector: `selector` (case-insensitive) must be a substring of exactly
    one of `titles`; its index is returned.

    Titles in, index out — the helper knows nothing about cards, prompts or
    the app, so the caller supplies whatever branch labels ITS layer holds:
    the LIVE prompt's options here in appapi, the card's own branch labels
    in tmlib's simulator. That is the point: an integer means different
    branches in the two orderings (the app hides branches the player cannot
    execute, and a card's printed text may order them differently again),
    while a title means the same branch everywhere — ONE grammar.

    Zero or more than one match raises ValueError naming the candidates;
    each layer wraps that in its own error type (Ask / EventError) so
    nothing is transmitted or applied.
    """
    want = str(selector).strip().lower()
    labels = [str(t) for t in titles]
    hits = [i for i, t in enumerate(labels) if want in t.lower()]
    if not hits:
        listed = ", ".join(f"[{i}] {t}" for i, t in enumerate(labels))
        raise ValueError(f"{selector!r} matches no branch title — "
                         f"options: {listed}")
    if len(hits) > 1:
        listed = ", ".join(f"[{i}] {labels[i]}" for i in hits)
        raise ValueError(f"{selector!r} is ambiguous — matches: {listed}")
    return hits[0]


def _match_branch_by_title(options: list[dict], substr: str, wf: dict) -> int:
    """`match_branch` against a LIVE prompt's options, in Ask terms. Codex
    H4a: the app HIDES branches the player cannot execute, so the visible
    index need not match the card data's own branch order — a title is
    stable where an index is not. Zero or more-than-one match raises Ask
    naming the candidates, before anything is sent."""
    try:
        return match_branch([prompt_title(o) for o in options], substr)
    except ValueError as e:
        raise Ask(f"--choice {e} (prompt '{prompt_title(wf)}')", wf) from None


def or_branch_response(wf: dict, choice, store=None, cards=None, space=None,
                       target=None, amount=None,
                       players: list[dict] | None = None,
                       expect: str | None = None) -> tuple[dict, str | None]:
    """The or-wrapped response selecting branch `choice` of an `or` prompt,
    with the INNER response built from THAT BRANCH'S OWN TYPE. Returns
    (response, the name of the argument it consumed).

    P9 #1 / Codex H3a: every caller used to emit `{"type": "option"}`
    whatever the branch was. Generation 5, Flooding: branch [0] was
    "Select adjacent player to remove 4 M€ from" (type `player`), the
    `--target` given on the command line was dropped in silence, and the
    app answered HTTP 400 "Not a valid SelectPlayerResponse".

    `choice` is a branch index (int), a dotted path into a submenu
    ("0.1" = that submenu's second entry), OR a case-insensitive substring
    of a branch's title in the LIVE prompt's own options (Codex H4a: the
    app hides branches the player cannot execute, so the visible index can
    differ from the card data's branch order — a title survives that, an
    index does not). An ambiguous or unmatched substring raises Ask naming
    the candidate titles; nothing is transmitted.

    The branch's type is the contract — option / player / space / card /
    amount, plus a nested `or` submenu addressed by a dotted choice
    ("0.1"). Generic: no card is ever named here. A branch that needs an
    argument the caller did not give raises an Ask naming the flag, so
    nothing is transmitted.
    """
    options = wf.get("options") or []
    raw = str(choice)
    head, _, rest = raw.partition(".")
    try:
        idx = int(head)
    except ValueError:
        idx = _match_branch_by_title(options, raw, wf)
        rest = ""
    if not 0 <= idx < len(options):
        raise Ask(f"choice {idx} out of range for '{prompt_title(wf)}' "
                  f"({len(options)} option(s))", wf)
    branch = options[idx]
    # A numeric index is the app's LIVE ordering, which the card data does
    # not fix: one recorded game sent "remove 2 microbes" as index 1 where
    # the app's index 1 was "add 1 microbe", and the wrong action went out.
    # `expect` is the step's own claim about what it is selecting; if the
    # branch does not match it, nothing is transmitted.
    if expect and str(expect).lower() not in prompt_title(branch).lower():
        listed = ", ".join(f"[{i}] {prompt_title(o)}"
                           for i, o in enumerate(options))
        raise Ask(f"choice {choice!r} selects branch [{idx}] "
                  f"'{prompt_title(branch)}' but the step expected "
                  f"{expect!r} — the app's branch order is not the card's. "
                  f"Live options: {listed}", wf)
    t = branch.get("type") or "option"
    where = f"branch [{idx}] '{prompt_title(branch)}' is a {t!r} prompt"

    def wrap(resp: dict, used: str | None) -> tuple[dict, str | None]:
        return or_choice(idx, resp), used

    if t == "or":
        if not rest:
            listed = ", ".join(f"{idx}.{i} {prompt_title(o)}"
                               for i, o in enumerate(branch.get("options") or []))
            raise Ask(f"{where} (a submenu) — pass --choice {idx}.<n>: {listed}",
                      wf)
        inner, used = or_branch_response(branch, rest, store=store, cards=cards,
                                         space=space, target=target,
                                         amount=amount, players=players)
        return wrap(inner, used)
    if t == "option":
        return wrap(option(), None)
    if t == "player":
        if target is None:
            offer = (f" (the app offers {branch['players']})"
                     if branch.get("players") else "")
            raise Ask(f"{where} — pass --target <name|color>{offer}", wf)
        return wrap(target_player(player_color(store, target, players)), "player")
    if t == "space":
        if space is None:
            raise Ask(f"{where} — pass --space <hex>", wf)
        sid = space_ref(space)
        legal = [str(s) for s in branch.get("spaces") or []]
        if legal and sid not in legal:
            raise Ask(f"space {sid} is not among the branch's legal spaces "
                      f"{legal[:12]}", wf)
        return wrap(_space_response(sid), "space")
    if t == "card":
        offered = offered_names(branch)
        canon = {n.lower(): n for n in offered}
        names = list(cards or [])
        if not names and int(branch.get("min") or 0) > 0:
            raise Ask(f"{where} — pass --cards \"<Card>\" (the app offers "
                      f"{offered})", wf)
        unknown = [n for n in names if n.lower() not in canon]
        if offered and unknown:
            raise Ask(f"{unknown} not offered by branch [{idx}]; it offers "
                      f"{offered}", wf)
        return wrap(_cards_response([canon.get(n.lower(), n) for n in names]),
                    "card")
    if t == "amount":
        if amount is None:
            span = ""
            if isinstance(branch.get("min"), int) or isinstance(branch.get("max"), int):
                span = f" ({branch.get('min')}–{branch.get('max')})"
            raise Ask(f"{where} — pass --amount <n>{span}", wf)
        try:
            n = int(amount)
        except (TypeError, ValueError):
            raise Ask(f"--amount takes a number, got {amount!r}", wf)
        lo, hi = branch.get("min"), branch.get("max")
        if (isinstance(lo, int) and n < lo) or (isinstance(hi, int) and n > hi):
            raise Ask(f"amount {n} is outside the branch's range {lo}–{hi}", wf)
        return wrap(amount_response(n), "amount")
    raise Ask(f"{where} — no builder for it: answer it with "
              f"sparring.py send, then planlib.py done", wf)


def is_space_wrapper(wf) -> bool:
    """An `or` whose branch [0] is a `space` prompt — the app's
    final-greenery placement (Player.takeActionForFinalGreenery: SelectSpace
    + "Don't place a greenery"). Codex H3b: a bare space response to it is
    HTTP 400 "Not a valid OrOptionsResponse"."""
    if not isinstance(wf, dict) or wf.get("type") != "or":
        return False
    first = (wf.get("options") or [{}])[0]
    return first.get("type") == "space"


def space_prompt_response(wf, space_id=None, skip: bool = False) -> dict:
    """Answer a board-space prompt whichever way the app wraps it: a bare
    `space` prompt, or the `or → space` wrapper (`skip` takes its decline
    branch — the first `option`-typed one)."""
    if is_space_wrapper(wf):
        decline = next((i for i, o in enumerate(wf.get("options") or [])
                        if (o.get("type") or "option") == "option"), None)
        if skip:
            if decline is None:
                raise Ask("this prompt has no decline branch to --skip to", wf)
            return or_choice(decline, option())
        if space_id is None:
            alt = (f", or --skip to take "
                   f"'{prompt_title(wf['options'][decline])}'"
                   if decline is not None else "")
            raise Ask(f"'{prompt_title(wf)}' wraps a space branch — pass a "
                      f"hex to place{alt}", wf)
        response, _ = or_branch_response(wf, 0, space=space_id)
        return response
    if not isinstance(wf, dict) or wf.get("type") != "space":
        raise Ask(f"this is not a space prompt (type "
                  f"{(wf or {}).get('type')!r})", wf)
    if skip:
        raise Ask("a bare `space` prompt cannot be skipped — pass a hex", wf)
    if space_id is None:
        raise Ask("pass the hex to place on", wf)
    return space(space_id)


# ── log rendering ────────────────────────────────────────────

class DataType(IntEnum):
    """common/logs/LogMessageDataType.ts — persisted as numbers, never
    reordered upstream."""
    STRING = 0
    RAW_STRING = 1
    PLAYER = 2          # value = player COLOR
    CARD = 3
    AWARD = 4
    MILESTONE = 5
    COLONY = 6
    _STANDARD_PROJECT = 7
    PARTY = 8
    TILE_TYPE = 9       # value = TileType enum number
    SPACE_BONUS = 10    # value = SpaceBonus enum number
    GLOBAL_EVENT = 11
    UNDERGROUND_TOKEN = 12
    SPACE = 13          # value = space id ("63")
    CARDS = 14          # value = [card names]


# card-table: tile-names
# common/TileType.ts tileTypeToString (base + Corporate Era + promo subset).
# These are TILE identities in the app's own log vocabulary, not card
# models — several happen to share the name of the card that places them.
TILE_TYPES = ["greenery", "ocean", "city", "Capital", "Commercial District",
              "Ecological Zone", "Industrial Center", "Lava Flows",
              "Mining Area", "Mining Rights", "Mohole Area",
              "Natural Preserve", "Nuclear Zone", "Restricted Area",
              "Deimos Down", "Great Dam", "Magnetic Field Generators"]
# card-table: end
# common/boards/SpaceBonus.ts TO_STRING_MAP (Tharsis subset)
SPACE_BONUSES = ["Titanium", "Steel", "Plant", "Card", "Heat", "Ocean",
                 "M€"]


def _render_datum(datum, names: dict | None) -> str:
    """Mirror of GameLogs.getLogsForGameEnd's callback: PLAYER → name
    (fallback: the color), everything else → value.toString(). The two
    numeric enums render as their upstream display names instead of the
    bare number the export prints."""
    if not isinstance(datum, dict):
        return ""
    t, v = datum.get("type"), datum.get("value")
    if t is None or v is None:
        return ""
    if t == DataType.PLAYER:
        return (names or {}).get(v, v)
    if t == DataType.CARDS and isinstance(v, (list, tuple)):
        return ",".join(str(c) for c in v)          # JS Array.toString()
    if t == DataType.TILE_TYPE and isinstance(v, int) and v < len(TILE_TYPES):
        return TILE_TYPES[v]
    if t == DataType.SPACE_BONUS and isinstance(v, int) and v < len(SPACE_BONUSES):
        return SPACE_BONUSES[v]
    return str(v)


def render_log_entry(entry: dict, names: dict | None = None) -> str:
    """One LogMessage → the plain-text line the ?full export prints
    (scripts/applog_parser.py grammar). `names` maps color → player name
    (from /api/player players[]); missing → the color is shown."""
    message = str(entry.get("message", ""))
    data = entry.get("data") or []
    out, i = [], 0
    while True:
        j = message.find("${", i)
        if j < 0:
            out.append(message[i:])
            break
        k = message.find("}", j)
        idx = message[j + 2:k] if k > j else ""
        if k < 0 or not idx.isdigit() or len(idx) > 2:
            out.append(message[i:j + 2])
            i = j + 2
            continue
        out.append(message[i:j])
        n = int(idx)
        out.append(_render_datum(data[n] if n < len(data) else None, names))
        i = k + 1
    return "".join(out)


def color_names(player_view: dict) -> dict:
    """color → name from a /api/player payload."""
    return {p.get("color"): p.get("name")
            for p in player_view.get("players", []) if p.get("color")}


def log_lines(client: AppClient, pid: str, generation: int | None = None,
              names: dict | None = None) -> list[str]:
    """The LOG panel for <pid> as export-style lines. Without `names`
    the player view is fetched once for the color → name map."""
    if names is None:
        names = color_names(client.player(pid))
    return [render_log_entry(e, names) for e in client.game_logs(pid, generation)]


# ── CLI ──────────────────────────────────────────────────────

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=None,
                   help=f"app base URL (default: state/setup.json appUrl, "
                        f"${ENV_VAR}, {DEFAULT_URL})")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("waitingfor"); s.add_argument("pid")
    s.add_argument("--game-age", type=int, default=0)
    s.add_argument("--undo-count", type=int, default=0)
    s = sub.add_parser("logs"); s.add_argument("pid")
    s.add_argument("--generation", type=int, default=None)
    s.add_argument("--full", action="store_true")
    s.add_argument("--json", action="store_true", help="raw entries")
    s = sub.add_parser("player"); s.add_argument("pid")
    s = sub.add_parser("send"); s.add_argument("pid"); s.add_argument("json")
    a = p.parse_args(argv)
    setup = None
    if a.url is None:
        try:
            from pathlib import Path
            setup = json.loads((Path(__file__).resolve().parent.parent
                                / "state" / "setup.json").read_text())
        except Exception:
            setup = None
    client = AppClient(a.url) if a.url else AppClient.from_setup(setup)
    try:
        if a.cmd == "waitingfor":
            print(json.dumps(client.waiting_for(a.pid, a.game_age, a.undo_count)))
        elif a.cmd == "logs":
            if a.full:
                print(client.game_logs(a.pid, full=True))
            elif a.json:
                print(json.dumps(client.game_logs(a.pid, a.generation), indent=1))
            else:
                print("\n".join(log_lines(client, a.pid, a.generation)))
        elif a.cmd == "player":
            print(json.dumps(client.player(a.pid), indent=1))
        elif a.cmd == "send":
            print(json.dumps(client.send(a.pid, json.loads(a.json)))[:2000])
        return 0
    except (AppError, AppUnavailable) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
