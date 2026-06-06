"""Safe file-name and path helpers."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile


SAFE_FOLDER_RE = re.compile(r"^[\w\-]+$")
SAFE_STORAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_source_folder(folder: str, base: Path = Path("./RAG_Content")) -> Path:
    if not SAFE_FOLDER_RE.match(folder):
        raise HTTPException(400, "Недопустимое имя папки")
    src_dir = (base / folder).resolve()
    root = base.resolve()
    if root != src_dir and root not in src_dir.parents:
        raise HTTPException(400, "Недопустимый путь")
    if not src_dir.exists() or not src_dir.is_dir():
        raise HTTPException(404, "Folder not found")
    return src_dir


def safe_upload_name(filename: str, allowed_suffixes: set[str] | None = None) -> str:
    name = Path(filename or "upload.bin").name
    if name in ("", ".", ".."):
        raise HTTPException(400, "Недопустимое имя файла")
    suffix = Path(name).suffix.lower()
    if allowed_suffixes is not None and suffix not in allowed_suffixes:
        raise HTTPException(400, f"Недопустимый тип файла: {suffix or 'без расширения'}")
    return name


def safe_dataset_storage_dir(dataset_id: str, base: Path = Path("./storage/datasets")) -> Path:
    if not dataset_id or not SAFE_STORAGE_ID_RE.match(dataset_id) or dataset_id in {".", ".."}:
        raise HTTPException(400, "Недопустимый dataset_id")
    ds_dir = (base / dataset_id).resolve()
    root = base.resolve()
    if root != ds_dir and root not in ds_dir.parents:
        raise HTTPException(400, "Недопустимый путь датасета")
    return ds_dir


async def save_upload_tmp(
    file: UploadFile,
    tmp_dir: Path = Path("/tmp/les_uploads"),
    allowed_suffixes: set[str] | None = None,
    max_bytes: int | None = None,
) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    name = safe_upload_name(file.filename or "upload.bin", allowed_suffixes)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}_{name}"
    written = 0
    try:
        with tmp_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if max_bytes is not None and written > max_bytes:
                    raise HTTPException(413, "Файл слишком большой")
                out.write(chunk)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path
