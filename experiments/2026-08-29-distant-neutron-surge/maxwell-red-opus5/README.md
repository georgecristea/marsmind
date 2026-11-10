# Distant Neutron Surge — Maxwell (Red) — 2026-08-29

Full artifact set for one online, two-player Terraforming Mars game played end-to-end
by the Phobos advisor in **app-online full-API autopilot** mode.

## Result

**LOSS — Mortimer (blue, Ecoline) 92 · Maxwell (red, Mining Guild) 66.** Margin −26.
12 generations. Game ended when all three global parameters maxed at the end of gen 12.

| | TR | Milestones | Awards | Greenery | City | Cards | **Total** |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mortimer (blue, Ecoline) | 58 | 10 | 0 | 11 | 10 | 3 | **92** |
| Maxwell (red, Mining Guild) | 27 | 5 | 15 | 3 | 3 | 13 | **66** |

Won decisively on awards (15–0) and card VP (13–3). Lost decisively on
terraforming rating (−31) and tile VP (−15).

## Contents

| File | What it is |
|---|---|
| `01-result.md` | Final scoring, both tableaus, the VP ledger line by line |
| `02-strategy.md` | The plan I actually played, generation by generation, and why |
| `03-game-log.md` | Every app LOG line, grouped by generation, both seats |
| `04-analysis.md` | Post-mortem: root cause of the loss, what worked, ranked mistakes |
| `05-failures-and-harness-bugs.md` | Harness defects and friction hit during play, with evidence |
| `06-kb-recommendations.md` | Proposed strategy-KB amendments (not applied — for separate review) |
| `raw/` | Untouched source data: setup, final engine state, full log, plan store, latency digest, app final state, filed bug |

## Provenance

- **Mode:** `app-online`, full API autopilot. The app was the rules engine; every one of
  my actions was transmitted through `scripts/execute.py` and the app view was adopted
  after each step. I never touched the opponent's state and had no visibility into their
  hand — only the public LOG panel and `/api/player` for my own seat.
- **Server:** `http://REDACTED-LAN-HOST:8080`, game "Distant Neutron Surge", my playerId `REDACTED-PLAYER-ID-MAXWELL`.
- **Setup:** 2 players, Corporate Era + base, Tharsis, no draft, no Prelude/Venus/Colonies/Turmoil,
  no WGT. Maxwell = red (me), Mortimer = blue.
- **Session:** `games/2026-08-29-game3`, executor `auto`, judgment level `every`.
- **Model:** **Opus 5** (confirmed by the player after the game; the session's
  system prompt string was stale).
- **Reasoning effort:** not configured or exposed to me in this session; no explicit
  effort/thinking-budget setting was surfaced, so I cannot report a value and have not invented one.
- **Opponent:** Mortimer (blue), played from a separate backend. I had no visibility into
  their hand, their reasoning or their tooling at any point — only the public LOG panel and the
  shared table state the app exposes. The opponent class for this row is recorded in the private
  eval ledger, not here.

## Wall-clock / latency

From `raw/latency-digest.json` (260 timing marks):

| Phase | Calls | p50 | p95 | max |
|---|---:|---:|---:|---:|
| `listen` (drain opponent's moves) | 71 | 3083 ms | 4100 ms | 4119 ms |
| `execute` (transmit one action) | 57 | 4139 ms | 8260 ms | 8271 ms |
| `sweep` | 2 | 5 ms | 7 ms | 7 ms |

≈ 7.5 minutes of pure harness round-trip time across 128 blocking calls, before any
model thinking.

The app's own clock (`timer.sumElapsed`) puts total thinking-plus-acting time at
**Maxwell 48 min 19 s vs Mortimer 39 min 26 s** — I was ~23% slower over the game.
See `05-failures-and-harness-bugs.md` for where the avoidable round trips went.
