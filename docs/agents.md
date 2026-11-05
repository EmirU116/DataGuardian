# Agents

The project's helper agents live in `.claude/agents/`, one file per agent. Each agent does one specific task, never writes feature code, and doesn't start other agents. This keeps to the rule in `CLAUDE.md`: features are built in a single session so the user stays in control of what changes. The one reviewer is `qa-auditor`. It may read and test feature code, but only reports what it finds; the fixes happen in the main session.

## Bias testing
`qa-auditor` includes bias (fairness) testing: checking whether a dataset could lead to unfair results for some groups of people. It finds sensitive attributes (such as gender, age or ethnicity) and likely proxies (such as zip code). It then compares, across groups:
- how well each group is represented;
- data quality: missing and invalid values;
- how many rows each group would lose if the data were cleaned;
- outcome rates, using the four-fifths rule: a ratio below 0.8 between the lowest and highest group rate is flagged;
- the same measures for combinations of groups.

The results are risk indicators to review, not a verdict: whether a gap is unfair depends on how the data will be used.

| Agent | What it does | When it is used | Can change things? |
|---|---|---|---|
| `pr-creator` | Runs the tests, pushes the branch and opens a PR. | When a feature is finished, its tests pass and QA has no blockers or majors (see `docs/workflow.md`, section 4). | Pushes a branch and opens a PR. Never edits files. |
| `branch-cleaner` | Deletes branches whose PR was merged, locally and on GitHub. | After the user merges a PR, or when asked to tidy branches. | Deletes merged branches only. Never edits files. |
| `dataset-profiler` | Loads one CSV with `load_csv()` and reports size, encoding, delimiter, columns and loader warnings. | When a new dataset is added to `data/` and you want a first look. | No (read-only). |
| `dependency-checker` | Compares third-party imports in `src/`, `tests/` and `notebooks/` with `requirement.txt`. | Before a PR that adds imports, or when an install fails. | No (reports and suggests lines). |
| `qa-auditor` | Quality assurance: data integrity, pipeline integrity (raw data untouched, no silent row loss), code and test gaps, algorithmic behavior (planted defects, invariance, determinism) and bias testing (representation, data quality and cleaning impact by group, outcome gaps, proxies). | Automatically before every feature PR (see `docs/workflow.md`, section 4), when a new dataset is analyzed, or when asked for a QA or bias review. | No (reports; the main session fixes). |
| `skill-scout` | Mines past session transcripts and `git log` for repeated multi-step tasks, and proposes them as skill candidates with evidence and pitfalls. | After each merged PR, or when asked to "find repeated tasks" (see `docs/skills.md`). | No (reports; the user approves which candidates become skills). |
| `docs-sync-checker` | Checks that `CLAUDE.md`, `README.md` and `docs/` still match the code: paths, function names, commands and project status. | After a feature lands, or before a PR that changes structure. | No (reports drift). |

## How to use them
Ask for the task in plain words, such as "profile the dataset in data/raw-data" or "clean up merged branches", or name the agent: "use dependency-checker". Claude starts the agent, and it reports back when done. Two agents also run as part of finishing a feature: `qa-auditor`, then `pr-creator` (see `docs/workflow.md`, section 4). Agents never run on their own or watch GitHub; Claude starts them during a session.

## Adding a new agent
The `add-agent` skill walks through these steps, including how to call a new agent before the session restarts.

1. Make sure the task is one specific job that helps the user and doesn't involve writing or reviewing feature code.
2. Add `.claude/agents/<name>.md` with `name`, `description` and `tools` in the frontmatter. Give it only the tools it needs (read-only agents get no edit tools).
3. Add a row to the table above. `docs-sync-checker` reports any agent missing from this table.
