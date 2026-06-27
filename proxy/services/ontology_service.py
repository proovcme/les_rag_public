"""W17.3 — доменная онтология: классификационный хребет + состояния CDE.

Два детерминированных слоя «второго мозга» стройки (0 LLM, ADR-11):

1. **Классификационный хребет Element→System→Space→Floor** поверх `cad_bim_elements`
   (W6.1/W6.7): навигация «элементы системы вентиляции на этаже 3» считается SQL +
   словарём категория→система, без LLM. Система берётся из системного свойства
   элемента, иначе из словарного маппинга категории, иначе «Прочее».

2. **Состояния документов/моделей (Container)** в координатах ISO 19650 CDE —
   WIP/Shared/Published/Archived + ревизии/`supersedes`. Таблица `les_containers`
   в метабазе; переходы — детерминированный конечный автомат; `supersedes` пишет и
   типизированное ребро в `les_edges` (W17.2), provenance сохраняется.

Захватка-хаб (LBS) — лёгкая свёрстка журнала объёмов (W8) по захваткам.
Всё детерминированно: приёмка карты — без единого LLM-вызова.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from backend.rag_config import rag_meta_db_path
from proxy.services.cad_bim_graph import CAD_BIM_DB_PATH, init_graph_db

# ── классификационный хребет: словарь категория → система ─────────────
# Детерминированный маппинг (Uniclass-style семейства систем). Сопоставление —
# по вхождению подстроки в категорию/тип/семейство элемента (нижний регистр).
CATEGORY_SYSTEM: list[tuple[tuple[str, ...], str]] = [
    (("воздуховод", "вентиляц", "duct", "hvac", "приточ", "вытяж"), "Вентиляция"),
    (("труб", "pipe", "водоснаб", "канализ", "отоплен", "тепл", "plumbing"), "Трубопроводы"),
    (("кабель", "электр", "cable", "wire", "conduit", "освещ", "lighting", "щит"), "Электрика"),
    (("стен", "wall"), "Стены"),
    (("перекрыт", "slab", "плит", "floor slab", "пол"), "Перекрытия"),
    (("колонн", "column"), "Колонны"),
    (("балк", "ригель", "beam", "framing"), "Балки/каркас"),
    (("двер", "door"), "Двери"),
    (("окн", "window", "витраж"), "Окна"),
    (("фундамент", "foundation", "сва", "ростверк"), "Фундаменты"),
    (("лестниц", "stair", "ramp", "пандус"), "Лестницы/пандусы"),
    (("оборудован", "equipment", "machinery"), "Оборудование"),
    (("кров", "roof"), "Кровля"),
]

# Имена свойств, несущих принадлежность к инженерной системе (Revit/IFC).
SYSTEM_PROP_NAMES = {
    "system", "система", "system name", "имя системы", "system type",
    "тип системы", "системное имя", "имя системы (системное имя)",
    "system classification", "классификация системы",
}

_UNASSIGNED = "—"


def derive_system(category: str, object_type: str, family: str, system_prop: str = "") -> str:
    """Система элемента (0 LLM): системное свойство → словарь категории → «Прочее»."""
    sp = (system_prop or "").strip()
    if sp:
        return sp
    hay = " ".join((category or "", object_type or "", family or "")).lower()
    for needles, system in CATEGORY_SYSTEM:
        if any(n in hay for n in needles):
            return system
    return "Прочее"


def _load_elements(import_id: str | None, db_path=CAD_BIM_DB_PATH) -> list[dict[str, Any]]:
    """Элементы + их системное свойство (один проход, без LLM)."""
    init_graph_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if import_id:
            el_rows = conn.execute(
                "SELECT source_id, object_type, name, category, family, level "
                "FROM cad_bim_elements WHERE import_id=?",
                (import_id,),
            ).fetchall()
        else:
            el_rows = conn.execute(
                "SELECT source_id, object_type, name, category, family, level FROM cad_bim_elements"
            ).fetchall()
        # системные свойства одним запросом → словарь source_id → значение
        sys_prop: dict[str, str] = {}
        try:
            prop_rows = conn.execute(
                "SELECT source_id, name, value FROM cad_bim_properties"
                + (" WHERE import_id=?" if import_id else ""),
                ((import_id,) if import_id else ()),
            ).fetchall()
            for p in prop_rows:
                if (p["name"] or "").strip().lower() in SYSTEM_PROP_NAMES and (p["value"] or "").strip():
                    sys_prop.setdefault(p["source_id"], p["value"].strip())
        except sqlite3.Error:
            pass
    out: list[dict[str, Any]] = []
    for r in el_rows:
        floor = (r["level"] or "").strip() or _UNASSIGNED
        category = (r["category"] or "").strip() or _UNASSIGNED
        system = derive_system(r["category"], r["object_type"], r["family"], sys_prop.get(r["source_id"], ""))
        out.append({
            "source_id": r["source_id"],
            "name": (r["name"] or "").strip(),
            "category": category,
            "floor": floor,
            "system": system,
        })
    return out


def classification_backbone(import_id: str | None = None) -> dict[str, Any]:
    """Хребет Floor → System → Category с количествами (навигация, 0 LLM)."""
    elements = _load_elements(import_id)
    floors: dict[str, dict[str, dict[str, int]]] = {}
    systems_seen: set[str] = set()
    categories_seen: set[str] = set()
    for e in elements:
        systems_seen.add(e["system"])
        categories_seen.add(e["category"])
        floors.setdefault(e["floor"], {}).setdefault(e["system"], {})
        floors[e["floor"]][e["system"]][e["category"]] = (
            floors[e["floor"]][e["system"]].get(e["category"], 0) + 1
        )
    floor_list = []
    for floor in sorted(floors):
        sys_list = []
        f_count = 0
        for system in sorted(floors[floor]):
            cats = floors[floor][system]
            s_count = sum(cats.values())
            f_count += s_count
            sys_list.append({
                "system": system,
                "elements": s_count,
                "categories": [
                    {"category": c, "elements": n} for c, n in sorted(cats.items(), key=lambda kv: -kv[1])
                ],
            })
        sys_list.sort(key=lambda s: -s["elements"])
        floor_list.append({"floor": floor, "elements": f_count, "systems": sys_list})
    floor_list.sort(key=lambda f: -f["elements"])
    return {
        "totals": {
            "floors": len(floors),
            "systems": len(systems_seen),
            "categories": len(categories_seen),
            "elements": len(elements),
        },
        "floors": floor_list,
    }


def elements_in(
    *, floor: str | None = None, system: str | None = None, category: str | None = None,
    import_id: str | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    """Обход хребта: элементы, удовлетворяющие фильтрам (0 LLM).
    Сопоставление по вхождению подстроки (нечувствительно к регистру) — «этаж 3»
    найдёт «Этаж 03», «вентиляц» найдёт «Вентиляция»."""
    def _match(value: str, needle: str | None) -> bool:
        return not needle or needle.strip().lower() in (value or "").lower()

    out = []
    for e in _load_elements(import_id):
        if _match(e["floor"], floor) and _match(e["system"], system) and _match(e["category"], category):
            out.append(e)
            if len(out) >= max(1, min(limit, 2000)):
                break
    return out


# ── состояния CDE (ISO 19650) на контейнерах ─────────────────────────

CDE_STATES = ("WIP", "Shared", "Published", "Archived")
CONTAINER_KINDS = {"document", "drawing", "model", "dataset"}
# Детерминированный конечный автомат жизненного цикла (ISO 19650):
#  WIP →Shared/Archived; Shared →WIP(доработка)/Published/Archived;
#  Published →Archived/WIP(новая ревизия); Archived — терминальное.
_TRANSITIONS: dict[str, set[str]] = {
    "WIP": {"Shared", "Archived"},
    "Shared": {"WIP", "Published", "Archived"},
    "Published": {"WIP", "Archived"},
    "Archived": set(),
}


def can_transition(from_state: str, to_state: str) -> bool:
    if from_state == to_state:
        return True
    return to_state in _TRANSITIONS.get(from_state, set())


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(rag_meta_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS les_containers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'document',
            title TEXT NOT NULL DEFAULT '',
            project_id INTEGER NOT NULL DEFAULT 0,
            cde_state TEXT NOT NULL DEFAULT 'WIP',
            revision TEXT NOT NULL DEFAULT '',
            supersedes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def register_container(
    ref: str, *, kind: str = "document", title: str = "", project_id: int = 0,
    revision: str = "", state: str = "WIP",
) -> dict[str, Any]:
    """Зарегистрировать/обновить контейнер (документ/чертёж/модель/датасет)."""
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("Пустой ref контейнера")
    if kind not in CONTAINER_KINDS:
        raise ValueError(f"kind: {sorted(CONTAINER_KINDS)}")
    if state not in CDE_STATES:
        raise ValueError(f"state: {list(CDE_STATES)}")
    with _connect() as conn:
        existing = conn.execute("SELECT cde_state FROM les_containers WHERE ref=?", (ref,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO les_containers(ref, kind, title, project_id, cde_state, revision, supersedes, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ref, kind, title.strip(), int(project_id), state, revision.strip(), "", _now()),
            )
        else:
            # повторная регистрация не сбрасывает состояние; обновляет метаданные
            conn.execute(
                "UPDATE les_containers SET kind=?, title=COALESCE(NULLIF(?,''), title), "
                "project_id=?, revision=COALESCE(NULLIF(?,''), revision), updated_at=? WHERE ref=?",
                (kind, title.strip(), int(project_id), revision.strip(), _now(), ref),
            )
    return get_container(ref) or {}


def set_container_state(ref: str, state: str) -> dict[str, Any]:
    """Перевод по жизненному циклу CDE. Недопустимый переход → ValueError."""
    ref = (ref or "").strip()
    if state not in CDE_STATES:
        raise ValueError(f"state: {list(CDE_STATES)}")
    current = get_container(ref)
    if current is None:
        raise ValueError(f"Контейнер {ref!r} не зарегистрирован")
    if not can_transition(current["cde_state"], state):
        raise ValueError(
            f"Недопустимый переход {current['cde_state']} → {state} (ISO 19650)"
        )
    with _connect() as conn:
        conn.execute(
            "UPDATE les_containers SET cde_state=?, updated_at=? WHERE ref=?", (state, _now(), ref)
        )
    return get_container(ref) or {}


def supersede_container(
    new_ref: str, old_ref: str, *, kind: str = "document", title: str = "",
    project_id: int = 0, revision: str = "",
) -> dict[str, Any]:
    """Новая ревизия заменяет старую: регистрирует новый контейнер с `supersedes`,
    архивирует старый и пишет типизированное ребро `supersedes` в граф (W17.2)."""
    new_ref = (new_ref or "").strip()
    old_ref = (old_ref or "").strip()
    register_container(new_ref, kind=kind, title=title, project_id=project_id, revision=revision)
    with _connect() as conn:
        conn.execute("UPDATE les_containers SET supersedes=?, updated_at=? WHERE ref=?", (old_ref, _now(), new_ref))
        # старую ревизию — в архив (терминальное состояние), если она известна
        if conn.execute("SELECT 1 FROM les_containers WHERE ref=?", (old_ref,)).fetchone():
            conn.execute("UPDATE les_containers SET cde_state='Archived', updated_at=? WHERE ref=?", (_now(), old_ref))
    # типизированное ребро в граф знаний (provenance), 0 LLM
    try:
        from proxy.services.edge_service import add_edge
        add_edge("container", new_ref, "container", old_ref, "supersedes",
                 method="cde_revision", provenance="ontology_service.supersede")
    except Exception:
        pass
    return get_container(new_ref) or {}


def get_container(ref: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM les_containers WHERE ref=?", ((ref or "").strip(),)).fetchone()
        return dict(row) if row else None


def list_containers(project_id: int | None = None, state: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    clauses, params = [], []
    if project_id is not None:
        clauses.append("project_id=?")
        params.append(int(project_id))
    if state:
        clauses.append("cde_state=?")
        params.append(state)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM les_containers{where} ORDER BY id DESC LIMIT ?", (*params, min(limit, 2000))
        ).fetchall()
        return [dict(r) for r in rows]


def cde_summary(project_id: int | None = None) -> dict[str, int]:
    """Счётчики контейнеров по состояниям CDE (для досье/графа)."""
    summary = {s: 0 for s in CDE_STATES}
    for c in list_containers(project_id=project_id):
        summary[c["cde_state"]] = summary.get(c["cde_state"], 0) + 1
    return summary


# ── Захватка-хаб (LBS) — лёгкая свёрстка журнала объёмов (W8) ─────────

def lbs_hubs(status: str = "confirmed", project_id: int | None = None) -> list[dict[str, Any]]:
    """Захватки как LBS-хабы: своды журнала объёмов по захваткам (0 LLM, SQL).
    Захватка без имени — под ключом «—» (общеплощадочные работы).
    project_id (Q3): фильтр по объекту (None → все)."""
    hubs: list[dict[str, Any]] = []
    clauses, params = ["status=?"], [status]
    if project_id is not None:
        clauses.append("project_id=?")
        params.append(int(project_id))
    where = " AND ".join(clauses)
    try:
        conn = sqlite3.connect(rag_meta_db_path())
        conn.row_factory = sqlite3.Row
        with conn:
            rows = conn.execute(
                "SELECT COALESCE(NULLIF(TRIM(zahvatka),''),'—') z, COUNT(*) n, "
                f"SUM(volume) total FROM les_field_entries WHERE {where} GROUP BY z ORDER BY total DESC",
                params,
            ).fetchall()
        for r in rows:
            hubs.append({"zahvatka": r["z"], "entries": r["n"], "total": round(float(r["total"] or 0), 2)})
    except sqlite3.Error:
        pass
    return hubs
