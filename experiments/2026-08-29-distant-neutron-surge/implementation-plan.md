# Post-game implementation plan

Every item below is traced to something that **actually happened in this game**, in one or both
seats' logs. Nothing here is a change for its own sake, and the two items shipped were chosen for
the ratio of value to blast radius, because a real online game is being played tonight.

Legend — **Ev**: which seat observed it. **BR**: blast radius.

---

## Status: ALL of P0–P3 shipped

Suite **2123 → 2170**, 47 new tests, zero regressions, five commits (each
independently revertible). End-to-end proof below.

### P0 · Connection reuse — `appapi.py`  *(the big one for internet play)*
**Ev: both seats, plus a measurement against the public host.** The harness
opened a **fresh connection per request**. On the LAN that is ~5 ms of waste; over
the internet — how every game is played from now on — each request pays a TCP
handshake *and* a TLS handshake before any data moves. Measured against the host
used for the previous online game night:

| | per request |
|---|---:|
| fresh connection (connect 120 ms + TLS 240 ms + transfer 115 ms) | **455 ms** |
| same request on a reused connection | **112 ms** |

**4.1×, 343 ms saved per request. At ~1800 requests a game: 13.7 min of transport
against 3.4 min.** Safety: keep-alive is skipped whenever `urllib.request.urlopen`
is not the stdlib function (so a test mock can never be bypassed and the whole
existing suite still exercises the old path), `PHOBOS_NO_KEEPALIVE=1` disables it
outright, `_ka_fetch` raises exactly what `urlopen` raises so retry/error handling
is untouched, and an idle connection the server dropped is re-established once.

### P0b · `.local` host resolved once — `appapi.py`  *(LAN only)*
214 ms connect via the mDNS name against 4.9 ms via the literal; DNS lookup is
5 ms either way, so it is dual-stack connect fallback, not resolution. Live check
1021 ms → 9.8 ms. **A no-op for internet play**, kept because LAN practice games
still use it.

### P0c · Trailing tile placements ride along — `execute.py`
Ice Asteroid and Giant Ice Asteroid each place two oceans; **both seats** stalled
on "Select space for second ocean" and needed a manual `resolve`. Extra placements
now queue as follow-ups of the play in flight.

### P1 · Correctness
- **D2 · numeric `or` index guarded.** The opposing seat *transmitted a wrong
  action* — its step's index 1 meant "remove 2 microbes", the app's index 1 was
  "add 1 microbe". A step may now carry `choiceLabel`; the resolved branch's title
  must contain it or nothing is sent. No label = today's behaviour.
- **D4 · lone player branch auto-selects.** Removal prompts arrive as an `or` menu,
  so a correct `target` went unused on Comet and Giant Ice Asteroid. Two or more
  player branches is ambiguous and refuses rather than guessing.
- **D1 · metal-value rates.** `split_payment` honours `pool["steelValue"]` /
  `["titaniumValue"]` (defaults = the constants), and `adopt_app` now **warns loudly**
  when the app prices metal differently from the engine. That silence was the real
  danger: `verify: engine == app` printed OK while both sides used the same wrong
  number. *Still deferred:* persisting the values onto the mat needs an audited
  engine verb and a new field through `_mat → diff → sync_player`; the warning
  covers the gap until then.

### P2 · Advisor and evaluator
- **Parameter-step counter on the brief.** The sharpest signal of the whole game,
  previously visible only in the post-mortem: `Parameter steps raised (from the
  log, ≈): … ⚠ YOU HAVE RAISED 3 — a cash engine that does not terraform loses on
  TR`. Approximate by construction (33/3 where the app said 37/5); the ratio is the
  point and the docstring forbids quoting it as authoritative.
- **D5 · maxed globals priced at zero** in the acquisition evaluator.
- **D3 · gross-price contract** written into `skills/turn-advisor` (doc only — the
  executor was right to refuse both seats; only the rule was unwritten).

### P3 · Hygiene
- **D8 · doctor flags stray empty root files** (advisory, never blocks play).

### Deliberately still open
- **D1 write side** — see above.
- **D6 · conditional plan steps** cannot be pre-composed. This is `set_plan`'s
  simulation gate working as specified; the patch-it-in-later workflow exists.
  No change.
- **D7 · cue-gate and pass-gate ergonomics.** Both gates were *right every time*;
  the pass gate found Space Elevator's and Small Animals' repeatable actions, worth
  ~2 VP and three cards of funding that would otherwise have been missed.
  Ergonomics only.

---

## Verification

- **Unit:** 2170 tests, OK (skipped 9, expected failures 3). Baseline was 2123.
- **End-to-end:** `e2e_practice.py --gens 3 --greedy` against the live local app —
  3 generations, 6 own turns, 13 bot runs, **64/64 feed lines applied, 0 gaps,
  0 drift incidents, 0 refusals, 0 errors**, 12.1 s wall clock, `listen` p50 **5 ms**
  and `execute` p50 **15 ms** (against 3083/4139 ms in the recorded game).
- **End-to-end OVER THE INTERNET:** the same runner against
  `https://terraforming-mars.herokuapp.com` — game created remotely, my seat's full lane
  works (`listen` p50 **359 ms**, `execute` p50 **718 ms** over HTTPS with keep-alive,
  feed 2/2 applied, **0 drift, 0 refusals**). The two BOT seats fail there with
  `HTTP 404` on `/api/player`: the shared public instance does not serve an opponent's
  player view immediately after `creategame` (the same three ids all return 200 minutes
  later, and the local server never does it). **Practice-vs-bots on a remote host only —
  it cannot affect app-online play, where opponents are humans and the harness never
  fetches their view.** Filed as
  `private/bugs/20260829-remote-practice-vs-bots-opponent-api-pla.md`; deliberately not
  fixed, because adding speculative 404-retry semantics to the one HTTP client hours
  before a live game is the wrong trade.
- **doctor:** all checks green, no active session, ready for `setup.py`.

## Pre-game checklist for the next online game

1. `python3 scripts/doctor.py` — expect all ✓.
2. At `setup.py`, give the **real server URL**. If it is a `.local` name the new
   resolver handles it; over the internet keep-alive does the work automatically.
3. If anything about the transport looks wrong mid-game, `PHOBOS_NO_KEEPALIVE=1`
   restores exactly the old behaviour without an edit.
4. The brief's new `Parameter steps raised` line is the pivot signal — if it warns,
   buy a repeatable parameter source that generation.
