"""Project PDF extraction orchestrator.

Builds dataset-level source maps from PDF project files without reindexing.
The output is navigation for the model, not a final engineering answer.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.rag_config import rag_meta_db_path
from proxy.services.drawing_manifest_service import extract_pdf_drawing_manifest
from proxy.services.electrical_evidence_summary_service import build_electrical_evidence_summary
from proxy.services.electrical_materials_service import extract_electrical_material_manifest
from proxy.services.electrical_schematic_service import extract_electrical_schematic_manifest
from proxy.services.pd_rd_manifest_service import extract_pd_rd_manifest
from proxy.services.project_pdf_table_service import extract_project_pdf_table_manifest, summarize_project_table_manifests

PROJECT_PDF_EXTRACT_SCHEMA = "project_pdf_extract_v1"
PROJECT_PDF_FILE_EXTRACT_SCHEMA = "project_pdf_file_extract_v1"
PROJECT_PDF_EXTRACT_ALGO_VERSION = "0.24.0.344"
PROJECT_PDF_EXTRACT_DIR = "_les_pdf_extract"
DEFAULT_MAX_FILES = 80
DEFAULT_MAX_PAGES = 260
SOURCE_REF_LIMIT = 40
FILE_WARNING_LIMIT = 20
SUMMARY_WARNING_LIMIT = 100
VOLUME_REGISTER_LIMIT = 300

_DISCIPLINE_CODES = frozenset({
    "АВТ", "АК", "АН", "АР", "АС", "АУПТ", "АОВ", "АПС",
    "ВК", "ГП", "ГСВ", "ГСН", "ГОЧС",
    "ИОС", "ИИКЕО",
    "КЖ", "КМ", "КМД", "КР",
    "МПБ", "НВ", "НВК", "НК",
    "ОВ", "ОДИ", "ООС",
    "ПБ", "ПЗУ", "ПОД", "ПОС",
    "СЗЗ", "СОУЭ", "СС",
    "ТБЭ", "ТХ",
    "ЭМ", "ЭН", "ЭО", "ЭОМ", "ЭС", "ЭЭ",
})
_GENERIC_DISCIPLINE_CODES = frozenset({"ИОС"})
_ELECTRICAL_DISCIPLINE_CODES = frozenset({"ЭМ", "ЭН", "ЭО", "ЭОМ", "ЭС"})


def project_pdf_extract_root(dataset_id: str, *, storage_root: Path = Path("storage/datasets")) -> Path:
    return Path(storage_root) / _validated_dataset_id(dataset_id) / PROJECT_PDF_EXTRACT_DIR


def project_pdf_extract_status(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
    meta_db_path: str | None = None,
) -> dict[str, Any]:
    """Return sidecar status without extracting or mutating source files."""
    docs = _dataset_pdf_documents(dataset_id, meta_db_path=meta_db_path)
    root = project_pdf_extract_root(dataset_id, storage_root=storage_root)
    summary_path = root / "summary.json"
    summary = _read_json(summary_path)
    stale = True
    if isinstance(summary, dict) and summary.get("input_signature") == _input_signature(docs):
        stale = False
    coverage = summary.get("coverage") if isinstance(summary, dict) and isinstance(summary.get("coverage"), dict) else {}
    return {
        "schema": "project_pdf_extract_status_v1",
        "dataset_id": dataset_id,
        "pdf_documents": len(docs),
        "sidecar_root": root.as_posix(),
        "summary_exists": summary_path.exists(),
        "stale": stale,
        "updated_at": summary.get("updated_at") if isinstance(summary, dict) else "",
        "status": summary.get("status") if isinstance(summary, dict) else "missing",
        "files_extracted": int(coverage.get("files_extracted") or 0),
        "files_attempted": int(coverage.get("files_attempted") or 0),
        "coverage": coverage,
        "warnings": summary.get("warnings") if isinstance(summary, dict) else [],
        "warnings_total": int(summary.get("warnings_total") or 0) if isinstance(summary, dict) else 0,
        "warnings_truncated": bool(summary.get("warnings_truncated")) if isinstance(summary, dict) else False,
    }


def project_pdf_extract_summary(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    """Read the latest extraction summary, or return a missing-sidecar payload."""
    path = project_pdf_extract_root(dataset_id, storage_root=storage_root) / "summary.json"
    payload = _read_json(path)
    if isinstance(payload, dict):
        return payload
    return {
        "schema": PROJECT_PDF_EXTRACT_SCHEMA,
        "dataset_id": dataset_id,
        "status": "missing",
        "files": [],
        "volume_register": [],
        "discipline_summaries": [],
        "source_navigation": [],
        "coverage": {"pdf_documents": 0, "files_attempted": 0, "files_extracted": 0, "files_ok": 0},
        "warnings": ["project_pdf_extract_not_run"],
        "warnings_total": 1,
        "warnings_truncated": False,
    }


def run_project_pdf_extract(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
    meta_db_path: str | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_pages: int = DEFAULT_MAX_PAGES,
    force: bool = False,
) -> dict[str, Any]:
    """Extract project PDF sidecars and write a compact dataset summary.

    The function writes only under ``storage/datasets/{dataset_id}/_les_pdf_extract``.
    It never updates the vector index, source PDFs or MetaDB rows.
    """
    docs = _dataset_pdf_documents(dataset_id, meta_db_path=meta_db_path)
    files_to_process = docs[: max(0, int(max_files))]
    root = project_pdf_extract_root(dataset_id, storage_root=storage_root)
    root.mkdir(parents=True, exist_ok=True)
    signature = _input_signature(docs)
    summary_path = root / "summary.json"
    if not force:
        existing = _read_json(summary_path)
        if isinstance(existing, dict) and existing.get("input_signature") == signature:
            existing["cache"] = "hit"
            return existing

    files: list[dict[str, Any]] = []
    schematic_manifests: list[dict[str, Any]] = []
    material_manifests: list[dict[str, Any]] = []
    project_table_manifests: list[dict[str, Any]] = []
    volume_register: list[dict[str, Any]] = []
    warnings: list[str] = []

    for doc in files_to_process:
        file_extract = _extract_pdf_file(doc, dataset_id=dataset_id, storage_root=storage_root, root=root, max_pages=max_pages)
        files.append(file_extract)
        warnings.extend(str(w) for w in file_extract.get("warnings") or [])
        pd_manifest = _read_json(_artifact_path(file_extract, "pd_rd_manifest"))
        if isinstance(pd_manifest, dict):
            volume_register.extend(_volume_rows(pd_manifest))
        schematic = _read_json(_artifact_path(file_extract, "electrical_schematic_manifest"))
        if isinstance(schematic, dict):
            schematic_manifests.append(schematic)
        material = _read_json(_artifact_path(file_extract, "electrical_material_manifest"))
        if isinstance(material, dict):
            material_manifests.append(material)
        project_tables = _read_json(_artifact_path(file_extract, "project_pdf_table_manifest"))
        if isinstance(project_tables, dict):
            project_table_manifests.append(project_tables)

    electrical_summary: dict[str, Any] | None = None
    if schematic_manifests or material_manifests:
        electrical_summary = build_electrical_evidence_summary(schematic_manifests, material_manifests)
        _write_json(root / "electrical_evidence_summary.json", electrical_summary)
    project_table_summary: dict[str, Any] | None = None
    if project_table_manifests:
        project_table_summary = summarize_project_table_manifests(project_table_manifests)
        _write_json(root / "project_pdf_table_summary.json", project_table_summary)

    coverage = _coverage(
        docs,
        files,
        electrical_summary,
        project_table_summary,
        volume_rows=len(volume_register),
    )
    unique_warnings = sorted(set(warnings))
    result = {
        "schema": PROJECT_PDF_EXTRACT_SCHEMA,
        "dataset_id": dataset_id,
        "status": _summary_status(docs, files),
        "context_role": "navigation",
        "is_evidence": False,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_signature": signature,
        "sidecar_root": root.as_posix(),
        "files": files,
        "volume_register": volume_register[:VOLUME_REGISTER_LIMIT],
        "volume_register_total": len(volume_register),
        "volume_register_truncated": len(volume_register) > VOLUME_REGISTER_LIMIT,
        "discipline_summaries": _discipline_summaries(files, electrical_summary, project_table_summary),
        "source_navigation": _source_navigation(files, electrical_summary, project_table_summary),
        "coverage": coverage,
        "warnings": unique_warnings[:SUMMARY_WARNING_LIMIT],
        "warnings_total": len(unique_warnings),
        "warnings_truncated": len(unique_warnings) > SUMMARY_WARNING_LIMIT,
    }
    _write_json(summary_path, result)
    return result


def compact_project_pdf_extract_for_model(summary: dict[str, Any], *, max_files: int = 12) -> dict[str, Any]:
    """Compact project-PDF summary for dataset memory / prompt brief."""
    if not isinstance(summary, dict) or summary.get("status") == "missing":
        return {}
    return {
        "schema": "project_pdf_extract_brief_v1",
        "context_role": "navigation_not_evidence",
        "status": summary.get("status"),
        "coverage": summary.get("coverage") or {},
        "source_navigation": list(summary.get("source_navigation") or [])[:12],
        "discipline_summaries": list(summary.get("discipline_summaries") or [])[:8],
        "files": [
            {
                "file_name": item.get("file_name"),
                "doc_role": item.get("doc_role"),
                "discipline": item.get("discipline"),
                "cipher": item.get("cipher"),
                "layers": item.get("layers") or [],
                "status": item.get("status"),
            }
            for item in list(summary.get("files") or [])[:max_files]
            if isinstance(item, dict)
        ],
        "warnings": list(summary.get("warnings") or [])[:8],
    }


def _extract_pdf_file(
    doc: dict[str, Any],
    *,
    dataset_id: str,
    storage_root: Path,
    root: Path,
    max_pages: int,
) -> dict[str, Any]:
    file_name = str(doc.get("file_name") or "")
    doc_id = str(doc.get("id") or "")
    source_path = _document_source_path(doc, dataset_id=dataset_id, storage_root=storage_root)
    file_key = _file_key(doc, source_path)
    doc_root = root / file_key
    doc_root.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    artifact_paths: dict[str, str] = {}
    layers: list[str] = []
    source_refs: list[str] = []

    if source_path is None:
        warnings.append(f"missing_pdf_source:{file_name}")
        return _file_payload(doc, source_path, doc_root, artifact_paths, layers, source_refs, warnings, status="missing_source")

    if not source_path.stat().st_size:
        warnings.append(f"empty_pdf_source:{file_name}")
        return _file_payload(doc, source_path, doc_root, artifact_paths, layers, source_refs, warnings, status="extract_error")

    drawing: dict[str, Any] = {}
    pd_manifest: dict[str, Any] = {}

    try:
        drawing = extract_pdf_drawing_manifest(source_path, max_pages=max_pages)
        artifact_paths["drawing_manifest"] = _write_json(doc_root / "drawing_manifest.json", drawing).as_posix()
        layers.append("drawing_manifest")
        source_refs.extend(_manifest_source_refs(drawing))
        warnings.extend(str(w) for w in drawing.get("warnings") or [])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"drawing_manifest_error:{type(exc).__name__}:{file_name}")

    try:
        pd_manifest = extract_pd_rd_manifest(source_path, max_pages=max_pages)
        artifact_paths["pd_rd_manifest"] = _write_json(doc_root / "pd_rd_manifest.json", pd_manifest).as_posix()
        layers.append("pd_rd_manifest")
        source_refs.extend(_manifest_source_refs(pd_manifest))
        warnings.extend(str(w) for w in pd_manifest.get("warnings") or [])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"pd_rd_manifest_error:{type(exc).__name__}:{file_name}")

    if _looks_electrical(file_name, drawing, pd_manifest):
        try:
            schematic = extract_electrical_schematic_manifest(source_path, max_pages=max_pages)
            artifact_paths["electrical_schematic_manifest"] = _write_json(
                doc_root / "electrical_schematic_manifest.json",
                schematic,
            ).as_posix()
            layers.append("electrical_schematic_manifest")
            source_refs.extend(_manifest_source_refs(schematic))
            warnings.extend(str(w) for w in schematic.get("warnings") or [])
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"electrical_schematic_manifest_error:{type(exc).__name__}:{file_name}")

        try:
            material = extract_electrical_material_manifest(source_path, max_pages=max_pages)
            artifact_paths["electrical_material_manifest"] = _write_json(
                doc_root / "electrical_material_manifest.json",
                material,
            ).as_posix()
            layers.append("electrical_material_manifest")
            source_refs.extend(_manifest_source_refs(material))
            warnings.extend(str(w) for w in material.get("warnings") or [])
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"electrical_material_manifest_error:{type(exc).__name__}:{file_name}")

    try:
        project_tables = extract_project_pdf_table_manifest(source_path, max_pages=max_pages)
        table_summary = project_tables.get("summary") if isinstance(project_tables.get("summary"), dict) else {}
        if any(
            int(table_summary.get(key) or 0)
            for key in ("detected_tables", "hvs_rows", "water_balance_rows", "room_explication_rows")
        ):
            artifact_paths["project_pdf_table_manifest"] = _write_json(
                doc_root / "project_pdf_table_manifest.json",
                project_tables,
            ).as_posix()
            layers.append("project_pdf_table_manifest")
            source_refs.extend(_manifest_source_refs(project_tables))
        warnings.extend(str(w) for w in project_tables.get("warnings") or [])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"project_pdf_table_manifest_error:{type(exc).__name__}:{file_name}")

    status = "ok" if layers else "extract_error"
    return _file_payload(doc, source_path, doc_root, artifact_paths, layers, source_refs, warnings, status=status)


def _file_payload(
    doc: dict[str, Any],
    source_path: Path | None,
    doc_root: Path,
    artifact_paths: dict[str, str],
    layers: list[str],
    source_refs: list[str],
    warnings: list[str],
    *,
    status: str,
) -> dict[str, Any]:
    fields = _primary_fields(_read_json(Path(artifact_paths.get("drawing_manifest", ""))))
    file_name = str(doc.get("file_name") or "")
    prioritized_refs = _prioritize_source_refs(source_refs)
    unique_warnings = sorted(set(warnings))
    return {
        "schema": PROJECT_PDF_FILE_EXTRACT_SCHEMA,
        "file_name": file_name,
        "doc_id": str(doc.get("id") or ""),
        "source_path": source_path.as_posix() if source_path else "",
        "doc_role": _doc_role(file_name, fields),
        "cipher": fields.get("cipher_norm") or fields.get("cipher") or "",
        "stage": fields.get("stage") or "",
        "discipline": _discipline(file_name, fields),
        "layers": layers,
        "artifact_paths": artifact_paths,
        "source_refs": prioritized_refs[:SOURCE_REF_LIMIT],
        "source_refs_total": len(prioritized_refs),
        "source_refs_truncated": len(prioritized_refs) > SOURCE_REF_LIMIT,
        "status": status,
        "warnings": unique_warnings[:FILE_WARNING_LIMIT],
        "warnings_total": len(unique_warnings),
        "warnings_truncated": len(unique_warnings) > FILE_WARNING_LIMIT,
        "sidecar_dir": doc_root.as_posix(),
    }


def _dataset_pdf_documents(dataset_id: str, *, meta_db_path: str | None = None) -> list[dict[str, Any]]:
    with sqlite3.connect(meta_db_path or rag_meta_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(documents)").fetchall()
            if row["name"]
        }
        select_items = [
            "id",
            "dataset_id",
            "file_name",
            "status",
            "chunk_count" if "chunk_count" in columns else "0 AS chunk_count",
            "doc_type" if "doc_type" in columns else "'' AS doc_type",
            "content_type" if "content_type" in columns else "'' AS content_type",
            "domain" if "domain" in columns else "'' AS domain",
            "pipeline" if "pipeline" in columns else "'' AS pipeline",
            "source_path" if "source_path" in columns else "'' AS source_path",
        ]
        rows = conn.execute(
            f"""
            SELECT {", ".join(select_items)}
            FROM documents
            WHERE dataset_id=?
              AND lower(file_name) LIKE '%.pdf'
            ORDER BY file_name
            """,
            (dataset_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _document_source_path(doc: dict[str, Any], *, dataset_id: str, storage_root: Path) -> Path | None:
    candidates = [
        str(doc.get("source_path") or ""),
        str(doc.get("file_path") or ""),
        str(doc.get("path") or ""),
        str(doc.get("file_name") or ""),
    ]
    for raw in candidates:
        if not raw.strip():
            continue
        raw_path = Path(raw).expanduser()
        for path in _candidate_pdf_paths(raw_path, dataset_id=dataset_id, storage_root=storage_root):
            if path.exists() and path.is_file() and path.suffix.lower() == ".pdf":
                return path
    return None


def _candidate_pdf_paths(raw_path: Path, *, dataset_id: str, storage_root: Path) -> list[Path]:
    if raw_path.is_absolute():
        return [raw_path]
    dataset_root = Path(storage_root) / _validated_dataset_id(dataset_id)
    return [
        raw_path,
        dataset_root / raw_path,
        dataset_root / raw_path.name,
    ]


def _file_key(doc: dict[str, Any], source_path: Path | None) -> str:
    base = f"{doc.get('id') or ''}|{doc.get('file_name') or ''}|{source_path or ''}"
    digest = hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]
    name = Path(str(doc.get("file_name") or "pdf")).stem
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)[:60] or "pdf"
    return f"{safe}_{digest}"


def _input_signature(docs: list[dict[str, Any]]) -> str:
    payload = {
        "algo_version": PROJECT_PDF_EXTRACT_ALGO_VERSION,
        "docs": [
            {
                "id": doc.get("id"),
                "file_name": doc.get("file_name"),
                "status": doc.get("status"),
                "chunk_count": doc.get("chunk_count"),
                "source_path": doc.get("source_path"),
            }
            for doc in docs
        ],
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _safe_dataset_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value or "").strip())
    return safe[:80] or "standalone"


def _validated_dataset_id(value: str) -> str:
    raw = str(value or "").strip()
    safe = _safe_dataset_id(raw)
    if not raw or raw in {".", ".."} or raw != safe:
        raise ValueError("dataset_id must be a single safe path component")
    return safe


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read_json(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    try:
        p = Path(path)
    except TypeError:
        return None
    if not p.exists() or not p.is_file():
        return None
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _primary_fields(drawing_manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(drawing_manifest, dict):
        return {}
    for page in drawing_manifest.get("pages") or []:
        fields = page.get("fields") if isinstance(page, dict) else {}
        if isinstance(fields, dict) and fields:
            return fields
    return {}


def _doc_role(file_name: str, fields: dict[str, Any]) -> str:
    leaf = _file_leaf(file_name)
    text = leaf.casefold().replace("ё", "е")
    tokens = set(_code_tokens(leaf))
    kind = str(fields.get("document_kind_code") or "").upper().replace("Ё", "Е").strip()
    cipher_tokens = set(_code_tokens(str(fields.get("cipher_norm") or fields.get("cipher") or "")))
    if any(phrase in text for phrase in ("содержание тома", "состав тома", "состав проектной документации")):
        return "состав тома"
    if "расчет нагруз" in text:
        return "таблица расчета нагрузок"
    if "ВОР" in tokens or (kind == "ВОР" and "ВОР" in cipher_tokens):
        return "ведомость объемов работ"
    if "СО" in tokens or (kind == "СО" and "СО" in cipher_tokens) or "спецификац" in text:
        return "спецификация оборудования"
    if "ПЗ" in tokens or (kind == "ПЗ" and "ПЗ" in cipher_tokens) or "поясн" in text:
        return "пояснительная записка"
    return "проектный PDF"


def _discipline(file_name: str, fields: dict[str, Any]) -> str:
    file_codes = [code for token in _code_tokens(_file_leaf(file_name)) if (code := _discipline_code(token))]
    specific = [code for code in file_codes if code not in _GENERIC_DISCIPLINE_CODES]
    if specific:
        return specific[-1]
    if file_codes:
        return file_codes[-1]

    cipher_codes = {
        code
        for token in _code_tokens(str(fields.get("cipher_norm") or fields.get("cipher") or ""))
        if (code := _discipline_code(token))
    }
    for key in ("subdiscipline_code", "discipline_code"):
        code = _discipline_code(str(fields.get(key) or ""))
        if code and code in cipher_codes:
            return code
    return ""


def _looks_electrical(file_name: str, drawing: dict[str, Any], _pd_manifest: dict[str, Any]) -> bool:
    fields = _primary_fields(drawing)
    if _discipline(file_name, fields) in _ELECTRICAL_DISCIPLINE_CODES:
        return True
    leaf = _file_leaf(file_name)
    tokens = set(_code_tokens(leaf))
    text = leaf.upper().replace("Ё", "Е")
    if tokens.intersection({"ГРЩ", "ВРУ"}) or "РАСЧЕТ НАГРУЗ" in text:
        return True
    return False


def _manifest_source_refs(manifest: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    _collect_explicit_source_refs(manifest, refs, limit=SOURCE_REF_LIMIT * 4)
    file_name = str(manifest.get("file_name") or "")
    for page in manifest.get("pages") or []:
        if isinstance(page, dict):
            page_no = page.get("page")
            if page_no:
                refs.append(f"{file_name}#page={page_no}")
    return _prioritize_source_refs(refs)


def _collect_explicit_source_refs(value: Any, refs: list[str], *, limit: int) -> None:
    if len(refs) >= limit:
        return
    if isinstance(value, dict):
        ref = value.get("source_ref")
        if isinstance(ref, str) and ref.strip():
            refs.append(ref.strip())
        for child in value.values():
            _collect_explicit_source_refs(child, refs, limit=limit)
            if len(refs) >= limit:
                return
    elif isinstance(value, list):
        for child in value:
            _collect_explicit_source_refs(child, refs, limit=limit)
            if len(refs) >= limit:
                return


def _prioritize_source_refs(refs: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in refs:
        ref = str(raw or "").strip()
        if ref and ref not in seen:
            seen.add(ref)
            unique.append(ref)
    specific_markers = ("#table=", "#row=", "!R", ":pz_", ":volume_", ":project_")
    specific = [ref for ref in unique if any(marker in ref for marker in specific_markers)]
    specific_set = set(specific)
    return specific + [ref for ref in unique if ref not in specific_set]


def _file_leaf(value: str) -> str:
    return str(value or "").replace("\\", "/").rsplit("/", 1)[-1]


def _code_tokens(value: str) -> list[str]:
    return re.findall(r"[0-9A-ZА-ЯЁ]+", str(value or "").upper().replace("Ё", "Е"))


def _discipline_code(value: str) -> str:
    token = str(value or "").upper().replace("Ё", "Е").strip()
    if token in _DISCIPLINE_CODES or re.fullmatch(r"СС\d{1,2}", token):
        return token
    return ""


def _artifact_path(file_extract: dict[str, Any], key: str) -> Path | None:
    value = (file_extract.get("artifact_paths") or {}).get(key)
    return Path(value) if value else None


def _volume_rows(pd_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    register = pd_manifest.get("volume_contents_register") if isinstance(pd_manifest, dict) else {}
    rows = register.get("rows") if isinstance(register, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _discipline_summaries(
    files: list[dict[str, Any]],
    electrical_summary: dict[str, Any] | None,
    project_table_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_disc: dict[str, dict[str, Any]] = {}
    for item in files:
        key = str(item.get("discipline") or "UNKNOWN")
        row = by_disc.setdefault(key, {"discipline": key, "files": 0, "roles": {}, "layers": {}})
        row["files"] += 1
        role = str(item.get("doc_role") or "document")
        row["roles"][role] = row["roles"].get(role, 0) + 1
        for layer in item.get("layers") or []:
            row["layers"][layer] = row["layers"].get(layer, 0) + 1
    out = list(by_disc.values())
    if electrical_summary:
        out.append({
            "discipline": "ЭС/ЭОМ",
            "summary_layer": "electrical_evidence_summary_v1",
            "metrics": electrical_summary.get("summary") or {},
        })
    if project_table_summary:
        out.append({
            "discipline": "PROJECT_TABLES",
            "summary_layer": "project_pdf_table_summary_v1",
            "metrics": project_table_summary.get("summary") or {},
        })
    return out


def _source_navigation(
    files: list[dict[str, Any]],
    electrical_summary: dict[str, Any] | None,
    project_table_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    nav: list[dict[str, Any]] = []
    for item in files:
        role = str(item.get("doc_role") or "")
        if role in {"пояснительная записка", "состав тома", "таблица расчета нагрузок", "ведомость объемов работ", "спецификация оборудования"}:
            nav.append({
                "file_name": item.get("file_name"),
                "role": role,
                "discipline": item.get("discipline"),
                "use_for": _use_for_role(role),
                "layers": item.get("layers") or [],
                "source_refs": list(item.get("source_refs") or [])[:5],
            })
    if electrical_summary:
        for row in electrical_summary.get("source_navigation") or []:
            if isinstance(row, dict):
                nav.append(row)
    if project_table_summary:
        for row in project_table_summary.get("source_navigation") or []:
            if isinstance(row, dict):
                nav.append(row)
    return nav[:80]


def _use_for_role(role: str) -> str:
    return {
        "пояснительная записка": "проектные решения, исходные данные, техническое описание",
        "состав тома": "навигация по комплекту и поиск нужного листа/раздела",
        "таблица расчета нагрузок": "нагрузки, щиты, токи, мощности, кабельные длины при наличии",
        "ведомость объемов работ": "объёмы работ и строки для сметы/сверки",
        "спецификация оборудования": "оборудование, материалы, SO->draft ВОР",
    }.get(role, "навигация по проектному PDF")


def _coverage(
    docs: list[dict[str, Any]],
    files: list[dict[str, Any]],
    electrical_summary: dict[str, Any] | None,
    project_table_summary: dict[str, Any] | None = None,
    *,
    volume_rows: int = 0,
) -> dict[str, Any]:
    files_ok = sum(1 for item in files if item.get("status") == "ok")
    return {
        "pdf_documents": len(docs),
        "files_attempted": len(files),
        "files_unattempted": max(0, len(docs) - len(files)),
        "files_limit_truncated": len(files) < len(docs),
        "files_extracted": files_ok,
        "files_ok": files_ok,
        "missing_source": sum(1 for item in files if item.get("status") == "missing_source"),
        "extract_errors": sum(1 for item in files if item.get("status") == "extract_error"),
        "volume_rows": max(0, int(volume_rows)),
        "pz_files": sum(1 for item in files if item.get("doc_role") == "пояснительная записка"),
        "vor_files": sum(1 for item in files if item.get("doc_role") == "ведомость объемов работ"),
        "so_files": sum(1 for item in files if item.get("doc_role") == "спецификация оборудования"),
        "electrical_summary": (electrical_summary or {}).get("summary") or {},
        "project_table_summary": (project_table_summary or {}).get("summary") or {},
    }


def _summary_status(docs: list[dict[str, Any]], files: list[dict[str, Any]]) -> str:
    if not docs:
        return "empty"
    files_ok = sum(1 for item in files if item.get("status") == "ok")
    if files_ok == len(docs):
        return "ok"
    if files_ok:
        return "partial"
    return "failed"
