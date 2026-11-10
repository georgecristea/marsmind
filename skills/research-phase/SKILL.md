---
name: research-phase
description: Research-phase buy evaluation — a photo of exactly 4 cards (or a draft round) gets an immediate verdict-first BUY/Pick line, KB-cited reasoning, one batched research.py + dealt log, then the generation plan.
---
# Skill: research-phase — 4-card buy evaluation (flagship)
TRIGGER (implicit): a photo of exactly 4 cards with no text = research
phase. Do NOT wait to be asked — evaluate immediately. Draft on
(setup.json draft=true, or the lobby shows "Draft: research phase") →
the Draft variant section below.

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

Procedure:
1. Identify the cards → cards.resolve against cards/db.json, pool = the
   row. Uncertain read → the verdict line still leads with what is
   certain, then ONE question for the unreadable card (iron rule 4).
2. FIRST LINE: "BUY: X + Y (N MC)" (or "BUY: nothing"). Decided from the
   photo + state in context (globals, clock range, MC, tableau, hand) and
   the KB — no tool call before it.
3. Reasoning under the verdict, one line per card: cost + 3 MC keep vs
   canonical prices (04-card-tiers.md); requirement window fit vs the
   clock (windows on the way OUT are urgent, on the way IN must not rot
   in hand); synergy checklist from 02 (feeds my engine? unlocks my hand?
   denies an opponent?); VP density (≤5 MC/VP good, ≤3 excellent);
   opponents' directions (would THEY want it? does it feed a threat they
   are building?). Every keep cites its KB principle. Budget guard: never
   recommend keeps that break the plan for the generation ("buy the win"
   needs MC to actually play things).
4. ONE batched tool call AFTER the verdict — a single bash invocation
   chaining: scripts/research.py "A" "B" "C" "D" --tableau "<played,
   comma-sep>" --hand "<hand, comma-sep>" [--resources "Card=N,…"] (the
   plumbing check: db lookup, windows vs the ONE clock, payback, ×K
   scaling — ×0 prints ZERO-EFFECT, a per-tag card with no matching tags
   is worthless in hand; a `REFUSED` line is a HARD GATE: the card's tag or
   production requirement is not met by the PERSISTENT tags in play (corp +
   green + blue; event tags and the card's own tags never count) and it
   cannot be kept without `--confirm-requirement "<Card>"` — the verdict
   line must not say BUY for it; `activates in hand: N` per trigger card;
   `next VP at` per accumulator) && apply.py dealt A B C D --kept X Y && the
   generation-plan set (hand-off below). If the script contradicts the
   verdict (a closed window missed, a ×0 card, a payback that fails the
   clock) the reply ends with ONE line "CORRECTION: BUY: …" — never a
   silent re-verdict. Read ALL strategy/*.md if not already in context
   this session.
5. Re-sort the hand if the buys changed the best play order (contract:
   one-line reason per moved card).

## Shape gate (the anti-fixation check)
Before the BUY verdict is composed, the state already in context includes
scripts/shape.py flags (the advise.py brief carries a SHAPE section; at a
research phase read it). Two rules, both priced in a real 8-VP loss:
- A SECOND consecutive zero-buy verdict is not a per-phase judgement: it is
  a hard trigger to re-derive the whole plan (exit, clock range top,
  economy) before answering. apply.py refuses to log it without
  --override "<reason>"; the reason goes in the reply, not just the log.
- "The offers are all unplayable" is itself a finding: cards dead for lack
  of energy/steel/production base mean the PLAN made them dead — surface
  that loop to the player instead of silently declining again.
Doctrine: the script computes the flags; the verdict stays the model's.

## Draft variant (setup.json draft=true, or the lobby shows "Draft: research phase")
Research is pick-1-pass: round 1 = 4 cards (pick 1, pass the rest),
round 2 = 3 cards (pick 1), round 3 = 2 cards (pick 1); the 4th card
arrives automatically; then the BUY screen shows the 4 drafted cards at
3 MC each.
- Per round the reply is two lines and NO tool call: first line
  "Pick: X", second line one sentence of reasoning (window vs clock,
  engine fit, denial). Decide from the photo + state in context.
- At the BUY screen: first line "BUY: X + Y (N MC)", then the plan
  (hand-off below). The batched call after it chains
  `scripts/research.py --quick "A" "B" "C" "D"` (one line per card:
  cost+3, window vs the ONE clock, payback or VP density,
  KEEP/PASS/DENY-only/JUDGE tag) && apply.py dealt … --kept … && the
  plan set.
- Drafted-but-unbought cards are discarded: a pick that denies an
  opponent (DENY-only) costs nothing beyond the pick — denial value
  counts at PICK time; never buy a denial card for 3 MC.
- Genuinely uncertain window/payback in a round: the "Pick: X" line
  still goes first; `research.py --quick` on the 2-4 named cards runs
  AFTER it in the same reply, and a contradiction is corrected with one
  final line "CORRECTION: Pick: Y".

## Auto-confirm (standing order)
The player ALWAYS follows the keep recommendation — do not wait for
confirmation. In the same reply as the verdict, in the ONE batched call
after it: log dealt/kept (apply.py dealt … --kept …), charge the MC, and
proceed straight into the generation plan (turn-advisor hand-off
below). They buy the recommended cards in the app at their leisure. If
they ever report a deviation, planlib reopen / apply.py corrections
reconcile it — their call is still final, it just doesn't block.

## Hand-off: research → full generation plan (mandatory)
The keep/reject verdict is not the end of the skill. In the same reply
(auto-confirm above), inside the one batched call:
1. Log dealt/kept (apply.py dealt … --kept …).
2. Resolve every opponent's research (log keeps; sparring.py drives app
   opponents).
3. Compose the FULL generation plan via skills/turn-advisor (advise.py →
   planlib set, ending in the passGate step) — without being asked; the
   plan block follows the BUY line in the reply. "What do I do" must
   never be necessary after research.
If real-table opponents act before the player, log their events first
(skills/event-logging); the plan composes with those events in state,
and later opponent events hit the plan's 🔁 volatility re-check rather
than triggering a silent full re-plan.

## Any-acquisition rule
research.py runs on EVERY card that enters consideration, not only the
4-card deal: Business Contacts-style picks, draws from placement bonuses,
card-draw actions — `--quick` for 2-4 named cards, in the batched call
AFTER the verdict line (verdict-first rule above). A card taken from a
look without the script can carry an unnoticed requirement (a 6-ocean
gate, say) for many generations. The engine also refuses `play` on
closed windows, but the evaluation belongs at PICK time, not play time.
