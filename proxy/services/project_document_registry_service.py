"""Document classification and virtual-volume assembly for Л.И.С.Т.

The service classifies MetaDB documents without parsing or indexing them, then
groups issued PDFs and editable/supporting files into virtual project volumes.
Assembly is a read-only register: missing and ambiguous components stay visible.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from backend.rag_config import rag_meta_db_path
from proxy.services.doc_type_classifier import classify_discipline, classify_doc_type
from proxy.services.document_set_model import parse_designation
from proxy.services.project_pdf_extract_service import project_pdf_extract_root, project_pdf_extract_summary

DOCUMENT_REGISTRY_SCHEMA = "project_document_registry_v1"
VIRTUAL_VOLUME_SCHEMA = "project_virtual_volume_v1"
DOCUMENT_REGISTRY_FILE = "document_registry.json"


def build_project_document_registry(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
    meta_db_path: str | None = None,
) -> dict[str, Any]:
    db_path = meta_db_path or rag_meta_db_path()
    docs = _dataset_documents(dataset_id, meta_db_path=db_path)
    dataset_meta = _dataset_metadata(dataset_id, meta_db_path=db_path)
    source_paths = [Path(str(doc.get("source_path") or "")).expanduser() for doc in docs if str(doc.get("source_path") or "")]
    common_root = _common_source_root(source_paths)
    table_summary = project_pdf_extract_summary(dataset_id, storage_root=storage_root)
    pdf_contexts = _pdf_contexts(table_summary)
    records = [
        _classify_document(
            doc,
            common_root=common_root,
            pdf_context=pdf_contexts.get(str(doc.get("id") or ""), {}),
        )
        for doc in docs
    ]
    _apply_dataset_stage(records, dataset_name=str(dataset_meta.get("name") or dataset_id))
    register_rows = [row for row in table_summary.get("volume_register") or [] if isinstance(row, dict)]
    volumes = _build_volumes(records, register_rows)
    project_meta = _resolve_project_meta(
        dataset_id,
        records,
        dataset_name=str(dataset_meta.get("name") or dataset_id),
        meta_db_path=db_path,
    )
    documentation = _build_documentation_entity(
        dataset_id,
        dataset_name=str(dataset_meta.get("name") or dataset_id),
        project_meta=project_meta,
        records=records,
        volumes=volumes,
    )
    payload = {
        "schema": DOCUMENT_REGISTRY_SCHEMA,
        "dataset_id": dataset_id,
        "status": "ok" if records else "empty",
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
        "source_root": common_root.as_posix() if common_root else "",
        "documentation": documentation,
        "document_count": len(records),
        "volume_count": len(volumes),
        "class_counts": dict(Counter(str(item.get("canonical_class") or "unknown") for item in records).most_common()),
        "role_counts": dict(Counter(str(item.get("assembly_role") or "unknown") for item in records).most_common()),
        "stage_counts": dict(Counter(str(item.get("stage") or "unknown") for item in records).most_common()),
        "section_counts": dict(Counter(str(item.get("section") or "unknown") for item in records).most_common()),
        "documents": records,
        "volumes": volumes,
    }
    root = project_pdf_extract_root(dataset_id, storage_root=storage_root)
    _write_json_atomic(root / DOCUMENT_REGISTRY_FILE, payload)
    return payload


def project_document_registry(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    path = project_pdf_extract_root(dataset_id, storage_root=storage_root) / DOCUMENT_REGISTRY_FILE
    payload = _read_json(path)
    if payload:
        return payload
    return {
        "schema": DOCUMENT_REGISTRY_SCHEMA,
        "dataset_id": dataset_id,
        "status": "missing",
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
        "document_count": 0,
        "volume_count": 0,
        "documents": [],
        "volumes": [],
        "warnings": ["document_registry_not_built"],
    }


def assemble_virtual_volume(
    dataset_id: str,
    index_query: str,
    *,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    query = str(index_query or "").strip()
    if not query:
        raise ValueError("index_query is required")
    registry = project_document_registry(dataset_id, storage_root=storage_root)
    volumes = list(registry.get("volumes") or [])
    query_norm = _norm_index(query)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for volume in volumes:
        score = _volume_score(volume, query_norm)
        if score > 0:
            ranked.append((score, volume))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("volume_key") or "")))
    if not ranked:
        return {
            "schema": VIRTUAL_VOLUME_SCHEMA,
            "dataset_id": dataset_id,
            "query": query,
            "status": "missing",
            "components": [],
            "missing": [f"том не найден по индексу: {query}"],
            "context_role": "navigation_not_evidence",
            "is_evidence": False,
        }
    top_score = ranked[0][0]
    ties = [volume for score, volume in ranked if score == top_score]
    selected = ties[0]
    status = "ambiguous" if len(ties) > 1 else str(selected.get("status") or "partial")
    documents_by_id = {
        str(item.get("document_id") or ""): item
        for item in registry.get("documents") or []
        if isinstance(item, dict) and item.get("document_id")
    }
    hydrated_components = [
        documents_by_id.get(str(item.get("document_id") or ""), item)
        for item in selected.get("components") or []
        if isinstance(item, dict)
    ]
    hydrated_volume = dict(selected) | {"components": hydrated_components}
    return {
        "schema": VIRTUAL_VOLUME_SCHEMA,
        "dataset_id": dataset_id,
        "query": query,
        "status": status,
        "score": top_score,
        "volume": hydrated_volume,
        "components": hydrated_components,
        "volume_register": list(selected.get("volume_register") or []),
        "alternatives": [
            {"volume_key": item.get("volume_key"), "index": item.get("index"), "discipline": item.get("discipline")}
            for item in ties[1:6]
        ],
        "missing": list(selected.get("missing") or []),
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
    }


def _dataset_documents(dataset_id: str, *, meta_db_path: str | None) -> list[dict[str, Any]]:
    with sqlite3.connect(meta_db_path or rag_meta_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(documents)") if row["name"]}
        wanted = [
            "id", "file_name", "status", "file_size", "chunk_count", "doc_type", "content_type",
            "domain", "route_dataset", "complexity", "pipeline", "source_path",
        ]
        select = [name if name in columns else f"'' AS {name}" for name in wanted]
        rows = conn.execute(
            f"SELECT {', '.join(select)} FROM documents WHERE dataset_id=? ORDER BY file_name",
            (dataset_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _classify_document(
    doc: dict[str, Any],
    *,
    common_root: Path | None,
    pdf_context: dict[str, Any],
) -> dict[str, Any]:
    source_path = Path(str(doc.get("source_path") or doc.get("file_name") or ""))
    relative = _relative_path(source_path, common_root)
    parts = relative.parts
    path_volume_key = parts[0] if len(parts) > 1 else (source_path.parent.name or "Без раздела")
    name = source_path.name or Path(str(doc.get("file_name") or "")).name
    suffix = source_path.suffix.casefold() or Path(name).suffix.casefold()
    lower_path = relative.as_posix().casefold().replace("ё", "е")
    lower_name = name.casefold().replace("ё", "е")
    designation = parse_designation(name)
    drawing_fields = pdf_context.get("drawing_fields") if isinstance(pdf_context.get("drawing_fields"), dict) else {}
    index = str(
        drawing_fields.get("cipher_norm")
        or (designation.raw if designation and _looks_like_project_index(designation.raw) else "")
        or pdf_context.get("cipher")
        or _extract_index(name)
    )
    base_cipher = str((designation.base_cipher if designation else "") or "")
    marka = str(
        drawing_fields.get("subdiscipline_code")
        or drawing_fields.get("discipline_code")
        or (designation.marka if designation else "")
        or pdf_context.get("discipline")
        or ""
    )
    classified_discipline = classify_discipline(name)
    discipline = marka or (classified_discipline if classified_discipline != "unknown" else "") or _discipline_from_path(path_volume_key, index)
    ingestion_doc_type = str(doc.get("doc_type") or "")
    classifier_type = classify_doc_type(name)
    document_kind_code = str(drawing_fields.get("document_kind_code") or "")
    document_kind_title = str(drawing_fields.get("document_kind_title") or "")
    canonical_class = document_kind_title or (classifier_type if classifier_type != "unknown" else ingestion_doc_type or "unknown")
    if canonical_class.casefold() in {"", "unknown"}:
        if suffix in {".xlsx", ".xls", ".xlsm", ".csv", ".tsv"}:
            canonical_class = "TABLE"
        elif suffix in {".pdf", ".doc", ".docx", ".rtf"}:
            canonical_class = "project_doc"
    role = "supporting_document"
    order = 50
    if "облож" in lower_name or "титул" in lower_name:
        role, order = "cover_title", 10
    elif suffix == ".pdf" and index and document_kind_code not in {"ПЗ", "PZ"}:
        role, order = "primary_volume", 20
    elif suffix == ".pdf" and "/pdf/" in f"/{lower_path}":
        role, order = "primary_volume", 20
    elif "редактируем" in lower_path:
        role, order = "editable_source", 40
    elif suffix in {".xlsx", ".xls", ".xlsm", ".csv", ".tsv"}:
        role, order = "supporting_table", 45
    elif suffix in {".doc", ".docx", ".rtf"}:
        role, order = "supporting_text", 46
    if path_volume_key.casefold().replace("ё", "е") == "сметы":
        if any(token in lower_name for token in ("ка", "кп", "коммерч")):
            role = "commercial_offer"
        else:
            role = "estimate"
    if document_kind_code in {"СО", "SO"} or re.search(r"(?:^|[-_.])(со|so)(?:[-_.]|$)", lower_name):
        role = "specification"
    elif document_kind_code == "ПЗ":
        role = "explanatory_note"
    related_kind = ""
    if "договор" in lower_name or classifier_type == "contract":
        related_kind = "contract"
    elif role == "commercial_offer":
        related_kind = "commercial_offer"
    elif role == "estimate" or classifier_type in {"estimate", "lsr"}:
        related_kind = "estimate"
    elif classifier_type == "mail":
        related_kind = "correspondence"
    entity_kind = "related_document" if related_kind else "project_document"
    record_id = str(doc.get("id") or hashlib.sha1(source_path.as_posix().encode()).hexdigest()[:20])
    page_count = int(pdf_context.get("page_count") or drawing_fields.get("page_count") or 0)
    sheet_count = _plausible_sheet_number(drawing_fields.get("sheet_count"), page_count=page_count)
    sheet_no = _plausible_sheet_number(drawing_fields.get("sheet_no"), page_count=page_count)
    return {
        "schema": "project_document_card_v1",
        "document_id": record_id,
        "file_name": str(doc.get("file_name") or name),
        "source_path": str(doc.get("source_path") or ""),
        "relative_path": relative.as_posix(),
        "extension": suffix,
        "volume_key": discipline or path_volume_key,
        "path_volume_key": path_volume_key,
        "index": index,
        "index_norm": _norm_index(index),
        "volume_identity": _volume_identity(
            index,
            document_kind_code,
            base_cipher=base_cipher,
            discipline=marka or discipline,
        ),
        "base_cipher": base_cipher,
        "marka": marka,
        "section": discipline or path_volume_key,
        "discipline": discipline,
        "canonical_class": canonical_class,
        "entity_kind": entity_kind,
        "related_kind": related_kind,
        "assembly_role": role,
        "order": order,
        "stage": _canonical_stage(str(drawing_fields.get("stage") or pdf_context.get("stage") or "")),
        "volume": str(drawing_fields.get("volume") or ""),
        "sheet_no": sheet_no,
        "sheet_count": sheet_count,
        "page_count": page_count,
        "declared_format": str(drawing_fields.get("declared_format") or ""),
        "document_kind_code": document_kind_code,
        "document_kind_title": document_kind_title,
        "source_file_name": str(drawing_fields.get("source_file_name") or ""),
        "sheet_title": str(drawing_fields.get("sheet_title") or ""),
        "object_name": str(drawing_fields.get("object_name") or ""),
        "address": str(drawing_fields.get("address") or ""),
        "sheets": list(pdf_context.get("sheet_register") or []),
        "ingestion": {
            "doc_type": ingestion_doc_type,
            "domain": str(doc.get("domain") or ""),
            "route_dataset": str(doc.get("route_dataset") or ""),
            "content_type": str(doc.get("content_type") or ""),
            "complexity": str(doc.get("complexity") or ""),
            "pipeline": str(doc.get("pipeline") or ""),
        },
        "classification": {
            "filename_class": classifier_type,
            "spds_designation_recognized": designation is not None,
            "drawing_manifest_available": bool(drawing_fields),
            "stage_source": "drawing_manifest" if _canonical_stage(str(drawing_fields.get("stage") or pdf_context.get("stage") or "")) else "",
        },
        "status": str(doc.get("status") or ""),
        "file_size": int(doc.get("file_size") or 0),
        "chunk_count": int(doc.get("chunk_count") or 0),
    }


def _apply_dataset_stage(records: list[dict[str, Any]], *, dataset_name: str) -> None:
    """Fill only missing project-document stages from the dataset's explicit kind."""
    fallback = _stage_from_dataset_name(dataset_name)
    if not fallback:
        return
    for record in records:
        if record.get("entity_kind") != "project_document" or record.get("stage"):
            continue
        record["stage"] = fallback
        classification = record.get("classification")
        if isinstance(classification, dict):
            classification["stage_source"] = "dataset_name"


def _plausible_sheet_number(value: Any, *, page_count: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.fullmatch(r"0*(\d{1,4})", text)
    if not match:
        return ""
    number = int(match.group(1))
    if number < 1 or (page_count > 0 and number > page_count):
        return ""
    return str(number)


def _build_volumes(records: list[dict[str, Any]], register_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    project_records = [record for record in records if record.get("entity_kind") != "related_document"]
    groups = _associate_volume_records(project_records)
    out: list[dict[str, Any]] = []
    for group_key, items in groups.items():
        ordered = sorted(items, key=lambda item: (int(item.get("order") or 50), str(item.get("relative_path") or "")))
        primary = [item for item in ordered if item.get("assembly_role") == "primary_volume"]
        primary_indexes = [str(item.get("index") or "") for item in primary if item.get("index")]
        index = primary_indexes[0] if primary_indexes else next((str(item.get("index") or "") for item in ordered if item.get("index")), "")
        discipline = next((str(item.get("discipline") or "") for item in primary + ordered if item.get("discipline")), "")
        volume_key = discipline or next((str(item.get("path_volume_key") or "") for item in ordered if item.get("path_volume_key")), "Без раздела")
        bases = {str((item.get("volume_association") or {}).get("basis") or "") for item in ordered}
        confidence = min((float((item.get("volume_association") or {}).get("confidence") or 0.0) for item in ordered), default=0.0)
        primary_names = {Path(str(item.get("source_path") or item.get("file_name") or "")).name for item in primary}
        rows = [
            row for row in register_rows
            if Path(str(row.get("source_ref") or "").split("#", 1)[0]).name in primary_names
        ]
        missing: list[str] = []
        if not primary:
            missing.append("нет выпущенного PDF в папке PDF")
        if len(primary) > 1:
            missing.append("несколько выпущенных PDF — требуется выбрать основной")
        status = "complete" if len(primary) == 1 else ("ambiguous" if len(primary) > 1 else "partial")
        out.append(
            {
                "schema": "project_volume_card_v1",
                "volume_id": hashlib.sha1(group_key.encode("utf-8", errors="ignore")).hexdigest()[:16],
                "volume_key": volume_key,
                "index": index,
                "index_norm": _norm_index(index),
                "discipline": discipline,
                "status": status,
                "document_count": len(ordered),
                "issued_pdf_count": len(primary),
                "association_basis": "+".join(sorted(basis for basis in bases if basis)) or "unresolved",
                "association_confidence": round(confidence, 3),
                "components": [_document_ref(item) for item in ordered],
                "volume_register": rows,
                "volume_register_count": len(rows),
                "missing": missing,
            }
        )
    return sorted(out, key=lambda item: (str(item.get("discipline") or ""), str(item.get("volume_key") or "")))


def _associate_volume_records(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []
    for item in records:
        index_norm = str(item.get("volume_identity") or "")
        if index_norm and _is_strong_volume_identity(index_norm) and item.get("assembly_role") == "primary_volume":
            item["volume_association"] = {"basis": "cipher_exact", "confidence": 1.0}
            groups[f"cipher:{index_norm}"].append(item)
        else:
            unresolved.append(item)
    for item in unresolved:
        identity = str(item.get("volume_identity") or "")
        exact_key = f"cipher:{identity}"
        if identity and exact_key in groups:
            item["volume_association"] = {"basis": "cipher_exact", "confidence": 1.0}
            groups[exact_key].append(item)
            continue
        discipline = _norm_index(str(item.get("discipline") or ""))
        stage = str(item.get("stage") or "")
        candidates = []
        for key, members in groups.items():
            member_disciplines = {_norm_index(str(member.get("discipline") or "")) for member in members}
            member_stages = {str(member.get("stage") or "") for member in members if member.get("stage")}
            if discipline and discipline in member_disciplines and (not stage or not member_stages or stage in member_stages):
                candidates.append(key)
        if len(candidates) == 1:
            item["volume_association"] = {"basis": "discipline_unique", "confidence": 0.8}
            groups[candidates[0]].append(item)
            continue
        path_key = _norm_index(str(item.get("path_volume_key") or ""))
        path_candidates = [
            key for key in candidates
            if any(path_key and path_key in {
                _norm_index(str(member.get("path_volume_key") or "")),
                _norm_index(str(member.get("discipline") or "")),
            } for member in groups[key])
        ]
        if len(path_candidates) == 1:
            item["volume_association"] = {"basis": "path_disambiguation", "confidence": 0.6}
            groups[path_candidates[0]].append(item)
            continue
        weak_identity = str(item.get("volume_identity") or "")
        if weak_identity:
            strong = _is_strong_volume_identity(weak_identity)
            fallback = f"cipher:{weak_identity}" if strong else f"cipher-weak:{weak_identity}"
            item["volume_association"] = {"basis": "cipher_exact" if strong else "cipher_weak", "confidence": 0.9 if strong else 0.65}
        else:
            fallback = f"fallback:{stage}:{discipline}:{path_key or item.get('document_id')}"
            item["volume_association"] = {"basis": "path_fallback" if path_key else "unresolved", "confidence": 0.35 if path_key else 0.0}
        groups[fallback].append(item)
    return groups


def _volume_score(volume: dict[str, Any], query_norm: str) -> int:
    if not query_norm:
        return 0
    score = 0
    index_norm = str(volume.get("index_norm") or "")
    key_norm = _norm_index(str(volume.get("volume_key") or ""))
    discipline_norm = _norm_index(str(volume.get("discipline") or ""))
    if query_norm == index_norm and index_norm:
        score += 200
    elif query_norm in index_norm or index_norm in query_norm:
        score += 100
    if query_norm == key_norm or query_norm == discipline_norm:
        score += 80
    for component in volume.get("components") or []:
        haystack = _norm_index(" ".join((str(component.get("index") or ""), str(component.get("relative_path") or ""))))
        if query_norm in haystack:
            score += 20
            break
    return score


def _build_documentation_entity(
    dataset_id: str,
    *,
    dataset_name: str,
    project_meta: dict[str, Any],
    records: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
) -> dict[str, Any]:
    related = [item for item in records if item.get("entity_kind") == "related_document"]
    project_documents = [item for item in records if item.get("entity_kind") == "project_document"]
    stages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for volume in volumes:
        stage = _normalize_stage(next(
            (str(item.get("stage") or "") for item in volume.get("components") or [] if item.get("stage")),
            _stage_from_dataset_name(dataset_name),
        ))
        sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in volume.get("components") or []:
            section = str(item.get("marka") or item.get("discipline") or item.get("section") or "Без раздела")
            sections[section].append(item)
        volume_node = {key: value for key, value in volume.items() if key not in {"components", "volume_register"}} | {
            "stage": stage,
            "sections": [
                {"code": code, "document_count": len(items), "documents": [_document_ref(item) for item in items]}
                for code, items in sorted(sections.items())
            ],
        }
        stages[stage].append(volume_node)
    project_node = {
        "schema": "documentation_project_v1",
        **project_meta,
        "document_count": len(project_documents),
        "stage_count": len(stages),
        "stages": [
            {
                "stage": stage,
                "volume_count": len(stage_volumes),
                "volumes": sorted(stage_volumes, key=lambda item: str(item.get("volume_key") or "")),
            }
            for stage, stage_volumes in sorted(stages.items())
        ],
    }
    return {
        "schema": "documentation_entity_v1",
        "documentation_id": dataset_id,
        "name": dataset_name,
        "project_count": 1 if project_documents else 0,
        "projects": [project_node] if project_documents else [],
        "related_entity_count": len(related),
        "related_entities": sorted(
            related,
            key=lambda item: (str(item.get("related_kind") or ""), str(item.get("relative_path") or "")),
        ),
        "relation_basis": str(project_meta.get("association_basis") or "dataset_scope"),
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
    }


def _document_ref(item: dict[str, Any]) -> dict[str, Any]:
    """Compact relation record; the full document card lives once in documents[]."""
    keys = (
        "document_id", "file_name", "relative_path", "extension", "index", "index_norm", "volume_identity",
        "marka", "section", "discipline", "canonical_class", "entity_kind", "related_kind",
        "assembly_role", "order", "stage", "page_count", "volume_association", "status",
    )
    return {key: item.get(key) for key in keys}


def _resolve_project_meta(
    dataset_id: str,
    records: list[dict[str, Any]],
    *,
    dataset_name: str,
    meta_db_path: str,
) -> dict[str, Any]:
    explicit = _explicit_project(dataset_id, meta_db_path=meta_db_path)
    if explicit:
        return {
            "project_id": explicit.get("id"),
            "name": explicit.get("name") or dataset_name,
            "code": explicit.get("code") or _dominant(records, "base_cipher"),
            "address": explicit.get("address") or _dominant(records, "address"),
            "association_basis": "les_project_dataset_link",
        }
    object_name = _dominant(records, "object_name")
    base_cipher = _dominant(records, "base_cipher")
    address = _dominant(records, "address")
    matched = _match_project_candidate(
        name=object_name or dataset_name,
        code=base_cipher,
        address=address,
        meta_db_path=meta_db_path,
    )
    if matched:
        return {
            "project_id": matched.get("id"),
            "name": matched.get("name") or object_name or dataset_name,
            "code": matched.get("code") or base_cipher,
            "address": matched.get("address") or address,
            "association_basis": "code_object_or_address_match",
        }
    return {
        "project_id": None,
        "name": object_name or dataset_name,
        "code": base_cipher,
        "address": address,
        "association_basis": "derived_from_dataset_metadata",
    }


def _dataset_metadata(dataset_id: str, *, meta_db_path: str) -> dict[str, Any]:
    try:
        with sqlite3.connect(meta_db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "datasets"):
                return {"id": dataset_id, "name": dataset_id}
            row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
            return dict(row) if row else {"id": dataset_id, "name": dataset_id}
    except sqlite3.Error:
        return {"id": dataset_id, "name": dataset_id}


def _explicit_project(dataset_id: str, *, meta_db_path: str) -> dict[str, Any] | None:
    try:
        with sqlite3.connect(meta_db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not (_table_exists(conn, "les_projects") and _table_exists(conn, "les_project_links")):
                return None
            row = conn.execute(
                """
                SELECT p.* FROM les_projects p
                JOIN les_project_links l ON l.project_id=p.id
                WHERE l.kind='dataset' AND l.ref=?
                ORDER BY l.id LIMIT 1
                """,
                (dataset_id,),
            ).fetchone()
            return dict(row) if row else None
    except sqlite3.Error:
        return None


def _match_project_candidate(
    *,
    name: str,
    code: str,
    address: str,
    meta_db_path: str,
) -> dict[str, Any] | None:
    try:
        with sqlite3.connect(meta_db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not _table_exists(conn, "les_projects"):
                return None
            rows = [dict(row) for row in conn.execute("SELECT * FROM les_projects WHERE status!='archived'")]
    except sqlite3.Error:
        return None
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        score = 0
        if code and _norm_index(code) == _norm_index(str(row.get("code") or "")):
            score += 100
        if name and _norm_phrase(name) == _norm_phrase(str(row.get("name") or "")):
            score += 50
        if address and _norm_phrase(address) == _norm_phrase(str(row.get("address") or "")):
            score += 50
        if score:
            scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], int(item[1].get("id") or 0)))
    return scored[0][1] if scored else None


def _dominant(records: list[dict[str, Any]], key: str) -> str:
    counts = Counter(str(item.get(key) or "").strip() for item in records if str(item.get(key) or "").strip())
    return counts.most_common(1)[0][0] if counts else ""


def _normalize_stage(value: str) -> str:
    return _canonical_stage(value) or "не определена"


def _canonical_stage(value: str) -> str:
    stage = re.sub(r"[^0-9A-ZА-ЯЁ]", "", str(value or "").strip().upper().replace("Ё", "Е"))
    return {
        "П": "ПД",
        "ПД": "ПД",
        "P": "ПД",
        "PROJECT": "ПД",
        "Р": "РД",
        "РД": "РД",
        "R": "РД",
        "WORKING": "РД",
        "ИД": "ИД",
        "И": "ИД",
        "ASBUILT": "ИД",
        "ЭП": "ЭП",
        "ТЭО": "ТЭО",
        "КД": "КД",
    }.get(stage, "")


def _stage_from_dataset_name(value: str) -> str:
    text = _norm_phrase(value)
    if "рабочая документация" in text:
        return "РД"
    if "проектная документация" in text:
        return "ПД"
    if "исполнительная документация" in text:
        return "ИД"
    return ""


def _norm_phrase(value: str) -> str:
    return " ".join(re.findall(r"[0-9a-zа-я]+", str(value or "").casefold().replace("ё", "е")))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _pdf_contexts(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for item in summary.get("files") or []:
        if not isinstance(item, dict):
            continue
        context = dict(item)
        drawing_path = (item.get("artifact_paths") or {}).get("drawing_manifest")
        drawing = _read_json(Path(str(drawing_path or ""))) if drawing_path else None
        if drawing:
            top_fields = drawing.get("fields") if isinstance(drawing.get("fields"), dict) else {}
            sheet_register = _sheet_register(drawing, source_path=str(item.get("source_path") or ""))
            context["sheet_register"] = sheet_register
            context["drawing_fields"] = _merge_drawing_fields(top_fields, sheet_register)
            context["page_count"] = int(drawing.get("page_count") or 0)
        doc_id = str(item.get("doc_id") or "")
        if doc_id:
            contexts[doc_id] = context
    return contexts


def _sheet_register(drawing: dict[str, Any], *, source_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in drawing.get("pages") or []:
        if not isinstance(page, dict):
            continue
        fields = page.get("fields") if isinstance(page.get("fields"), dict) else {}
        stage = _canonical_stage(str(fields.get("stage") or ""))
        row = {
            "page": int(page.get("page") or 0),
            "cipher": str(fields.get("cipher_norm") or fields.get("cipher") or ""),
            "stage": stage,
            "sheet_no": str(fields.get("sheet_no") or ""),
            "sheet_count": str(fields.get("sheet_count") or ""),
            "sheet_title": str(fields.get("sheet_title") or ""),
            "declared_format": str(fields.get("declared_format") or ""),
            "document_kind_code": str(fields.get("document_kind_code") or ""),
            "source_file_name": str(fields.get("source_file_name") or ""),
            "source_ref": f"{source_path}#page={int(page.get('page') or 0)}",
        }
        if any(row[key] for key in ("cipher", "stage", "sheet_no", "sheet_title", "declared_format", "document_kind_code")):
            rows.append(row)
    return rows


def _merge_drawing_fields(top_fields: dict[str, Any], sheets: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(top_fields)
    for target, source in (
        ("cipher_norm", "cipher"),
        ("stage", "stage"),
        ("sheet_no", "sheet_no"),
        ("sheet_count", "sheet_count"),
        ("sheet_title", "sheet_title"),
        ("declared_format", "declared_format"),
        ("document_kind_code", "document_kind_code"),
        ("source_file_name", "source_file_name"),
    ):
        values = [str(row.get(source) or "") for row in sheets if str(row.get(source) or "")]
        if values:
            merged[target] = Counter(values).most_common(1)[0][0]
    merged["stage"] = _canonical_stage(str(merged.get("stage") or ""))
    return merged


def _extract_index(file_name: str) -> str:
    stem = Path(str(file_name or "")).stem
    compact = " ".join(stem.split())
    match = re.search(r"\d{2,}[._/-][0-9A-Za-zА-Яа-яЁё._/-]+", compact)
    return match.group(0).strip(" ._-") if match else ""


def _looks_like_project_index(value: str) -> bool:
    text = str(value or "")
    return bool(re.search(r"\d", text) and re.search(r"[._/-]", text))


def _discipline_from_path(volume_key: str, index: str) -> str:
    key = str(volume_key or "").strip()
    if key and len(key) <= 20 and re.fullmatch(r"[0-9A-Za-zА-Яа-яЁё_.() -]+", key):
        return key
    tokens = re.findall(r"[A-ZА-ЯЁ]{2,8}\d*", str(index or "").upper())
    return tokens[-1] if tokens else ""


def _norm_index(value: str) -> str:
    text = str(value or "").upper().replace("Ё", "Е")
    text = re.sub(r"[._/\\\s]+", "-", text)
    text = re.sub(r"\b[VB](?=\d)", "В", text)
    return re.sub(r"-+", "-", text).strip("-")


def _volume_identity(index: str, document_kind_code: str = "", *, base_cipher: str = "", discipline: str = "") -> str:
    base = _norm_index(base_cipher)
    discipline_norm = _norm_index(discipline)
    if base and discipline_norm and discipline_norm != "UNKNOWN":
        return f"{base}-{discipline_norm}"
    normalized = _norm_index(index)
    if not normalized:
        return ""
    parts = [_canonical_discipline_token(part) for part in normalized.split("-")]
    if discipline_norm and discipline_norm in parts:
        parts = parts[: parts.index(discipline_norm) + 1]
    trailing_kinds = {"СО", "SO", "ПЗ", "PZ", "ВОР", "VOR"}
    kind = _norm_index(document_kind_code)
    if len(parts) > 2 and parts[-1] in trailing_kinds and (not kind or parts[-1] == kind):
        parts.pop()
    return "-".join(parts)


def _canonical_discipline_token(value: str) -> str:
    return {
        "AR": "АР", "AOV": "АОВ", "OV": "ОВ", "VK": "ВК", "APS": "АПС",
        "APPZ": "АППЗ", "SOUE": "СОУЭ", "AUPT": "АУПТ", "EM": "ЭМ",
        "EO": "ЭО", "EOM": "ЭОМ", "ES": "ЭС", "SS": "СС", "TH": "ТХ",
        "KR": "КР", "KJ": "КЖ", "KM": "КМ",
    }.get(value, value)


def _is_strong_volume_identity(value: str) -> bool:
    return len([part for part in _norm_index(value).split("-") if part]) >= 4


def _common_source_root(paths: list[Path]) -> Path | None:
    absolute = [path.resolve() for path in paths if path.is_absolute()]
    if not absolute:
        return None
    try:
        common = Path(os.path.commonpath([path.as_posix() for path in absolute]))
    except ValueError:
        return None
    return common if common.is_dir() else common.parent


def _relative_path(path: Path, common_root: Path | None) -> Path:
    if common_root and path.is_absolute():
        try:
            return path.resolve().relative_to(common_root.resolve())
        except ValueError:
            pass
    return Path(path.name or path.as_posix())


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
