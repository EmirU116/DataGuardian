# Coding Style

## General
- Follow PEP 8: 4-space indents, `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_CASE` for module constants.
- Add type hints to every function signature. Put `from __future__ import annotations` at the top of modules.
- Prefer small functions that each do one thing. Name helper functions that are only used inside their module with a leading underscore (`_detect_delimiter`).
- Don't use magic numbers. Make thresholds and limits named constants at the top of the module (e.g. `SAMPLE_SIZE_BYTES`).

## Comments and docstrings
- Every module starts with a docstring explaining **how it works**: the steps it takes and the important design choices. See `src/loader.py`.
- Every public function and class has a Google-style docstring with `Args`, `Returns` and `Raises`.
- Comments explain *why*, not *what*. Example: `keep_default_na=False  # keep "NA", "null", "" as written`.

## Project structure
```
src/
  loader.py       # reading datasets (the only place that touches files)
  checks/         # one module per data-quality check
  report.py       # combines check results
tests/            # pytest tests, mirroring src/ (test_<module>.py)
notebooks/        # step-by-step walkthroughs that import from src/
data/raw-data/    # original datasets, read-only
docs/             # documentation
```

- Logic lives in `src/`. Notebooks and the Streamlit app (Phase 2) call `src/` functions and never re-implement checks.
- Only `src/loader.py` reads dataset files. Checks receive a DataFrame, which keeps them easy to test.
- Nothing writes into `data/raw-data/`.

## Data handling
- The loader keeps every value as **raw text**. Checks decide what a value should be; pandas must not guess types or turn `"NA"` into NaN before a check sees it.
- Checks never modify the DataFrame they receive.

## Check functions
Every check has the same shape:

```python
def check_something(df: pd.DataFrame) -> list[dict]:
    """..."""
```

Each finding is a dict with these keys:

| Key | Meaning |
|---|---|
| `check` | Check name, e.g. `"missing_values"` |
| `column` | Column name, or `None` for dataset-level findings |
| `severity` | `"info"`, `"warning"` or `"error"` |
| `count` / `percent` | How many values are affected |
| `message` | Human-readable explanation |
| `examples` | A few offending values |

A check must work on these edge cases without crashing:
- an empty DataFrame;
- a single row;
- a column that is entirely blank;
- unicode text.

## Error handling
- Expected failures raise a project exception with a readable message, such as `DataLoadError` for files that can't be loaded. Chain the original error with `raise ... from exc`.
- Problems that still allow the work to continue are reported as warnings or findings instead of exceptions (e.g. skipped malformed rows).
- Never use a bare `except:`. Catch specific exception types.
- Don't `print()` from library code. Return information to the caller instead.

## Tests
- Use pytest. Name tests `test_<behaviour>`, e.g. `test_row_with_too_many_fields_is_skipped_and_counted`.
- Build input files in pytest's `tmp_path` so each test controls the exact bytes on disk.
- Each edge case and failure case in a plan gets its own test.
- Run the tests before committing: `.venv/bin/pytest`.
