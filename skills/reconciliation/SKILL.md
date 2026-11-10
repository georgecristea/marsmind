---
name: reconciliation
description: Reconcile tracked state against ground truth — opponent mat photos, main-board photos, app screenshots or API values — via diff proposals, observe/snap, the deviation drill and turn-boundary re-sync.
---
# Skill: reconciliation — between-gen mat photos vs simulated balances
TRIGGER: opponent mat photo(s), typically batched during production phase;
any evidence that disagrees with the tracker (app value, photo, report).

1. Identify each mat's owner by cube COLOR (setup.json mapping) — never
   by seating guess.
2. Extract per mat: TR marker, all 6 resource stocks, all 6 production
   tracks. Uncertain cube counts → say so, ask for the number in text.
   Never guess silently.
3. Build a DIFF PROPOSAL per player: observed vs current (simulated)
   values, one line per changed field. The player confirms before apply.
4. Apply via scripts/apply.py observe <player> --mc N --prod-mc N …
   The script reports drift vs simulation:
   - small drift → adopt silently (script does this)
   - LARGE drift (≳5 MC or any production change) → surface it: "Green
     has 12 MC more than simulated — missed card sale or wrong
     production?" Adopt after the player confirms; the answer often
     back-corrects a production estimate or reveals a missed play (log it
     retroactively).
5. Globals tier is separate and continuous: O2/temp/TR/oceans accepted
   any time from photo, short text ("O2 10%"), or inference from logged
   actions — latest wins, parameters only move up (apply.py sync).
6. PHYSICAL mode: log every opponent tile PLACEMENT with `apply.py place
   <opp> <type> <hex>` (not just counts) — `free_land` only sees tracked
   tiles, so the board-full warning is otherwise optimistic.

## Production tracks are first-class
Every between-gen reconcile MUST capture production tracks (all 6), not
only resource stocks — a mis-tracked production drifts by its delta EVERY
generation (compounding), while a stock error is one-time. Photo checklist
per mat: TR, 6 stocks, 6 production tracks.

## Deviation drill (standing rule)
Auto-confirm means the player SOMETIMES deviates (missed buy, different
click). The moment any evidence disagrees with the tracker (app API value,
photo, their report), run this chain WITHOUT pausing the table:
1. TRUTH: fetch the app mat/tableau/hand (curl /api/player) or ask for ONE
   photo. The table/app is always truth; the tracker follows.
2. DIFF: list every mismatched quantity (MC, TR, globals, hand, played,
   board hexes).
3. COMPENSATE via scripts only: res/prod/tr for quantities, unplay/unplace
   for phantom plays/tiles, sync --force for a phantom global raise,
   hand add/remove for hand drift. Never hand-edit JSON.
4. VERIFY: re-read tracker vs truth — must match exactly; print both.
5. RE-PLAN: planlib set for the REMAINING steps (old plan is void the
   moment reality diverged), maps re-attached.
6. LOG one correction note explaining root cause.
Marking plan steps done in app games: verify the card/tile actually
appears in the app tableau BEFORE planlib done on 🔁 steps that depend
on a purchase or placement the player performed manually.

## Turn-boundary re-sync
Any mid-generation re-plan (correction, deviation, disruption) MUST
re-anchor the TURN GROUPING, not just the state:
1. Ask the app whose input is pending (curl /api/player → waitingFor)
   and how many actions the player has already taken THIS turn (app game
   log / their report / the action menu title "first action" vs "next
   action").
2. The re-planned FIRST turn contains ONLY the actions remaining in the
   real current turn (possibly just one, possibly zero → it's the
   opponent's move and the message must say WAIT, not GO).
3. Renumber from the real turn index; never reuse old labels for moved
   steps.
4. Every GO message states exactly which actions belong to THIS app
   turn; anything further is listed as upcoming, not as instructions.
Violating this desynchronizes the player from the app ("plan one action
ahead") — worse than no plan.

## Photo-read calibration
Printed card names and printed numbers read reliably in both bright and
dark light; cube-derived readings do not. Standing rules:
1. TRUST PAPER, INTERROGATE PLASTIC: printed text/costs may be read at
   face confidence; every cube-derived claim (marker position, pile
   count, cube COLOR) is demoted one confidence level before use.
2. Known biases to correct: empty production tracks read as ~1 (Corporate
   Era truth is 0 — never infer production >0 from a parallax cube read
   alone); warm light turns white cubes greenish (validate every cube
   color against setup.json's roster — a color not at the table is a
   misread); stacked metallic piles are INTERVALS, never points.
3. Temperature is ask-by-default: the marker is usually out of frame. A
   board photo without the track end never establishes temperature.
4. Reconciliation is containment, not overwrite: ledger/estimate value
   inside the photo interval → silent confirm; outside → one targeted
   question naming the delta.
5. Color calibration: before the first photo of a physical session,
   confirm every player's cube color against setup.json under the
   table's actual light (setup.py prints the checklist in physical mode).
