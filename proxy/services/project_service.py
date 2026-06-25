"""W17.1 — сущность объекта строительства + привязки (проектный режим ЛЕС).

ЛЕС работает в двух режимах: «от объекта» (ретрив/досье сужены к проекту) и
обычный RAG (без фильтра). Здесь — хаб-сущность `les_projects` и лёгкая
тег-таблица `les_project_links` (что относится к объекту). Всё детерминированно,
0 LLM (ADR-11). Таблицы — в метабазе рядом с les_notes/les_tasks/les_field_entries.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from backend.rag_config import rag_meta_db_path

# Доменные виды привязок (что можно отнести к объекту). Расширяется по мере волны.
LINK_KINDS = {"dataset", "cad_bim_import", "task", "field_zahvatka", "mail_thread", "note", "folder"}
PROJECT_STATUSES = {"active", "archived", "on_hold"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT NOT NULL DEFAULT '',
            address TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_project_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            ref TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, kind, ref)
        )
        """
    )
    return conn


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def create_project(name: str, code: str = "", address: str = "") -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Пустое имя объекта")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO les_projects(name, code, address, status, created_at) VALUES (?,?,?,?,?)",
            (name, (code or "").strip(), (address or "").strip(), "active", _now()),
        )
        pid = cur.lastrowid
    # get_project открывает новое соединение — читаем после коммита with-блока.
    return get_project(pid) or {}


def list_projects(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM les_projects ORDER BY status='archived', id DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()
        return [dict(r) for r in rows]


def get_project(project_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM les_projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            return None
        project = dict(row)
        project["links"] = list_links(project_id)
        return project


def set_project_status(project_id: int, status: str) -> dict[str, Any] | None:
    if status not in PROJECT_STATUSES:
        raise ValueError(f"status: {sorted(PROJECT_STATUSES)}")
    with _connect() as conn:
        conn.execute("UPDATE les_projects SET status=? WHERE id=?", (status, project_id))
    return get_project(project_id)


def delete_project(project_id: int) -> bool:
    with _connect() as conn:
        conn.execute("DELETE FROM les_project_links WHERE project_id=?", (project_id,))
        cur = conn.execute("DELETE FROM les_projects WHERE id=?", (project_id,))
        return cur.rowcount > 0


def link_entity(project_id: int, kind: str, ref: str) -> dict[str, Any]:
    if kind not in LINK_KINDS:
        raise ValueError(f"kind: {sorted(LINK_KINDS)}")
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("Пустой ref")
    with _connect() as conn:
        if conn.execute("SELECT 1 FROM les_projects WHERE id=?", (project_id,)).fetchone() is None:
            raise ValueError(f"Объект {project_id} не найден")
        conn.execute(
            "INSERT OR IGNORE INTO les_project_links(project_id, kind, ref, created_at) VALUES (?,?,?,?)",
            (project_id, kind, ref, _now()),
        )
        row = conn.execute(
            "SELECT * FROM les_project_links WHERE project_id=? AND kind=? AND ref=?",
            (project_id, kind, ref),
        ).fetchone()
        return dict(row) if row else {}


def unlink_entity(project_id: int, kind: str, ref: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM les_project_links WHERE project_id=? AND kind=? AND ref=?",
            (project_id, kind, (ref or "").strip()),
        )
        return cur.rowcount > 0


def list_links(project_id: int, kind: str | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM les_project_links WHERE project_id=? AND kind=? ORDER BY id",
                (project_id, kind),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM les_project_links WHERE project_id=? ORDER BY kind, id",
                (project_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def project_dataset_ids(project_id: int) -> list[str]:
    """Датасеты, привязанные к объекту — область ретрива в режиме проекта.
    Пусто → проект без своей области (chat не сужает, остаётся обычный RAG)."""
    return [link["ref"] for link in list_links(project_id, kind="dataset")]


def project_for_dataset(dataset_id: str) -> int:
    """Обратный поиск: к какому объекту привязан датасет (kind='dataset'). 0 — не привязан.

    Симметрия датасет↔проект: выбор ДАТАСЕТА несёт контекст своего объекта (LES.md) так же, как
    выбор ПРОЕКТА — проект это лишь именованная группа датасетов (ADR scope). Без этого режим
    датасета терял LES.md, который есть в режиме проекта."""
    if not dataset_id:
        return 0
    with _connect() as conn:
        row = conn.execute(
            "SELECT project_id FROM les_project_links WHERE kind='dataset' AND ref=? ORDER BY id LIMIT 1",
            (str(dataset_id),),
        ).fetchone()
    return int(row["project_id"]) if row else 0


def _datasets_in_scope(dataset_ids: list[str]) -> list[dict[str, Any]]:
    """Имена/счётчики привязанных датасетов из метабазы (нормативы в области)."""
    if not dataset_ids:
        return []
    out: list[dict[str, Any]] = []
    try:  # datasets/documents — таблицы RAG-бэкенда; в свежей метабазе их может не быть
        with _connect() as conn:
            qmarks = ",".join("?" * len(dataset_ids))
            rows = conn.execute(
                f"SELECT id, name, chunk_count FROM datasets WHERE id IN ({qmarks})", dataset_ids
            ).fetchall()
            for r in rows:
                try:
                    files = conn.execute(
                        "SELECT COUNT(*) FROM documents WHERE dataset_id=?", (r["id"],)
                    ).fetchone()[0]
                except Exception:
                    files = 0
                out.append({"id": r["id"], "name": r["name"], "files": files, "chunks": r["chunk_count"]})
    except Exception:
        # таблицы нет → вернём хотя бы id-привязки (имена подтянутся на живой системе)
        out = [{"id": did, "name": did, "files": 0, "chunks": 0} for did in dataset_ids]
    return out


def build_registry() -> dict[str, Any]:
    """Реестр проектов (общая карта): все объекты + папки + мета из LES.md. Без LLM."""
    import json
    import sqlite3

    le_meta: dict[int, dict] = {}
    try:  # мета из LES.md-контекста (таблица создаётся les_md_service)
        conn = sqlite3.connect(rag_meta_db_path())
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT project_id, meta_json FROM les_md_context").fetchall():
            try:
                le_meta[int(r["project_id"])] = json.loads(r["meta_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                pass
        conn.close()
    except sqlite3.OperationalError:
        pass

    out = []
    for p in list_projects(limit=500):
        pid = int(p["id"])
        meta = le_meta.get(pid, {})
        folders = [l["ref"] for l in list_links(pid, "folder")]
        out.append({
            "id": pid, "name": p.get("name"), "code": p.get("code") or meta.get("cipher"),
            "address": p.get("address") or meta.get("address"), "stage": meta.get("stage"),
            "status": p.get("status"), "folders": folders,
            "datasets": len(project_dataset_ids(pid)), "has_les_md": pid in le_meta,
        })
    return {"projects": out, "count": len(out)}


def build_dossier(project_id: int) -> dict[str, Any] | None:
    """W17.5 КАРТА ОБЪЕКТА: паспорт объекта одним собранным ответом — нормативы в
    области, решения/задачи, объёмы по захваткам, BIM, связи. Всё детерминированно
    (SQL + существующие сервисы), 0 LLM. PARA-корзины выводятся из статусов."""
    project = get_project(project_id)
    if project is None:
        return None
    by_kind: dict[str, list[str]] = {}
    for link in project.get("links", []):
        by_kind.setdefault(link["kind"], []).append(link["ref"])

    datasets = _datasets_in_scope(by_kind.get("dataset", []))

    # Оперативные данные. Прим.: задачи/объёмы/заметки пока глобальны (партиционирование
    # по объекту — рефайнмент); привязанные явно — в links_by_kind.
    from proxy.services.task_service import list_tasks
    from proxy.services.memory_service import list_notes
    from proxy.services.field_intake_service import aggregate_volumes
    from proxy.services.edge_service import list_edges

    # Q3: оперативные данные партиционированы по объекту — досье строго в рамках объекта.
    all_tasks = list_tasks("", 500, project_id=project_id)
    open_tasks = [t for t in all_tasks if t.get("status") in ("open", "in_progress")]
    closed = sum(1 for t in all_tasks if t.get("status") in ("done", "dropped", "closed"))

    try:
        vol_rows = aggregate_volumes(status="confirmed", project_id=project_id)
    except Exception:
        vol_rows = []
    vol_total = sum(float(r.get("total") or 0) for r in vol_rows)

    notes = list_notes(50, project_id=project_id)
    edges = list_edges(5000)

    # W17.4 — решения проекта (RFI-стиль), строго по объекту (Q3).
    try:
        from proxy.services.decision_service import list_decisions
        decisions = list_decisions(project_id=project_id, limit=50)
    except Exception:
        decisions = []

    bim = None
    try:
        from proxy.services.cad_bim_graph import graph_summary
        bim = graph_summary()
    except Exception:
        bim = None

    # W17.3 — онтология: хребет (своды), состояния CDE контейнеров, LBS-захватки.
    classification = None
    cde = None
    lbs: list[dict[str, Any]] = []
    try:
        from proxy.services.ontology_service import classification_backbone, cde_summary, lbs_hubs
        backbone = classification_backbone()
        classification = {
            "totals": backbone.get("totals", {}),
            "top_floors": [
                {"floor": f["floor"], "elements": f["elements"],
                 "top_systems": [s["system"] for s in f.get("systems", [])[:5]]}
                for f in backbone.get("floors", [])[:6]
            ],
        }
        cde = cde_summary(project_id)
        lbs = lbs_hubs(project_id=project_id)
    except Exception:
        pass

    return {
        "project": {k: project.get(k) for k in ("id", "name", "code", "address", "status", "created_at")},
        "datasets_in_scope": datasets,
        "links_by_kind": {k: len(v) for k, v in by_kind.items()},
        "open_tasks": [
            {"id": t.get("id"), "title": t.get("title"), "status": t.get("status")} for t in open_tasks[:50]
        ],
        "volumes": {
            "groups": len(vol_rows),
            "total": round(vol_total, 2),
            "by_position": [
                {"position": r.get("position"), "unit": r.get("unit"), "total": r.get("total")}
                for r in vol_rows[:20]
            ],
        },
        "notes_count": len(notes),
        "edges_count": len(edges),
        "decisions": [  # W17.4 — решения по объекту (последние)
            {"id": d.get("id"), "decision": d.get("decision"), "status": d.get("status"),
             "rationale": d.get("rationale")}
            for d in decisions[:20]
        ],
        "decisions_count": len(decisions),
        "bim": bim,
        "classification": classification,  # W17.3 хребет (своды по этажам/системам)
        "cde": cde,  # W17.3 контейнеры по состояниям WIP/Shared/Published/Archived
        "lbs": lbs,  # W17.3 захватки-хабы (своды журнала объёмов)
        # PARA-корзины из статусов (не ручные папки): активные задачи / нормативы / закрытое.
        "para": {"active": len(open_tasks), "resources": len(datasets), "archive": closed},
    }
