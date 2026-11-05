"""Safe CSV loading for Data Quality Guardian.

How it works
------------
`load_csv()` is the single entry point for reading a dataset. It:

1. Validates the path: the file exists, is a regular file, ends in `.csv` and is
   not empty.
2. Reads a sample from the start of the file to:
   - detect the encoding (UTF-16 by its BOM, else UTF-8, else Latin-1);
   - refuse binary files (NUL bytes in a non-UTF-16 file);
   - detect the delimiter (`,` `;` tab `|`) with `csv.Sniffer`;
   - inspect the raw header for duplicate or blank column names.
3. Reads the whole file with pandas, keeping **every value as raw text**
   (`dtype=str`, `keep_default_na=False`). Nothing is converted to numbers, dates
   or NaN, so the checks can see exactly what is in the file: `"NA"`, `""`, `" 12 "`
   and `"abc"` all survive as written.
4. Counts malformed rows (more fields than the header) and skips them instead of
   crashing. Rows with *fewer* fields are kept; their missing fields become NaN,
   which the missing-values check reports.

Files that cannot be analyzed raise `DataLoadError` with a readable message.
Problems that still allow analysis (Latin-1 fallback, skipped rows, duplicate
column names, large file) are returned as warnings in `LoadResult.warnings`.
The original file is only ever read, never modified.
"""

from __future__ import annotations

import codecs
import csv
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# How many bytes to read from the start of the file for sniffing.
SAMPLE_SIZE_BYTES = 64 * 1024

# Delimiters we try to detect. Restricting the set stops Sniffer from picking
# letters or punctuation that merely happen to appear on every line.
CANDIDATE_DELIMITERS = ",;\t|"

# Files larger than this produce a warning (Phase 1 loads everything into memory).
DEFAULT_SIZE_WARNING_MB = 100.0

# How many malformed rows to keep as examples in the warning message.
MAX_BAD_ROW_EXAMPLES = 3

_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)


class DataLoadError(Exception):
    """Raised when a file cannot be loaded as a CSV dataset."""


@dataclass
class LoadResult:
    """A loaded dataset plus what the loader learned while reading it.

    Attributes:
        df: The data, with every column as raw text.
        path: Path of the source file.
        encoding: Encoding used to decode the file (e.g. ``"utf-8"``, ``"latin-1"``).
        delimiter: Field separator that was detected.
        file_size_bytes: Size of the file on disk.
        skipped_rows: Number of malformed rows (too many fields) that were skipped.
        warnings: Human-readable notes on problems that did not stop loading.
    """

    df: pd.DataFrame
    path: Path
    encoding: str
    delimiter: str
    file_size_bytes: int
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)


def load_csv(
    path: str | Path,
    *,
    size_warning_mb: float = DEFAULT_SIZE_WARNING_MB,
) -> LoadResult:
    """Load a CSV file safely, keeping every value as raw text.

    Args:
        path: Path to the ``.csv`` file.
        size_warning_mb: Add a warning when the file is larger than this many MB.

    Returns:
        A `LoadResult` with the DataFrame and loading metadata.

    Raises:
        DataLoadError: The file is missing, not a CSV, empty, binary, has a header
            but no data rows, or cannot be parsed.
    """
    path = Path(path)
    file_size = _validate_path(path)
    warnings: list[str] = []

    if file_size > size_warning_mb * 1024 * 1024:
        warnings.append(
            f"File is {file_size / (1024 * 1024):.1f} MB, above the "
            f"{size_warning_mb:g} MB threshold; loading may be slow or use a lot of memory."
        )

    sample = _read_sample(path)
    encoding = _detect_encoding(sample)
    text_sample = _decode_sample(sample, encoding)

    if not text_sample.strip():
        raise DataLoadError(f"File contains only whitespace: {path}")

    delimiter = _detect_delimiter(text_sample)
    warnings.extend(_check_header(text_sample, delimiter))

    df, bad_rows, encoding = _read_with_fallback(path, delimiter, encoding, warnings)

    if df.empty:
        raise DataLoadError(f"File has a header but no data rows: {path}")

    if bad_rows:
        examples = "; ".join(
            str(row) for row in bad_rows[:MAX_BAD_ROW_EXAMPLES]
        )
        warnings.append(
            f"Skipped {len(bad_rows)} malformed row(s) with more fields than the "
            f"header. Examples: {examples}"
        )

    return LoadResult(
        df=df,
        path=path,
        encoding=encoding,
        delimiter=delimiter,
        file_size_bytes=file_size,
        skipped_rows=len(bad_rows),
        warnings=warnings,
    )


def _validate_path(path: Path) -> int:
    """Check that `path` is a readable, non-empty .csv file and return its size."""
    if not path.exists():
        raise DataLoadError(f"File not found: {path}")
    if not path.is_file():
        raise DataLoadError(f"Not a file: {path}")
    if path.suffix.lower() != ".csv":
        raise DataLoadError(f"Expected a .csv file, got '{path.suffix or 'no extension'}': {path}")

    size = path.stat().st_size
    if size == 0:
        raise DataLoadError(f"File is empty: {path}")
    return size


def _read_sample(path: Path) -> bytes:
    """Read the first `SAMPLE_SIZE_BYTES` bytes of the file."""
    try:
        with path.open("rb") as f:
            return f.read(SAMPLE_SIZE_BYTES)
    except OSError as exc:  # permissions, file locked by another program, etc.
        raise DataLoadError(f"Could not read file {path}: {exc}") from exc


def _detect_encoding(sample: bytes) -> str:
    """Guess the file encoding from a byte sample.

    UTF-16 is recognised by its byte-order mark. Otherwise the sample is tried as
    UTF-8 (with or without BOM); if that fails, Latin-1 is used, which can decode
    any byte sequence. Binary files are rejected here: NUL bytes do not occur in
    UTF-8 or Latin-1 text.
    """
    if sample.startswith(_UTF16_BOMS):
        return "utf-16"

    if b"\x00" in sample:
        raise DataLoadError(
            "File looks binary (contains NUL bytes). It may be an Excel or other "
            "non-text file renamed to .csv."
        )

    try:
        # final=False: a multi-byte character cut off at the end of the sample is
        # not an error, only genuinely invalid bytes are.
        codecs.getincrementaldecoder("utf-8-sig")().decode(sample, final=False)
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "latin-1"


def _decode_sample(sample: bytes, encoding: str) -> str:
    """Decode the byte sample, ignoring a character cut off at the end."""
    return codecs.getincrementaldecoder(encoding)().decode(sample, final=False)


def _detect_delimiter(text_sample: str) -> str:
    """Detect the field separator, defaulting to a comma.

    Sniffer fails on single-column files (there is no delimiter to find); a comma
    is the right default there.
    """
    # Only sniff complete lines so a line cut off at the end of the sample does
    # not confuse the field counts.
    lines = text_sample.splitlines()
    if len(lines) > 1:
        lines = lines[:-1]
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines), delimiters=CANDIDATE_DELIMITERS)
        return dialect.delimiter
    except csv.Error:
        return ","


def _check_header(text_sample: str, delimiter: str) -> list[str]:
    """Return warnings about blank or duplicate column names in the raw header.

    pandas silently renames these (``"Unnamed: 2"``, ``"id.1"``), so we inspect the
    header as written in the file.
    """
    try:
        header = next(csv.reader(text_sample.splitlines(), delimiter=delimiter))
    except (StopIteration, csv.Error):
        return []

    warnings = []
    names = [name.strip() for name in header]

    blank_positions = [i + 1 for i, name in enumerate(names) if not name]
    if blank_positions:
        warnings.append(
            f"Blank column name(s) at position(s) {blank_positions}; "
            "they were renamed to 'Unnamed: N'."
        )

    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name and name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        warnings.append(
            f"Duplicate column name(s) {duplicates}; "
            "later copies were renamed with a '.1', '.2' suffix."
        )
    return warnings


def _read_with_fallback(
    path: Path, delimiter: str, encoding: str, warnings: list[str]
) -> tuple[pd.DataFrame, list[list[str]], str]:
    """Read the full file, retrying as Latin-1 if UTF-8 fails past the sample.

    Returns the DataFrame, the malformed rows that were skipped, and the encoding
    actually used. Appends a warning to `warnings` when falling back to Latin-1.
    """
    try:
        df, bad_rows = _read_csv(path, delimiter, encoding)
    except UnicodeDecodeError:
        # The sample was valid UTF-8 but an invalid byte appears later on.
        encoding = "latin-1"
        df, bad_rows = _read_csv(path, delimiter, encoding)

    if encoding == "latin-1":
        warnings.append(
            "File is not valid UTF-8; it was read as Latin-1. Accented or special "
            "characters may display incorrectly."
        )
    # Report UTF-8 with or without BOM simply as "utf-8".
    return df, bad_rows, "utf-8" if encoding == "utf-8-sig" else encoding


def _read_csv(
    path: Path, delimiter: str, encoding: str
) -> tuple[pd.DataFrame, list[list[str]]]:
    """Read the file with pandas, collecting malformed rows instead of failing.

    The python engine is required for the `on_bad_lines` callback; it is slower
    than the C engine but lets us count and report bad rows.
    """
    bad_rows: list[list[str]] = []

    def collect_bad_row(fields: list[str]) -> None:
        bad_rows.append(fields)
        return None  # returning None tells pandas to skip the row

    try:
        df = pd.read_csv(
            path,
            sep=delimiter,
            encoding=encoding,
            dtype=str,
            keep_default_na=False,  # keep "NA", "null", "" as written
            engine="python",
            on_bad_lines=collect_bad_row,
        )
    except UnicodeDecodeError:
        raise  # handled by _read_with_fallback
    except pd.errors.EmptyDataError as exc:
        raise DataLoadError(f"File has no columns or data: {path}") from exc
    except (pd.errors.ParserError, csv.Error, ValueError) as exc:
        raise DataLoadError(f"Could not parse {path} as CSV: {exc}") from exc
    except OSError as exc:
        raise DataLoadError(f"Could not read file {path}: {exc}") from exc

    return df, bad_rows
