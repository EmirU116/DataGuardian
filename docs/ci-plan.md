# Plan: CI test workflow

Branch: `chore/ci-tests`

## Goal
Run the test suite on GitHub automatically, so a PR shows a green check or a red cross before anyone reviews it. Until now the tests ran only on whoever's machine opened the PR.

This branch also records the "watch and continue" routine: what Claude does after a PR is opened and then merged (see the last section).

## Scope
- One GitHub Actions workflow: `.github/workflows/tests.yml`.
- It runs on:
  - every pull request into `main`, `dev` or `testing`;
  - every push to `main` (after a merge), so `main` itself is checked;
  - manual runs from the Actions tab (`workflow_dispatch`).
- Steps:
  1. Check out the code.
  2. Set up Python 3.14, the version used locally, with pip caching keyed on `requirement.txt`.
  3. Create `.venv` and install `requirement.txt` into it, so CI uses exactly the commands in `CLAUDE.md`.
  4. Run `.venv/bin/pytest -q`.
- `docs/workflow.md` gets a section on CI, and `CLAUDE.md` a line pointing to it.

## Out of scope
- Running `qa-auditor` or any Claude-based job in CI. That needs Claude credentials stored as a GitHub secret, and comes later.
- Linting and formatting checks. The project has no linter configured yet.
- Testing on several Python versions or operating systems. The project targets one version; a matrix can be added if that changes.
- Making the check required before merging. This is a GitHub setting (branch protection) that only the repository owner can turn on; it is described in `docs/workflow.md`.

## Worst-case scenarios and how the plan handles them
| Risk | What could go wrong | Handling |
|---|---|---|
| Tests depend on local files | `data/` is git-ignored, so a test reading a real dataset would pass locally and fail in CI. | Checked: `tests/test_loader.py` only uses pytest's `tmp_path`. `docs/coding-style.md` and this plan keep that rule: tests build their own fixtures. |
| Python version mismatch | Python 3.14 not available on the runner, or `pandas>=3.1` not installable for it. | `actions/setup-python` provides 3.14. If the install fails, the job fails loudly at the install step, not silently in the tests. |
| Slow installs | `jupyter` pulls in many packages and is only needed for notebooks. | pip caching. `timeout-minutes: 15` stops a hung job. If installs stay slow, split notebook packages into a separate requirements file later. |
| Hung or runaway job | A test hangs and burns Actions minutes. | Job timeout of 15 minutes. |
| Wasted runs | Several pushes to one PR start overlapping runs. | `concurrency` cancels the older run on the same branch. |
| Too many permissions | The workflow token can write to the repo. | `permissions: contents: read`. The job only reads code. |
| PRs from forks | A fork PR could run untrusted code with secrets. | The workflow uses no secrets and only read permission, and it uses the `pull_request` trigger (not `pull_request_target`), so a fork's code never sees anything sensitive. |
| Hidden default-encoding bugs | Code that calls `open()` without `encoding=` works on Linux (UTF-8 default) but breaks for users on a non-UTF-8 Windows locale. | CI sets `PYTHONWARNDEFAULTENCODING=1`, and `pyproject.toml` turns `EncodingWarning` into an error, so such a call fails the tests. (Forcing `PYTHONUTF8=1` was rejected: it would hide these bugs instead of catching them.) Tests write bytes explicitly. |
| CI can't be run locally | The workflow can only be fully tested on GitHub. | Locally: validate the YAML, and repeat the job's steps in a fresh virtual environment. On GitHub: the PR for this branch is the first real run, watched until it finishes. |

## How it fits the project rules
- **Feature branch and PR:** this work happens on `chore/ci-tests` and ends in a PR, following the definition of done in `CLAUDE.md`.
- **Error handling:** no project code changes. The workflow fails visibly at the step that broke.
- **Packages:** no new packages are needed.
- **Raw data:** the workflow never touches `data/`.
- **Agents:** none are added. `pr-creator` and `qa-auditor` are used as usual.

## Watch and continue (routine after a PR)
Agreed with the user: after a PR is opened, Claude keeps going on its own.
1. After `pr-creator` opens the PR, Claude starts a background watch on it in the same session (polling `gh pr view <n> --json state,reviewDecision` and `gh pr checks <n>` every few minutes).
2. If CI fails on the PR, Claude fixes it on the same branch and pushes again.
3. When the user merges the PR, Claude deletes the local branch, updates `main`, and starts the next item in the "Suggested branch order" of the current phase plan. It goes all the way: plan, code, tests, QA, PR.
4. If the PR is closed without merging, or the user requests changes, Claude stops and asks the user.
5. When there is no next item in the plan, Claude stops and reports that the phase is done.

The watch only runs while the Claude Code session is open. Nothing runs on GitHub on Claude's behalf.

## Done when
- `.github/workflows/tests.yml` exists and its YAML is valid.
- The same steps pass locally in a fresh virtual environment.
- The workflow runs on this branch's PR and passes.
- `docs/workflow.md` and `CLAUDE.md` describe CI and the watch-and-continue routine.
