# Diagnostics and failures

No failure changed the authoritative app state or required a game undo. The app remained the rules engine and every mismatch was reconciled by adoption.

## Network and setup

- The supplied `.local` hostname resolved inconsistently and returned `No route to host` from the execution environment.
- Direct access to the same host's LAN address succeeded. The session stored that reachable base URL locally; committed artifacts redact it.

## Executor and prompt-shape mismatches

1. **GHG Producing Bacteria branch ordering.** In generation 8, tracker choice `1` predicted “remove two microbes,” while the live app interpreted index 1 as “add one microbe.” The app state was adopted, leaving temperature unchanged and GHG at three microbes. A private bug was filed during play; no harness fix was attempted.
2. **Immigrant City gross price.** A step recorded 8 MC after two steel, while the app correctly advertised gross calculated cost 12. The executor refused before sending. The step was patched to gross cost 12 plus two steel, resulting in the intended 8 MC payment.
3. **Comet and Giant Ice Asteroid removal prompts.** The app represented plant removal as an `or` menu, not a player selector. Both cards were already safely sent; `execute.py resolve` selected red and completed the steps.
4. **Multi-ocean follow-ups.** Giant Ice Asteroid required separate resolution for its second ocean and subsequent removal selector. State remained consistent throughout.
5. **0°C threshold ocean.** GHG's temperature step opened an unplanned free-ocean prompt. It was resolved on hex 04, and the plan was patched around the extra TR/ocean.

## Planning and workflow issues

- A conditional Insects step was rejected because oxygen was still 5%; the corrected draft omitted it until the requirement opened.
- Local Heat Trapping's bespoke +4 plants were not modeled by the deterministic card behavior. Adding an explicit tracker resource event made the simulated plan match the app.
- Two plan submissions failed due shell quoting/formatting. One created eight empty, untracked root files; those files were identified as agent-created garbage and removed before commit.
- The raw acquisition evaluator valued Imported Hydrogen as an ocean even after oceans were maxed. Context correctly overrode the recommendation.
- The Business Contacts evaluator favored Asteroid Mining over Earth Catapult. The advisor overrode it; Earth Catapult remained unplayed. This is a strategic judgment miss rather than a harness failure.

## What worked as designed

- Pre-send validation prevented the Immigrant City cost error from reaching the app.
- App adoption corrected bespoke effects and threshold bonuses without blocking play.
- The pass gate surfaced technically available but strategically negative actions such as late Pets.
- The information firewall held: no opponent player identifier or hidden hand was accessed.
