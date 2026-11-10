"""bugs.py — multi-agent bug inbox: file/list/claim/close, single-fixer guard."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bugs


class TestBugInbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_creates_report_with_id(self):
        bid = bugs.file_report(self.inbox, reporter="zoti", area="sparring",
                               title="wait timeout mislabels stall",
                               body="repro: ...")
        p = self.inbox / f"{bid}.md"
        self.assertTrue(p.exists())
        txt = p.read_text()
        self.assertIn("status: open", txt)
        self.assertIn("reporter: zoti", txt)

    def test_two_reports_never_collide(self):
        a = bugs.file_report(self.inbox, "a1", "x", "t", "b")
        b = bugs.file_report(self.inbox, "a2", "x", "t", "b")
        self.assertNotEqual(a, b)

    def test_claim_is_exclusive(self):
        bid = bugs.file_report(self.inbox, "zoti", "engine", "t", "b")
        bugs.claim(self.inbox, bid, by="night-shift")
        with self.assertRaises(bugs.AlreadyClaimed):
            bugs.claim(self.inbox, bid, by="advisor")
        self.assertIn("claimed-by: night-shift",
                      (self.inbox / f"{bid}.md").read_text())

    def test_close_requires_claim_and_records_fix(self):
        bid = bugs.file_report(self.inbox, "zoti", "engine", "t", "b")
        with self.assertRaises(bugs.NotClaimed):
            bugs.close(self.inbox, bid, commit="abc1234")
        bugs.claim(self.inbox, bid, by="night-shift")
        bugs.close(self.inbox, bid, commit="abc1234")
        txt = (self.inbox / f"{bid}.md").read_text()
        self.assertIn("status: fixed", txt)
        self.assertIn("abc1234", txt)

    def test_list_filters_open(self):
        a = bugs.file_report(self.inbox, "r", "x", "one", "b")
        b = bugs.file_report(self.inbox, "r", "x", "two", "b")
        bugs.claim(self.inbox, b, by="f"); bugs.close(self.inbox, b, commit="c")
        open_ids = [e["id"] for e in bugs.list_reports(self.inbox, only_open=True)]
        self.assertEqual(open_ids, [a])


if __name__ == "__main__":
    unittest.main()
