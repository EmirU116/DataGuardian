# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project
Data Quality Guardian analyzes CSV datasets to spot bad data so they can be cleaned. Checks include duplicates, missing values, wrong or unexpected column data types, schema changes, inconsistent formats, invalid values and dirty text.

See @./README.md for the project description.

## Project status
The repo currently holds only `README.md` and this file. No source code, dependencies, tests or docs exist yet. Create the folders below when they are first needed, and update this file with real commands (app entry point, test runner) once they exist.

## Tech Stack
- Language: Python
- Frontend: Streamlit (UI and graphs for the analyzed data)
- Notebooks: use `.ipynb` files to transform a dataset step by step, with an explanation for each step.
- Packages: install with `pip install <package-name>` and add every new package to `requirement.txt` (the name is singular in this project).

## Commands
- Install dependencies: `pip install -r requirement.txt`

## Folder structure
- `./src`: source code.
- `./data`: dataset files such as `.csv`.
- `./data/raw-data`: original, unmodified datasets. Never write to or modify files here; save cleaned or derived output elsewhere under `./data`.
- `./docs`: all documentation.
- `requirement.txt`: package dependencies.

## Codebase rules
- Before writing any code for a feature, you MUST make a plan first. The plan covers worst-case scenarios and how the feature fits the existing system and these rules.
- Comment the code for readability, and give functions/modules docstrings explaining how the code works.
- Error handling is required, especially when working with APIs.
- Write tests for functions that contain business logic, complex algorithms or error-prone conditions.
- Repeated tasks or multi-step tasks should be turned into a skill.

## Git workflow
Never work directly on `main`. Create a branch for each feature, open a PR into `main`, `dev` or `testing` when it is done, and delete the branch once the PR is accepted.

## Documentation
- `./docs/workflow.md`: workflows (such as the git branch workflow above) with an explanation of the problem each one solves and why it is used.
- `./docs/coding-style.md`: the project's coding style and how to structure code.
