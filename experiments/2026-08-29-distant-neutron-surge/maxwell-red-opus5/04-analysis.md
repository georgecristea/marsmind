# Post-mortem — why this was lost by 26

## The one-sentence cause

I built the biggest cash engine on the table and never built a terraforming engine, so my
terraforming rating was still **20 — its starting value — at the end of generation 9** of a
12-generation game, while Mortimer's heat-and-plant engine raised his every single generation
from gen 1.

## The number that says it all

| | TR at gen 1 | TR at gen 9 | TR at end | Gained |
|---|---:|---:|---:|---:|
| Maxwell | 20 | **20** | 27 | **+7** |
| Mortimer | 20 | 33 | 58 | **+38** |

Final TR delta −31, against a final margin of −26. **The TR gap alone was larger than the
loss.** Every other column I contested I won: awards +15, card VP +10.

## The trap, stated precisely

I priced the game as "MC production → buy points late". That is a coherent plan in the
abstract, and I executed it well: MC production 15 against his 2, four milestone/award
purchases, 26 cards played, 13 card VP against his 3.

What I failed to price is that **TR is itself the best production card in the game.** Each
step of terraforming rating pays 1 MC every generation *and* 1 VP at the end. Mortimer did not
"spend money on points" — he built an engine whose output was simultaneously income and score.

The consequence is brutal and I watched it happen without naming it until too late:

| Income at gen 12 | TR | MC production | **Total per generation** |
|---|---:|---:|---:|
| Mortimer | 58 | 2 | **60** |
| Maxwell | 27 | 15 | **42** |

**The dedicated MC-engine player finished poorer than the terraforming player.** My entire
economic thesis inverted somewhere around generation 8, and because I had framed the game as
"out-produce him and buy the win", I kept buying production (Acquired Company as late as
generation 10) instead of noticing that his TR had become a better cash engine than my cash engine.

## Where his 38 TR came from — all of it repeatable, none of it bought late

- **Mohole Area, generation 1** — 20 MC for **4 heat production**. That single card, played on
  his first turn, produced roughly one temperature step every other generation for the whole
  game. He later pushed heat production to 6.
- **Ecoline plants** — 2–4 plant production for 12 generations, at 7 plants per greenery
  (Ecoline's discount), giving 11 greeneries and with them most of the 14 oxygen steps.
- **Ocean and temperature cards** layered on top: Towing A Comet, Lava Flows, Comet, Deep Well
  Heating, GHG Producing Bacteria, Giant Ice Asteroid, plus standard-project asteroids and
  aquifers once his income was enormous.

He terraformed on essentially every turn of the game at near-zero marginal cost. I terraformed
on eleven turns total, all in generations 10–12, at 7–23 MC per step.

## Ranked mistakes

1. **Never built any repeatable TR source (root cause).** Not one card in my 26-card tableau
   generated terraforming rating on a recurring basis. Everything was MC, steel, or one-shot.
2. **Abandoned the Ore Processor engine in generation 4 on a misapplied KB rule.** Ore Processor
   converts 4 energy → 1 titanium + 1 oxygen step (**+1 TR**) every generation, forever. I
   dropped the plan after Mortimer used Energy Tapping *once*, citing `strategy/02`'s
   "an engine with ONE stealable input is a trap". That rule is about a single input with no
   backup — it is not a reason to abandon the only repeatable TR source available with nine
   generations left. I then compounded the error: **Fuel Factory (gen 4) and Soil Factory
   (gen 7) each consume 1 energy production**, so I actively dismantled the very resource
   both Ore Processor and any heat route needed. Ore Processor sat in my tableau, unused, for
   eight generations as a decorative building tag.
3. **Violated my own KB on tile planning.** `strategy/02` says: *"the turn you place a city,
   book its plant source ... a city with no plant source is worth ~2."* I placed city 53 in
   generation 1 and had no plant source until Designed Microorganisms in **generation 8**; the
   first greenery landed in **generation 10**. Final tile VP 6 against 21. When I finally did
   place greeneries they were excellent — all three adjacent to city 53, scoring 3 VP each —
   which is exactly the evidence that doing it six generations earlier was available and worth ~12 VP.
4. **The opening evaluation asked the wrong question.** I scored the ten cards for economy and
   corp synergy and never once asked *"where does my TR come from?"* Nitrogen-Rich Asteroid
   (+3 TR) was rejected by `payback.py` at −6 MC net — but payback.py prices *production*, and
   I let a tool built for one question answer a different one. A card that is bad production
   value can still be correct TR tempo.
5. **Never corrected the removal gap against a known plant deck.** I passed on Virus (1 MC,
   remove 5 plants) and Big Asteroid in the opening ten, before corps were revealed — fair.
   But Mortimer revealed Ecoline on turn one and over the next ~30 offered cards I bought
   exactly one removal effect, Small Animals, in **generation 9**. He converted plants to
   greeneries eleven times.
6. **Over-invested in Builder.** ~24 MC of pure enablers (an 11 MC Power Plant bought only to
   make Soil Factory legal) for 5 VP plus the Terraformer denial. The denial was real and I'd
   defend the claim itself, but the enabler chain was expensive, and the same MC spent on TR
   in generation 6 would have compounded as income for six generations.

## What worked and should be kept

1. **Reading `score.py` instead of assuming the award rules.** Finding `AWARD_VP = (5, 2)`
   with *"2nd not awarded in 2p"* reframed the whole middle game: at two players each award is
   a 5–0 swing and there are only three slots. Sweeping all three on structurally-locked
   metrics scored 15 and denied him ~10. Best 42 MC of the game.
2. **Locking metrics by archetype, not by lead.** I funded Banker against a plant deck with
   1 MC production, and Miner against an opponent whose steel *and* titanium production were
   zero for the entire game — not because I was ahead, but because he had no mechanism to
   catch up. All three held to the final scoring.
3. **Builder timed to deny Terraformer.** Claimed the last milestone slot in gen 7 while he
   was at TR 29; he finished at 58, which would have been a free 5 VP.
4. **Requirement-window discipline.** Search For Life (max 6% oxygen) played at 5% the turn
   before his greenery shut it; the final oxygen step taken in gen 12 ahead of a first-player
   opponent holding a ready greenery.
5. **Hackers.** 3 MC for a four-step production swing with exactly one legal target at 2p.

## Honest note on the mid-game read

At generation 7 I wrote in my own threat block: *"I am winning the economy and losing the TR
race... the pivot from engine to TR/points must happen no later than gen 5."* I diagnosed this
correctly and then **did not act on it** — I spent generations 7 and 8 on Builder enablers and
award funding instead. The analysis was right; the reallocation never happened. That gap
between naming a problem and changing the spending is the most reusable lesson here.

---

# Appendix — the two tables that settle it

Both come from the app's own end-of-game payload (`raw/final-app-state.json`), found only
while assembling these artifacts. They are much sharper evidence than anything above.

## A. Who actually terraformed — `globalParameterSteps`

The app counts, per player, how many steps of each global parameter that player raised
across the whole game.

| Parameter | Steps in the game | Mortimer raised | **Maxwell raised** |
|---|---:|---:|---:|
| Temperature | 19 | 19 | **0** |
| Oxygen | 14 | 11 | 3 |
| Oceans | 9 | 7 | 2 |
| **Total** | **42** | **37** | **5** |

**I raised the global parameters five times in twelve generations. He did it thirty-seven
times — and took every single one of the nineteen temperature steps.** Temperature is the
largest TR pool on the board and I never touched it once, because I never bought a single point
of heat production and abandoned the one oxygen engine I owned (Ore Processor) in generation 4.

That row — Temperature 19–0 — is this game in one line.

## B. Where the game was actually lost — `victoryPointsByGeneration`

| Gen | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Mortimer | 20 | 23 | 27 | 27 | 37 | 41 | 43 | 55 | 63 | 73 | 82 | **92** |
| Maxwell | 18 | 17 | 19 | 21 | 26 | 31 | 39 | 43 | 48 | 55 | 60 | **66** |
| **Gap** | −2 | −6 | −8 | −6 | −11 | −10 | **−4** | −12 | −15 | −18 | −22 | **−26** |

The narrowest the game ever got was **generation 7, four points down** — exactly when the
milestone-and-award plan had just paid out (Builder claimed, Banker and Scientist funded).
The plan to buy the scoreboard *worked*, and it very nearly held.

Then the gap goes −4 → −12 → −15 → −18 → −22 → −26: **I lost 22 VP across the last five
generations**, at a steady ~4–5 per generation. That is precisely the rate at which a TR engine
compounds against a player who has none — his terraforming was paying him both points and the
income to buy more of it, while my cash engine had already spent its one-off purchases
(the awards and the milestone) and had nothing repeatable left to buy.

**The lesson is not "the award plan was wrong."** The award plan is what kept it to 26. The
lesson is that a one-off VP purchase plan has a ceiling, and a terraforming engine does not.

## C. Clock (`timer.sumElapsed`)

Maxwell 2,898,746 ms ≈ **48 min 19 s**. Mortimer 2,365,530 ms ≈ **39 min 26 s**.

I was ~23% slower over the game — noticeable, but a good deal less lopsided than it felt from
the spectator view. The gap is roughly accounted for by the ~10 avoidable harness round trips
in `05-failures-and-harness-bugs.md`; the per-generation planning discipline itself was not the
main cost.
