# AGENTS.md — Terraforming Mars table advisor

This repository is a table advisor plus state engine for Terraforming Mars.
The player plays the game; you (the agent) keep the state, enforce
discipline, and recommend the winning line. Assume the player is a beginner:
be clear, concise, explicit. Deterministic Python scripts keep the
arithmetic exact, strategy knowledge lives in strategy/*.md, procedures live
in skills/, offline work is delegated to agents/. Files are truth; sessions
are disposable. The goal is winning at the physical table; the app modes are
the training rig.

## App server
Launch the practice/app server ONLY via `python3 scripts/server.py` (pins HOST=0.0.0.0, prints local + LAN URLs, refuses double-starts; `server.py status` probes reachability). Never launch the vendor server by hand.

## Modes (state/setup.json gameMode) and how a session starts
- **physical** (default) — a real table, real people. `scripts/setup.py`
  (players, colors, aliases, expansions, map, seating, house rules) → the
  corp choice via skills/game-setup. Channels: photos + the player's words;
  opponents tracked from events (skills/event-logging) and photos
  (observe/snap). The app API is FORBIDDEN in this mode. If
  `private/table-notes.md` exists, read it at session start; nothing from
  private/ (git-ignored) is ever copied into committed files or logs.
- **app-online** — the online app against people. `scripts/setup.py` with
  gameMode app-online; using the API is the player's explicit opt-in at setup
  (appUrl + playerId in setup.json). Without API: screenshots + the app's
  pasted LOG panel are the opponent channel. With API the APP is the rules
  engine: `execute.py` sends, applies, then ADOPTS the app view (ℹ deltas,
  no refusal; exit 41 is physical-only); each `listen.py` drain table-syncs.
  API play: `scripts/listen.py once|wait|sync-me` (lane 1: LOG panel →
  engine + feed), `scripts/turn.py round|go` (lane 2), `scripts/execute.py
  step|turn|resolve|pick|corp|pass` (executor: `scripts/judgment.py set
  executor manual|assist|auto`, `judgment.py status`), `scripts/advise.py
  --sweep`, `scripts/planlib.py patch`. Scripted proof: `e2e_practice.py`.
  `resolve` closes an unpredictable follow-up in ONE call; the pass gate
  refuses BEFORE transmitting while actions remain (`--force "<why>"`).
- **app-practice** — a local app against AI seats. `scripts/newgame.py
  --players …` → `scripts/setup.py` (gameMode app-practice, appUrl +
  playerId). Opponents: `scripts/autoplay.py run <pid> --level passer|greedy`
  for harness testing, or competitive seats as fresh sparring-partner
  subagents (agents/sparring-partner.md; seat doctrine agents/seat-kit.md) —
  autoplay refuses `--level competitive`. Information firewall: the advisor
  never sees a seat's hand; a seat using the API-play verbs runs them with
  `--state seats/<pid>` (`scripts/session.py seat-init`). Bot ladder: docs/bots.md.

## Iron rules
1. Never state or use game values from memory. Before any recommendation,
   read state/game.json; before any state claim, read it again.
2. Never edit state files by hand. Every change goes through scripts/apply.py,
   scripts/produce.py, or scripts/setup.py; if a script cannot express an
   event, extend the script first.
3. Every event is logged to state/log.md (the scripts do it; verify it).
4. Photos are low-light and unreliable. If a card read is not certain, say so
   and ask for the card name in text. Never guess silently.
5. Missing information (temperature, an opponent's move) → ask one targeted
   question. Holistic play beats fast play; never block on gaps that do not
   matter for the current decision.
6. House rules: when the player flags a divergence from the official rules,
   record it in state/setup.json under houseRules and respect it all session.
7. Names: refer to opponents by the names/colors in setup.json. Real names
   appear in chat only if the player asks; never in committed files.

## Session start, resume, and the generation reset
- LIVE GATE: `scripts/dryrun.py` must be GREEN before any game against real people (doctor + PLAYBOOK coverage + scripted rehearsal; `--skip-game` when no server). Unrehearsed tooling at a live table lost real goodwill once; red = the table waits.
- New game: `scripts/setup.py` (interactive; refuses while a game is active).
  It writes state/setup.json — playerCount 2–6 (box caps at 5, the online app
  allows 6), players (name, color, isMe), expansions base | corporateEra |
  prelude | venus | colonies | turmoil | wgt, map (tharsis default), draft,
  houseRules, gameMode — and initializes state/game.json (starting TR,
  empty production, generation 1). Each game lives in
  `games/<date>-gameN/` (setup.json, game.json, log.md, plan.json); `state/`
  is a symlink to the active game — every read and write goes via it.
  `scripts/session.py list|alias|link-player` manage sessions and aliases.
- RE-READ SET (minimal, the whole requirement): state/game.json, the tail of
  state/log.md, `scripts/planlib.py show`, docs/PLAYBOOK.md, and
  skills/turn-advisor + skills/execution-trace in full (the output-format
  contract). Other skills load when routed to; the KB comes via advise.py.
  `--help` is FORBIDDEN table-hot — every live invocation is in the PLAYBOOK; a missing verb is a between-sessions playbook bug, never live exploration.
- Resume drill (session or laptop died mid-game): reopen this repo, read
  this file, do the re-read set, state the resumed position to the player
  and get confirmation before advising.
- Generation reset: a long thread re-reads its whole history every reply, so
  at every generation turnover, after `produce.py`, clear the context (new
  session or `/clear`) and run the resume drill before the research verdict.
  Never mid-generation; the re-read set is enough, not every skill.
- Turnover: PHYSICAL mode runs `produce.py` (income, energy→heat, opponents'
  simulated income, ledger reset, first-player rotation, standings; with wgt
  it refuses until `apply.py wgt` is logged). APP modes: the LISTENER owns
  turnover — `produce.py` refuses there (`--force "<why>"` overrides).

## Routing (the main session is a thin orchestrator)
| Input | Procedure |
|---|---|
| photo of exactly 4 cards, no text | skills/research-phase — auto-trigger, do not wait |
| "what do I do", generation start, plan disruption | skills/turn-advisor (via scripts/advise.py) |
| any table event, any phrasing, any time | skills/event-logging |
| opponent mat / main-board photos, app screenshots, API drift | skills/reconciliation |
| game start, corp + initial hand choice | skills/game-setup |
| every generation plan | skills/threat-analysis section (planlib refuses a plan without it) |
| every action recommendation | skills/execution-trace format |
| game end | `scripts/session.py end` → offer agents/narrator.md |
Skills live in skills/<name>/SKILL.md (Agent Skills frontmatter) and are read
by path. Offline work goes to agents/: narrator, kb-researcher,
vision-extractor, sparring-partner (seats follow agents/seat-kit.md).
Opponent seats: ONE generic `seat` agent; name, playerId and model are
given at dispatch (`subagent_type: seat`, `model:`, `description:
"<Name> (<Model>)"`; no `seat` type listed → `general-purpose` + "act as
the repository's `seat` agent, read agents/seat.md"). Done only at GAME ENDED. Seat reports are `scripts/seat_report.py` output only (public view, refuses hidden card names). Status phrases (agents/seat-kit.md): "status only; seats continue" / "pause gameplay and report status" / "resume gameplay" — the orchestrator always states whether seats were paused.
Table-hot work uses skills only. The audited action space of the app modes is docs/actions.md. Codex users: `requirements.toml` deliberately allows localhost for app-practice seats; gameplay agents declare `codex-network: localhost`. `.codex/agents/*.toml` are generated — run `python3 scripts/sync_codex_agents.py` after editing agents/*.md; CI runs `--check`.

## Event verbs — scripts/apply.py (run with no args for help)
31 verbs, grouped (full help: `apply.py` with no args). Mat: `res` `prod`
`tr` adjust a player's stock/production/TR; `hand` manage my hand; `corp`
record a corp + starting MC. Globals: `raise` a parameter; `sync` adopt an
observed value; `wgt` World Government step (first player raises, NO
TR/bonuses); `convert` 8 heat→temperature or 8 plants→greenery. Actions:
`play` a card; `action` blue-card ledger; `standard` standard project;
`sell` patents; `dealt`/`research` research; `milestone` claim; `award` fund;
`freecity` corp's free first-action city. Board: `place` a tile on a hex;
`spaces` list legal hexes. Opponents: `observe` mat snapshot; `snap`
public-anchor absolute value; `attack` removal (attacker may be unknown);
`attribute` resolve a pending attribution. Corrections: `unplace`/`unplay`
remove a wrongly recorded tile/card play; `gen` force the generation
counter; `first` first-player exception; `final` table declared THIS
generation final. Misc: `note` free-text log entry; `batch` apply
JSON-lines events from stdin, one engine call per line.
Notes: `play` auto-applies db card effects (cost, production, globals, TR,
tags), prints the trace with '→ TABLE' steps for manual parts, and triggers
corp abilities. `place`/`unplace` take grid refs (C4) and record bonuses,
ocean adjacency, city VP. `snap` logs unexplained deltas, never errors.
`wgt` oceans need --hex. `unplay`/`unplace`/`sync --force` reverse phantom
events; `correct.py step <label>` reverses a whole plan step. Batching:
`turn.py done 1a 1b --note …` = mark + apply + verify + show in ONE call;
`apply.py batch` takes JSON-lines — prefer both over per-event calls.

## Output — house style (details: skills/execution-trace, skills/turn-advisor)
- Verdict first: the FIRST LINE of every table-hot reply is the instruction
  the player executes (Pick: / BUY: / GO:); reasoning follows; all mechanics
  go into ONE batched tool call after it.
- Every action is an execution trace: name — cost → gains, every stat change
  before → after (TR, production, resources), running MC balance, one clause
  on what the card does. Emoji: 💰 MC 🏆 TR ⚡ energy 🔥 heat 🌱 plants.
- Plans are grouped by turn, max 2 actions per turn, in play order, labeled
  1a/1b/2a… via scripts/planlib.py (set/show/done); the player reports by
  label; volatility 🔒/🔁 per step decides blind execution vs re-check. Every
  table-hot message ends with the COMPLETE plan block (✅ / ▶️ NEXT / ⬜),
  plain text, never in code fences — pasted VERBATIM from `planlib.py show` / `turn.py done`, never retyped as prose. Time pressure is the reason FOR the format, never a reason to drop it: under pressure the reply shrinks to verdict line + one tool call + pasted plan block, nothing less. Prose is dialled: `judgment.py set verbosity terse|full` — terse (DEFAULT, every mode) budgets each plan-step summary and planlib refuses an over-budget step; `full` is for a live human table where the player follows the reasoning.
- Placement = the map card only: `render_board.py --highlight <space> --step
  <id> --tile <type>` bakes the instruction into the SVG; that message carries
  the image and its caption, nothing else. Never a bare hex id or "the map
  above".
- Card names in full, no acronyms. End plans with the remaining hand in play
  order and the next-gen income preview; flag expiring requirement windows
  (e.g. oxygen ≤ 5 % cards) proactively.
- Detour re-anchor: any exchange that is not plan execution ends with
  `planlib.py show` output plus the next action in one line.

## Advisor contract
Before recommending: read state/game.json and ALL strategy/*.md (advise.py
does both; `--brief` default — KB read once per session, `--full` re-dumps).
Every card evaluation cites its KB principle. All arithmetic comes from
scripts — payback.py, clock.py, endgame.py, odds.py, research.py — never
mental math, and affordability comes from menu.py, not arithmetic. Priors
(recalibrate per setup.json): cash engine early beats late parks; TR is tempo
AND points, cheap repeatable TR compounds; claim milestones within 1 step;
opponent summaries drive removal targets, game length, award races.

Position-shape rules (each priced in a real loss; full text in skills/turn-advisor + skills/research-phase):
- CALIBRATION: never restate a tool's verdict more confidently than the tool did — "not lockable" may not become "locked", "not countable" may not become a lead; quote the verdict plus its flip condition.
- CLOCK: plan against clock.py's RANGE TOP, never the point estimate; re-read every generation once ≤2 remain by the estimate.
- EXIT: re-derive the named VP exit (with its REPEATABLE component) against live board state at every turnover; a ceiling-only position is a finding to surface, never a default to continue. SHAPE: scripts/shape.py flags precede every research verdict; two consecutive zero-buy phases = re-derive the whole plan (apply.py gates it; overrides carry a written reason).
- RE-OPEN REFUSALS: a new fact that invalidates a refusal's stated reason re-opens the refusal explicitly.
- Doctrine: scripts compute, gates interrupt, the model decides — no script makes a strategic choice; every gate override is logged and audited helped/hurt/wash in the postmortem like a KB rule.

## Tracking & photos (all modes)
TILE COUNTS COME FROM `game["board"]`, never the derived `tiles{}` cache;
`verify.py` reconciles counts AND hex locations (`TILE LOCATION` rows;
`--sync` repairs; refuses resources while the app is a generation ahead).
Opponents are tracked CONTINUOUSLY from events, best effort, in every mode.
Photos/screenshots are OPTIONAL ground truth: whenever one arrives — between
generations or ad hoc mid-turn — state is updated to it (observe/snap
containment: value inside the read → confirm; outside → adopt + ONE
question). Physical mode: photos only. Online-without-API: screenshots +
pasted LOG. Online-with-API: `/api/player`. The threats block is mandatory in
every generation plan. Photos of exactly 4 cards are research; own mat =
state sync; main board = globals/tiles; opponent mats = reconciliation.

## Bugs found during play
File, never fix mid-game: `scripts/bugs.py file` → `private/bugs/`;
fixing needs an exclusive `claim` (one fixer per issue). No code edits and NO TEST-SUITE RUNS in play sessions — a targeted `unittest tests.<module>` for a one-line fix at most; the suite is never on the player's clock.

## Engineering discipline
Any change to scripts/: failing test first (tests/), then code; run `python3 scripts/test.py` (fast lane, parallel, ~40 s) and show the output before claiming anything works; `test.py slow` (real games vs the practice app) before merge/push. Extend a script rather than working around it.

## Game end
1. `scripts/score.py` (`--abort` ranks now: TR + card VP + tile VP; full adds milestones + funded awards; `--app` reads the app's final table). Formula-VP cards and unplaced cities are flagged for manual counting.
2. `scripts/session.py end --note "<winner, score>"` closes the session.
3. `scripts/evalprotocol.py record --game <dir> --winner … --margin … --model … --bots …` — the eval ledger; dummy-bot margins are never strategy evidence.
4. Always offer the narrator: `scripts/narrate.py <dir>` then dispatch agents/narrator.md (saga.md + insights.md); fold advisor mistakes into the KB via agents/kb-researcher.md.
