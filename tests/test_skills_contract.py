"""The verdict-first rule is TEXT in three skills;
this test keeps the shared paragraph present and identical in all three,
and the draft-variant flow present in research-phase."""
import re
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent / "skills"
THREE = ("turn-advisor", "research-phase", "event-logging")
HEADING = "## Verdict-first"


def _section(text: str, heading: str) -> str:
    """Heading line + its paragraph (up to the first blank line)."""
    m = re.search(rf"^({re.escape(heading)}[^\n]*\n.*?)(?=\n\n|\Z)", text,
                  re.M | re.S)
    return m.group(1).strip() if m else ""


class TestVerdictFirst(unittest.TestCase):
    def _skill(self, name):
        return (SKILLS / name / "SKILL.md").read_text()

    def test_rule_present_in_all_three_skills(self):
        for name in THREE:
            text = self._skill(name)
            body = _section(text, HEADING)
            self.assertTrue(body, f"{name}: no '{HEADING}' section")
            for phrase in ("FIRST LINE", "NO tool call", "ONE batched",
                           "Pick: X", "BUY:", "one bash call, one line"):
                self.assertIn(phrase, body, f"{name}: missing {phrase!r}")

    def test_shared_paragraph_is_identical(self):
        bodies = {n: _section(self._skill(n), HEADING) for n in THREE}
        ref = bodies["turn-advisor"]
        for name, body in bodies.items():
            self.assertEqual(body, ref, f"{name}: verdict-first text drifted")

    def test_no_script_before_verdict_wording_left(self):
        # research-phase step 2 used to say "Run scripts/research.py" as the
        # first act; the verdict now leads and research.py runs after it.
        text = self._skill("research-phase")
        verdict_at = text.index(HEADING)
        first_run = re.search(r"Run scripts/research\.py", text)
        self.assertTrue(first_run is None or first_run.start() > verdict_at,
                        "research-phase still runs research.py before the verdict")


class TestDraftVariant(unittest.TestCase):
    def test_draft_flow_in_research_phase(self):
        text = (SKILLS / "research-phase" / "SKILL.md").read_text()
        body = _section(text, "## Draft variant")
        self.assertTrue(body, "no '## Draft variant' section")
        for phrase in ("pick-1-pass", "draft=true", "4 cards", "pick 1",
                       "3 cards", "2 cards", "4th", "Pick: X", "BUY: X + Y",
                       "3 MC each", "discarded", "denial", "--quick"):
            self.assertIn(phrase, body, f"draft section missing {phrase!r}")


class TestRoundLoop(unittest.TestCase):
    """turn-advisor's two-lane round loop (API play): compact, and it
    names every verb the loop runs on."""

    def test_round_loop_section(self):
        text = (SKILLS / "turn-advisor" / "SKILL.md").read_text()
        heading = "## Two-lane round loop"
        m = re.search(rf"^{re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text,
                      re.M | re.S)
        self.assertTrue(m, "no '## Two-lane round loop' section")
        body = m.group(1).strip()
        self.assertLessEqual(len(body.splitlines()), 40,
                             "round-loop section must stay ≤ 40 lines")
        for phrase in ("set --draft", "turn.py round", "planlib.py patch",
                       "turn.py go", "promote", "judgment.py set",
                       "degrade", "triggers-only", "research",
                       "executor", "SWEEP: no"):
            self.assertIn(phrase, body, f"round-loop section missing {phrase!r}")


if __name__ == "__main__":
    unittest.main()
