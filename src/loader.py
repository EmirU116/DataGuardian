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
   - detects the delimiter (`,` `;` tab `|`) with `csv.Sniffer`, or, when the
     rows are irregular, by testing each candidate on the header and the first
     data rows (with a warning that it was guessed);
   - inspects the raw header for duplicate or blank column names.
3. Reads the whole file with pandas, keeping **every value as raw text**
   (`dtype=str`, `keep_default_na=False`). Nothing is converted to numbers, dates
   or NaN, so the checks can see exactly what is in the file: `"NA"`, `""`, `" 12 "`
   and `"abc"` all survive as written.
4. Counts malformed rows (more fields than the header, or broken quoting that
   pandas can't read) and skips them instead of crashing. Rows with *fewer* fields are kept; their missing fields become NaN,
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
import itertools
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# How many bytes to read from the start of the file for sniffing.
SAMPLE_SIZE_BYTES = 64 * 1024

# Upper limit on the text read while looking for the end of the header line.
# A stray quote in an unquoted name (e.g. `5" screen`) can make a header look
# unfinished; the limit stops that from pulling the whole file into memory.
MAX_HEADER_SEARCH_CHARS = 1024 * 1024

# How many data rows the delimiter fallback looks at.
DELIMITER_CHECK_ROWS = 200

# The csv module refuses fields over 128 KiB by default. Real files can have
# longer values, and an unclosed quote swallows everything after it; both must
# be read (and reported) rather than fail or be dropped. 2**31 - 1 is the
# largest limit every platform accepts.
MAX_CSV_FIELD_SIZE = 2**31 - 1

# When two delimiters fit the header and the data equally well, prefer the one
# least likely to appear inside values: commas are common in text and decimal
# numbers ("2,5"), so the comma comes last.
TIE_PREFERENCE = "\t;|,"

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
        skipped_rows: Number of malformed rows that were skipped: rows with more
            fields than the header, and rows with broken quoting.
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
    leading_blank, header_text, whole_file = _read_header_text(path, encoding)

    delimiter, delimiter_warning = _detect_delimiter(header_text, complete=whole_file)
    if delimiter_warning:
        warnings.append(delimiter_warning)
    warnings.extend(_check_header(header_text, delimiter))

    df, bad_rows, encoding = _read_with_fallback(
        path, delimiter, encoding, warnings, skiprows=leading_blank
    )
    # pandas silently stops at, or skips, a record with broken quoting ('"a"b,c'),
    # or merges the lines after an unclosed quote. Check the quoting and count
    # the records independently, so no row disappears without a trace.
    unread, quoting_problem, verified = _check_quoting(
        path, delimiter, encoding, skiprows=leading_blank, rows_read=len(df) + len(bad_rows)
    )
    df, dropped_blank, kept_blank = _handle_blank_lines(df)

    if df.empty and bad_rows and not unread:
        # Every data row was malformed. The usual causes are a wrong delimiter or
        # a trailing delimiter at the end of each row ("1,2,").
        raise DataLoadError(
            f"All {len(bad_rows)} data row(s) have more fields than the header "
            f"({len(df.columns)} column(s)), e.g. {bad_rows[0]}. Check the delimiter, "
            f"or whether every row ends with an extra '{delimiter}': {path}"
        )
    if df.empty and unread:
        raise DataLoadError(
            f"No data row could be read: {unread} row(s) have broken quoting "
            f"({quoting_problem}): {path}"
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
    if unread:
        warnings.append(
            f"Skipped {unread} row(s) with broken quoting that could not be read "
            f"({quoting_problem}). Check the quotes there."
        )
    elif quoting_problem:
        warnings.append(
            f"Broken quoting at {quoting_problem}. No row was lost, but the values "
            f"there may be merged into one field or cut. Check the quotes there."
        )
    if not verified:
        warnings.append(
            "The row count could not be double-checked (the file could not be "
            "re-read as CSV); rows with broken quoting may be missing."
        )

    return LoadResult(
        df=df,
        path=path,
        encoding=encoding,
        delimiter=delimiter,
        file_size_bytes=file_size,
        skipped_rows=len(bad_rows) + unread,
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


def _read_header_text(path: Path, encoding: str) -> tuple[int, str, bool]:
    """Find the header line and return (blank lines before it, text from it on,
    whether that text runs to the end of the file).

    The file is decoded chunk by chunk until a non-whitespace character appears,
    then read on until the whole header line is in and `SAMPLE_SIZE_BYTES`
    characters from the start of the header are available (or the file ends).
    So a file that starts with more than one
    sample's worth of blank lines still loads, and the delimiter is sniffed from
    complete lines starting at the header, not from a header cut off at the end
    of the sample.

    One limit: if the header still looks like it is inside a quoted name after
    `MAX_HEADER_SEARCH_CHARS` characters (usually a stray quote in an unquoted
    name, like ``5" screen``), the search stops there instead of reading the
    whole file. An unquoted header is always read to its end, however wide.

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
    whole_file = False
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
                    whole_file = True
                    break
                # Stop once the whole header line is in, plus a sample's worth of
                # text, so a very wide header is never cut off mid-way.
                if (
                    header_line_complete
                    and len(text) - header_offset >= SAMPLE_SIZE_BYTES
                ):
                    break
                if (
                    in_quotes
                    and header_offset is not None
                    and len(text) - header_offset >= MAX_HEADER_SEARCH_CHARS
                ):
                    break  # an "open quote" this long is a stray quote: stop searching
    except OSError as exc:
        raise DataLoadError(f"Could not read file {path}: {exc}") from exc

    if header_offset is None:
        raise DataLoadError(f"File contains only whitespace: {path}")
    return leading_blank, text[header_offset:], whole_file


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


def _detect_delimiter(text_sample: str, *, complete: bool = False) -> tuple[str, str | None]:
    """Detect the field separator.

    `csv.Sniffer` is tried first. It fails when lines don't all have the same
    number of fields (a short row, an extra field, a blank line), and on
    single-column files. Then each candidate is tested on the header record and
    the first data rows (`_score_delimiter`):

    - a candidate counts only if it splits the header into several fields *and*
      the data agrees: it splits at least half of the data rows, or at least a
      fifth of the rows have exactly the header's field count. So a
      single-column file whose header happens to contain ``;`` (``price;eur``)
      stays one column, while a ``;`` file with many short rows is still found;
    - among those, the one whose rows most often have the header's field count
      wins (ties: more header fields, then the order of `CANDIDATE_DELIMITERS`).

    If no candidate qualifies, the file is read as one column with the comma.
    That comes with a warning when the header contains a candidate character
    (the file might really have several columns); a guessed delimiter always
    comes with a warning.

    Args:
        text_sample: Text starting at the header line.
        complete: True if `text_sample` runs to the end of the file. Then its
            last line is complete and is used too; otherwise it may be cut off
            and is ignored.

    Returns:
        The delimiter, and a warning message if it was guessed (else None).
    """
    # Only sniff complete lines so a line cut off at the end of the sample does
    # not confuse the field counts.
    lines = text_sample.splitlines()
    if len(lines) > 1 and not complete:
        lines = lines[:-1]
    try:
        sniffed = csv.Sniffer().sniff("\n".join(lines), delimiters=CANDIDATE_DELIMITERS).delimiter
    except csv.Error:
        sniffed = None
    if sniffed is not None:
        return _break_delimiter_tie(text_sample, sniffed, complete=complete)

    best: tuple[float, int, int] | None = None  # (match share, header fields, -order)
    best_delimiter = ","
    in_header: list[str] = []  # candidates that split the header, accepted or not
    for order, candidate in enumerate(CANDIDATE_DELIMITERS):
        score = _score_delimiter(text_sample, candidate, complete=complete)
        if _splits_header(text_sample, candidate):
            in_header.append(candidate)
        if score is None:
            continue
        key = (score[0], score[1], -order)
        if best is None or key > best:
            best, best_delimiter = key, candidate

    if best is None:
        if not in_header:
            return ",", None  # one column: there is no delimiter to find
        return ",", (
            f"The header contains {', '.join(repr(c) for c in in_header)} but the data "
            f"rows mostly don't, so the file was read as a single column. If it has "
            f"several columns, check the delimiter."
        )
    return best_delimiter, (
        f"Could not detect the delimiter from the data (rows have different numbers "
        f"of fields); guessed {best_delimiter!r}: it splits the header into "
        f"{best[1]} columns and {best[0]:.0%} of the first data rows match."
    )


def _break_delimiter_tie(
    text_sample: str, sniffed: str, *, complete: bool
) -> tuple[str, str | None]:
    """Check Sniffer's pick against the other candidates.

    Sniffer prefers the comma whenever both it and, say, ``;`` give every line
    the same number of fields, as in ``id;Preis, EUR`` with values like
    ``2,5``. If another candidate scores at least as well (`_score_delimiter`),
    the choice is ambiguous: the candidate least likely to occur inside values
    wins (`TIE_PREFERENCE`), with a warning.

    Returns:
        The delimiter, and a warning if the choice was ambiguous (else None).
    """
    own = _score_delimiter(text_sample, sniffed, complete=complete)
    if own is None:
        return sniffed, None
    tied = [sniffed] + [
        c
        for c in CANDIDATE_DELIMITERS
        if c != sniffed
        and (score := _score_delimiter(text_sample, c, complete=complete)) is not None
        and score >= own
    ]
    if len(tied) == 1:
        return sniffed, None
    choice = min(tied, key=TIE_PREFERENCE.index)
    return choice, (
        f"The delimiter is ambiguous: {', '.join(repr(c) for c in tied)} fit the "
        f"header and the data equally well. Used {choice!r}; check the columns."
    )


def _score_delimiter(
    text_sample: str, delimiter: str, *, complete: bool = False
) -> tuple[float, int] | None:
    """Score `delimiter` as the field separator of `text_sample`.

    Parses the header record and up to `DELIMITER_CHECK_ROWS` data records with
    `csv.reader` (so quoted delimiters and quoted line breaks are handled). Blank
    records are ignored. Unless `complete` (the text runs to the end of the
    file), the last record is dropped because the sample may cut it off.

    Returns:
        None if the delimiter doesn't split the header, or if it splits fewer than
        half of the data rows *and* fewer than a fifth of them have the header's
        field count. Otherwise (share of data rows whose field count
        equals the header's, number of header fields). With no data rows at all,
        the header alone decides.
    """
    reader = csv.reader(io.StringIO(text_sample, newline=""), delimiter=delimiter)
    records: list[list[str]] = []
    try:
        for record in reader:
            records.append(record)
            if len(records) > DELIMITER_CHECK_ROWS + 1:
                break
    except csv.Error:
        if not records:
            return None  # this delimiter can't even parse the header

    if not records or len(records[0]) < 2:
        return None
    header_fields = len(records[0])
    rows = records[1:]
    if len(rows) > 1 and not complete:
        rows = rows[:-1]  # possibly cut off by the end of the sample
    rows = [r for r in rows if r and not (len(r) == 1 and not r[0].strip())]
    if not rows:
        return 1.0, header_fields

    split = sum(1 for r in rows if len(r) > 1)
    matching = sum(1 for r in rows if len(r) == header_fields)
    if split * 2 < len(rows) and matching * 5 < len(rows):
        return None  # the data doesn't support this delimiter
    return matching / len(rows), header_fields


def _splits_header(text_sample: str, delimiter: str) -> bool:
    """Return True if `delimiter` splits the header record into several fields."""
    try:
        header = next(csv.reader(io.StringIO(text_sample, newline=""), delimiter=delimiter))
    except (StopIteration, csv.Error):
        return False
    return len(header) > 1


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


@contextmanager
def _large_csv_fields() -> Iterator[None]:
    """Lift the csv module's field-size limit for the duration of a read.

    The limit is global state in the csv module (pandas' python engine uses it
    too), so the previous value is always restored, even after an error.
    """
    previous = csv.field_size_limit()
    csv.field_size_limit(MAX_CSV_FIELD_SIZE)
    try:
        yield
    finally:
        csv.field_size_limit(previous)


def _csv_lines(path: Path, encoding: str) -> Iterator[str]:
    """Yield the file's lines as `csv.reader` expects them (``newline=""``).

    UTF-8 is opened as ``utf-8-sig`` so a BOM is dropped, as pandas does. For
    Latin-1, a UTF-8 BOM decoded as ``"ï»¿"`` is removed from the first line,
    otherwise it would hide a quote at the start of the first header name.
    """
    if encoding == "utf-8":
        encoding = "utf-8-sig"
    with path.open("r", encoding=encoding, newline="") as f:
        first = next(f, "")
        if encoding == "latin-1" and first.startswith(_UTF8_BOM_AS_LATIN1):
            first = first[len(_UTF8_BOM_AS_LATIN1):]
        yield from itertools.chain([first], f)


def _check_quoting(
    path: Path, delimiter: str, encoding: str, *, skiprows: int, rows_read: int
) -> tuple[int, str | None, bool]:
    """Find broken quoting, and data records pandas silently failed to read.

    pandas' python engine drops a record with broken quoting (``"a"b,c``)
    without calling `on_bad_lines` when it is the last one, and an unclosed
    quote swallows every line after it. Two extra passes with `csv.reader`
    catch both:

    1. A lenient pass counts the records; fewer rows from pandas (plus its
       malformed rows, header excluded) means records were lost.
    2. A strict pass finds the first broken record and where it starts and
       ends, so the warning points at the right lines.

    Args:
        path: The CSV file.
        delimiter: The detected delimiter.
        encoding: The encoding pandas used, as reported by `_read_with_fallback`.
        skiprows: Blank lines before the header (one record each for csv).
        rows_read: Data rows pandas returned, including blank-line rows, plus
            the malformed rows it reported.

    Returns:
        (records pandas lost, a description of the first broken record such as
        "line 4: ',' expected after '\"'" or "lines 4-1004: unexpected end of
        data", or None, and whether the file could be re-checked at all).
    """
    try:
        with _large_csv_fields():
            total = sum(1 for _ in csv.reader(_csv_lines(path, encoding), delimiter=delimiter))
    except (OSError, UnicodeDecodeError, csv.Error):
        return 0, None, False

    problem: str | None = None
    start_line = 1  # first physical line of the record being read
    try:
        with _large_csv_fields():
            reader = csv.reader(_csv_lines(path, encoding), delimiter=delimiter, strict=True)
            for _ in reader:
                start_line = reader.line_num + 1
    except csv.Error as exc:
        end_line = max(reader.line_num, start_line)
        where = f"line {start_line}" if end_line == start_line else f"lines {start_line}-{end_line}"
        problem = f"{where}: {exc}"
    except (OSError, UnicodeDecodeError):
        pass

    unread = max(total - skiprows - 1 - rows_read, 0)
    if unread and problem is None:
        problem = "the broken line could not be located"
    return unread, problem, True


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
        with _large_csv_fields():  # long values must load, not fail or vanish
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
