---
name: finish-feature
description: Take a finished feature or fix branch through the definition of done - tests, commit, qa-auditor, fix and re-check loop, then the PR with pr-creator and a watch on it. Use when a feature or fix on its branch is complete, or when the user says "finish this", "wrap up the feature", "open the PR" or "ship the feature". Not for chores (.md or small config only); those go straight to main.
---

# Finish a feature

Runs everything between "the code is done" and "the PR is open and watched", in the order `CLAUDE.md` requires ("Finishing a feature"). It exists because the routine is long, and each pitfall below cost real clean-up the first time.

## When to use
- A `feature/` or `fix/` branch is complete in Claude's judgement.
- Not for chores: if every changed file is `.md`, `.gitignore`, `requirement.txt` or `pyproject.toml`, use the chore steps in `CLAUDE.md` instead.

## Steps
1. **Check the branch is still open for work.**
   ```bash
   git branch --show-current
   gh pr list --head "$(git branch --show-current)" --state all --json number,state
   ```
   - If a PR for this branch is already `MERGED` or `CLOSED`, stop. New commits must go on a fresh branch from an updated `main` (`git checkout main && git pull --ff-only && git checkout -b <new>`). Cherry-pick any commits already made there.
   - If `main` has moved since the branch was cut, merge it in now: `git fetch -q origin && git merge --no-edit origin/main`.
2. **Tests.** Write unit tests for new business logic, algorithms and error-prone conditions. Then:
   ```bash
   .venv/bin/pytest -q
   PYTHONWARNDEFAULTENCODING=1 .venv/bin/pytest -q -W error::EncodingWarning   # same strictness as CI
   ```
   Fix failures (the code, or the test if the test is wrong) until both pass. If a failure can't be fixed, stop and report it to the user.
3. **Commit** the work: `git add <files>`, then `git commit -q -F - <<'EOF' … EOF`, ending with the attribution line from the session's instructions.
4. **QA.** Run the `qa-auditor` agent on the branch:
   - areas `code`, `pipeline` and `algorithms`;
   - add `data` and `bias` when a dataset exists under `data/raw-data/` and the change touches how data is loaded, checked or reported;
   - in the prompt, say what the branch changes and which areas are skipped, and why.
   - Don't switch branches or edit files while it runs; it reads the working tree. If other work is needed on `main` meanwhile, use a separate worktree (`git worktree add <scratch dir> main`).
5. **Fix loop.** For every `blocker` and `major`:
   - fix it, add a regression test, and repeat steps 2–4;
   - give `qa-auditor` the previous findings, so it verifies them with the original repro inputs.
   
   Stop and report to the user if a blocker or major can't be fixed. `minor` findings may stay, but they go in the PR description.
6. **Open the PR** with the `pr-creator` agent. Pass it:
   - the summary of changes;
   - the test result;
   - the QA verdict and the remaining minors.
7. **Watch the PR** with the `watch-pr` skill. Then give the user the link. The user merges; Claude never does.

## Pitfalls
- **Committing to a merged branch.** Commits pushed after a PR merged never reach `main` (seen with PR #3). That's why step 1 checks the PR state.
- **Branching from a stale `main`.** Always `git pull --ff-only` before `git checkout -b`, or merge `origin/main` in step 1.
- **New agent not callable.** An agent added in this session isn't callable until the session restarts ("Agent type '<name>' not found"). Fallback: a `general-purpose` agent told to act as `<name>`, read `.claude/agents/<name>.md` first and follow it exactly, with the same read-only limits.
- **Harmless `pr-creator` error.** Its `gh pr view --json url` check exits 1 when no PR exists yet. That's expected, not a failure.
- **Fan-out.** Don't run several QA or helper agents in parallel on feature code; `CLAUDE.md` allows one QA reviewer.

## Done when
- Both pytest runs pass, and the last `qa-auditor` verdict has no blockers or majors.
- The PR is open with the QA verdict in its description, and a watch is running on it.
