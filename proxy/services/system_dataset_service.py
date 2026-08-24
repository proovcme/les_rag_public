"""Typed registry for module-owned RAG datasets.

System datasets are readable evidence/navigation sources owned by a LES module,
not user/project uploads.  Keeping this identity in MetaDB prevents module cards
from competing in project scopes merely because they share a source folder.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
import uuid

from backend.rag_config import rag_meta_db_path


@dataclass(frozen=True)
class SystemDatasetSpec:
    dataset_name: str
    module_id: str
    source_role: str
    display_name: str
    pinned_order: int


SYSTEM_DATASETS: tuple[SystemDatasetSpec, ...] = (
    SystemDatasetSpec("NORMATIVE_SERVICE_Index", "normcontrol", "normative_reference", "Нормативы и чек-листы", 10),
    SystemDatasetSpec("PRICE_SERVICE_Index", "smeta", "price_reference", "Прайсы", 20),
    SystemDatasetSpec("SMETA_SERVICE_Index", "smeta", "module_navigation", "Сметные источники", 30),
    SystemDatasetSpec("SMETA_NORMS_Index", "smeta", "normative_reference", "Сметные нормы", 40),
)
EXTERNAL_SYSTEM_DATASETS: tuple[SystemDatasetSpec, ...] = (
    SystemDatasetSpec("ARTEL_Index", "artel", "integration_knowledge", "ARTEL", 5),
)
_SYSTEM_DATASET_NAMESPACE = uuid.UUID("fda5fe77-08da-47c0-9866-cfbde72bbd83")


def system_dataset_spec(dataset_name: str) -> SystemDatasetSpec | None:
    name = str(dataset_name or "").strip()
    for item in (*SYSTEM_DATASETS, *EXTERNAL_SYSTEM_DATASETS):
        if name == item.dataset_name:
            return item
    if name == "GESN_NORMS_2022_PDF" or name.startswith("SMETA_RU_NORM_"):
        return SystemDatasetSpec(name, "smeta", "normative_source", name, 90)
    return None


def dataset_identity(dataset_name: str) -> tuple[str, str]:
    spec = system_dataset_spec(dataset_name)
    return ("system", spec.module_id) if spec else ("user", "")


def ensure_system_datasets(conn: sqlite3.Connection) -> list[str]:
    """Idempotently provision operator-owned service datasets in MetaDB."""
    created: list[str] = []
    for spec in SYSTEM_DATASETS:
        dataset_id = str(uuid.uuid5(_SYSTEM_DATASET_NAMESPACE, spec.dataset_name))
        row = conn.execute("SELECT id FROM datasets WHERE name=? LIMIT 1", (spec.dataset_name,)).fetchone()
        if row:
            conn.execute(
                "UPDATE datasets SET dataset_scope='system', module_id=? WHERE id=?",
                (spec.module_id, str(row[0])),
            )
            continue
        stable_row = conn.execute("SELECT id FROM datasets WHERE id=? LIMIT 1", (dataset_id,)).fetchone()
        if stable_row:
            conn.execute(
                "UPDATE datasets SET name=?, dataset_scope='system', module_id=? WHERE id=?",
                (spec.dataset_name, spec.module_id, dataset_id),
            )
            continue
        conn.execute(
            "INSERT INTO datasets (id, name, status, dataset_scope, module_id) "
            "VALUES (?, ?, 'IDLE', 'system', ?)",
            (dataset_id, spec.dataset_name, spec.module_id),
        )
        created.append(dataset_id)
    return created


def module_dataset_ids(module_id: str, *, db_path: str | None = None) -> list[str]:
    """Return only explicitly typed system datasets owned by a module."""
    owner = str(module_id or "").strip()
    if not owner:
        return []
    try:
        with sqlite3.connect(db_path or rag_meta_db_path()) as conn:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(datasets)")}
            if not {"dataset_scope", "module_id"}.issubset(columns):
                return []
            rows = conn.execute(
                "SELECT id FROM datasets WHERE dataset_scope='system' AND module_id=? "
                "ORDER BY name, id",
                (owner,),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [str(row[0]) for row in rows]
