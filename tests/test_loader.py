"""Tests for src.loader.load_csv.

Each test writes a small CSV into pytest's temporary directory, so the exact
bytes on disk (encoding, delimiter, malformed rows) are controlled by the test.
"""

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
