# Metadata

- App game name: Distant Neutron Surge
- Run/game identifier: `<gameId>`
- Local session: `games/2026-08-29-game2`
- Date: 2026-08-29
- Mode: `app-online`, public player API, executor `auto`
- Players: Mortimer/Blue/Ecoline; Maxwell/Red/Mining Guild
- Player count: 2
- Map and cards: Tharsis, base + Corporate Era, no draft
- Result: Mortimer 92–66 Maxwell
- Model: Codex, GPT-5 family (`codex-gpt-5` in the evaluation ledger)
- Reasoning effort: the runtime did not expose a named effort level; the session used its configured default
- Information policy: only Mortimer's player view and public table/log data were used; Maxwell's hidden hand was never accessed
- Source revision before artifact commit: `3ad9af335436d1553c4c7cee9f9c785d7ce77a2c`
- Network note: the supplied mDNS host did not route in the execution environment, so the same host was reached at its LAN address; that address and all player identifiers are omitted here

## Autopilot latency

| Phase | Calls | p50 | p95 | Max |
|---|---:|---:|---:|---:|
| Listener | 100 | 157 ms | 283 ms | 581 ms |
| Executor | 53 | 261 ms | 721 ms | 1,154 ms |
| Plan promotion | 12 | 82 ms | 176 ms | 193 ms |
| Judgment sweep | 10 | 19 ms | 36 ms | 37 ms |

There were 374 timing marks and zero quiet-zone abandonments.
