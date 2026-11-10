@AGENTS.md

## Claude Code
- Auto-memory: Claude Code keeps its own notes under
  `~/.claude/projects/<project>/memory/` (MEMORY.md index + topic files).
  Rules and procedures belong in AGENTS.md and skills/, never only there.
- Agents: dispatch agents/*.md through the Agent tool — the prompt names
  the agent file and the agent reads it in full. Sparring seats are one
  fresh agent per seat per generation (agents/sparring-partner.md).
- `CLAUDE.local.md` (git-ignored) is where the player keeps personal table
  notes and preferences; Claude Code loads it after this file.

## Private documents (player-specific — never in git)
Session briefs for a successor session, implementation plans, post-game
analyses, play history, table notes and results ledgers are the player's
private documents. They live under `private/` (git-ignored) — never
elsewhere in the tree, never committed or pushed. A brief for the next
session goes to `private/plans/` and is referenced from auto-memory, not
from the repository.
