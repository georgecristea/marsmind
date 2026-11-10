# Strategy KB 4 — Card Valuation & Tiers
Distilled from BGG thread 1847708, "A Quantified Guide to TM Strategy"
(I-Sheng Yang, 2017) — the canonical MC-valuation framework. Base +
Corporate Era. All prices INCLUDE the 3 MC keep-cost unless noted.

## Canonical prices (what things cost when bought via cards)
| Thing               | MC | Thing                | MC |
|---------------------|----|----------------------|----|
| 1 energy production | 7  | 1 steel production   | 8  |
| 1 heat production   | 6  | 1 titanium production| 10 |
| 1 plant production  | 10 | 1 MC income          | 5  |
| 1 temperature step  | 10 | 1 TR                 | 10 |
| 1 ocean tile        | 14 | 1 VP                 | 5  |

Windfall (one-shot) resources: 1 plant = 1 steel = 1 titanium = 1 card =
2 heat = 2 MC. Tile-placement bonus ≈ 4 MC (early; decays as board fills).
Useful card in hand = 3 MC; useless = 1 MC (sell). Late, card-poor: a
useful card is worth ~7 MC. A science tag costs ~4–5 MC.

Identities to remember: ocean 14 = temp 10 + placement 4;
TR 10 = VP 5 + income 5; greenery tile = 19 (TR 10 + VP 5 + placement 4).

## The two adjustments
- **Wholesale discount**: big multi-effect cards are cheaper per unit —
  play big cards when you can afford them (don't go all-out in gen 1 and
  then be unable to afford a gen-2 big card).
- **Requirement discount**: harder requirements → cheaper card (plant-prod
  cards vary ±4 MC, others ±2). A card whose requirement JUST became
  satisfied is usually above-rate value.
- Max-requirement cards ("max 5% O2" etc.) are almost always worth playing
  — priced cheap, but they expire: play or discard early.

## Standard projects = cards + 4 MC
SP energy 11 / temp 14 / ocean 18 / greenery ≈ 19-value for 23. You
overpay ~4 MC per SP. That 4 MC is routinely negated by circumstance —
grab SPs when any of these apply, else prefer cards:
- Free bonus steps (temp bumps at O2 thresholds, ocean from temp track):
  worth even 2 SPs of overpay; count turn order into them, stall if needed.
- Milestone security: 3× SP greenery + 8 = 20 MC for Gardener's 5 VP —
  better than card-rate. NEVER let anyone walk into a milestone uncontested.
- Ocean adjacency (2 MC/ocean) and greenery-next-to-own-city (+1 VP = 5 MC)
  fully negate the overpay. Mid-game on, city next to 2 greeneries pays.
- Heat production from SP asteroid is a TRAP unless the heat is genuinely
  useful to your plan.
- Power Plant SP (11) into energy SOLD for MC (Power Infrastructure-class
  1:1 cashers) is a double trap: 24 MC of SPs + ~30 energy cashed = 0 TR;
  kept as heat = 3-4 TR (observed for a rival in a 4-player game — the
  winning margin — 06 TR engines). Energy is heat-to-be; its cash value
  is 1 MC only when heat has no track left.

## Engine vs terraform — the core equivalence
5 MC → 1 MC income → (over ~10 gens) → 10 MC → 1 VP late = the same as
just buying VP early. There is NO inherent edge to engine-building; the
edge is only in above-rate cards. Game length is a Nash tug-of-war:
board/SP/event players shorten it, blue-green engine players lengthen it.
Build only engines that pay ≥1 VP/5 MC even in a SHORT game (~8 gens in
4–5p) — they win short and long. When holding the inferior engine,
terraform hard and end the game early. (Matches 02's TR-RUSH lever.)

## Break-even cheat sheet (usages/triggers to hit 1 VP per 5 MC)
- Energy users: Steelworks/Ore Processor/Ironworks ≈ 4 uses pre-max-O2;
  Physics Complex 6 (usually too slow). Add ~1 use per 2–3 energy prod
  bought via SP instead of cards.
- Repeatable energy→TR: Nuclear Power + Equatorial Magnetizer in gen 1 =
  8 TR for 21 MC over 8 gens (≈ 2.6 MC/TR, best rate at the table —
  observed in a 4-player game, 06 TR engines); it dies to one Power Supply
  Consortium, so buy the second energy source (Power Plant SP gen 4,
  Robotic Workforce copying the power card) BEFORE the steal, not 6 gens
  after.
- Energy prod bought after gen 5 for a heat step is dead: 3× Space Mirrors
  + Giant Space Mirror = 38 MC → 2 TR; the same MC = 2-3 asteroids
  (observed for a rival — 06 TR engines). Energy prod with only
  Steelworks-class sinks and no TR outlet: TR 27, lowest at the table
  (observed for another rival in the same 4-player game).
- Energy-prod converters (to other prod): standard rate — good early IF
  energy came from cards. Electro Catapult terrible; Soil Factory weak.
  Cities: Commercial District / Urbanized Area / Open City break even on
  income alone; Cupola/Domed Crater need 1 VP; other cities need 3+ VP →
  mid/late VP buys only. ~22 produce / ~22 consume energy cards — ignoring
  the energy sector makes a third of the deck dead for you.
- Microbes: GHG Producing Bacteria ~3 gens; Regolith Eaters 3–6;
  Nitrite Reducing 1–5; Ants 4–6; Tardigrades 4–8 (weak). Extreme-Cold
  Fungus + GHG/Regolith after break-even ≈ 1 TR/generation — elite.
- Animals: Birds/Fish good from 2 uses; Livestock 3; Predators 3+;
  Small Animals 4. Count remaining generations before buying (≥3 runway).
- Trigger cards: Pets ~6 city-triggers (near-automatic); Herbivores 5;
  Decomposers 5; Ecological Zone just 2 extra. Viral Enhancers: priced
  against your HAND, not the deck — must-keep when ≥2 activatable
  plant/microbe/animal cards are already in hand (observed in a 5-player
  game: it turned a dead plant/microbe hand — Worms, Insects, Mangrove,
  Ecological Zone — into the winning engine); at 0-1 it is the guide's
  "speeds everything by ~1". research.py --hand prints the count. Arctic
  Algae: must-keep, must-play — ~12 free plants at 4p, WGT oceans pay too
  (observed in a 4-player WGT game — 06 plants). Protected Habitats: best
  combo with any plant strategy.
- Repeatable ocean actions (Water Import from Europa 12 MC → 1 TR + bonus
  + placement MC): use EVERY gen you can afford while oceans remain — used
  once with money idle gens 6-9 = −2 TR (observed for a rival — 06 TR
  engines).
- Immigrant City early (+1 MC prod per later city, any player's) + city
  spam = Mayor + Landlord + adjacency: 23 VP from one plan (observed for
  the winner of a 4-player game — 06 tiles). Zeppelins in the LAST gen
  with 7 cities out: +7 MC prod flips Banker — price city-count production
  cards by the award, not by income (12 MC → 6 VP, same game — 06 tiles).
- Kelp Farming-class production bought gen 4 and never played after it
  unlocked gen 6: ≈ 8 MC + 12 plants ≈ 3-4 VP lost — play production the
  gen it unlocks or sell it (observed for a rival — 06 economy timing).
- Accumulator arithmetic: VP on per-resource cards is a step function —
  count to the NEXT threshold (research.py --resources), and feed
  steal/move actions from a card sitting on an odd count: Predators
  taking from Herbivores 3→2 loses nothing at 1-per-2 and is a free VP.
- Jovian VP: Ganymede Colony needs 4–5 Jovian tags; Terraforming Ganymede
  3; Miranda Resort 2 Earth tags. Beam from Thorium Asteroid & Methane
  from Titan efficient on their own. Saturn Systems at the table changes
  all Jovian math (+5 MC per early tag for them — deny accordingly).
- Card-draw engines (all science-tagged; value in card-RICH state):
  Mars University 1–2 triggers; AI Central 3 gens; Restricted Area 3–4;
  Development Center 4–5; Inventors' Guild 4–6; Olympus Conference 2–6.
  Inventors' Guild is a SELECTION engine, not just draw: look-and-buy
  finds the archetype-changing card, corp- and table-speed-independent
  (observed in a 5-player game: it found Viral Enhancers, Tundra Farming,
  Ganymede Colony and Anti-Gravity Technology) — price it above its
  4–6-trigger draw value when bought by gen 4.
- Science-tag suppliers: near-free tag on Research, Robotic Workforce,
  Natural Preserve, Fusion Power, Designed Microorganisms. Overpriced tag
  on Development Center, Adaptation Technology, Restricted Area,
  Inventors' Guild (situational). Science-req payoffs worth reaching:
  Mass Converter (5 tags, huge), Quantum Extractor (4), Gene Repair /
  Lightning Harvest (3); AI Central's rate is poor as pure value —
  its draw engine is the point.
- Security Fleet: 5 uses to break even — usually skip.
- Plant-tag greens: essentially all standard-rate → good early. Avoid
  small plant production (destruction risk): 0 or 3+.

## Corp initial-value math (guide's method; ≥60 MC = strong pick)
Value = cash + priced starting assets + fit with your 10 cards:
Teractor 60+3/early-Earth-tag; IC 70 (if steels spent early);
PhoboLog 63 (needs early Ti sinks); Ecoline 62+ (underestimate — plants
worth more to it); Saturn 57+5/early-Jovian; Credicor 57+4/big-card;
Helion 57; Thorgate 55+3/power-card; Tharsis 52+8/early-city (can win
playing ZERO cards: SP greenery next to own city is card-rate for it —
Mayor+Gardener+Landlord line); Inventrix 51+4-if-req-waived-early;
Mining Guild 48+8/bonus-steel-prod; UNMI ~40+: weak for Terraformer
milestone, but mid-late its 3 MC → 1 TR is the best per-turn rate at the
table. Baseline reference: no-corp standard = 62. Full corp playbooks →
03-corporations.md.

## Timing rules
- 2 actions/turn only when rushing a milestone or spending 8 plants
  (convert the same turn you hit 8 — idle plants get eaten); otherwise
  act late to react, especially for tile adjacency.
- Branch tags wide early while staying at-rate — flexibility multiplies
  how many future cards are useful to you.
- Late game: only 5 MC → 1 VP matters; income is dead weight — stop
  buying it (matches 01's production cutoff).
- From gen 6: printed VP at ≤ 5 MC/VP beats TR at 10-14 MC/TR — passing
  Space Station/Pets/Zeppelins/Livestock for TR cost 4-6 VP (observed in
  a 4-player game — 06 card VP). Refuse 1-VP cards at 8-19 MC (~10 MC/VP)
  while a milestone (8 → 5 VP) or asteroid (14 → 1 TR + income) is
  buyable (observed: ~9 such cards bought by one rival).
- Last generation: asteroids, awards, milestones, printed VP, conversions
  ONLY — no draw engines (AI Central 21 → 1 VP), no production (Mohole
  Area 20 → 0), no discounts (observed: ≈ 20-25 MC = 2-3 TR thrown away
  by a rival — 06 tempo).
- Negative-VP cards (Bribed Committee, Nuclear Zone, Indentured Workers)
  are at-rate in gens 1-4 and wrong from gen 8 unless net ≥ +2 VP — three
  negative VP was the whole gap to the winner (observed for a rival in a
  4-player game — 06 card VP).
- Award funding is a LOCK test, not a lead test: fund only when no rival's
  reachable max (incl. last-gen production cards) beats you (observed:
  Banker funded gen 2, lost gen 10 — 06 milestones).
- Milestone claim-first: when you qualify and a rival is one step behind
  and acts before you, the claim precedes every card (observed: a 10-VP
  swing — 06 milestones).

## Rules subtlety (practice-game lesson)
Event (red) cards' TAGS DO NOT PERSIST after play — they lie face-down.
Per-tag payoffs (Miranda Resort, Builder milestone, Scientist award, tag
requirements) count only corp + green + blue cards. Exception: the event
tag itself and "events ever played" counters (Media Archives).
