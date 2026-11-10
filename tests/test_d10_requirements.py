"""D10 — hard gate on non-global card requirements in research.py.

Codex S5: a 3-tag-requirement card (the Advanced Ecosystems SHAPE — needs a
plant, a microbe AND an animal tag) was bought with no animal tag because
the evaluator printed a soft `manual check` and the advisor assumed the
card's OWN tags could satisfy its own pre-play requirement.

Vendor rule (vendor/terraforming-mars/src/server/cards/requirements/
TagCardRequirement.ts → player.tags.count → Tags.rawCount reads
playedCards.tags, NOT playedCards.eventTags; Player.canPlay runs
Card.canPlay → CardRequirements.satisfies BEFORE Player.playCard pushes the
card into playedCards): tag requirements are checked against the tags the
player ALREADY has in play — corp + green + blue cards; events excluded;
the card being played never counts toward its own requirement.

Every card here is chosen from cards/db.json by SHAPE (never a literal in
scripts/ — tests/test_no_card_literals.py guards that).
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import research  # noqa: E402

DB = json.loads((ROOT / "cards" / "db.json").read_text())["cards"]
_TAGREQ = re.compile(r"^(\d+)\s+([a-z]+)\s+tags?$", re.I)


def _tag_reqs(card):
    """{tag: n} of a card's tag requirement, or None when not a tag req."""
    req = card.get("requirements")
    if not req:
        return None
    out = {}
    for clause in req.split(","):
        m = _TAGREQ.match(clause.strip())
        if not m:
            return None
        out[m.group(2).lower()] = out.get(m.group(2).lower(), 0) + int(m.group(1))
    return out


def three_tag_card():
    """The Advanced Ecosystems SHAPE: three distinct 1-tag requirements,
    and the card itself carries all three tags (the trap)."""
    for c in DB:
        reqs = _tag_reqs(c)
        if reqs and len(reqs) == 3 and all(n == 1 for n in reqs.values()) \
                and set(reqs) <= set(c.get("tags") or []):
            return c
    raise AssertionError("no 3-tag-requirement card in db.json")


def provider(tag, event=False, exclude=()):
    """A card carrying `tag`: a persisting (non-event) one, or an event."""
    for c in DB:
        if c["name"] in exclude or c.get("type") == "corporation":
            continue
        is_event = c.get("type") == "event"
        if is_event == event and tag in (c.get("tags") or []):
            return c["name"]
    raise AssertionError(f"no {'event' if event else 'persisting'} {tag} card")


def corp_with(tag):
    for c in DB:
        if c.get("type") == "corporation" and tag in (c.get("tags") or []):
            return c["name"]
    raise AssertionError(f"no corporation with a {tag} tag")


def no_requirement_card():
    for c in DB:
        if not c.get("requirements") and c.get("type") == "automated" \
                and (c.get("behavior") or {}).get("production"):
            return c["name"]
    raise AssertionError("no requirement-free production card")


def game(played=(), corp=None, o2=2, temp=-12, oceans=5, gen=7, mc=46):
    me = {"name": "Me", "resources": {"mc": mc},
          "playedCards": [{"name": n} for n in played]}
    if corp:
        me["corporation"] = corp
    return {"generation": gen,
            "globals": {"temperature": temp, "oxygen": o2, "oceans": oceans},
            "me": me}


class TestThreeTagShape(unittest.TestCase):
    def setUp(self):
        self.card = three_tag_card()
        self.name = self.card["name"]
        self.tags = sorted(_tag_reqs(self.card))

    def _eval(self, g, **kw):
        return research.evaluate(g, [self.name], **kw)[0]

    def _provider(self, tag, event=False, exclude=()):
        # never the card under test itself (it carries all three tags)
        return provider(tag, event=event, exclude={self.name, *exclude})

    def test_zero_matching_tags_is_refused(self):
        e = self._eval(game())
        r = e["requirement"]
        self.assertEqual(e["windowInfo"]["status"], "unresolved")
        self.assertEqual(r["verdict"], "refused")
        self.assertEqual(r["required"], {t: 1 for t in self.tags})
        self.assertEqual(r["have"], {t: 0 for t in self.tags})
        self.assertEqual(r["missing"], {t: 1 for t in self.tags})

    def test_one_matching_tag_is_still_refused(self):
        t0 = self.tags[0]
        e = self._eval(game(played=[self._provider(t0)]))
        r = e["requirement"]
        self.assertEqual(r["verdict"], "refused")
        self.assertEqual(r["have"][t0], 1)
        self.assertNotIn(t0, r["missing"])
        self.assertEqual(set(r["missing"]), set(self.tags) - {t0})

    def test_three_matching_persistent_tags_is_allowed(self):
        played, used = [], set()
        for t in self.tags:
            n = self._provider(t, exclude=used)
            used.add(n)
            played.append(n)
        e = self._eval(game(played=played))
        r = e["requirement"]
        self.assertEqual(r["verdict"], "met")
        self.assertEqual(r["missing"], {})
        self.assertEqual(e["windowInfo"]["status"], "open")

    def test_corporation_tag_counts_as_persistent(self):
        # the corp is in play from turn one — vendor pushes it into playedCards
        for t in self.tags:
            try:
                corp = corp_with(t)
            except AssertionError:
                continue
            e = self._eval(game(corp=corp))
            self.assertEqual(e["requirement"]["have"][t], 1)
            return
        self.skipTest("no corporation carries one of the required tags")

    def test_event_tagged_match_does_not_count(self):
        for t in self.tags:
            try:
                ev = self._provider(t, event=True)
            except AssertionError:
                continue
            e = self._eval(game(played=[ev]))
            r = e["requirement"]
            self.assertEqual(r["have"][t], 0, f"event {ev} counted toward {t}")
            self.assertEqual(r["verdict"], "refused")
            return
        self.skipTest("no event card carries one of the required tags")

    def test_the_cards_own_tags_never_count(self):
        # the card carries every tag it requires — and still fails at 0 tags
        self.assertTrue(set(self.tags) <= set(self.card["tags"]))
        e = self._eval(game())
        self.assertEqual(e["requirement"]["have"], {t: 0 for t in self.tags})
        self.assertEqual(e["requirement"]["verdict"], "refused")
        # nor when the same card is named in --tableau by mistake
        e = self._eval(game(), tableau=[self.name])
        self.assertEqual(e["requirement"]["have"], {t: 0 for t in self.tags})

    def test_tableau_flag_feeds_persistent_tags_but_not_events(self):
        t0 = self.tags[0]
        e = self._eval(game(), tableau=[self._provider(t0)])
        self.assertEqual(e["requirement"]["have"][t0], 1)
        try:
            ev = self._provider(t0, event=True)
        except AssertionError:
            return
        e = self._eval(game(), tableau=[ev])
        self.assertEqual(e["requirement"]["have"][t0], 0)

    def test_confirm_lifts_the_refusal(self):
        e = self._eval(game(), confirm=[self.name])
        r = e["requirement"]
        self.assertEqual(r["verdict"], "confirmed")
        self.assertEqual(r["missing"], {t: 1 for t in self.tags})   # still shown
        self.assertNotEqual(e["windowInfo"]["status"], "unresolved")
        self.assertIn("confirm", e["window"].lower())

    def test_quick_line_refuses_and_prints_required_have_missing(self):
        line = research.quick_lines(game(), [self.name])[0]
        self.assertIn("REFUSED", line)
        for word in ("required", "have", "missing"):
            self.assertIn(word, line)
        self.assertIn("--confirm-requirement", line)

    def test_quick_line_keeps_when_met(self):
        played, used = [], set()
        for t in self.tags:
            n = self._provider(t, exclude=used)
            used.add(n)
            played.append(n)
        line = research.quick_lines(game(played=played), [self.name])[0]
        self.assertNotIn("REFUSED", line)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.card = three_tag_card()
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "game.json"
        self.state.write_text(json.dumps(game()))

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "research.py"),
                            "--state", str(self.state), *args],
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def test_full_report_refuses_with_required_have_missing(self):
        rc, out = self._run(self.card["name"], "--full")
        self.assertEqual(rc, 0, out)
        self.assertIn("REFUSED", out)
        for word in ("required", "have", "missing"):
            self.assertIn(word, out)
        self.assertIn("--confirm-requirement", out)

    def test_confirm_flag_is_visible_in_the_output(self):
        rc, out = self._run(self.card["name"], "--full",
                            "--confirm-requirement", self.card["name"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("REFUSED", out)
        self.assertIn("confirmed", out.lower())
        self.assertIn("missing", out)          # the gap is still spelled out

    def test_quick_path_confirm_flag(self):
        rc, out = self._run(self.card["name"], "--quick",
                            "--confirm-requirement", self.card["name"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("REFUSED", out)
        self.assertIn("confirmed", out.lower())


class TestUnaffected(unittest.TestCase):
    def test_card_without_tag_requirement_is_unchanged(self):
        name = no_requirement_card()
        e = research.evaluate(game(), [name])[0]
        self.assertEqual(e["windowInfo"]["status"], "none")
        self.assertNotIn("requirement", e)
        line = research.quick_lines(game(), [name])[0]
        self.assertNotIn("REFUSED", line)

    def test_global_parameter_requirements_keep_their_handling(self):
        closed = next(c["name"] for c in DB
                      if (c.get("requirements") or "").startswith("min ")
                      and "O2" in c["requirements"])
        g = game(o2=0)
        e = research.evaluate(g, [closed])[0]
        self.assertEqual(e["windowInfo"]["status"], "closed")
        self.assertNotIn("requirement", e)


if __name__ == "__main__":
    unittest.main()
