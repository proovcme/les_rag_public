"""W17.2 — хранилище типизированных рёбер графа знаний + детерминированный вывод.

Рёбра выводятся БЕЗ LLM (ADR-11): regex `[[вики]]`, regex НТД-кодов (СП/ГОСТ/СНиП),
regex Source ID BIM-элементов. У каждого ребра — метод извлечения, уровень
доверия (trusted/candidate) и provenance. Детерминированные рёбра доверенные
сразу; LLM-предложенные (позже) входят как candidate до заземления.

Таблица `les_edges` — в метабазе рядом с les_projects/les_notes/les_tasks.
"""
from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from backend.rag_config import rag_meta_db_path

# ── regex-экстракторы (переиспользуют идиомы существующих сервисов) ──

# [[вики-ссылка]] — цель резолвится позже (документ/норматив/задача/элемент/заметка).
_WIKI_RE = re.compile(r"\[\[\s*([^\]\[]+?)\s*\]\]")

# НТД-коды: СП NN.NNNNN[.YYYY], ГОСТ [Р] NNNNN-YYYY / NN.NNN-YYYY, СНиП …, СН/ВСН/РД.
_NTD_RE = re.compile(
    r"(?:ГОСТ\s+Р|ГОСТ|СНиП|СП|СН|ВСН|РД)\s*\d[\w.\-/]*",
    re.IGNORECASE,
)

# Source ID элемента BIM (та же идиома, что в cad_bim_highlight).
_SOURCE_ID_RE = re.compile(r"Source ID(?:\s*/\s*GlobalId)?\s*:\s*(\S+)", re.IGNORECASE)


def _dedup(seq: list[str]) -> list[str]:
    out: list[str] = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def extract_wiki_links(text: str) -> list[str]:
    return _dedup([m.group(1).strip() for m in _WIKI_RE.finditer(text or "")])


def extract_ntd_refs(text: str) -> list[str]:
    """Нормализованные коды НТД: верхний регистр, одиночные пробелы, без хвостовой
    пунктуации. «сп 7.13130.» → «СП 7.13130»."""
    refs = []
    for m in _NTD_RE.finditer(text or ""):
        code = re.sub(r"\s+", " ", m.group(0).strip()).upper().rstrip(".,;:)")
        code = code.replace("СНИП", "СНиП")  # каноничный регистр смешанного префикса
        refs.append(code)
    return _dedup(refs)


def extract_element_refs(text: str) -> list[str]:
    return _dedup([m.group(1).strip().rstrip(".,;:)") for m in _SOURCE_ID_RE.finditer(text or "")])


# ── хранилище ───────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_kind TEXT NOT NULL,
            src_id TEXT NOT NULL,
            dst_kind TEXT NOT NULL,
            dst_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            method TEXT NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'trusted',
            provenance TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(src_kind, src_id, dst_kind, dst_id, edge_type)
        )
        """
    )
    return conn


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def add_edge(
    src_kind: str, src_id: str, dst_kind: str, dst_id: str, edge_type: str,
    *, method: str, confidence: str = "trusted", provenance: str = "",
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO les_edges
               (src_kind, src_id, dst_kind, dst_id, edge_type, method, confidence, provenance, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (src_kind, str(src_id), dst_kind, str(dst_id), edge_type, method, confidence, provenance, _now()),
        )


def delete_src_edges(src_kind: str, src_id: str, method: str | None = None) -> int:
    """Удалить рёбра, исходящие из узла (для идемпотентной ре-деривации)."""
    with _connect() as conn:
        if method:
            cur = conn.execute(
                "DELETE FROM les_edges WHERE src_kind=? AND src_id=? AND method=?",
                (src_kind, str(src_id), method),
            )
        else:
            cur = conn.execute(
                "DELETE FROM les_edges WHERE src_kind=? AND src_id=?", (src_kind, str(src_id))
            )
        return cur.rowcount


def edges_for(kind: str, node_id: str) -> dict[str, list[dict[str, Any]]]:
    """Рёбра узла в обе стороны: исходящие (out) и входящие бэклинки (in)."""
    with _connect() as conn:
        out = conn.execute(
            "SELECT * FROM les_edges WHERE src_kind=? AND src_id=? ORDER BY edge_type, id",
            (kind, str(node_id)),
        ).fetchall()
        inc = conn.execute(
            "SELECT * FROM les_edges WHERE dst_kind=? AND dst_id=? ORDER BY edge_type, id",
            (kind, str(node_id)),
        ).fetchall()
    return {"out": [dict(r) for r in out], "in": [dict(r) for r in inc]}


def list_edges(limit: int = 500, method: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if method:
            rows = conn.execute(
                "SELECT * FROM les_edges WHERE method=? ORDER BY id DESC LIMIT ?",
                (method, min(limit, 5000)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM les_edges ORDER BY id DESC LIMIT ?", (min(limit, 5000),)
            ).fetchall()
        return [dict(r) for r in rows]


# ── детерминированный вывод рёбер из текста ──────────────────────────

def derive_edges_from_text(src_kind: str, src_id: str, text: str, *, provenance: str = "") -> list[dict[str, str]]:
    """Из текста заметки/задачи вывести типизированные рёбра (0 LLM) и сохранить.
    Идемпотентно: перед записью чистит прежние авто-рёбра этого узла (по методам).
    Возвращает список созданных рёбер (для лога/проверки)."""
    text = text or ""
    created: list[dict[str, str]] = []
    plan = (
        [("references_ntd", "ntd_code", "regex_ntd", c) for c in extract_ntd_refs(text)]
        + [("wiki_link", "wiki", "wikilink", w) for w in extract_wiki_links(text)]
        + [("mentions_element", "element", "bim_id", e) for e in extract_element_refs(text)]
    )
    # идемпотентность: убрать прежние авто-рёбра этих методов из узла
    for method in ("regex_ntd", "wikilink", "bim_id"):
        delete_src_edges(src_kind, src_id, method=method)
    for edge_type, dst_kind, method, dst_id in plan:
        add_edge(src_kind, src_id, dst_kind, dst_id, edge_type, method=method, provenance=provenance or src_kind)
        created.append({"edge_type": edge_type, "dst_kind": dst_kind, "dst_id": dst_id, "method": method})
    return created
