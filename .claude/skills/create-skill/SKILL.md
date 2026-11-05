---
name: create-skill
description: Turn an approved skill candidate into a project skill in .claude/skills/. Use when the user approves a candidate from docs/skill-candidates.md or asks to "create a skill", "make this a skill" or "add a skill for X". Only for candidates the user has approved.
---

# Create a project skill

A skill is a written routine that Claude follows inside the main session. It makes a repeated task run the same way every time, including the pitfalls learned the hard way. This skill covers writing one for Data Quality Guardian.

## Before you start
- The candidate must have status `approved` in `docs/skill-candidates.md`, or the user must have approved it in this conversation. Never create a skill from a `proposed` or `rejected` entry.
- Check that no existing skill (`.claude/skills/*/SKILL.md`) or agent (`.claude/agents/*.md`) already covers it. If one partly does, extend that one instead and tell the user.

## Steps
1. **Get on `main`:** `git checkout main && git pull --ff-only`. A skill is a chore: it ships straight to `main` (see "Chores" in `CLAUDE.md`).
2. **Pick the name:** kebab-case and verb-first where possible (`finish-feature`, `watch-pr`, `ship-chore`). The folder is `.claude/skills/<name>/`.
3. **Write `.claude/skills/<name>/SKILL.md`** with this shape:
   ```markdown
   ---
   name: <name>
   description: <what it does in one sentence>. Use when <situations>, or when the user says "<trigger phrase>", "<another phrase>".
   ---

   # <Title>

   <One paragraph: what problem this routine solves.>

   ## When to use
   ## Steps          (numbered, with the exact commands that worked)
   ## Pitfalls       (each failure seen in the evidence, and what to do instead)
   ## Done when      (how to check the routine succeeded)
   ```
   - The `description` decides when Claude picks the skill, so put the real trigger phrases and situations in it.
   - Use the evidence from the candidate: the step sequence and the pitfalls. Don't invent steps nobody has run.
   - Keep it to one job. A routine that does two unrelated things becomes two skills.
   - Follow `CLAUDE.md`. A skill can't override its rules: no fan-out subagents for feature work, the definition of done still applies, and the user still merges every PR. A skill may call the project's single-purpose agents (`pr-creator`, `qa-auditor`, and others).
   - Supporting files (templates, scripts) go in the same folder and are referenced from `SKILL.md` by relative path. Scripts follow the project's coding style (docstrings, error handling).
4. **Check the frontmatter parses:**
   ```bash
   .venv/bin/python -I -c "import sys, yaml; t = open(sys.argv[1], encoding='utf-8').read(); print(yaml.safe_load(t.split('---')[1]))" .claude/skills/<name>/SKILL.md
   ```
   It must print a dict with `name` and `description`.
5. **Update the indexes:**
   - add a row to the table in `docs/skills.md`;
   - set the candidate's status to `created` in `docs/skill-candidates.md`, with the date.
6. **Ship it as a chore:** commit only these `.md` files with a message like `Add <name> skill`, then `git push origin main`, and check the `Tests` run on `main` (`gh run list --branch main --limit 1 --json status,conclusion`).
7. **Tell the user** the skill's name, its trigger phrases, and that it appears in the skill list after a new session starts.

## Pitfalls
- A skill whose `description` is vague ("helps with git") is never picked. Name the situation and the words a user would say.
- Skills load at session start. A new skill isn't available until a new Claude Code session, so don't try to invoke it straight away.
- Don't put secrets, dataset values or personal data in a skill: it's committed to git.

## Done when
- `.claude/skills/<name>/SKILL.md` exists and its frontmatter parses.
- `docs/skills.md` lists it, and `docs/skill-candidates.md` marks it `created`.
- The commit is on `origin/main`, and the `Tests` run for it passed.
