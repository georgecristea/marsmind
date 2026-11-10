#!/usr/bin/env python3
"""Game session lifecycle: list games, end the active game, manage aliases.

Starting a game = scripts/setup.py (interactive). Each game lives in its own
games/<date>-gameN/ folder; state/ points at the active one.

`seat-init <pid> [--url U] [--dir D]` builds a competitive seat's OWN state
folder (default seats/<pid>/, git-ignored) from that seat's /api/player view:
isMe = the seat, only ITS playerId stored, gameMode app-practice. The seat
then runs listen.py / execute.py / turn.py / planlib.py with `--state D` and
never touches the advisor's state/ (the information firewall of
agents/seat-kit.md).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import appapi
import judgment
from tmlib import EventError, GameManager, Store, validate_setup
import latency


def seat_init(pid: str, url: str, root: str | Path = ".",
              directory: str | Path | None = None) -> Path:
    """A seat's own state folder from its /api/player view. Refuses an
    existing folder; stores no playerId but the seat's own."""
    root = Path(root)
    d = Path(directory) if directory else root / "seats" / pid
    if d.exists():
        raise EventError(f"{d} already exists — the seat's state is already "
                         "initialised (delete it to start over)")
    view = appapi.AppClient(url).player(pid)
    me_color = (view.get("thisPlayer") or {}).get("color")
    players = []
    for p in view.get("players") or []:
        entry = {"name": p.get("name"), "color": p.get("color"),
                 "isMe": p.get("color") == me_color, "aliases": []}
        if entry["isMe"]:
            entry["playerId"] = pid
        players.append(entry)
    if not any(p["isMe"] for p in players):
        raise EventError(f"the view for {pid!r} names no seat with its own color")
    names = [p["name"] for p in players]
    setup = {"playerCount": len(players), "players": players,
             "expansions": ["base", "corporateEra"], "map": "tharsis",
             "draft": False, "houseRules": [], "seatingOrder": names,
             "firstPlayerGen1": names[0], "gameMode": "app-practice",
             "appUrl": url.rstrip("/"), "seat": True}
    setup["judgment"] = judgment.defaults(setup)
    validate_setup(setup)
    store = Store(root, state_dir=d)
    store.init(setup)
    me = next(p["name"] for p in players if p["isMe"])
    store.log("G1", f"seat-init: this folder tracks the seat {me} ({pid}) only")
    return d


def end_latency_digest(game_dir) -> str | None:
    """Archive the game's latency digest as <game_dir>/latency-digest.json
    and return the printable digest — None (nothing written) when the game
    recorded no marks."""
    game_dir = Path(game_dir)
    d = latency.digest(game_dir / latency.FILENAME)
    if not d["marks"]:
        return None
    (game_dir / "latency-digest.json").write_text(
        json.dumps(d, indent=2) + "\n")
    return latency.format_digest(d)


def end_reminder(game_dir) -> str:
    """Post-game nudge: every finished game gets its saga + insights."""
    return (
        f"📖 Saga time — dispatch the narrator agent (agents/narrator.md):\n"
        f"   bundle: scripts/narrate.py {game_dir}\n"
        f"   output: {game_dir}/saga.md + insights.md (ask the player first)"
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all game sessions")
    e = sub.add_parser("end", help="end the active game")
    e.add_argument("--note", default="", help="result note, e.g. 'Anna won, 71 VP'")
    al = sub.add_parser("alias", help="add an alias for a player")
    al.add_argument("player"); al.add_argument("alias")
    lp = sub.add_parser("link-player", help="persist an opponent's app "
                        "playerId into setup.json (required for app-mode "
                        "games so gamecheck.py doesn't rely on memory)")
    lp.add_argument("player"); lp.add_argument("player_id")
    lp.add_argument("--force", action="store_true",
                    help="overwrite an existing different id")
    si = sub.add_parser("seat-init", help="a competitive seat's OWN state "
                        "folder from its /api/player view (never state/)")
    si.add_argument("pid", help="the seat's app playerId — the only id it gets")
    si.add_argument("--url", default=None,
                    help=f"app URL (default ${appapi.ENV_VAR}, {appapi.DEFAULT_URL})")
    si.add_argument("--dir", default=None, help="folder (default seats/<pid>)")

    a = p.parse_args(argv)
    gm = GameManager()
    try:
        if a.cmd == "seat-init":
            url = a.url or appapi.configured_url(None) or appapi.DEFAULT_URL
            d = seat_init(a.pid, url, directory=a.dir)
            print(f"seat state initialised: {d}\n"
                  f"  use: scripts/listen.py --state {d} --pid {a.pid} wait\n"
                  f"       scripts/execute.py --state {d} --pid {a.pid} …")
            return 0
        if a.cmd == "list":
            games = gm.list_games()
            if not games:
                print("No games yet. Start one with scripts/setup.py")
            for g in games:
                mark = " ACTIVE" if g["active"] else ""
                ended = f" ended {g['endedAt']}" if g.get("endedAt") else ""
                result = f" — {g['result']}" if g.get("result") else ""
                print(f"{g['dir']}: {', '.join(g['players'])}{ended}{result}{mark}")
        elif a.cmd == "end":
            game_dir = gm.end(note=a.note)
            print(f"Game ended and archived: {game_dir}")
            print(end_reminder(game_dir))
            digest_text = end_latency_digest(game_dir)
            if digest_text:
                print(digest_text)
                print(f"   archived: {game_dir}/latency-digest.json")
        elif a.cmd == "alias":
            from tmlib import Engine
            print(Engine(Store()).add_alias(a.player, a.alias))
        elif a.cmd == "link-player":
            print(gm.link_player(a.player, a.player_id, force=a.force))
        return 0
    except (EventError, FileNotFoundError, appapi.AppError,
            appapi.AppUnavailable) as e2:
        print(f"ERROR: {e2}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
