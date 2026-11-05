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
