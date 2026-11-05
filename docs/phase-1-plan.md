# Phase 1 Plan: Foundation and Detection Engine

## Goal
Load a CSV dataset, run a set of data-quality checks on it, and produce a structured report of the problems found.

Phase 1 **detects** problems only. It does not modify data.

The engine is plain Python in `src/`, independent of Streamlit and notebooks, so later phases can build a UI and cleaning steps on top of it.

## Decisions
| Topic | Decision |
|---|---|
| Dataset | A public, deliberately messy CSV, stored unmodified in `data/raw-data/` |
| Scope | Detection only; fixing/cleaning moves to Phase 2 |
| Schema-change detection | Later phase |
| UI | Streamlit dashboard in Phase 2 |
| Testing | pytest |

**Candidate dataset:** Kaggle "Cafe Sales - Dirty Data for Cleaning Training". It has about 10k rows, with missing values, `ERROR`/`UNKNOWN` placeholders and numbers stored as text. Confirm availability and license before downloading.

**Fallback:** Titanic (`train.csv`), which mainly tests missing values and mixed types.

## Target structure
```
src/
  loader.py          # safe CSV loading
  checks/
    missing.py       # missing values
    duplicates.py    # duplicate rows / keys
    dtypes.py        # data-type problems
    formats.py       # format consistency
  report.py          # combines check results
tests/
  fixtures/          # small hand-made CSVs with known problems
  test_*.py
notebooks/
  01_explore.ipynb   # step-by-step demo on the sample dataset
data/
  raw-data/          # original datasets, never modified
docs/
  workflow.md
  coding-style.md
requirement.txt
```

## Work items

### 1. Project setup
- Create the folders above and `requirement.txt` with `pandas`, `pytest` and `jupyter`.
- Write `docs/workflow.md` (feature-branch workflow) and `docs/coding-style.md`.
- Add a `.gitignore` covering virtual environments, `__pycache__`, notebook checkpoints and large data files.

### 2. CSV loader (`src/loader.py`)
`load_csv(path) -> pandas.DataFrame`

Reads every column as **text** first, so the type checks can see what is actually in the file.

Failure cases it must handle with a clear error:
- The file does not exist, or is not a `.csv`.
- The file is empty, or has a header but no rows.
- The file encoding is not UTF-8. Retry with `latin-1` and report which encoding was used.
- The separator is not a comma (`;`, tab). Detect it with `csv.Sniffer`.
- Malformed rows with the wrong number of fields. Count and report them instead of crashing.
- Duplicate or blank column names.
- Very large files. Phase 1 warns above a size threshold; chunked loading is deferred.

### 3. Checks (`src/checks/`)
Every check has the same shape: it takes a DataFrame and returns a list of findings. Each finding is a small dict:

```python
{"check": "missing_values", "column": "price", "severity": "warning",
 "count": 42, "percent": 4.2, "message": "...", "examples": [...]}
```

| Check | Detects |
|---|---|
| Missing values | Real nulls and disguised blanks (`""`, whitespace-only, `NA`, `N/A`, `null`, `None`, `-`, `?`, `UNKNOWN`, `ERROR`), per column, as counts and % |
| Duplicates | Fully duplicated rows; duplicates in a given key column (optional argument) |
| Data types | The type a column *should* be (int/float/date/bool/text), inferred from what most values parse as, plus the values that don't fit (e.g. `"abc"` in a mostly numeric column) |
| Formats | Leading/trailing whitespace, inconsistent casing of the same value (`"Cash"`/`"cash"`), mixed date formats within one column |

Edge cases every check must handle:
- An empty DataFrame.
- A single-row dataset.
- A column that is entirely blank.
- Unicode text.
- Very wide datasets.

### 4. Report (`src/report.py`)
`run_all_checks(df) -> Report`

The report contains:
- **Dataset summary:** number of rows and columns, file size, encoding.
- **Findings:** the list of all findings, sorted by severity.
- **Per-column summary:** a table that Phase 2 will render in Streamlit.

If one check fails, the report records the error and the remaining checks still run.

### 5. Tests (`tests/`)
- pytest tests for the loader and each check, run against small fixture CSVs whose problems are known exactly.
- The tests cover each edge case listed above.
- Run them with `pytest`, or a single test with `pytest tests/test_missing.py::test_name`.

### 6. Demo notebook (`notebooks/01_explore.ipynb`)
The notebook walks through the engine on the sample dataset. It loads the file, runs each check with an explanation of what it found and why it matters, and finishes with the full report.

## Out of scope for Phase 1
- Fixing or cleaning data.
- Saving cleaned files to `data/processed/`.
- Streamlit dashboard.
- Schema-change detection: comparing against an expected schema or a previous version.
- Outlier and value-range validation.

## Done when
- `pytest` passes.
- The notebook runs top to bottom on the sample dataset and finds real problems in it.
- `docs/workflow.md` and `docs/coding-style.md` exist.
- All work is merged to `main` through PRs.

## Suggested branch order
1. `chore/project-setup`: items 1 and 2.
2. `feature/quality-checks`: item 3 and its tests.
3. `feature/report`: item 4 and its tests.
4. `docs/demo-notebook`: item 6.
