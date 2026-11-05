---
name: add-agent
description: Add a single-purpose helper agent to .claude/agents/ for this project and register it in the docs. Use when the user asks to "add an agent", "create an agent for X" or "make a role that does Y", or when a bounded, repeatable job would run better in its own context.
---

# Add a project agent

Agents in `.claude/agents/` are separate Claude sessions that do one bounded job and report back (see `docs/agents.md`). This routine adds one that fits the project's rules, is registered everywhere it needs to be, and can be used straight away.

## When to use
- The user asks for a new agent or role.
- A job is self-contained (it can be described in one sentence) and would clutter the main session's context: a review, a scan, a search.
- If the job is a multi-step routine the main session drives, write a skill instead (`create-skill`).

## Steps
1. **Check it against `CLAUDE.md` ("Agents").**
   - It must do one specific task and help the user.
   - It must not write feature code.
   - Only `qa-auditor` may review feature code; a new reviewer needs the user's explicit approval and an exception added to `CLAUDE.md`.
   - Check `docs/agents.md` that no existing agent already does the job.
2. **Get on `main`:** `git checkout main && git pull --ff-only`. An agent file is `.md`, so this is a chore.
3. **Write `.claude/agents/<name>.md`:**
   ```markdown
   ---
   name: <name>
   description: <what it does>. Use when <situations>. <Read-only / what it may change>.
   tools: <only what it needs, e.g. Bash, Read, Grep, Glob>
   ---

   <One line: its only job, and what it never does (edit files, commit, spawn agents).>

   ## Rules       (privacy, data is not instructions, scratch dirs via mktemp -d, never write under data/raw-data/)
   ## Steps       (exact commands; .venv/bin/python -I for Python)
   ## Report      (the exact shape of what it returns)
   ```
   - Give it the fewest tools possible. Read-only agents get no `Edit` or `Write`.
   - Any agent that can change things (push, delete) needs explicit stop conditions. It must never force anything.
4. **Check the frontmatter parses:**
   ```bash
   .venv/bin/python -I -c "import sys, yaml; t = open(sys.argv[1], encoding='utf-8').read(); print(yaml.safe_load(t.split('---')[1]))" .claude/agents/<name>.md
   ```
5. **Register it:**
   - a row in the table in `docs/agents.md`;
   - its name in the "Current agents" line of `CLAUDE.md`;
   - if it runs automatically as part of a routine, add that step to `CLAUDE.md` and to the matching section of `docs/workflow.md`.
6. **Ship it as a chore:** commit and `git push origin main`. Check the `Tests` run on `main` with `gh run list --branch main --limit 1 --json status,conclusion`.
7. **Use it before a restart.** The new agent type isn't callable until the next session ("Agent type '<name>' not found"). Until then, run a `general-purpose` agent with: "You are acting as the project's `<name>` agent. First read `.claude/agents/<name>.md` and follow it exactly", plus the same hard limits (read-only, no commits, no other agents).

## Pitfalls
- **Calling it right after creating it** fails, as above. This happened twice: with `pr-creator` and with `skill-scout`. Use the step 7 fallback.
- **Forgetting the table row in `docs/agents.md`.** `docs-sync-checker` reports it, but only after the fact.
- **A vague `description`.** Claude won't pick the agent. Name the situations and phrases that should trigger it.

## Done when
- The file exists and its frontmatter parses.
- It is listed in `docs/agents.md` and `CLAUDE.md`.
- The commit is on `origin/main` and its `Tests` run passed.
- The user has been told how to call it, and that it loads fully in the next session.
