#!/usr/bin/env python3
"""Deck odds: exact hypergeometric math over the base+CorpEra deck.

Race margins under uncertainty: removal risk is priced,
not guessed — deck composition comes from cards/db.json, probabilities
are exact (math.comb), never simulated.

Library:
    p_at_least_one(matching, deck_size, draws) -> float
    expected(matching, deck_size, draws)       -> float
    count_removal(db)   -> (count, deck_size, names)   # plant-removal cards
    removal_report(db, hands=(4, 8, 12)) -> str

CLI:
    python3 scripts/odds.py draw --matching N --deck M --draws K
    python3 scripts/odds.py removal        # plant-removal risk by hand size
"""
import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PLANT_REMOVAL = re.compile(r"remove.*plant", re.IGNORECASE)


def p_at_least_one(matching: int, deck_size: int, draws: int) -> float:
    """P(≥1 of `matching` cards among `draws` draws from `deck_size`)."""
    draws = min(draws, deck_size)
    if matching <= 0 or draws <= 0 or deck_size <= 0:
        return 0.0
    if draws > deck_size - matching:
        return 1.0
    return 1.0 - math.comb(deck_size - matching, draws) / math.comb(deck_size, draws)


def expected(matching: int, deck_size: int, draws: int) -> float:
    draws = min(draws, deck_size)
    return draws * matching / deck_size if deck_size else 0.0


def count_removal(db: dict) -> tuple[int, int, list[str]]:
    """Plant-removal cards in the PROJECT deck (corporations excluded).

    Approximate by design: regex over effects text ("remove … plant"),
    so protection cards mentioning removal count too — worst-case bias
    is the intended direction for threat pricing.
    """
    projects = [c for c in db["cards"] if c.get("type") != "corporation"]
    names = [c["name"] for c in projects
             if PLANT_REMOVAL.search(c.get("effects") or "")]
    return len(names), len(projects), names


def removal_report(db: dict, hands: tuple[int, ...] = (4, 8, 12)) -> str:
    count, deck, names = count_removal(db)
    lines = [
        f"Plant-removal cards (regex, approx): {count} of {deck} "
        f"project cards ({count / deck:.1%})",
        f"  {', '.join(names)}",
    ]
    for h in hands:
        p = p_at_least_one(count, deck, h)
        lines.append(f"P(opponent holds ≥1 | drew {h} cards) = {p:.1%}")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draw", help="P(≥1 matching) + expected hits")
    d.add_argument("--matching", type=int, required=True,
                   help="matching cards left in the deck")
    d.add_argument("--deck", type=int, required=True, help="cards left in deck")
    d.add_argument("--draws", type=int, required=True)
    sub.add_parser("removal",
                   help="plant-removal deck composition + hold probabilities")
    a = p.parse_args()
    if a.cmd == "draw":
        print(f"P(≥1 in {a.draws} draws) = "
              f"{p_at_least_one(a.matching, a.deck, a.draws):.1%}")
        print(f"Expected hits = {expected(a.matching, a.deck, a.draws):.2f}")
    else:
        import cards
        print(removal_report(cards.load_db()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
