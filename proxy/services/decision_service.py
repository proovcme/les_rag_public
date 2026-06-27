"""W17.4 — слой решений проекта (DecisionRecord, RFI-стиль). 0 LLM (ADR-11).

Решение по объекту — структурированная запись (вопрос/решение/обоснование/статус/теги)
с веером типизированных рёбер в граф знаний (W17.2): `justified_by`→норматив,
`concerns`→элемент, `references`→[[вики]], `at`→захватка, `supersedes`→прежнее решение.
Рёбра выводятся детерминированно из текста (regex-экстракторы edge_service) — самое
ценное семейство «обоснование решения↔артефакт↔норматив» считается без LLM.

Таблица `les_decisions` — в метабазе; партиционирование по объекту (Q3, project_id).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from typing import Any

from backend.rag_config import rag_meta_db_path

logger = logging.getLogger(__name__)

DECISION_STATUSES = ("open", "decided", "superseded")

# «реши: …», «решение: …», «принято решение: …»
DECISION_CREATE_RE = re.compile(
    r"^\s*(?:реши|решени[ея]|принято\s+решение)\s*[:—-]\s*(?P<text>.{3,800})$",
    re.IGNORECASE | re.DOTALL,
)
# «решения», «какие решения», «решения по объекту»
DECISION_LIST_RE = re.compile(
    r"^\s*(?:какие\s+|покажи\s+)?решени[яй](?:\s+по\s+объекту)?\s*\??\s*$",
    re.IGNORECASE,
)
# хвост «обоснование: …» / «т.к. …» / «потому что …»
_RATIONALE_RE = re.compile(r"\s*(?:обоснование\s*[:—-]|т\.\s*к\.|потому\s+что)\s*(?P<r>.+)$", re.IGNORECASE | re.DOTALL)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL DEFAULT 0,
            question TEXT NOT NULL DEFAULT '',
            decision TEXT NOT NULL,
            rationale TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'decided',
            tags TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    return conn


def _now() -> float:
    return time.time()


def _derive_decision_edges(decision_id: int, question: str, decision: str, rationale: str, at: str = "") -> int:
    """Типизированный веер рёбер решения (0 LLM). Возвращает число созданных рёбер."""
    try:
        from proxy.services.edge_service import (
            add_edge, extract_ntd_refs, extract_wiki_links, extract_element_refs, delete_src_edges,
        )
    except Exception as err:  # граф недоступен — решение всё равно сохраняется
        logger.warning("[EDGES] decision#%s edges skipped: %s", decision_id, err)
        return 0

    sid = str(decision_id)
    # идемпотентность: убрать прежние авто-рёбра решения
    for method in ("regex_ntd", "wikilink", "bim_id", "explicit"):
        delete_src_edges("decision", sid, method=method)

    text_all = "\n".join((question or "", decision or "", rationale or ""))
    prov = f"decision#{decision_id}"
    n = 0
    # обоснование → норматив (justified_by) — самое ценное семейство
    for ntd in extract_ntd_refs(rationale + "\n" + decision):
        add_edge("decision", sid, "ntd_code", ntd, "justified_by", method="regex_ntd", provenance=prov)
        n += 1
    # решение касается элемента (concerns)
    for el in extract_element_refs(text_all):
        add_edge("decision", sid, "element", el, "concerns", method="bim_id", provenance=prov)
        n += 1
    # ссылки на документы/сущности (references) через [[вики]]
    for w in extract_wiki_links(text_all):
        add_edge("decision", sid, "wiki", w, "references", method="wikilink", provenance=prov)
        n += 1
    # привязка к захватке (at)
    if (at or "").strip():
        add_edge("decision", sid, "zahvatka", at.strip(), "at", method="explicit", provenance=prov)
        n += 1
    return n


def create_decision(
    decision: str, *, question: str = "", rationale: str = "", status: str = "decided",
    tags: str = "", project_id: int = 0, at: str = "",
) -> dict[str, Any]:
    decision = (decision or "").strip()
    if not decision:
        raise ValueError("Пустой текст решения")
    if status not in DECISION_STATUSES:
        raise ValueError(f"status: {list(DECISION_STATUSES)}")
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO les_decisions(project_id, question, decision, rationale, status, tags, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (int(project_id), question.strip(), decision, rationale.strip(), status, tags.strip(), now, now),
        )
        conn.commit()
        decision_id = cur.lastrowid
    edges = _derive_decision_edges(decision_id, question, decision, rationale, at)
    logger.info("[DECISION] #%s (%d рёбер): %s", decision_id, edges, decision[:80])
    return get_decision(decision_id)


def list_decisions(project_id: int | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    clauses, params = [], []
    if project_id is not None:
        clauses.append("project_id=?")
        params.append(int(project_id))
    if status:
        clauses.append("status=?")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM les_decisions{where} ORDER BY id DESC LIMIT ?", (*params, min(limit, 1000))
        ).fetchall()
    return [dict(r) for r in rows]


def get_decision(decision_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM les_decisions WHERE id=?", (decision_id,)).fetchone()
    if not row:
        return None
    record = dict(row)
    record["backlinks"] = _grouped_backlinks(decision_id)
    return record


def _grouped_backlinks(decision_id: int) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Бэклинки решения, сгруппированные по типу ребра (не плоский счётчик, W17.4)."""
    try:
        from proxy.services.edge_service import edges_for
    except Exception:
        return {"out": {}, "in": {}}
    raw = edges_for("decision", str(decision_id))
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {"out": {}, "in": {}}
    for direction in ("out", "in"):
        for e in raw.get(direction, []):
            grouped[direction].setdefault(e["edge_type"], []).append(e)
    return grouped


def update_status(decision_id: int, status: str) -> dict[str, Any] | None:
    if status not in DECISION_STATUSES:
        raise ValueError(f"status: {list(DECISION_STATUSES)}")
    with _connect() as conn:
        conn.execute("UPDATE les_decisions SET status=?, updated_at=? WHERE id=?", (status, _now(), decision_id))
        conn.commit()
    return get_decision(decision_id)


def supersede_decision(new_id: int, old_id: int) -> dict[str, Any] | None:
    """Новое решение заменяет прежнее: ребро `supersedes` + старое → status=superseded."""
    update_status(old_id, "superseded")
    try:
        from proxy.services.edge_service import add_edge
        add_edge("decision", str(new_id), "decision", str(old_id), "supersedes",
                 method="decision_revision", provenance=f"decision#{new_id}")
    except Exception:
        pass
    return get_decision(new_id)


def count_open(project_id: int | None = None) -> int:
    return len(list_decisions(project_id=project_id, status="open"))


def _format_decision_line(d: dict[str, Any]) -> str:
    marker = {"open": "◌", "decided": "●", "superseded": "⊘"}.get(d["status"], "·")
    just = d.get("backlinks", {}).get("out", {}).get("justified_by", [])
    tail = f" (обоснование: {', '.join(e['dst_id'] for e in just)})" if just else ""
    return f"{marker} #{d['id']} {d['decision'][:140]}{tail}"


def maybe_handle_decision_command(question: str, project_id: int = 0) -> dict[str, Any] | None:
    """Команды слоя решений из чата (ADR-11: regex+SQL, без LLM).
    «реши: <решение> обоснование: <…>» → запись + типизированные рёбра; «решения» → список."""
    text = question.strip()

    match = DECISION_LIST_RE.match(text)
    if match:
        items = list_decisions(project_id=project_id or None, limit=30)
        if not items:
            return {"answer": "Решений по объекту пока нет. Записать: «реши: …»",
                    "operation": "decisions_list", "count": 0}
        # подтянем сгруппированные рёбра для строк (justified_by)
        rich = [get_decision(d["id"]) or d for d in items]
        answer = "**Решения по объекту:**\n" + "\n".join(_format_decision_line(d) for d in rich)
        return {"answer": answer, "operation": "decisions_list", "count": len(items)}

    match = DECISION_CREATE_RE.match(text)
    if match:
        body = match.group("text").strip().rstrip(".")
        rationale = ""
        rmatch = _RATIONALE_RE.search(body)
        if rmatch:
            rationale = rmatch.group("r").strip()
            body = body[: rmatch.start()].strip(" ,;—-")
        rec = create_decision(body, rationale=rationale, project_id=project_id)
        edges = sum(len(v) for v in rec.get("backlinks", {}).get("out", {}).values())
        note = f" · {edges} связей в граф" if edges else ""
        return {
            "answer": f"● Решение #{rec['id']} записано{note}: {rec['decision'][:160]}",
            "operation": "decision_create",
            "count": 1,
            "decision_id": rec["id"],
        }

    return None
