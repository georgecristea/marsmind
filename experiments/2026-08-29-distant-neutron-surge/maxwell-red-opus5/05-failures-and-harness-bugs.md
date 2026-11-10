# Failures, harness defects and friction

Nothing here changed the outcome — the loss was strategic (see `04-analysis.md`). But three
of these cost real in-game resources or real wall-clock time, and one is a filed bug.

## 1. FILED BUG — metal-value modifiers are not modelled, causing silent overpayment

**Filed as** `private/bugs/20260829-execute-py-overpays-cards-when-a-metal-v.md`
(copy in `raw/bug-advanced-alloys-pricing.md`).

`scripts/tmlib.py` uses module-level constants `STEEL_VALUE = 2` / `TITANIUM_VALUE = 3`
(tmlib.py:176, used in the affordability path at :309) with no hook for tableau cards that
change them. I played **Advanced Alloys** in generation 5 ("each steel/titanium you have is
worth 1 M€ extra"), after which my steel is worth 3 and titanium 4 — and the harness never knew.

Two distinct consequences:

**(a) Real MC lost.** `execute.py` builds the app payment from the engine's arithmetic, and the
app accepts a submitted payment without refunding an overpayment. Ore Processor (cost 13) paid
with 3 steel: the engine computed `13 − 3×2 = 7` and sent `{steel: 3, megacredits: 7}`. With
Advanced Alloys the card needed `13 − 3×3 = 4` MC. Post-send verification showed MC 7 where
the step predicted 10 — and **`verify: engine == app` still printed OK, because both sides used
the same wrong number.** That is the dangerous part: the reconciliation cannot catch an error
shared by both models. Repeated on Space Elevator (4 steel+titanium spent) and Interstellar
Colony Ship (4 titanium). Estimated total leak ~10 MC across the game.

**(b) Plan composition blocked.** `planlib set_plan` refused a correct step —
`ERROR: Plan step 2a is not executable: Need 17 MC, have 14` — for a Space Elevator play the
app would have charged 13.

**Suggested fix:** make the metal values per-player lookups that add the tableau's metal bonus,
used by *both* the affordability check and `execute.py`'s payment builder. Failing test first:
a player holding Advanced Alloys paying a 13 MC building card with 3 steel owes 4 MC, not 7.

## 2. The documented workaround for (1) is itself blocked

`tmlib.play(cost=…)` exists to pin a price, and the docstring says "--cost pins the price".
But `execute.py` cross-checks the step's cost against the app's `calculatedCost` and refuses:

```
ASK: price disagreement for Space Elevator: engine/step 23 MC vs app calculatedCost 27
     — fix the step's cost ... before sending [nothing sent]
```

`calculatedCost` is the printed cost after *card* discounts, before metal — so pinning a cost
that accounts for metal always disagrees with it. I had to abandon the pin and absorb the
overpayment. (The pin *did* work in one case where it coincided with a genuine card discount:
Designed Microorganisms after Indentured Workers, pinned to 8, matched `calculatedCost` 8.)

**Worth noting for whoever fixes #1:** these two interact. Fixing the metal values makes the
pin unnecessary; leaving them broken means there is currently *no* correct way to pay a card
with metal while a modifier is in play.

## 3. Multi-tile cards only consume the first placement

Ice Asteroid places **two** ocean tiles. The step carried two `place` events, but
`execute.py plan_actions` attached only the first as the action's `space` follow-up and then stopped:

```
ASK: the app asks a 'space' follow-up ('Select space for second ocean') the step does not cover
```

Recovered with `execute.py resolve 1b --space 13`, which worked cleanly. Low severity, but any
two-ocean card (Ice Asteroid, Giant Ice Asteroid, Artificial Lake-class effects) will hit it.
`plan_actions` should queue *all* trailing `place` events for one actionable event, not just one.

## 4. The pass gate worked, and cost four round trips

The gate refused my pass four times because the pre-declared `force` reason did not enumerate
every live menu item. **It was right every time**, and twice it caught something genuinely
valuable I had overlooked:

- **Space Elevator's action** (1 steel → 5 MC) — I had not registered it as a repeatable income
  source. Once found, it funded a card in three separate generations.
- **Small Animals' action** (add 1 animal, free, 1 VP per 2 animals) — worth 2 VP by game end,
  and I would have skipped it entirely.

So this is friction, not a defect: the gate paid for itself. The brittleness is that the reason
string must pre-enumerate blue-card actions that only appear once a card is in the tableau, so a
`force` written at plan-composition time is stale by the time the pass is reached. A gate that
listed the live items *in the refusal* (it does) and let the reason cover them by category
("all repeatable card actions are spent this generation") would cost fewer round trips.

## 5. Plan-composition refusals that arrive late

Two `set_plan` rejections came only after composing a full multi-step plan with a long threats block:

- `Plan step 1b is cue-gated (place event) but has no "cue"` — the cue requirement is only
  enforced at submission, so a whole plan is rewritten for one missing field.
- `'Small Animals' requirement not met: closed — opens later (min 6% O2, now 5%)` — correct and
  useful, but it means a *conditional* step ("play this if his greenery opens the window before
  my last turn") cannot be pre-composed at all; it has to be patched in later.

## 6. ROOT CAUSE OF THE SPEED GAP — a 214 ms mDNS connect penalty on every request

Measured after the game, against the `appUrl` this session was configured with:

```
              namelookup /  connect  / starttransfer /  total
mDNS host   :    0.005s  /  0.214s   /    0.219s     /  0.220s
raw LAN IP  :    0.001s  /  0.005s   /    0.010s     /  0.010s
```

**25x per request — and it is not name resolution.** Lookup is 5 ms either way. It is the TCP
*connect*: 214 ms against 4.9 ms, the signature of dual-stack fallback (the mDNS responder
offers an IPv6 link-local address first, the connection stalls, and IPv4 is retried after the
~200 ms Happy Eyeballs delay).

`setup.json` was configured with the `.local` hostname I was given, so every HTTP call the
harness made paid that toll. At 128 blocking harness calls — each issuing several requests —
this alone accounts for essentially the entire 7.5 minutes of round-trip time recorded below.

**Fix (configuration, no code change):** put the resolved IP in `setup.json`'s `appUrl` rather
than the mDNS name. Worth having `scripts/server.py status` or `setup.py` warn when `appUrl`
is a `.local` name and the resolved address answers materially faster.

## 7. Wall-clock accounting

From `raw/latency-digest.json`, 260 marks:

| Phase | Calls | p50 | p95 |
|---|---:|---:|---:|
| `listen` | 71 | 3083 ms | 4100 ms |
| `execute` | 57 | 4139 ms | 8260 ms |

≈ **7.5 minutes of blocking harness time** across 128 calls, before any model thinking. The
opponent was materially faster throughout. The breakdown of *why*, honestly:

- The bulk is structural and correct: one `listen` per opponent turn and one `execute` per action,
  each a real HTTP round trip against a LAN server.
- The avoidable part is the **~10 extra round trips** from items 1–5 above, plus several
  `ASK: NOT WAITING` responses where I batched an execute behind a wait and the opponent's turn
  had not finished.
- The rest is deliberate: full threat analysis, `planlib` simulation and per-step verification
  every generation, as the repository contract requires. The user explicitly confirmed
  mid-game that this discipline should **not** be traded away for speed.

**Revised conclusion after item 6:** the planning discipline was not the main cost. At ~214 ms
of dead connect time per request, the transport alone accounts for the bulk of the round-trip
total. When asked mid-game why I was slow I attributed it to my own process and to harness
friction; that answer was incomplete — the largest single factor was one line of configuration,
a `.local` hostname where an IP address belonged.

## 8. Non-defect: one strategy tool answered a question it was not built for

`payback.py` rejected Nitrogen-Rich Asteroid at "−6 MC net; needs 17 gens, only 14 left". That
verdict is correct *for a production card* — the card's +1 plant production genuinely does not
pay back. But the card's real value was **+3 TR of tempo**, which payback.py does not price at
all, and I took its verdict as a verdict on the card. Tooling worked as designed; the advisor
misused it. Captured as a KB recommendation rather than a bug.
