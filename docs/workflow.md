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

## 4. Finishing a feature: test, QA, then PR

**What:** when Claude is satisfied that a feature on its branch is complete, it does the following on its own:
1. Writes unit tests where needed (business logic, complex algorithms, error-prone conditions).
2. Runs the full suite with `.venv/bin/pytest`.
3. If tests fail, it fixes them and runs the suite again. If a failure can't be fixed, it stops and reports to the user, and no PR is opened.
4. Once all tests pass, it commits the work.
5. It runs the `qa-auditor` agent on the code, pipeline and algorithms. It also covers data and bias when a dataset is present and the feature touches data handling. Docs-only branches skip this step.
6. It fixes every `blocker` and `major` finding, then runs the tests and the QA again. If one can't be fixed, it stops and reports to the user, and no PR is opened.
7. It opens a PR with the `pr-creator` agent, which runs the tests once more and refuses to open the PR if any fail. The PR description includes the QA verdict and any remaining `minor` findings.
8. The user reviews the PR and merges it. Claude never merges.

**Problem it solves:** before this rule, "done" depended on someone remembering to write tests, run them, check quality and ask for a PR. That made it easy for untested or broken code, or code that quietly mishandles data, to reach review, or for finished work to sit on a branch.

**Why we use it:**
- Every PR arrives with passing tests and a QA report, so review time goes to the design and the code, not to finding failing tests.
- `qa-auditor` catches what unit tests miss. That includes edge cases nobody wrote a test for, checks that miscount planted defects, and cleaning that would remove far more rows from one group than another.
- The tests run at three points: by Claude while working, again after QA fixes, and by `pr-creator` just before the PR is opened.
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

## 7. Continuous integration (CI)

**What:** `.github/workflows/tests.yml` runs the tests on GitHub:
- on every PR into `main`, `dev` or `testing`;
- on every push to `main`;
- by hand from the repository's **Actions** tab.

It sets up Python 3.14, creates `.venv`, installs `requirement.txt` and runs `.venv/bin/pytest -q`: the same commands as `CLAUDE.md`. The result appears on the PR as the `Tests / pytest` check.

Tests must build their own fixtures (pytest's `tmp_path`) and never read files under `data/`, because `data/` isn't in git and doesn't exist in CI.

**Optional, recommended:** make the check required so a PR can't be merged while tests fail. On GitHub: **Settings → Branches → Add branch protection rule** (or **Rulesets**) for `main`, enable "Require status checks to pass", and select `pytest`. Only the repository owner can do this.

**Problem it solves:** tests used to run only on the machine of whoever opened the PR. A missing package in `requirement.txt`, or a test that relied on a local file, passed there and broke for everyone else.

**Why we use it:**
- Every PR is tested in a clean environment, built only from what is in git.
- The reviewer sees pass or fail on the PR without running anything.
- `main` is re-tested after each merge.

Plan and design decisions: `docs/ci-plan.md`.

## 8. Watch and continue after a PR

**What:** after Claude opens a PR, it keeps watching it in the same session:
1. If the CI check fails, it fixes the problem on the branch and pushes again.
2. When the user merges the PR, Claude deletes the local branch, updates `main`, and starts the next item in the current phase plan's "Suggested branch order". It goes through the full routine of section 4: plan, code, tests, QA and PR.
3. If the PR is closed without merging, or changes are requested, Claude stops and asks.
4. When the plan has no next item, Claude stops and reports that the phase is done.

**Problem it solves:** without it, every merge needed a new prompt ("now do the next item") and work stalled until someone remembered.

**Why we use it:**
- Work keeps moving through the plan.
- The user still reviews and merges every PR. Merging is the go-ahead for the next item.
- **Limit:** the watch only runs while the Claude Code session is open. Nothing runs on GitHub on Claude's behalf.
