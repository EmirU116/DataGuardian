"""Tests for src.loader.load_csv.

Each test writes a small CSV into pytest's temporary directory, so the exact
bytes on disk (encoding, delimiter, malformed rows) are controlled by the test.
"""

import os
import time
from pathlib import Path

import pandas as pd
import pytest

from src.loader import SAMPLE_SIZE_BYTES, DataLoadError, load_csv


def write(tmp_path: Path, content: str | bytes, name: str = "data.csv") -> Path:
    """Write `content` to a file in tmp_path and return its path."""
    path = tmp_path / name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8", newline="")
    else:
        path.write_bytes(content)
    return path


# --- Happy path -------------------------------------------------------------


def test_loads_simple_csv(tmp_path):
    result = load_csv(write(tmp_path, "id,name,price\n1,Coffee,2.5\n2,Tea,3\n"))

    assert list(result.df.columns) == ["id", "name", "price"]
    assert len(result.df) == 2
    assert result.delimiter == ","
    assert result.encoding == "utf-8"
    assert result.skipped_rows == 0
    assert result.warnings == []


def test_values_stay_raw_text(tmp_path):
    """Placeholders, blanks and padded numbers must not be converted."""
    path = write(tmp_path, "id,price,note\n1, 12 ,NA\n2,abc,\n3,null,N/A\n")
    df = load_csv(path).df

    assert df["id"].tolist() == ["1", "2", "3"]  # not converted to int
    assert df["price"].tolist() == [" 12 ", "abc", "null"]  # whitespace kept
    assert df["note"].tolist() == ["NA", "", "N/A"]  # not converted to NaN


def test_quoted_field_containing_delimiter(tmp_path):
    df = load_csv(write(tmp_path, 'id,name\n1,"Smith, John"\n')).df
    assert df["name"].tolist() == ["Smith, John"]


def test_single_column_file(tmp_path):
    result = load_csv(write(tmp_path, "name\nAlice\nBob\n"))
    assert list(result.df.columns) == ["name"]
    assert result.delimiter == ","


def test_single_row(tmp_path):
    assert len(load_csv(write(tmp_path, "a,b\n1,2\n")).df) == 1


def test_uppercase_extension_accepted(tmp_path):
    assert len(load_csv(write(tmp_path, "a\n1\n", name="DATA.CSV")).df) == 1


# --- Delimiters --------------------------------------------------------------


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_detects_delimiter(tmp_path, delimiter):
    content = f"id{delimiter}name{delimiter}price\n1{delimiter}Tea{delimiter}2,5\n"
    result = load_csv(write(tmp_path, content))

    assert result.delimiter == delimiter
    assert list(result.df.columns) == ["id", "name", "price"]
    assert result.df["price"].tolist() == ["2,5"]


# --- Encodings ---------------------------------------------------------------


def test_utf8_bom_is_stripped(tmp_path):
    result = load_csv(write(tmp_path, b"\xef\xbb\xbfid,name\n1,Caf\xc3\xa9\n"))

    assert list(result.df.columns) == ["id", "name"]  # no BOM in first name
    assert result.df["name"].tolist() == ["Café"]
    assert result.encoding == "utf-8"


def test_unicode_text(tmp_path):
    df = load_csv(write(tmp_path, "city\nZürich\n東京\nİstanbul\n")).df
    assert df["city"].tolist() == ["Zürich", "東京", "İstanbul"]


def test_latin1_fallback(tmp_path):
    result = load_csv(write(tmp_path, "id,name\n1,Café\n".encode("latin-1")))

    assert result.encoding == "latin-1"
    assert result.df["name"].tolist() == ["Café"]
    assert any("Latin-1" in w for w in result.warnings)


def test_latin1_byte_after_sample_falls_back(tmp_path):
    """The sample is valid UTF-8, but an invalid byte appears later on."""
    filler = "".join(f"{i},row\n" for i in range(SAMPLE_SIZE_BYTES // 5))
    content = ("id,name\n" + filler).encode("utf-8") + "999,Café\n".encode("latin-1")
    result = load_csv(write(tmp_path, content))

    assert result.encoding == "latin-1"
    assert result.df["name"].iloc[-1] == "Café"


def test_utf16_with_bom(tmp_path):
    result = load_csv(write(tmp_path, "id,name\n1,Café\n".encode("utf-16")))

    assert result.encoding == "utf-16"
    assert result.df["name"].tolist() == ["Café"]


# --- Malformed content -------------------------------------------------------


def test_row_with_too_many_fields_is_skipped_and_counted(tmp_path):
    result = load_csv(write(tmp_path, "a,b\n1,2\n3,4,5\n6,7\n"))

    assert result.df["a"].tolist() == ["1", "6"]
    assert result.skipped_rows == 1
    assert any("Skipped 1 malformed row" in w for w in result.warnings)


def test_row_with_too_few_fields_is_padded(tmp_path):
    df = load_csv(write(tmp_path, "a,b,c\n1,2,3\n4\n")).df

    assert len(df) == 2
    assert pd.isna(df["b"].iloc[1]) and pd.isna(df["c"].iloc[1])


def test_duplicate_column_names_warn(tmp_path):
    result = load_csv(write(tmp_path, "id,name,id\n1,a,2\n"))

    assert list(result.df.columns) == ["id", "name", "id.1"]
    assert any("Duplicate column name" in w and "'id'" in w for w in result.warnings)


def test_blank_column_name_warns(tmp_path):
    result = load_csv(write(tmp_path, "id,,name\n1,x,a\n"))

    assert any("Blank column name" in w and "[2]" in w for w in result.warnings)


def test_large_file_warns(tmp_path):
    result = load_csv(write(tmp_path, "a\n1\n"), size_warning_mb=0.000001)
    assert any("threshold" in w for w in result.warnings)


# --- Blank lines -------------------------------------------------------------
# Every line of a file must be accounted for:
# rows loaded + skipped_rows + blank_lines (+ blank lines kept as "" values).


def test_blank_line_between_rows_is_dropped_and_counted(tmp_path):
    result = load_csv(write(tmp_path, "a,b\n1,2\n\n3,4\n"))

    assert result.df["a"].tolist() == ["1", "3"]
    assert result.blank_lines == 1
    assert any("Ignored 1 blank line(s) between rows" in w for w in result.warnings)


def test_whitespace_only_line_in_multi_column_file_is_dropped(tmp_path):
    result = load_csv(write(tmp_path, "a,b\n1,2\n   \n3,4\n"))

    assert result.df["a"].tolist() == ["1", "3"]
    assert result.blank_lines == 1


def test_row_of_empty_fields_is_kept(tmp_path):
    """',' is a real record whose fields are empty, not a blank line."""
    result = load_csv(write(tmp_path, "a,b\n1,2\n,\n"))

    assert result.df.values.tolist() == [["1", "2"], ["", ""]]
    assert result.blank_lines == 0


def test_single_column_blank_line_is_kept_as_empty_value(tmp_path):
    result = load_csv(write(tmp_path, "name\nAlice\n\nBob\n"))

    assert result.df["name"].tolist() == ["Alice", "", "Bob"]
    assert result.blank_lines == 0
    assert any("Kept 1 blank line(s) as empty values" in w for w in result.warnings)


def test_single_column_whitespace_value_is_kept_as_written(tmp_path):
    df = load_csv(write(tmp_path, "name\nAlice\n   \nBob\n")).df
    assert df["name"].tolist() == ["Alice", "   ", "Bob"]


def test_single_column_trailing_blank_lines_are_dropped(tmp_path):
    result = load_csv(write(tmp_path, "name\nAlice\nBob\n\n\n"))

    assert result.df["name"].tolist() == ["Alice", "Bob"]
    assert result.blank_lines == 2
    assert any("at the end of the file" in w for w in result.warnings)


def test_blank_lines_before_header_are_skipped(tmp_path):
    result = load_csv(write(tmp_path, "\n\na,b\n1,2\n"))

    assert list(result.df.columns) == ["a", "b"]
    assert result.df.values.tolist() == [["1", "2"]]
    assert result.blank_lines == 2
    assert any("before the header" in w for w in result.warnings)


def test_header_check_still_works_after_leading_blank_lines(tmp_path):
    result = load_csv(write(tmp_path, "\nid,name,id\n1,a,2\n"))
    assert any("Duplicate column name" in w for w in result.warnings)


def test_blank_lines_with_windows_line_endings(tmp_path):
    result = load_csv(write(tmp_path, "\r\na,b\r\n1,2\r\n\r\n3,4\r\n"))

    assert result.df["b"].tolist() == ["2", "4"]
    assert result.blank_lines == 2


def test_blank_line_inside_quoted_field_is_part_of_the_value(tmp_path):
    result = load_csv(write(tmp_path, 'a,b\n1,"x\n\ny"\n2,z\n'))

    assert result.df["b"].tolist() == ["x\n\ny", "z"]
    assert result.blank_lines == 0


def test_only_blank_lines_after_header_means_no_data(tmp_path):
    with pytest.raises(DataLoadError, match="no data rows"):
        load_csv(write(tmp_path, "a,b\n\n\n"))


@pytest.mark.parametrize(
    "content",
    [
        "\r\ra,b\r1,2\r3,4\r",  # old Mac line endings (lone CR)
        "\r\r\na,b\n1,2\n3,4\n",  # mixed: CR, then CRLF
        "\n \ra,b\n1,2\n3,4\n",  # whitespace-only line ended by a lone CR
    ],
)
def test_leading_blank_lines_with_any_line_ending(tmp_path, content):
    result = load_csv(write(tmp_path, content))

    assert list(result.df.columns) == ["a", "b"]
    assert result.df["a"].tolist() == ["1", "3"]
    assert result.blank_lines == 2


def test_header_beyond_first_sample_is_found(tmp_path):
    """More than a whole sample of blank lines before the header still loads."""
    content = "\n" * (SAMPLE_SIZE_BYTES + 10) + "a;b\n1;2\n"
    result = load_csv(write(tmp_path, content))

    assert result.delimiter == ";"
    assert result.df.values.tolist() == [["1", "2"]]
    assert result.blank_lines == SAMPLE_SIZE_BYTES + 10


@pytest.mark.parametrize("blank_count", [SAMPLE_SIZE_BYTES - 3, SAMPLE_SIZE_BYTES - 1])
def test_header_cut_by_sample_boundary_still_sniffs_delimiter(tmp_path, blank_count):
    content = "\n" * blank_count + "name;age;city\nAl;30;X\nBo;40;Y\n"
    result = load_csv(write(tmp_path, content))

    assert result.delimiter == ";"
    assert list(result.df.columns) == ["name", "age", "city"]


@pytest.mark.parametrize(
    ("content", "encoding"),
    [
        ("﻿\n\na,b\n1,2\n\n3,4\n", "utf-8"),  # UTF-8 BOM, then blank lines
        ("\n\na,b\n1,2\n\n3,4\n", "utf-16-le-bom"),
        ("\n\na,b\n1,2\n\n3,4\n", "utf-16-be-bom"),
        ("\n\na,b\ncafé,2\n\nnaïve,4\n", "latin-1"),
    ],
)
def test_blank_lines_with_other_encodings(tmp_path, content, encoding):
    if encoding == "utf-16-le-bom":
        raw = b"\xff\xfe" + content.encode("utf-16-le")
    elif encoding == "utf-16-be-bom":
        raw = b"\xfe\xff" + content.encode("utf-16-be")
    else:
        raw = content.encode(encoding)
    result = load_csv(write(tmp_path, raw))

    assert list(result.df.columns) == ["a", "b"]
    assert len(result.df) == 2
    assert result.blank_lines == 3


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_blank_lines_with_other_delimiters(tmp_path, delimiter):
    d = delimiter
    result = load_csv(write(tmp_path, f"\na{d}b{d}c\n1{d}2{d}3\n\n4{d}5{d}6\n"))

    assert result.delimiter == delimiter
    assert result.df["c"].tolist() == ["3", "6"]
    assert result.blank_lines == 2


@pytest.mark.parametrize(
    ("content", "leading_blank", "data_lines"),
    [
        ("a,b\n1,2\n\n3,4,5\n6,7\n\n8,9,10\n", 0, 6),
        ("\n\na,b\r\n1,2\r\n\r\n   \r\n3\r\n", 2, 4),
        ("name\nAl\n\nBo\n,x\n\n\n", 0, 6),
        ("a,b,c\n1,2,3\n4\n\n5,6,7,8\n,,\n", 0, 5),
    ],
)
def test_every_line_is_accounted_for(tmp_path, content, leading_blank, data_lines):
    """Data lines after the header = rows loaded + skipped rows + dropped blank lines."""
    result = load_csv(write(tmp_path, content))

    after_header = result.blank_lines - leading_blank
    assert len(result.df) + result.skipped_rows + after_header == data_lines


# --- Extra fields in every row (implicit index) ---------------------------------
# When data rows have one field more than the header, pandas would normally use
# the first field as the row index, silently losing that column of data.


def test_extra_field_in_every_row_is_skipped_not_used_as_index(tmp_path):
    result = load_csv(write(tmp_path, "a,b\n1,2\n3,4,5\n6,7,8\n"))

    assert result.df.values.tolist() == [["1", "2"]]
    assert result.skipped_rows == 2
    assert list(result.df.index) == [0]


@pytest.mark.parametrize(
    "content",
    [
        "a,b\n1,2,3\n\n4,5,6\n",
        "a,b\n1,2,\n3,4,\n",  # common export bug: a trailing delimiter on every row
    ],
)
def test_all_rows_malformed_gives_a_clear_error(tmp_path, content):
    """Nothing valid is left; the error explains why instead of saying "no data"."""
    with pytest.raises(DataLoadError, match=r"All 2 data row\(s\) have more fields"):
        load_csv(write(tmp_path, content))


@pytest.mark.parametrize(
    "content",
    [
        "a,b\n\n1,2\n",
        "a,b\r\n\r\n1,2\r\n",
        "a,b,c\n\n1,2,3\n",
        "\n\na,b\n\n1,2\n",
        "id,id,\n\n1,2,3\n",
    ],
)
def test_blank_line_right_after_header(tmp_path, content):
    result = load_csv(write(tmp_path, content))

    assert len(result.df) == 1
    assert result.df.iloc[0, 0] == "1"


def test_single_column_blank_line_right_after_header_is_a_value(tmp_path):
    assert load_csv(write(tmp_path, "a\n\n1\n")).df["a"].tolist() == ["", "1"]


def test_utf8_bom_with_late_latin1_byte_gives_clean_column_name(tmp_path):
    """UTF-8 BOM, then an invalid UTF-8 byte after the sample: Latin-1 fallback."""
    rows = "".join(f"{i},x\n" for i in range(SAMPLE_SIZE_BYTES // 4))
    raw = b"\xef\xbb\xbfid,name\n" + rows.encode("ascii") + b"9,caf\xe9\n"
    result = load_csv(write(tmp_path, raw))

    assert result.encoding == "latin-1"
    assert list(result.df.columns) == ["id", "name"]
    assert result.df["name"].iloc[-1] == "café"


def test_very_wide_header_is_checked_completely(tmp_path):
    """A header longer than the sample: blank names at the end are still found,
    and no blank name is invented where the sample would have cut the header."""
    names = [f"column_{i}" for i in range(SAMPLE_SIZE_BYTES // 8)] + [""]
    header = ",".join(names)
    assert len(header) > SAMPLE_SIZE_BYTES
    result = load_csv(write(tmp_path, header + "\n" + ",".join("1" * len(names)) + "\n"))

    blank_warnings = [w for w in result.warnings if "Blank column name" in w]
    assert len(blank_warnings) == 1
    assert f"[{len(names)}]" in blank_warnings[0]


def test_single_column_header_with_two_field_rows(tmp_path):
    result = load_csv(write(tmp_path, "id\n1\n2,y\n3\n"))

    assert result.df["id"].tolist() == ["1", "3"]
    assert result.skipped_rows == 1


def test_no_warning_for_file_without_blank_lines(tmp_path):
    result = load_csv(write(tmp_path, "a,b\n1,2\n"))

    assert result.blank_lines == 0
    assert result.warnings == []


# --- Other edge cases --------------------------------------------------------


def test_leading_zeros_are_kept(tmp_path):
    df = load_csv(write(tmp_path, "code,zip\n007,01234\n")).df
    assert df.values.tolist() == [["007", "01234"]]


def test_header_without_trailing_newline_has_no_data(tmp_path):
    with pytest.raises(DataLoadError, match="no data rows"):
        load_csv(write(tmp_path, "id,name"))


def test_last_row_without_trailing_newline_is_loaded(tmp_path):
    assert load_csv(write(tmp_path, "a,b\n1,2\n3,4")).df["a"].tolist() == ["1", "3"]


def test_very_wide_file(tmp_path):
    header = ",".join(f"c{i}" for i in range(2000))
    row = ",".join(str(i) for i in range(2000))
    df = load_csv(write(tmp_path, f"{header}\n{row}\n")).df

    assert df.shape == (1, 2000)
    assert df["c1999"].tolist() == ["1999"]


# --- Delimiter guessed from the header ----------------------------------------


@pytest.mark.parametrize(
    ("content", "delimiter"),
    [
        ("id|name|age\n1|x|3\n2|y\n3|z|5\n", "|"),  # a short row
        ("a;b\n1;2\n3;4;5\n6;7\n", ";"),  # an extra field
        ("a\tb\tc\n1\t2\t3\n4\t5\n6\t7\t8\n", "\t"),  # a short row
    ],
)
def test_irregular_file_still_gets_the_right_delimiter(tmp_path, content, delimiter):
    """Sniffer fails on irregular lines; the header decides, with a warning."""
    result = load_csv(write(tmp_path, content))

    assert result.delimiter == delimiter
    assert len(result.df.columns) > 1
    assert any("guessed" in w for w in result.warnings)


def test_quoted_delimiter_in_header_does_not_count(tmp_path):
    result = load_csv(write(tmp_path, '"a;b",c\n1;2,3\n4,5,6\n'))
    assert result.delimiter == ","


def test_single_column_file_gets_no_delimiter_warning(tmp_path):
    result = load_csv(write(tmp_path, "name\nAl\n\nBo\n"))
    assert not any("guessed" in w for w in result.warnings)


@pytest.mark.parametrize("header", ["price;eur", "a|b", "size (cm);weight"])
def test_single_column_header_with_delimiter_character_stays_one_column(tmp_path, header):
    """The header alone must not decide: the data rows aren't split."""
    result = load_csv(write(tmp_path, f"{header}\n1\n2\n\n3\n"))

    assert list(result.df.columns) == [header]
    assert result.df[header].tolist() == ["1", "2", "", "3"]  # blank kept as a value
    assert not any("guessed" in w for w in result.warnings)


def test_comma_file_with_semicolons_in_header_names_stays_comma(tmp_path):
    result = load_csv(write(tmp_path, "a;b;c,d\n1,2\n3\n4,5\n6,7,8\n"))

    assert result.delimiter == ","
    assert list(result.df.columns) == ["a;b;c", "d"]


@pytest.mark.parametrize(
    "content",
    [
        "a;b;c\n1;2;3\n4\n5\n6;7;8\n9\n10\n",  # most rows short, 1 in 3 complete
        "".join(["id;name;email\n"] + [f"{i};x;y\n" if i % 3 == 0 else f"{i}\n" for i in range(300)]),
    ],
)
def test_semicolon_file_with_many_short_rows_is_still_found(tmp_path, content):
    result = load_csv(write(tmp_path, content))

    assert result.delimiter == ";"
    assert len(result.df.columns) == 3


def test_header_with_delimiter_but_unsplit_rows_warns(tmp_path):
    """Read as one column, but say so: the file might really have columns."""
    result = load_csv(write(tmp_path, "a;b;c\n1\n2\n"))

    assert list(result.df.columns) == ["a;b;c"]
    assert any("read as a single column" in w for w in result.warnings)


@pytest.mark.parametrize(
    "content",
    ["id;Preis, EUR\n1;2,5\n2;3,75\n3;1,25\n", "id;name;Preis, EUR\n1;a;2,5\n2;b;3,75\n"],
)
def test_semicolon_wins_tie_with_comma_and_warns(tmp_path, content):
    """Both delimiters give consistent field counts; ';' is preferred because
    commas are common inside values (decimal commas)."""
    result = load_csv(write(tmp_path, content))

    assert result.delimiter == ";"
    assert result.df["id"].tolist()[:2] == ["1", "2"]
    assert any("ambiguous" in w for w in result.warnings)


@pytest.mark.parametrize(
    ("content", "delimiter", "columns"),
    [
        ("price;eur\n1\n", ",", ["price;eur"]),  # one data row, one column
        ("a|b\nx\n", ",", ["a|b"]),
        ("x;y|z|w\n1|2|3\n", "|", ["x;y", "z", "w"]),  # one data row, real columns
        ('"price;eur"\n1\n2\n\n3\n', ",", ["price;eur"]),  # quoted single name
    ],
)
def test_delimiter_with_one_data_row(tmp_path, content, delimiter, columns):
    """The whole file fits in the sample, so the data row counts too."""
    result = load_csv(write(tmp_path, content))

    assert result.delimiter == delimiter
    assert list(result.df.columns) == columns


# --- Very long headers ---------------------------------------------------------


def test_long_header_with_quoted_line_break(tmp_path):
    """A line break inside a quoted name doesn't end the header early."""
    names = ['"multi\nline"'] + [f"c{i}" for i in range(11000)]
    header = ";".join(names)
    assert len(header) > SAMPLE_SIZE_BYTES
    row = ";".join("1" * len(names))
    result = load_csv(write(tmp_path, f"{header}\n{row}\n"))

    assert result.delimiter == ";"
    assert result.df.shape == (1, len(names))
    assert result.df.columns[0] == "multi\nline"


def test_long_header_without_line_break_is_fast(tmp_path):
    """Counting blank lines used to be quadratic on a long line (27 s)."""
    header = ",".join(f"c{i}" for i in range(20000))
    start = time.perf_counter()
    with pytest.raises(DataLoadError, match="no data rows"):
        load_csv(write(tmp_path, header))
    assert time.perf_counter() - start < 10


def test_stray_quote_in_header_does_not_read_whole_file(tmp_path):
    """A `"` inside an unquoted name looks like an open quote; the header search
    is capped instead of reading the whole file."""
    from src.loader import MAX_HEADER_SEARCH_CHARS, _read_header_text

    rows = "".join(f"{i},x,y\n" for i in range(200_000))  # about 2.6 MB
    path = write(tmp_path, 'size_in",c,d\n' + rows)
    _, header_text, _ = _read_header_text(path, "utf-8-sig")

    assert len(header_text) <= MAX_HEADER_SEARCH_CHARS + SAMPLE_SIZE_BYTES
    assert load_csv(path).delimiter == ","


def test_unquoted_header_longer_than_search_cap_is_still_checked(tmp_path, monkeypatch):
    """The cap only applies inside quotes; a plain wide header is read in full."""
    import src.loader as loader

    monkeypatch.setattr(loader, "MAX_HEADER_SEARCH_CHARS", 1000)
    names = [f"col{i:05d}" for i in range(1000)] + ["col00005", ""]
    content = ",".join(names) + "\n" + ",".join("1" * len(names)) + "\n"
    result = load_csv(write(tmp_path, content))

    assert any("Duplicate column name" in w and "col00005" in w for w in result.warnings)
    assert any("Blank column name" in w for w in result.warnings)


# --- Broken quoting ---------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        'c0,c1\n1,2\n3,4\n"a"b,c\n',  # last line: pandas stopped without a trace
        'c0,c1\n1,2\n3,4\n"open\n',  # an unclosed quote at the end of the file
    ],
)
def test_broken_quoting_on_last_line_is_counted(tmp_path, content):
    result = load_csv(write(tmp_path, content))

    assert result.df["c0"].tolist() == ["1", "3"]
    assert result.skipped_rows == 1
    assert any("broken quoting" in w and "line 4" in w for w in result.warnings)


def test_unclosed_quote_past_csv_field_limit_is_reported(tmp_path):
    """An unclosed quote that swallows more than csv's default 128 KiB limit
    used to lose thousands of rows silently."""
    good = "".join(f"{i},{i}\n" for i in range(10))
    after = "".join(f"{i},{'v' * 40}\n" for i in range(4000))  # about 180 KB
    result = load_csv(write(tmp_path, "a,b\n" + good + '"x,1\n' + after))

    assert result.df["a"].tolist() == [str(i) for i in range(10)]
    assert result.skipped_rows == 1
    assert any("broken quoting" in w and "lines 12-" in w for w in result.warnings)


def test_unclosed_quote_reports_where_it_starts(tmp_path):
    after = "".join(f"{i},{i}\n" for i in range(1000))
    result = load_csv(write(tmp_path, 'a,b\n1,1\n2,2\n"x,1\n' + after))

    assert any("lines 4-1004" in w for w in result.warnings)


def test_bom_file_with_quoted_line_break_in_first_name_is_not_broken(tmp_path):
    raw = '"a\nx",b\n1,2\n3,4\n'.encode("utf-8-sig")
    result = load_csv(write(tmp_path, raw))

    assert list(result.df.columns) == ["a\nx", "b"]
    assert result.skipped_rows == 0
    assert result.warnings == []


def test_value_longer_than_csv_field_limit_loads(tmp_path):
    import csv

    long_value = "x" * 200_000
    result = load_csv(write(tmp_path, f"a,b\n1,{long_value}\n2,y\n"))

    assert result.df["b"].tolist() == [long_value, "y"]
    assert csv.field_size_limit() == 131072  # the global limit is restored


def test_valid_quotes_are_not_reported_as_broken(tmp_path):
    result = load_csv(write(tmp_path, 'c0,c1\n1,a"b\n2,"x\n\ny"\n3,"say ""hi"""\n'))

    assert len(result.df) == 3
    assert result.skipped_rows == 0
    assert result.warnings == []


# --- More encoding edge cases ---------------------------------------------------


def test_bom_then_blank_lines_then_latin1_byte(tmp_path):
    raw = b"\xef\xbb\xbf\n\nname,city\nz,\xe9\n"
    result = load_csv(write(tmp_path, raw))

    assert result.encoding == "latin-1"
    assert list(result.df.columns) == ["name", "city"]
    assert result.df["city"].tolist() == ["é"]
    assert result.blank_lines == 2


def test_bom_far_before_header_then_latin1_byte(tmp_path):
    """The BOM is stripped even when the header is more than one chunk away."""
    raw = b"\xef\xbb\xbf" + b"\n" * (SAMPLE_SIZE_BYTES + 100) + b"name,city\nz,\xe9\n"
    result = load_csv(write(tmp_path, raw))

    assert list(result.df.columns) == ["name", "city"]
    assert result.df["city"].tolist() == ["é"]
    assert result.blank_lines == SAMPLE_SIZE_BYTES + 100


def test_truncated_utf16_file_is_rejected(tmp_path):
    raw = "a,b\n1,2\n".encode("utf-16") + b"\x00"
    with pytest.raises(DataLoadError, match="UTF-16"):
        load_csv(write(tmp_path, raw))


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="file permissions are not enforced for root or on this platform",
)
def test_unreadable_file(tmp_path):
    path = write(tmp_path, "a\n1\n")
    path.chmod(0)
    try:
        with pytest.raises(DataLoadError, match="Could not read"):
            load_csv(path)
    finally:
        path.chmod(0o600)


# --- Files that cannot be loaded ---------------------------------------------


def test_missing_file(tmp_path):
    with pytest.raises(DataLoadError, match="not found"):
        load_csv(tmp_path / "nope.csv")


def test_directory_instead_of_file(tmp_path):
    folder = tmp_path / "folder.csv"
    folder.mkdir()
    with pytest.raises(DataLoadError, match="Not a file"):
        load_csv(folder)


@pytest.mark.parametrize("name", ["data.txt", "data.xlsx", "data"])
def test_wrong_extension(tmp_path, name):
    with pytest.raises(DataLoadError, match="Expected a .csv file"):
        load_csv(write(tmp_path, "a\n1\n", name=name))


def test_empty_file(tmp_path):
    with pytest.raises(DataLoadError, match="empty"):
        load_csv(write(tmp_path, ""))


def test_whitespace_only_file(tmp_path):
    with pytest.raises(DataLoadError, match="whitespace"):
        load_csv(write(tmp_path, "  \n\n \n"))


def test_header_only(tmp_path):
    with pytest.raises(DataLoadError, match="no data rows"):
        load_csv(write(tmp_path, "id,name,price\n"))


def test_binary_file(tmp_path):
    with pytest.raises(DataLoadError, match="binary"):
        load_csv(write(tmp_path, b"PK\x03\x04\x00\x00\x00binary junk"))


def test_accepts_string_path(tmp_path):
    assert len(load_csv(str(write(tmp_path, "a\n1\n"))).df) == 1
