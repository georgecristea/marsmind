---
name: turn-advisor
description: Generation plans and the anti-pass discipline — compose, simulate, label and re-anchor the full-generation plan (turn IDs, volatility markers, machine-gated pass step, speculative drafts).
---
# Skill: turn-advisor — generation plans & the anti-Pass discipline
TRIGGER: generation start, "what do I do", any disruption to the plan.

Procedure:
1. Run scripts/advise.py — NEVER advise from memory — in the speculative
   window (opponents' round / research), so the GO message itself opens
   with the actions (verdict-first rule below). The brief contains
   state, saturation list, windows, clock, opponents, and the full KB.
   It is --brief by default in app modes (KB read once per session) and
   --full in physical mode (KB included every call). Read the brief's
   `Free land: N` line and the `Clock:` range aloud in the plan header;
   at `⚠ BOARD NEARLY FULL` the plan must not buy plant production or
   tile cards (KB 01/02 land-scarcity rule).
2. Produce ONE full-generation plan: sequence of turns (max 2 actions
   each), every action in execution-trace format. Include:
   - milestone-race timing vs seating ("you act before Green this gen")
   - requirement windows being played around
   - what to hold back and why (react-late rule from 04)
3. HAND ORDER IS A CONTRACT: end with the hand in recommended play
   order; apply it via scripts/apply.py hand reorder …; the player
   mirrors it physically. Any state change → re-check order, one-line
   reason per moved card.
4. THE SATURATION RULE: never recommend Pass without walking the
   brief's saturation list and giving a verdict per remaining item
   (▢ available → do it or say exactly why it's bad; ✓ used). Pass is
   legal advice only when the list is empty or everything left is
   genuinely negative.
5. Every card evaluation cites its KB principle; every arithmetic claim
   comes from a script (payback/clock/endgame), not mental math.
   ANTI-ANCHORING: a 06 lesson applies only when its evidence conditions
   (player count, expansions, phase, ×N, seats/humans class) match the
   live position. When no principle fits, SAY SO and price from 01/04 —
   that is the contract working, not a violation. ×1 lessons are priors
   to weigh, not laws; seats-class timing lessons are discounted at a
   human table.
6. Include the threats section (skills/threat-analysis).

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

## Turn-ID contract (enforced)
Every plan step is labeled `<turn><letter>`: 1a, 1b, 2a, 2b… (max 2 actions
per turn). Store every generation plan via scripts/planlib.py (JSON on
stdin, shape `{"threats": "<per-opponent threats from the brief's RACES
block>", "steps": [{id/summary/volatility…}]}` — planlib REFUSES a live plan
without a non-empty `threats` field). The player reports execution by
label — "did 1a", "performed both turn 1", "5b done" — → planlib.py done
<label>, then apply the matching state events via apply.py. Never
re-derive what was executed from memory: plan.json is the truth of intent,
log.md of execution.

## Plan brevity (enforced)
Doctrine, not a relaxation of the contract above — brevity cuts prose, never
data. Before → after values, the cue, the running MC balance, `mapHighlight`
and the `passGate` step all stay exactly as required.
1. A step summary is the trace line plus ONE clause, never a paragraph:
   `PLAY Sponsors (3 MC) — 💰 25→22; MC prod 4→6 · Earth tag at 6 off`.
2. A KB citation is a bracketed tag — `[06 milestones]`, `[04 canonical]` —
   not a sentence of KB prose.
3. The threats block is one line per opponent (corp, TR, what they need
   next, my counter) plus one line of consequence — not a narrative.
4. Hex choices are the hex id plus the adjacency count from `apply.py
   spaces` (e.g. "hex 35, adjMine=2"), never a geometric essay.
5. The reasoning that justified a step lives in the advisor's thinking; when
   it matters for the record, ONE `apply.py note` per generation carries it
   — not a restatement in every step.

Example — a real P9 gen 13 step, same events, before and after this rule:
- Before (430 chars): "SP CITY on hex 35 (25 MC) — pay 25 -> 57 -> 32 MC;
  gain the 2-plant hex bonus (plants 2 -> 4) and 2 MC for the adjacent ocean
  on 34 (MC 32 -> 34); MC production 23 -> 24. FIFTH CITY and the 06 3p
  last-generation line: hex 35 already touches my greeneries on 26 and 27,
  so the city scores 2 VP the moment it lands, and step 2a adds a third
  beside it. It is legal — no city is adjacent (neighbours 26, 27, 34, 36,
  43, 44)."
- After (~150 chars): "SP CITY on hex 35 (25 MC) — 💰 57→32→34 (ocean adj);
  plants 2→4; MC prod 23→24. Adj greeneries 26/27 = 2 VP now. [06 3p
  last-gen]"

## Volatility markers + proactive re-check (enforced)
Each step is classed:
- 🔒 safe — own-mat engine step (play own production/economy card, own
  conversion with no removal threat live): execute blind.
- 🔁 recheck — board-contested or window-dependent (tile placement hexes,
  milestone claims, requirement-window plays, conversions while opponent
  removal is live, award races): confirm against latest opponent events
  BEFORE executing.
When any logged opponent event touches a 🔁 step, flag it IMMEDIATELY and
unprompted ("Green took hex 13 — ocean → hex 28 instead"); if the plan
still holds, stay silent. Full re-plan only on structural disruption.

## Self-contained messages (enforced)
Plan steps that involve a board placement carry a `mapHighlight` field
(the space id). EVERY message that shows the plan — first delivery,
re-anchor, unchanged re-show — MUST regenerate and attach the map card
(render_board.py --highlight) at that step, as long as the step is open.
NEVER reference a map "above" or in an earlier message; maps are free to
regenerate. A plan message must be fully usable in isolation on a phone
with zero scrolling.

## Full-plan block (enforced, never truncated)
EVERY table-hot message — plans, verdicts, detour closings, event acks —
ends with the COMPLETE generation plan: every step, ✅/▶️ NEXT/⬜ status,
one line each, plain text (no code fences). Never a subset, never
"continuing from X", even when only one step remains or nothing changed.
The player keeps overview from any single message without scrolling. The
detour re-anchor IS this block (plus the one-line next action).

## Detour re-anchor protocol (enforced)
A "detour" is ANY exchange during an active game that is not itself plan
execution: rules questions, system fixes, KB debates, photo issues, small
talk. THE RULE: the message that closes a detour ends with the plan status
block (planlib.py show — ✅ done / ▶️ NEXT pointer) and restates the next
physical action in one line. The player must never have to scroll back or
ask "where were we". This applies during development sessions exactly as
at the table. If no plan is active, re-anchor to the current phase instead
(research buys pending, produce due, etc.).

## Card prices in a step are GROSS (enforced by the executor)
A step's `cost` is the price the APP advertises (`calculatedCost`) — the
printed cost after CARD discounts only. Steel and titanium are separate
`steel:` / `titanium:` kwargs and are NEVER subtracted from it; the splitter
prices the ore. Recording a net price is refused before anything is sent
("price disagreement … engine/step N vs app calculatedCost M"). Both seats of
one recorded game hit this, from opposite directions — one pinned a price with
the ore already deducted, the other recorded 8 MC after two steel where the
app said 12. The guard was right both times; the contract was simply not
written down. If a genuine discount the engine does not model makes the app
cheaper, pin `cost` to the APP's number, never to your own arithmetic.

## Or-branches are named, never numbered (enforced by planlib)
A card whose action or play reads "X, or Y" takes its branch as a TITLE
SUBSTRING: `"choice": "remove 3 microbes"`. Never a bare index — the app's
live branch order is not the card's printed order (it hides branches you
cannot execute), so the same integer picks a different branch in each
layer; that is how a step meaning "remove 3 microbes to gain TR" once
executed "add 1 microbe" instead. A title means one branch everywhere,
matched by the same helper in the sandbox and on the wire, and it is
self-describing, so nothing else is needed. planlib refuses a bare integer;
an index is legal only alongside `"choiceLabel": "<title substring>"`, which
the executor checks against the LIVE branch and refuses before transmitting.

## Plan simulation gate (enforced)
Every plan step that changes state carries machine-readable `events`
(Engine method + args). planlib.set_plan SIMULATES the full sequence in
a sandbox before the plan is shown — an unaffordable/illegal step aborts
composition. Rebates/refunds (Media Group, Credicor) arrive AFTER
payment: affordability is always GROSS cost, which the simulation
enforces automatically because the engine does. Never present a plan
whose set_plan raised.

## Generation-start phase gate (enforced)
Order is MANDATORY at every generation turnover:
1. Close production + reconcile (produce.py, cross-check).
2. ANNOUNCE: "New generation N — research first: show me the 4 cards"
   and WAIT. No action planning before research is resolved.
3. Research verdict (skills/research-phase): the player auto-follows it
   (standing order) — log dealt/keeps immediately, no confirmation wait;
   deviations reconcile after the fact.
4. In the SAME turn, compose + simulate the generation plan (kept
   cards may change it entirely).
A research photo arriving before the announcement short-circuits step 2,
but never steps 3-4. The research verdict must LEAD its message — never
buried under RCA/detours; drift analysis comes after.

## Exit re-justification + shape gate (enforced by planlib)
At every generation turnover, before planlib set:
- Re-derive the NAMED VP EXIT against LIVE board state and write it into the
  plan's "exit" field, naming its REPEATABLE component. A correct gen-1 exit
  does not persist by default — oxygen maxing, land running out or a rival's
  economy tripling yours invalidates it (an 8-VP loss was level on tiles and
  milestones and lost purely on slope).
- Read the SHAPE block (scripts/shape.py via the advise brief): cards
  bought/gen vs the field, MC production vs table median, repeatable-source
  inventory. A ceiling-only position (all one-off purchases, nothing
  compounding) is surfaced to the player as a finding with the numbers;
  planlib refuses such a plan without an explicit "exitAck" reason.
- CLOCK: the plan horizon is clock.py's RANGE TOP, never the point estimate.
- CALIBRATION: tool verdicts are quoted at their own confidence. Never
  hand-copy menu.py's award lock test — planlib INJECTS it verbatim onto
  any award-funding step (`lockVerdict`) and renders it as its own ⚖ line
  in `show` / `turn.py done`. Write the summary without it; a summary that
  claims "locked" against a "not lockable" verdict is still refused.
Doctrine: scripts compute, gates interrupt, the model decides — every
override carries a written reason and is audited in the postmortem.

## Saturation re-check timing
The saturation check runs against LIVE state at the moment of the pass
recommendation — not at plan time. Heat/plant conversions especially:
production and card effects during the generation can cross the 8
threshold after the plan was written. Re-run the checklist (advise.py
saturation block) immediately before advising Pass, every time.

## Pass is machine-gated
Every plan's pass step carries `"passGate": true`. planlib REFUSES to
mark it done while the live saturation list has AVAILABLE items — the
advisor cannot recommend an early pass even by mistake. Override needs
done <id> --force "<reason per item>", which is logged. The player is
the beginner at the table: the harness is their only source of "what can
I still do" — the gate makes that promise structural. Costed card actions
are affordability-checked (mcCost parsed at registration).

## Structural supports (trust the tool)
- set_plan AUTOFILLS `mapHighlight` from any `place` event; explicit
  values win. You still add it manually for placements resolved at
  execution time (e.g. a card whose place event is logged later).
- `planlib.py show` prints 📍 ATTACH MAP markers per open placement step
  and a ⚠ warning when the plan has no passGate step. Its output is the
  chat plan block: paste it styled (bold ids, ✅/▶️/⬜), NEVER inside code
  fences (execution-trace phone rule).
- End EVERY generation plan with an explicit pass step carrying
  `"passGate": true` — planlib refuses to mark it done while live
  saturation still shows available actions.

## Batching mandate
Mechanical loops never run one call at a time. Composite verbs exist —
use them: `turn.py done <labels…>` (done + note + tracker numbers +
plan + NEXT in one process), `planlib.py done` with multiple labels,
`apply.py batch` (JSON-lines, one call per opponent turn). ONE shell
invocation per table-hot reply (verdict-first rule): independent
lookups (state read, card lookup, odds) chain into that same invocation
with &&. A sequential chain of single-purpose calls where a composite
verb exists is a defect, not a style choice. Verification stays —
batched into the same invocation, never dropped.

## Speculative turn prep (the multi-opponent speed lever)
While OPPONENTS are taking their round (especially 4-opponent physical
games), do not idle: compose the player's next-turn plan immediately as
a DRAFT — `planlib.py set --draft` (same JSON, same sandbox gate). As
opponent events arrive (skills/event-logging), they hit the draft's 🔁
steps exactly like a live plan's. When the player's turn comes:
1. `planlib.py promote` — re-simulates the whole draft against CURRENT
   state. Clean → the GO message is a DELTA ("plan stands", maps
   re-attached), near-instant.
2. Promote REFUSED (a named step became infeasible — hex taken, race
   moved) → patch only the named step(s), set fresh, go.
`done` on an unpromoted draft is machine-refused — a speculative plan
can never be executed by accident. Composing the draft costs time nobody
is waiting on; promoting costs one simulation. This replaces "start
planning when it's your turn" entirely in physical mode.

## Two-lane round loop (API play)
Lane 1 is mechanical (the listener absorbs app-log lines into the feed
and the engine; triage classifies them). Lane 2 is judgment — you. Per
generation:
1. AFTER OWN TURN — compose the next-turn DRAFT immediately: `planlib.py
   set --draft` (JSON with `threats` from the RACES block). Nobody waits.
2. PER OPPONENT ROUND — the blocking `listen.py wait` sleeps through the
   opponents' turns and returns their events as ONE batch, so there is no
   per-event wake (the first autopilot game ran one sweep in twelve
   generations because of this). The listener surfaces judgment itself: a
   drain that leaves unhandled hard triggers ends with a `⚠ JUDGMENT
   NEEDED` banner naming them; run `advise.py --sweep` and conclude with
   ONE `planlib.py patch` — the exact command CONCLUDE prints, `--live`
   and all (`replace` / `insert_after` / `remove` / `threats` / `feed`:
   [line ids], step lists or `{"<id>": step}`; only `feed` = "plan
   stands"). A patch that ERRORS is stamped `patchFailed` in plan.json and
   blocks execution until it lands — never chain past it. No banner = a
   quiet round, no reasoning owed. Triggers older than the plan and
   turnover triggers from earlier generations are auto-pruned. A TIMEOUT
   prints `WAITING ON: <seat>`: a stopped seat freezes the table, re-message it.
   Event-by-event cadence (manual pace): `turn.py round --opp I --of N
   [--last-before-me] [--boundary]` prints PENDING TRIGGERS, then the
   sweep brief or `SWEEP: no`, then one `judgment:` line. Pending
   triggers are handled IMMEDIATELY, sweep or not; a sweep never blocks
   the player — promote abandons it (counted; two abandoned rounds in a
   row degrade the level).
3. OWN TURN — `turn.py go`: listens once, warns `⚠ JUDGMENT: N unhandled
   trigger(s)` (read them BEFORE executing; it warns, not refuses, so the
   loop cannot deadlock), promotes the draft (refusal names the step →
   patch → go again), prints the executor hint, plan, menu line, NEXT.
   Then execute per `judgment.executor`: manual/assist = the player acts
   and you `turn.py done <labels>`; auto = `scripts/execute.py` sends each
   step and ADOPTS the app view (ℹ deltas, no exit 41). Verdict first.
4. GENERATION BOUNDARY — produce.py → research verdict → FULL re-plan
   (set, not patch); the old generation's draft is dead.
Degrade rule: `judgment.py set level every|per-opponent|after-k|
triggers-only` may change mid-game; auto-degrade steps one notch per two
consecutive abandoned rounds, a clean round resets the streak.
`triggers-only` still handles pending triggers — only scheduled sweeps
stop. `judgment.py status` (last line of every `round`) when sweeps feel
late; `advise.py --sweep --peek` looks without committing.

## Verbosity: terse (default) vs full
`judgment.py set verbosity terse|full`, flippable mid-game, shown by
`judgment.py show` / `status`. TERSE is the default in every game mode:
`planlib.py set|patch` REFUSES an open step whose summary exceeds
`planlib.SUMMARY_BUDGET` characters, naming the step and its length — the
advisor's own clock is generated tokens, and the prose that goes is the KB
citation, the rejected alternatives, the "why this beats X" and the board
state the threats block already carries. Machine-required text never counts
against the budget (the step's `cue`, and an award lock verdict if one is
quoted at all — normally it is injected, not written); one step may
opt out with `"verbose": "<reason>"`, logged like any override.
Terse compresses PROSE ONLY. Untouched: every `event`, every before→after
value, the running 💰 balance, the `cue`, the threats block, the `exit`
field, placement maps, the plan block itself. FULL is for a live human
table where the player is reading along and the reasoning is the product.

## WGT-choice step (World Government Terraforming expansion)
When the brief prints "WGT ON … THAT IS YOU", the plan ends with one more
step AFTER passGate: `WGT: raise <parameter> [ocean on <grid ref>]`, no
events (the app prompts the player after everyone passed; log the outcome
with `apply.py wgt …`, never `raise`/`place`). Choose in this order: open
our own requirement window > close an opponent's window > deny the
heat-production thresholds > ocean adjacency for us / denial for them >
clock control (shorten when TR-leading, lengthen when our engine leads).
When an opponent chooses, draft the next generation with one extra
worst-case step on the parameter that hurts the player most.
