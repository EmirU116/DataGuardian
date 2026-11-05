"""Safe CSV loading for Data Quality Guardian.

How it works
------------
`load_csv()` is the single entry point for reading a dataset. It:

1. Validates the path: the file exists, is a regular file, ends in `.csv` and is
   not empty.
2. Reads a sample from the start of the file to:
   - detect the encoding (UTF-16 by its BOM, else UTF-8, else Latin-1);
   - refuse binary files (NUL bytes in a non-UTF-16 file).
   Then it finds the header line, skipping blank lines before it (even more
   than one sample's worth), and from the text starting at the header:
   - detects the delimiter (`,` `;` tab `|`) with `csv.Sniffer`;
   - inspects the raw header for duplicate or blank column names.
3. Reads the whole file with pandas, keeping **every value as raw text**
   (`dtype=str`, `keep_default_na=False`). Nothing is converted to numbers, dates
   or NaN, so the checks can see exactly what is in the file: `"NA"`, `""`, `" 12 "`
   and `"abc"` all survive as written.
4. Counts malformed rows (more fields than the header) and skips them instead of
   crashing. Rows with *fewer* fields are kept; their missing fields become NaN,
   which the missing-values check reports.
5. Handles blank lines explicitly instead of letting pandas drop them silently:
   - blank lines before the header are skipped;
   - in a file with several columns, an empty or whitespace-only line is not a
     record, so it is dropped;
   - in a single-column file, a blank line between values *is* a value (an empty
     one), so it is kept as ``""``; blank lines at the very end are dropped.
   Every dropped blank line is counted in `LoadResult.blank_lines`, so each line
   of the file is accounted for: rows loaded + `skipped_rows` + `blank_lines`.

Files that cannot be analyzed raise `DataLoadError` with a readable message.
Problems that still allow analysis (Latin-1 fallback, skipped rows, blank lines,
duplicate column names, large file) are returned as warnings in
`LoadResult.warnings`. The original file is only ever read, never modified.
"""

from __future__ import annotations

import codecs
import csv
import io
import re
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

# The UTF-8 byte-order mark as it looks when decoded as Latin-1.
_UTF8_BOM_AS_LATIN1 = codecs.BOM_UTF8.decode("latin-1")


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
        blank_lines: Number of blank lines that were not loaded as rows (before the
            header, between records of a multi-column file, or at the end of a
            single-column file). Blank lines kept as empty values are not counted.
        warnings: Human-readable notes on problems that did not stop loading.
    """

    df: pd.DataFrame
    path: Path
    encoding: str
    delimiter: str
    file_size_bytes: int
    skipped_rows: int = 0
    blank_lines: int = 0
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
        DataLoadError: The file is missing, not a CSV, empty, binary, a truncated
            UTF-16 file, has a header but no data rows, has only rows with more
            fields than the header, or cannot be parsed.
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

    # Blank lines before the header would otherwise be read as the header itself.
    # header_text starts at the header, even if it lies beyond the first sample.
    leading_blank, header_text = _read_header_text(path, encoding)

    delimiter, delimiter_warning = _detect_delimiter(header_text)
    if delimiter_warning:
        warnings.append(delimiter_warning)
    warnings.extend(_check_header(header_text, delimiter))

    df, bad_rows, encoding = _read_with_fallback(
        path, delimiter, encoding, warnings, skiprows=leading_blank
    )
    df, dropped_blank, kept_blank = _handle_blank_lines(df)

    if df.empty and bad_rows:
        # Every data row was malformed. The usual causes are a wrong delimiter or
        # a trailing delimiter at the end of each row ("1,2,").
        raise DataLoadError(
            f"All {len(bad_rows)} data row(s) have more fields than the header "
            f"({len(df.columns)} column(s)), e.g. {bad_rows[0]}. Check the delimiter, "
            f"or whether every row ends with an extra '{delimiter}': {path}"
        )
    if df.empty:
        raise DataLoadError(f"File has a header but no data rows: {path}")

    if leading_blank:
        warnings.append(f"Ignored {leading_blank} blank line(s) before the header.")
    if dropped_blank:
        where = "at the end of the file" if len(df.columns) == 1 else "between rows"
        warnings.append(
            f"Ignored {dropped_blank} blank line(s) {where}; they are not data rows."
        )
    if kept_blank:
        warnings.append(
            f"Kept {kept_blank} blank line(s) as empty values: in a single-column "
            "file a blank line is a missing value."
        )

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
        blank_lines=leading_blank + dropped_blank,
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


def _read_header_text(path: Path, encoding: str) -> tuple[int, str]:
    """Find the header line and return (blank lines before it, text from it on).

    The file is decoded chunk by chunk until a non-whitespace character appears,
    then read on until the whole header line is in and `SAMPLE_SIZE_BYTES`
    characters from the start of the header are available (or the file ends).
    So a file that starts with more than one
    sample's worth of blank lines still loads, and the delimiter is sniffed from
    complete lines starting at the header, not from a header cut off at the end
    of the sample.

    Decoding uses ``errors="replace"``: this text is only used to sniff the
    delimiter and inspect the header. The full read in `_read_with_fallback`
    decides the real encoding.

    Raises:
        DataLoadError: The file contains only whitespace, or cannot be read.
    """
    decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
    text = ""
    header_offset: int | None = None
    header_line_complete = False
    in_quotes = False  # inside a quoted header field at the end of the text so far
    leading_blank = 0
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(SAMPLE_SIZE_BYTES)
                piece = decoder.decode(chunk, final=not chunk)
                if not text and encoding == "latin-1" and piece.startswith(_UTF8_BOM_AS_LATIN1):
                    # A UTF-8 BOM decoded as Latin-1 is "ï»¿", which would make a
                    # blank first line look like the header. Removing it changes
                    # no line count, so `skiprows` still matches pandas.
                    piece = piece[len(_UTF8_BOM_AS_LATIN1):]
                text += piece
                # Only the new piece needs checking, which keeps this linear.
                if header_offset is None and piece.strip():
                    leading_blank, header_offset = _count_leading_blank_lines(text)
                    header_line_complete, in_quotes = _scan_header_end(text, header_offset, False)
                elif header_offset is not None and not header_line_complete:
                    header_line_complete, in_quotes = _scan_header_end(piece, 0, in_quotes)
                if not chunk:
                    break
                # Stop once the whole header line is in, plus a sample's worth of
                # text, so a very wide header is never cut off mid-way.
                if (
                    header_line_complete
                    and len(text) - header_offset >= SAMPLE_SIZE_BYTES
                ):
                    break
    except OSError as exc:
        raise DataLoadError(f"Could not read file {path}: {exc}") from exc

    if header_offset is None:
        raise DataLoadError(f"File contains only whitespace: {path}")
    return leading_blank, text[header_offset:]


# A double quote, or a line break: what decides where a CSV record ends.
_QUOTE_OR_BREAK = re.compile(r'["\r\n]')


def _scan_header_end(text: str, start: int, in_quotes: bool) -> tuple[bool, bool]:
    """Look for the end of the header record in `text` from `start` on.

    The header ends at the first line break *outside* double quotes; a line
    break inside a quoted name is part of the name. Every ``"`` toggles the
    quoted state (an escaped ``""`` toggles twice, so it cancels out).

    Args:
        text: The text to scan.
        start: Where to start scanning.
        in_quotes: Whether the scan starts inside a quoted field (carried over
            from the previous piece of the file).

    Returns:
        (whether the header record is complete, the quoted state at the end).
    """
    for match in _QUOTE_OR_BREAK.finditer(text, start):
        if match.group() == '"':
            in_quotes = not in_quotes
        elif not in_quotes:
            return True, in_quotes
    return False, in_quotes


# One line and its terminator. pandas' python engine ends a line at "\r\n", a
# lone "\r" or "\n", so the blank-line count must use the same rule to agree
# with `skiprows`.
_LINE_PATTERN = re.compile(r"([^\r\n]*)(\r\n|\r|\n)")


def _count_leading_blank_lines(text: str) -> tuple[int, int]:
    """Count empty or whitespace-only lines at the start of `text`.

    Returns the number of such lines and the character offset where the first
    non-blank line starts.
    """
    count = 0
    offset = 0
    while True:
        # match() is anchored at `offset`; finditer() would search forward from
        # every position, which is quadratic on a long line with no line break.
        match = _LINE_PATTERN.match(text, offset)
        if match is None or match.group(1).strip():
            break
        count += 1
        offset = match.end()
    return count, offset


def _handle_blank_lines(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Drop or keep the rows pandas created from blank lines.

    The file is read with ``skip_blank_lines=False``, so a blank line becomes a
    row whose fields are all missing (NaN). A real empty field is ``""`` (because
    of ``keep_default_na=False``), so NaN-only rows can only come from blank lines.

    - Several columns: a row is a blank line when every field is missing, or when
      only the first field is present and it is whitespace (a whitespace-only
      line). Such rows are dropped.
    - One column: blank rows at the end of the file are dropped; blank rows
      between values are kept and filled with ``""``, since the value is empty.
      Whitespace-only values (``"   "``) are real text and are left untouched.

    Known limit: in a multi-column file, a line holding only a quoted empty or
    whitespace value (``""`` or ``"  "``) parses exactly like a whitespace-only
    line, so it is dropped and counted as a blank line too.

    Returns:
        The cleaned DataFrame (with a fresh index), the number of dropped blank
        lines, and the number of blank lines kept as empty values.
    """
    if df.empty:
        return df, 0, 0

    if len(df.columns) == 1:
        column = df.columns[0]
        is_blank = df[column].isna().tolist()

        # Blank lines after the last value are formatting, not values.
        trailing = 0
        for blank in reversed(is_blank):
            if not blank:
                break
            trailing += 1
        if trailing:
            df = df.iloc[: len(df) - trailing]

        kept = int(df[column].isna().sum())
        if kept:
            df = df.assign(**{column: df[column].fillna("")})
        return df.reset_index(drop=True), trailing, kept

    first = df.iloc[:, 0]
    rest_missing = df.iloc[:, 1:].isna().all(axis=1)
    first_blank = first.fillna("").str.strip().eq("")
    is_blank_line = rest_missing & first_blank

    dropped = int(is_blank_line.sum())
    if dropped:
        df = df[~is_blank_line].reset_index(drop=True)
    return df, dropped, 0


def _detect_delimiter(text_sample: str) -> tuple[str, str | None]:
    """Detect the field separator.

    `csv.Sniffer` is tried first. It fails when lines don't all have the same
    number of fields (a short row, an extra field, a blank line), and on
    single-column files. Then the header record decides: the candidate that
    splits it into the most fields wins, and a warning says the delimiter was
    guessed. If no candidate splits the header, the file has one column and the
    comma is used, with no warning.

    Returns:
        The delimiter, and a warning message if it was guessed (else None).
    """
    # Only sniff complete lines so a line cut off at the end of the sample does
    # not confuse the field counts.
    lines = text_sample.splitlines()
    if len(lines) > 1:
        lines = lines[:-1]
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines), delimiters=CANDIDATE_DELIMITERS)
        return dialect.delimiter, None
    except csv.Error:
        pass

    best, best_count = ",", 1
    for candidate in CANDIDATE_DELIMITERS:
        try:
            # csv.reader reads one full record, so quoted delimiters and quoted
            # line breaks in the header are handled.
            fields = next(csv.reader(io.StringIO(text_sample, newline=""), delimiter=candidate))
        except (StopIteration, csv.Error):
            continue
        if len(fields) > best_count:
            best, best_count = candidate, len(fields)

    if best_count == 1:
        return ",", None  # one column: there is no delimiter to find
    return best, (
        f"Could not detect the delimiter from the data (rows have different numbers "
        f"of fields); guessed {best!r} because it splits the header into "
        f"{best_count} columns."
    )


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
    path: Path, delimiter: str, encoding: str, warnings: list[str], *, skiprows: int = 0
) -> tuple[pd.DataFrame, list[list[str]], str]:
    """Read the full file, retrying as Latin-1 if UTF-8 fails past the sample.

    `skiprows` is the number of blank lines before the header. Returns the
    DataFrame, the malformed rows that were skipped, and the encoding actually
    used. Appends a warning to `warnings` when falling back to Latin-1.
    """
    try:
        df, bad_rows = _read_csv(path, delimiter, encoding, skiprows)
    except UnicodeDecodeError as exc:
        if encoding == "utf-16":
            # Latin-1 would "succeed" on UTF-16 bytes but produce garbage.
            raise DataLoadError(
                f"File looks like UTF-16 but could not be decoded; it may be "
                f"truncated or corrupt: {path}"
            ) from exc
        # The sample was valid UTF-8 but an invalid byte appears later on.
        encoding = "latin-1"
        df, bad_rows = _read_csv(path, delimiter, encoding, skiprows)

    if encoding == "latin-1" and len(df.columns) and str(df.columns[0]).startswith(
        _UTF8_BOM_AS_LATIN1
    ):
        # A UTF-8 BOM read as Latin-1 turns into "ï»¿" at the start of the first
        # column name; remove it so the name is what the file says.
        df = df.rename(columns={df.columns[0]: str(df.columns[0])[len(_UTF8_BOM_AS_LATIN1):]})

    if encoding == "latin-1":
        warnings.append(
            "File is not valid UTF-8; it was read as Latin-1. Accented or special "
            "characters may display incorrectly."
        )
    # Report UTF-8 with or without BOM simply as "utf-8".
    return df, bad_rows, "utf-8" if encoding == "utf-8-sig" else encoding


def _read_csv(
    path: Path, delimiter: str, encoding: str, skiprows: int = 0
) -> tuple[pd.DataFrame, list[list[str]]]:
    """Read the file with pandas, collecting malformed rows instead of failing.

    The python engine is required for the `on_bad_lines` callback; it is slower
    than the C engine but lets us count and report bad rows. Blank lines are
    kept (``skip_blank_lines=False``) so `_handle_blank_lines` can count them
    instead of pandas dropping them silently.

    The file is read in two passes:

    1. The header only (``nrows=0``), to get the column names exactly as pandas
       names them (blank names become ``"Unnamed: N"``, duplicates get ``".1"``).
    2. Every line *without* a header row (``header=None``), header line included.
       The header line is then the first row, so it sets the number of columns
       and every longer row goes to `on_bad_lines`. With a normal header read,
       pandas would silently turn the first field into the row index when the
       data rows are one field longer than the header, and that data would be
       lost.
    """
    bad_rows: list[list[str]] = []

    def collect_bad_row(fields: list[str]) -> None:
        bad_rows.append(fields)
        return None  # returning None tells pandas to skip the row

    options = dict(
        sep=delimiter,
        encoding=encoding,
        dtype=str,
        keep_default_na=False,  # keep "NA", "null", "" as written
        skip_blank_lines=False,  # blank lines are counted, not silently dropped
        skiprows=skiprows,  # blank lines before the header
        engine="python",
    )
    try:
        # index_col=False: with skip_blank_lines=False, a blank line right after
        # the header otherwise makes pandas fail while guessing an index.
        names = pd.read_csv(path, nrows=0, index_col=False, **options).columns
        df = pd.read_csv(path, header=None, on_bad_lines=collect_bad_row, **options)
    except UnicodeDecodeError:
        raise  # handled by _read_with_fallback
    except pd.errors.EmptyDataError as exc:
        raise DataLoadError(f"File has no columns or data: {path}") from exc
    except (pd.errors.ParserError, csv.Error, ValueError) as exc:
        raise DataLoadError(f"Could not parse {path} as CSV: {exc}") from exc
    except OSError as exc:
        raise DataLoadError(f"Could not read file {path}: {exc}") from exc

    if df.shape[1] != len(names):
        # Both passes parse the same header line, so this should not happen.
        raise DataLoadError(
            f"Could not parse the header of {path}: found {len(names)} column "
            f"name(s) but {df.shape[1]} field(s) in the header line."
        )
    # Drop the header line (row 0) and use the names from the first pass.
    df = df.iloc[1:].reset_index(drop=True)
    df.columns = names
    return df, bad_rows
