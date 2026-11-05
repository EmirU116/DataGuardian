# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project
Data Quality Guardian analyzes CSV datasets to spot bad data so they can be cleaned. Checks include duplicates, missing values, wrong or unexpected column data types, schema changes, inconsistent formats, invalid values and dirty text.

See @./README.md for the project description.

## Project status
Phase 1 (detection engine) is in progress; see `docs/phase-1-plan.md` for scope and order of work. There is no Streamlit app yet (Phase 2). Update the commands below when an app entry point exists.

## Tech Stack
- Language: Python
- Frontend: Streamlit (UI and graphs for the analyzed data)
- Notebooks: use `.ipynb` files to transform a dataset step by step, with an explanation for each step.
- Packages: install with `pip install <package-name>` and add every new package to `requirement.txt` (the name is singular in this project).

## Commands
The project uses a virtual environment in `.venv/` (the system Python does not allow global pip installs).
- Create the environment: `python3 -m venv .venv`
- Install dependencies: `.venv/bin/pip install -r requirement.txt`
- Run all tests: `.venv/bin/pytest`
- Run one test file: `.venv/bin/pytest tests/test_loader.py`
- Run one test: `.venv/bin/pytest tests/test_loader.py::test_name`

## Architecture
- `src/loader.py`: `load_csv()` is the single entry point for reading a dataset. It reads **every column as raw text** (`dtype=str`, `keep_default_na=False`), so values like `"NA"`, `""` and `"abc"` in a numeric column survive for the checks to inspect. It returns a `LoadResult` (DataFrame plus encoding, delimiter, skipped rows and warnings) and raises `DataLoadError` for files that cannot be analyzed.
- `src/checks/`: one module per check; each takes a DataFrame and returns a list of finding dicts (shape in `docs/phase-1-plan.md`).
- Notebooks import from `src/`; they never reimplement check logic.

## Folder structure
- `./src`: source code.
- `./data`: dataset files such as `.csv`.
- `./data/raw-data`: original, unmodified datasets. Never write to or modify files here; save cleaned or derived output elsewhere under `./data`.
- `./docs`: all documentation.
- `requirement.txt`: package dependencies.

## Codebase rules
- Before writing any code for a feature, you MUST make a plan first. The plan covers worst-case scenarios and how the feature fits the existing system and these rules.
- Exception: small changes, such as editing `.md` files, do not need a plan and may be committed directly to `main` without a feature branch.
- Comment the code for readability, and give functions/modules docstrings explaining how the code works.
- Error handling is required, especially when working with APIs.
- Write tests for functions that contain business logic, complex algorithms or error-prone conditions.
- Repeated tasks or multi-step tasks should be turned into a skill.

## Git workflow
Never work directly on `main` (except for the small changes allowed above). Create a branch for each feature, open a PR into `main`, `dev` or `testing` when it is done, and delete the branch once the PR is accepted.

### Finishing a feature (definition of done)
When Claude is satisfied that a feature on its branch is complete, it does the following without waiting to be asked:
1. Write unit tests for the new code where the rule under "Codebase rules" requires them (business logic, complex algorithms, error-prone conditions). Docs-only changes need no tests.
2. Run the full suite: `.venv/bin/pytest`.
3. If any test fails, fix the code (or the test, if the test is wrong) and run the suite again. Never open a PR with failing tests. If the failure cannot be fixed, stop and report it to the user instead.
4. Commit the work on the feature branch.
5. Run the `qa-auditor` agent on the branch with the areas `code`, `pipeline` and `algorithms`. Add `data` and `bias` when a dataset exists under `data/raw-data/` and the feature changes how data is loaded, checked or reported. Docs-only branches skip this step.
6. Fix every `blocker` and `major` finding in this session, then repeat steps 2–5. If a blocker or major can't be fixed, stop and report it to the user instead of opening a PR.
7. Open a PR with the `pr-creator` agent (`.claude/agents/pr-creator.md`). Pass it the test result, a summary of the changes, the QA verdict, and any remaining `minor` findings so the reviewer sees them.
8. Give the user the PR link. The user reviews and merges every PR; Claude never merges one itself.

## Agents
- Multi-agent work is NOT allowed when developing a feature: do not spawn parallel or fan-out subagents to plan, write or review feature code. Work on a feature in a single session so the user stays in control of what changes.
- Allowed: single-purpose agents that are part of the project's own system and help the user, such as `pr-creator`. New agents of this kind go in `.claude/agents/` and must focus on one specific task.
- Exception for QA: the `qa-auditor` agent may review feature code, data, pipelines and algorithms, including bias testing. It is read-only and only reports findings; the main session fixes them, so the user stays in control of every change.
- Current agents: `pr-creator`, `branch-cleaner`, `dataset-profiler`, `dependency-checker`, `docs-sync-checker`, `qa-auditor`. See `docs/agents.md` for what each does and when to use it; add a row there for every new agent.

## Documentation
- `./docs/workflow.md`: workflows (such as the git branch workflow above) with an explanation of the problem each one solves and why it is used.
- `./docs/coding-style.md`: the project's coding style and how to structure code.
- `./docs/agents.md`: the project's helper agents, what each does and how to add one.
