# Action space — base + Corporate Era (audited against the upstream engine)

Source of truth: vendor/terraforming-mars Player.getActions() (Player.ts:1560-1678).

1. Claim a milestone — 8 MC, max 3 total; hidden unless affordable AND a
   threshold met (Terraformer TR35, Mayor 3 cities, Gardener 3 greeneries,
   Builder 8 building tags, Planner 16 cards in hand).
2. Convert 8 plants → greenery — Ecoline needs 7. STILL LEGAL at max O2
   (tile + 1 VP only, no TR).
3. Convert 8 heat → temperature — STILL OFFERED at max temp but pure no-op.
4. Blue-card action — once per generation per card (incl. UNMI: 3 MC → +1 TR
   in gens where TR already rose).
5. Play project card — affordability incl. steel/Ti/heat-as-MC per corp.
6. End Turn — only mid-turn, multiplayer, opponent NOT passed. Not a pass.
7. Fund an award — 8/14/20, max 3, NO eligibility check; slots deniable.
8. Standard projects: Power Plant 11; Asteroid 14 (offered at max temp —
   wasted); Aquifer 18 (offered at 9 oceans — MONEY BURNS, no tile);
   Greenery 23 / City 25 (disabled only when no legal space).
9. Sell patents — separate action: discard any number, 1 MC each.
10. Pass — always offered; ends your generation.

Turn structure: 2 actions/turn while opponent in round; ONCE OPPONENT PASSED
— no cap, unlimited consecutive actions until you pass. Blue-action ledger
resets at production.

Saturation contract: advise._saturation mirrors ALL of the above; anything
the app offers that the list omits is a bug (learned the hard way: a missed award slot).
