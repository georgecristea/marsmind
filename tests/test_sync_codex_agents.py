"""scripts/sync_codex_agents.py — agents/<name>.md (canonical, YAML
frontmatter) → .codex/agents/<name>.toml adapters. Generate, --check,
stale/orphan/unmanaged detection, actionable frontmatter errors, TOML
round-trip via tomllib."""
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sync_codex_agents.py"
sys.path.insert(0, str(ROOT / "scripts"))
import sync_codex_agents as sca  # noqa: E402

NARRATOR_MD = """---
description: Use when: a finished game folder needs its saga and insights.
tools: [read, edit]
user-invocable: true
---
# Agent: narrator
Body of the canonical agent.
"""

VISION_MD = """---
description: Use when: a batch of table photos must become observations.
tools: [read]
user-invocable: false
---
# Agent: vision-extractor
Read-only.
"""

SKILL_MD = """---
name: turn-advisor
description: Generation plans and the anti-pass discipline.
---
# Skill: turn-advisor
"""


def make_repo(tmp: Path, agents=None, skills=None) -> Path:
    agents = {"narrator": NARRATOR_MD, "vision-extractor": VISION_MD} if agents is None else agents
    skills = {"turn-advisor": SKILL_MD} if skills is None else skills
    (tmp / "agents").mkdir()
    for name, text in agents.items():
        (tmp / "agents" / f"{name}.md").write_text(text)
    for name, text in skills.items():
        d = tmp / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(text)
    return tmp


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_sync_writes_valid_toml_and_check_is_clean(self):
        self.assertEqual(sca.sync(self.root), [])
        path = self.root / ".codex" / "agents" / "narrator.toml"
        text = path.read_text()
        self.assertEqual(text.splitlines()[0], sca.MARKER)
        data = tomllib.loads(text)
        self.assertEqual(data["name"], "narrator")
        self.assertTrue(data["description"].startswith("Use when:"))
        self.assertIn("agents/narrator.md", data["developer_instructions"])
        self.assertIn("Canonical `user-invocable` is true.", data["developer_instructions"])
        self.assertNotIn("sandbox_mode", data)          # narrator has edit
        self.assertEqual(sca.check(self.root), [])

    def test_read_only_sandbox_when_tools_lack_edit(self):
        sca.sync(self.root)
        data = tomllib.loads((self.root / ".codex/agents/vision-extractor.toml").read_text())
        self.assertEqual(data["sandbox_mode"], "read-only")
        self.assertIn("Canonical `user-invocable` is false.", data["developer_instructions"])

    def test_sync_is_idempotent(self):
        sca.sync(self.root)
        before = {p.name: p.read_text() for p in (self.root / ".codex/agents").glob("*.toml")}
        sca.sync(self.root)
        after = {p.name: p.read_text() for p in (self.root / ".codex/agents").glob("*.toml")}
        self.assertEqual(before, after)


class TestCheck(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self._tmp.name))
        sca.sync(self.root)
        self.adapters = self.root / ".codex" / "agents"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_adapter(self):
        (self.adapters / "narrator.toml").unlink()
        errs = sca.check(self.root)
        self.assertTrue(any("missing" in e and "narrator" in e for e in errs), errs)

    def test_stale_adapter_detected_and_resynced(self):
        p = self.adapters / "narrator.toml"
        p.write_text(p.read_text().replace('"narrator"', '"narrator-old"', 1))
        errs = sca.check(self.root)
        self.assertTrue(any("stale" in e and "narrator" in e for e in errs), errs)
        self.assertEqual(sca.sync(self.root), [])
        self.assertEqual(sca.check(self.root), [])

    def test_stale_when_canonical_changes(self):
        md = self.root / "agents" / "narrator.md"
        md.write_text(md.read_text().replace("tools: [read, edit]", "tools: [read]"))
        errs = sca.check(self.root)
        self.assertTrue(any("stale" in e for e in errs), errs)
        sca.sync(self.root)
        data = tomllib.loads((self.adapters / "narrator.toml").read_text())
        self.assertEqual(data["sandbox_mode"], "read-only")

    def test_orphan_generated_adapter_reported_then_removed(self):
        orphan = self.adapters / "ghost.toml"
        orphan.write_text(sca.render_toml("ghost", sca.agent_meta_from_text(NARRATOR_MD, "x")))
        errs = sca.check(self.root)
        self.assertTrue(any("orphan" in e and "ghost" in e for e in errs), errs)
        self.assertEqual(sca.sync(self.root), [])
        self.assertFalse(orphan.exists())

    def test_unmanaged_adapter_refused_not_overwritten(self):
        p = self.adapters / "narrator.toml"
        hand = 'name = "narrator"\ndescription = "mine"\ndeveloper_instructions = "x"\n'
        p.write_text(hand)
        errs = sca.sync(self.root)
        self.assertTrue(any("unmanaged adapter" in e and "agents/narrator.md" in e for e in errs), errs)
        self.assertEqual(p.read_text(), hand)
        errs = sca.check(self.root)
        self.assertTrue(any("unmanaged" in e for e in errs), errs)

    def test_unmanaged_codex_only_adapter_reported_and_kept(self):
        p = self.adapters / "extra.toml"
        p.write_text('name = "extra"\ndescription = "d"\ndeveloper_instructions = "i"\n')
        errs = sca.check(self.root)
        self.assertTrue(any("unmanaged" in e and "extra" in e for e in errs), errs)
        sca.sync(self.root)
        self.assertTrue(p.exists())

    def test_generated_toml_content_validated(self):
        p = self.adapters / "narrator.toml"
        text = p.read_text().replace("agents/narrator.md", "agents/other.md")
        p.write_text(text)
        errs = sca.check(self.root)
        self.assertTrue(errs)


class TestFrontmatter(unittest.TestCase):
    def test_missing_frontmatter_is_actionable(self):
        with self.assertRaises(sca.FrontmatterError) as cm:
            sca.agent_meta_from_text("# Agent: x\nno frontmatter\n", "agents/x.md")
        msg = str(cm.exception)
        self.assertIn("agents/x.md", msg)
        self.assertIn("---", msg)

    def test_missing_key_named(self):
        text = "---\ndescription: d\ntools: [read]\n---\nbody\n"
        with self.assertRaises(sca.FrontmatterError) as cm:
            sca.agent_meta_from_text(text, "agents/x.md")
        self.assertIn("user-invocable", str(cm.exception))

    def test_tools_must_be_inline_list_of_known_tools(self):
        text = "---\ndescription: d\ntools:\n  - read\nuser-invocable: true\n---\n"
        with self.assertRaises(sca.FrontmatterError) as cm:
            sca.agent_meta_from_text(text, "agents/x.md")
        self.assertIn("tools", str(cm.exception))
        text = "---\ndescription: d\ntools: [read, fly]\nuser-invocable: true\n---\n"
        with self.assertRaises(sca.FrontmatterError) as cm:
            sca.agent_meta_from_text(text, "agents/x.md")
        self.assertIn("fly", str(cm.exception))

    def test_user_invocable_must_be_bool(self):
        text = "---\ndescription: d\ntools: [read]\nuser-invocable: yes\n---\n"
        with self.assertRaises(sca.FrontmatterError) as cm:
            sca.agent_meta_from_text(text, "agents/x.md")
        self.assertIn("user-invocable", str(cm.exception))

    def test_codex_network_is_localhost_only(self):
        text = ("---\ndescription: d\ntools: [read]\nuser-invocable: true\n"
                "codex-network: internet\n---\n")
        with self.assertRaises(sca.FrontmatterError) as cm:
            sca.agent_meta_from_text(text, "agents/x.md")
        self.assertIn("codex-network", str(cm.exception))
        self.assertIn("localhost", str(cm.exception))

    def test_multiline_description_rejected(self):
        text = "---\ndescription: >\n  long\ntools: [read]\nuser-invocable: true\n---\n"
        with self.assertRaises(sca.FrontmatterError):
            sca.agent_meta_from_text(text, "agents/x.md")

    def test_frontmatter_error_surfaces_in_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp), agents={"bad": "# no frontmatter\n"})
            errs = sca.check(root)
            self.assertTrue(any("agents/bad.md" in e for e in errs), errs)


class TestSkillFrontmatter(unittest.TestCase):
    def test_skill_name_must_match_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = SKILL_MD.replace("name: turn-advisor", "name: other")
            root = make_repo(Path(tmp), skills={"turn-advisor": bad})
            sca.sync(root)
            errs = sca.check(root)
            self.assertTrue(any("skills/turn-advisor" in e and "name" in e for e in errs), errs)

    def test_skill_description_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = "---\nname: turn-advisor\n---\n# x\n"
            root = make_repo(Path(tmp), skills={"turn-advisor": bad})
            sca.sync(root)
            errs = sca.check(root)
            self.assertTrue(any("description" in e for e in errs), errs)


class TestCli(unittest.TestCase):
    def test_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            r = subprocess.run([sys.executable, str(SCRIPT), "--root", tmp, "--check"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("ERROR", r.stdout + r.stderr)
            r = subprocess.run([sys.executable, str(SCRIPT), "--root", tmp],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            r = subprocess.run([sys.executable, str(SCRIPT), "--root", tmp, "--check"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((root / ".codex/agents/narrator.toml").exists())

    def test_repo_adapters_are_in_sync(self):
        self.assertEqual(sca.check(ROOT), [])


if __name__ == "__main__":
    unittest.main()


SEAT_MD = """---
description: Use when: dispatching opponent seat "Anna" (Sonnet 5) in a practice game.
tools: [read, search, bash]
user-invocable: false
model: sonnet
---
# Seat Anna (Sonnet 5)
Read agents/seat-kit.md first.
"""

SEAT_LOCALHOST_MD = """---
description: Use when: dispatching opponent seat "Anna" (Sonnet 5) in a practice game.
tools: [read, search, bash]
user-invocable: false
model: sonnet
codex-network: localhost
---
# Seat Anna (Sonnet 5)
Read agents/seat-kit.md first.
"""


class TestClaudeAdapters(unittest.TestCase):
    """P7 S3: seats need to be identifiable in Claude Code's agent list, which
    reads .claude/agents/<name>.md — but agents/<name>.md is the single source
    of truth and .codex/agents/ is generated from it. Hand-writing Claude
    adapters would fork the doctrine per host. So the generator emits BOTH
    adapters from the one canonical file, and an optional `model:` key pins
    the seat's model on both hosts."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self._tmp.name),
                              agents={"narrator": NARRATOR_MD,
                                      "seat-anna-sonnet-5": SEAT_MD})
        self.claude = self.root / ".claude" / "agents"
        self.codex = self.root / ".codex" / "agents"

    def tearDown(self):
        self._tmp.cleanup()

    def test_model_key_is_accepted(self):
        meta = sca.agent_meta_from_text(SEAT_MD, "agents/seat-anna-sonnet-5.md")
        self.assertEqual(meta["model"], "sonnet")
        self.assertIsNone(sca.agent_meta_from_text(NARRATOR_MD, "x").get("model"))

    def test_model_must_be_a_known_tier(self):
        bad = SEAT_MD.replace("model: sonnet", "model: gpt-9")
        with self.assertRaises(sca.FrontmatterError) as cm:
            sca.agent_meta_from_text(bad, "agents/seat.md")
        self.assertIn("model", str(cm.exception))

    def test_sync_writes_a_claude_adapter_per_agent(self):
        self.assertEqual(sca.sync(self.root), [])
        path = self.claude / "seat-anna-sonnet-5.md"
        self.assertTrue(path.exists())
        text = path.read_text()
        self.assertEqual(text.splitlines()[0], "---")
        fields = sca.parse_frontmatter(text, "x")
        self.assertEqual(fields["name"], "seat-anna-sonnet-5")
        self.assertEqual(fields["model"], "sonnet")
        self.assertTrue(fields["description"].startswith("Use when:"))
        self.assertIn("agents/seat-anna-sonnet-5.md", text)   # points home
        self.assertIn(sca.MARKER_MD, text)                     # generated marker

    def test_claude_tools_are_mapped_to_claude_names(self):
        sca.sync(self.root)
        fields = sca.parse_frontmatter(
            (self.claude / "seat-anna-sonnet-5.md").read_text(), "x")
        self.assertEqual(fields["tools"], "[Read, Grep, Glob, Bash]")
        fields = sca.parse_frontmatter((self.claude / "narrator.md").read_text(), "x")
        self.assertIn("Edit", fields["tools"])
        self.assertNotIn("model", fields)          # no model → inherit

    def test_codex_adapter_carries_the_model(self):
        sca.sync(self.root)
        data = tomllib.loads((self.codex / "seat-anna-sonnet-5.toml").read_text())
        self.assertEqual(data["model"], "sonnet")
        data = tomllib.loads((self.codex / "narrator.toml").read_text())
        self.assertNotIn("model", data)

    def test_codex_localhost_agents_use_workspace_write_sandbox(self):
        sub = Path(self._tmp.name) / "localhost"
        sub.mkdir()
        root = make_repo(sub,
                         agents={"seat-anna-sonnet-5": SEAT_LOCALHOST_MD})
        self.assertEqual(sca.sync(root), [])
        data = tomllib.loads(
            (root / ".codex/agents/seat-anna-sonnet-5.toml").read_text())
        self.assertEqual(data["sandbox_mode"], "workspace-write")
        meta = sca.agent_meta_from_text(SEAT_LOCALHOST_MD,
                                        "agents/seat-anna-sonnet-5.md")
        self.assertEqual(meta["codex_network"], "localhost")
        self.assertEqual(sca.check(root), [])

    def test_check_covers_missing_stale_and_orphan_claude_adapters(self):
        sca.sync(self.root)
        self.assertEqual(sca.check(self.root), [])
        p = self.claude / "seat-anna-sonnet-5.md"
        p.unlink()
        self.assertTrue(any("missing" in e and ".claude/agents/seat-anna" in e
                            for e in sca.check(self.root)))
        sca.sync(self.root)
        p.write_text(p.read_text() + "\nhand edit\n")
        self.assertTrue(any("stale" in e and ".claude/agents/seat-anna" in e
                            for e in sca.check(self.root)))
        sca.sync(self.root)
        ghost = self.claude / "ghost.md"
        ghost.write_text(sca.render_claude_md("ghost", sca.agent_meta_from_text(SEAT_MD, "x")))
        self.assertTrue(any("orphan" in e and "ghost" in e for e in sca.check(self.root)))
        self.assertEqual(sca.sync(self.root), [])
        self.assertFalse(ghost.exists())

    def test_hand_written_claude_adapter_is_refused_not_overwritten(self):
        sca.sync(self.root)
        p = self.claude / "narrator.md"
        hand = "---\nname: narrator\ndescription: mine\n---\nmine\n"
        p.write_text(hand)
        errs = sca.sync(self.root)
        self.assertTrue(any("unmanaged" in e and "narrator" in e for e in errs), errs)
        self.assertEqual(p.read_text(), hand)

    def test_sync_is_idempotent_for_claude_adapters(self):
        sca.sync(self.root)
        before = {p.name: p.read_text() for p in self.claude.glob("*.md")}
        sca.sync(self.root)
        self.assertEqual(before, {p.name: p.read_text() for p in self.claude.glob("*.md")})
