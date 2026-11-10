# Game log

- G1 — judgment executor: assist → auto
- G1 — Hand +['Corporate Stronghold', 'Callisto Penal Mines', 'Hackers', 'Rad-Suits', 'Earth Office'] → ['Corporate Stronghold', 'Callisto Penal Mines', 'Hackers', 'Rad-Suits', 'Earth Office']
- G1 — triage: handled #1, #3 — Gen-1 turnover: I am first player; full gen-1 plan is being composed now (corp+hand just resolved).
- G1 — Maxwell is Mining Guild (start 30 MC → 30), +5 steel, +1 steel prod
- G1 — Maxwell: -15 MC → 15
- G1 — Mortimer is Ecoline (start 36 MC → 36), +3 plants, +2 plants prod
- G1 — Mortimer: research kept 4 cards (−12 MC → 24)
- G1 — Plan set: 1a, 1b, 2a, 2b
- G1 — Maxwell: standard project power_plant, −11 MC, +1 energy production
- G1 — Executed plan step(s): 1a
- G1 — execute.py: 1a sent to the app, app-adopted
- G1 — Maxwell played Corporate Stronghold (paid 1 MC + 5 steel) → balance 3 MC
  1. paid 1 MC (base 11)
  2. ENERGY production 1 → 0
  3. MC production 0 → 3
  4. city tile → TABLE: place it (not adjacent to a city)
- G1 — Maxwell placed city on 53 [H1], +2 steel, Mining Guild: +1 steel production
- G1 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'red city on hex 53, steel 2, MC production 3, energy production 0')
- G1 — execute.py: 1b sent to the app, app-adopted
- G1 — Mortimer played Mohole Area (~−20 MC → ~4)
  1. paid 20 MC (base 20)
  2. HEAT production 0 → 4
  3. special tile → TABLE: place it
  4. → TABLE: tile = {'type': 'moholearea', 'on': 'ocean', 'adjacencyBonus': '@dynamic'} (resolve manually; log follow-ups via apply.py)
- G1 — Mortimer placed moholearea on 32 [E4], +2 plants
- G1 — Plan patched (live): threats updated
- G1 — Maxwell played Earth Office (paid 1 MC) → balance 2 MC
  1. paid 1 MC (base 1)
- G1 — Executed plan step(s): 2a
- G1 — execute.py: 2a sent to the app, app-adopted
- G1 — Executed plan step(s): 2b
- G1 — execute.py: 2b sent to the app, app-adopted
- G1 — Production (end of gen 1): Maxwell +23 MC (TR 20 + prod 3), energy→heat (0+0 heat), opponents simulated. → Generation 2, first player Mortimer
- G2 — triage: handled #27, #28 — Gen-2 turnover, Mortimer first player. Research resolved and full gen-2 plan composed in the same turn.
- G2 — Hand +['Geothermal Power', 'Solar Wind Power'] → ['Callisto Penal Mines', 'Hackers', 'Rad-Suits', 'Geothermal Power', 'Solar Wind Power']
- G2 — Maxwell: -6 MC → 19
- G2 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b
- G2 — Mortimer played Towing A Comet (~−23 MC → ~1)
  1. paid 23 MC (base 23)
  2. PLANTS 7 → 9
  3. oxygen 0% → 1% → TR 21
  4. oceans 0 → 1 → TR 22
  5. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
- G2 — Mortimer placed ocean on 33 [E5], +2 plants
- G2 — Mortimer: spent 7 plants → greenery, oxygen 1% → 2%, TR → 23 (Convert Plants standard action)
- G2 — Mortimer placed greenery on 41 [F4], +1 plants, +2 MC (1 adjacent ocean)
- G2 — Plan patched (draft): threats updated — triggered by feed #32, #34, #37
- G2 — Draft plan PROMOTED (re-simulated clean against current state)
- G2 — Maxwell played Geothermal Power (paid 3 MC + 4 steel) → balance 16 MC
  1. paid 3 MC (base 11)
  2. ENERGY production 0 → 2
- G2 — Executed plan step(s): 1a
- G2 — execute.py: 1a sent to the app, app-adopted
- G2 — Maxwell played Hackers (paid 3 MC) → balance 13 MC
  1. paid 3 MC (base 3)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. ENERGY production 2 → 1
  4. MC production 3 → 5
- G2 — Executed plan step(s): 1b
- G2 — execute.py: 1b sent to the app, app-adopted
- G2 — Observed Mortimer mat (gen 2), drift: MC prod -2 (sim 0 → obs -2)
- G2 — Mortimer played Energy Tapping (~−3 MC → ~0)
  1. paid 3 MC (base 3)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
- G2 — Maxwell: -1 ENERGY production → 0
- G2 — Mortimer: +1 ENERGY production → 1
- G2 — triage: handled #47 — Energy Tapping took my energy prod 1->0. Plan stands: step 2a (Solar Wind Power) ADDS energy prod from zero, it does not require an existing step, so nothing is blocked. Noted for the KB though — he now holds energy-steal, so any future single-source energy engine of mine is stealable [02 TR engines: a stealable single input needs its second source bought BEFORE the attack].
- G2 — Maxwell played Solar Wind Power (paid 11 MC) → balance 2 MC
  1. paid 11 MC (base 11)
  2. ENERGY production 0 → 1
  3. TITANIUM 0 → 2
- G2 — Executed plan step(s): 2a
- G2 — execute.py: 2a sent to the app, app-adopted
- G2 — Executed plan step(s): 2b
- G2 — execute.py: 2b sent to the app, app-adopted
- G2 — Production (end of gen 2): Maxwell +25 MC (TR 20 + prod 5), energy→heat (0+0 heat), opponents simulated. → Generation 3, first player Maxwell
- G3 — Hand +['Ore Processor', 'Lagrange Observatory'] → ['Callisto Penal Mines', 'Rad-Suits', 'Ore Processor', 'Lagrange Observatory']
- G3 — Maxwell: -6 MC → 21
- G3 — triage: handled #53, #54 — Gen-3 turnover, I am first player. Research resolved (Ore Processor + Lagrange Observatory); full gen-3 plan composed in the same turn.
- G3 — Plan set: 1a, 1b
- G3 — Maxwell played Callisto Penal Mines (paid 18 MC + 2 Ti) → balance 3 MC
  1. paid 18 MC (base 24)
  2. MC production 5 → 8
- G3 — Executed plan step(s): 1a
- G3 — execute.py: 1a sent to the app, app-adopted
- G3 — Executed plan step(s): 1b
- G3 — execute.py: 1b sent to the app, app-adopted
- G3 — Mortimer: research kept 1 cards (−3 MC → 18)
- G3 — Mortimer played Noctis City (~−18 MC → ~0)
  1. paid 18 MC (base 18)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. MC production -2 → 1
- G3 — Mortimer placed city on 31 [E3] (Noctis City), +2 plants
- G3 — Mortimer: tiles.cities corrected 0 → 1
- G3 — Mortimer: -1 ENERGY production → 0
- G3 — Mortimer: spent 7 plants → greenery, oxygen 2% → 3%, TR → 24 (Convert Plants standard action)
- G3 — Mortimer placed greenery on 40 [F3], +1 plants
- G3 — Mortimer: spent 8 heat, temperature -30°C → -28°C, TR → 25 (Convert Heat standard action)
- G3 — Production (end of gen 3): Maxwell +28 MC (TR 20 + prod 8), energy→heat (1+0 heat), opponents simulated. → Generation 4, first player Mortimer
- G4 — Hand +['Small Animals', 'Algae'] → ['Rad-Suits', 'Ore Processor', 'Lagrange Observatory', 'Small Animals', 'Algae']
- G4 — Maxwell: -6 MC → 25
- G4 — triage: handled #64, #66, #67, #69, #71, #72 — Gen-4 turnover, Mortimer first player. Full re-plan supersedes these: Gardener 2/3 is conceded (I have no plant source and cannot contest 3 greeneries); the 9-plant asteroid-target flag stands unanswered because 12 offered cards have contained no removal I could play — Small Animals just bought is the answer and needs 6% O2 (now 3%). Clock re-read below.
- G4 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b
- G4 — Mortimer: research kept 2 cards (−6 MC → 20)
- G4 — Mortimer played Research Outpost (~−18 MC → ~2)
  1. paid 18 MC (base 18)
  2. city tile → TABLE: place it (not adjacent to a city)
- G4 — Mortimer placed city on 03 [A1], +2 steel
- G4 — triage: handled #76, #77 — Mayor 2/3 for Mortimer (Noctis 31 + Research Outpost 03), and he is also Gardener 2/3. MILESTONE SQUEEZE: 3 slots exist; if he takes Gardener and Mayor only one remains and Builder must be mine before he finds a third. I am 5 of 8 building tags after 2a and need 3 more — building-tag cards are now the joint #1 research priority alongside energy production. Plan otherwise stands; he has already PASSED gen 4, so the rest of this generation is uncontested.
- G4 — Draft plan PROMOTED (re-simulated clean against current state)
- G4 — Maxwell played Lagrange Observatory (paid 9 MC) → balance 16 MC
  1. paid 9 MC (base 9)
  2. → TABLE: draw 1 card(s) — log with `apply.py hand add <card>`
- G4 — Executed plan step(s): 1a
- G4 — Hand +['Fuel Factory'] → ['Rad-Suits', 'Ore Processor', 'Small Animals', 'Algae', 'Fuel Factory']
- G4 — execute.py: 1a sent to the app, app-adopted
- G4 — Plan patched (live): replaced 2a; replaced 2b; threats updated
- G4 — Maxwell played Rad-Suits (paid 6 MC) → balance 10 MC
  1. paid 6 MC (base 6)
  2. MC production 8 → 9
- G4 — Executed plan step(s): 1b
- G4 — execute.py: 1b sent to the app, app-adopted
- G4 — Maxwell played Fuel Factory (paid 0 MC + 3 steel) → balance 10 MC
  1. paid 0 MC (base 6)
  2. ENERGY production 1 → 0
  3. MC production 9 → 10
  4. TITANIUM production 0 → 1
- G4 — Executed plan step(s): 2a
- G4 — execute.py: 2a sent to the app, app-adopted
- G4 — Executed plan step(s): 2b
- G4 — execute.py: 2b sent to the app, app-adopted
- G4 — Hand +['Fuel Factory'] → ['Ore Processor', 'Small Animals', 'Algae', 'Fuel Factory']
- G4 — Production (end of gen 4): Maxwell +30 MC (TR 20 + prod 10), energy→heat (1+0 heat), opponents simulated. → Generation 5, first player Maxwell
- G5 — Hand −'Fuel Factory' → ['Ore Processor', 'Small Animals', 'Algae']
- G5 — Hand +['Advanced Alloys', 'Designed Microorganisms', 'Soil Factory'] → ['Ore Processor', 'Small Animals', 'Algae', 'Advanced Alloys', 'Designed Microorganisms', 'Soil Factory']
- G5 — Maxwell: -9 MC → 31
- G5 — triage: handled #90, #91 — Gen-5 turnover, I am first player. Full re-plan; strategy pivots to the AWARD SWEEP (see threats).
- G5 — Plan set: 1a, 1b, 2a, 2b
- G5 — Maxwell played Advanced Alloys (paid 9 MC) → balance 22 MC
  1. paid 9 MC (base 9)
  2. → TABLE: steelValue = 1 (resolve manually; log follow-ups via apply.py)
  3. → TABLE: titanumValue = 1 (resolve manually; log follow-ups via apply.py)
- G5 — Executed plan step(s): 1a
- G5 — execute.py: 1a sent to the app, app-adopted
- G5 — Maxwell funded award Banker (−8 MC)
- G5 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'your marker on Banker, 22 MC down to 14')
- G5 — execute.py: 1b sent to the app, app-adopted
- G5 — Mortimer: research kept 1 cards (−3 MC → 25)
- G5 — Research: dealt ['Advanced Alloys', 'Designed Microorganisms', 'Soil Factory'], kept ['Advanced Alloys', 'Designed Microorganisms', 'Soil Factory'] (−9 MC → 5)
- G5 — Maxwell: +9 MC → 14
- G5 — Hand −'Designed Microorganisms' → ['Ore Processor', 'Small Animals', 'Algae', 'Soil Factory', 'Advanced Alloys', 'Designed Microorganisms', 'Soil Factory']
- G5 — Hand −'Soil Factory' → ['Ore Processor', 'Small Animals', 'Algae', 'Advanced Alloys', 'Designed Microorganisms', 'Soil Factory']
- G5 — Hand −'Advanced Alloys' → ['Ore Processor', 'Small Animals', 'Algae', 'Designed Microorganisms', 'Soil Factory']
- G5 — Mortimer: spent 7 plants → greenery, oxygen 3% → 4%, TR → 26 (Convert Plants standard action)
- G5 — Mortimer placed greenery on 39 [F2], +2 plants
- G5 — Mortimer played Business Contacts (~−6 MC → ~19)
  1. paid 6 MC (base 7, −1: Research Outpost −1)
  2. → TABLE: draw 4 card(s) — log with `apply.py hand add <card>`
- G5 — triage: handled #96, #98 — Banker funded (slot 2 now 14 MC). Oxygen 4% — Small Animals (6%) opens in ~2 more oxygen steps, which Mortimer himself supplies; it stays in hand until then. He now has 3 greeneries so Gardener is his to claim. Plan stands: 2a Ore Processor then pass at 10 MC. NEW BOARD PLAN for gens 6+: SP City on hex 60 (25 MC: +1 MC prod, +2 steel hex bonus, Mining Guild +1 steel prod, Mayor progress) makes hexes 54 and 59 adjacent to BOTH my cities, so each greenery placed there scores 4 VP (1 greenery + 2 city adjacency + 1 TR) — that is what Designed Microorganisms' +2 plant production feeds.
- G5 — Maxwell played Ore Processor (paid 7 MC + 3 steel) → balance 7 MC
  1. paid 7 MC (base 13)
  2. blue action registered: Spend 4 energy to gain 1 titanium and increase oxygen 1 step.
- G5 — Executed plan step(s): 2a
- G5 — execute.py: 2a sent to the app, app-adopted
- G5 — Executed plan step(s): 2b
- G5 — execute.py: 2b sent to the app, app-adopted
- G5 — Mortimer claimed milestone Gardener (−8 MC)
- G5 — Mortimer played Ecological Zone (~−11 MC → ~0)
  1. paid 11 MC (base 12, −1: Research Outpost −1)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
- G5 — Mortimer placed ecologicalzone on 42 [F5], +1 plants, +2 MC (1 adjacent ocean)
- G5 — Mortimer: tiles.special corrected 1 → 2
- G5 — Mortimer: card resources adopted from the app: Ecological Zone 0 → 2
- G5 — Mortimer: spent 8 heat, temperature -28°C → -26°C, TR → 27 (Convert Heat standard action)
- G5 — Production (end of gen 5): Maxwell +30 MC (TR 20 + prod 10), energy→heat (0+0 heat), opponents simulated. → Generation 6, first player Mortimer
- G6 — Hand +['Search For Life', 'Space Elevator'] → ['Small Animals', 'Algae', 'Designed Microorganisms', 'Soil Factory', 'Search For Life', 'Space Elevator']
- G6 — Maxwell: -6 MC → 31
- G6 — triage: handled #104, #110, #112, #113 — Mortimer claimed Gardener (5 VP), 2 milestone slots left. Temp -26; Designed Microorganisms' max -14C window still has 6 steps of room at his ~0.5 steps/gen, so it can wait one generation. Full re-plan below: the priority is consuming award slot 2 before he funds Landlord (7 tiles v my 1).
- G6 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b
- G6 — Mortimer: research kept 1 cards (−3 MC → 27)
- G6 — Mortimer played Imported Nitrogen (~−22 MC → ~5)
  1. paid 22 MC (base 23, −1: Research Outpost −1)
  2. PLANTS 5 → 9
  3. TR +1 → 28
- G6 — Mortimer: card resources adopted from the app: Ecological Zone 2 → 4
- G6 — Mortimer: spent 7 plants → greenery, oxygen 4% → 5%, TR → 29 (Convert Plants standard action)
- G6 — Mortimer placed greenery on 24 [D4], +1 plants, +2 MC (1 adjacent ocean)
- G6 — triage: handled #118, #120, #121 — Oxygen 5%: Search For Life (max 6%) is played THIS turn in step 1a before his next greenery closes it; Small Animals (min 6%) opens on his very next oxygen step. He also revealed Ecological Zone (animals, 1 VP per 2) and Imported Nitrogen — his VP is broadening beyond TR, which raises the value of consuming the award slots now. Landlord is his and unreachable for me (his 8 tiles v my 1); step 1b funds SCIENTIST, not Landlord. Plan stands.
- G6 — Draft plan PROMOTED (re-simulated clean against current state)
- G6 — Maxwell played Search For Life (paid 3 MC) → balance 28 MC
  1. paid 3 MC (base 3)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. blue action registered: Spend 1 M€ to reveal the top card of the draw deck. If that card has a microbe tag, add a science resource here.
- G6 — Executed plan step(s): 1a
- G6 — execute.py: 1a sent to the app, app-adopted
- G6 — Maxwell funded award Scientist (−14 MC)
- G6 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'your marker on Scientist, 28 MC down to 14')
- G6 — execute.py: 1b sent to the app, app-adopted
- G6 — Mortimer played GHG Producing Bacteria (~−7 MC → ~0)
  1. paid 7 MC (base 8, −1: Research Outpost −1)
- G6 — Mortimer used action GHG Producing Bacteria: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 1
- G6 — Maxwell: standard project power_plant, −11 MC, +1 energy production
- G6 — Executed plan step(s): 2a
- G6 — execute.py: 2a sent to the app, app-adopted
- G6 — triage: handled #125 — Scientist funded; last award slot now 20 MC and reserved for Miner (steel+titanium held: my metal prod 3/gen rising to 4 with Space Elevator, his zero). He is at 0 MC so he cannot take that slot this turn. Plan stands: pass at 3 MC into a 33 MC gen 7 that claims Builder.
- G6 — Executed plan step(s): 2b
- G6 — execute.py: 2b sent to the app, app-adopted
- G6 — Production (end of gen 6): Maxwell +30 MC (TR 20 + prod 10), energy→heat (0+0 heat), opponents simulated. → Generation 7, first player Maxwell
- G7 — Hand +['Mining Expedition'] → ['Small Animals', 'Algae', 'Designed Microorganisms', 'Soil Factory', 'Space Elevator', 'Mining Expedition']
- G7 — Maxwell: -3 MC → 30
- G7 — triage: handled #132, #133 — Gen-7 turnover, I am first player. Full re-plan: this is the Builder generation.
- G7 — Plan set: 1a, 1b, 2a, 2b
- G7 — Mortimer: research kept 2 cards (−6 MC → 24)
- G7 — Plan patched (live): replaced 1a; replaced 1b; replaced 2a; replaced 2b
- G7 — Maxwell played Space Elevator (paid 16 MC + 1 steel + 3 Ti) → balance 14 MC
  1. paid 16 MC (base 27)
  2. TITANIUM production 1 → 2
  3. blue action registered: Spend 1 steel to gain 5 M€.
- G7 — Executed plan step(s): 1a
- G7 — execute.py: 1a sent to the app, app-adopted
- G7 — Maxwell played Soil Factory (paid 3 MC + 3 steel) → balance 11 MC
  1. paid 3 MC (base 9)
  2. ENERGY production 1 → 0
  3. PLANTS production 0 → 1
- G7 — Executed plan step(s): 1b
- G7 — execute.py: 1b sent to the app, app-adopted
- G7 — Mortimer: spent 8 heat, temperature -26°C → -24°C — track bonus: Mortimer +1 heat prod (→ 5), TR → 30 (Convert Heat standard action)
- G7 — Mortimer played Deep Well Heating (~−12 MC → ~16)
  1. paid 8 MC (base 13, −1: Research Outpost −1)
  2. ENERGY production 0 → 1
  3. temperature -24°C → -22°C → TR 31
  4. paid 2 steel
- G7 — Observed Mortimer mat (gen 7), drift: MC -4 (sim 16 → obs 12); STEEL +2 (sim 0 → obs 2)
- G7 — Maxwell claimed milestone Builder (−8 MC)
- G7 — Executed plan step(s): 2a (cue confirmed by the player — 'app-adopted': 2a 'your marker on Builder, 11 MC down to 3')
- G7 — execute.py: 2a sent to the app, app-adopted
- G7 — triage: handled #142, #144 — BUILDER CLAIMED (+5 VP); milestones 1-1, one slot left and he needs TR 35 for Terraformer from 29. He took TWO temperature steps this generation (Deep Well Heating + heat conversion), temp now -22: Designed Microorganisms' max -14C window has only 4 steps left at his new ~2/gen rate, so it is the FIRST play of gen 8, ahead of Mining Expedition. He also gained 1 energy production and 1 heat production. Plan stands; passing at 3 MC.
- G7 — Executed plan step(s): 2b
- G7 — execute.py: 2b sent to the app, app-adopted
- G7 — Mortimer used action GHG Producing Bacteria: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 2
- G7 — Production (end of gen 7): Maxwell +30 MC (TR 20 + prod 10), energy→heat (1+0 heat), opponents simulated. → Generation 8, first player Mortimer
- G8 — Hand +['Indentured Workers', 'Interstellar Colony Ship'] → ['Small Animals', 'Algae', 'Designed Microorganisms', 'Mining Expedition', 'Indentured Workers', 'Interstellar Colony Ship']
- G8 — Maxwell: -6 MC → 27
- G8 — triage: handled #146, #151, #152 — Builder claimed; milestones 1-1, one slot left (he needs TR 35 from 31 for Terraformer — now genuinely close, watch it). Gen-8 re-plan: he holds 44 MC, enough to fund the LAST award slot for Landlord, so Miner is funded this turn before he can.
- G8 — Draft plan set (speculative — promote before executing): 1a, 1b
- G8 — Mortimer: research kept 2 cards (−6 MC → 38)
- G8 — Mortimer played Immigrant City (~−12 MC → ~30)
  1. paid 8 MC (base 13, −1: Research Outpost −1)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. ENERGY production 1 → 0
  4. MC production 1 → -1
  5. city tile → TABLE: place it (not adjacent to a city)
  6. paid 2 steel
  7. Immigrant City (Mortimer): +1 MC production → 0 (city placed)
- G8 — Mortimer placed city on 25 [D5], +2 plants, +2 MC (1 adjacent ocean)
- G8 — Mortimer: +1 ENERGY production → 1
- G8 — Mortimer: +2 MC production → 2
- G8 — Mortimer claimed milestone Mayor (−8 MC)
- G8 — Observed Mortimer mat (gen 8), drift: MC prod -2 (sim 2 → obs 0); ENERGY prod -1 (sim 1 → obs 0)
- G8 — triage: handled #156, #157, #158, #160, #161 — Mortimer claimed MAYOR — 0 milestone slots left, final 10-5 to him. Upside: Terraformer is now unreachable for him, which is precisely what claiming Builder a generation early bought. He also placed a 3rd city (Landlord further out of reach) and moved MC production. Plan unchanged and now more urgent: fund MINER, the last award slot, this action.
- G8 — Draft plan PROMOTED (re-simulated clean against current state)
- G8 — Maxwell funded award Miner (−20 MC)
- G8 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'your marker on Miner, 27 MC down to 7')
- G8 — execute.py: 1a sent to the app, app-adopted
- G8 — Plan patched (live): replaced 1b; inserted 2a, 2b, 3a after 1a
- G8 — Action used: Space Elevator ✓: −1 steel → 1, MC 7 → 12
- G8 — Executed plan step(s): 2a
- G8 — execute.py: 2a sent to the app, app-adopted
- G8 — Mortimer played Protected Valley (~−22 MC → ~2)
  1. paid 22 MC (base 23, −1: Research Outpost −1)
  2. MC production 0 → 2
  3. greenery tile, oxygen 5% → 6% → TR 32
  4. → TABLE: place the greenery (adjacent to your tiles)
- G8 — Mortimer placed greenery on 34 [E6], +2 plants, +2 MC (1 adjacent ocean)
- G8 — Mortimer: card resources adopted from the app: Ecological Zone 4 → 5
- G8 — Mortimer: spent 7 plants → greenery, oxygen 6% → 7%, TR → 33 (Convert Plants standard action)
- G8 — Mortimer placed greenery on 23 [D3], +1 plants
- G8 — Maxwell played Indentured Workers (paid 0 MC) → balance 12 MC
  1. paid 0 MC (base 0)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. Indentured Workers: next card Maxwell plays this generation costs 8 MC less
- G8 — Executed plan step(s): 2b
- G8 — execute.py: 2b sent to the app, app-adopted
- G8 — Maxwell played Designed Microorganisms (paid 8 MC) → balance 4 MC
  1. paid 8 MC (base 16) — --cost 8 override (auto-discounts skipped)
  2. PLANTS production 1 → 3
- G8 — Executed plan step(s): 3a
- G8 — execute.py: 3a sent to the app, app-adopted
- G8 — Plan patched (live): replaced 1b; inserted 3b after 3a
- G8 — triage: handled #162, #168, #169, #172 — Oxygen 7% (he placed two more greeneries): Small Animals is legal from gen 9 — it leads that generation. He holds 11 plants; Mining Expedition (removes 2) is the follow-up. All award and milestone slots now resolved.
- G8 — Mortimer used action GHG Producing Bacteria: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 3
- G8 — Action used: Search For Life ✓: −1 mc → 3
- G8 — Executed plan step(s): 3b
- G8 — execute.py: 3b sent to the app, app-adopted
- G8 — Executed plan step(s): 1b
- G8 — execute.py: 1b sent to the app, app-adopted
- G8 — Production (end of gen 8): Maxwell +30 MC (TR 20 + prod 10), energy→heat (0+0 heat), opponents simulated. → Generation 9, first player Maxwell
- G9 — Hand +['Dust Seals', 'Technology Demonstration'] → ['Small Animals', 'Algae', 'Mining Expedition', 'Interstellar Colony Ship', 'Dust Seals', 'Technology Demonstration']
- G9 — Maxwell: -6 MC → 27
- G9 — triage: handled #183, #184 — Gen-9 turnover, I am first player. Full re-plan: conversion phase begins.
- G9 — Plan set: 1a, 1b, 2a, 2b, 3a
- G9 — Maxwell played Small Animals (paid 6 MC) → balance 21 MC
  1. paid 6 MC (base 6)
  2. Small Animals: Mortimer −1 plants production → 1
  3. blue action registered: Add 1 animal to this card.
- G9 — Executed plan step(s): 1a
- G9 — execute.py: 1a sent to the app, app-adopted
- G9 — Maxwell played Interstellar Colony Ship (paid 9 MC + 4 Ti) → balance 12 MC
  1. paid 9 MC (base 24, −3: Earth Office −3)
- G9 — Executed plan step(s): 1b
- G9 — execute.py: 1b sent to the app, app-adopted
- G9 — Mortimer: research kept 3 cards (−9 MC → 30)
- G9 — Mortimer used action GHG Producing Bacteria: or-choice 1 = Remove 2 microbes to raise temperature 1 step, −2 microbe on GHG Producing Bacteria → 1, temperature -22°C → -20°C — track bonus: Mortimer +1 heat prod (→ 6) → TR 34
- G9 — Mortimer played Lava Flows (~−17 MC → ~13)
  1. paid 17 MC (base 18, −1: Research Outpost −1)
  2. temperature -20°C → -18°C → TR 35
  3. temperature -18°C → -16°C → TR 36
  4. special tile → TABLE: place it
  5. → TABLE: tile = {'type': 'lavaflows', 'on': 'volcanic', 'title': 'Select either Tharsis Tholus, Ascraeus Mons, Pavonis Mons or Arsia Mons', 'adjacencyBonus': '@dynamic'} (resolve manually; log follow-ups via apply.py)
- G9 — Mortimer placed lavaflows on 29 [E1] (Arsia Mons), +2 plants
- G9 — Maxwell played Dust Seals (paid 2 MC) → balance 10 MC
  1. paid 2 MC (base 2)
- G9 — Executed plan step(s): 2a
- G9 — execute.py: 2a sent to the app, app-adopted
- G9 — Maxwell played Technology Demonstration (paid 5 MC) → balance 5 MC
  1. paid 5 MC (base 5)
  2. → TABLE: draw 2 card(s) — log with `apply.py hand add <card>`
- G9 — Executed plan step(s): 2b
- G9 — Hand +['Building Industries', 'Tundra Farming'] → ['Algae', 'Mining Expedition', 'Building Industries', 'Tundra Farming']
- G9 — execute.py: 2b sent to the app, app-adopted
- G9 — Plan patched (live): replaced 3a; inserted 3b after 3a
- G9 — Action used: Search For Life ✓: −1 mc → 4
- G9 — Executed plan step(s): 3a
- G9 — Sync: temperature = -14°C
- G9 — execute.py: 3a sent to the app, app-adopted
- G9 — Plan patched (live): replaced 3b; inserted 4a after 3b — triggered by feed #196
- G9 — Action used: Small Animals ✓: Small Animals: +1 animal on the card → 1
- G9 — Executed plan step(s): 3b
- G9 — execute.py: 3b sent to the app, app-adopted
- G9 — execute.py: pass with 1 available action(s) OVERRIDDEN: 4 MC left and every repeatable action is spent this generation — Space Elevator (2a), Search For Life (3a) and Small Animals (3b). Building Industries needs 1 energy production and I have 0. Tundra Farming needs -6C against -14 now. Mining Expedition (12) leads gen 10 on ~34 MC with the second city on hex 60. Algae needs 5 oceans (now 1). Plants 4 at +3/gen, first FREE greenery in gen 11. No standard project is reachable at 4 MC. All milestones and awards resolved.
- G9 — Mortimer: spent 8 heat, temperature -14°C → -12°C, TR → 37 (Convert Heat standard action)
- G9 — Mortimer played Insects (~−8 MC → ~5)
  1. paid 8 MC (base 9, −1: Research Outpost −1)
  2. plants production: own plant tags incl. this: 3
  3. PLANTS production 1 → 4
- G9 — Sync: temperature = -14°C
- G9 — Mortimer: spent 7 plants → greenery, oxygen 7% → 8% — 8% O2 track bonus: free temperature step, temperature -14°C → -12°C, Mortimer +1 TR, TR → 39 (Convert Plants standard action)
- G9 — Mortimer placed greenery on 30 [E2], +2 plants
- G9 — execute.py: pass with 1 available action(s) OVERRIDDEN: 4 MC left and every repeatable action is spent this generation — Space Elevator (2a), Search For Life (3a) and Small Animals (3b). Building Industries needs 1 energy production and I have 0. Tundra Farming needs -6C against -14 now. Mining Expedition (12) leads gen 10 on ~34 MC with the second city on hex 60. Algae needs 5 oceans (now 1). Plants 4 at +3/gen, first FREE greenery in gen 11. No standard project is reachable at 4 MC. All milestones and awards resolved.
- G9 — Executed plan step(s): 4a
- G9 — execute.py: 4a sent to the app, app-adopted
- G9 — Production (end of gen 9): Maxwell +30 MC (TR 20 + prod 10), energy→heat (0+0 heat), opponents simulated. → Generation 10, first player Mortimer
- G10 — Hand +['Ice Asteroid', 'Windmills'] → ['Algae', 'Mining Expedition', 'Building Industries', 'Tundra Farming', 'Ice Asteroid', 'Windmills']
- G10 — Maxwell: -6 MC → 28
- G10 — Mortimer: research kept 1 cards (−3 MC → 43)
- G10 — Mortimer: spent 7 plants → greenery, oxygen 8% → 9%, TR → 40 (Convert Plants standard action)
- G10 — Mortimer placed greenery on 22 [D2], +1 plants
- G10 — Mortimer played Extreme-Cold Fungus (~−12 MC → ~31)
  1. paid 12 MC (base 13, −1: Research Outpost −1)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
- G10 — Plan set: 1a, 1b, 2a, 2b, 3a
- G10 — Maxwell played Windmills (paid 0 MC + 3 steel) → balance 28 MC
  1. paid 0 MC (base 6)
  2. ENERGY production 0 → 1
- G10 — Executed plan step(s): 1a
- G10 — execute.py: 1a sent to the app, app-adopted
- G10 — Maxwell played Ice Asteroid (paid 17 MC + 2 Ti) → balance 11 MC
  1. paid 17 MC (base 23)
  2. oceans 1 → 2 → TR 21
  3. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  4. oceans 2 → 3 → TR 22
  5. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
- G10 — Maxwell placed ocean on 28 [D8], +2 plants
- G10 — Maxwell placed ocean on 13 [B6], → TABLE: +2 card (draw/track manually)
- G10 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'two new blue ocean tiles on hexes 28 and 13, TR 22, plants 9')
- G10 — Hand +['Heat Trappers', 'Acquired Company'] → ['Algae', 'Mining Expedition', 'Building Industries', 'Tundra Farming', 'Heat Trappers', 'Acquired Company']
- G10 — execute.py resolve: 1b follow-up answered, app-adopted
- G10 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 1 → 3
- G10 — Mortimer used action GHG Producing Bacteria: or-choice 1 = Remove 2 microbes to raise temperature 1 step, −2 microbe on GHG Producing Bacteria → 1, temperature -12°C → -10°C → TR 41
- G10 — Maxwell: spent 8 plants → greenery, oxygen 9% → 10%, TR → 23 (Convert Plants standard action)
- G10 — Maxwell placed greenery on 59 [I1, app J1], +1 steel, Mining Guild: +1 steel production
- G10 — Executed plan step(s): 2a (cue confirmed by the player — 'app-adopted': 2a 'red greenery on hex 59, plants down to 1, oxygen up one step')
- G10 — execute.py: 2a sent to the app, app-adopted
- G10 — Action used: Small Animals ✓: Small Animals: +1 animal on the card → 2
- G10 — Executed plan step(s): 2b
- G10 — execute.py: 2b sent to the app, app-adopted
- G10 — Plan patched (live): replaced 3a; inserted 3a0 after 2b
- G10 — Maxwell played Acquired Company (paid 7 MC) → balance 4 MC
  1. paid 7 MC (base 10, −3: Earth Office −3)
  2. MC production 10 → 13
- G10 — Executed plan step(s): 3a0
- G10 — Sync: oceans = 4
- G10 — TILE LOCATION: nobody ocean added on 43 [app]
- G10 — execute.py: 3a0 sent to the app, app-adopted
- G10 — execute.py: 5 unhandled trigger(s) OVERRIDDEN: 4 MC left. Space Elevator's action (1 steel -> 5 MC) is declined deliberately: 5 MC does not reach anything this generation (Mining Expedition 12, SP asteroid 14), and the steel is worth more next generation when 5 MC completes a purchase. Every other repeatable action (Small Animals, Search For Life) is already spent, and no card in hand is legal or affordable.
- G10 — execute.py: pass with 1 available action(s) OVERRIDDEN: 4 MC left. Space Elevator's action (1 steel -> 5 MC) is declined deliberately: 5 MC does not reach anything this generation (Mining Expedition 12, SP asteroid 14), and the steel is worth more next generation when 5 MC completes a purchase. Every other repeatable action (Small Animals, Search For Life) is already spent, and no card in hand is legal or affordable.
- G10 — Executed plan step(s): 3a
- G10 — execute.py: 3a sent to the app, app-adopted
- G10 — Mortimer played Local Heat Trapping (~−0 MC → ~31)
  1. paid 0 MC (base 1, −1: Research Outpost −1)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. −5 heat → 5
- G10 — Mortimer: +4 PLANTS → 6
- G10 — Mortimer played Convoy From Europa (~−14 MC → ~17)
  1. paid 14 MC (base 15, −1: Research Outpost −1)
  2. oceans 4 → 5 → TR 42
  3. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  4. → TABLE: draw 1 card(s) — log with `apply.py hand add <card>`
- G10 — Mortimer: +1 PLANTS → 7
- G10 — Sync: oceans = 4
- G10 — Mortimer: spent 7 plants → greenery, oxygen 10% → 11%, TR → 43 (Convert Plants standard action)
- G10 — Mortimer placed greenery on 26 [D6], +1 plants
- G10 — Mortimer played Noctis Farming (~−9 MC → ~8)
  1. paid 9 MC (base 10, −1: Research Outpost −1)
  2. MC production 2 → 3
  3. PLANTS 1 → 3
- G10 — Mortimer: card resources adopted from the app: Ecological Zone 5 → 6
- G10 — Production (end of gen 10): Maxwell +36 MC (TR 23 + prod 13), energy→heat (0+0 heat), opponents simulated. → Generation 11, first player Maxwell
- G11 — Hand +['Release of Inert Gases'] → ['Algae', 'Mining Expedition', 'Building Industries', 'Tundra Farming', 'Heat Trappers', 'Release of Inert Gases']
- G11 — Maxwell: -3 MC → 37
- G11 — Plan set: 1a, 1b, 2a, 2b, 3a, 3b
- G11 — Mortimer: research kept 2 cards (−6 MC → 48)
- G11 — Action used: Space Elevator ✓: −1 steel → 5, MC 37 → 42
- G11 — Executed plan step(s): 1a
- G11 — execute.py: 1a sent to the app, app-adopted
- G11 — Maxwell played Release of Inert Gases (paid 14 MC) → balance 28 MC
  1. paid 14 MC (base 14)
  2. TR +2 → 25
- G11 — Executed plan step(s): 1b
- G11 — execute.py: 1b sent to the app, app-adopted
- G11 — Plan patched (live): threats updated — triggered by feed #194, #201, #209, #244, #245, #250, #257, #258
- G11 — Maxwell: standard project greenery, −23 MC, greenery tile, oxygen 11% → 12%
- G11 — Maxwell placed greenery on 54 [H2]
- G11 — Executed plan step(s): 2a (cue confirmed by the player — 'app-adopted': 2a 'red greenery on hex 54, MC down to 5, oxygen up one step')
- G11 — Sync: temperature = -8°C
- G11 — execute.py: 2a sent to the app, app-adopted
- G11 — Action used: Small Animals ✓: Small Animals: +1 animal on the card → 3
- G11 — Executed plan step(s): 2b
- G11 — execute.py: 2b sent to the app, app-adopted
- G11 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 1 → 3
- G11 — Mortimer used action GHG Producing Bacteria: or-choice 1 = Remove 2 microbes to raise temperature 1 step, −2 microbe on GHG Producing Bacteria → 1, temperature -8°C → -6°C → TR 44
- G11 — Sync: temperature = -8°C
- G11 — Mortimer played Comet (~−20 MC → ~28)
  1. paid 20 MC (base 21, −1: Research Outpost −1)
  2. temperature -8°C → -6°C → TR 45
  3. oceans 4 → 5 → TR 46
  4. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  5. → TABLE: Comet: remove up to 3 plants from any player (log with --target <player>, or apply.py attack)
- G11 — Mortimer placed ocean on 44 [F7], +1 plants, +2 MC (1 adjacent ocean)
- G11 — ATTACK on Maxwell: -3 plants → 1, by Mortimer
- G11 — Mortimer: spent 8 heat, temperature -6°C → -4°C, TR → 47 (Convert Heat standard action)
- G11 — Action used: Search For Life ✓: −1 mc → 4
- G11 — Executed plan step(s): 3a
- G11 — execute.py: 3a sent to the app, app-adopted
- G11 — Executed plan step(s): 3b
- G11 — execute.py: 3b sent to the app, app-adopted
- G11 — Mortimer: spent 7 plants → greenery, oxygen 12% → 13%, TR → 48 (Convert Plants standard action)
- G11 — Mortimer placed greenery on 17 [C4]
- G11 — Mortimer played Investment Loan (~−2 MC → ~38)
  1. paid 2 MC (base 3, −1: Research Outpost −1)
  2. MC production 3 → 2
  3. MC 30 → 40
- G11 — Mortimer: standard project aquifer, −18 MC, oceans 5 → 6
- G11 — Mortimer placed ocean on 45 [F8], +1 plants, +2 MC (1 adjacent ocean)
- G11 — Mortimer: standard project asteroid, −14 MC, temperature -4°C → -2°C
- G11 — Production (end of gen 11): Maxwell +39 MC (TR 26 + prod 13), energy→heat (1+0 heat), opponents simulated. → Generation 12, first player Mortimer
- G12 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a, 3b
- G12 — Mortimer: research kept 2 cards (−6 MC → 54)
- G12 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 1 → 3
- G12 — Mortimer used action GHG Producing Bacteria: or-choice 1 = Remove 2 microbes to raise temperature 1 step, −2 microbe on GHG Producing Bacteria → 1, temperature -2°C → 0°C — BONUS OCEAN from the temperature track: Mortimer places an ocean now (log place + raise oceans events) → TR 51
- G12 — Mortimer placed ocean on 04 [A2], +2 steel
- G12 — Mortimer: oceans 6 → 7, TR → 52
- G12 — Draft plan PROMOTED (re-simulated clean against current state)
- G12 — Action used: Space Elevator ✓: −1 steel → 7, MC 43 → 48
- G12 — Executed plan step(s): 1a
- G12 — execute.py: 1a sent to the app, app-adopted
- G12 — Maxwell: standard project greenery, −23 MC, greenery tile, oxygen 13% → 14%
- G12 — Maxwell placed greenery on 47 [G2]
- G12 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'red greenery on hex 47, oxygen at maximum, TR 27, MC down to 25')
- G12 — execute.py: 1b sent to the app, app-adopted
- G12 — Mortimer played Giant Ice Asteroid (~−35 MC → ~19)
  1. paid 35 MC (base 36, −1: Research Outpost −1)
  2. temperature 0°C → 2°C → TR 53
  3. temperature 2°C → 4°C → TR 54
  4. oceans 7 → 8 → TR 55
  5. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  6. oceans 8 → 9 → TR 56
  7. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  8. → TABLE: Giant Ice Asteroid: remove up to 6 plants from any player (log with --target <player>, or apply.py attack)
- G12 — Mortimer placed ocean on 06 [A4], +1 card (drawn, hidden)
- G12 — Sync: oceans = 8
- G12 — Observed Mortimer mat (gen 12), drift: TR -1 (sim 56 → obs 55)
- G12 — Mortimer placed ocean on 07 [A5], +4 MC (2 adjacent ocean)
- G12 — Mortimer: oceans 8 → 9, TR → 56
- G12 — ATTACK on Maxwell: -4 plants → 0, by Mortimer
- G12 — Mortimer: spent 8 heat, temperature 4°C → 6°C, TR → 57 (Convert Heat standard action)
- G12 — Maxwell played Tundra Farming (paid 16 MC) → balance 9 MC
  1. paid 16 MC (base 16)
  2. PLANTS production 3 → 4
  3. MC production 13 → 15
  4. PLANTS 0 → 1
- G12 — Executed plan step(s): 2a
- G12 — execute.py: 2a sent to the app, app-adopted
- G12 — Action used: Small Animals ✓: Small Animals: +1 animal on the card → 4
- G12 — Executed plan step(s): 2b
- G12 — execute.py: 2b sent to the app, app-adopted
- G12 — Mortimer: standard project asteroid, −14 MC, temperature 6°C → 8°C
- G12 — Action used: Search For Life ✓: −1 mc → 8
- G12 — Executed plan step(s): 3a
- G12 — execute.py: 3a sent to the app, app-adopted
- G12 — Executed plan step(s): 3b
- G12 — Maxwell: +42 MC → 50
- G12 — Maxwell: +3 STEEL → 10
- G12 — Maxwell: +2 TITANIUM → 6
- G12 — Maxwell: +4 PLANTS → 5
- G12 — Maxwell: +1 HEAT → 5
- G12 — execute.py: 3b sent to the app, app-adopted
- G12 — Production (end of gen 12): Maxwell +42 MC (TR 27 + prod 15), energy→heat (1+0 heat), opponents simulated. → Generation 13, first player Maxwell
- G13 — Maxwell: -42 MC → 50
- G13 — Maxwell: -3 STEEL → 10
- G13 — Maxwell: -2 TITANIUM → 6
- G13 — Maxwell: -4 PLANTS → 5
- G13 — Maxwell: -1 HEAT → 5
- G13 — Mortimer placed greenery on 09 [B2] (Tharsis Tholus), +1 steel, +2 MC (1 adjacent ocean)
- G13 — Mortimer: tiles.greeneries corrected 10 → 11
- G13 — Observed Mortimer mat (gen 13), drift: PLANTS -7 (sim 10 → obs 3)
- Game ended 2026-08-29 — Mortimer (Ecoline, human/opponent seat) WON 92-66 vs Maxwell (Mining Guild, advisor). 12 generations, app-online full-API autopilot, 2p Corporate Era Tharsis, no draft. Advisor swept all 3 awards 15-0 and won card VP 13-3, but lost TR 27-58 and tile VP 6-21: no terraforming engine was ever built and the first greenery landed in gen 10.
