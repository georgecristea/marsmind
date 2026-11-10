# Setup

The detailed version of the README quick start: requirements, the first run,
how a fresh agent session begins, and what to do when something is off.

## Requirements
- Python 3.10 or newer. The scripts use `X | None` annotations evaluated at
  import time (3.10) and nothing newer; the suite is run on 3.11 and 3.14.
- Standard library only. There is nothing to `pip install`.
- `git` (for the optional engine clone). `node` 22.x and `npm` only for the
  local app (mode 3).
- A coding agent that reads `AGENTS.md`: Claude Code, Codex, or similar. The
  harness is a set of scripts and markdown procedures; the agent is the
  advisor.

## First run
```
git clone https://github.com/georgecristea/marsmind && cd marsmind
python3 scripts/doctor.py
```
`doctor.py` prints one line per check and a `Next:` line:
- Python version against the minimum.
- `cards/db.json` and `board.json` present and parseable, with counts.
- `state/`: no active session, an active session (named, with its
  generation), a dangling link, or a legacy real directory.
- `vendor/terraforming-mars`: optional; whether the card extractor and the
  db audit can run, and whether the clone sits at the pinned commit.
- `games/` writable.

Exit code 0 means playable. Then:
```
python3 scripts/setup.py
```
`setup.py` is interactive and takes no arguments. It asks for your name and
color, opponents as `Name=color, Name=color`, expansions (default
`base,corporateEra`; add `wgt` for World Government Terraforming), map,
draft variant, seating order, first player, house rules (one per line, empty
line ends), and the game mode: `physical`, `app-practice` or `app-online`.
App modes also ask for the app URL and your player id. It creates
`games/<date>-gameN/` with `setup.json`, `game.json` and `log.md`, and points
the `state/` symlink at it.

Verify the test suite once after cloning:
```
python3 -m unittest discover -s tests
```

## Starting an agent session
Start the agent in the repo root. It reads `AGENTS.md` first; that file
routes every kind of input to a procedure under `skills/` and states the
rules (state only from files, all changes through scripts, ask when unsure).

A new session has no memory of earlier ones. Files are the truth, so the
player only needs to say one of two things:
- "New game" — the agent runs `python3 scripts/setup.py` with you (or you run
  it yourself before starting the agent).
- "Resume" — the agent reads `state/game.json`, the tail of `state/log.md`
  and the plan store, then states the position for confirmation before
  advising.

The same drill covers a crashed session mid-game: reopen the agent, say
"resume". Nothing is lost because nothing lived in the conversation.

## The game loop in commands
The agent runs these; you report in plain words.
```
python3 scripts/advise.py --brief          # state + calculators → the brief the plan is built from
python3 scripts/research.py "Card A" "Card B" "Card C" "Card D"   # research-phase verdict inputs
python3 scripts/planlib.py show            # the labeled plan (1a, 1b, 2a …)
python3 scripts/turn.py done 1a 1b --note "Anna claimed Mayor"     # steps executed + a table note
python3 scripts/apply.py play Anna "Comet" # any opponent event; `apply.py` alone lists the verbs
python3 scripts/produce.py                 # production phase, next generation
python3 scripts/score.py --abort           # standings right now
python3 scripts/session.py end --note "Anna won, 71 VP"
```

## Troubleshooting

**`state/` is a dangling symlink.** The session folder it pointed at was
moved or deleted. `rm state`, then `python3 scripts/session.py list` to see
what exists and `python3 scripts/setup.py` to start fresh. To reattach an
existing folder, `ln -s games/<folder> state`.

**`state/` is a real directory.** Legacy layout. Move it into `games/`
(`mv state games/legacy-state`) and re-run `doctor.py`.

**`setup.py` refuses: a game is active.** End it first
(`python3 scripts/session.py end --note "…"`) or remove the `state` link.

**`vendor/` is absent.** Normal for modes 1 and 2. Everything table-hot runs
from the committed `cards/db.json` and `board.json`. The only test that
needs the engine source is `tests/test_db_audit.py::TestAuditScript`
(it re-extracts the card db and diffs it); without `vendor/` that one test
fails with "vendor clone not found" and every other test passes. Run
`scripts/vendor_bootstrap.sh` to add the clone at the pinned commit.

**`audit_db.py` reports deltas.** The clone is not at the commit recorded in
`cards/db.json`. `scripts/vendor_bootstrap.sh` re-pins a clean checkout. If
you upgraded the engine on purpose, regenerate with
`python3 scripts/extract_cards.py` and review the diff.

**Phone photos.** Photos are the input channel in mode 1 and they are
unreliable in low light. Turn the big lights on for the moments that matter
(corporation choice, the four research cards, the between-generation mat
walk), shoot straight down from close, one subject per photo, and name the
player colors aloud or in text once at the start. The agent asks for a card
name in text whenever a read is uncertain; answer with the name rather than
a second photo.
