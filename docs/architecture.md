# Architecture

MarsMind separates what must be exact from what must be judged. Deterministic
Python owns state, arithmetic and legality; the agent owns evaluation,
wording and the conversation with the player. Every layer below is a plain
file in the repo, so a session can die and a new one resume from disk.

## Engine — `scripts/tmlib.py`, `scripts/apply.py`
`tmlib.py` is the core: the `Store` (load/save of `game.json`, append-only
`log.md`), the `Engine` (one method per event type — resources, production,
TR, global parameters, card play with effects from `cards/db.json`, tile
placement on `board.json`, milestones, awards, corporation abilities,
opponent observations), rule enforcement (requirements, costs, once-per-
generation actions, parameter caps) and the `GameManager` for sessions.
`apply.py` is the command-line face of the engine: one verb per event,
each printing the trace of what it applied and any `→ TABLE` step the
player must perform by hand. `apply.py batch` takes JSON-lines events;
`correct.py` reverses a plan step; `produce.py` runs the production phase
and rolls the generation.

## State — `games/<session>/`, `state/`
Each game session is a folder `games/<date>-gameN/` holding `setup.json`
(players, colors, expansions, house rules, mode), `game.json` (the full
tracked state: own mat at full fidelity, opponents at public fidelity with
provenance), `log.md` (every event, human-readable) and `plan.json`. The
`state/` symlink points at the active session, so every script and every
procedure addresses `state/game.json`; `session.py end` removes the link
and archives the folder. Nothing in `games/` is edited by hand.

## Plan store — `scripts/planlib.py`, `scripts/turn.py`
The generation plan is a list of labeled steps (1a, 1b, 2a …), each with
its events, a volatility mark (safe to execute blind, or re-check against
the board first) and, for contested steps, the cue that must be seen before
it counts as done. `planlib.py set` simulates the plan against current
state and checks it for a threats block and a pass-gate step; `promote`
re-simulates a draft; `show` renders it. `turn.py done 1a 1b
--note …` marks steps executed, applies their events, logs the note and
prints the tracker numbers and the next open step in one call.

## Advisor — `scripts/advise.py` and the calculators
`advise.py --brief` assembles everything the agent reasons over: current
state, the engine-derived action menu, the race table (milestone and award
metrics per player), requirement windows, the clock estimate, opponent
summaries, and in full mode the strategy knowledge base. The arithmetic is
delegated: `payback.py` (production value over the remaining horizon),
`clock.py` (generations left from parameter fill), `endgame.py` (best
action line in the last generations), `odds.py`, `research.py` (one-call
verdict inputs for a dealt hand), `score.py` (standings now or at the
end). `verify.py` and `gamecheck.py` compare the tracker with the app in
the app modes. All HTTP to the app goes through `appapi.py` (`AppClient`:
`/api/player`, `/api/waitingfor`, `/api/game/logs`, `/player/input`;
retries, typed errors, and `render_log_entry` — the LOG panel's JSON
entries rendered to the same lines as the plain-text export that
`applog_parser.py` reads).

## API play pipeline — `listen.py`, `turn.py`, `execute.py`, `judgment.py`
In the app modes the loop is two lanes over the same files. Lane 1,
`listen.py` (`once|wait|sync-me`), fetches the app's LOG panel through
`appapi.py`, renders each entry to the export grammar, applies it through
the replay machinery (`replay_applog.py`) into the live engine, writes one
triage entry per line to `feed.jsonl` (`triage.py` decides what needs a
look) and keeps a cursor so nothing is applied twice; after any own line it
reconciles the own mat and hand from `/api/player`. Lane 2, `turn.py round`
per opponent event and `turn.py go` on the own turn, runs the judgment
schedule (`judgment.py`: sweep level, quiet zone, executor mode) and the
plan store. `execute.py` turns a plan step into the app's input tree,
answers the follow-ups the step covers, verifies the app view against a
sandbox simulation and marks the step done; `pick|corp|pass` answer the
research and initial prompts. `latency.py` times every phase.
`e2e_practice.py` runs the whole pipeline against dummy seats with no
model; a competitive seat runs the same verbs on its own folder
(`session.py seat-init`, `--state`).

## Knowledge base — `strategy/`
Numbered markdown files: valuation and economy (MC prices of resources,
production and TR; payback rules), archetypes and the game arc, corporation
notes, card tiers, openings. Claims are priced in VP or MC and cite their
sources; lessons from played games are folded back in after each session.
The advisor reads the whole set before recommending and cites the
principle behind each evaluation; the `kb-researcher` agent maintains it
offline.

## Skills — `skills/`
Table-hot procedures, one folder per trigger: game setup, the research
phase (four dealt cards → keep/reject verdict), the turn advisor (the
generation plan and the anti-pass discipline), event logging (free-form
reports → events), reconciliation (mat photos → state), threat analysis
(per opponent, in every plan) and the execution-trace output format shared
by all of them. `AGENTS.md` routes each kind of input to its skill.

## Agents — `agents/`
Briefs for work dispatched outside the table-hot loop: the narrator (a
finished session → saga and insights), the KB researcher, the vision
extractor (photo batches → structured observations), and the sparring
seats (`sparring-partner.md`, `seat-kit.md`) that play opponents on the
local app through `scripts/sparring.py` while seeing only their own seat.

## Tests and the replay fixture — `tests/`
`python3 -m unittest discover -s tests` covers the engine, every CLI, the
calculators, the plan store, the modes and the agents' drivers; it runs in
a few seconds with no network and no engine clone (only the card-db audit
needs `vendor/`). Recorded sessions under `tests/fixtures/` are replayed
through the same code paths: a captured app log is parsed into events,
applied from a fresh game, and the resulting TR, credits and production per
player are asserted against the app's own final numbers. Any change to
`scripts/` starts with a failing test.
