# Roadmap

Open items, in rough priority order. Contributions welcome — see
`CONTRIBUTING.md`.

## Physical table
- **Phone acceptance of placement maps.** Placement instructions render a
  board map (SVG with the instruction baked in) that must be readable on a
  phone at the table. The rendering exists; sign-off from a real placement
  on a phone is still pending.

## Engine fidelity (regression fixture: `tests/test_replay_fixture.py`)
- **Immigrant City trigger set vs the app.** The app fires Immigrant City's
  income on more city placements than the engine models; the replay pins
  the resulting MC gap as an expected failure.
- **Mining Rights dynamic production.** The production bonus depends on the
  placement bonus of the chosen hex; the engine currently corrects from the
  app log instead of deriving it.
- **Noctis City triggers.** Noctis City's fixed placement and its
  interaction with city-adjacency effects are not modelled.

## Online mode
- **Lightweight turn-wait polling.** `sparring.py wait` polls the full
  player model every 2s; the server exposes a purpose-built cheap
  endpoint (`/api/waitingfor`, GO/REFRESH/WAIT) for exactly this. Switch
  the wait loop to it (and the interval can then drop below 1s). No
  push channel exists server-side (no websockets/SSE) — light polling
  is the correct mechanism unless we ever patch the vendor.
- **One-call turn executor.** Once a plan step is decided, executing it
  still costs one model round-trip per action. A `turn go <labels>`
  verb that runs the planned steps' app actions sequentially inside ONE
  script process (sparring verbs + verify at the end) would collapse a
  two-action turn to a single call — the last big latency win on the
  acting side.
- **API listener (mode 2).** Watch the hosted app's `waitingfor` endpoint
  between the player's turns, fetch new log entries, and auto-apply them
  through the app-log parser — explicit opt-in at setup, stoppable on the
  player's word. Event processing follows the two-lane design (mechanical
  absorption + triggered/scheduled judgment; see design notes).
- **Draft / research via the API.** Read drafted and dealt cards from the
  player endpoint so research verdicts need no screenshots.
- **Own-state sync via the API.** Refresh the player's own panel from the
  player endpoint after each turn instead of from photos.

## Variants
- **Surprise-variant support matrix.** A per-toggle table (full / partial /
  unsupported, with the degradation rule) plus a setup checklist that asks
  every app toggle and refuses or warns on unsupported ones; extraction of
  prelude / venus / promo decks on demand so unknown cards stay rare.

## Code health
- **tmlib split.** `scripts/tmlib.py` carries the engine, the store, the
  session manager and the board in one module; split it along those seams
  without changing the CLIs.

## Autonomous online seat ("autopilot")
The advisor plays an online seat by itself: poll the app for its turn,
read the public log and its own player view, plan with the same skills and
scripts, and submit inputs through the app's player-input endpoint (the
local sparring driver already speaks that protocol). Requires the online
API listener above. Any host (Claude Code, Codex, OpenClaw) with the repo
and a player link could then play against another instance on another
machine, the online app being the neutral referee. Rules of engagement:
public information only during the game; opponents informed.
