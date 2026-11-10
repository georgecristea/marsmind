# PLAYBOOK — exact invocations for every table-hot verb

**Standing rule: `--help` is FORBIDDEN at a live table.** Every command the
advisor may need during a game is here, with its exact shape. If a verb is
missing, that is a between-sessions playbook bug — file it, do not explore
live. Part of the RE-READ SET (AGENTS.md).

All commands run from the repo root as `python3 scripts/<cmd>`. `state/` is a
symlink to the active game; seats use `--state seats/<pid>`.

## Session / setup
```
python3 scripts/setup.py                  # interactive; stdin order: name, color,
                                          # "Opp=color,Opp2=color", expansions, map,
                                          # draft y/n, seating, first player,
                                          # house rules (blank line ends), gameMode,
                                          # appUrl, playerId
python3 scripts/session.py list
python3 scripts/session.py end --note "<winner, score, one-line summary>"
python3 scripts/session.py alias <player> <alias>
python3 scripts/session.py link-player <name> <pid>
python3 scripts/session.py seat-init <pid> [--url U] [--dir D]
python3 scripts/judgment.py status
python3 scripts/judgment.py set executor manual|assist|auto
python3 scripts/judgment.py set level every|per-opponent|after-k|triggers-only
python3 scripts/judgment.py set verbosity terse|full   # plan-step prose budget
python3 scripts/doctor.py
python3 scripts/server.py            # practice server only; server.py status probes
```

## Advice / plan (planlib JSON via stdin heredoc)
```
python3 scripts/advise.py --full     # once per session, off the player's clock
python3 scripts/advise.py --brief    # default re-read
python3 scripts/advise.py --sweep    # opponent-event sweep (judgment lane)

python3 scripts/planlib.py set [--draft] <<'JSON'
{"generation": N, "threats": "<per-opponent block — REQUIRED live>",
 "exit": "<named VP exit incl. its repeatable component — required, see gates>",
 "steps": [
   {"id": "1a", "volatility": "safe|recheck", "summary": "…",
    "cue": "<player-visible outcome — required for milestone/award/place/cueGated>",
    "events": [{"method": "play|place|standard|milestone|award|convert|res|prod|tr|sell",
                "args": ["Hector", "…"], "kwargs": {}}],
    "mapHighlight": "<hex>", "passGate": true, "force": "<per-item reason>",
    "choice": "<or-branch TITLE SUBSTRING>", "buy": false}
 ]}
JSON
# or-cards: "choice" is a TITLE SUBSTRING ("remove 3 microbes"), never a
# bare index — the app's live branch order is not the card's, so an index
# means a different branch in each layer (a bare int is refused). An index
# is legal only with "choiceLabel": "<title substring>", which the executor
# checks against the live branch before it transmits.
python3 scripts/planlib.py patch [--live] <<'JSON'
{"replace": {"1b": {…step…}}, "insert_after": {"1a": [{…}]},
 "remove": ["2a"], "threats": "…"}
JSON
python3 scripts/planlib.py show
python3 scripts/planlib.py promote            # draft → live (re-simulated)
python3 scripts/planlib.py done <id> …        # prefer turn.py done
python3 scripts/planlib.py skip <id> --note "…" | reopen <id>
```

## Composite verbs (prefer these — one call, not three)
```
python3 scripts/turn.py done 1a 1b --note "…" [--confirm "<cue text>"]
python3 scripts/turn.py round --opp I --of N [--last-before-me] [--boundary]
python3 scripts/turn.py go
python3 scripts/apply.py batch  <<'JSONL'     # one engine call per line
{"method": "res", "args": ["Hector", "mc", -3], "kwargs": {}}
JSONL
```

## Executor (API play only)
```
python3 scripts/execute.py step 1a [--dry-run] [--no-done] [--force "<why>"]
python3 scripts/execute.py turn 1a 1b [--dry-run]
python3 scripts/execute.py resolve 1a [--cards "<Card>"]   # close a follow-up; no --cards = decline
python3 scripts/execute.py pick "<Card>" ["<Card>"…]       # research/draft buy
python3 scripts/execute.py pick                             # buy nothing — REFUSED on a
       --override "<why>"                                   # 2nd consecutive zero buy
                                                            # without a written reason
python3 scripts/execute.py corp "<Corp>" "<Card>"…         # initial corp + buys
python3 scripts/execute.py sell "<Card>"…
python3 scripts/execute.py pass [--force "<per-item reason>"]
```
`step`/`turn` refuse a standard project whose only effect is a step on a
FULL track (SP asteroid at +8 °C, SP aquifer at 9 oceans) before anything
is sent — "ZERO-EFFECT STANDARD PROJECT". SP greenery at 14 % O2 still
places its tile and is never refused. Override: `--force "<why>"`.

## Listener (API play; `paste` is the screenshot-mode lane)
```
python3 scripts/listen.py once|status|init
python3 scripts/listen.py wait [--interval 1] [--idle 10] [--timeout 570]
python3 scripts/listen.py sync-me
python3 scripts/listen.py paste <<'LOG'      # pasted LOG panel text (or --file F);
<paste the app LOG window here>              # overlap-safe: re-pasting applies
LOG
                                             # nothing twice; never apply.py by hand
# exit codes: once 0 none | 10 applied | 20 GO | 30 GO+applied; paste 0 none | 10 applied
```

## Events — apply.py (31 verbs; run bare `apply.py` for the grouped list)
```
python3 scripts/apply.py res    <player> <mc|steel|titanium|plants|energy|heat> <±n>
python3 scripts/apply.py prod   <player> <kind> <±n>
python3 scripts/apply.py tr     <player> <±n>
python3 scripts/apply.py raise  <temperature|oxygen|oceans>            # with TR
python3 scripts/apply.py sync   <temperature|oxygen|oceans|me> [value] [--force]
       # sync me --tr --mc --steel --titanium --plants --energy --heat
       #         --prod-mc --prod-steel --prod-titanium --prod-plants
       #         --prod-energy --prod-heat
python3 scripts/apply.py wgt    <temperature|oxygen|oceans> [--hex C4]  # no TR/bonuses
python3 scripts/apply.py convert <player> plants|heat
python3 scripts/apply.py play   <player> "<Card>" [--ignore-requirements "<why>"]
                                [--target <victim>] [--choice N]
python3 scripts/apply.py action use "<Card>" <player> [--target …]     # blue ledger
       # or-action: --choice "<title substring>" (never a bare index)
python3 scripts/apply.py hand   add|remove "<Card>" …
python3 scripts/apply.py dealt  --kept "<Card>,…" "<C1>" "<C2>" "<C3>" "<C4>"  # MY research
python3 scripts/apply.py research <opponent> --kept N                  # THEIR research
python3 scripts/apply.py standard <player> greenery|city|aquifer|asteroid|power_plant|sell_patents
python3 scripts/apply.py sell   "<Card>" …                             # mine, 1 MC each
python3 scripts/apply.py corp   <player> "<Corp>" [--mc N]
python3 scripts/apply.py milestone <player> <Mayor|Gardener|Builder|Terraformer|Planner>
python3 scripts/apply.py award  <player> <Landlord|Banker|Scientist|Thermalist|Miner>
python3 scripts/apply.py freecity <player> <hex>
python3 scripts/apply.py place  <player> <city|greenery|ocean|special> <hex|C4>
python3 scripts/apply.py spaces <city|greenery|ocean|special> [--sort mine|oceans|bonus]
python3 scripts/apply.py observe <player> [--tr --mc --steel --titanium --plants
                                --energy --heat --prod-* …]            # opponents only
python3 scripts/apply.py snap   <player> <anchor> <value>       # anchor may be card:"<Card>"
                                          # (observed on-card resource count — the honest
                                          # channel that turns a score bound into a number)
python3 scripts/apply.py attack <victim> <what> <n> [--by <attacker>]
python3 scripts/apply.py attribute <pending-id> <attacker>
python3 scripts/apply.py unplace <hex> | unplay <player> "<Card>"      # corrections
python3 scripts/apply.py gen <n> | first <player> | final
python3 scripts/apply.py note "<free text>"
```
**Double-count guard:** `play`/`place` auto-apply db effects, corp triggers and
placement bonuses and PRINT the numbered trace. READ THE TRACE before adding any
manual `res`/`prod` from a pasted log line — if the trace already shows it, the
log line is already applied.

## Turnover
```
python3 scripts/produce.py [--skip-wgt "<why>"] [--force "<why>"]
       # PHYSICAL mode only by hand; app modes: the listener owns turnover
```

## Arithmetic (never mental math)
```
python3 scripts/menu.py                                   # affordability — THE menu
python3 scripts/clock.py                                  # plan to the RANGE TOP
python3 scripts/shape.py                                  # position shape + flags
python3 scripts/payback.py --cost 16 --gens-left 5 mc=2 plants=1
python3 scripts/payback.py --cost 16 --gens-range 5 8 heat=2 [--no-keep-cost]
python3 scripts/research.py "<C1>" "<C2>" "<C3>" "<C4>" [--quick|--full]
python3 scripts/endgame.py [--gens 1|2] [--milestone-eligible]
python3 scripts/odds.py removal
python3 scripts/odds.py draw --matching N --deck M --draws K
python3 scripts/score.py [--abort|--app]
python3 scripts/verify.py [--sync]
```

## Board render (every placement instruction — no bare hex ids)
```
python3 scripts/render_board.py --highlight <hex> --step <id> --tile <type>
       # writes state/board.svg; SendUserFile it in the same message
```

## End of game
```
python3 scripts/score.py --app
python3 scripts/session.py end --note "…"
python3 scripts/evalprotocol.py record --game games/<dir> --winner X --margin N
        --model "<model>" --bots "<field>"
python3 scripts/narrate.py games/<dir>          # then dispatch agents/narrator.md
python3 scripts/bugs.py file --reporter advisor --area "<area>" --title "…" --body -
```
