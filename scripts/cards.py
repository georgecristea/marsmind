#!/usr/bin/env python3
"""Card database lookup: exact and fuzzy name matching over cards/db.json.

Library:
    load_db()             -> full db dict (cached)
    find(name)            -> card dict via exact case-insensitive name, or None
    fuzzy(name, limit=3)  -> [(card, score), ...] best matches, score in 0..1
    resolve(name, pool)   -> (card, "accept"|"confirm"|"ask") voice-noise policy

CLI:
    python3 scripts/cards.py <query...>   # prints best matches with details
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "cards" / "db.json"

_db: dict | None = None


def load_db(path: Path = DB_PATH) -> dict:
    """Load (and cache) the card database."""
    global _db
    if _db is None or path != DB_PATH:
        with open(path, encoding="utf-8") as f:
            db = json.load(f)
        if path == DB_PATH:
            _db = db
        return db
    return _db


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("-", " ").replace("'", "").split())


_idx: dict[str, dict] | None = None


def _index(db: dict) -> dict[str, dict]:
    global _idx
    if db is _db:                     # default DB: build once, reuse
        if _idx is None:
            _idx = {_norm(c["name"]): c for c in db["cards"]}
        return _idx
    return {_norm(c["name"]): c for c in db["cards"]}


def find(name: str, db: dict | None = None) -> dict | None:
    """Exact, case-insensitive lookup (also tolerant of hyphen/apostrophe noise)."""
    db = db or load_db()
    return _index(db).get(_norm(name))


def fuzzy(name: str, limit: int = 3, db: dict | None = None) -> list[tuple[dict, float]]:
    """Fuzzy name match for OCR / speech-to-text noise.

    Returns up to `limit` (card, score) pairs, best first. Exact match scores 1.0.
    """
    db = db or load_db()
    idx = _index(db)
    query = _norm(name)
    if query in idx:
        return [(idx[query], 1.0)][:limit]

    scored: list[tuple[dict, float]] = []
    for key, card in idx.items():
        score = difflib.SequenceMatcher(None, query, key).ratio()
        # Substring/prefix bumps help truncated OCR reads ("mining right").
        if query and (query in key or key in query):
            score = max(score, 0.9)
        scored.append((card, round(score, 3)))
    scored.sort(key=lambda cs: (-cs[1], cs[0]["name"]))
    return scored[:limit]


def format_card(card: dict) -> str:
    lines = [f"{card['name']}  [{card['type']}]  cost {card['cost']} MC"]
    if card["tags"]:
        lines.append(f"  tags: {', '.join(card['tags'])}")
    if card["requirements"]:
        lines.append(f"  requires: {card['requirements']}")
    if card["effects"]:
        lines.append(f"  effects: {card['effects']}")
    if card["action"]:
        lines.append(f"  action: {card['action']}")
    if card["vp"] is not None:
        lines.append(f"  vp: {card['vp']}")
    return "\n".join(lines)


def resolve(name: str, pool: list[str] | None = None,
            db: dict | None = None) -> tuple[dict | None, str]:
    """Voice-noise resolution policy (tuned on a real-utterance corpus).

    Returns (card, verdict): verdict is "accept" (use silently),
    "confirm" (use, but echo the canonical name back — one-word check),
    or "ask" (do NOT guess; ask the player). pool restricts candidates to a
    known context (hand, tableau, the 4-card research row) — context
    turns heavy garble into a safe accept.
    """
    exact = find(name, db=db)
    if exact is not None and pool is None:
        return exact, "accept"
    if pool:
        pdb = {"cards": [c for n in pool
                         for c in [find(n, db=db)] if c is not None]}
        top = fuzzy(name, limit=2, db=pdb)
        if not top:
            return None, "ask"
        (card, s1) = top[0]
        s2 = top[1][1] if len(top) > 1 else 0.0
        if s1 >= 0.5 and (s1 - s2) >= 0.08:
            return card, "accept"
        if s1 >= 0.5:
            return card, "confirm"
        return card, "ask"
    top = fuzzy(name, limit=2, db=db)
    if not top:
        return None, "ask"
    (card, s1) = top[0]
    s2 = top[1][1] if len(top) > 1 else 0.0
    margin = s1 - s2
    if s1 >= 0.80 and margin >= 0.10:
        return card, "accept"
    if s1 >= 0.65 and margin >= 0.10:
        return card, "confirm"
    return card, "ask"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip())
        return 2
    query = " ".join(argv)
    matches = fuzzy(query, limit=3)
    if not matches:
        print(f"no match for {query!r}")
        return 1
    best_score = matches[0][1]
    if best_score < 1.0:
        print(f"no exact match for {query!r}; closest:")
    for card, score in matches:
        if score < 0.5 and score < best_score:
            continue
        print(f"--- match {score:.2f} ---")
        print(format_card(card))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
