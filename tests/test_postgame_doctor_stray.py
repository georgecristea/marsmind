"""doctor: flag stray empty files in the repo root (D8).

From the blind 2p game: two malformed plan submissions (shell quoting) left
EIGHT empty untracked files in the repository root. They were spotted and
removed before commit, but only because someone looked. A pre-game check
costs nothing and catches the next one.

Advisory only — it never makes the repo unplayable, because an empty stray
file has no effect on a game in progress.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import doctor


class TestStrayRootFiles(unittest.TestCase):

    def _root(self, names=()):
        d = Path(self._tmp.name)
        (d / "scripts").mkdir(exist_ok=True)
        for n in names:
            (d / n).write_text("")
        return d

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_clean_root_passes(self):
        self.assertTrue(doctor.check_stray_root_files(self._root()).ok)

    def test_empty_stray_files_are_named(self):
        c = doctor.check_stray_root_files(self._root(["1a", "2b", "steps"]))
        self.assertFalse(c.ok)
        self.assertIn("1a", c.text)
        self.assertIn("3", c.text)

    def test_known_empty_markers_are_not_flagged(self):
        self.assertTrue(doctor.check_stray_root_files(
            self._root([".gitkeep", "py.typed"])).ok)

    def test_non_empty_root_files_are_never_flagged(self):
        d = self._root()
        (d / "README.md").write_text("# real content")
        self.assertTrue(doctor.check_stray_root_files(d).ok)

    def test_it_is_advisory_and_never_blocks_play(self):
        d = self._root(["1a"])
        (d / "cards").mkdir(); (d / "cards" / "db.json").write_text("{}")
        report = doctor.Report(checks=[doctor.check_stray_root_files(d)])
        self.assertTrue(report.playable,
                        "a stray empty file must not make the repo unplayable")


if __name__ == "__main__":
    unittest.main()
