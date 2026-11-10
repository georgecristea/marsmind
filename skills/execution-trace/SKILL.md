---
name: execution-trace
description: Output-format contract for every action recommendation — numbered resolution-order micro-scripts, before→after stat changes, map-card placements, phone rendering, verification cues.
---
# Skill: execution-trace — output format contract
USE: for EVERY action recommendation, from any skill. This format is shared.

Every recommended action = a numbered micro-script in ACTUAL RESOLUTION
ORDER, one physical table-step per line, never grouped by type. Template:

▶️ PLAY: Comet 🔴 event
 1. Pay 21 MC → balance 25 → 4
 2. Temperature +1 step → −10 → −8°C → TR 23 → 24
 3. Place ocean on [named hex from board.json] → gain [exact bonus]
 4. Remove up to 3 plants from [target — say who and why]
 5. Card to event pile
 ✅ End state: 4 MC, TR 24, temp −8°C

Rules:
- Steps come from card data (cards/db.json) + board.json, never memory.
- Every resource change shows before → after. Running MC balance on every
  payment line. Emoji: 💰 MC 🏆 TR ⚡ energy 🔥 heat 🌱 plants.
- Card-type chips match physical frames: 🟢 automated, 🔵 active, 🔴 event.
- Placement steps name the exact hex and enumerate its bonus + adjacency
  gains (board.json math, photos only verify).
- After the trace, log the same action via scripts/apply.py so state
  matches the table when the player executes it.
- Card names in full — never acronyms or abbreviations.
- Phone display: prefer a styled HTML panel (colors, chips, large
  cost/balance numbers, tickable steps); the emoji text template is the
  chat fallback. Never walls of raw text.
- One plan per generation (full sequence at generation start); quick
  re-asks only on disruption.

## Placement instructions (instruction baked into the map)
On the phone a separate image card and a text instruction never sit
together reliably, so the instruction lives INSIDE the image, and the
placement message carries nothing else.
1. Render with the banner and the tile type:
   `scripts/render_board.py --highlight <space> --step <id> --tile
   <city|greenery|ocean|special>` (or `--title "<text>"` to override).
   It writes state/board.svg with the instruction drawn as a banner at
   the top, the target hex ringed thick with a HERE pointer, and prints
   the composed title as the LAST stdout line.
2. A placement message contains ONLY the map card: the SVG sent as a
   file with the caption = that last stdout line, verbatim. No logs, no
   trace lines, no plan block, nothing before or after it in that
   message. The plan block, acks and the remaining steps go in the
   FOLLOWING message.
3. Banner text format (auto-composed from render_board.describe()):
   `<step> — <TILE> on <app grid ref> (<landmark phrase>). <gains>`
   e.g. `3b — GREENERY on J2 (land hex, adjacent tiles: Green's city).
   +2 steel`. The grid ref is the ONLINE APP's label: rows A–H, then J
   — the app has no row I, so our I2 is printed J2 (render_board.
   app_label). Never instruct by internal hex id alone, never reference
   "the map above".
4. After the player places, their board photo / the app state verifies;
   mismatch → apply.py is corrected (state follows the table, or the
   tile is moved if the table broke a rule).
5. Acceptance rule: the player must be able to find and execute a
   placement from the phone WITHOUT asking "where". If that fails at a
   real placement, the message format is the defect — fix it, and note
   the outcome in the game's log.

## Phone rendering rule (enforced)
NEVER wrap table-hot output (plans, traces, saturation lists) in code
fences — they collapse/truncate on the phone. Use plain markdown lines:
✅ done, ▶️ NEXT in bold, ⬜ open. One plan block per message, at the end.

## Verification cues
Every instruction ends with what the player should SEE if it went right —
the cue is part of the step, not an optional extra. Only the verbs
differ by mode:
- Physical mode: physical verbs + marker/pile checks. "Pay 8 MC to the
  bank, move your TR marker to 45, take a greenery tile — your plant
  pile should now hold 1 cube and the TR marker sits on 45."
- App mode: exact UI verbs + button-label checks. "Tick 3 cards — the
  button must read 'Buy 3 cards (9 MC)' BEFORE you click it."
A step whose cue doesn't match reality is reported, not forced — that
report routes to correct.py, never to improvisation. The ✅ End state
line is the cue for the whole action.
