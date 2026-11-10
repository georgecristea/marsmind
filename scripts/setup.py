#!/usr/bin/env python3
"""Interactive game setup — starts a fresh game session under games/.

Collects players/colors/seating/house rules, writes setup.json + fresh
game.json, and points state/ at the new game. Run at the start of game night.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tmlib import EventError, GameManager
import judgment


GAME_MODES = ("physical", "app-practice", "app-online")


def ask(prompt: str, default: str = "") -> str:
    tag = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{tag}: ").strip()
    except EOFError:                      # scripted stdin ran out → default
        return default
    return val or default


def main() -> int:
    # This script is interactive and takes NO arguments, but it had
    # no parser — `setup.py --help` fell through to the prompts and, on
    # EOF, created a game session from the defaults. argparse owns argv.
    argparse.ArgumentParser(
        prog="setup.py",
        description="Interactive game setup — asks for players, expansions, "
                    "house rules and game mode, then CREATES a new game "
                    "session under games/ and points state/ at it. "
                    "Takes no arguments.",
    ).parse_args()
    try:
        me_name = ask("Your name", "Player")
        me_color = ask("Your color", "red")
        opp_raw = ask("Opponents (Name=color, comma-separated)")
        opponents = []
        for part in filter(None, (p.strip() for p in opp_raw.split(","))):
            name, _, color = part.partition("=")
            opponents.append({"name": name.strip(), "color": color.strip(),
                              "isMe": False, "aliases": []})
        players = [{"name": me_name, "color": me_color, "isMe": True,
                    "aliases": []}] + opponents

        expansions = [e.strip() for e in
                      ask("Expansions", "base,corporateEra").split(",")]
        game_map = ask("Map", "tharsis")
        draft = ask("Draft variant? (y/n)", "n").lower().startswith("y")
        default_seating = ",".join(p["name"] for p in players)
        seating = [s.strip() for s in
                   ask("Seating order (clockwise)", default_seating).split(",")]
        first = ask("First player generation 1", seating[0])

        house_rules = []
        print("House rules (one per line, empty line to finish):")
        try:
            while rule := input().strip():
                house_rules.append(rule)
        except EOFError:
            pass

        # Input channel mode. physical = photos + words (default);
        # app-practice = API + sparring opponents; app-online = API reads,
        # human opponents. Prompted LAST so pre-gameMode stdin drivers
        # (which run out of lines here) still get the physical default.
        game_mode = ask("Game mode (physical / app-practice / app-online)",
                        "physical")
        if game_mode not in GAME_MODES:
            raise EventError(
                f"gameMode must be one of {GAME_MODES}, got {game_mode!r}")
        app_url = player_id = ""
        if game_mode != "physical":
            app_url = ask("App URL", "http://localhost:8080")
            player_id = ask("Your app playerId (from the player link)")

        setup = {
            "playerCount": len(players),
            "players": players,
            "expansions": expansions,
            "map": game_map,
            "draft": draft,
            "houseRules": house_rules,
            "seatingOrder": seating,
            "firstPlayerGen1": first,
            "gameMode": game_mode,
        }
        if app_url:
            setup["appUrl"] = app_url
        if player_id:
            players[0]["playerId"] = player_id    # players[0] is me
        # Judgment-schedule defaults (scripts/judgment.py) — derived from
        # the answers above, no extra prompt.
        setup["judgment"] = judgment.defaults(setup)
        from tmlib import validate_setup, setup_coverage_warnings
        validate_setup(setup)
        for w in setup_coverage_warnings(setup):
            print(f"⚠ {w}")
        print()
        print(judgment.ladder_text(setup))
        game_dir = GameManager().start(setup)
        print(f"\nGame session started: {game_dir}")
        print(f"state/ → {game_dir.name}; generation 1, first player {first}.")
        if game_mode == "physical":
            # The pre-game checklist is STRUCTURAL — printed by the
            # harness at every physical setup so nobody has to remember it.
            print(f"""
=== PHYSICAL GAME NIGHT — PRE-GAME CHECKLIST ===
1. If private/table-notes.md exists, read it NOW (advisor: before
   anything else — table protocols and per-opponent notes live there).
2. COLOR CALIBRATION RITUAL (20 seconds, do it at the table):
   line up ALL player cubes left-to-right PLUS one copper, one
   silver, one gold resource cube, under tonight's actual table light;
   photograph; name the order by voice ("left to right: ..."). Retake
   if the lighting changes during the night.
3. Confirm color map: {me_name}={me_color}; log every opponent's color + aliases.
   Declare any COMPONENT SUBSTITUTES the same way ("white die = 10 MC")
   — undeclared substitutes poison every later photo read.
4. Big lights ON for photo moments (corp choice, research fans,
   between-gen mat walk); cozy light in between.
5. Laptop plugged in, session live, phone chat tested with one message.
   MODEL ECONOMY: know the model budget + reset time; switch models
   only BETWEEN generations.
6. Clear a photo zone (one sheet of paper) next to your seat.
======================================================""")
        return 0
    except EventError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
