# Workflows

This file covers how work moves through the project. Each section says what the workflow is, the problem it solves and why we use it.

## 1. Feature-branch workflow (git)

**What:**
1. Update `main`: `git checkout main && git pull`.
2. Create a branch for the work: `git checkout -b <type>/<short-name>`.
   - The type is `feature/` for new functionality, `chore/` for setup and tooling, `docs/` for documentation, or `fix/` for bug fixes.
   - Examples: `feature/quality-checks`, `chore/project-setup`.
3. Commit on that branch. Run the tests before every commit (`.venv/bin/pytest`).
4. Push and open a PR into `main`, `dev` or `testing`. Claude can do this with the `pr-creator` agent.
5. After the PR is merged, delete the branch locally (`git branch -d <branch>`) and on GitHub.

**Problem it solves:** if work goes straight to `main`, half-finished or broken code becomes the version everyone builds on, and there is no point at which changes are reviewed.

**Why we use it:**
- `main` always works.
- Each feature is reviewed as a whole through its PR.
- An unfinished experiment can be thrown away by deleting its branch.

**Exception:** small changes, such as editing `.md` files, may be committed directly to `main` (see `CLAUDE.md`).

## 2. Plan before code

**What:** before coding a feature, write a plan covering:
- the scope;
- the worst-case scenarios and edge cases;
- how the feature fits the existing structure and rules.

Large plans go in `docs/` (e.g. `docs/phase-1-plan.md`).

**Problem it solves:** without a plan, edge cases are discovered late, after the design is built, and the fixes get bolted on.

**Why we use it:** writing the failure cases down first turns them directly into tests and keeps the design consistent.

## 3. Single-session feature work (no multi-agent)

**What:** a feature is developed in one Claude Code session. Parallel or fan-out subagents are not used to plan, write or review feature code. Single-purpose agents that are part of the project's system, such as `pr-creator`, are allowed.

**Problem it solves:** with several agents changing code at once, it is hard to follow what changed and why, and control over the codebase is lost.

**Why we use it:** every change stays visible and reviewable by the user.

## 4. Getting the sample dataset

**What:**
1. Download the sample dataset (see `docs/phase-1-plan.md`) by hand.
2. Place it unmodified in `data/raw-data/`.
3. Write cleaned or derived output elsewhere under `data/`, never into `data/raw-data/`.

**Problem it solves:** datasets can be large and come with licenses that don't allow redistribution, so committing them to git causes trouble.

**Why we use it:** `.gitignore` excludes data files and keeps only the folder structure. Everyone fetches the data themselves, and the raw copy always remains the untouched original to compare against.

## 5. Development environment

**What:**
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirement.txt
.venv/bin/pytest
```

**Problem it solves:** the system Python refuses global `pip install`. Without an isolated environment, package versions also differ between machines.

**Why we use it:**
- A per-project `.venv/` keeps dependencies isolated.
- `requirement.txt` pins the version ranges.
