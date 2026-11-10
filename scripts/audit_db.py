#!/usr/bin/env python3
"""Card-db integrity audit.

Re-extracts card data from the vendored engine source and diffs it against
the committed cards/db.json. Any delta = the committed db is stale or the
extractor changed → exit 1 with a readable report.

Advisory notes (never fail the audit) — the checklist for a generic
interpreter, printed every run:
  * bespoke-code cards (effects implemented in TS methods, listed with the
    hooks they override) lacking a curated behavior patch: their db behavior
    may be PARTIAL — the engine emits a TABLE fallback, but a patch is better;
  * cards whose action the db carries as PROSE only (no `actionBehavior`);
  * a COVERAGE line with the structured-data counts.

Offline and fast (pure file parsing) — runs in the test suite.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    committed = json.loads((ROOT / "cards" / "db.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "db.json"
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "extract_cards.py"),
             "--out", str(out)], capture_output=True, text=True)
        if r.returncode != 0:
            print("EXTRACTOR FAILED:\n" + r.stdout + r.stderr)
            return 1
        fresh = json.loads(out.read_text())

    old = {c["name"]: c for c in committed["cards"]}
    new = {c["name"]: c for c in fresh["cards"]}
    problems: list[str] = []

    for name in sorted(set(old) | set(new)):
        if name not in old:
            problems.append(f"MISSING from committed db: {name}")
        elif name not in new:
            problems.append(f"STALE (no longer extracted): {name}")
        elif old[name] != new[name]:
            for k in sorted(set(old[name]) | set(new[name])):
                if old[name].get(k) != new[name].get(k):
                    problems.append(
                        f"DELTA {name}.{k}: committed={old[name].get(k)!r} "
                        f"vs extracted={new[name].get(k)!r}")

    from extract_cards import BEHAVIOR_PATCHES
    cards = fresh["cards"]
    unpatched = sorted(
        f"{c['name']} [{', '.join(c.get('bespokeMethods') or [])}]"
        for c in cards
        if c.get("bespoke") and c["name"] not in BEHAVIOR_PATCHES)
    if unpatched:
        print(f"note: {len(unpatched)} bespoke cards without curated patches "
              "(engine falls back to TABLE steps):")
        for n in unpatched:
            print(f"  ~ {n}")

    # Cards the phase-2 interpreter cannot drive: the db has their action as
    # PROSE only, because the vendor implements action()/canAct() in code
    # instead of the declarative `action:` block of ActionCard.
    prose_only = sorted(c["name"] for c in cards
                        if c.get("action") and not c.get("actionBehavior"))
    if prose_only:
        print(f"note: {len(prose_only)} cards with a prose-only action "
              "(no structured `actionBehavior`):")
        for n in prose_only:
            print(f"  ~ {n}")

    n_action = sum(1 for c in cards if c.get("actionBehavior"))
    n_vp = sum(1 for c in cards if c.get("vpData") is not None)
    n_vp_prose = sum(1 for c in cards
                     if c.get("vp") is not None and c.get("vpData") is None)
    n_disc = sum(1 for c in cards if c.get("cardDiscount"))
    n_bespoke = sum(1 for c in cards if c.get("bespoke"))
    print(f"COVERAGE — {len(cards)} cards: {n_action} structured actions "
          f"(+{len(prose_only)} prose-only), {n_vp} structured VP "
          f"(+{n_vp_prose} formula-only), {n_disc} card discounts, "
          f"{n_bespoke} bespoke ({len(unpatched)} unpatched)")

    if problems:
        print(f"\nAUDIT FAILED — {len(problems)} delta(s):")
        for pr in problems:
            print("  ✗ " + pr)
        print("\nFix: regenerate (python3 scripts/extract_cards.py) and "
              "review the diff, or repair the extractor.")
        return 1
    print(f"AUDIT OK — {len(new)} cards, committed db matches vendor extraction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
