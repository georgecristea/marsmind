# Game log

- G1 — judgment executor: assist → auto
- G1 — Maxwell is Mining Guild (start 30 MC → 30), +5 steel, +1 steel prod
- G1 — Maxwell: research kept 5 cards (−15 MC → 15)
- G1 — Mortimer is Ecoline (start 36 MC → 36), +3 plants, +2 plants prod
- G1 — Mortimer: -12 MC → 24
- G1 — Hand +['Mohole Area', 'Energy Tapping', 'Noctis City', 'Towing A Comet'] → ['Mohole Area', 'Energy Tapping', 'Noctis City', 'Towing A Comet']
- G1 — Draft plan set (speculative — promote before executing): 1a, 2a, 3a
- G1 — Plan patched (draft): no step changes (plan stands) — triggered by feed #1, #3
- G1 — Maxwell: standard project power_plant, −11 MC, +1 energy production
- G1 — Maxwell played Corporate Stronghold (~−11 MC → ~3)
  1. paid 1 MC (base 11)
  2. ENERGY production 1 → 0
  3. MC production 0 → 3
  4. city tile → TABLE: place it (not adjacent to a city)
  5. paid 5 steel
- G1 — Maxwell: tiles.cities corrected 1 → 0
- G1 — Maxwell placed city on 53 [H1], +2 steel, Mining Guild: +1 steel production
- G1 — Maxwell: tiles.cities corrected 0 → 1
- G1 — Plan patched (draft): removed 2a; threats updated
- G1 — Draft plan PROMOTED (re-simulated clean against current state)
- G1 — Mortimer played Mohole Area (paid 20 MC) → balance 4 MC
  1. paid 20 MC (base 20) — --cost 20 override (auto-discounts skipped)
  2. HEAT production 0 → 4
  3. special tile → TABLE: place it
  4. → TABLE: tile = {'type': 'moholearea', 'on': 'ocean', 'adjacencyBonus': '@dynamic'} (resolve manually; log follow-ups via apply.py)
- G1 — Mortimer placed moholearea on 32 [E4], +2 plants
- G1 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'blue Mohole Area tile sits on app hex E4 (internal 32); Mortimer shows 4 heat production and 5 plants')
- G1 — execute.py: 1a sent to the app, app-adopted
- G1 — Maxwell played Earth Office (~−1 MC → ~2)
  1. paid 1 MC (base 1)
- G1 — Executed plan step(s): 3a
- G1 — execute.py: 3a sent to the app, app-adopted
- G1 — Production (end of gen 1): Mortimer +20 MC (TR 20 + prod 0), energy→heat (0+4 heat), opponents simulated. → Generation 2, first player Mortimer
- G2 — Research: dealt ['Aerobraked Ammonia Asteroid', 'Vesta Shipyard', 'Mass Converter', 'Soletta'], kept [] (−0 MC → 24)
- G2 — Hand reordered → ['Towing A Comet', 'Energy Tapping', 'Noctis City']
- G2 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 3a
- G2 — Plan patched (draft): no step changes (plan stands) — triggered by feed #27, #28
- G2 — Maxwell: research kept 2 cards (−6 MC → 19)
- G2 — Draft plan PROMOTED (re-simulated clean against current state)
- G2 — Mortimer played Towing A Comet (paid 23 MC) → balance 1 MC
  1. paid 23 MC (base 23) — --cost 23 override (auto-discounts skipped)
  2. PLANTS 7 → 9
  3. oxygen 0% → 1% → TR 21
  4. oceans 0 → 1 → TR 22
  5. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
- G2 — Mortimer placed ocean on 33 [E5], +2 plants
- G2 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'blue ocean tile sits on app hex E5 (internal 33); Mortimer shows 1 MC, 11 plants, TR 22, oxygen 1%, oceans 1')
- G2 — execute.py: 1a sent to the app, app-adopted
- G2 — Mortimer: spent 7 plants → greenery, oxygen 1% → 2%, TR → 23 (Convert Plants standard action)
- G2 — Mortimer placed greenery on 41 [F4], +1 plants, +2 MC (1 adjacent ocean)
- G2 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'blue greenery sits on app hex F4 (internal 41); Mortimer shows 3 MC, 5 plants, TR 23, oxygen 2%')
- G2 — execute.py: 1b sent to the app, app-adopted
- G2 — Maxwell played Geothermal Power (~−11 MC → ~16)
  1. paid 3 MC (base 11)
  2. ENERGY production 0 → 2
  3. paid 4 steel
- G2 — Maxwell played Hackers (~−3 MC → ~13)
  1. paid 3 MC (base 3)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. ENERGY production 2 → 1
  4. MC production 3 → 5
- G2 — Mortimer: -2 MC production → -2
- G2 — Maxwell: +2 MC production → 7
- G2 — Observed Maxwell mat (gen 2), drift: MC prod -2 (sim 7 → obs 5)
- G2 — Plan patched (live): threats updated — triggered by feed #44
- G2 — Mortimer played Energy Tapping (paid 3 MC) → balance 0 MC
  1. paid 3 MC (base 3) — --cost 3 override (auto-discounts skipped)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
- G2 — Executed plan step(s): 2a
- G2 — Mortimer: +1 ENERGY production → 1
- G2 — execute.py: 2a sent to the app, app-adopted
- G2 — Executed plan step(s): 3a
- G2 — execute.py: 3a sent to the app, app-adopted
- G2 — Observed Maxwell mat (gen 2), drift: ENERGY prod -1 (sim 1 → obs 0)
- G2 — Maxwell played Solar Wind Power (~−11 MC → ~2)
  1. paid 11 MC (base 11)
  2. ENERGY production 0 → 1
  3. TITANIUM 0 → 2
- G2 — Production (end of gen 2): Mortimer +21 MC (TR 23 + prod -2), energy→heat (0+4 heat), opponents simulated. → Generation 3, first player Maxwell
- G3 — Research: dealt ['Regolith Eaters', 'Micro-Mills', 'Predators', 'Ecological Zone'], kept ['Ecological Zone'] (−3 MC → 18)
- G3 — Hand reordered → ['Noctis City', 'Ecological Zone']
- G3 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 3a
- G3 — Plan patched (draft): no step changes (plan stands) — triggered by feed #52, #53
- G3 — Maxwell: research kept 2 cards (−6 MC → 21)
- G3 — Maxwell played Callisto Penal Mines (~−24 MC → ~3)
  1. paid 18 MC (base 24)
  2. MC production 5 → 8
  3. paid 2 titanium
- G3 — Plan patched (draft): threats updated
- G3 — Draft plan PROMOTED (re-simulated clean against current state)
- G3 — Mortimer played Noctis City (paid 18 MC) → balance 0 MC
  1. paid 18 MC (base 18) — --cost 18 override (auto-discounts skipped)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. MC production -2 → 1
- G3 — Mortimer placed city on 31 [E3] (Noctis City), +2 plants
- G3 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'blue city sits on app hex E3 (internal 31); Mortimer shows 0 MC, 9 plants, 0 energy production, and 1 MC production')
- G3 — Mortimer: -1 ENERGY production → 0
- G3 — Mortimer: tiles.cities corrected 0 → 1
- G3 — execute.py: 1a sent to the app, app-adopted
- G3 — Mortimer: spent 7 plants → greenery, oxygen 2% → 3%, TR → 24 (Convert Plants standard action)
- G3 — Mortimer placed greenery on 40 [F3], +1 plants
- G3 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'blue greenery sits on app hex F3 (internal 40); Mortimer shows 3 plants, TR 24, oxygen 3%, and two greeneries')
- G3 — execute.py: 1b sent to the app, app-adopted
- G3 — Mortimer: spent 8 heat, temperature -30°C → -28°C, TR → 25 (Convert Heat standard action)
- G3 — Executed plan step(s): 2a
- G3 — execute.py: 2a sent to the app, app-adopted
- G3 — Executed plan step(s): 3a
- G3 — execute.py: 3a sent to the app, app-adopted
- G3 — Production (end of gen 3): Mortimer +26 MC (TR 25 + prod 1), energy→heat (1+4 heat), opponents simulated. → Generation 4, first player Mortimer
- G4 — Research: dealt ['Research Outpost', 'Phobos Space Haven', 'Imported Nitrogen', 'Black Polar Dust'], kept ['Research Outpost', 'Imported Nitrogen'] (−6 MC → 20)
- G4 — Hand reordered → ['Research Outpost', 'Ecological Zone', 'Imported Nitrogen']
- G4 — Draft plan set (speculative — promote before executing): 1a, 1b
- G4 — Plan patched (draft): no step changes (plan stands) — triggered by feed #68, #70, #71
- G4 — Maxwell: research kept 2 cards (−6 MC → 25)
- G4 — Plan patched (draft): threats updated
- G4 — Draft plan PROMOTED (re-simulated clean against current state)
- G4 — Mortimer played Research Outpost (paid 18 MC) → balance 2 MC
  1. paid 18 MC (base 18) — --cost 18 override (auto-discounts skipped)
  2. city tile → TABLE: place it (not adjacent to a city)
- G4 — Mortimer placed city on 03 [A1], +2 steel
- G4 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'blue city sits on app hex A1 (internal 03), adjacent to no other tile; Mortimer shows 2 MC, 2 steel, and two cities')
- G4 — execute.py: 1a sent to the app, app-adopted
- G4 — Executed plan step(s): 1b
- G4 — execute.py: 1b sent to the app, app-adopted
- G4 — Maxwell played Lagrange Observatory (~−9 MC → ~16)
  1. paid 9 MC (base 9)
  2. → TABLE: draw 1 card(s) — log with `apply.py hand add <card>`
- G4 — Maxwell played Rad-Suits (~−6 MC → ~10)
  1. paid 6 MC (base 6)
  2. MC production 8 → 9
- G4 — Maxwell played Fuel Factory (~−6 MC → ~10)
  1. paid 0 MC (base 6)
  2. ENERGY production 1 → 0
  3. MC production 9 → 10
  4. TITANIUM production 0 → 1
  5. paid 3 steel
- G4 — Production (end of gen 4): Mortimer +26 MC (TR 25 + prod 1), energy→heat (0+4 heat), opponents simulated. → Generation 5, first player Maxwell
- G5 — Research: dealt ['Ice Cap Melting', 'Magnetic Field Generators', 'Business Contacts', 'Titanium Mine'], kept ['Business Contacts'] (−3 MC → 25)
- G5 — Hand reordered → ['Business Contacts', 'Ecological Zone', 'Imported Nitrogen']
- G5 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a
- G5 — Plan patched (draft): no step changes (plan stands) — triggered by feed #88, #89
- G5 — Maxwell: research kept 3 cards (−9 MC → 31)
- G5 — Maxwell played Advanced Alloys (~−9 MC → ~22)
  1. paid 9 MC (base 9)
  2. → TABLE: steelValue = 1 (resolve manually; log follow-ups via apply.py)
  3. → TABLE: titanumValue = 1 (resolve manually; log follow-ups via apply.py)
- G5 — Maxwell funded award Banker (−8 MC)
- G5 — Plan patched (draft): threats updated — triggered by feed #31, #33, #36, #66, #94
- G5 — Draft plan PROMOTED (re-simulated clean against current state)
- G5 — Mortimer: spent 7 plants → greenery, oxygen 3% → 4%, TR → 26 (Convert Plants standard action)
- G5 — Mortimer placed greenery on 39 [F2], +2 plants
- G5 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'blue greenery sits on app hex F2 (internal 39); Mortimer shows 2 plants, TR 26, oxygen 4%, and three greeneries')
- G5 — execute.py: 1a sent to the app, app-adopted
- G5 — Mortimer played Business Contacts (paid 6 MC) → balance 19 MC
  1. paid 6 MC (base 7) — --cost 6 override (auto-discounts skipped)
  2. → TABLE: draw 4 card(s) — log with `apply.py hand add <card>`
- G5 — Executed plan step(s): 1b
- G5 — Hand +['Earth Catapult', 'Noctis Farming'] → ['Ecological Zone', 'Imported Nitrogen', 'Earth Catapult', 'Noctis Farming']
- G5 — execute.py resolve: 1b follow-up answered, app-adopted
- G5 — Hand reordered → ['Ecological Zone', 'Earth Catapult', 'Imported Nitrogen', 'Noctis Farming']
- G5 — Plan patched (live): replaced 2a; replaced 2b; replaced 3a; inserted 4a after 3a; threats updated
- G5 — Maxwell played Ore Processor (~−13 MC → ~7)
  1. paid 7 MC (base 13)
  2. paid 3 steel
- G5 — Mortimer claimed milestone Gardener (−8 MC)
- G5 — Executed plan step(s): 2a (cue confirmed by the player — 'app-adopted': 2a 'Mortimer’s blue marker is on Gardener; the milestone shows claimed by Blue')
- G5 — execute.py: 2a sent to the app, app-adopted
- G5 — Mortimer played Ecological Zone (paid 11 MC) → balance 0 MC
  1. paid 11 MC (base 12) — --cost 11 override (auto-discounts skipped)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
- G5 — Mortimer placed special on 42 [F5], +1 plants, +2 MC (1 adjacent ocean)
- G5 — Executed plan step(s): 2b (cue confirmed by the player — 'app-adopted': 2b 'blue Ecological Zone tile sits on app hex F5 (internal 42), adjacent to greenery 41; Mortimer shows 2 MC, 3 plants, and one animal on Ecological Zone')
- G5 — Mortimer: card resources adopted from the app: Ecological Zone 0 → 2
- G5 — Mortimer: tiles.special corrected 1 → 2
- G5 — execute.py: 2b sent to the app, app-adopted
- G5 — Mortimer: spent 8 heat, temperature -28°C → -26°C, TR → 27 (Convert Heat standard action)
- G5 — Executed plan step(s): 3a
- G5 — execute.py: 3a sent to the app, app-adopted
- G5 — Executed plan step(s): 4a
- G5 — execute.py: 4a sent to the app, app-adopted
- G5 — Production (end of gen 5): Mortimer +28 MC (TR 27 + prod 1), energy→heat (0+4 heat), opponents simulated. → Generation 6, first player Mortimer
- G6 — Research: dealt ['GHG Producing Bacteria', 'Trees', 'Food Factory', 'Herbivores'], kept ['GHG Producing Bacteria'] (−3 MC → 27)
- G6 — Hand reordered → ['Imported Nitrogen', 'GHG Producing Bacteria', 'Earth Catapult', 'Noctis Farming']
- G6 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a
- G6 — Plan patched (draft): no step changes (plan stands) — triggered by feed #103, #109, #111, #112
- G6 — Maxwell: research kept 2 cards (−6 MC → 31)
- G6 — Draft plan PROMOTED (re-simulated clean against current state)
- G6 — Mortimer played Imported Nitrogen (paid 22 MC) → balance 5 MC
  1. paid 22 MC (base 23) — --cost 22 override (auto-discounts skipped)
  2. PLANTS 5 → 9
  3. TR +1 → 28
- G6 — Executed plan step(s): 1a
- G6 — Mortimer: card resources adopted from the app: Ecological Zone 2 → 4
- G6 — execute.py: 1a sent to the app, app-adopted
- G6 — Mortimer: spent 7 plants → greenery, oxygen 4% → 5%, TR → 29 (Convert Plants standard action)
- G6 — Mortimer placed greenery on 24 [D4], +1 plants, +2 MC (1 adjacent ocean)
- G6 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'blue greenery sits on app hex D4 (internal 24); Mortimer shows 7 MC, 3 plants, TR 29, oxygen 5%, and four greeneries')
- G6 — execute.py: 1b sent to the app, app-adopted
- G6 — Maxwell played Search For Life (~−3 MC → ~28)
  1. paid 3 MC (base 3)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
- G6 — Maxwell funded award Scientist (−14 MC)
- G6 — Plan patched (live): threats updated — triggered by feed #96, #124
- G6 — Mortimer played GHG Producing Bacteria (paid 7 MC) → balance 0 MC
  1. paid 7 MC (base 8) — --cost 7 override (auto-discounts skipped)
  2. blue action registered: Add 1 microbe to this card, or remove 2 microbes to raise temperature 1 step.
- G6 — Executed plan step(s): 2a
- G6 — execute.py: 2a sent to the app, app-adopted
- G6 — Action used: GHG Producing Bacteria ✓: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 1
- G6 — Executed plan step(s): 2b
- G6 — execute.py: 2b sent to the app, app-adopted
- G6 — Maxwell: standard project power_plant, −11 MC, +1 energy production
- G6 — Executed plan step(s): 3a
- G6 — execute.py: 3a sent to the app, app-adopted
- G6 — Production (end of gen 6): Mortimer +30 MC (TR 29 + prod 1), energy→heat (0+4 heat), opponents simulated. → Generation 7, first player Maxwell
- G7 — Research: dealt ['Terraforming Ganymede', 'Deep Well Heating', 'Insects', 'Livestock'], kept ['Deep Well Heating', 'Insects'] (−6 MC → 24)
- G7 — Hand reordered → ['Deep Well Heating', 'Insects', 'Earth Catapult', 'Noctis Farming']
- G7 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 3a
- G7 — Plan patched (draft): no step changes (plan stands) — triggered by feed #131, #132
- G7 — Maxwell: research kept 1 cards (−3 MC → 30)
- G7 — Maxwell played Space Elevator (~−27 MC → ~20)
  1. paid 10 MC (base 27)
  2. TITANIUM production 1 → 2
  3. paid 4 steel
  4. paid 3 titanium
- G7 — Maxwell played Soil Factory (~−9 MC → ~11)
  1. paid 9 MC (base 9)
  2. ENERGY production 1 → 0
  3. PLANTS production 0 → 1
- G7 — Plan patched (draft): threats updated — triggered by feed #4, #13, #39, #83, #101, #120, #136, #138
- G7 — Draft plan PROMOTED (re-simulated clean against current state)
- G7 — Mortimer: spent 8 heat, temperature -26°C → -24°C — track bonus: Mortimer +1 heat prod (→ 5), TR → 30 (Convert Heat standard action)
- G7 — Executed plan step(s): 1a
- G7 — execute.py: 1a sent to the app, app-adopted
- G7 — Mortimer played Deep Well Heating (paid 12 MC) → balance 12 MC
  1. paid 12 MC (base 13) — --cost 12 override (auto-discounts skipped)
  2. ENERGY production 0 → 1
  3. temperature -24°C → -22°C → TR 31
- G7 — Executed plan step(s): 1b
- G7 — execute.py: 1b sent to the app, app-adopted
- G7 — Maxwell claimed milestone Builder (−8 MC)
- G7 — Plan patched (live): threats updated — triggered by feed #141, #145
- G7 — Action used: GHG Producing Bacteria ✓: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 2
- G7 — Executed plan step(s): 2a
- G7 — execute.py: 2a sent to the app, app-adopted
- G7 — Executed plan step(s): 3a
- G7 — execute.py: 3a sent to the app, app-adopted
- G7 — Production (end of gen 7): Mortimer +32 MC (TR 31 + prod 1), energy→heat (0+5 heat), opponents simulated. → Generation 8, first player Mortimer
- G8 — Research: dealt ['Immigrant City', 'Special Design', 'Protected Valley', 'Industrial Center'], kept ['Immigrant City', 'Protected Valley'] (−6 MC → 38)
- G8 — Hand reordered → ['Immigrant City', 'Protected Valley', 'Insects', 'Earth Catapult', 'Noctis Farming']
- G8 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a, 4a
- G8 — Plan patched (draft): no step changes (plan stands) — triggered by feed #150, #151
- G8 — Maxwell: research kept 2 cards (−6 MC → 27)
- G8 — Draft plan PROMOTED (re-simulated clean against current state)
- G8 — Plan patched (live): replaced 1a
- G8 — Mortimer played Immigrant City (paid 8 MC + 2 steel) → balance 30 MC
  1. paid 8 MC (base 13) — --cost 12 override (auto-discounts skipped)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. ENERGY production 1 → 0
  4. MC production 1 → -1
  5. city tile → TABLE: place it (not adjacent to a city)
  6. Immigrant City (Mortimer): +1 MC production → 0 (city placed)
- G8 — Mortimer placed city on 25 [D5], +2 plants, +2 MC (1 adjacent ocean)
- G8 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'blue city sits on app hex D5 (internal 25), adjacent to greenery 24 and ocean 33; Mortimer shows 32 MC, 0 steel, 9 plants, and three cities')
- G8 — execute.py: 1a sent to the app, app-adopted
- G8 — Mortimer claimed milestone Mayor (−8 MC)
- G8 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'Mortimer’s blue marker is on Mayor; all three milestone slots are filled')
- G8 — execute.py: 1b sent to the app, app-adopted
- G8 — Maxwell funded award Miner (−20 MC)
- G8 — Plan patched (live): threats updated — triggered by feed #143, #160, #161
- G8 — Maxwell used action Space Elevator: −1 steel → 1, MC 7 → 12
- G8 — Mortimer played Protected Valley (paid 22 MC) → balance 2 MC
  1. paid 22 MC (base 23) — --cost 22 override (auto-discounts skipped)
  2. MC production 0 → 2
  3. greenery tile, oxygen 5% → 6% → TR 32
  4. → TABLE: place the greenery (adjacent to your tiles)
- G8 — Mortimer placed greenery on 34 [E6], +2 plants, +2 MC (1 adjacent ocean)
- G8 — Executed plan step(s): 2a (cue confirmed by the player — 'app-adopted': 2a 'blue greenery sits on app hex E6 (internal 34); Mortimer shows 4 MC, 11 plants, MC production 2, TR 32, and oxygen 6%')
- G8 — Mortimer: card resources adopted from the app: Ecological Zone 4 → 5
- G8 — execute.py: 2a sent to the app, app-adopted
- G8 — Mortimer: spent 7 plants → greenery, oxygen 6% → 7%, TR → 33 (Convert Plants standard action)
- G8 — Mortimer placed greenery on 23 [D3], +1 plants
- G8 — Executed plan step(s): 2b (cue confirmed by the player — 'app-adopted': 2b 'blue greenery sits on app hex D3 (internal 23); Mortimer shows 5 plants, TR 33, oxygen 7%, and six greeneries')
- G8 — execute.py: 2b sent to the app, app-adopted
- G8 — Maxwell played Indentured Workers (~−0 MC → ~12)
  1. paid 0 MC (base 0)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. Indentured Workers: next card Maxwell plays this generation costs 8 MC less
- G8 — Maxwell played Designed Microorganisms (~−8 MC → ~4)
  1. paid 8 MC (base 16, −8: Indentured Workers −8)
  2. PLANTS production 1 → 3
- G8 — Action used: GHG Producing Bacteria ✓: or-choice 1 = Remove 2 microbes to raise temperature 1 step, −2 microbe on GHG Producing Bacteria → 0, temperature -22°C → -20°C — track bonus: Mortimer +1 heat prod (→ 6) → TR 34
- G8 — Executed plan step(s): 3a
- G8 — Sync: temperature = -22°C
- G8 — Mortimer: TR -1 → 33
- G8 — Mortimer: -1 HEAT production → 5
- G8 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 0 → 3
- G8 — execute.py: 3a sent to the app, app-adopted
- G8 — Executed plan step(s): 4a
- G8 — execute.py: 4a sent to the app, app-adopted
- G8 — Maxwell: -1 MC → 3
- G8 — Production (end of gen 8): Mortimer +35 MC (TR 33 + prod 2), energy→heat (1+5 heat), opponents simulated. → Generation 9, first player Maxwell
- G9 — Research: dealt ['Adapted Lichen', 'Extreme-Cold Fungus', 'Convoy From Europa', 'Lava Flows'], kept ['Extreme-Cold Fungus', 'Convoy From Europa', 'Lava Flows'] (−9 MC → 30)
- G9 — Hand reordered → ['Lava Flows', 'Insects', 'Extreme-Cold Fungus', 'Convoy From Europa', 'Noctis Farming', 'Earth Catapult']
- G9 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a, 4a
- G9 — Plan patched (draft): no step changes (plan stands) — triggered by feed #182, #183
- G9 — Maxwell: research kept 2 cards (−6 MC → 27)
- G9 — Maxwell played Small Animals (~−6 MC → ~21)
  1. paid 6 MC (base 6)
  2. → TABLE: Small Animals: decrease any plants production 1 (name the victim: --target <player>)
- G9 — Mortimer: -1 PLANTS production → 1
- G9 — Maxwell played Interstellar Colony Ship (~−21 MC → ~12)
  1. paid 9 MC (base 24, −3: Earth Office −3)
  2. paid 4 titanium
- G9 — POST-GAME DIRECTIVE (execute only after game ends): create a repo-root artifact folder identifiable by game id + Mortimer + blue; include full public game log, failures/diagnostics, complete strategy and outcome analysis, model/reasoning metadata, KB-update recommendations, and relevant game artifacts; do not modify harness; commit and push to main.
- G9 — Plan patched (draft): replaced 2b; threats updated — triggered by feed #167, #171, #174, #188
- G9 — Draft plan PROMOTED (re-simulated clean against current state)
- G9 — Action used: GHG Producing Bacteria ✓: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 4
- G9 — Executed plan step(s): 1a
- G9 — Sync: temperature = -20°C
- G9 — Mortimer: TR +1 → 34
- G9 — Mortimer: +1 HEAT production → 6
- G9 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 4 → 1
- G9 — execute.py: 1a sent to the app, app-adopted
- G9 — Mortimer played Lava Flows (paid 17 MC) → balance 13 MC
  1. paid 17 MC (base 18) — --cost 17 override (auto-discounts skipped)
  2. temperature -20°C → -18°C → TR 35
  3. temperature -18°C → -16°C → TR 36
  4. special tile → TABLE: place it
  5. → TABLE: tile = {'type': 'lavaflows', 'on': 'volcanic', 'title': 'Select either Tharsis Tholus, Ascraeus Mons, Pavonis Mons or Arsia Mons', 'adjacencyBonus': '@dynamic'} (resolve manually; log follow-ups via apply.py)
- G9 — Mortimer placed lavaflows on 29 [E1] (Arsia Mons), +2 plants
- G9 — Executed plan step(s): 1b (cue confirmed by the player — 'app-adopted': 1b 'blue Lava Flows tile sits on app hex E1 (internal 29, Arsia Mons); Mortimer shows 13 MC, 9 plants, TR 36, and temperature −16°C')
- G9 — execute.py: 1b sent to the app, app-adopted
- G9 — Maxwell played Dust Seals (~−2 MC → ~10)
  1. paid 2 MC (base 2)
- G9 — Maxwell played Technology Demonstration (~−5 MC → ~5)
  1. paid 5 MC (base 5)
  2. → TABLE: draw 2 card(s) — log with `apply.py hand add <card>`
- G9 — Mortimer: spent 8 heat, temperature -16°C → -14°C, TR → 37 (Convert Heat standard action)
- G9 — Executed plan step(s): 2a
- G9 — execute.py: 2a sent to the app, app-adopted
- G9 — Mortimer played Insects (paid 8 MC) → balance 5 MC
  1. paid 8 MC (base 9) — --cost 8 override (auto-discounts skipped)
  2. plants production: own plant tags incl. this: 3
  3. PLANTS production 1 → 4
- G9 — Executed plan step(s): 2b
- G9 — execute.py: 2b sent to the app, app-adopted
- G9 — Maxwell: -1 MC → 4
- G9 — Maxwell used action Small Animals: Small Animals: +1 animal on the card → 1
- G9 — Plan patched (live): no step changes (plan stands) — triggered by feed #199
- G9 — Mortimer: spent 7 plants → greenery, oxygen 7% → 8% — 8% O2 track bonus: free temperature step, temperature -14°C → -12°C, Mortimer +1 TR, TR → 39 (Convert Plants standard action)
- G9 — Mortimer placed greenery on 30 [E2], +2 plants
- G9 — Executed plan step(s): 3a (cue confirmed by the player — 'app-adopted': 3a 'blue greenery sits on app hex E2 (internal 30); Mortimer shows 4 plants, TR 38, oxygen 8%, and seven greeneries')
- G9 — execute.py: 3a sent to the app, app-adopted
- G9 — Executed plan step(s): 4a
- G9 — execute.py: 4a sent to the app, app-adopted
- G9 — Production (end of gen 9): Mortimer +41 MC (TR 39 + prod 2), energy→heat (0+6 heat), opponents simulated. → Generation 10, first player Mortimer
- G10 — Research: dealt ['Fueled Generators', 'Local Heat Trapping', 'Zeppelins', 'Power Grid'], kept ['Local Heat Trapping'] (−3 MC → 43)
- G10 — Hand reordered → ['Extreme-Cold Fungus', 'Local Heat Trapping', 'Convoy From Europa', 'Noctis Farming', 'Earth Catapult']
- G10 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a, 3b, 4a, 4b, 5a
- G10 — Plan patched (draft): no step changes (plan stands) — triggered by feed #211, #212
- G10 — Maxwell: research kept 2 cards (−6 MC → 28)
- G10 — Draft plan PROMOTED (re-simulated clean against current state)
- G10 — Mortimer: spent 7 plants → greenery, oxygen 8% → 9%, TR → 40 (Convert Plants standard action)
- G10 — Mortimer placed greenery on 22 [D2], +1 plants
- G10 — Executed plan step(s): 1a (cue confirmed by the player — 'app-adopted': 1a 'blue greenery on app hex D2; Mortimer has 2 plants, TR 40, oxygen 9%')
- G10 — execute.py: 1a sent to the app, app-adopted
- G10 — Mortimer played Extreme-Cold Fungus (paid 12 MC) → balance 31 MC
  1. paid 12 MC (base 13) — --cost 12 override (auto-discounts skipped)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. blue action registered: Gain 1 plant, or add 2 microbes to ANOTHER card.
- G10 — Executed plan step(s): 1b
- G10 — execute.py: 1b sent to the app, app-adopted
- G10 — Maxwell played Windmills (~−6 MC → ~28)
  1. paid 0 MC (base 6)
  2. ENERGY production 0 → 1
  3. paid 3 steel
- G10 — Maxwell played Ice Asteroid (~−23 MC → ~11)
  1. paid 17 MC (base 23)
  2. oceans 1 → 2 → TR 21
  3. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  4. oceans 2 → 3 → TR 22
  5. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  6. paid 2 titanium
- G10 — Sync: oceans = 1
- G10 — Observed Maxwell mat (gen 10), drift: TR -2 (sim 22 → obs 20)
- G10 — Maxwell placed ocean on 28 [D8], +2 plants
- G10 — Maxwell: oceans 1 → 2, TR → 21
- G10 — Maxwell placed ocean on 13 [B6], +2 card (drawn, hidden)
- G10 — Maxwell: oceans 2 → 3, TR → 22
- G10 — Plan patched (live): replaced 3b; replaced 4a — triggered by feed #193, #207, #223, #224, #225
- G10 — Action used: Extreme-Cold Fungus ✓
- G10 — Executed plan step(s): 2a
- G10 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 1 → 3
- G10 — execute.py: 2a sent to the app, app-adopted
- G10 — Action used: GHG Producing Bacteria ✓: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 4
- G10 — Executed plan step(s): 2b
- G10 — Sync: temperature = -10°C
- G10 — Mortimer: TR +1 → 41
- G10 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 4 → 1
- G10 — execute.py: 2b sent to the app, app-adopted
- G10 — Maxwell: spent 8 plants → greenery, oxygen 9% → 10%, TR → 23 (Convert Plants standard action)
- G10 — Maxwell placed greenery on 59 [I1, app J1], +1 steel, Mining Guild: +1 steel production
- G10 — Maxwell used action Small Animals: Small Animals: +1 animal on the card → 2
- G10 — Plan patched (live): replaced 4a — triggered by feed #232
- G10 — Mortimer played Local Heat Trapping (paid 0 MC) → balance 31 MC
  1. paid 0 MC (base 1) — --cost 0 override (auto-discounts skipped)
  2. → TABLE: BESPOKE card — db behavior may be partial; read the card text and log any extra effects
  3. −5 heat → 5
- G10 — Mortimer: +4 PLANTS → 6
- G10 — Executed plan step(s): 3a
- G10 — execute.py: 3a sent to the app, app-adopted
- G10 — Mortimer played Convoy From Europa (paid 14 MC) → balance 17 MC
  1. paid 14 MC (base 15) — --cost 14 override (auto-discounts skipped)
  2. oceans 3 → 4 → TR 42
  3. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  4. → TABLE: draw 1 card(s) — log with `apply.py hand add <card>`
- G10 — Mortimer placed ocean on 43 [F6], +1 plants
- G10 — Executed plan step(s): 3b (cue confirmed by the player — 'app-adopted': 3b 'blue ocean on app hex F6 (internal 43); Mortimer has 17 MC, 7 plants, TR 42 and four oceans')
- G10 — Hand +['Pets'] → ['Noctis Farming', 'Earth Catapult', 'Pets']
- G10 — execute.py: 3b sent to the app, app-adopted
- G10 — Hand reordered → ['Noctis Farming', 'Pets', 'Earth Catapult']
- G10 — Maxwell played Acquired Company (~−7 MC → ~4)
  1. paid 7 MC (base 10, −3: Earth Office −3)
  2. MC production 10 → 13
- G10 — Plan patched (live): replaced 4b
- G10 — Mortimer: spent 7 plants → greenery, oxygen 10% → 11%, TR → 43 (Convert Plants standard action)
- G10 — Mortimer placed greenery on 26 [D6], +1 plants
- G10 — Executed plan step(s): 4a (cue confirmed by the player — 'app-adopted': 4a 'blue greenery on app hex D6; Mortimer has 1 plant, TR 43, oxygen 11%')
- G10 — execute.py: 4a sent to the app, app-adopted
- G10 — Mortimer played Noctis Farming (paid 9 MC) → balance 8 MC
  1. paid 9 MC (base 10) — --cost 9 override (auto-discounts skipped)
  2. MC production 2 → 3
  3. PLANTS 1 → 3
- G10 — Executed plan step(s): 4b
- G10 — Mortimer: card resources adopted from the app: Ecological Zone 5 → 6
- G10 — execute.py: 4b sent to the app, app-adopted
- G10 — Plan patched (live): replaced 5a
- G10 — Executed plan step(s): 5a
- G10 — execute.py: 5a sent to the app, app-adopted
- G10 — Production (end of gen 10): Mortimer +46 MC (TR 43 + prod 3), energy→heat (0+6 heat), opponents simulated. → Generation 11, first player Maxwell
- G11 — Research: dealt ['Comet', 'Energy Saving', 'Investment Loan', 'Symbiotic Fungus'], kept ['Comet', 'Investment Loan'] (−6 MC → 48)
- G11 — Hand reordered → ['Comet', 'Investment Loan', 'Pets', 'Earth Catapult']
- G11 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a, 3b, 4a, 4b, 5a
- G11 — Plan patched (draft): no step changes (plan stands) — triggered by feed #255, #256
- G11 — Maxwell: research kept 1 cards (−3 MC → 37)
- G11 — Maxwell used action Space Elevator: −1 steel → 5, MC 37 → 42
- G11 — Maxwell played Release of Inert Gases (~−14 MC → ~28)
  1. paid 14 MC (base 14)
  2. TR +2 → 25
- G11 — Draft plan PROMOTED (re-simulated clean against current state)
- G11 — Action used: Extreme-Cold Fungus ✓
- G11 — Executed plan step(s): 1a
- G11 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 1 → 3
- G11 — execute.py: 1a sent to the app, app-adopted
- G11 — Action used: GHG Producing Bacteria ✓: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 4
- G11 — Executed plan step(s): 1b
- G11 — Sync: temperature = -8°C
- G11 — Mortimer: TR +1 → 44
- G11 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 4 → 1
- G11 — execute.py: 1b sent to the app, app-adopted
- G11 — Maxwell: standard project greenery, −23 MC, greenery tile, oxygen 11% → 12%
- G11 — Maxwell placed greenery on 54 [H2]
- G11 — Maxwell used action Small Animals: Small Animals: +1 animal on the card → 3
- G11 — Plan patched (live): replaced 3a — triggered by feed #268
- G11 — Mortimer played Comet (paid 20 MC) → balance 28 MC
  1. paid 20 MC (base 21) — --cost 20 override (auto-discounts skipped)
  2. temperature -8°C → -6°C → TR 45
  3. oceans 4 → 5 → TR 46
  4. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  5. Comet: Maxwell lost 3 plants (up to 3) → 1
- G11 — Mortimer placed ocean on 44 [F7], +1 plants, +2 MC (1 adjacent ocean)
- G11 — Executed plan step(s): 2a (cue confirmed by the player — 'app-adopted': 2a 'blue ocean on app hex F7 (internal 44); Mortimer has 30 MC, 8 plants, TR 46; Maxwell lost up to 3 plants')
- G11 — execute.py resolve: 2a follow-up answered, app-adopted
- G11 — Mortimer: spent 8 heat, temperature -6°C → -4°C, TR → 47 (Convert Heat standard action)
- G11 — Executed plan step(s): 2b
- G11 — execute.py: 2b sent to the app, app-adopted
- G11 — Maxwell: -1 MC → 4
- G11 — Plan patched (live): no step changes (plan stands) — triggered by feed #276
- G11 — Mortimer: spent 7 plants → greenery, oxygen 12% → 13%, TR → 48 (Convert Plants standard action)
- G11 — Mortimer placed greenery on 17 [C4]
- G11 — Executed plan step(s): 3a (cue confirmed by the player — 'app-adopted': 3a 'blue greenery on app hex C4 (internal 17); Mortimer has 1 plant, TR 48, oxygen 13%')
- G11 — execute.py: 3a sent to the app, app-adopted
- G11 — Mortimer played Investment Loan (paid 2 MC) → balance 38 MC
  1. paid 2 MC (base 3) — --cost 2 override (auto-discounts skipped)
  2. MC production 3 → 2
  3. MC 30 → 40
- G11 — Executed plan step(s): 3b
- G11 — execute.py: 3b sent to the app, app-adopted
- G11 — Mortimer: standard project aquifer, −18 MC, oceans 5 → 6
- G11 — Mortimer placed ocean on 45 [F8], +1 plants, +2 MC (1 adjacent ocean)
- G11 — Executed plan step(s): 4a (cue confirmed by the player — 'app-adopted': 4a 'blue ocean on app hex F8 (internal 45); Mortimer has 22 MC, 2 plants, TR 49 and six oceans')
- G11 — execute.py: 4a sent to the app, app-adopted
- G11 — Mortimer: standard project asteroid, −14 MC, temperature -4°C → -2°C
- G11 — Executed plan step(s): 4b
- G11 — execute.py: 4b sent to the app, app-adopted
- G11 — Executed plan step(s): 5a
- G11 — execute.py: 5a sent to the app, app-adopted
- G11 — Production (end of gen 11): Mortimer +52 MC (TR 50 + prod 2), energy→heat (0+6 heat), opponents simulated. → Generation 12, first player Mortimer
- G12 — Research: dealt ['Eos Chasma National Park', 'ArchaeBacteria', 'Giant Ice Asteroid', 'Mining Area'], kept ['Giant Ice Asteroid', 'Eos Chasma National Park'] (−6 MC → 54)
- G12 — Hand reordered → ['Giant Ice Asteroid', 'Eos Chasma National Park', 'Pets', 'Earth Catapult']
- G12 — Draft plan set (speculative — promote before executing): 1a, 1b, 2a, 2b, 3a, 3b, 4a
- G12 — Plan patched (draft): no step changes (plan stands) — triggered by feed #291, #292
- G12 — Draft plan PROMOTED (re-simulated clean against current state)
- G12 — Action used: Extreme-Cold Fungus ✓
- G12 — Executed plan step(s): 1a
- G12 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 1 → 3
- G12 — execute.py: 1a sent to the app, app-adopted
- G12 — Action used: GHG Producing Bacteria ✓: or-choice 0 = Add 1 microbe to this card, GHG Producing Bacteria: +1 microbe on the card → 4
- G12 — Executed plan step(s): 1b
- G12 — Sync: temperature = 0°C
- G12 — Sync: oceans = 7
- G12 — Mortimer: +2 STEEL → 2
- G12 — Mortimer: TR +2 → 52
- G12 — Mortimer: card resources adopted from the app: GHG Producing Bacteria 4 → 1
- G12 — TILE LOCATION: nobody ocean added on 04 [app]
- G12 — execute.py resolve: 1b follow-up answered, app-adopted
- G12 — Maxwell used action Space Elevator: −1 steel → 7, MC 43 → 48
- G12 — Maxwell: standard project greenery, −23 MC, greenery tile, oxygen 13% → 14%
- G12 — Maxwell placed greenery on 47 [G2]
- G12 — Plan patched (live): replaced 2a; replaced 2b; inserted 3a, 3b after 2b; removed 3a, 3b, 4a — triggered by feed #217, #233, #242, #244, #245, #248, #271, #272, #281, #286, #289, #300, #305
- G12 — Mortimer played Giant Ice Asteroid (paid 35 MC) → balance 19 MC
  1. paid 35 MC (base 36) — --cost 35 override (auto-discounts skipped)
  2. temperature 0°C → 2°C → TR 53
  3. temperature 2°C → 4°C → TR 54
  4. oceans 7 → 8 → TR 55
  5. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  6. oceans 8 → 9 → TR 56
  7. → TABLE: place the ocean tile (name the hex; gain its placement bonus + 2 MC per adjacent ocean)
  8. → TABLE: Giant Ice Asteroid: remove up to 6 plants from any player (log with --target <player>, or apply.py attack)
- G12 — Mortimer placed ocean on 06 [A4], → TABLE: +1 card (draw/track manually)
- G12 — Mortimer placed ocean on 07 [A5], +4 MC (2 adjacent ocean)
- G12 — Executed plan step(s): 2a (cue confirmed by the player — 'app-adopted': 2a 'blue oceans on app hexes A4 and A5; Mortimer has 21 MC, TR 56, max oceans, temp 4C; Maxwell has zero plants')
- G12 — Hand +['Imported Hydrogen'] → ['Eos Chasma National Park', 'Pets', 'Earth Catapult', 'Imported Hydrogen']
- G12 — execute.py resolve: 2a follow-up answered, app-adopted
- G12 — Mortimer: spent 8 heat, temperature 4°C → 6°C, TR → 57 (Convert Heat standard action)
- G12 — Executed plan step(s): 2b
- G12 — execute.py: 2b sent to the app, app-adopted
- G12 — Hand reordered → ['Pets', 'Earth Catapult', 'Imported Hydrogen', 'Eos Chasma National Park']
- G12 — Maxwell played Tundra Farming (~−16 MC → ~9)
  1. paid 16 MC (base 16)
  2. PLANTS production 3 → 4
  3. MC production 13 → 15
  4. PLANTS 4 → 5
- G12 — Maxwell used action Small Animals: Small Animals: +1 animal on the card → 4
- G12 — Observed Maxwell mat (gen 12), drift: PLANTS -4 (sim 5 → obs 1)
- G12 — Plan patched (live): replaced 3a; replaced 3b — triggered by feed #313
- G12 — Mortimer: standard project asteroid, −14 MC, temperature 6°C → 8°C
- G12 — Executed plan step(s): 3a
- G12 — execute.py: 3a sent to the app, app-adopted
- G12 — Executed plan step(s): 3b
- G12 — execute.py: 3b sent to the app, app-adopted
- G12 — Maxwell: -1 MC → 8
- G12 — Production (end of gen 12): Mortimer +60 MC (TR 58 + prod 2), energy→heat (0+6 heat), opponents simulated. → Generation 13, first player Maxwell
- G13 — Mortimer placed greenery on 09 [B2] (Tharsis Tholus), +1 steel, +2 MC (1 adjacent ocean)
- G13 — Mortimer: tiles.greeneries corrected 10 → 11
- G13 — Mortimer: -7 PLANTS → 3
- Game ended 2026-08-29 — Mortimer won 92-66 (Blue Ecoline vs Maxwell Red Mining Guild)
