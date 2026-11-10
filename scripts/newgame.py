#!/usr/bin/env python3
"""Create a game on the local terraforming-mars app (DEV TOOL).

Wraps POST /api/creategame with the full NewGameConfig the vendored server
expects (the shape is undocumented tribal knowledge — notably the
server 500s if clonedGamedId is present as null). Prints game id +
playerIds, ready for setup.py / autoplay / sparring seats.

    python3 scripts/newgame.py --players "Zed=red,Ana=green,Ben=yellow"
    python3 scripts/newgame.py --players ... --json     # full response
"""
import argparse
import json
import sys
import urllib.request

BASE = "http://localhost:8080"


def payload(players_spec: str, board: str = "tharsis",
            seed: float = 0.5, draft: bool = False,
            wgt: bool = True) -> dict:
    """Full NewGameConfig for a base+Corporate Era game. First listed
    player is first player. players_spec: 'Name=color,Name=color,…'."""
    players = []
    for i, part in enumerate(filter(None,
                                    (p.strip() for p in players_spec.split(",")))):
        name, sep, color = part.partition("=")
        if not sep or not name.strip() or not color.strip():
            raise ValueError(f"bad player spec {part!r} (want Name=color)")
        players.append({"name": name.strip(), "color": color.strip(),
                        "beginner": False, "handicap": 0, "first": i == 0})
    if len(players) < 2:
        raise ValueError("need at least 2 players (Name=color, comma-sep)")
    expansions = {e: False for e in
                  ("corpera", "promo", "venus", "colonies", "prelude",
                   "prelude2", "turmoil", "community", "ares", "moon",
                   "pathfinders", "ceo", "starwars", "underworld",
                   "deltaProject")}
    expansions["corpera"] = True
    return {
        "players": players, "expansions": expansions, "board": board,
        "seed": seed, "randomFirstPlayer": False,
        # NO clonedGamedId key — the server 500s on an explicit null
        "undoOption": False, "showTimers": False, "fastModeOption": False,
        "showOtherPlayersVP": False, "aresExtremeVariant": False,
        "politicalAgendasExtension": "Standard",
        "removeNegativeGlobalEventsOption": False, "modularMA": False,
        # World Government Terraforming (vendor: WGT-checkbox) — house default
        "solarPhaseOption": wgt,
        "draftVariant": draft, "initialDraft": False,
        "preludeDraftVariant": False, "ceosDraftVariant": False,
        "startingCorporations": 2, "shuffleMapOption": False,
        "randomMA": "No randomization", "includeFanMA": False,
        "soloTR": False, "customCorporationsList": [], "bannedCards": [],
        "includedCards": [], "customColoniesList": [], "customPreludes": [],
        "requiresMoonTrackCompletion": False,
        "requiresVenusTrackCompletion": False, "altVenusBoard": False,
        "escapeVelocityMode": False, "twoCorpsVariant": False,
        "customCeos": [], "startingCeos": 3, "startingPreludes": 4,
        "maxCraterCount": 0,
    }


def create(players_spec: str, url: str = BASE, **kw) -> dict:
    body = json.dumps(payload(players_spec, **kw)).encode()
    req = urllib.request.Request(f"{url}/api/creategame", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--players", required=True,
                    help="'Name=color,…' — first listed is first player")
    ap.add_argument("--url", default=BASE)
    ap.add_argument("--board", default="tharsis")
    ap.add_argument("--seed", type=float, default=0.5)
    ap.add_argument("--draft", action="store_true")
    ap.add_argument("--no-wgt", dest="wgt", action="store_false",
                    help="disable World Government Terraforming (default ON)")
    ap.add_argument("--json", action="store_true", help="dump full response")
    a = ap.parse_args()
    try:
        out = create(a.players, url=a.url, board=a.board, seed=a.seed,
                     draft=a.draft, wgt=a.wgt)
    except (urllib.error.URLError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(out, indent=1))
        return 0
    print(f"game: {out.get('id')}  spectator: {out.get('spectatorId')}")
    for p in out.get("players", []):
        print(f"  {p['name']:<10} {p['color']:<8} {p['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
