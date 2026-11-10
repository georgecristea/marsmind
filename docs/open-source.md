# Open source — licensing, provenance, and what the repo ships

## Licence
The repository is licensed under GPL-3.0 (see `LICENSE`). Reason:
`cards/db.json` and `board.json` are DERIVED from the
[terraforming-mars](https://github.com/terraforming-mars/terraforming-mars)
open-source engine (GPL-3.0); the source commit is recorded in both files
and they are regenerated with `scripts/extract_cards.py` and
`scripts/extract_board.py` from a local clone at `vendor/` (git-ignored).
GPL-3 terms follow the derived data, so the whole project is published under
the same licence rather than shipping the harness under a permissive licence
and the data separately.

Card text is FryxGames intellectual property; `NOTICE` carries the
non-affiliation statement. The strategy knowledge base paraphrases public
sources and cites them by URL.

## What is in the repo, and what is not
Shipped: the state engine and CLIs (`scripts/`), the skills and agent
procedures (`skills/`, `agents/`), the strategy knowledge base (`strategy/`),
the card and board data, the test suite with its fixtures, and product docs
(`docs/`).

Never committed (all git-ignored):
- `private/` — anything about real people or real tables (rosters, runbooks,
  photos, archived session notes), and the player's evals ledger
  (`private/evals.jsonl`, see `scripts/evalprotocol.py --help`).
- `games/` — play history. One folder per game session; `state/` is a
  symlink to the active one. The directory is created on demand by
  `scripts/setup.py`; only `games/.gitkeep` is tracked.
- `vendor/` — the upstream engine clone, needed only to re-extract or
  re-audit the card/board data (`tests/test_db_audit.py` skips the audit when
  it is absent).

People in committed files, fixtures, and tests are always aliases
(Anna, Ben, Carl, Diana, Felix, Zed …), never real names. `experiments/`
holds write-ups of controlled runs; their seats carry aliases too.

## Runtime assumption
The harness is host-agnostic: `AGENTS.md` is the session contract (Claude
Code reads it through `CLAUDE.md`, Codex natively; see `docs/hosts.md`),
`skills/` are the table-hot procedures, `agents/` the offline workers.
Deterministic Python (3.10+, standard library only) keeps the arithmetic
exact; the model judges, code computes. CI runs `python3 scripts/test.py`
(`.github/workflows/tests.yml`).

## Before publishing a fork or a release
- `python3 scripts/test.py` green, including `tests/test_entrypoints.py`:
  with a local `private/forbidden-names.txt` (one name per line,
  git-ignored) it checks EVERY tracked file for real names, and it always
  checks for home-directory paths.
- No player ids or game ids from a hosted app instance (fixtures use
  `<playerId>` / `<gameId>` placeholders) and no machine hostnames.
- No API keys: the harness uses none.
- Publish a squashed snapshot, not the development history: history is
  where deleted play data survives.
