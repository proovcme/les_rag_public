"""Persistent chat and dataset context memory for LES.

This layer is deterministic: it summarizes known SQLite metadata and chat
history into compact profiles. Profiles are prompt hints, not evidence.
Numbers, standards and final claims must still come from retrieved sources or
calculation services.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from backend.rag_config import rag_meta_db_path
from proxy.services.lexical_index_service import lexical_db_path

logger = logging.getLogger(__name__)

DATASET_PROFILE_FILE = "_les_dataset_profile.json"
PROFILE_SCHEMA = "context_memory_v1"
PROFILE_DEPTHS = {"metadata", "deep"}
DEEP_SAMPLE_ROWS = 240
DEEP_FRAGMENT_LIMIT = 10

_ASSUME_RE = re.compile(r"\b(ASSUME|допущен|принял[аи]?|считаем|предполож)", re.I)
_MISSING_RE = re.compile(r"\b(MISSING|не хватает|нужн[аоы]?|требуется|нет данных|нужен|нужна|нужны)", re.I)
_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.I)
_NORM_REF_RE = re.compile(
    r"\b(?:ГОСТ\s*Р?\s*[\d.\-]+|СП\s*\d+(?:\.\d+)*|СНиП\s*[\d.\-]+|ФЗ\s*[-№]?\s*\d+)\b",
    re.I,
)
_TABLE_SIGNAL_RE = re.compile(r"(\|.+\||\b(?:итого|ед\.?\s*изм|кол-во|количество|сумма|цена)\b)", re.I)
_STOPWORDS = frozenset(
    "какой какие каких что это есть если нужно надо можно через чтобы тогда потому "
    "пожалуйста сделай покажи проверь посчитай ответь весь всех очень для при или "
    "смета сметы проект объекта документ файл".split()
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    ensure_context_memory_schema(conn)
    return conn


def ensure_context_memory_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_chat_profiles (
            session_id TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL,
            turn_count INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_dataset_profiles (
            dataset_id TEXT PRIMARY KEY,
            profile_json TEXT NOT NULL,
            content_signature TEXT NOT NULL DEFAULT '',
            profile_path TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        )
        """
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _loads(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except Exception:
        return default


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(row)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.OperationalError:
        return set()


def _top_counts(values: list[str], *, limit: int = 8) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        key = (value or "").strip() or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return [
        {"value": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _keywords(texts: list[str], *, limit: int = 12) -> list[str]:
    counts: dict[str, int] = {}
    for text in texts:
        for word in _WORD_RE.findall(text or ""):
            low = word.lower()
            if low in _STOPWORDS or len(low) < 4:
                continue
            stem = low[:10]
            counts[stem] = counts.get(stem, 0) + 1
    return [word for word, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _safe_dataset_dir(dataset_id: str, storage_root: Path) -> Path:
    root = storage_root.resolve()
    target = (root / dataset_id).resolve()
    if root not in target.parents and target != root:
        raise ValueError("dataset_id escapes storage root")
    return target


def _dataset_row(conn: sqlite3.Connection, dataset_id: str) -> dict[str, Any]:
    if not _table_exists(conn, "datasets"):
        return {"id": dataset_id, "name": dataset_id}
    cols = _columns(conn, "datasets")
    wanted = [c for c in ("id", "name", "status", "chunk_count", "group_name", "sensitivity") if c in cols]
    if not wanted:
        return {"id": dataset_id, "name": dataset_id}
    row = conn.execute(
        f"SELECT {', '.join(wanted)} FROM datasets WHERE id=?", (dataset_id,)
    ).fetchone()
    return dict(row) if row else {"id": dataset_id, "name": dataset_id}


def _document_rows(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "documents"):
        return []
    cols = _columns(conn, "documents")
    wanted = [
        c
        for c in (
            "id",
            "dataset_id",
            "file_name",
            "status",
            "file_mtime",
            "file_size",
            "chunk_count",
            "doc_type",
            "domain",
            "route_dataset",
            "source_path",
        )
        if c in cols
    ]
    if not wanted:
        return []
    rows = conn.execute(
        f"SELECT {', '.join(wanted)} FROM documents WHERE dataset_id=? ORDER BY file_name",
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def dataset_signature(conn: sqlite3.Connection, dataset_id: str) -> str:
    payload = {"dataset": _dataset_row(conn, dataset_id), "documents": _document_rows(conn, dataset_id)}
    return hashlib.sha256(_json_text(payload).encode("utf-8")).hexdigest()[:16]


def _normalize_depth(depth: str | None) -> str:
    value = (depth or "metadata").strip().lower()
    return value if value in PROFILE_DEPTHS else "metadata"


def _lexical_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(lexical_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _lexical_signature(dataset_id: str) -> str:
    try:
        with _lexical_connect() as conn:
            if not _table_exists(conn, "lexical_chunks"):
                return "no_lexical"
            row = conn.execute(
                """
                SELECT COUNT(*) AS count_rows,
                       COALESCE(MAX(updated_at), 0) AS max_updated,
                       COALESCE(MAX(id), 0) AS max_id
                FROM lexical_chunks
                WHERE dataset_id=?
                """,
                (dataset_id,),
            ).fetchone()
            return _hash_text(_json_text(dict(row) if row else {}))
    except Exception as err:  # noqa: BLE001
        logger.warning("[CONTEXT_MEMORY] lexical signature skipped for %s: %s", dataset_id, err)
        return "lexical_unavailable"


def _content_signature(conn: sqlite3.Connection, dataset_id: str, *, depth: str) -> str:
    base = dataset_signature(conn, dataset_id)
    if depth != "deep":
        return base
    return _hash_text(f"{base}:{_lexical_signature(dataset_id)}:deep")


def _preview(text: str, *, limit: int = 260) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rsplit(" ", 1)[0].rstrip() + "..."


def _norm_refs(texts: list[str], *, limit: int = 20) -> list[str]:
    refs: dict[str, int] = {}
    for text in texts:
        for raw in _NORM_REF_RE.findall(text or ""):
            ref = " ".join(raw.upper().replace("  ", " ").split())
            refs[ref] = refs.get(ref, 0) + 1
    return [ref for ref, _count in sorted(refs.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _lexical_deep_profile(dataset_id: str) -> dict[str, Any]:
    """Bounded lexical scan for dataset passport. No source files, no LLM, no reindex."""
    try:
        with _lexical_connect() as conn:
            if not _table_exists(conn, "lexical_chunks"):
                return {"available": False, "reason": "lexical_chunks_missing"}
            total_row = conn.execute(
                "SELECT COUNT(*) AS n, COUNT(DISTINCT doc_name) AS docs "
                "FROM lexical_chunks WHERE dataset_id=?",
                (dataset_id,),
            ).fetchone()
            total = int(total_row["n"] or 0) if total_row else 0
            docs_count = int(total_row["docs"] or 0) if total_row else 0
            if total <= 0:
                return {"available": False, "reason": "no_lexical_chunks", "lexical_chunks": 0}

            doc_rows = conn.execute(
                """
                SELECT doc_name, COUNT(*) AS chunks
                FROM lexical_chunks
                WHERE dataset_id=?
                GROUP BY doc_name
                ORDER BY chunks DESC, doc_name ASC
                LIMIT 12
                """,
                (dataset_id,),
            ).fetchall()
            heading_rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(section_heading, ''), NULLIF(parent_heading, ''), '') AS heading,
                       COUNT(*) AS chunks
                FROM lexical_chunks
                WHERE dataset_id=? AND (section_heading <> '' OR parent_heading <> '')
                GROUP BY heading
                ORDER BY chunks DESC, heading ASC
                LIMIT 12
                """,
                (dataset_id,),
            ).fetchall()
            sample_rows = conn.execute(
                """
                SELECT doc_name, text, section_heading, parent_heading, context_kind, chunk_ord
                FROM lexical_chunks
                WHERE dataset_id=? AND COALESCE(text, '') <> ''
                ORDER BY doc_name ASC, COALESCE(chunk_ord, id) ASC
                LIMIT ?
                """,
                (dataset_id, DEEP_SAMPLE_ROWS),
            ).fetchall()
    except Exception as err:  # noqa: BLE001
        logger.warning("[CONTEXT_MEMORY] lexical deep profile skipped for %s: %s", dataset_id, err)
        return {"available": False, "reason": "lexical_read_error"}

    texts = [str(row["text"] or "") for row in sample_rows]
    fragments: list[dict[str, Any]] = []
    seen_docs: set[str] = set()
    table_signal = 0
    for row in sample_rows:
        text = str(row["text"] or "")
        if _TABLE_SIGNAL_RE.search(text):
            table_signal += 1
        doc = str(row["doc_name"] or "")
        if doc in seen_docs or len(fragments) >= DEEP_FRAGMENT_LIMIT:
            continue
        preview = _preview(text)
        if not preview:
            continue
        seen_docs.add(doc)
        fragments.append(
            {
                "doc_name": doc,
                "heading": str(row["section_heading"] or row["parent_heading"] or ""),
                "chunk_ord": row["chunk_ord"],
                "preview": preview,
            }
        )

    return {
        "available": True,
        "lexical_chunks": total,
        "lexical_docs": docs_count,
        "sampled_chunks": len(sample_rows),
        "top_documents": [dict(row) for row in doc_rows],
        "frequent_headings": [dict(row) for row in heading_rows if str(row["heading"] or "").strip()],
        "content_keywords": _keywords(texts, limit=20),
        "norm_refs": _norm_refs(texts + [str(row["doc_name"] or "") for row in doc_rows]),
        "table_signal_chunks": table_signal,
        "representative_fragments": fragments,
    }


def build_dataset_profile(
    dataset_id: str,
    *,
    dataset_name: str = "",
    storage_root: Path = Path("storage/datasets"),
    force: bool = False,
    depth: str = "metadata",
) -> dict[str, Any]:
    """Build or read a compact dataset profile and mirror it to a sidecar file."""
    dataset_id = (dataset_id or "").strip()
    if not dataset_id:
        raise ValueError("dataset_id is required")
    depth = _normalize_depth(depth)

    now = time.time()
    with _connect() as conn:
        signature = _content_signature(conn, dataset_id, depth=depth)
        stored = conn.execute(
            "SELECT profile_json, content_signature, profile_path, updated_at "
            "FROM les_dataset_profiles WHERE dataset_id=?",
            (dataset_id,),
        ).fetchone()
        if stored and not force and stored["content_signature"] == signature:
            profile = _loads(stored["profile_json"], {})
            if isinstance(profile, dict) and profile:
                profile.setdefault("profile_path", stored["profile_path"] or "")
                if profile.get("depth") == depth:
                    return profile
                return profile

        ds = _dataset_row(conn, dataset_id)
        docs = _document_rows(conn, dataset_id)
        name = dataset_name or str(ds.get("name") or dataset_id)
        file_names = [str(d.get("file_name") or "") for d in docs]
        sample_docs = sorted(
            docs,
            key=lambda d: (-(int(d.get("chunk_count") or 0)), str(d.get("file_name") or "")),
        )[:12]
        profile = {
            "schema": PROFILE_SCHEMA,
            "kind": "dataset_profile",
            "depth": depth,
            "dataset_id": dataset_id,
            "name": name,
            "status": str(ds.get("status") or ""),
            "group_name": str(ds.get("group_name") or ""),
            "sensitivity": str(ds.get("sensitivity") or ""),
            "document_count": len(docs),
            "chunk_count": int(ds.get("chunk_count") or sum(int(d.get("chunk_count") or 0) for d in docs)),
            "file_extensions": _top_counts([Path(f).suffix.lower() or "none" for f in file_names]),
            "document_types": _top_counts([str(d.get("doc_type") or "") for d in docs]),
            "domains": _top_counts([str(d.get("domain") or "") for d in docs]),
            "routes": _top_counts([str(d.get("route_dataset") or "") for d in docs]),
            "status_counts": _top_counts([str(d.get("status") or "") for d in docs]),
            "keywords": _keywords(file_names),
            "sample_files": [
                {
                    "file_name": str(d.get("file_name") or ""),
                    "status": str(d.get("status") or ""),
                    "chunks": int(d.get("chunk_count") or 0),
                    "doc_type": str(d.get("doc_type") or ""),
                }
                for d in sample_docs
            ],
            "coverage_note": (
                "Паспорт описывает индекс и файлы по метаданным. Это ускоряет выбор маршрута, "
                "но не является evidence для ответа."
            ),
            "content_signature": signature,
            "updated_at": now,
        }
        if depth == "deep":
            profile["deep"] = _lexical_deep_profile(dataset_id)

        profile_path = ""
        try:
            ds_dir = _safe_dataset_dir(dataset_id, storage_root)
            ds_dir.mkdir(parents=True, exist_ok=True)
            path = ds_dir / DATASET_PROFILE_FILE
            profile["profile_path"] = str(path)
            path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
            profile_path = str(path)
        except Exception as err:  # noqa: BLE001
            profile["profile_path"] = ""
            logger.warning("[CONTEXT_MEMORY] dataset profile sidecar skipped for %s: %s", dataset_id, err)

        conn.execute(
            """
            INSERT INTO les_dataset_profiles(dataset_id, profile_json, content_signature, profile_path, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                profile_json=excluded.profile_json,
                content_signature=excluded.content_signature,
                profile_path=excluded.profile_path,
                updated_at=excluded.updated_at
            """,
            (dataset_id, _json_text(profile), signature, profile_path, now),
        )
        conn.commit()
        return profile


def get_dataset_profile(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
    depth: str = "metadata",
) -> dict[str, Any]:
    return build_dataset_profile(dataset_id, storage_root=storage_root, force=False, depth=depth)


def _all_dataset_ids(conn: sqlite3.Connection) -> list[str]:
    if not _table_exists(conn, "datasets"):
        return []
    rows = conn.execute("SELECT id FROM datasets ORDER BY name, id").fetchall()
    return [str(row["id"]) for row in rows if str(row["id"] or "").strip()]


def warmup_dataset_profiles(
    *,
    dataset_ids: list[str] | None = None,
    storage_root: Path = Path("storage/datasets"),
    depth: str = "deep",
    force: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """Build dataset passports in batch. Safe no-reindex warmup."""
    depth = _normalize_depth(depth)
    with _connect() as conn:
        ids = [str(d).strip() for d in (dataset_ids or []) if str(d).strip()]
        if not ids:
            ids = _all_dataset_ids(conn)
    if limit and limit > 0:
        ids = ids[:limit]
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    started = time.time()
    for dataset_id in ids:
        try:
            profile = build_dataset_profile(
                dataset_id,
                storage_root=storage_root,
                depth=depth,
                force=force,
            )
            results.append(
                {
                    "dataset_id": dataset_id,
                    "name": profile.get("name", ""),
                    "depth": profile.get("depth", depth),
                    "document_count": profile.get("document_count", 0),
                    "chunk_count": profile.get("chunk_count", 0),
                    "lexical_chunks": (profile.get("deep") or {}).get("lexical_chunks", 0),
                    "profile_path": profile.get("profile_path", ""),
                }
            )
        except Exception as err:  # noqa: BLE001
            logger.warning("[CONTEXT_MEMORY] warmup failed for %s: %s", dataset_id, err)
            errors.append({"dataset_id": dataset_id, "error": str(err)})
    return {
        "status": "ok" if not errors else "partial",
        "depth": depth,
        "requested": len(ids),
        "built": len(results),
        "errors": errors,
        "elapsed_sec": round(time.time() - started, 3),
        "profiles": results,
    }


def _compact_lines(text: str, pattern: re.Pattern[str], *, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.strip("-* \t").split())
        if len(line) < 6 or not pattern.search(line):
            continue
        if line not in lines:
            lines.append(line[:220])
        if len(lines) >= limit:
            break
    return lines


def update_chat_profile(
    *,
    session_id: str | None,
    question: str,
    answer: str,
    crag_status: str,
    route: dict[str, Any] | None = None,
    requested_dataset_filter: str | None = None,
    effective_dataset_filter: str | None = None,
    resolved_dataset_ids: list[str] | None = None,
    resolved_dataset_names: list[str] | None = None,
    source_dataset_ids: list[str] | None = None,
    source_dataset_names: list[str] | None = None,
    success: int = 0,
) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if not sid:
        return None

    now = time.time()
    with _connect() as conn:
        row = conn.execute(
            "SELECT profile_json, turn_count FROM les_chat_profiles WHERE session_id=?", (sid,)
        ).fetchone()
        profile = _loads(row["profile_json"], {}) if row else {}
        if not isinstance(profile, dict):
            profile = {}
        route = route or {}
        turns = int(row["turn_count"] if row else 0) + 1
        datasets = [
            {"id": str(did), "name": str(name or did)}
            for did, name in zip(resolved_dataset_ids or [], resolved_dataset_names or [])
        ]
        source_datasets = [
            {"id": str(did), "name": str(name or did)}
            for did, name in zip(source_dataset_ids or [], source_dataset_names or [])
        ]
        assumptions = list(profile.get("assumptions") or [])
        blockers = list(profile.get("blockers") or [])
        for item in _compact_lines(answer, _ASSUME_RE):
            if item not in assumptions:
                assumptions.append(item)
        for item in _compact_lines(answer, _MISSING_RE):
            if item not in blockers:
                blockers.append(item)
        profile.update(
            {
                "schema": PROFILE_SCHEMA,
                "kind": "chat_profile",
                "session_id": sid,
                "turn_count": turns,
                "project_id": int(profile.get("project_id") or 0),
                "last_question": " ".join(str(question or "").split())[:500],
                "last_answer_preview": " ".join(str(answer or "").split())[:700],
                "last_status": crag_status,
                "last_success": int(bool(success)),
                "mode": str(route.get("channel") or route.get("profile", {}).get("channel") or ""),
                "route_reason": str(route.get("reason") or ""),
                "requested_dataset_filter": requested_dataset_filter or "",
                "effective_dataset_filter": effective_dataset_filter or "",
                "datasets": datasets,
                "source_datasets": source_datasets,
                "assumptions": assumptions[-12:],
                "blockers": blockers[-12:],
                "updated_at": now,
            }
        )
        conn.execute(
            """
            INSERT INTO les_chat_profiles(session_id, profile_json, turn_count, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                profile_json=excluded.profile_json,
                turn_count=excluded.turn_count,
                updated_at=excluded.updated_at
            """,
            (sid, _json_text(profile), turns, now),
        )
        conn.commit()
        return profile


def get_chat_profile(session_id: str) -> dict[str, Any] | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT profile_json FROM les_chat_profiles WHERE session_id=?", (sid,)
        ).fetchone()
    return _loads(row["profile_json"], {}) if row else None


def _dataset_profile_block(profile: dict[str, Any]) -> str:
    samples = ", ".join(item["file_name"] for item in profile.get("sample_files", [])[:6] if item.get("file_name"))
    doc_types = ", ".join(f"{x['value']}:{x['count']}" for x in profile.get("document_types", [])[:5])
    exts = ", ".join(f"{x['value']}:{x['count']}" for x in profile.get("file_extensions", [])[:5])
    keywords = ", ".join(profile.get("keywords", [])[:10])
    parts = [
        f"- {profile.get('name') or profile.get('dataset_id')} ({profile.get('dataset_id')}): "
        f"{profile.get('document_count', 0)} файлов, {profile.get('chunk_count', 0)} чанков",
    ]
    if doc_types:
        parts.append(f"  типы: {doc_types}")
    if exts:
        parts.append(f"  расширения: {exts}")
    if keywords:
        parts.append(f"  ключевые слова по именам файлов: {keywords}")
    deep = profile.get("deep") or {}
    if deep.get("available"):
        content_keywords = ", ".join(deep.get("content_keywords", [])[:10])
        norm_refs = ", ".join(deep.get("norm_refs", [])[:8])
        if content_keywords:
            parts.append(f"  ключевые слова по содержанию: {content_keywords}")
        if norm_refs:
            parts.append(f"  частые нормативные ссылки: {norm_refs}")
    if samples:
        parts.append(f"  примеры файлов: {samples}")
    return "\n".join(parts)


def build_context_memory_block(
    *,
    session_id: str | None = None,
    dataset_ids: list[str] | None = None,
    dataset_names: list[str] | None = None,
    storage_root: Path = Path("storage/datasets"),
    max_datasets: int = 5,
) -> str:
    """Return a compact prompt block with chat and dataset profiles."""
    parts: list[str] = []
    chat_profile = get_chat_profile(session_id or "") if session_id else None
    if chat_profile:
        chat_lines = [
            f"Паспорт чата: ходов {chat_profile.get('turn_count', 0)}, "
            f"последний статус {chat_profile.get('last_status') or 'unknown'}.",
        ]
        if chat_profile.get("effective_dataset_filter"):
            chat_lines.append(f"Текущий фильтр: {chat_profile['effective_dataset_filter']}.")
        if chat_profile.get("assumptions"):
            chat_lines.append("Принятые допущения: " + "; ".join(chat_profile["assumptions"][-5:]))
        if chat_profile.get("blockers"):
            chat_lines.append("Нехватки/блокеры: " + "; ".join(chat_profile["blockers"][-5:]))
        parts.append("\n".join(chat_lines))

    dataset_lines: list[str] = []
    names = dataset_names or []
    scoped_ids = list(dataset_ids or [])
    for idx, dataset_id in enumerate(scoped_ids[:max(0, max_datasets)]):
        try:
            profile = build_dataset_profile(
                dataset_id,
                dataset_name=names[idx] if idx < len(names) else "",
                storage_root=storage_root,
                depth="deep",
            )
            dataset_lines.append(_dataset_profile_block(profile))
        except Exception as err:  # noqa: BLE001
            logger.warning("[CONTEXT_MEMORY] dataset profile failed for %s: %s", dataset_id, err)
    if max_datasets and len(scoped_ids) > max_datasets:
        dataset_lines.append(f"- ...ещё {len(scoped_ids) - max_datasets} датасетов не включены в prompt-паспорт")
    if dataset_lines:
        parts.append("Паспорта выбранных датасетов:\n" + "\n".join(dataset_lines))

    if not parts:
        return ""
    return (
        "Память контекста (паспорт чата/датасетов; это навигация и фон, НЕ evidence):\n"
        + "\n\n".join(parts)
    )
