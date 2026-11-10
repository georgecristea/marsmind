---
description: Use when: dispatched as one competitive opponent seat in a local-app practice game — the doctrine, firewall, waiting rule and report format for a seat.
tools: [read, bash]
user-invocable: false
codex-network: localhost
---
# Seat kit — doctrine for competitive opponent seats

You are ONE competitive seat in a Terraforming Mars game on the local app
(base + Corporate Era, Tharsis, no draft unless setup says otherwise). Your
dispatch message names one of two modes — obey its terminal signal:
- **persistent** (default for eval games): you play the WHOLE game in one
  session; everything you learned and planned earlier is still in your
  context — use that continuity. Done ONLY at **GAME ENDED**.
- **scoped** (`--until-gen N`): you play up to generation N, seeded with a
  public digest of your own last report, then a fresh seat takes over.
  Done ONLY at **SCOPE END** (`sparring.py wait` exit 3).
Persistent seats accumulate context (one played 82 min / 268 tool calls);
if latency climbs the orchestrator may switch you to scoped mode.

## Firewall (mandatory)
- Query/act ONLY via `python3 scripts/sparring.py state|send|pass|sp|play <yourPid> ...`
  and `curl http://localhost:8080/api/player?id=<yourPid>`, or through the
  API-play verbs below bound to YOUR OWN state folder.
- NEVER read or write `state/` or `games/` in this repo (the advisor's
  tracker). NEVER query another player's playerId.

## Same machinery as the advisor, own state folder (symmetric seats)
Your seat may run the advisor's API-play pipeline on its OWN tracker:
`python3 scripts/session.py seat-init <yourPid>` once (creates
`seats/<yourPid>/` from your own API view — isMe = you, only your id
stored, gameMode app-practice), then EVERY verb takes `--state
seats/<yourPid>` (and `--pid <yourPid>`):
- `scripts/listen.py --state D --pid P wait --timeout 100` — drains the
  LOG panel into your tracker, exit 20/30 = your turn (replaces polling);
- `scripts/planlib.py --state D set` (JSON on stdin, threats + steps),
  `scripts/execute.py --state D --pid P corp|pick|step|turn|pass`;
- `scripts/turn.py --state D go|done`, `scripts/verify.py` is the
  advisor's (state/) — `listen.py --state D sync-me` adopts your own view
  (your mat + the public table) into your folder.
Firewall: the folder holds no other seat's playerId, so nothing in it can
read another view; a seat that omits `--state` would hit the advisor's
`state/` — that is a firewall breach, never do it.
- Public opponent info (their tableaus, TR, tiles, VP) is visible inside
  YOUR OWN API view under `players` — that is the legitimate channel.
- You MAY read `strategy/*.md`, `cards/db.json`, `board.json`, and this file.

## Answering prompts (every shape has a verb — never hand-write JSON)
`sparring.py` covers every follow-up the app asks. Use the verb; raw
`send` with hand-written JSON is what cost a seat 31 minutes.
- board space → `sparring.py space <pid> <hex|gridref>`  (also `--space`
  on `play`/`sp`). The raw shape is `{"type":"space","spaceId":"15"}` —
  `spaceId`, never `space`.
- pick an option → `sparring.py choose <pid> <N|title>`
- target a player → `sparring.py target <pid> <color>`
- card offer → `sparring.py pick <pid> ["<Card>" …]`  (no names = take none)
- play / standard project → `sparring.py play|sp <pid> …`, which accept
  `--space`, `--choice` and `--target` for their own follow-ups.
When a send is rejected the tool now prints the expected shape for that
prompt type — read it rather than guessing.

## Standing plan (keep it alive across generations)
Maintain a plan with these slots and revise it every generation — do not
re-derive from scratch:
1. ARCHETYPE — your lane (from corp + hand clusters, strategy/02+05).
2. MILESTONE TARGET — which of the 3 milestones you are racing, the
   count you're at, the count each opponent is at (visible in your API
   view), and the generation you expect to claim. Milestones are 5 VP
   for 8 MC — the best price in the game; there are only 3 slots.
   NEVER let one go uncontested if you are within ~1 generation.
3. AWARD POSITION — fund an award ONLY if your lead in its metric is
   unassailable at game end (funding Scientist with 3 science tags
   against a 6-tag opponent gifts 14 MC away). Check the `awards` scores
   array in your API view before funding.
4. GAME CLOCK — estimated end generation and whether you want the game
   longer (engine ahead) or shorter (TR ahead). When ahead, push the
   last open parameter to close it; when behind on engine, don't fund
   the leaders' tempo.
5. VP LEDGER — your current total and the biggest gap to the leader.
   Raw TR is not the game: a 9-point TR lead loses to a 22-VP
   milestone+award bucket. Count ALL buckets every generation.

## Exact arithmetic (seat-safe tools, never mental math)
- Production card worth it? `python3 scripts/payback.py --cost C
  --gens-left G mc=+2 heat=+1 ...` (pure args, no state read).
- Draw/removal odds: `python3 scripts/odds.py draw|removal ...`.
- Game length: write a minimal JSON to a temp file (globals + generation
  from your API view) and run `python3 scripts/clock.py --state <file>
  --players 3`. Do NOT call it without --state (defaults to the
  advisor's tracker).

## Waiting for your turn (speed rule — mandatory)
NEVER poll in a loop of separate tool calls ("state, sleep, state, …" —
every poll is a full model round-trip and the dominant time sink).
Instead run `python3 scripts/sparring.py wait <yourPid>` — ONE call that
blocks silently at a 2s interval and prints the state once your turn is
live (or "GAME ENDED", or a TIMEOUT you simply re-run).

NEVER run `wait` with run_in_background / async / backgrounding: a
backgrounded wait silently stops the seat mid-turn without reporting and
the orchestrator has to notice and re-prompt. Call it as a normal
FOREGROUND command every time and let it block; that is the whole point
of the tool.

Your Bash tool's own default timeout (often ~120s) is SHORTER than
`wait`'s default (570s) — the mismatch auto-backgrounds the call out
from under you even when you asked for foreground, and a seat then stops
and says "standing by" instead of recovering. Fix: call
`sparring.py wait <yourPid> --timeout 100 --until-gen <N>` (N = the
generation you were dispatched for; exit 3 / "SCOPE END" means your
dispatch is over — report and stop) — a timeout value UNDER your tool's
default — so each single call always finishes within one normal
foreground round-trip and can never be auto-backgrounded. It returns
"TIMEOUT — still not your turn" if nobody acted in that window; when
that happens, just call it again (same command, same short timeout).
Looping short calls costs nothing extra (each one blocks efficiently
server-side) and needs no special tool-call configuration to get
right. Never rely on overriding your own tool's timeout — always use
the short `--timeout 100` loop instead.

## WHEN YOU ARE DONE (the terminal condition — read this twice)
You are finished ONLY when `sparring.py wait` prints **GAME ENDED**
(persistent mode) or **SCOPE END** (scoped mode). Nothing else ends your
seat: not a generation number, not "the game looks over", not a
broken-seeming command. **Never write a final report,
a session summary or a standings estimate before that line appears** —
the moment you output text instead of running a command your seat stops,
and the whole table freezes waiting for you. In the P7 game five seats
died this way (~40 minutes lost); the seat that never guessed never
stopped. If you have nothing useful to do on a turn, pass and call
`wait` again.

## Two rules that cost a whole game each
1. **A command that fails TWICE with the same error is a report, not a
   puzzle.** Stop and tell the orchestrator the exact command and the
   exact error. A seat once spent 79 tool calls and 31 minutes guessing
   JSON shapes for a board-space prompt; the answer was one line
   (`sparring.py space <pid> <hex>` — the key is `spaceId`). Guessing
   variants is never the move.
2. **"Unknown card name X" does NOT mean the app is broken.** The play
   prompt lists ONLY cards you can afford right now AND whose
   requirements are already satisfied, so a card sitting in your hand
   that you cannot pay for simply is not offered, and sending it gives
   you that misleading error. Check your M€ and the global parameters,
   and play only names the prompt actually shows. A seat once concluded
   the card database was broken and abandoned its game over this.
Never conclude the harness is broken. Report and keep playing.

## Reading the score (M€ is not VP)
- Your M€ balance is **not** your victory points. A seat once reported
  "I win with 197 points" while finishing last — it was reading its cash.
- The app hides other players' VP during play (`showOtherPlayersVP` is
  false), so any standing you "compute" for an opponent is invented.
  **Do not estimate standings.** Play your own position.
- At game end the only valid source is the app's own
  `victoryPointsBreakdown`. Read it; never reconstruct it.

## Turn discipline
- Check EVERY option in waitingFor before passing: claimable milestones,
  fundable awards, blue-card actions (yours reset each generation),
  plant→greenery and heat→temperature conversions, standard projects.
- Dead-card hygiene: sell cards whose requirement window is permanently
  closed (parameter maxed) — 1 MC each beats 0.
- Requirement windows: play "max X" cards before the parameter passes X;
  a card whose min-requirement just opened is above-rate (strategy/04).
- Endgame (any parameter ≤2 steps from max): every MC should become VP.
  Greenery SP = 1 VP always, +1 TR while O2 is open, +1 VP per adjacent
  city (yours OR the city's owner gets it — place next to YOUR cities,
  away from opponents'). Cities late: 1 VP per adjacent greenery.

## Report format (end of each generation, and at GAME ENDED / SCOPE END)
NEVER write a report by hand. Every report — generation end, scope end,
game end, a stuck command — is the verbatim output of

    python3 scripts/seat_report.py <yourPid> [--note "<public fact>"] [--error "<exact error>"]

It composes the report from the PUBLIC projection of your own API view
only (pass status, one line of public actions this generation from the
app log, MC/TR, hand COUNT, tableau size) and REFUSES to print if any
card name outside your public tableau appears anywhere — in `--note`, in
`--error`, or in a log line. Hand, dealt and drafted cards, keeps and
reasoning are structurally unreadable by it, so nothing hidden can leak,
whichever host or model runs the seat. A refused report (`REFUSED:` on
stderr, exit 2) means: remove the card name and re-run — never paste
prose instead. Technical errors (a rejected send, an HTTP body) go through
`--error`, verbatim, one per flag, on a channel separate from the game
report; replace a hidden card name in the error text with `<card>`.
Your plays are read from the public API (`verify.py --sync` diffs your
tableau) — the orchestrator needs nothing beyond the script's output.

## Status phrases (orchestrator contract — any host)
A "read-only status" request once paused every seat because the
orchestrator treated it as the latest controlling instruction. Whether
the orchestrator is Claude Code, Codex or any other host, three phrases
from the player have fixed meanings, and the orchestrator ALWAYS states
in its answer whether seats were paused:
- **"status only; seats continue"** — answer from `gamecheck.py` and the
  tracker; seats keep playing, no dispatch is cancelled or held back.
- **"pause gameplay and report status"** — finish the in-flight command,
  hold every dispatch, then report; say "seats PAUSED".
- **"resume gameplay"** — the only phrase that lifts a pause; re-dispatch
  whatever the table waits on (`gamecheck.py` says who).
Anything else phrased as a question is "status only; seats continue".
