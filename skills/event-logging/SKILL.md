---
name: event-logging
description: Async input grammar — turn any table report (free text, voice garble, photos, turn-ID execution reports, anonymous attacks, table declarations) into logged apply.py events immediately.
---
# Skill: event-logging — async input grammar
TRIGGER: any message that reports table events, in any form, any time.
Information arrives ad hoc, out of order, incomplete — design for it.

- Free-form grammar: <player-ref> + <action>. "Blue played Comet",
  "green plays a city", "Red did the microbe thing" → resolve player via
  setup.json aliases (name/color/alias, case-insensitive). Ambiguous →
  ask ONCE, then save the phrasing: scripts/session.py alias <player> <text>.
- Voice-noise tolerance: fuzzy-match card names via scripts/cards.py
  ("comets"→Comet, "mining right"→Mining Rights).
- Apply IMMEDIATELY via scripts/apply.py (play/res/prod/raise/standard/
  milestone/…) — one bash call per reply (apply.py batch for several
  events), one line of ack. Opponent card plays are event-driven: one
  line → their playedCards[] grows (never wait for photos of their
  tableau).
- Inference chains: "Green raised temp" → apply raise temperature Green
  (temp +2°C, their TR +1). Log what a play implies when db.json knows it.
- Phase commands anywhere: "round is over"/"gen done"/"production" →
  scripts/produce.py. "I'm first now" → note exception in log.
- Implicit photo intents: 4 cards = research phase (skills/research-phase);
  own mat = state sync (res/prod/sync); main board = globals/tiles sync;
  opponent mats between gens = reconciliation skill.
- Tolerate gaps: NEVER block on missing input; never assume no news =
  nothing happened. If a gap matters for a recommendation, ask ONE
  targeted question, not a checklist. Drift self-heals at reconciliation.

## Verdict-first + one batched call (identical text in turn-advisor / research-phase / event-logging)
In EVERY table-hot reply the FIRST LINE is the instruction the player
executes in the app / at the table: the draft pick ("Pick: X"), the buy
list ("BUY: X + Y (N MC)"), the GO actions ("GO: 1a … · 1b …"). Draft
picks and buy verdicts are decided from the photo + the state already in
context — NO tool call precedes that line; answer, THEN log. Everything
mechanical the reply needs (log events, plan set/done, map render,
research.py for the record) goes into ONE batched tool call AFTER the
verdict: a single bash invocation (apply.py batch / turn.py done +
planlib + render_board chained with &&), never a sequence of calls.
Opponent-event acks: one bash call, one line of reply. Reasoning, RCA
and detours come after the verdict, never before it. A generation plan
is composed in the speculative window (turn-advisor); its GO message
opens with the actions, and the plan block + maps follow.

## Turn-ID execution reports
"I did 1a" / "performed both turn 2" / "3b done" → planlib.py done <label>
+ apply the step's state events (apply.py play/standard/convert/…) exactly
as planned, or ask ONE question if the step had a 🔁 recheck pending.

## Implicit intent: revealed-card decision (blue actions, effects)
A photo of ONE (or few) revealed card(s) while a look-and-buy action is in
flight (Business Network, Inventors' Guild, research effects) = a buy/keep
verdict request. Respond IMMEDIATELY, no tool call before the first
line: verdict + one-line KB math + exact click instruction. Anticipate
these photos whenever such an action is part of the current plan step.
Log the outcome only after the player confirms — never eagerly.

## Research-phase checklist (anti-drift)
Every research phase, for EVERY opponent, log the keep count the moment
it's visible (they take cards from the row): apply.py research <player>
--kept N. Missing this drifts their MC simulation by 3 per card — the
most common drift class in practice.

## Opponent event → plan re-check (cross-link)
After applying ANY opponent event while a generation plan is active:
walk the plan's OPEN 🔁 steps (turn-advisor volatility rule). Untouched →
stay silent, no re-plan chatter. Touched (their tile took a planned hex,
removal threatens a conversion, a milestone/award race moved) → flag it
unprompted, patch the remaining steps via planlib set, and re-show the
full plan block with maps. Full re-plan only on structural disruption.

## Per-generation main-board photo
Physical games: every generation turnover expects ONE main-board photo
(TR markers, global parameters, tiles) logged as a first-class
observation. It is the cheap public anchor: diff it against tracked
state; any missed event surfaces as a delta. Absorb the delta (log
"unknown +N source"), ask at most ONE targeted question. Turnover
without the photo → request it once, never block on it.

## No pre-queued observations
Never log an opponent count/value BEFORE reading the output that reports
it (autoplay summaries, photos, the player's words). A research count
batched as "kept 0" before the source prints "kept 1" is a silent drift.
Log AFTER the source speaks; batching is for events already observed.

## Card-name resolution policy (cards.resolve)
Every spoken/typed card name goes through `cards.resolve(name, pool=…)`:
- "accept" → use silently. "confirm" → use it but ECHO the canonical
  name in the reply ("Lake Marineris — logged"); the player corrects if
  wrong. "ask" → never guess; one question.
- ALWAYS pass the context pool when one exists: the player's hand, their
  tableau actions, the 4-card research row, an opponent's known
  tableau. Context turns heavy voice-garble into safe accepts
  ("marinaria" is unambiguous within a 4-card hand).
Regression corpus = real utterances from earlier games
(tests/test_cards.py::TestResolvePolicy) — add new garbles after every
game.

## Anonymous events + table declarations
- "Someone removed my plants" → `apply.py attack <me> plants N` — the
  EFFECT is applied immediately (the player's ledger is truth regardless
  of attacker); attribution PENDS and the advisor asks "who?" once, at a
  calm moment. Resolve with `apply.py attribute <idx> <player>`.
  Attacks with known attacker: `--by <player>` (feeds threat-analysis).
- "This is the last generation" (table vote) → `apply.py final` — pins
  the clock, flips the advisor to pure-VP mode instantly.
- SUBSYSTEM-SILENCE PROBE: by ~generation 3 with zero milestone/award
  events at the table, ask ONCE whether the table ignores them by habit
  or house rule — record the answer (houseRules if ruled out; exploit
  flag if merely ignored). Same probe for awards.
