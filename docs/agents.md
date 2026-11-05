# Agents

The project's helper agents live in `.claude/agents/`, one file per agent. Each agent does one specific task, never writes or reviews feature code, and doesn't start other agents. This keeps to the rule in `CLAUDE.md`: features are built in a single session so the user stays in control of what changes.

| Agent | What it does | When it is used | Can change things? |
|---|---|---|---|
| `pr-creator` | Runs the tests, pushes the branch and opens a PR. | When a feature is finished and its tests pass (see `docs/workflow.md`, section 4). | Pushes a branch and opens a PR. Never edits files. |
| `branch-cleaner` | Deletes branches whose PR was merged, locally and on GitHub. | After the user merges a PR, or when asked to tidy branches. | Deletes merged branches only. Never edits files. |
| `dataset-profiler` | Loads one CSV with `load_csv()` and reports size, encoding, delimiter, columns and loader warnings. | When a new dataset is added to `data/` and you want a first look. | No (read-only). |
| `dependency-checker` | Compares third-party imports in `src/`, `tests/` and `notebooks/` with `requirement.txt`. | Before a PR that adds imports, or when an install fails. | No (reports and suggests lines). |
| `docs-sync-checker` | Checks that `CLAUDE.md`, `README.md` and `docs/` still match the code: paths, function names, commands and project status. | After a feature lands, or before a PR that changes structure. | No (reports drift). |

## How to use them
Ask for the task in plain words, such as "profile the dataset in data/raw-data" or "clean up merged branches", or name the agent: "use dependency-checker". Claude starts the agent, and it reports back when done. Agents don't run automatically or watch GitHub.

## Adding a new agent
1. Make sure the task is one specific job that helps the user and doesn't involve writing or reviewing feature code.
2. Add `.claude/agents/<name>.md` with `name`, `description` and `tools` in the frontmatter. Give it only the tools it needs (read-only agents get no edit tools).
3. Add a row to the table above. `docs-sync-checker` reports any agent missing from this table.
