"""Model-first preparation of office fields for the L.I.S.T. Studio.

The model receives bounded excerpts from explicitly selected documents and
returns a typed intermediate representation.  This service never renders an
office file: the operator must review the proposal in the GUI and separately
call ``list_office_service.create_draft``.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from proxy.services import extract_service, forms_service
from proxy.services.document_explorer_service import DocumentExplorer, explorer


IR_SCHEMA = "office_document_ir_v1"
MAX_DOCUMENTS = 8
MAX_EVIDENCE = 24
MAX_EXCERPT_CHARS = 900
MAX_INSTRUCTION_CHARS = 4000


class OfficeAgentUnavailable(RuntimeError):
    """The active LES model could not produce a valid office IR."""


Extractor = Callable[..., Awaitable[Any]]


def _manual_fields(form_id: str, project_id: int | None, manual: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved = forms_service.resolve_fields(form_id, project_id, manual)
    if resolved is None:
        raise ValueError(f"Форма {form_id!r} не найдена")
    fields = [
        dict(field)
        for field in resolved.get("fields") or []
        if str(field.get("source") or "manual") == "manual"
    ]
    return resolved, fields


def _selected_documents(
    source_refs: list[dict[str, Any]] | None,
    *,
    dataset_id: str,
    reader: DocumentExplorer,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in source_refs or []:
        if not isinstance(raw, dict):
            continue
        doc_id = str(raw.get("doc_id") or "").strip()
        if not doc_id or doc_id in seen:
            continue
        document = reader.get_document(doc_id)
        if document is None:
            raise ValueError(f"Выбранный документ {doc_id!r} не найден в реестре Л.И.С.Т.")
        actual_dataset = str(document.get("dataset_id") or "").strip()
        if dataset_id and actual_dataset != dataset_id:
            raise ValueError("Выбранный документ не принадлежит активному датасету")
        seen.add(doc_id)
        selected.append(document)
        if len(selected) >= MAX_DOCUMENTS:
            break
    if not selected:
        raise ValueError("Выберите хотя бы один файл-основание в Л.И.С.Т.")
    return selected


def _chunk_key(chunk: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(chunk.get("doc_id") or ""),
        str(chunk.get("point_id") or ""),
        str(chunk.get("chunk_ord") or ""),
    )


def _collect_evidence(
    documents: list[dict[str, Any]],
    *,
    instruction: str,
    field_labels: list[str],
    reader: DocumentExplorer,
) -> list[dict[str, Any]]:
    query = " ".join(part for part in [instruction, *field_labels] if str(part).strip())[:MAX_INSTRUCTION_CHARS]
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            key = _chunk_key(row)
            text = str(row.get("snippet") or row.get("text") or "").strip()
            if not text or key in seen:
                continue
            seen.add(key)
            candidates.append({**row, "text": text[:MAX_EXCERPT_CHARS]})

    per_document = max(2, MAX_EVIDENCE // max(1, len(documents)))
    for document in documents:
        doc_id = str(document.get("id") or "")
        if query:
            search_result = reader.search(query, doc_id=doc_id, limit=min(3, per_document), max_chars=MAX_EXCERPT_CHARS)
            add(list(search_result.get("hits") or []))
        ordered = reader.document_chunks_by_id(
            doc_id,
            limit=per_document,
            max_chars=MAX_EXCERPT_CHARS,
        )
        if ordered:
            add(list(ordered.get("chunks") or []))

    evidence: list[dict[str, Any]] = []
    for index, chunk in enumerate(candidates[:MAX_EVIDENCE], 1):
        chunk_ord = chunk.get("chunk_ord")
        file_name = str(chunk.get("doc_name") or "")
        evidence.append({
            "evidence_id": f"E{index}",
            "dataset_id": str(chunk.get("dataset_id") or ""),
            "doc_id": str(chunk.get("doc_id") or ""),
            "file_name": file_name,
            "point_id": str(chunk.get("point_id") or ""),
            "chunk_ord": chunk_ord,
            "section": str(chunk.get("section_heading") or chunk.get("parent_heading") or ""),
            "source_ref": f"{file_name}#chunk={chunk_ord}",
            "excerpt": str(chunk.get("text") or ""),
        })
    if not evidence:
        raise ValueError("В выбранных файлах нет доступных текстовых фрагментов")
    return evidence


def _response_schema(keys: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["fields"],
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key", "value", "status", "confidence", "evidence_ids", "note"],
                    "properties": {
                        "key": {"type": "string", "enum": keys},
                        "value": {"type": "string"},
                        "status": {"type": "string", "enum": ["grounded", "assumption", "missing"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                        "note": {"type": "string"},
                    },
                },
            },
        },
    }


def _context(
    *,
    title: str,
    instruction: str,
    fields: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    payload = {
        "document_title": title,
        "operator_instruction": instruction,
        "fields_to_prepare": [
            {"key": field.get("key"), "label": field.get("label"), "type": field.get("type", "str")}
            for field in fields
        ],
        "evidence": evidence,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _canonical_sources(documents: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "dataset_id": str(document.get("dataset_id") or ""),
            "doc_id": str(document.get("id") or ""),
            "file_name": str(document.get("file_name") or ""),
            "source_ref": str(document.get("file_name") or ""),
        }
        for document in documents
    ]


def _normalize_fields(
    raw_fields: list[dict[str, Any]],
    *,
    fields: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    evidence_by_id = {str(item["evidence_id"]): item for item in evidence}
    expected = {str(item.get("key") or ""): item for item in fields}
    proposals: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for item in raw_fields:
        key = str(item.get("key") or "")
        if key not in expected or key in proposals:
            warnings.append(f"Модель вернула неизвестное или повторное поле: {key or 'без ключа'}")
            continue
        status = str(item.get("status") or "missing")
        value = str(item.get("value") or "").strip()
        evidence_ids = [str(value) for value in item.get("evidence_ids") or []]
        linked = [evidence_by_id[value] for value in evidence_ids if value in evidence_by_id]
        if status == "grounded" and not linked:
            status = "assumption" if value else "missing"
            warnings.append(f"Поле {key}: evidence модели не подтверждено контрактом")
        if status == "missing":
            value = ""
            linked = []
        try:
            confidence = min(1.0, max(0.0, float(item.get("confidence") or 0)))
        except (TypeError, ValueError):
            confidence = 0.0
        proposals[key] = {
            "key": key,
            "label": str(expected[key].get("label") or key),
            "value": value,
            "status": status,
            "confidence": confidence,
            "evidence": linked,
            "note": str(item.get("note") or "").strip(),
        }
    for key, field in expected.items():
        if key not in proposals:
            proposals[key] = {
                "key": key,
                "label": str(field.get("label") or key),
                "value": "",
                "status": "missing",
                "confidence": 0.0,
                "evidence": [],
                "note": "Модель не вернула поле.",
            }
    return [proposals[str(field.get("key") or "")] for field in fields], warnings


async def prepare_document_ir(
    form_id: str,
    *,
    project_id: int | None = None,
    manual: dict[str, Any] | None = None,
    dataset_id: str = "",
    source_refs: list[dict[str, Any]] | None = None,
    instruction: str = "",
    reader: DocumentExplorer | None = None,
    extractor: Extractor | None = None,
) -> dict[str, Any]:
    """Return a reviewable IR; never create or modify an office document."""
    manual = dict(manual or {})
    instruction = str(instruction or "").strip()[:MAX_INSTRUCTION_CHARS]
    resolved, manual_fields = _manual_fields(form_id, project_id, manual)
    editable = [field for field in manual_fields if not str(manual.get(str(field.get("key") or ""), "")).strip()]
    reader = reader or explorer()
    documents = await asyncio.to_thread(
        _selected_documents,
        source_refs,
        dataset_id=dataset_id,
        reader=reader,
    )
    if not editable:
        return {
            "schema": IR_SCHEMA,
            "form_id": form_id,
            "title": str(resolved.get("title") or form_id),
            "fields": [],
            "missing_fields": [],
            "warnings": ["Все ручные поля уже заполнены; модель ничего не изменяла."],
            "source_refs": _canonical_sources(documents),
            "evidence_count": 0,
            "review_required": True,
            "artifact_created": False,
            "model_attempts": 0,
        }

    evidence = await asyncio.to_thread(
        _collect_evidence,
        documents,
        instruction=instruction,
        field_labels=[str(field.get("label") or field.get("key") or "") for field in editable],
        reader=reader,
    )
    keys = [str(field.get("key") or "") for field in editable]
    instruction_text = (
        "Подготовь значения только для перечисленных ручных полей офисного документа. "
        "Не выдумывай факты. status=grounded допустим только при прямой опоре на evidence_id; "
        "status=assumption используй для явно видимого авторского предположения; если данных нет, "
        "верни status=missing и пустое value. Не добавляй поля и не меняй факты источников."
    )
    run_extractor = extractor or extract_service.run_structured_extraction
    result = await run_extractor(
        _response_schema(keys),
        instruction_text,
        _context(
            title=str(resolved.get("title") or form_id),
            instruction=instruction,
            fields=editable,
            evidence=evidence,
        ),
        max_attempts=3,
        max_tokens=4096,
    )
    if not getattr(result, "ok", False) or not isinstance(getattr(result, "data", None), dict):
        details = "; ".join(str(value) for value in (getattr(result, "errors", None) or []) if str(value).strip())
        raise OfficeAgentUnavailable(details or "Модель не вернула валидный office_document_ir_v1")

    proposals, warnings = _normalize_fields(
        list((result.data or {}).get("fields") or []),
        fields=editable,
        evidence=evidence,
    )
    return {
        "schema": IR_SCHEMA,
        "form_id": form_id,
        "title": str(resolved.get("title") or form_id),
        "dataset_id": str(dataset_id or ""),
        "instruction": instruction,
        "fields": proposals,
        "missing_fields": [
            {"key": item["key"], "label": item["label"]}
            for item in proposals if not str(item.get("value") or "").strip()
        ],
        "warnings": warnings,
        "source_refs": _canonical_sources(documents),
        "evidence_count": len(evidence),
        "review_required": True,
        "artifact_created": False,
        "model_attempts": int(getattr(result, "attempts", 0) or 0),
    }
