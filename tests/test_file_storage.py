from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from proxy.storage.file_storage import (
    safe_dataset_storage_dir,
    safe_upload_name,
    save_upload_tmp,
    validate_source_folder,
)


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


def test_safe_upload_name_rejects_paths_and_suffixes():
    assert safe_upload_name("../report.pdf", {".pdf"}) == "report.pdf"

    with pytest.raises(HTTPException) as exc:
        safe_upload_name("report.exe", {".pdf"})
    assert exc.value.status_code == 400


def test_validate_source_folder_rejects_traversal(tmp_path):
    base = tmp_path / "RAG_Content"
    base.mkdir()

    with pytest.raises(HTTPException) as exc:
        validate_source_folder("../outside", base=base)
    assert exc.value.status_code == 400


def test_safe_dataset_storage_dir_rejects_traversal(tmp_path):
    base = tmp_path / "storage" / "datasets"
    base.mkdir(parents=True)

    assert safe_dataset_storage_dir("ds-1", base=base) == (base / "ds-1").resolve()

    with pytest.raises(HTTPException) as exc:
        safe_dataset_storage_dir("../outside", base=base)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_save_upload_tmp_streams_and_enforces_size(tmp_path):
    saved = await save_upload_tmp(
        _upload("note.txt", b"hello"),
        tmp_dir=tmp_path,
        allowed_suffixes={".txt"},
        max_bytes=10,
    )
    assert saved.read_bytes() == b"hello"

    with pytest.raises(HTTPException) as exc:
        await save_upload_tmp(
            _upload("big.txt", b"too large"),
            tmp_dir=tmp_path,
            allowed_suffixes={".txt"},
            max_bytes=3,
        )
    assert exc.value.status_code == 413
    assert not list(tmp_path.glob("*big.txt"))
