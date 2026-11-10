---
name: paste-loop
description: Screenshot-mode online play — every pasted app-LOG window goes through ONE listen.py paste call, the standing plan is re-printed verbatim before anything else, and at most one background sweep agent judges the position behind the player's turn.
---
# Skill: paste-loop — the screenshot-mode table protocol
TRIGGER: an app-online game WITHOUT the API opt-in (no appUrl in use) —
the player pastes the app's LOG panel text, at any granularity, at any
time. Half-turns, overlapping windows and exact re-pastes are all normal.

Doctrine (binding): scripts compute, gates interrupt, the model decides.
Reconciliation is DETERMINISTIC — the paste lane, one fast call, never an
agent. Judgment (threats, plan content) is MODEL-only and runs in a
background sweep agent. The main session is the single writer: only it
runs planlib.py patch / apply.py; a sweep agent never writes state.

## On EVERY paste, in this order
1. ONE call: `python3 scripts/listen.py paste` with the pasted text on
   stdin (heredoc — exact shape in docs/PLAYBOOK.md). NEVER apply pasted
   lines by hand via apply.py: the engine auto-applies each card's db
   effects, so a manual re-apply double-counts them. The paste lane
   replays every line exactly once (overlap-safe: re-pasting an
   overlapping or repeated window applies nothing twice), appends one
   feed entry per line and prints the hard-trigger verdicts.
2. RE-PRINT THE STANDING PLAN VERBATIM before anything else: the
   `planlib.py show` block (✅ done / ▶️ NEXT / ⬜ todo, 🔒/🔁 volatility,
   🎯 EXIT, threats), plain text, never in code fences, never retyped as
   prose. "My turn but no plan on screen" must be structurally
   impossible; the standing plan is ALWAYS executable as printed.
3. Dispatch or refresh AT MOST ONE background sweep agent
   (agents/sweeper.md). Never wait for it, never block the player on it;
   if a sweep is already in flight (state/sweep-inflight exists), do not
   dispatch another — the running one will conclude or be relaunched.

## Sweep verdicts (arrive later, off the player's clock)
- "stands" → relay ONE quiet line ("sweep: plan stands") and mark the
  feed lines handled (the empty patch with only "feed", run by the MAIN
  session). Nothing else changes.
- a patch spec → the MAIN session applies it (`planlib.py patch` with the
  sweeper's exact spec including its "feed" lines), then re-prints the
  plan block. If the patch is refused STALE (the feed advanced past the
  sweep's cursor stamp), discard the verdict and dispatch ONE fresh
  sweep; override with --stale-ok "<reason>" only when the new feed lines
  are judged irrelevant, and say so.

## What may interrupt the player
Only triage HARD TRIGGERS (the JUDGMENT block the paste call prints) may
block the player's turn — read them before executing, handle or sweep.
Everything else runs behind the standing plan. Photos/screenshots stay
the optional ground truth (skills/reconciliation); the pasted LOG is the
event channel.
