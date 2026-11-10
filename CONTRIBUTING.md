# Contributing

Small, test-backed changes are the easiest to merge.

- **Test first.** Any change to `scripts/` starts with a failing test in
  `tests/`, then the code. Run the fast lane (what CI runs, parallel, under a
  minute) before opening a PR and paste the summary line:

      python3 scripts/test.py

  `python3 scripts/test.py slow` adds real games against the local practice
  app (needs `vendor/` and `scripts/server.py`). `tests/test_db_audit.py` re-audits `cards/db.json` against a local clone of
  the upstream engine at `vendor/` and skips when the clone is absent; CI
  runs without it.
- **No play data in PRs.** `games/`, `private/`, and `evals.jsonl` are
  git-ignored on purpose. A regression that needs a real game goes in
  `tests/fixtures/` as a trimmed, aliased fixture (see
  `tests/fixtures/replay-4p-wgt/`).
- **Aliases for people.** Committed files, fixtures, logs and tests refer to
  players by aliases (Anna, Ben, Carl, Diana, Felix, Zed …), never real names,
  emails, hosted-app player ids or game ids (use `<playerId>` / `<gameId>`
  placeholders). `tests/test_entrypoints.py` checks every tracked file against
  a maintainer's local list of names (`private/forbidden-names.txt`) and for
  home-directory paths.
- **Card data changes** go through `scripts/extract_cards.py` /
  `scripts/extract_board.py` against a pinned upstream commit, never by
  editing `cards/db.json` or `board.json` by hand.
- **Docs** in `docs/` are product documentation only (action space, adversary
  ladder, roadmap, licensing); session notes and plans stay out of the tree.

By contributing you agree that your contribution is licensed under the
GPL-3.0, like the rest of the project (see `LICENSE` and `NOTICE`).
