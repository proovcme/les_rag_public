"""Typed dataset memory: navigation layer with provenance hooks.

The model-facing memory is not evidence. It helps the answerer choose files and
tools, while checked claims still come from chunks, tables, graph atoms or code
calculations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.rag_config import rag_meta_db_path

TYPED_MEMORY_SCHEMA = "dataset_memory_v1"
FILE_CARD_SCHEMA = "file_card_v1"
EVIDENCE_ATOM_SCHEMA = "evidence_atom_v1"
DATASET_READER_SCHEMA_ID = "dataset_reader_map_v1"
DATASET_BRIEF_SCHEMA_ID = "dataset_brief_for_model_v1"

logger = logging.getLogger(__name__)

CONTENT_LAYER_LABELS = {
    "text": "текст",
    "graphics": "графика",
    "tables": "таблицы",
    "calculations": "расчёты",
    "technical_docs": "техничка",
    "drawings": "чертежи",
    "cad_bim": "BIM/CAD",
    "normative": "нормы",
    "estimate": "сметы",
}

_TABLE_EXTS = {".xls", ".xlsx", ".xlsm", ".csv"}
_CAD_EXTS = {".dwg", ".dxf", ".ifc", ".ifczip", ".rvt", ".rfa", ".nwc"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
_DRAWING_MARKS = {
    "ар", "ас", "кр", "кж", "км", "кмд", "ов", "вк", "нвк", "эом", "эм", "сс", "апс", "соуэ",
    "пзу", "гп", "ios", "иос",
}
_TECH_RE = re.compile(
    r"(паспорт|руководств|инструкц|техническ|технич|ту\b|задани[ея]|пояснительн|пз\b|состав\s+проекта)",
    re.I,
)
_CALC_RE = re.compile(r"(расчет|расч[её]т|калькуляц|лср|кац|баланс|формул|смет|стоимост|итого)", re.I)
_SPEC_RE = re.compile(r"(спецификац|ведомост|вор\b|оборудован|материал|таблиц)", re.I)
_NORM_RE = re.compile(r"(гост|сп\s*\d|снип|санпин|гэсн|фер|тер|норматив|свод\s+правил)", re.I)
_RUNNING_READER_TASKS: set[str] = set()

DATASET_READER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "corpus_kind",
        "reader_summary",
        "where_to_look",
        "file_roles",
        "known_gaps",
        "answer_guidance",
        "confidence",
    ],
    "properties": {
        "schema": {"type": "string", "enum": [DATASET_READER_SCHEMA_ID]},
        "corpus_kind": {
            "type": "string",
            "enum": ["project", "normative", "estimate", "technical_catalog", "mixed", "unknown"],
        },
        "reader_summary": {"type": "string"},
        "where_to_look": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["question_type", "target_files", "reason"],
                "properties": {
                    "question_type": {"type": "string"},
                    "target_files": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
                    "reason": {"type": "string"},
                },
            },
            "maxItems": 16,
        },
        "file_roles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["file_name", "role", "what_inside", "confidence"],
                "properties": {
                    "file_name": {"type": "string"},
                    "role": {"type": "string"},
                    "what_inside": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
            "maxItems": 40,
        },
        "known_gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "answer_guidance": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def _connect(meta_db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(meta_db_path or rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    ensure_typed_memory_schema(conn)
    return conn


def ensure_typed_memory_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            content_signature TEXT NOT NULL,
            document_count INTEGER NOT NULL DEFAULT 0,
            indexed_count INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,
            UNIQUE(dataset_id, revision_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_memory (
            dataset_id TEXT PRIMARY KEY,
            revision_id TEXT NOT NULL,
            schema TEXT NOT NULL,
            memory_json TEXT NOT NULL,
            reader_status TEXT NOT NULL DEFAULT 'bootstrap',
            is_evidence INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_kind TEXT NOT NULL DEFAULT 'document',
            content_layers_json TEXT NOT NULL DEFAULT '[]',
            document_role TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            key_entities_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0.5,
            provenance_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL,
            UNIQUE(dataset_id, revision_id, file_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_atoms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            file_name TEXT NOT NULL,
            atom_kind TEXT NOT NULL,
            value_text TEXT NOT NULL DEFAULT '',
            value_num REAL,
            unit TEXT NOT NULL DEFAULT '',
            entity_refs_json TEXT NOT NULL DEFAULT '[]',
            source_ref TEXT NOT NULL DEFAULT '',
            provenance_json TEXT NOT NULL DEFAULT '{}',
            confidence REAL NOT NULL DEFAULT 0.5,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_cards_dataset ON file_cards(dataset_id, revision_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atoms_dataset ON evidence_atoms(dataset_id, revision_id)")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _documents(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if not columns:
        return []

    def _expr(name: str, default: str = "''") -> str:
        return f"COALESCE({name}, {default})" if name in columns else default

    rows = conn.execute(
        f"""
        SELECT dataset_id, file_name, status,
               {_expr("chunk_count", "0")} AS chunk_count,
               {_expr("doc_type")} AS doc_type,
               {_expr("content_type")} AS content_type,
               {_expr("domain")} AS domain,
               {_expr("route_dataset")} AS route_dataset,
               {_expr("pipeline")} AS pipeline,
               {_expr("source_path")} AS source_path
        FROM documents
        WHERE dataset_id=?
        ORDER BY file_name
        """,
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _content_signature(docs: list[dict[str, Any]]) -> str:
    payload = [
        {
            "file_name": d.get("file_name", ""),
            "status": d.get("status", ""),
            "chunk_count": int(d.get("chunk_count") or 0),
            "doc_type": d.get("doc_type", ""),
            "content_type": d.get("content_type", ""),
            "pipeline": d.get("pipeline", ""),
        }
        for d in docs
    ]
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()[:16]


def _add(layers: list[str], *items: str) -> None:
    for item in items:
        if item and item not in layers:
            layers.append(item)


def infer_file_typing(doc: dict[str, Any]) -> dict[str, Any]:
    """Multi-label file typing from current metadata and file naming signals."""
    file_name = str(doc.get("file_name") or "")
    name = Path(file_name).name
    low = file_name.casefold().replace("ё", "е")
    ext = Path(name).suffix.lower()
    doc_type = str(doc.get("doc_type") or "").upper()
    content_type = str(doc.get("content_type") or "").lower()
    domain = str(doc.get("domain") or "").upper()
    pipeline = str(doc.get("pipeline") or "").lower()
    layers: list[str] = []

    if ext in _TABLE_EXTS or content_type == "table" or doc_type in {"TABLE", "SPEC", "KS2"}:
        _add(layers, "tables")
    if ext in _CAD_EXTS or content_type == "cad_bim" or doc_type == "CAD_BIM" or domain == "CAD_BIM":
        _add(layers, "cad_bim", "graphics")
    if ext in _IMAGE_EXTS or content_type == "scan":
        _add(layers, "graphics")
    if ext == ".pdf" or "markdown_pdf_tables" in pipeline:
        _add(layers, "text")
        if content_type in {"mixed", "scan"}:
            _add(layers, "graphics")
    if ext in {".doc", ".docx", ".txt", ".md"} or content_type in {"text", "mixed", "email"}:
        _add(layers, "text")
    if doc_type == "NORMATIVE" or domain.startswith("NTD_") or _NORM_RE.search(low):
        _add(layers, "normative", "text")
    if doc_type == "SMETA" or "SMETA" in domain or _CALC_RE.search(low):
        _add(layers, "calculations", "estimate")
    if _SPEC_RE.search(low):
        _add(layers, "tables", "technical_docs")
    if _TECH_RE.search(low):
        _add(layers, "technical_docs", "text")
    if any(mark in low.split("/")[-1].replace("_", " ").replace("-", " ").split() for mark in _DRAWING_MARKS):
        _add(layers, "drawings", "graphics", "technical_docs")
    if not layers:
        _add(layers, "text")

    if "cad_bim" in layers:
        file_kind = "model_or_cad"
    elif "estimate" in layers:
        file_kind = "estimate"
    elif "normative" in layers:
        file_kind = "normative"
    elif "drawings" in layers:
        file_kind = "drawing_set"
    elif "tables" in layers and layers == ["tables"]:
        file_kind = "table"
    elif "technical_docs" in layers:
        file_kind = "technical_document"
    else:
        file_kind = "document"

    role = _document_role(low, layers, doc_type)
    return {
        "file_kind": file_kind,
        "content_layers": layers,
        "content_layer_labels": [CONTENT_LAYER_LABELS.get(layer, layer) for layer in layers],
        "document_role": role,
        "source_granularity": _source_granularity(layers),
        "confidence": 0.78 if doc_type or content_type else 0.58,
        "classified_by": "metadata_name_bootstrap",
    }


def _document_role(low_name: str, layers: list[str], doc_type: str) -> str:
    if "состав" in low_name and "проект" in low_name:
        return "состав проекта"
    if "пояснительн" in low_name or re.search(r"(^|[/_\-\s])пз($|[/_\-\s.])", low_name):
        return "пояснительная записка"
    if "задани" in low_name and "проект" in low_name:
        return "задание на проектирование"
    if "спецификац" in low_name:
        return "спецификация"
    if "ведомост" in low_name or "вор" in low_name:
        return "ведомость"
    if doc_type == "NORMATIVE":
        return "нормативный документ"
    if "cad_bim" in layers:
        return "модель/графика"
    if "estimate" in layers:
        return "сметный расчёт"
    if "drawings" in layers:
        return "чертёжный комплект"
    return "документ"


def _source_granularity(layers: list[str]) -> str:
    if "cad_bim" in layers:
        return "element_property"
    if "tables" in layers or "calculations" in layers:
        return "table_row_or_cell"
    if "drawings" in layers or "graphics" in layers:
        return "page_region"
    return "chunk"


def chunk_payload_typing(file_name: str, route_metadata: dict[str, Any] | None, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Typed metadata for Qdrant/lexical payloads."""
    doc = dict(route_metadata or {})
    doc["file_name"] = file_name
    payload = payload or {}
    if payload.get("type") == "table_row":
        doc["content_type"] = "table"
    typing = infer_file_typing(doc)
    source_granularity = typing["source_granularity"]
    if payload.get("type") == "table_row":
        source_granularity = "table_row"
    elif payload.get("mail_node_kind"):
        source_granularity = "message_part"
    return {
        "file_kind": typing["file_kind"],
        "content_layers": typing["content_layers"],
        "content_layer_labels": typing["content_layer_labels"],
        "document_role": typing["document_role"],
        "source_granularity": source_granularity,
        "typed_by": typing["classified_by"],
    }


def _file_summary(doc: dict[str, Any], typing: dict[str, Any]) -> str:
    labels = ", ".join(typing.get("content_layer_labels") or [])
    role = typing.get("document_role") or "документ"
    chunks = int(doc.get("chunk_count") or 0)
    status = str(doc.get("status") or "")
    return f"{role}; слои: {labels}; статус индекса {status}; чанков {chunks}"


def build_typed_dataset_memory(
    dataset_id: str,
    *,
    force: bool = False,
    meta_db_path: str | None = None,
) -> dict[str, Any]:
    """Build/update typed memory and file cards. No reindex, no vector writes."""
    now = time.time()
    with _connect(meta_db_path) as conn:
        docs = _documents(conn, dataset_id)
        signature = _content_signature(docs)
        revision_id = f"rev-{signature}"
        existing = conn.execute(
            "SELECT memory_json FROM dataset_memory WHERE dataset_id=? AND revision_id=?",
            (dataset_id, revision_id),
        ).fetchone()
        if existing and not force:
            return _loads(existing["memory_json"], {})

        indexed_count = sum(1 for d in docs if str(d.get("status") or "") == "INDEXED")
        chunk_count = sum(int(d.get("chunk_count") or 0) for d in docs)
        conn.execute(
            """
            INSERT OR IGNORE INTO dataset_revisions
                (dataset_id, revision_id, content_signature, document_count, indexed_count, chunk_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (dataset_id, revision_id, signature, len(docs), indexed_count, chunk_count, now),
        )

        cards = []
        by_layer: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        roles: dict[str, int] = {}
        for doc in docs:
            typing = infer_file_typing(doc)
            for layer in typing["content_layers"]:
                by_layer[layer] = by_layer.get(layer, 0) + 1
            by_kind[typing["file_kind"]] = by_kind.get(typing["file_kind"], 0) + 1
            role = typing["document_role"]
            roles[role] = roles.get(role, 0) + 1
            card = {
                "schema": FILE_CARD_SCHEMA,
                "dataset_id": dataset_id,
                "revision_id": revision_id,
                "file_name": str(doc.get("file_name") or ""),
                "status": str(doc.get("status") or ""),
                "chunk_count": int(doc.get("chunk_count") or 0),
                "file_kind": typing["file_kind"],
                "content_layers": typing["content_layers"],
                "content_layer_labels": typing["content_layer_labels"],
                "document_role": role,
                "summary": _file_summary(doc, typing),
                "key_entities": [],
                "confidence": typing["confidence"],
                "provenance": {
                    "source": "metadb.documents",
                    "classified_by": typing["classified_by"],
                    "doc_type": str(doc.get("doc_type") or ""),
                    "content_type": str(doc.get("content_type") or ""),
                    "domain": str(doc.get("domain") or ""),
                    "pipeline": str(doc.get("pipeline") or ""),
                },
            }
            cards.append(card)
            conn.execute(
                """
                INSERT INTO file_cards
                    (dataset_id, revision_id, file_name, file_kind, content_layers_json, document_role,
                     summary, key_entities_json, confidence, provenance_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dataset_id, revision_id, file_name) DO UPDATE SET
                    file_kind=excluded.file_kind,
                    content_layers_json=excluded.content_layers_json,
                    document_role=excluded.document_role,
                    summary=excluded.summary,
                    key_entities_json=excluded.key_entities_json,
                    confidence=excluded.confidence,
                    provenance_json=excluded.provenance_json,
                    updated_at=excluded.updated_at
                """,
                (
                    dataset_id,
                    revision_id,
                    card["file_name"],
                    card["file_kind"],
                    _json(card["content_layers"]),
                    card["document_role"],
                    card["summary"],
                    _json(card["key_entities"]),
                    card["confidence"],
                    _json(card["provenance"]),
                    now,
                ),
            )

        memory = {
            "schema": TYPED_MEMORY_SCHEMA,
            "dataset_id": dataset_id,
            "revision_id": revision_id,
            "context_role": "navigation",
            "is_evidence": False,
            "reader_status": "bootstrap",
            "reader_note": (
                "Typed memory is a navigation map. Facts in final answers must still come "
                "from retrieved chunks, table rows, graph atoms or calculation services."
            ),
            "document_count": len(docs),
            "indexed_count": indexed_count,
            "chunk_count": chunk_count,
            "data_layers": [
                {"id": layer, "label": CONTENT_LAYER_LABELS.get(layer, layer), "files": count}
                for layer, count in sorted(by_layer.items(), key=lambda item: (-item[1], item[0]))
            ],
            "file_kinds": [
                {"id": kind, "files": count}
                for kind, count in sorted(by_kind.items(), key=lambda item: (-item[1], item[0]))
            ],
            "document_roles": [
                {"role": role, "files": count}
                for role, count in sorted(roles.items(), key=lambda item: (-item[1], item[0]))[:20]
            ],
            "important_files": _important_files(cards),
            "file_cards": cards[:500],
            "known_gaps": _known_gaps(docs, by_layer),
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO dataset_memory(dataset_id, revision_id, schema, memory_json, reader_status, is_evidence, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                revision_id=excluded.revision_id,
                schema=excluded.schema,
                memory_json=excluded.memory_json,
                reader_status=excluded.reader_status,
                is_evidence=0,
                updated_at=excluded.updated_at
            """,
            (dataset_id, revision_id, TYPED_MEMORY_SCHEMA, _json(memory), "bootstrap", now),
        )
        conn.commit()
        return memory


def _important_files(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority_weights = {
        "состав проекта": 100,
        "пояснительная записка": 95,
        "задание на проектирование": 90,
        "ведомость": 72,
        "спецификация": 70,
        "нормативный документ": 55,
        "чертёжный комплект": 50,
        "сметный расчёт": 40,
    }
    ranked = []
    for card in cards:
        role = str(card.get("document_role") or "")
        score = max((weight for term, weight in priority_weights.items() if term in role), default=0)
        score += min(4, int(card.get("chunk_count") or 0) // 250)
        if score:
            ranked.append((score, card))
    ranked.sort(key=lambda item: (-item[0], item[1].get("file_name", "")))
    return [
        {
            "file_name": card["file_name"],
            "document_role": card["document_role"],
            "content_layers": card["content_layers"],
            "summary": card["summary"],
        }
        for _score, card in ranked[:24]
    ]


def _known_gaps(docs: list[dict[str, Any]], by_layer: dict[str, int]) -> list[str]:
    gaps: list[str] = []
    if not docs:
        gaps.append("В датасете нет документов в MetaDB.")
    pending = sum(1 for d in docs if str(d.get("status") or "") == "PENDING")
    errors = sum(1 for d in docs if str(d.get("status") or "") == "ERROR")
    if pending:
        gaps.append(f"{pending} файлов ещё ожидают индексации.")
    if errors:
        gaps.append(f"{errors} файлов с ошибкой индексации.")
    if not by_layer.get("tables"):
        gaps.append("Табличный слой не обнаружен; числовые сводки могут требовать чтения PDF/DOCX.")
    return gaps


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _reader_context(
    memory: dict[str, Any],
    *,
    file_limit: int | None = None,
    char_limit: int | None = None,
) -> str:
    if file_limit is None:
        file_limit = _env_int("LES_DATASET_READER_FILE_LIMIT", 240, minimum=20)
    if char_limit is None:
        char_limit = _env_int("LES_DATASET_READER_CONTEXT_CHARS", 64000, minimum=8000)
    important_names = {str(item.get("file_name") or "") for item in memory.get("important_files") or []}
    cards = list(memory.get("file_cards") or [])
    cards.sort(
        key=lambda card: (
            0 if str(card.get("file_name") or "") in important_names else 1,
            -int(card.get("chunk_count") or 0),
            str(card.get("file_name") or ""),
        )
    )
    payload = {
        "schema": "dataset_reader_input_v1",
        "dataset_id": memory.get("dataset_id"),
        "revision_id": memory.get("revision_id"),
        "document_count": memory.get("document_count", 0),
        "indexed_count": memory.get("indexed_count", 0),
        "chunk_count": memory.get("chunk_count", 0),
        "data_layers": memory.get("data_layers") or [],
        "file_kinds": memory.get("file_kinds") or [],
        "document_roles": memory.get("document_roles") or [],
        "important_files": memory.get("important_files") or [],
        "known_gaps": memory.get("known_gaps") or [],
        "file_cards_scope": {
            "included": min(len(cards), file_limit),
            "total": len(cards),
            "selection": (
                "important files first, then indexed/chunk-rich files; use as navigation, "
                "not as proof that omitted files do not exist"
            ),
        },
        "file_cards": [
            {
                "file_name": card.get("file_name"),
                "status": card.get("status"),
                "chunk_count": card.get("chunk_count", 0),
                "file_kind": card.get("file_kind"),
                "content_layers": card.get("content_layers") or [],
                "document_role": card.get("document_role"),
                "summary": card.get("summary"),
            }
            for card in cards[:file_limit]
        ],
    }
    text = _json(payload)
    if len(text) > char_limit:
        return text[:char_limit] + "\n...TRUNCATED..."
    return text


def _reader_instruction() -> str:
    return (
        "Ты reader-pass Л.Е.С.: изучаешь карту датасета и составляешь навигационную память. "
        "Это НЕ evidence и НЕ финальный ответ пользователю. Не выдумывай факты, которых нет во входе. "
        "Определи тип корпуса: проект, нормы, сметы, техничка, смешанный корпус или неизвестно. "
        "Укажи, какие файлы открывать для широких вопросов: паспорт объекта, состав проекта, ТЭП, "
        "инженерные разделы, сметы, спецификации, нормы. Если корпус похож на набор норм, не описывай его "
        "как строительный объект. Выбери 10-30 конкретных file_roles из имён, которые есть во входе. "
        "Не добавляй в known_gaps фразу о том, что file_cards/file list ограничен или выбран частично: "
        "это нормальная навигационная выборка, а не отсутствие данных. Если для широкого вопроса файл "
        "виден в карте, советуй добрать его точечно, а не писать «данных нет». Верни только JSON по схеме."
    )


async def _run_reader_extraction(schema: dict[str, Any], instruction: str, context: str, *, max_attempts: int):
    from proxy.services.extract_service import run_structured_extraction

    return await run_structured_extraction(
        schema,
        instruction,
        context,
        max_attempts=max_attempts,
    )


def _store_reader_update(
    dataset_id: str,
    *,
    revision_id: str,
    status: str,
    updates: dict[str, Any],
    meta_db_path: str | None = None,
) -> dict[str, Any]:
    now = time.time()
    with _connect(meta_db_path) as conn:
        row = conn.execute(
            "SELECT memory_json FROM dataset_memory WHERE dataset_id=? AND revision_id=?",
            (dataset_id, revision_id),
        ).fetchone()
        memory = _loads(row["memory_json"], {}) if row else {}
        memory.update(updates)
        memory["reader_status"] = status
        memory["updated_at"] = now
        conn.execute(
            """
            UPDATE dataset_memory
            SET memory_json=?, reader_status=?, updated_at=?
            WHERE dataset_id=? AND revision_id=?
            """,
            (_json(memory), status, now, dataset_id, revision_id),
        )
        conn.commit()
        return memory


async def run_dataset_reader_pass(
    dataset_id: str,
    *,
    force: bool = False,
    meta_db_path: str | None = None,
    max_attempts: int = 2,
) -> dict[str, Any]:
    """Ask the active model to build a navigation map over typed memory.

    The result is stored as dataset memory, not evidence. Final answers must
    still retrieve chunks/tables/graph/calculations before asserting facts.
    """
    memory = await asyncio.to_thread(build_typed_dataset_memory, dataset_id, force=force, meta_db_path=meta_db_path)
    if memory.get("reader_status") == "model" and not force:
        return memory
    context = _reader_context(memory)
    result = await _run_reader_extraction(
        DATASET_READER_SCHEMA,
        _reader_instruction(),
        context,
        max_attempts=max_attempts,
    )
    revision_id = str(memory.get("revision_id") or "")
    if result.ok and isinstance(result.data, dict):
        return await asyncio.to_thread(
            _store_reader_update,
            dataset_id,
            revision_id=revision_id,
            status="model",
            updates={
                "reader_schema": DATASET_READER_SCHEMA_ID,
                "reader_output": result.data,
                "reader_errors": [],
                "reader_attempts": result.attempts,
                "reader_note": (
                    "Model reader output is navigation memory only. Evidence must be fetched from "
                    "chunks, tables, graph atoms or calculation services before final claims."
                ),
            },
            meta_db_path=meta_db_path,
        )
    return await asyncio.to_thread(
        _store_reader_update,
        dataset_id,
        revision_id=revision_id,
        status="model_failed",
        updates={
            "reader_schema": DATASET_READER_SCHEMA_ID,
            "reader_output": None,
            "reader_errors": list(result.errors or []),
            "reader_attempts": result.attempts,
        },
        meta_db_path=meta_db_path,
    )


def dataset_reader_after_parse_enabled() -> bool:
    return os.getenv("LES_DATASET_READER_AFTER_PARSE", "0").strip().lower() in {"1", "true", "yes", "on"}


def schedule_dataset_reader_pass(
    dataset_id: str,
    *,
    reason: str = "",
    force: bool = True,
    require_enabled: bool = True,
) -> dict[str, Any]:
    """Schedule a model reader pass on the current event loop, with per-process dedupe."""
    dataset_id = str(dataset_id)
    if require_enabled and not dataset_reader_after_parse_enabled():
        return {"scheduled": False, "reason": "disabled", "dataset_id": dataset_id}
    if dataset_id in _RUNNING_READER_TASKS:
        return {"scheduled": False, "reason": "already_running", "dataset_id": dataset_id}
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return {"scheduled": False, "reason": "no_event_loop", "dataset_id": dataset_id}

    _RUNNING_READER_TASKS.add(dataset_id)

    async def _runner() -> None:
        try:
            await run_dataset_reader_pass(dataset_id, force=force)
            logger.info("[dataset-reader] completed dataset=%s reason=%s", dataset_id, reason)
        except Exception:
            logger.exception("[dataset-reader] failed dataset=%s reason=%s", dataset_id, reason)
        finally:
            _RUNNING_READER_TASKS.discard(dataset_id)

    loop.create_task(_runner())
    return {"scheduled": True, "reason": reason or "manual", "dataset_id": dataset_id}


def get_typed_dataset_memory(dataset_id: str, *, meta_db_path: str | None = None) -> dict[str, Any]:
    with _connect(meta_db_path) as conn:
        row = conn.execute("SELECT memory_json FROM dataset_memory WHERE dataset_id=?", (dataset_id,)).fetchone()
        if row:
            return _loads(row["memory_json"], {})
    return build_typed_dataset_memory(dataset_id, meta_db_path=meta_db_path)


def latest_file_cards(dataset_ids: list[str], *, meta_db_path: str | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    if not dataset_ids:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with _connect(meta_db_path) as conn:
        qmarks = ",".join("?" * len(dataset_ids))
        rows = conn.execute(
            f"""
            SELECT fc.*
            FROM file_cards fc
            JOIN dataset_memory dm
              ON dm.dataset_id=fc.dataset_id AND dm.revision_id=fc.revision_id
            WHERE fc.dataset_id IN ({qmarks})
            """,
            [str(d) for d in dataset_ids],
        ).fetchall()
        for row in rows:
            card = dict(row)
            card["content_layers"] = _loads(card.pop("content_layers_json", "[]"), [])
            card["key_entities"] = _loads(card.pop("key_entities_json", "[]"), [])
            card["provenance"] = _loads(card.pop("provenance_json", "{}"), {})
            out[(str(card.get("dataset_id") or ""), str(card.get("file_name") or ""))] = card
    return out


def current_dataset_revision_id(dataset_id: str, *, meta_db_path: str | None = None) -> str:
    try:
        with _connect(meta_db_path) as conn:
            row = conn.execute(
                "SELECT revision_id FROM dataset_memory WHERE dataset_id=?",
                (str(dataset_id),),
            ).fetchone()
            return str(row["revision_id"] or "") if row else ""
    except Exception:
        return ""


def typed_memory_prompt_block(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return ""
    lines = [
        "КАРТА ДАТАСЕТА ЛЕС (навигация, не evidence):",
        "Используй эту карту, чтобы выбирать файлы/слои/инструменты. "
        "Факты и числа подтверждай источниками, таблицами, графом или расчётным кодом.",
    ]
    for memory in memories:
        if not memory:
            continue
        lines.append(
            f"\nДатасет {memory.get('dataset_id')}: "
            f"{memory.get('document_count', 0)} файлов, {memory.get('chunk_count', 0)} чанков."
        )
        layers = memory.get("data_layers") or []
        if layers:
            lines.append(
                "Слои: "
                + ", ".join(f"{x.get('label') or x.get('id')}×{x.get('files')}" for x in layers[:10])
            )
        important = memory.get("important_files") or []
        if important:
            lines.append("Ключевые файлы для широких вопросов:")
            for item in important[:12]:
                lines.append(f"- {item.get('file_name')} — {item.get('document_role')}")
        reader = memory.get("reader_output") if memory.get("reader_status") == "model" else None
        if isinstance(reader, dict):
            summary = str(reader.get("reader_summary") or "").strip()
            if summary:
                lines.append(f"Reader-pass: {summary[:700]}")
            where = reader.get("where_to_look") or []
            if where:
                lines.append("Reader-pass советует искать:")
                for item in where[:8]:
                    files = ", ".join(str(f) for f in (item.get("target_files") or [])[:5])
                    lines.append(f"- {item.get('question_type')}: {files} — {item.get('reason')}")
        gaps = memory.get("known_gaps") or []
        if gaps:
            lines.append("Ограничения карты: " + "; ".join(str(g) for g in gaps[:4]))
    return "\n".join(lines)


def _brief_join(items: list[str], *, limit: int = 8) -> str:
    values = [str(item or "").strip() for item in items if str(item or "").strip()]
    return ", ".join(values[:limit])


def _file_card_by_name(memory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(card.get("file_name") or ""): card
        for card in (memory.get("file_cards") or [])
        if str(card.get("file_name") or "")
    }


def _task_guidance(question: str) -> list[str]:
    q = (question or "").casefold().replace("ё", "е")
    guidance = []
    if re.search(r"(смет|стоимост|вор\b|лср|гэсн|рим|расцен|цена)", q):
        guidance.append(
            "Для сметы сначала найди ВОР/спецификации/ЛСР/таблицы объёмов, затем добирай нормы и цены; "
            "brief не заменяет строки источников и расчёт."
        )
    if re.search(r"(нормоконтрол|замечан|провер|гост|сп\s*\d|снип|требован)", q):
        guidance.append(
            "Для нормоконтроля сначала найди применимый раздел проекта и нормативный источник, "
            "потом формулируй замечание с пунктом/фрагментом."
        )
    if re.search(r"(расскажи|обзор|изучи|проект|объект|корпус|датасет|документац)", q):
        guidance.append(
            "Для широкого обзора открой паспортные документы, состав проекта и пояснительные записки; "
            "таблицы и чертежи используй как уточняющий слой."
        )
    if re.search(r"(таблиц|спецификац|ведомост|перечен|реестр|список)", q):
        guidance.append(
            "Для табличных вопросов ищи файлы со слоями tables/calculations и подтверждай числа строками таблиц."
        )
    return guidance


def dataset_brief_for_model(
    memories: list[dict[str, Any]],
    *,
    question: str = "",
    max_files: int = 14,
    max_chars: int = 7000,
) -> str:
    """Compact model-facing brief over dataset memory.

    The brief is deliberately model-first: it helps the model decide what to
    read next, but it is not evidence and does not choose conclusions.
    """
    clean_memories = [memory for memory in memories if memory]
    if not clean_memories:
        return ""
    lines = [
        "ПАСПОРТ ОБЛАСТИ ДЛЯ МОДЕЛИ (навигация, не источник фактов)",
        f"schema: {DATASET_BRIEF_SCHEMA_ID}",
        "Главное: модель и текущий промпт принимают профессиональное решение. "
        "Этот brief только помогает понять корпус и выбрать файлы. "
        "Факты, числа и выводы бери из найденных фрагментов документов, таблиц, графа или расчётной трассы.",
        "Не пересказывай пользователю этот brief, его schema и служебные названия; в видимом ответе говори как инженер.",
        "Связь с фрагментами: file_name из этого brief совпадает с doc_name/file_name в Qdrant и lexical_chunks; "
        "для проверки открывай конкретный файл через retrieval/doc_filter и ссылайся уже на найденный фрагмент.",
    ]
    task_guidance = _task_guidance(question)
    if task_guidance:
        lines.append("Маршрут под текущий вопрос:")
        lines.extend(f"- {item}" for item in task_guidance[:4])
    for memory in clean_memories:
        dataset_id = str(memory.get("dataset_id") or "")
        lines.append(
            f"\nОбласть {dataset_id}: файлов {memory.get('document_count', 0)}, "
            f"проиндексировано {memory.get('indexed_count', 0)}, чанков {memory.get('chunk_count', 0)}."
        )
        layers = memory.get("data_layers") or []
        if layers:
            lines.append(
                "Слои данных: "
                + ", ".join(f"{x.get('label') or x.get('id')} ({x.get('files')})" for x in layers[:10])
            )
        roles = memory.get("document_roles") or []
        if roles:
            lines.append(
                "Роли документов: "
                + ", ".join(f"{x.get('role')} ({x.get('files')})" for x in roles[:10])
            )
        cards_by_name = _file_card_by_name(memory)
        important = memory.get("important_files") or []
        if important:
            lines.append("Открывать в первую очередь:")
            for item in important[:max_files]:
                file_name = str(item.get("file_name") or "")
                card = cards_by_name.get(file_name, {})
                chunks = card.get("chunk_count")
                layers_text = _brief_join(list(item.get("content_layers") or card.get("content_layers") or []), limit=4)
                suffix = f"; чанков {chunks}" if chunks is not None else ""
                if layers_text:
                    suffix += f"; слои {layers_text}"
                lines.append(f"- {file_name} — {item.get('document_role') or card.get('document_role') or 'документ'}{suffix}")
        reader = memory.get("reader_output") if memory.get("reader_status") == "model" else None
        if isinstance(reader, dict):
            summary = str(reader.get("reader_summary") or "").strip()
            if summary:
                lines.append(f"Reader-pass модели: {summary[:700]}")
            where = reader.get("where_to_look") or []
            if where:
                lines.append("Куда смотреть по типам вопросов:")
                for item in where[:8]:
                    files = _brief_join([str(f) for f in (item.get("target_files") or [])], limit=5)
                    lines.append(f"- {item.get('question_type')}: {files} — {item.get('reason')}")
            answer_guidance = str(reader.get("answer_guidance") or "").strip()
            if answer_guidance:
                lines.append(f"Подсказка reader-pass: {answer_guidance[:500]}")
        gaps = [str(g) for g in (memory.get("known_gaps") or []) if str(g).strip()]
        if gaps:
            lines.append("Известные ограничения карты: " + "; ".join(gaps[:5]))
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars].rsplit("\n", 1)[0].rstrip() + "\n...BRIEF_TRUNCATED..."
    return text
