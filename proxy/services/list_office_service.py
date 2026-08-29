"""Л.И.С.Т. Студия — append-only реестр офисных документов.

Оригиналы и индексированные источники никогда не открываются на запись. Каждая
генерация создаёт новую ревизию в собственном каталоге и сопровождается
машиночитаемым manifest с полями, provenance и SHA-256 готового файла.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from backend.runtime_paths import mutable_path
from typing import Any

from proxy.services import forms_service


OFFICE_WORKSPACE_DIR = mutable_path("data/list_office")
ARTIFACT_SCHEMA = "list.office_artifact.v1"
_SAFE_ID = re.compile(r"^[a-f0-9]{32}$")


def _workspace_dir() -> Path:
    root = Path(os.getenv("LES_LIST_OFFICE_DIR", str(OFFICE_WORKSPACE_DIR)))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _documents_dir() -> Path:
    root = _workspace_dir() / "documents"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_id(value: str | None, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"Некорректный {label}")
    return normalized


def _clean_source_refs(source_refs: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in source_refs or []:
        if not isinstance(raw, dict):
            continue
        item = {
            "dataset_id": str(raw.get("dataset_id") or "").strip(),
            "doc_id": str(raw.get("doc_id") or "").strip(),
            "file_name": str(raw.get("file_name") or "").strip(),
            "source_ref": str(raw.get("source_ref") or "").strip(),
        }
        if not any(item.values()):
            continue
        key = (item["dataset_id"], item["doc_id"], item["file_name"], item["source_ref"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_path(document_id: str, revision_id: str) -> Path:
    return _documents_dir() / document_id / "revisions" / revision_id / "manifest.json"


def _next_revision_no(document_id: str) -> int:
    revisions_dir = _documents_dir() / document_id / "revisions"
    highest = 0
    if revisions_dir.is_dir():
        for path in revisions_dir.glob("*/manifest.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                highest = max(highest, int(data.get("revision_no") or 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
    return highest + 1


def create_draft(
    form_id: str,
    fmt: str,
    *,
    project_id: int | None = None,
    manual: dict[str, Any] | None = None,
    dataset_id: str = "",
    source_refs: list[dict[str, Any]] | None = None,
    document_id: str | None = None,
    office_ir: dict[str, Any] | None = None,
    review_confirmed: bool = False,
) -> dict[str, Any]:
    """Создать новую неизменяемую ревизию DOCX/XLSX и её manifest."""
    fmt = str(fmt or "").strip().lower()
    if fmt not in {"docx", "xlsx"}:
        raise ValueError("Студия выпускает только DOCX или XLSX")
    descriptor = forms_service.load_descriptor(form_id)
    if descriptor is None:
        raise ValueError(f"Форма {form_id!r} не найдена")
    preserved_ir: dict[str, Any] | None = None
    if office_ir:
        if office_ir.get("schema") != "office_document_ir_v1" or str(office_ir.get("form_id") or "") != form_id:
            raise ValueError("Некорректный office_document_ir_v1")
        if not review_confirmed:
            raise ValueError("Подтвердите ручную проверку предложений Л.Е.С.")
        encoded_ir = json.dumps(office_ir, ensure_ascii=False)
        if len(encoded_ir.encode("utf-8")) > 256 * 1024:
            raise ValueError("office_document_ir_v1 превышает допустимый размер")
        preserved_ir = json.loads(encoded_ir)

    logical_id = _safe_id(document_id, label="document_id") if document_id else uuid.uuid4().hex
    revision_id = uuid.uuid4().hex
    revision_no = _next_revision_no(logical_id)
    revision_dir = _manifest_path(logical_id, revision_id).parent
    revisions_dir = revision_dir.parent
    revisions_dir.mkdir(parents=True, exist_ok=True)
    work_dir = revisions_dir / f".{revision_id}.tmp"
    work_dir.mkdir(parents=False, exist_ok=False)

    filename = f"{form_id}_r{revision_no}.{fmt}"
    artifact_path = work_dir / filename
    try:
        generated = forms_service.generate(
            form_id,
            fmt,
            project_id=project_id,
            manual=manual or {},
            out_path=artifact_path,
        )
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    resolved = dict(generated.get("resolved") or {})
    fields = list(resolved.get("fields") or [])
    missing_fields = [
        {"key": str(field.get("key") or ""), "label": str(field.get("label") or field.get("key") or "")}
        for field in fields
        if not str(field.get("value") or "").strip()
    ]
    sources = _clean_source_refs(source_refs)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    manifest = {
        "schema": ARTIFACT_SCHEMA,
        "document_id": logical_id,
        "revision_id": revision_id,
        "revision_no": revision_no,
        "state": "draft",
        "immutable": True,
        "originals_modified": False,
        "form_id": form_id,
        "title": str(resolved.get("title") or descriptor.get("title") or form_id),
        "format": fmt,
        "created_at": created_at,
        "project_id": project_id,
        "dataset_id": str(dataset_id or "").strip(),
        "source_refs": sources,
        "agent_assisted": preserved_ir is not None,
        "review_confirmed": bool(review_confirmed) if preserved_ir is not None else False,
        "office_document_ir": preserved_ir,
        "fields": fields,
        "missing_fields": missing_fields,
        "artifact": {
            "filename": filename,
            "relative_path": str((revision_dir / filename).relative_to(_workspace_dir())),
            "size": artifact_path.stat().st_size,
            "sha256": _sha256(artifact_path),
        },
    }
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(work_dir, revision_dir)
    return manifest


def _read_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != ARTIFACT_SCHEMA:
        return None
    return data


def list_artifacts(*, limit: int = 100) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _documents_dir().glob("*/revisions/*/manifest.json"):
        item = _read_manifest(path)
        if item is not None:
            rows.append(item)
    rows.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return rows[: max(1, min(int(limit or 100), 500))]


def get_artifact(revision_id: str) -> dict[str, Any] | None:
    revision_id = _safe_id(revision_id, label="revision_id")
    matches = list(_documents_dir().glob(f"*/revisions/{revision_id}/manifest.json"))
    if len(matches) != 1:
        return None
    return _read_manifest(matches[0])


def artifact_file(revision_id: str) -> tuple[Path, dict[str, Any]] | None:
    manifest = get_artifact(revision_id)
    if manifest is None:
        return None
    relative = str((manifest.get("artifact") or {}).get("relative_path") or "")
    root = _workspace_dir().resolve()
    target = (root / relative).resolve()
    if root not in target.parents or not target.is_file():
        return None
    if _sha256(target) != str((manifest.get("artifact") or {}).get("sha256") or ""):
        return None
    return target, manifest
