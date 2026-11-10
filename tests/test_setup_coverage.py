"""Warn BEFORE a game starts when the setup exceeds the data we hold.

cards/db.json carries base + corporateEra only — extract_cards.py filters to
those two manifests by construction, and board.json is Tharsis only
(extract_board.py reads TharsisBoard.ts and hardcodes its volcano/Noctis
names). validate_setup checked players, colours and seating but said nothing
about either, so a Prelude or Hellas game could be set up and would fail
mid-game: an unknown card raises "not in cards/db.json" on `play`, and a
different map makes every hex id and placement bonus wrong.

Advisory, never blocking: the player may knowingly accept degraded tracking
and drive unknown cards with an explicit --cost. The point is that the choice
is made with open eyes at setup, not discovered in generation 4.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tmlib


def _setup(expansions, game_map="tharsis"):
    return {"playerCount": 2,
            "players": [{"name": "A", "color": "red", "isMe": True},
                        {"name": "B", "color": "blue", "isMe": False}],
            "expansions": expansions, "map": game_map,
            "seatingOrder": ["A", "B"], "firstPlayerGen1": "A"}


class TestSetupCoverageWarnings(unittest.TestCase):

    def test_base_corporate_era_tharsis_is_clean(self):
        self.assertEqual(
            tmlib.setup_coverage_warnings(_setup(["base", "corporateEra"])), [])

    def test_wgt_and_draft_need_no_card_data(self):
        s = _setup(["base", "corporateEra", "wgt"])
        s["draft"] = True
        self.assertEqual(tmlib.setup_coverage_warnings(s), [])

    def test_prelude_is_flagged_by_name(self):
        w = " ".join(tmlib.setup_coverage_warnings(
            _setup(["base", "corporateEra", "prelude"])))
        self.assertIn("prelude", w.lower())
        self.assertIn("db.json", w)

    def test_every_unsupported_expansion_is_named(self):
        w = " ".join(tmlib.setup_coverage_warnings(
            _setup(["base", "venus", "colonies", "turmoil"])))
        for mod in ("venus", "colonies", "turmoil"):
            self.assertIn(mod, w.lower())

    def test_non_tharsis_map_is_flagged(self):
        w = " ".join(tmlib.setup_coverage_warnings(
            _setup(["base", "corporateEra"], game_map="hellas")))
        self.assertIn("hellas", w.lower())
        self.assertIn("board.json", w)

    def test_warnings_never_raise(self):
        """A setup we cannot fully back must still be creatable."""
        s = _setup(["base", "prelude"], game_map="elysium")
        tmlib.validate_setup(s)          # must not raise
        self.assertEqual(len(tmlib.setup_coverage_warnings(s)), 2)


class TestDoctorSurfacesCoverage(unittest.TestCase):
    """The pre-game ritual is `doctor.py`, so it must say so too."""

    def setUp(self):
        import doctor
        from tempfile import TemporaryDirectory
        self.doctor = doctor
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "state").mkdir()

    def _write(self, setup):
        import json
        (self.root / "state" / "setup.json").write_text(json.dumps(setup))

    def test_clean_setup_passes(self):
        self._write(_setup(["base", "corporateEra"]))
        self.assertTrue(self.doctor.check_setup_coverage(self.root).ok)

    def test_unsupported_expansion_is_reported(self):
        self._write(_setup(["base", "prelude"]))
        c = self.doctor.check_setup_coverage(self.root)
        self.assertFalse(c.ok)
        self.assertIn("prelude", c.text.lower())
        self.assertFalse(c.required, "must never block play")

    def test_no_active_session_is_silent(self):
        import shutil
        shutil.rmtree(self.root / "state")
        self.assertTrue(self.doctor.check_setup_coverage(self.root).ok)


if __name__ == "__main__":
    unittest.main()
