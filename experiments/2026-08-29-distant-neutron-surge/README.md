# Distant Neutron Surge — a blind model-vs-model experiment

**2026-08-29 · two-player Corporate Era / Tharsis, no draft · online app, full-API autopilot**

## What made this run unusual

Two independent advisor sessions played the same online game against each other through the
**same Phobos harness**, from the **same prompt**, each in its own session with its own hidden
hand — and **neither was told the opponent was an AI.** Both were given invented human names and
both played the whole game believing they faced a person. Neither had access to the other's
state, reasoning, or repository session. Both wrote their post-game artifacts *before* learning
the truth.

| Seat | Corp | Model | Artifacts |
|---|---|---|---|
| Maxwell (red) | Mining Guild | **Opus 5** | [`maxwell-red-opus5/`](maxwell-red-opus5/) |
| Mortimer (blue) | Ecoline | **Codex, GPT-5.6-Sol (high reasoning)** | [`mortimer-blue-codex/`](mortimer-blue-codex/) |

**Result: Mortimer 92 — Maxwell 66.** Twelve generations.

| | TR | Milestones | Awards | Greenery | City | Cards | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mortimer (Codex) | 58 | 10 | 0 | 11 | 10 | 3 | **92** |
| Maxwell (Opus 5) | 27 | 5 | 15 | 3 | 3 | 13 | **66** |

Because both sides wrote up the same game blind, the two folders can be read against each other:
where they agree, the evidence is cross-validated; where they disagree, the disagreement is
itself informative.

---

## Question 1 — is this proof that one model is better?

**No. Not close to it.** It is one game with uncontrolled starting conditions.

**What is genuinely confounded:**

- **The corporations were not comparable, and were not chosen from a common pool.** Maxwell was
  offered UNMI and Mining Guild; Mortimer was offered Ecoline. **Ecoline is a terraforming engine
  by construction** — plant production converts to greeneries, greeneries raise oxygen, oxygen is
  TR. **Mining Guild contains no terraforming whatsoever**; it is a steel-and-buildings economy
  corp. The single axis this game turned on (TR tempo vs cash engine) is partly *supplied by the
  corp draw*. That is a very large confound sitting directly on the causal path.
- **Every research offer differed** for twelve generations. Mortimer was offered Mohole Area in
  generation 1 — 4 heat production for 20 MC, the card that produced roughly a third of their
  38 TR. Maxwell was never offered anything comparable.
- **n = 1.** No replication, no seat swap, no shared seed.

**What the game does support, and this part is not luck:**

- Maxwell made a **decision** error that no card draw forced: with Ore Processor in hand — a
  repeatable +1 TR every generation — it was abandoned in generation 4 after a single Energy
  Tapping, and then its input (energy production) was dismantled by two later plays. Maxwell's
  terraforming rating was still **20, its starting value, at the end of generation 9 of 12**.
  Mining Guild is a mid-tier corp, not a losing one; a strong line with it still buys terraforming.
- Maxwell also **wrote the diagnosis and did not act on it**: the generation-7 threat block says
  "the pivot from engine to TR must happen no later than gen 5", and generations 7–8 then spent
  ~44 MC on milestone enablers and award funding.
- Mortimer made a comparable-in-kind but far smaller error, self-reported in their own artifacts:
  Earth Catapult taken over Asteroid Mining from Business Contacts, then never played.

**Honest verdict:** this is **one observation of a decision-quality gap on one specific axis** —
pricing global-parameter tempo against a cash engine — with a corp draw that pushed both players
toward exactly those poles. It is a reason to run the experiment properly. It is *not* a model
ranking.

**To turn this into evidence, the next runs need controls.** Proposed design in
[`experiment-design.md`](experiment-design.md): mirrored corp assignment, seat swap, and several
games before any claim is made.

---

## Question 2 — why was the opponent so much faster, and should we switch models tonight?

**86% of the speed difference was network transport. It was not thinking.** And it was our side's
configuration, not their model.

Both seats emit `latency.jsonl` start/end marks around every harness call, so this is measured,
not inferred:

| | Maxwell (Opus 5) | Mortimer (Codex) | ratio |
|---|---:|---:|---:|
| `execute` p50 | 4139 ms | 261 ms | **15.9×** |
| `listen` p50 | 3083 ms | 171 ms | **18.0×** |
| **Total harness time** | **498.3 s (8.31 min)** | **39.8 s (0.66 min)** | **12.5×** |
| App clock (turn wall time) | 48.31 min | 39.43 min | |
| **App clock minus harness ≈ thinking** | **40.01 min** | **38.76 min** | **1.03×** |

**Decomposition of the 8.89-minute gap: 7.64 min transport (86%), 1.24 min everything else (14%)
— about 6 seconds per generation.**

### The cause

`state/setup.json` for the Maxwell seat carried `appUrl = http://<lan-host>.local:8080`.
Mortimer's environment could not route that mDNS name at all, so that seat fell back to the
host's raw LAN address. Measured afterwards on the same LAN, same server:

```
              namelookup /  connect  / starttransfer /  total
mDNS host   :    0.005s  /  0.214s   /    0.219s     /  0.220s
raw LAN IP  :    0.001s  /  0.005s   /    0.010s     /  0.010s
```

**Name resolution is 5 ms either way — the 214 ms is the TCP connect**, the signature of
dual-stack fallback (the mDNS responder answers with an IPv6 link-local address first, the
connection stalls, IPv4 is retried after the ~200 ms Happy Eyeballs delay). `appapi.py` opens a
**fresh connection per request**, so that toll was paid on every single call: a listener drain
issues ~14 requests, which is exactly 14 × 220 ms ≈ 3080 ms, matching the observed p50 of 3083 ms.
Mortimer's identical drain cost 171 ms.

The competitor did not have a faster loop. **They accidentally had a working one.**

### Answer for tonight

**Switching models for speed is not supported by this evidence.** The measured thinking-time
difference is ~6 s per generation, which is noise next to a 214 ms per-request tax paid thousands
of times. **The fix is one gated change in `appapi.py`, already shipped and tested** (see
[`implementation-plan.md`](implementation-plan.md) item H1): a `.local` host is resolved once to
its IPv4 literal and dialled by address, falling back to the name if the literal stops answering.
On the numbers above this should take the Maxwell-seat harness time from ~498 s to ~40 s and make
the two seats' wall clocks essentially equal.

If you want to run the competitor model, do it because you want more model evidence —
**not because this game showed it plays faster. It didn't.**

### Postscript: the LAN answer was not the important one

This game was hosted on a third machine on the same LAN. Future games are over the
internet, where the `.local` fix does nothing — and where the *underlying* defect it exposed
gets far worse. `appapi` opened a **fresh connection per request**, and over the internet each
request then pays a TCP handshake *and* a TLS handshake before any data moves. Measured
against the host used for the previous online game night: **455 ms fresh against 112 ms
reused, ~1800 requests a game, 13.7 min of transport against 3.4 min.** Connection reuse is
now shipped (`implementation-plan.md` P0), which matters more for how games will actually be
played than anything the mDNS measurement produced.

---

## Where the two write-ups agree — cross-validated harness findings

These are the strongest harness signals in the whole exercise, because two independent sessions
hit them without any shared context:

| Finding | Maxwell | Mortimer |
|---|---|---|
| **Multi-tile cards place only their first tile** | Ice Asteroid stalled on "Select space for second ocean" | Giant Ice Asteroid needed separate resolution for its second ocean |
| **Gross-vs-net card price refusals in the executor** | Space Elevator cost pin refused against `calculatedCost` | Immigrant City step recorded net 8 MC, app advertised gross 12 |
| **The `.local` host is a problem** | 214 ms connect penalty per request | "returned `No route to host`" — had to use the LAN address |
| **Conditional plan steps cannot be pre-composed** | Small Animals refused at 5% O2 | Insects refused at 5% O2 |
| **The pass gate earns its keep** | surfaced Space Elevator + Small Animals actions worth ~2 VP and three cards | surfaced late Pets as a negative action |

Two of these are fixed in this pass; the rest are triaged in the implementation plan.

## Where they disagree

- **On the award sweep.** Maxwell's write-up treats 15–0 on awards as the best 42 MC of the game.
  Mortimer's treats it as an exploitable over-commitment: *"Maxwell spent 42 MC funding all three
  awards and earned 15 VP. Mortimer spent 16 MC on two milestones and earned 10 VP, then
  redirected the 26 MC difference into parameters and tiles."*
  **Both are right, and the synthesis is the actual lesson.** The awards were not a mistake — the
  VP-by-generation curve shows the gap at its narrowest, −4, in generation 7 exactly when they
  landed. The mistake was treating them as the *plan* rather than as a supplement to a
  terraforming engine that was never built. A one-off VP purchase has a ceiling; an engine does not.
