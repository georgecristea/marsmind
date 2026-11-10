---
name: threat-analysis
description: Per-opponent threats section of every generation plan — infer archetypes from logged plays, price counters (milestone snipes, removal, denial, game-length control) on worst-case margins.
---
# Skill: threat-analysis — read opponents, counter them, control the clock
TRIGGER: part of every generation plan; also on notable opponent plays.

Per opponent, from their event-driven playedCards[] (WITH generation
sequence), tags, tiles, production:
1. Infer archetype(s) from 02-archetypes-game-arc.md — what is their
   engine trying to become? Sequence matters: early energy+steel =
   building toward cities; microbe cards in generations 1-2 = long-game
   VP farm.
2. What do they NEED next (cards, parameters, board spots, milestones)?
3. Concrete counters, priced via 04's math:
   - milestone snipes (claim what they're 1 step from — 8 MC for 5 VP
     AND −5 VP for them; at a table that ignores milestones by habit
     they are free VP — see the silence probe in event-logging)
   - removal targets (plant-hoarder at 6+ plants with a greenery pending;
     never hoard 8 plants yourself when removal is live)
   - deny scarce slots: last oceans, contested map regions, award funding
   - GAME-LENGTH CONTROL (first-class lever): when TR-leading, rush
     parameters to strand slow engines (TR-RUSH from 02; 04's short-game
     rule); when behind on engine, same — end it before their engine pays.
     When our engine leads, quietly avoid accelerating the end.
4. Output as the `threats` section of the generation plan: per opponent
   one block — archetype, next need, counter (with cost/benefit).
Ruthlessness is authorized: attack cards, snipes, early game end.

## Race margins under uncertainty
Opponent hands are hidden and turns go unobserved — price threats on
worst-case bounds, not point estimates: claim contested milestones one
step early; credit racing opponents ~1 step of hidden progress per
unobserved turn; price plant-removal risk with `scripts/odds.py
removal` (P someone holds it, by hand size) before advising an 8-plant
hoard or a delayed conversion. See 02's race-margin section.
