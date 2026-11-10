# Recommended strategy-KB updates

**Not applied.** The instruction for this session was to change nothing in the harness, so
these are proposals for separate review. They follow `strategy/06`'s header contract —
AMEND a conflicting prior → INCREMENT an existing rule's ×N → only then APPEND — and use its
line format `- RULE · price: … · (EVIDENCE · ×N class)`.

Two framing notes for whoever folds these:

- **This is the KB's first two-player game.** Everything in `strategy/01`–`03` is explicitly
  tuned for "4–5p casual" and `06` is entirely `seats` class. Several priors inverted at 2p and
  should be amended in place with a player-count qualifier rather than overwritten. **The
  evidence class for these lines is deliberately left unassigned below** — `06`'s taxonomy has
  only `seats` and `humans`, and the correct value for this game should be taken from the
  private eval ledger at fold time rather than guessed here.
- **`06`'s outcome loop** (judge every cited rule helped/hurt/wash) is run at the bottom.

---

## A. AMEND a conflicting prior (do this first)

### A1 — `strategy/01`, "Resource values": TR is under-priced as income

Current: *"1 TR ≈ 1 VP + ~1 MC income per remaining generation."* That is arithmetically right
and strategically far too quiet. Proposed amendment, in place:

> **TR IS THE BEST PRODUCTION CARD IN THE GAME.** A TR step pays 1 MC every remaining
> generation *and* 1 VP, so it is simultaneously income and score — no MC-production card is
> both. At low player counts, where games run long, a player who terraforms every generation
> out-earns a dedicated MC engine as a side effect of scoring. Price a TR step against MC
> production directly, not only against VP.

*Evidence:* the dedicated MC-engine seat finished with MC production 15 against 2 and still had
**less income** — 42/gen against 60/gen — because the opponent's TR was 58 to its 27.
(2p CE gens 1-12, both sides · CLASS-AT-FOLD-TIME)

### A2 — `strategy/02`, HEAT/TEMPERATURE archetype: the "stealable single input" rule is too broad

Current: *"An engine with ONE stealable input (energy prod at a Power Supply Consortium table)
needs its second source bought before the attack, not after."* Read literally at the table, this
became a reason to **abandon** the only repeatable TR source available. Proposed amendment:

> …needs its second source bought before the attack, not after. **But abandoning the engine is
> not the alternative to protecting it: only abandon a repeatable TR source if you have already
> named its replacement.** One observed steal is evidence to buy redundancy, not to write the
> line off — and never dismantle the input yourself afterwards.

*Evidence:* Ore Processor (4 energy → 1 titanium + 1 oxygen step = **+1 TR every generation**)
was dropped in gen 4 after a single Energy Tapping, with nine generations left and no
replacement named; two later cards (Fuel Factory, Soil Factory) each consumed 1 energy
production, so the input was self-dismantled. The card sat unused in the tableau for eight
generations as a decorative building tag. (2p CE gens 4-12, the player · CLASS-AT-FOLD-TIME)

### A3 — `strategy/01`, payback test: say what it does *not* price

> The payback test prices **production**. It does not price TR tempo, denial, tag value or
> requirement-window position. Never let a payback verdict veto a card whose value is TR.

*Evidence:* Nitrogen-Rich Asteroid (+3 TR total, +1 plant production) was rejected at
"−6 MC net; needs 17 gens, only 14 left" — a correct verdict on its plant-production line and
the wrong verdict on the card, in a game ultimately lost by 31 TR. (2p CE gen 1, the player · CLASS-AT-FOLD-TIME)

---

## B. INCREMENT existing rules re-observed here

### B1 — Tiles & cities, "Build the tile plan the same turn as the city" → **×2**, add `humans`

Re-observed with the same shape and a larger price. Append to its price field:

> ; city placed gen 1 with no plant source until gen 8 and first greenery gen 10 → tile VP 6 v 21

*Note for the fold:* when greeneries finally landed they were placed correctly — all three
adjacent to the single city, so the city scored 3 — which is precisely the evidence that the
plan was available six generations earlier and worth roughly 12 VP.
(add `2p CE gens 1-10, the player` · ×2 · now `seats`+`humans`)

### B2 — Milestones/awards, "Fund an award only if you can LOCK the metric … prefer the metric your position OWNS structurally" → **×4**, add `humans`

Strongly confirmed, and it was the single best-performing rule in the game. Append:

> ; all three slots swept on archetype-locked metrics (Banker v a 1-MC-production plant deck,
> Miner v an opponent with ZERO steel and titanium production all game) → 15 VP, all held to
> final scoring

### B3 — Milestones/awards, "Claim the turn you qualify" → **×5**, add `humans`

Append:

> ; Builder claimed the turn the 8th building tag landed (gen 7) took the last milestone slot
> and made Terraformer unreachable for an opponent who finished at TR 58

---

## C. APPEND — genuinely new rules

### C1 — Player-count rule (the important one)

> - Two-player awards score **5–0: there is no second place** — so each of the three slots is a
>   full 5 VP swing plus denial, and sweeping all three on structurally-owned metrics is the
>   cheapest VP on the board · price: 42 MC → 15 VP for me and 0 for a rival who led Landlord
>   15 tiles to 2 and Thermalist 11 heat to 3 · (2p CE gens 5-8, the player · ×1 CLASS-AT-FOLD-TIME)

Verified in code, not assumed: `scripts/score.py` `AWARD_VP = (5, 2)` with the comment
*"2nd not awarded in 2p"*. **Recommend the KB tell the advisor to read this constant rather
than recall the rule**, since the 4–5p intuition ("second place is accidental value") is
actively misleading at 2p.

### C2 — The opening question the corp evaluation is missing

> - At the corp + initial-10 decision, after scoring economy and synergy, ask one more question
>   out loud: **"which card here produces TR every generation?"** — a hand with no repeatable
>   terraforming needs one bought by gen 3 or the engine has no exit · price: five economy keeps,
>   TR unchanged at its starting value through gen 9 of 12, −31 TR at scoring · (2p CE gens 1-9,
>   the player · ×1 CLASS-AT-FOLD-TIME)

### C3 — Diagnosing without reallocating

> - When a threat block names a pivot ("the pivot from engine to TR must happen by gen N"), the
>   NEXT generation's spend must move or the diagnosis is decoration — re-read your own prior
>   threats block at each generation plan and check the money followed it · price: the pivot was
>   written in the gen-7 threats block and generations 7-8 still spent ~44 MC on milestone
>   enablers and award funding; the first TR purchase came in gen 10 · (2p CE gens 7-10, the
>   player · ×1 CLASS-AT-FOLD-TIME)

### C4 — Low-player-count clock

> - At 2p the board fills slowly and the game runs long (12+ generations here), which makes
>   *repeatable* sources dominate one-shot purchases far more than the 4-5p priors suggest —
>   but the same length lets a TR leader's income compound, so falling behind on TR is
>   self-reinforcing, not recoverable by out-producing · price: an 8-generation TR deficit grew
>   from 5 to 31 while MC production led 15 to 2 · (2p CE gens 3-12, both sides · ×1 CLASS-AT-FOLD-TIME)

### C5 — Blue-card actions are free VP and get forgotten

> - Register every repeatable card action the turn the card lands and take it EVERY generation;
>   the pass gate finding one is a miss, not a save · price: Small Animals' free animal action
>   was worth 2 VP and Space Elevator's 1 steel → 5 MC funded a card in three generations —
>   both were discovered only when the pass gate refused a pass · (2p CE gens 8-12, the player
>   · ×1 CLASS-AT-FOLD-TIME)

---

## D. Outcome loop — every rule cited in this game's plans, judged

| Rule cited | Verdict | Action |
|---|---|---|
| `02` awards: prefer the structurally-owned metric, never fund a mere lead | **helped** (15 VP) | increment → ×4 (B2) |
| `02` milestones: claim the turn you qualify, 5 VP for 8 MC | **helped** (Builder denied Terraformer) | increment → ×5 (B3) |
| `02` TR engines: a stealable single input is a trap | **HURT** — cost the only repeatable TR source | amend (A2) |
| `02` tile plan the same turn as the city | **HURT** — cited in gen 1, then violated for nine generations | increment + amend price (B1) |
| `01` payback: positive margin or skip | **HURT** once — vetoed a TR card on its production line | amend scope (A3) |
| `01` discounts are excellent early, dead late (Earth Office, gen 1) | **helped**, modestly (~6 MC saved across two Earth cards) | no change |
| `01` requirement windows: max-X cards die, play or discard early | **helped** — Search For Life played at 5% oxygen against a max of 6% | no change |
| `03` Mining Guild: aim tiles at metal-bonus hexes | **wash** — the trigger fired four times and steel outran anything to spend it on; steel prod was still useful late as free spending power once Miner was locked | consider a caveat: Mining Guild needs a *building-card density* check at the corp decision, not just 2 synergy hits |
| `03` power beats synergy on scattered hands | **wash** — Mining Guild over UNMI was defensible and not the cause of the loss | no change |

---

## E. Addendum — the sharpest single metric, found after the fact

The app exposes `globalParameterSteps` per player in its end-of-game payload: how many steps
of each parameter each player personally raised. For this game it read **Mortimer 37, Maxwell 5
— including temperature 19–0.**

**Recommendation:** teach the advisor to read this as a live scoreboard, not a post-mortem stat.
`scripts/advise.py`'s brief already prints the globals; adding a per-player "parameter steps
raised" line would surface "you have raised zero temperature steps in nine generations" at the
moment it is still fixable. A proposed `06` line:

> - Track how many global-parameter steps YOU have personally raised, every generation — a
>   count still near zero by gen 4 means the deck has no terraforming engine and the plan must
>   change that generation, not "when the economy is ready" · price: 5 steps to a rival's 37,
>   temperature 19-0, in a game lost by 26 with the cash engine leading MC production 15 to 2 ·
>   (2p CE gens 1-12, both sides · ×1 CLASS-AT-FOLD-TIME)

And the corresponding companion, which the VP-by-generation curve supports directly (gap −4 at
gen 7, −26 at gen 12):

> - One-off VP purchases (milestones, awards, printed-VP cards) have a CEILING; a terraforming
>   engine does not — once the purchasable VP is bought, a player without a repeatable TR source
>   loses ground every remaining generation at a fixed rate · price: level at −4 VP in gen 7 when
>   the milestone and two awards landed, then −22 VP across the last five generations at ~4.5/gen ·
>   (2p CE gens 7-12, both sides · ×1 CLASS-AT-FOLD-TIME)
