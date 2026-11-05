# Workflows

This file covers how work moves through the project. Each section says what the workflow is, the problem it solves and why we use it.

## 1. Feature-branch workflow (git)

**What:**
1. Update `main`: `git checkout main && git pull`.
2. Create a branch for the work: `git checkout -b <type>/<short-name>`.
   - The type is `feature/` for new functionality, `chore/` for setup and tooling, `docs/` for documentation, or `fix/` for bug fixes.
   - Examples: `feature/quality-checks`, `chore/project-setup`.
3. Commit on that branch. Run the tests before every commit (`.venv/bin/pytest`).
4. Push and open a PR into `main`, `dev` or `testing`. When Claude finishes a feature, it does this itself once the tests pass (see section 4).
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

## 4. Finishing a feature: test, then PR

**What:** when Claude is satisfied that a feature on its branch is complete, it does the following on its own:
1. Writes unit tests where needed (business logic, complex algorithms, error-prone conditions).
2. Runs the full suite with `.venv/bin/pytest`.
3. If tests fail, it fixes them and runs the suite again. If a failure can't be fixed, it stops and reports to the user, and no PR is opened.
4. Once all tests pass, it commits and opens a PR with the `pr-creator` agent. `pr-creator` runs the tests once more and refuses to open the PR if any fail.
5. The user reviews the PR and merges it. Claude never merges.

**Problem it solves:** before this rule, "done" depended on someone remembering to write tests, run them and ask for a PR. That made it easy for untested or broken code to reach review, or for finished work to sit on a branch.

**Why we use it:**
- Every PR arrives with passing tests, so review time goes to the design and the code, not to finding failing tests.
- The test run happens twice: once by Claude while working and once by `pr-creator` just before the PR is opened.
- The user stays in control: nothing reaches `main` without the user's review and merge.

## 5. Getting the sample dataset

**What:**
1. Download the sample dataset (see `docs/phase-1-plan.md`) by hand.
2. Place it unmodified in `data/raw-data/`.
3. Write cleaned or derived output elsewhere under `data/`, never into `data/raw-data/`.

**Problem it solves:** datasets can be large and come with licenses that don't allow redistribution, so committing them to git causes trouble.

**Why we use it:** `.gitignore` excludes data files and keeps only the folder structure. Everyone fetches the data themselves, and the raw copy always remains the untouched original to compare against.

## 6. Development environment

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
