"""Unit tests for proxy.services.native_open_service."""

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from proxy.services.native_open_service import _is_path_allowed, open_native_file


@pytest.fixture
def local_tmp_dir() -> Path:
    d = Path("data/tmp_test_native_open").resolve()
    d.mkdir(parents=True, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_native_open_allowed_path(local_tmp_dir: Path):
    sample_file = local_tmp_dir / "test_doc.pdf"
    sample_file.write_text("dummy content", encoding="utf-8")

    # Path inside local_tmp_dir is allowed relative to project root
    assert _is_path_allowed(sample_file.resolve()) is True


def test_native_open_nonexistent_file(local_tmp_dir: Path):
    missing_file = local_tmp_dir / "nonexistent.docx"
    res = open_native_file(missing_file)
    assert res["status"] == "not_found"
    assert res["returncode"] == -1


def test_native_open_mocked_launch(local_tmp_dir: Path):
    sample_file = local_tmp_dir / "test_sheet.xlsx"
    sample_file.write_text("data", encoding="utf-8")

    with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        res = open_native_file(sample_file)
        assert res["status"] == "opened"
        mock_run.assert_called_once()
        assert "open" in mock_run.call_args[0][0]


def test_native_open_win32_launch(local_tmp_dir: Path):
    sample_file = local_tmp_dir / "test_dwg.dwg"
    sample_file.write_text("dwg data", encoding="utf-8")

    with patch("sys.platform", "win32"), patch("os.startfile", create=True) as mock_startfile:
        res = open_native_file(sample_file)
        assert res["status"] == "opened"
        mock_startfile.assert_called_once_with(str(sample_file.resolve()))
