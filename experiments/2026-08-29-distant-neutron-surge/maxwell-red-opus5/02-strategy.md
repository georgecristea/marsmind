# The strategy I actually played

## The opening decision (generation 1)

Two corporations offered: **United Nations Mars Initiative** (40 MC) and **Mining Guild**
(30 MC + 5 steel + 1 steel production). Ten initial cards: Corporate Stronghold, Hackers,
Earth Office, Nitrogen-Rich Asteroid, Ironworks, Rad-Suits, Callisto Penal Mines, Virus,
Insulation, Big Asteroid.

I scored both corps against the same ten cards per `strategy/03`:

- **Mining Guild — 2 direct synergy hits** (Corporate Stronghold and Ironworks are building
  tags payable in steel; Corporate Stronghold's city can land on a metal-bonus hex to trigger
  +1 steel production), plus 2 building tags on the corp itself toward Builder.
- **UNMI — 0 hits.** Its only TR-cheap partners (Nitrogen-Rich Asteroid 31, Big Asteroid 27)
  were unaffordable in gen 1 after keeps, and it is the weakest corp in every no-prelude source.

`payback.py` cleared four keeps and rejected Nitrogen-Rich Asteroid (−6 MC net, needs 17
generations, 14 available). **Picked Mining Guild, bought 5** (Corporate Stronghold, Callisto
Penal Mines, Hackers, Rad-Suits, Earth Office).

**This is also where the game was lost, and I did not see it.** Every one of those five cards
is an economy card. The hand had no repeatable terraforming in it and I did not treat that as
a problem to solve — I treated cash as the win condition. See `04-analysis.md`.

## The plan in one line

Build the largest MC engine on the table, use it to buy points late, and win the parts of the
scoreboard that money buys outright — milestones and awards.

That plan executed almost perfectly. It still lost by 26, because the part of the scoreboard
money *doesn't* buy — terraforming rating — is bigger than all the rest combined at two players.

## Generation by generation

| Gen | What I did | My TR | Their TR |
|---:|---|---:|---:|
| 1 | SP Power Plant → Corporate Stronghold (city on **hex 53**, steel-steel bonus, Mining Guild fired) → Earth Office. MC prod 3, steel prod 2. | 20 | 20 |
| 2 | Geothermal Power → **Hackers** (my MC prod 5, *his* MC prod to −2) → Solar Wind Power. | 20 | 20 |
| 3 | Callisto Penal Mines (MC prod 8). | 20 | 25 |
| 4 | Lagrange Observatory → Rad-Suits → Fuel Factory. MC prod 10. | 20 | 25 |
| 5 | Advanced Alloys → **funded Banker** (8 MC) → Ore Processor. | 20 | 26 |
| 6 | Search For Life (max-6%-oxygen window, played the turn before it shut) → **funded Scientist** (14 MC) → SP Power Plant. | 20 | 27 |
| 7 | Space Elevator → Soil Factory → **claimed Builder** (8 MC, 8 of 8 building tags). | 20 | 29 |
| 8 | **Funded Miner** (20 MC, last slot) → Space Elevator action → Indentured Workers → Designed Microorganisms at 8 MC. | 20 | 33 |
| 9 | **Small Animals** (cut his plant production 2→1) → Interstellar Colony Ship (4 VP) → Dust Seals → Technology Demonstration. | 20 | 39 |
| 10 | Windmills → Ice Asteroid (2 oceans, +2 TR) → **converted 8 plants → greenery on hex 59** → Acquired Company. | **23** | 41 |
| 11 | Space Elevator action → Release of Inert Gases (+2 TR) → SP Greenery on hex 54. | **26** | 43 |
| 12 | SP Greenery on hex 47 — **took the final oxygen step** → Tundra Farming. | **27** | 58 |

**Read that TR column.** My terraforming rating was still 20 — its starting value, untouched —
at the end of generation 9, three quarters of the way through the game.

## The four decisions I got right

1. **The two-player award rule.** I read `score.py` rather than assuming, and found
   `AWARD_VP = (5, 2)` with *"2nd not awarded in 2p"*. At two players an award you win is a
   clean 5–0, and there are only three slots. I funded all three on metrics structurally
   locked by his archetype — Banker (he was an Ecoline plant deck with ~1 MC production),
   Scientist, and Miner (his steel and titanium production were **zero all game**). Result:
   **15–0**, and it denied him the Landlord and Thermalist he was leading. Best 42 MC I spent.
2. **Claiming Builder in generation 7.** He took Gardener (gen 6) and Mayor (gen 8). Claiming
   the third slot early both scored 5 and made **Terraformer unreachable** for him — he
   finished at TR 58, far past the 35 it needed.
3. **Hackers in generation 2.** 3 MC for a four-step production swing, and in a two-player
   game the "decrease any MC production" has exactly one legal target. It held him at 0–2 MC
   production for most of the game and he repeatedly ended generations broke.
4. **Racing him for the last oxygen step in gen 12.** He was first player with a greenery
   ready; I bought the 23 MC standard project ahead of everything else to bank the final +1 TR.

## The one denial that worked, and its limit

**Small Animals** (gen 9) cut his plant production 2→1. He had it back to 4 within two
generations via Noctis Farming and Protected Valley. Single-step production attacks do not
slow an engine that is still buying cards; it arrived far too late to matter.
