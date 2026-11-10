#!/usr/bin/env python3
"""Board renderer: SVG map of the CURRENT tracked state (board.json +
state/game.json occupancy). Fully offline — never depends on the app.

Grid language: rows A (top) … I (bottom), hexes numbered 1..n left→right
within each row. Every placement instruction cites the grid ref (e.g. "E3"),
shows this map with the target ringed, and adds a landmark phrase.

The instruction is baked INTO the image. `--title` draws a
banner at the top of the SVG; `--step`/`--tile` + `--highlight` auto-compose
it ("<step> — <TILE> on <app ref> (<landmark>). <gains>"). The banner's grid
ref is the ONLINE APP's label (rows A–H, then J — the app skips the letter
I): app_label(). grid_label() keeps our A–I scheme for every other caller.
The composed title is printed as the LAST stdout line for reuse as the
file caption.
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_board = json.loads((ROOT / "board.json").read_text())
SPACES = {s["id"]: s for s in _board["spaces"] if not s.get("offMap")}

HEX = 46  # hex radius px
BONUS_GLYPH = {"steel": "🔩", "titanium": "🔶", "plant": "🌱", "card": "🃏",
               "heat": "🔥", "ocean": "💧"}
TILE_STYLE = {"ocean": ("#1d4f6e", "OCEAN"), "greenery": ("#2e6b30", "GREEN"),
              "city": ("#7a7a85", "CITY"), "special": ("#8a5a2b", "SPEC")}
PLAYER_RING = {"red": "#c43b2b", "green": "#3f9b3f", "blue": "#3b6fc4",
               "yellow": "#c4a72b", "black": "#333"}


def grid_label(sp: dict) -> str:
    row_letter = chr(ord("A") + sp["y"])
    in_row = sorted((s["x"] for s in SPACES.values() if s["y"] == sp["y"]))
    return f"{row_letter}{in_row.index(sp['x']) + 1}"


APP_ROWS = "ABCDEFGHJ"   # the online app skips the letter I


def app_label(sp: dict) -> str:
    """Grid ref as the ONLINE APP prints it: same numbering as grid_label,
    but our row I is the app's row J (the app has no row I)."""
    return APP_ROWS[sp["y"]] + grid_label(sp)[1:]


CX, CY = 525, 395  # board center — rows form the physical centered diamond


def _center(sp: dict) -> tuple[float, float]:
    """Row-centered layout, exactly like the physical board: row y's hexes
    sit symmetrically around the vertical axis; vertical position by row."""
    row = sorted((s["x"] for s in SPACES.values() if s["y"] == sp["y"]))
    i = row.index(sp["x"])
    w = HEX * 1.73
    cx = CX + (i - (len(row) - 1) / 2) * w
    cy = CY + (sp["y"] - 4) * HEX * 1.5
    return cx, cy


def _hex_points(cx: float, cy: float, r: float) -> str:
    pts = []
    for i in range(6):
        a = math.pi / 180 * (60 * i - 30)
        pts.append(f"{cx + r*math.sin(a):.1f},{cy - r*math.cos(a):.1f}")
    return " ".join(pts)


W, H = 1050, 790          # board canvas (banner is added ABOVE it)
BANNER_PAD = 18


def _xml(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def _wrap(text: str, max_chars: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and len(cand) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def _banner(title: str) -> tuple[list[str], int]:
    """Light banner, dark large text, wrapped to 2 lines (3 only when a
    title is very long — the font shrinks first). Returns (svg, height)."""
    for size, max_lines in ((32, 2), (26, 2), (22, 3)):
        per_line = int((W - 2 * BANNER_PAD) / (size * 0.52))
        lines = _wrap(title, per_line)
        if len(lines) <= max_lines:
            break
    lines = lines[:3]
    lh = int(size * 1.3)
    height = BANNER_PAD * 2 + lh * len(lines)
    out = [f'<rect class="banner" x="0" y="0" width="{W}" height="{height}" '
           'fill="#EDE3D6"/>',
           f'<rect x="0" y="{height - 4}" width="{W}" height="4" fill="#E8A33C"/>']
    for i, ln in enumerate(lines):
        y = BANNER_PAD + lh * i + int(size * 0.95)
        out.append(f'<text class="banner-line" x="{BANNER_PAD}" y="{y}" '
                   f'fill="#14100E" font-size="{size}" font-weight="bold">'
                   f'{_xml(ln)}</text>')
    return out, height


def render(game: dict, highlight: str | None = None,
           colors: dict | None = None, title: str | None = None) -> str:
    """SVG of the board. colors: player name → cube color (from setup).
    title: instruction banner drawn INTO the image, above the board."""
    occupied = game.get("board", {})
    colors = colors or {}
    banner, top = _banner(title) if title else ([], 0)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="0 0 {W} {H + top}" '
           'font-family="Helvetica,Arial" font-size="13">',
           f'<rect width="{W}" height="{H + top}" fill="#14100E"/>',
           *banner,
           f'<g class="board" transform="translate(0,{top})">',
           f'<circle cx="{CX}" cy="{CY}" r="365" fill="#8a4a2b" opacity="0.55"/>',
           f'<circle cx="{CX}" cy="{CY}" r="365" fill="none" stroke="#C4552B" '
           'stroke-width="3" opacity="0.6"/>',
           '<text x="20" y="30" fill="#E8A33C" font-size="20">PHOBOS board — '
           f'generation {game.get("generation","?")}</text>']
    # row labels
    for y in range(9):
        sp0 = min((s for s in SPACES.values() if s["y"] == y), key=lambda s: s["x"])
        cx, cy = _center(sp0)
        out.append(f'<text x="{cx - HEX*2.1:.0f}" y="{cy+5:.0f}" fill="#9C8B7A" '
                   f'font-size="18">{chr(ord("A")+y)}</text>')
        if APP_ROWS[y] != chr(ord("A") + y):      # the app calls row I "J"
            out.append(f'<text x="{cx - HEX*2.1:.0f}" y="{cy+22:.0f}" fill="#E8A33C" '
                       f'font-size="11">app: {APP_ROWS[y]}</text>')
    for sid, sp in SPACES.items():
        cx, cy = _center(sp)
        occ = occupied.get(sid)
        fill = "#233043" if sp["oceanReserved"] else "#2a2019"
        stroke = "#4a5a72" if sp["oceanReserved"] else "#3A2C24"
        if occ:
            fill = TILE_STYLE.get(occ["tile"], ("#555", "?"))[0]
        out.append(f'<polygon class="hex" points="{_hex_points(cx, cy, HEX*0.95)}" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
        label = grid_label(sp)
        out.append(f'<text x="{cx:.0f}" y="{cy - HEX*0.45:.0f}" fill="#9C8B7A" '
                   f'text-anchor="middle" font-size="12">{label}</text>')
        if occ:
            style = TILE_STYLE.get(occ["tile"], ("#555", occ["tile"][:5]))
            ring = PLAYER_RING.get(colors.get(occ["player"], ""), "#EDE3D6")
            out.append(f'<circle class="tile" cx="{cx:.0f}" cy="{cy:.0f}" r="{HEX*0.55:.0f}" '
                       f'fill="{style[0]}" stroke="{ring}" stroke-width="4"/>')
            out.append(f'<text x="{cx:.0f}" y="{cy+4:.0f}" fill="#fff" text-anchor="middle" '
                       f'font-size="11" font-weight="bold">{style[1]}</text>')
            out.append(f'<text x="{cx:.0f}" y="{cy+HEX*0.8:.0f}" fill="#EDE3D6" '
                       f'text-anchor="middle" font-size="10">{occ["player"]}</text>')
        else:
            glyphs = "".join(BONUS_GLYPH.get(b, "?") for b in sp.get("bonus", []))
            if glyphs:
                out.append(f'<text x="{cx:.0f}" y="{cy+6:.0f}" text-anchor="middle" '
                           f'font-size="15">{glyphs}</text>')
            if sp.get("name"):
                out.append(f'<text x="{cx:.0f}" y="{cy+HEX*0.62:.0f}" fill="#8FB6C4" '
                           f'text-anchor="middle" font-size="9">{sp["name"]}</text>')
    if highlight in SPACES:
        # drawn AFTER every hex so no neighbour covers the marker
        sp = SPACES[highlight]
        cx, cy = _center(sp)
        out.append(f'<polygon points="{_hex_points(cx, cy, HEX*1.12)}" '
                   'fill="none" stroke="#14100E" stroke-width="14"/>')
        out.append(f'<polygon class="target" points="{_hex_points(cx, cy, HEX*1.12)}" '
                   'fill="none" stroke="#E8A33C" stroke-width="8"/>')
        # pointer: filled arrow above the hex + label with a dark halo
        tip_y, base_y = cy - HEX * 1.2, cy - HEX * 1.9
        out.append(f'<polygon class="pointer" points="{cx:.0f},{tip_y:.0f} '
                   f'{cx-22:.0f},{base_y:.0f} {cx+22:.0f},{base_y:.0f}" '
                   'fill="#E8A33C" stroke="#14100E" stroke-width="3"/>')
        out.append(f'<text x="{cx:.0f}" y="{base_y - 8:.0f}" fill="#E8A33C" '
                   'stroke="#14100E" stroke-width="5" paint-order="stroke" '
                   'text-anchor="middle" font-size="26" font-weight="bold">'
                   f'HERE · {app_label(sp)}</text>')
    out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def _bonus_marks(cx: float, cy: float, bonus: list) -> list:
    """Placement bonus as DRAWN shapes (emoji render as black blobs in
    plain SVG rasterisers — the reference card must survive any viewer)."""
    style = {"plant": ("#57B75B", "circle"), "steel": ("#B98A4B", "square"),
             "titanium": ("#D6DCE4", "hex"), "card": ("#7FB2E8", "rect"),
             "heat": ("#E8763C", "circle"), "any": ("#EDE3D6", "diamond")}
    marks, n = [], len(bonus)
    if not n:
        return marks
    step, r = 17, 6
    x0 = cx - step * (n - 1) / 2
    for i, b in enumerate(bonus):
        col, shape = style.get(b, ("#EDE3D6", "circle"))
        x, y = x0 + i * step, cy + 11
        if shape == "circle":
            marks.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" '
                         f'fill="{col}" stroke="#14100E" stroke-width="1.5"/>')
        elif shape == "square":
            marks.append(f'<rect x="{x-r:.0f}" y="{y-r:.0f}" width="{2*r}" '
                         f'height="{2*r}" fill="{col}" stroke="#14100E" '
                         'stroke-width="1.5"/>')
        elif shape == "rect":
            marks.append(f'<rect x="{x-r+1:.0f}" y="{y-r-1:.0f}" width="{2*r-2}" '
                         f'height="{2*r+2}" rx="1.5" fill="{col}" '
                         'stroke="#14100E" stroke-width="1.5"/>')
        elif shape == "hex":
            marks.append(f'<polygon points="{_hex_points(x, y, r+1.5)}" '
                         f'fill="{col}" stroke="#14100E" stroke-width="1.5"/>')
        else:
            marks.append(f'<polygon points="{x:.0f},{y-r-1:.0f} {x+r+1:.0f},'
                         f'{y:.0f} {x:.0f},{y+r+1:.0f} {x-r-1:.0f},{y:.0f}" '
                         f'fill="{col}" stroke="#14100E" stroke-width="1.5"/>')
    return marks


def _legend_swatch(x: int, y: int, kind: str, label: str) -> list:
    out = _bonus_marks(x, y - 11, [kind])
    out.append(f'<text x="{x+13}" y="{y+5:.0f}" fill="#C9BCAC" '
               f'font-size="15">{label}</text>')
    return out


def reference_card() -> str:
    """Standalone board REFERENCE (no game state): every hex labelled with
    the app grid ref, placement bonuses, named landmarks, ocean slots and a
    legend. The player keeps this one image; placement instructions then
    only need to name a cell."""
    pad_top, pad_bot = 96, 120
    out = ['<svg xmlns="http://www.w3.org/2000/svg" '
           f'viewBox="0 0 {W} {H + pad_top + pad_bot}" '
           'font-family="Helvetica,Arial" font-size="13">',
           f'<rect width="{W}" height="{H + pad_top + pad_bot}" fill="#14100E"/>',
           f'<text x="{W//2}" y="44" fill="#E8A33C" font-size="31" '
           'font-weight="bold" text-anchor="middle">THARSIS — BOARD '
           'REFERENCE</text>',
           f'<text x="{W//2}" y="72" fill="#9C8B7A" font-size="15" '
           'text-anchor="middle">Rows A–H then J (no row I, exactly as the '
           'app prints it) · numbered left→right within each row</text>',
           f'<g transform="translate(0,{pad_top})">',
           f'<circle cx="{CX}" cy="{CY}" r="365" fill="#8a4a2b" opacity="0.5"/>',
           f'<circle cx="{CX}" cy="{CY}" r="365" fill="none" stroke="#C4552B" '
           'stroke-width="3" opacity="0.6"/>']
    for y in range(9):
        sp0 = min((s for s in SPACES.values() if s["y"] == y),
                  key=lambda s: s["x"])
        cx, cy = _center(sp0)
        out.append(f'<text x="{cx - HEX*2.2:.0f}" y="{cy+8:.0f}" fill="#E8A33C" '
                   f'font-size="25" font-weight="bold">{APP_ROWS[y]}</text>')
    for sid, sp in SPACES.items():
        cx, cy = _center(sp)
        ocean = sp["oceanReserved"]
        out.append(f'<polygon points="{_hex_points(cx, cy, HEX*0.95)}" '
                   f'fill="{"#23374F" if ocean else "#2a2019"}" '
                   f'stroke="{"#6E93BE" if ocean else "#3A2C24"}" '
                   'stroke-width="2"/>')
        out.append(f'<text x="{cx:.0f}" y="{cy - HEX*0.30:.0f}" fill="#F7F1E7" '
                   'text-anchor="middle" font-size="20" font-weight="bold">'
                   f'{app_label(sp)}</text>')
        out.extend(_bonus_marks(cx, cy, sp.get("bonus", [])))
        if sp.get("name"):
            words, ny = _xml(sp["name"]).split(), cy + HEX*0.52
            for i, w in enumerate(words[:2]):
                out.append(f'<text x="{cx:.0f}" y="{ny + i*10:.0f}" '
                           'fill="#93B7C9" text-anchor="middle" '
                           f'font-size="9.5">{w}</text>')
    out.append("</g>")
    ly = H + pad_top + 42
    out.append(f'<rect x="0" y="{ly-34}" width="{W}" height="2" fill="#3A2C24"/>')
    out.append(f'<text x="24" y="{ly}" fill="#E8A33C" font-size="15" '
               'font-weight="bold">PLACEMENT BONUS</text>')
    present = {b for sp in SPACES.values() for b in sp.get("bonus", [])}
    x = 200
    for kind in ("plant", "steel", "titanium", "card", "heat", "any"):
        if kind not in present:
            continue
        label = "any two" if kind == "any" else kind
        out.extend(_legend_swatch(x, ly, kind, label))
        x += 42 + len(label) * 9
    out.append(f'<rect x="24" y="{ly+22}" width="17" height="17" fill="#23374F" '
               'stroke="#6E93BE" stroke-width="2"/>')
    out.append(f'<text x="49" y="{ly+36}" fill="#C9BCAC" font-size="15">'
               'reserved for an OCEAN tile (only ocean tiles go here; each '
               'adjacent ocean pays the placer 2 M€)</text>')
    out.append(f'<text x="24" y="{ly+62}" fill="#9C8B7A" font-size="14">'
               'Blue-grey labels name the board\u2019s landmark areas. '
               'Bonuses go to whoever places a tile on that hex.</text>')
    out.append("</svg>")
    return "\n".join(out)


def describe(sid: str, game: dict) -> str:
    """Landmark phrase for a space: grid ref + neighbours + kind."""
    sp = SPACES[str(sid)]
    kind = "ocean-reserved slot" if sp["oceanReserved"] else "land hex"
    named = [SPACES[a]["name"] for a in sp["adjacent"]
             if a in SPACES and SPACES[a].get("name")]
    occ = game.get("board", {})
    tiles = [f"{occ[a]['player']}'s {occ[a]['tile']}" for a in sp["adjacent"] if a in occ]
    bits = [f"{grid_label(sp)} — {kind}",
            f"bonus: {' '.join(BONUS_GLYPH.get(b, b) for b in sp['bonus']) or 'none'}"]
    if sp.get("name"):
        bits.append(f"this is {sp['name']}")
    if named:
        bits.append(f"next to {', '.join(named)}")
    if tiles:
        bits.append(f"adjacent tiles: {', '.join(tiles)}")
    return "; ".join(bits)


def placement_gains(sid: str, game: dict) -> str:
    """What the placer receives (same arithmetic as tmlib.Engine.place):
    hex bonus counts + 2 MC per adjacent ocean tile."""
    sp = SPACES[str(sid)]
    occ = game.get("board", {})
    names = {"plant": "plant", "steel": "steel", "titanium": "titanium",
             "heat": "heat", "card": "card", "mc": "MC"}
    counts: dict[str, int] = {}
    for b in sp.get("bonus", []):
        counts[b] = counts.get(b, 0) + 1
    parts = [f"+{n} {names.get(b, b)}" for b, n in counts.items()]
    adj = sum(1 for a in sp["adjacent"] if occ.get(a, {}).get("tile") == "ocean")
    if adj:
        parts.append(f"+{2*adj} MC ({adj} adjacent ocean)")
    return ", ".join(parts) if parts else "no bonus"


def compose_title(step: str, tile: str, sid: str, game: dict) -> str:
    """Banner text: '<step> — <TILE> on <app ref> (<landmark>). <gains>'.
    Landmark = describe() minus the grid/bonus bits (the app's label is the
    one the player matches on their phone, so the ref is app_label, never I-row)."""
    sp = SPACES[str(sid)]
    parts = describe(sid, game).split("; ")
    kind = parts[0].split(" — ", 1)[1]
    landmark = ", ".join([kind] + [b for b in parts[1:] if not b.startswith("bonus:")])
    return (f"{step} — {tile.upper()} on {app_label(sp)} ({landmark}). "
            f"{placement_gains(sid, game)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state", default="state/game.json")
    p.add_argument("--setup", default="state/setup.json")
    p.add_argument("--highlight", default=None, help="space id to ring")
    p.add_argument("--title", default=None,
                   help="instruction banner drawn INTO the image (top)")
    p.add_argument("--step", default=None, help="plan step id (e.g. 3b) — "
                   "with --tile and --highlight auto-composes --title")
    p.add_argument("--tile", default=None,
                   choices=["city", "greenery", "ocean", "special"])
    p.add_argument("--out", default="state/board.svg")
    p.add_argument("--reference", action="store_true",
                   help="standalone board reference card (no game state)")
    a = p.parse_args()
    if a.reference:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(reference_card())
        print(f"board reference → {out}")
        return 0
    if (a.step or a.tile) and not a.title:
        if not (a.step and a.tile and a.highlight):
            p.error("--step and --tile need each other and --highlight "
                    "(or pass --title explicitly)")
    game = json.loads(Path(a.state).read_text())
    colors = {}
    setup_path = Path(a.setup)
    if setup_path.exists():
        colors = {pl["name"]: pl["color"]
                  for pl in json.loads(setup_path.read_text())["players"]}
    title = a.title
    if not title and a.step:
        title = compose_title(a.step, a.tile, a.highlight, game)
    svg = render(game, highlight=a.highlight, colors=colors, title=title)
    Path(a.out).write_text(svg)
    print(f"wrote {a.out}")
    if a.highlight:
        print(describe(a.highlight, game))
    if title:
        print(title)          # LAST line = caption for the file card
    return 0


if __name__ == "__main__":
    sys.exit(main())
