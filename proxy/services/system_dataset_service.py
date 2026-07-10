"""Typed registry for module-owned RAG datasets.

System datasets are readable evidence/navigation sources owned by a LES module,
not user/project uploads.  Keeping this identity in MetaDB prevents module cards
from competing in project scopes merely because they share a source folder.
"""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from backend.rag_config import rag_meta_db_path


@dataclass(frozen=True)
class SystemDatasetSpec:
    dataset_name: str
    module_id: str
    source_role: str


def system_dataset_spec(dataset_name: str) -> SystemDatasetSpec | None:
    name = str(dataset_name or "").strip()
    if name == "SMETA_SERVICE_Index":
        return SystemDatasetSpec(name, "smeta", "module_navigation")
    if name == "GESN_NORMS_2022_PDF" or name.startswith("SMETA_RU_NORM_"):
        return SystemDatasetSpec(name, "smeta", "normative_source")
    return None


def dataset_identity(dataset_name: str) -> tuple[str, str]:
    spec = system_dataset_spec(dataset_name)
    return ("system", spec.module_id) if spec else ("user", "")


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
