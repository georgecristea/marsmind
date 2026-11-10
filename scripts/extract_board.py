#!/usr/bin/env python3
"""Extract the Tharsis board from the vendored terraforming-mars repo -> board.json.

dev tool: regenerates board.json from vendor/ (a clone of the upstream engine; not needed to play).

Source: vendor/terraforming-mars/src/server/boards/TharsisBoard.ts (row layout,
space types, placement bonuses, volcanic/Noctis markers) plus the id/coordinate
and adjacency algorithms replicated from BoardBuilder.ts and Board.ts:
  - off-grid colony spaces get ids '01' (Ganymede Colony) and '02' (Phobos
    Space Haven); on-map spaces get ids '03'..'63' row by row.
  - x = (9 - tilesInRow) + columnIndex, y = row (rows of 5,6,7,8,9,8,7,6,5).
  - neighbours per Board.computeAdjacentSpaces (middle row y=4).

Volcano display names are not in the server data (they are cosmetic labels in
src/client/components/Board.vue); they are assigned here to the four volcanic
spaces in official map order, top to bottom.

Deterministic: same vendor checkout -> byte-identical board.json.

Usage: python3 scripts/extract_board.py [--vendor PATH] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "terraforming-mars"
OUT = ROOT / "board.json"

TILES_PER_ROW = [5, 6, 7, 8, 9, 8, 7, 6, 5]

BONUS_MAP = {
    "STEEL": "steel",
    "TITANIUM": "titanium",
    "PLANT": "plant",
    "DRAW_CARD": "card",
    "HEAT": "heat",
    "OCEAN": "ocean",
    "MEGACREDITS": "megacredits",
}

# Cosmetic names for the volcanic spaces, in board order (top to bottom),
# matching the printed Tharsis map and the labels in the client UI.
VOLCANO_NAMES = ["Tharsis Tholus", "Ascraeus Mons", "Pavonis Mons", "Arsia Mons"]


def die(msg: str) -> None:
    sys.exit(f"extract_board: {msg}")


def parse_builder_calls(vendor: Path) -> list[dict]:
    src = (vendor / "src/server/boards/TharsisBoard.ts").read_text(encoding="utf-8")
    body_match = re.search(r"newInstance[\s\S]*?builder\.build\(\)", src)
    if not body_match:
        die("could not find builder chain in TharsisBoard.ts")
    body = body_match.group(0)

    spaces: list[dict] = []
    for m in re.finditer(r"\.(land|ocean|volcanic|cove|doNotShuffleLastSpace)\(([^)]*)\)", body):
        method, argstr = m.group(1), m.group(2)
        if method == "doNotShuffleLastSpace":
            spaces[-1]["noctis"] = True  # only used for Noctis City on Tharsis
            continue
        bonus = []
        for token in argstr.split(","):
            token = token.strip()
            if not token:
                continue
            if token not in BONUS_MAP:
                die(f"unknown bonus token {token!r}")
            bonus.append(BONUS_MAP[token])
        spaces.append({
            "type": "ocean" if method in ("ocean", "cove") else "land",
            "volcanic": method == "volcanic",
            "bonus": bonus,
        })
    return spaces


def compute_adjacency(spaces: list[dict]) -> None:
    """Replicates Board.computeAdjacentSpaces for the 9-row hex map."""
    by_coord = {(s["x"], s["y"]): s["id"] for s in spaces}
    middle = 4
    for s in spaces:
        x, y = s["x"], s["y"]
        top_left = [x, y - 1]
        top_right = [x, y - 1]
        bottom_left = [x, y + 1]
        bottom_right = [x, y + 1]
        if y < middle:
            bottom_left[0] -= 1
            top_right[0] += 1
        elif y == middle:
            bottom_right[0] += 1
            top_right[0] += 1
        else:
            bottom_right[0] += 1
            top_left[0] -= 1
        coords = [top_left, top_right, [x + 1, y], bottom_right, bottom_left, [x - 1, y]]
        adjacent = []
        for cx, cy in coords:
            sid = by_coord.get((cx, cy))
            if sid is not None and sid != s["id"] and sid not in adjacent:
                adjacent.append(sid)
        s["adjacent"] = adjacent


def vendor_commit(vendor: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(vendor), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor", type=Path, default=VENDOR)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    vendor = args.vendor
    if not (vendor / "src/server/boards/TharsisBoard.ts").exists():
        die(f"vendor clone not found at {vendor}")

    raw = parse_builder_calls(vendor)
    if len(raw) != sum(TILES_PER_ROW):
        die(f"expected {sum(TILES_PER_ROW)} builder spaces, got {len(raw)}")

    spaces: list[dict] = []
    idx = 0
    volcano_i = 0
    for row, count in enumerate(TILES_PER_ROW):
        x_offset = 9 - count
        for i in range(count):
            r = raw[idx]
            space = {
                "id": f"{idx + 3:02d}",
                "row": row,
                "x": x_offset + i,
                "y": row,
                "type": r["type"],
                "bonus": r["bonus"],
                "oceanReserved": r["type"] == "ocean",
                "offMap": False,
            }
            if r["volcanic"]:
                space["volcanic"] = True
                space["name"] = VOLCANO_NAMES[volcano_i]
                volcano_i += 1
            if r.get("noctis"):
                space["name"] = "Noctis City"
                space["reservedFor"] = "Noctis City (city tile from the Noctis City card only)"
            spaces.append(space)
            idx += 1

    if volcano_i != 4:
        die(f"expected 4 volcanic spaces, found {volcano_i}")
    noctis = [s for s in spaces if s.get("name") == "Noctis City"]
    if len(noctis) != 1 or noctis[0]["id"] != "31":
        die("Noctis City space did not land on id '31' (SpaceName.NOCTIS_CITY)")

    compute_adjacency(spaces)

    off_map = [
        {"id": "01", "name": "Ganymede Colony", "offMap": True, "type": "colony",
         "bonus": [], "oceanReserved": False, "adjacent": [],
         "reservedFor": "Ganymede Colony card city tile"},
        {"id": "02", "name": "Phobos Space Haven", "offMap": True, "type": "colony",
         "bonus": [], "oceanReserved": False, "adjacent": [],
         "reservedFor": "Phobos Space Haven card city tile"},
    ]

    board = {
        "map": "tharsis",
        "source": "https://github.com/terraforming-mars/terraforming-mars",
        "commit": vendor_commit(vendor),
        "rows": TILES_PER_ROW,
        "counts": {
            "onMapSpaces": len(spaces),
            "oceanReserved": sum(1 for s in spaces if s["oceanReserved"]),
            "offMapSpaces": len(off_map),
        },
        "spaces": off_map + spaces,
    }
    args.out.write_text(json.dumps(board, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(spaces)} on-map spaces "
          f"({board['counts']['oceanReserved']} ocean-reserved) + {len(off_map)} off-map")


if __name__ == "__main__":
    main()
