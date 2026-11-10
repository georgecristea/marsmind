"""Entry-point contract: AGENTS.md is the canonical, host-neutral session
contract; CLAUDE.md imports it; every path it names exists; every apply.py
verb is listed; Codex adapters are in sync; no personal tokens anywhere in
the entry docs, skills or agents."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / "CLAUDE.md"

# Historical tokens: game numbers, plan-item ids, calendar dates.
# Real names never belong in the tree; the operator keeps their own list
# in private/forbidden-names.txt (git-ignored, one name per line) and it
# is folded into the same check when present. A line starting with "!" is
# an ALLOWED token (e.g. the repository owner's account handle in URLs): it
# is blanked out of a line before the names are searched.
_NAMES = ROOT / "private" / "forbidden-names.txt"


def parse_name_list(text):
    """(names, allowed) from the private list: '#' comments, '!' allows."""
    names, allowed = [], []
    for raw in text.splitlines():
        n = raw.strip()
        if not n or n.startswith("#"):
            continue
        (allowed if n.startswith("!") else names).append(n.lstrip("!").strip())
    return names, [a for a in allowed if a]


def name_hits(files, names, allowed):
    """'path:line: token' for every line naming someone, allowed tokens excepted."""
    if not names:
        return []
    rx = re.compile("|".join(re.escape(n) for n in names), re.I)
    allow = re.compile("|".join(re.escape(a) for a in allowed), re.I) if allowed else None
    hits = []
    for rel, text in files:
        for i, line in enumerate(text.splitlines(), 1):
            m = rx.search(allow.sub(" ", line) if allow else line)
            if m:
                hits.append(f"{rel}:{i}: {m.group(0)!r}")
    return hits


_NAME_LIST = parse_name_list(_NAMES.read_text()) if _NAMES.exists() else ([], [])
_TOKENS = r"game ?1?[0-9]\b|\b[AB][0-9]{1,2}\b|20[0-9]{2}-[01][0-9]-[0-3][0-9]"
if _NAME_LIST[0]:
    _TOKENS = "|".join([re.escape(n) for n in _NAME_LIST[0]] + [_TOKENS])
FORBIDDEN = re.compile(_TOKENS, re.I)

PATH_RE = re.compile(
    r"(?<![\w/@.])((?:scripts|skills|agents|docs|strategy|cards|tests|\.codex)/[\w./-]*\w)")


def scrub_targets():
    files = [AGENTS, CLAUDE]
    files += sorted((ROOT / "skills").glob("*/SKILL.md"))
    files += sorted((ROOT / "agents").glob("*.md"))
    return files


class TestAgentsMd(unittest.TestCase):
    def test_exists_and_short(self):
        self.assertTrue(AGENTS.exists(), "AGENTS.md missing")
        n = len(AGENTS.read_text().splitlines())
        self.assertLessEqual(n, 200, f"AGENTS.md has {n} lines (max 200)")

    def test_claude_md_imports_agents_md(self):
        first = CLAUDE.read_text().splitlines()[0].strip()
        self.assertEqual(first, "@AGENTS.md")
        self.assertFalse(CLAUDE.is_symlink(), "CLAUDE.md must be a file, not a symlink")

    def test_every_referenced_path_exists(self):
        text = AGENTS.read_text()
        missing = []
        for m in PATH_RE.finditer(text):
            rel = m.group(1)
            if "*" in rel or "<" in rel:
                continue
            if not (ROOT / rel).exists():
                missing.append(rel)
        self.assertEqual(missing, [], f"AGENTS.md references missing paths: {missing}")

    def test_every_apply_verb_listed(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/apply.py"), "--help"],
                           capture_output=True, text=True)
        m = re.search(r"\{([a-z,]+)\}", r.stdout)
        self.assertIsNotNone(m, "could not parse apply.py --help")
        verbs = m.group(1).split(",")
        self.assertGreaterEqual(len(verbs), 30)
        text = AGENTS.read_text()
        absent = [v for v in verbs if not re.search(rf"\b{re.escape(v)}\b", text)]
        self.assertEqual(absent, [], f"apply.py verbs missing from AGENTS.md: {absent}")

    def test_minimal_reread_set_named(self):
        text = AGENTS.read_text()
        for needle in ("state/game.json", "state/log.md", "planlib.py show",
                       "skills/turn-advisor", "skills/execution-trace"):
            self.assertIn(needle, text)


class TestCodexSync(unittest.TestCase):
    def test_sync_check_passes(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/sync_codex_agents.py"),
                            "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_adapter_per_agent(self):
        for md in (ROOT / "agents").glob("*.md"):
            toml = ROOT / ".codex" / "agents" / f"{md.stem}.toml"
            self.assertTrue(toml.exists(), f"missing {toml}")


class TestScrubbed(unittest.TestCase):
    def test_no_forbidden_tokens(self):
        hits = []
        for f in scrub_targets():
            for i, line in enumerate(f.read_text().splitlines(), 1):
                m = FORBIDDEN.search(line)
                if m:
                    hits.append(f"{f.relative_to(ROOT)}:{i}: {m.group(0)!r}")
        self.assertEqual(hits, [], "personal/historical tokens found:\n" + "\n".join(hits))

    def test_no_private_file_references(self):
        bad = re.compile(r"runbook|handoff|frames\.py|table-roster", re.I)
        hits = [f"{f.relative_to(ROOT)}:{i}" for f in scrub_targets()
                for i, line in enumerate(f.read_text().splitlines(), 1) if bad.search(line)]
        self.assertEqual(hits, [], f"stale references: {hits}")


def tracked_text_files():
    """Every git-tracked file that decodes as text (the whole public tree)."""
    r = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    out = []
    for rel in filter(None, r.stdout.split("\0")):
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            out.append((rel, p.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return out


class TestPublicTree(unittest.TestCase):
    """The tree is public: no real names and no home paths in ANY tracked
    file — tests, fixtures, docs and scripts included, not only the entry
    docs that TestScrubbed covers."""

    def setUp(self):
        self.files = tracked_text_files()
        if self.files is None:
            self.skipTest("not a git checkout")

    def test_no_real_names_in_any_tracked_file(self):
        if not _NAMES.exists():
            self.skipTest("operator check: needs private/forbidden-names.txt")
        names, allowed = _NAME_LIST
        if not names:
            self.skipTest("private/forbidden-names.txt has no names")
        hits = name_hits(self.files, names, allowed)
        self.assertEqual(hits, [], f"{len(hits)} real-name hits:\n"
                         + "\n".join(hits[:60]))

    def test_allow_lines_exempt_a_token_but_not_the_name(self):
        names, allowed = parse_name_list("# comment\nQuorvel\n!quorvelhandle\n")
        self.assertEqual((names, allowed), (["Quorvel"], ["quorvelhandle"]))
        files = [("README.md", "github.com/quorvelhandle/x\nask Quorvel\n")]
        self.assertEqual(name_hits(files, names, allowed), ["README.md:2: 'Quorvel'"])

    def test_no_home_directory_paths(self):
        rx = re.compile(r"/(?:Users|home)/[A-Za-z][\w.-]*/")
        hits = [f"{rel}:{i}" for rel, text in self.files
                for i, line in enumerate(text.splitlines(), 1) if rx.search(line)]
        self.assertEqual(hits, [], f"home-directory paths: {hits}")


if __name__ == "__main__":
    unittest.main()
