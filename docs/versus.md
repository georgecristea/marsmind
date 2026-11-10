# Playing against an external agent

An independent agent (any runtime, any model backend) can join a hosted
game as an opponent seat. The server enforces hidden information
structurally — each seat's private view is gated by its player id — so a
fair match needs only the contract below, not trust in anyone's
discipline.

## Match setup (host side)
1. Start the server via `python3 scripts/server.py` (LAN-visible by
   default; it prints the LAN URL).
2. Create the game: `python3 scripts/newgame.py --url <lan-url>
   --players "You=red,Visitor=green,..."`.
3. Hand the visiting agent its SEAT BRIEF: the server URL and **its own
   player id — nothing else**. Never share the `spectatorId` or another
   seat's id.
4. Record the result with `scripts/evalprotocol.py record --bots
   external-<agent>` — external-agent games are their own evidence
   tier; never aggregate them with internal seat tiers.

## Visiting-agent contract
- Truth arrives only through the API with your own player id. Play via
  `scripts/sparring.py --url <server>` (or raw HTTP; `docs/actions.md`
  is the audited action space).
- If you work from a clone of this repository: read `scripts/`,
  `skills/`, `strategy/`, `docs/`, `cards/db.json`, `board.json`
  freely. Do **not** read `state/`, `games/`, `seats/` folders that are
  not yours, or `private/` — and do not pull the repository while a
  match is running (the host may commit its own perspective at any
  time).
- You may keep your own tracker: `session.py seat-init <pid>` gives you
  an isolated `seats/<pid>/` state directory; every verb accepts
  `--state seats/<pid>`.
- Stalls: before claiming one, check whose input the server is actually
  waiting on (`scripts/gamecheck.py`). A turn-wait timeout is not a
  failure — restart the wait.

## Reporting firewall (matches with a human spectator)
A spectator who talks to one side is a side channel. During the match,
any progress reports from either agent carry **public information
only** — moves made, tiles placed, visible track values — never hand
contents, plans, or reasoning. Full reasoning dumps are welcome **after
the final scoring**, where they become analysis instead of leakage.

## Host-side symmetry
The hosting advisor observes the visitor exactly as it would a human:
public log entries and public state. It never reads the visitor's seat
folder, transcripts, or reports beyond the public-only channel above.

## Code freeze and bug flow during a match
- Both sides name the harness commit the match is played on; neither
  pulls nor pushes code until final scoring.
- External agents never push to this repository. Bugs found during play
  are filed via `scripts/bugs.py` into the agent's own `private/bugs/`
  and delivered to the maintainer after the match; fixes go through the
  normal claim-then-fix flow (`CONTRIBUTING.md`).
