# Adversary ladder

Practice opponents for app-practice mode, from trivial to real. The level is
chosen per run (`autoplay.py run <pid> --level <passer|greedy|competitive>`)
and RECORDED in the eval ledger (`evalprotocol.py record --bots …`). A win
against dummies is harness validation, never strategy evidence — never
aggregate results across tiers.

## External bots (assessed, not integrated)
- jankeromnes/terraforming-mars-bot targets an old fork of the engine and
  imports build artifacts that no longer exist upstream; the app's input
  protocol has since moved to typed `waitingFor` JSON (what sparring.py
  speaks). Direct integration would be a porting project. Worth mining:
  `bots/quantum.js`, a heuristic policy (card scoring, placement
  preferences) whose ideas can be lifted into autoplay personas.
- recurrsive/OpenTF and SliceOfBread/tm are research-grade or partial (the
  latter reportedly does not play cards). Same conclusion: the autoplay
  harness is the maintained path; external bots are idea sources.

## Levels

0. **passer** — keeps nothing, passes every turn. Pure harness-mechanics
   testing (deterministic, fastest).
1. **greedy** (v2, current default) — heuristic policy: clock-derived
   horizon (v1 hardcoded the generations left, which made every production
   card score negative, so bots kept 0 cards and passed all game), a card
   value model, standard-project fallback so banked cash buys TR
   (asteroid → aquifer → greenery ladder), milestone claims, conversions.
   A mediocre-but-active opponent; the regression-test adversary.
2. **personas** (planned) — greedy v2 with rush / engine / denial biases;
   mine quantum.js for scoring ideas.
3. **competitive** (v1) — model-piloted seats: an LLM plays each seat's
   turns. `--level competitive` REFUSES to autopilot; each seat is a
   sparring-partner SUBAGENT that sees only its own playerId (a structural
   information firewall — the advisor never sees a seat's hand). Protocol
   in agents/sparring-partner.md. Cost: one subagent dispatch per bot turn
   (~30-40 per game per seat) — use for eval games, not smoke tests.
   Known structural weakness: a fresh context per generation means no
   cross-generation planning.
3b. **competitive-v2** — same models, persistence fixed: ONE agent per seat
   for the whole game (message continuation each generation), doctrine in
   agents/seat-kit.md (standing plan, milestone/award racing, seat-safe
   calculators payback.py / odds.py / clock.py --state). Similar or lower
   token cost than v1 (context reuse beats knowledge-base re-reads). Ledger
   tier `--bots competitive-v2` — never aggregate with v1 results.
3c. **competitive-v2, context-refreshed** — same doctrine, different
   lifecycle: a FRESH agent per seat per generation, seeded with a compact
   public digest built from the seat's own last report (never the raw
   transcript). Motivation: persistent seats' per-generation latency climbs
   as their transcript grows; refresh keeps it flat. Cost: the seat's
   private cross-generation plan is lost each refresh, so it plays slightly
   more reactively. Ledger: still `--bots competitive-v2` (the doctrine tier
   is what is measured; note the lifecycle in `--notes` when it matters).
3d. **competitive-v2 on a small model** — the context-refreshed doctrine
   with seats on a cheaper, faster model. Purpose: (a) many-player evidence
   at a fraction of the time and cost, (b) a model-tier anchor: if small
   seats still beat the advisor, the gap is harness/strategy, not model.
   Ledger: `--bots competitive-v2` with the seat model in `--notes`; never
   aggregate with games on other seat models without splitting on the note.
4. **symmetric harness** (shipped: `session.py seat-init`, every verb takes
   `--state seats/<pid>`; an instrument rather than an adversary) — seats run
   the advisor's full decision loop on their own state folder.
   Purpose: clean experiments (model A/B with an identical harness; harness
   ablation with identical models), not stronger sparring. The state layer
   is redundant for app seats (the server already tracks their state
   exactly), so this rung is built when such an experiment is scheduled.
5. app-online mode against real people on a hosted instance.
6. The physical table — the actual goal.
