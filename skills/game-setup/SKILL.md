---
name: game-setup
description: Session start — run setup.py, then evaluate both corporations against the initial 10 cards and recommend corp, keeps and a generation-1 opening line.
---
# Skill: game-setup — session start + the corp & initial-10 decision
TRIGGER: new game; "let's start"; corp choice photo.

1. Run scripts/setup.py (players, colors, aliases, expansions, map,
   seating order, first player, house rules, game mode). House rules are
   recorded and respected all session.
2. CORP + INITIAL 10 CARDS = the game's highest-stakes decision. When
   the photo/list of 2 corps + 10 cards arrives:
   - read strategy/03-corporations.md + 04's corp initial-value math
     (≥60 MC threshold) + 05-openings.md
   - evaluate BOTH corps against the SAME 10 cards: initial value +
     per-card synergy bonuses; budget = corp MC − 3 × keeps; make sure
     the kept cards are actually playable on that budget early
   - pick archetype(s) from the cards (flexibility > fixed style),
     recommend corp + keeps + a gen-1 opening line (05) in
     execution-trace format
3. Record: scripts/apply.py corp <me> <name> --mc N; dealt-log the 10
   via hand add for keeps; log rejects in a note.
4. Opponents' corps: log as announced (apply.py corp <opp> <name> --mc N
   from db.json starting MC) — feeds threat-analysis from generation 1.
