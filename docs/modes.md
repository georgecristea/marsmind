# Game modes

`setup.json` carries one `gameMode`: `physical`, `app-online` (the
open-source app, hosted or local, with its player API) or `app-practice`
(the local app with AI sparring seats). The advisor loop is identical in all
three — brief, plan, report, events, produce — only the input channels and
the verification source differ. Opponents are tracked continuously from
events in every mode; a photo, screenshot or API read is optional ground
truth that the state is reconciled to whenever one arrives.

## Mode 1 — physical table, against people (`physical`)

**Channels.** Phone photos and the player's words, typed or dictated. Photos
of: the two corporation cards and the initial ten, every research deal
(four cards, no caption needed — the agent evaluates them unprompted),
opponent mats between generations, the board on request. Words for
everything else: "Anna played Comet", "Ben claimed Mayor", "did 1a and 1b".

**The agent may.** Read and write state only through scripts; ask for a card
name in text when a photo read is uncertain; ask for a missing value
(temperature, an opponent's move) instead of assuming it; record house
rules the player flags and respect them all session.

**The agent may not.** Use any app or API; state a game value from
conversation memory; edit `games/` files by hand; guess a card silently.

**What the player sends, when.**
- Session start: `setup.py` answers (players, colors, expansions, seating,
  first player, house rules), the color line-up under the table light.
- Corporation choice: one photo of the corps and the ten cards.
- Each generation: a photo of the four research cards; then the executed
  step labels with any opponent events since the last report; a photo of
  the opponent mats during production (optional, but the most valuable
  reconciliation point).
- Game end: final scores in words.

**Latency.** A research verdict or a generation plan takes about as long as
the other players need for their own research phase. Reporting executed
steps by label (`turn.py done 1a 1b`) is one call and returns in seconds;
that is what keeps the table moving. The pass gate refuses to close a
generation while the engine still lists an available action, so expect one
question before a pass, not after it.

## Mode 2 — online, against people (`app-online`, API off or on)

The same loop with a screen instead of a table. Applies to the open-source
Terraforming Mars app, self-hosted or public. Platforms whose terms forbid
outside assistance are out of scope; opponents must know an AI is advising
the seat.

**Channels.** Screenshots (clean, unlike photos) of the hand, the research
row and the panels; lines pasted from the app's LOG panel for opponent
events, which are public information; the player's words. With the API
opted in at setup (`gameMode=app-online`, app URL, the player's own id;
opponents linked with `session.py link-player`), `/api/player?id=…` fills
the same slot as a mat photo: it returns the seat's own view plus the
public board, and the harness reads it after applied steps to verify the
tracker.

**The agent may.** Read the player API when the mode is `app-online`; treat
pasted LOG lines as events; reconcile to a screenshot the moment one
arrives.

**The agent may not.** Send any input to the app unless the player opted in
at setup (appUrl + playerId) and `judgment.py set executor assist|auto`; with
executor `manual` (the default) the player clicks and the API is read-only.
Never read the API when it was not opted in (screenshots-only is chosen on
purpose, usually to rehearse the table). Infer an opponent's hand from anything: the API exposes none of it
and the LOG panel reports keeps as counts.

**What the player sends, when.** The same cadence as mode 1: research row
screenshot at each generation start, executed labels plus pasted LOG lines
after each of the player's turns, a panel screenshot between generations if
the API is off. Choose before generation 1 whether the API is on and record
the choice in the house rules so the game's evaluation row is honest.

**Latency.** Lower than mode 1: no photo interpretation, no card-name
questions. Pasting three LOG lines and a label is a ten-second report.

**Two-lane loop (API on).** Lane 1 is mechanical: `listen.py wait` drains
the app's LOG panel into the engine and the triage feed and returns when
it is the player's turn (`once` for a single drain, `sync-me` to reconcile
the own mat and hand). Lane 2 is judgment: `turn.py round` after each
opponent event (pending triggers, a sweep when `judgment.py` says so),
`turn.py go` on the own turn (listen, promote the draft, executor hint,
plan, menu). The executor mode in `judgment.py set executor` decides who
clicks: `manual` (the player clicks, `execute.py` only dry-runs), `assist`
(prints each input, then sends) or `auto` (sends); `execute.py
step|turn|pick|corp|pass` builds the inputs from the plan, verifies the
app view against a sandbox simulation and only then marks the step done.

## Mode 3 — local app, against AI sparring seats (`app-practice`)

The training rig. The engine runs locally (`scripts/vendor_bootstrap.sh
--build`, then `npm start` in `vendor/terraforming-mars`);
`scripts/newgame.py` creates the game and prints one player id per seat.
The player's seat goes into `setup.py` (`app-practice`, app URL, player
id). Opponent seats are driven by the harness at a chosen level
(`docs/bots.md`):
- `autoplay.py run <pid> --level passer|greedy` plays a seat with a
  heuristic policy until it is no longer that seat's turn. Everything it
  prints is public-table information; hidden information is reported as
  counts. Use these levels to test the harness, never as strategy evidence.
- `--level competitive` refuses to autopilot: each such seat is a separate
  agent that sees only its own player id, decides at model level and acts
  through `scripts/sparring.py` (`agents/sparring-partner.md`,
  `agents/seat-kit.md`). `gamecheck.py` shows whom the app is waiting on
  before anyone concludes the game is stuck.

**Channels.** The player API for the advised seat; the sparring seats'
public reports; the app in a browser for the human's own clicks. No photos
in this mode — the agent never asks for one.

**The agent may.** Read the API freely for its own seat and public state;
verify every applied step against the app; drive dummy seats; dispatch
competitive seats.

**The agent may not.** Read another seat's `/api/player` view or any
sparring seat's private reasoning (the information firewall); pass on the
player's behalf; count a win over dummy seats as evidence.

**What the player sends, when.** Little: the player id at setup, clicks in
the app, "go" between turns. Record the result with
`evalprotocol.py record --game games/<session> --winner … --margin …
--model … --bots <level>`; the ledger keeps tiers apart.

**Latency.** Dummy seats play a turn in seconds. Competitive seats take
minutes per generation, growing with the game unless the seats are
refreshed per generation (`docs/bots.md`).

**Two-lane loop and seats.** The same lanes as mode 2 (`listen.py wait`
→ `turn.py go` → `execute.py`), with the executor defaulting to `auto`.
A competitive seat may run the identical pipeline on its own tracker:
`session.py seat-init <pid>` creates `seats/<pid>/`, and every verb takes
`--state seats/<pid> --pid <pid>` — the folder holds only that seat's id,
so the firewall is structural. `scripts/e2e_practice.py [--gens N]
[--greedy]` is the scripted proof of the pipeline against dummy seats:
it plays a whole game through these verbs and exits non-zero on any
own-seat drift or refused prompt.
