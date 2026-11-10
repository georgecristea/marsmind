# Strategy KB 0 — Winning Layers (architecture) & Sources

## Layer 1 — Strategy Knowledge Base (this folder) [IN PROGRESS]
Distilled community wisdom the advisor MUST read before recommending.
Files:
- 01-valuation-economy.md  — MC values of resources/production/TR, payback math
- 02-archetypes-game-arc.md — engine archetypes, 3-phase arc, milestones, 4–5p
- 03-corporations.md        — corp-by-corp notes, tiers for 4-5p, corp+hand
                              joint decision (facts verified vs open-source TM)
- 04-card-tiers.md          — canonical MC prices, break-even cheat sheet,
                              timing rules (BGG Quantified Guide + observed play)
- 05-openings.md            — first-2-gen playbooks per archetype, opening
                              traps, 4-5p adjustments
- 06-lessons-from-play.md   — LEDGER of VP-priced rules from observed games,
                              one line per lesson with a neutral evidence tag
                              ("4p, WGT, gen 7 — a rival"); grows one game
                              at a time

Key sources found (community research):
- BGG thread 1847708 "A Quantified Guide to TM Strategy" (Ender_Wiggin) —
  canonical MC-valuation framework; fetch via browser (JS-rendered).
- boardgamestrategist.wordpress.com — early-game card selection series.
- everythingisagame.com/terraforming-mars-strategy — corp tiers, player-count
  adaptations (2p engine-pure → 5p interactive).
- boardoflife.wordpress.com — corporation strategic notes.
- Steam community consensus: flexibility > fixed style; card draw is
  near-universally strong; do the arithmetic on combos.

## Layer 2 — Deterministic Calculators [TO BUILD]
LLM judges, code computes. Scripts (place in scripts/):
- payback.py  — input: card cost, production delta, gens remaining →
                net MC value + break-even generation.
- endgame.py  — input: game.json, gens left (1–2) → brute-force own action
                sequences → max achievable VP line.
- odds.py     — draw probabilities: P(card type X in next N draws) given
                deck composition; attack-risk estimates.
- clock.py    — game-length estimator: current parameters + observed fill
                rate → predicted end generation (drives phase switching).

## Layer 3 — Self-play calibration [LATER]
Log full games via harness; post-game review of advisor errors; patch KB.

## Advisor contract
Before recommending: read game.json + ALL strategy/*.md. Every card
evaluation must cite which principle/archetype justifies it. When Layer 2
scripts exist, arithmetic claims (payback, endgame lines) must come from
script output, not mental math.
CITE OBSERVED PLAY: 06 is evidence, 01-05 are priors. When a 06 line
applies, cite it by group and evidence tag ("06 plants: 4p, WGT, gen 6 —
a rival") and let its measured price override the prior; when a prior and
a 06 line conflict, amend the prior in place and note the amendment. After
every game, append the ranked mistakes and the winner's decisive moves to
06 (neutrally — no names, no dates) before anything else.
