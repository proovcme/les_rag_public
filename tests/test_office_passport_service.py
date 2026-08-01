"""Unit tests for proxy.services.office_passport_service."""

import csv
import shutil
from pathlib import Path

import pytest
from proxy.services.office_passport_service import audit_office_document


@pytest.fixture
def local_tmp_dir() -> Path:
    d = Path("data/tmp_test_office_passport").resolve()
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_office_passport_csv(local_tmp_dir: Path):
    csv_file = local_tmp_dir / "test_data.csv"
    with csv_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Header1", "Header2", "Header3"])
        writer.writerow(["Val1", "Val2", "Val3"])
        writer.writerow(["Val4", "Val5", "Val6"])

    passport = audit_office_document(csv_file)
    assert passport["schema"] == "list.office_passport.v1"
    assert passport["passport_kind"] == "table"
    assert passport["structure"]["row_count"] == 3
    assert passport["structure"]["column_count"] == 3


def test_office_passport_text(local_tmp_dir: Path):
    txt_file = local_tmp_dir / "notes.txt"
    txt_file.write_text("Line 1\nLine 2\nLine 3\nLine 4", encoding="utf-8")

    passport = audit_office_document(txt_file)
    assert passport["passport_kind"] == "text"
    assert passport["structure"]["line_count"] == 4


def test_office_passport_nonexistent(local_tmp_dir: Path):
    with pytest.raises(FileNotFoundError):
        audit_office_document(local_tmp_dir / "missing.docx")
