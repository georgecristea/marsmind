"""THE GUARD for phase 2 of private/plans/generalize-engine-plan.md.

Card behaviour is DATA (cards/db.json), not code. Every card name that
appears as a string literal in scripts/ is a card someone modelled by hand,
and the P7/P8 fix passes proved that road never ends: ACTION_EFFECTS,
OR_CHOICE_PATCHES, menu's ACTION_COSTS, the replayer's per-card action
chain, score.py's VP prose parsing.

Rule: no card name from cards/db.json may appear as a whole string literal
in any scripts/*.py, with three exceptions:

  * scripts/extract_cards.py, scripts/audit_db.py and
    scripts/extract_board.py — they BUILD the data files (cards/db.json,
    board.json) from the vendor source, so naming cards and board spaces
    is exactly their job;
  * a block opened by a `# card-table: <what>` comment and closed by
    `# card-table: end` — the small, deliberate tables of rules the vendor
    itself implements as TypeScript hooks (corporations, tile/card
    triggers, the four prose-only blue actions) and that therefore have no
    data to read yet. Each card in such a block has a `bespokeMethods`
    entry in the db saying which hook it overrides.

If this test fails, the fix is to read the card's data — actionBehavior,
vpData, cardDiscount, resourceType, behavior — not to widen the allow-list.

The match is on the WHOLE literal ("Helion" fails, "Only Helion can spend
heat as MC" is prose and passes), which is exactly the shape a hand model
takes: a table key or an `== "<Card>"` comparison.
"""
import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# these build the data files from the vendor source (cards/db.json,
# board.json), so naming cards and board spaces is exactly their job
BUILDERS = {"extract_cards.py", "audit_db.py", "extract_board.py"}

OPEN_MARK = "# card-table:"
CLOSE_MARK = "# card-table: end"


def card_names() -> set[str]:
    db = json.loads((ROOT / "cards" / "db.json").read_text())
    return {c["name"] for c in db["cards"]}


def allowed_lines(source: str) -> set[int]:
    """Line numbers inside a `# card-table: …` … `# card-table: end` block."""
    out: set[int] = set()
    inside = False
    for n, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(CLOSE_MARK):
            inside = False
            out.add(n)
            continue
        if stripped.startswith(OPEN_MARK):
            inside = True
        if inside:
            out.add(n)
    return out


def literals(path: Path, names: set[str]) -> list[tuple[int, str]]:
    source = path.read_text()
    skip = allowed_lines(source)
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.strip() in names and node.lineno not in skip:
                hits.append((node.lineno, node.value.strip()))
    return sorted(set(hits))


class TestNoCardLiterals(unittest.TestCase):
    def setUp(self):
        self.names = card_names()

    def test_no_script_hand_models_a_card(self):
        offenders = {}
        for path in sorted(SCRIPTS.glob("*.py")):
            if path.name in BUILDERS:
                continue
            hits = literals(path, self.names)
            if hits:
                offenders[path.name] = hits
        self.assertEqual(
            offenders, {},
            "card names hand-coded outside cards/db.json — read the card's "
            "data (actionBehavior / vpData / cardDiscount / resourceType) "
            "instead of adding a case:\n"
            + "\n".join(f"  {f}: {h}" for f, h in offenders.items()))

    def test_the_guard_can_actually_see_a_literal(self):
        """A guard that never fires is not a guard."""
        name = sorted(self.names)[0]
        src = f'x = {name!r}\n'
        path = ROOT / "tests" / "_guard_probe.py"
        try:
            path.write_text(src)
            self.assertEqual(literals(path, self.names), [(1, name)])
        finally:
            path.unlink(missing_ok=True)

    def test_a_marked_table_is_skipped(self):
        name = sorted(self.names)[0]
        src = ("# card-table: probe\n"
               f"T = {{{name!r}: 1}}\n"
               "# card-table: end\n"
               f"y = {name!r}\n")
        path = ROOT / "tests" / "_guard_probe.py"
        try:
            path.write_text(src)
            self.assertEqual(literals(path, self.names), [(4, name)])
        finally:
            path.unlink(missing_ok=True)

    def test_every_card_table_block_is_closed(self):
        for path in sorted(SCRIPTS.glob("*.py")):
            depth = 0
            for line in path.read_text().splitlines():
                s = line.strip()
                if s.startswith(CLOSE_MARK):
                    depth -= 1
                elif s.startswith(OPEN_MARK):
                    depth += 1
                self.assertIn(depth, (0, 1),
                              f"{path.name}: unbalanced {OPEN_MARK} block")
            self.assertEqual(depth, 0, f"{path.name}: unclosed {OPEN_MARK}")


if __name__ == "__main__":
    unittest.main()
