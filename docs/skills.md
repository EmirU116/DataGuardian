# Skills

A **skill** is a written routine in `.claude/skills/<name>/SKILL.md`. Claude loads it into the main session when a task matches its description, and follows its steps. Skills make repeated, multi-step tasks run the same way every time, including the pitfalls learned the hard way. They're committed to git, so the whole project uses the same routines.

## Skills vs agents

| | Skill | Agent (`.claude/agents/`) |
|---|---|---|
| Runs in | The main session, with full context | A separate session that reports back |
| Good for | Multi-step routines the main session drives, such as finishing a feature or shipping a chore | One bounded job with its own context, such as a QA audit or opening a PR |
| Fits the single-session rule? | Yes: nothing runs in parallel | Only single-purpose helpers (see `docs/agents.md`) |

A skill may call agents. For example, a "finish a feature" routine can call `qa-auditor` and `pr-creator`.

## Current skills

| Skill | What it does | When it is used | Origin |
|---|---|---|---|
| `create-skill` | Writes a project skill from an approved candidate, updates this table and the candidate log, and ships it as a chore. | When the user approves a candidate, or asks to make something a skill. | Set up with the skills system (2026-11-05). |

## How repeated tasks become skills

1. **Discovery.**
   - The `skill-scout` agent mines past session transcripts and `git log` for step sequences that repeat (3+ times, or in 2+ sessions), repeated requests, and failed attempts that were later fixed.
   - It runs after each merged PR, and whenever you ask ("find repeated tasks").
   - Claude also notes repeats it notices during a session.
2. **Log.** Every candidate goes into `docs/skill-candidates.md` with its evidence and status `proposed`.
3. **Approval.** Claude posts the candidates in chat and carries on with its current work. You approve or reject each one:
   - approved candidates become `approved`;
   - rejected ones become `rejected`, with a reason, so they aren't proposed again.
4. **Creation.** Claude follows the `create-skill` skill: it writes `SKILL.md`, adds a row to the table above, marks the candidate `created`, and pushes it to `main` as a chore.

New skills appear in Claude Code's skill list from the next session on.

## Rules for every skill
- One job per skill.
- The `description` names the situations and the words that should trigger it.
- Skills follow `CLAUDE.md` and can't override it: no fan-out subagents for feature work, the definition of done still applies, and the user merges every PR.
- No secrets, dataset values or personal data in a skill.
