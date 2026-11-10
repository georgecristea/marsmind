"""Per-player global-parameter step counter on the advisor brief.

The single sharpest signal in the blind 2p game, and it was only visible in
the post-mortem: the app's own globalParameterSteps read Mortimer 37 to
Maxwell 5, with TEMPERATURE 19-0. The losing seat's terraforming rating was
still its starting value at the end of generation 9 of 12 and the brief never
said so — it printed globals and free land, but nothing about WHO had been
raising them.

Counted from the listener's structured feed (state/feed.jsonl), which already
records one entry per app-log line with a "global: <player> raised <param>"
reason, so no new state and no new engine verb is needed. Physical mode has
no feed and simply gets no line.
"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import advise


def _feed(rows):
    return "\n".join(json.dumps(r) for r in rows) + "\n"


ROWS = [
    {"actor": "Mortimer", "kind": "played",
     "reasons": ["global: Mortimer raised oxygen +1 → 12 steps left on oxygen"]},
    {"actor": "Mortimer", "kind": "placed",
     "reasons": ["global: Mortimer raised oceans +1 → 8 steps left on oceans"]},
    {"actor": "Mortimer", "kind": "used_standard",
     "reasons": ["global: Mortimer raised temperature +1 → 18 steps left"]},
    {"actor": "Mortimer", "kind": "played",
     "reasons": ["global: Mortimer raised temperature +2 → 16 steps left"]},
    {"actor": "Maxwell", "kind": "placed",
     "reasons": ["global: Maxwell raised oceans +1 → 7 steps left on oceans"]},
    {"actor": "Maxwell", "kind": "gained", "reasons": ["asteroid target: …"]},
    {"actor": "Mortimer", "kind": "passed", "reasons": []},
]


class TestParameterStepTally(unittest.TestCase):

    def _tally(self, rows):
        with TemporaryDirectory() as d:
            p = Path(d) / "feed.jsonl"
            p.write_text(_feed(rows))
            return advise.parameter_steps(p)

    def test_counts_steps_per_player_and_parameter(self):
        t = self._tally(ROWS)
        self.assertEqual(t["Mortimer"]["temperature"], 3)   # +1 and +2
        self.assertEqual(t["Mortimer"]["oxygen"], 1)
        self.assertEqual(t["Mortimer"]["oceans"], 1)
        self.assertEqual(t["Mortimer"]["total"], 5)
        self.assertEqual(t["Maxwell"]["total"], 1)

    def test_non_global_reasons_are_ignored(self):
        t = self._tally(ROWS)
        self.assertEqual(t["Maxwell"]["oceans"], 1)
        self.assertEqual(t["Maxwell"]["temperature"], 0)

    def test_missing_feed_is_not_an_error(self):
        self.assertEqual(advise.parameter_steps(Path("/nope/feed.jsonl")), {})

    def test_line_names_both_players_and_flags_a_zero(self):
        line = advise.parameter_steps_line(self._tally(ROWS), "Maxwell")
        self.assertIn("Mortimer 5", line)
        self.assertIn("Maxwell 1", line)
        self.assertIn("temp", line.lower())

    def test_line_warns_when_I_have_raised_almost_nothing(self):
        rows = [r for r in ROWS if r["actor"] == "Mortimer"]
        line = advise.parameter_steps_line(self._tally(rows), "Maxwell")
        self.assertIn("⚠", line,
                      "a seat that has raised nothing must be told so")
        self.assertNotIn("buy a repeatable parameter source", line,
                         "the warning must not PRESCRIBE a TR pivot — two "
                         "ledger games were won while losing TR")
        self.assertIn("VP exit", line)

    def test_no_line_without_a_feed(self):
        self.assertEqual(advise.parameter_steps_line({}, "Maxwell"), "")


if __name__ == "__main__":
    unittest.main()
