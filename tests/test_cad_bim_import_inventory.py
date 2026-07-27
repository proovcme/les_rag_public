import sqlite3

import pytest

from proxy.routers import speckle
from proxy.services.cad_bim_graph import cad_bim_import_inventory, init_graph_db


def _insert_import(
    conn: sqlite3.Connection,
    import_id: str,
    source: str,
    *,
    elements: int,
    relations: int,
    properties: int,
) -> None:
    conn.execute(
        """
        INSERT INTO cad_bim_imports
        (id, source, source_kind, profile, created_at, element_count, relation_count, property_count, projection_path)
        VALUES (?, ?, 'json', 'autocad', '2026-07-04T10:00:00+00:00', ?, ?, ?, ?)
        """,
        (
            import_id,
            source,
            elements,
            relations,
            properties,
            f"RAG_Content/CAD_BIM/exports/cad_bim_json_{import_id}.md",
        ),
    )
    for idx in range(elements):
        conn.execute(
            """
            INSERT INTO cad_bim_elements
            (id, import_id, source_id, object_type, name, created_at)
            VALUES (?, ?, ?, 'LINE', ?, '2026-07-04T10:00:00+00:00')
            """,
            (f"{import_id}-el-{idx}", import_id, f"{import_id}:el:{idx}", f"Element {idx}"),
        )


def test_cad_bim_import_inventory_marks_duplicates_weak_imports_and_index_status(tmp_path):
    db_path = tmp_path / "cad_bim_graph.db"
    meta_db = tmp_path / "les_meta_qwen.db"
    init_graph_db(db_path)
    with sqlite3.connect(db_path) as conn:
        _insert_import(
            conn,
            "imp_a",
            "RAG_Content/CAD_BIM/JSON/kotelnaya_repair_3.Леснои_64-АТМ-Р-Планы_aaaabbbbcc.cad_bim_graph.json",
            elements=1524,
            relations=1523,
            properties=13316,
        )
        _insert_import(
            conn,
            "imp_b",
            "RAG_Content/CAD_BIM/JSON/kotelnaya_repair_4.Леснои_64-АТМ-Р-Планы_ddddbbbbcc.cad_bim_graph.json",
            elements=1524,
            relations=1523,
            properties=13316,
        )
        _insert_import(
            conn,
            "tiny",
            "RAG_Content/CAD_BIM/JSON/kotelnaya_repair_5.title_page_1111222233.cad_bim_graph.json",
            elements=1,
            relations=0,
            properties=6,
        )

    with sqlite3.connect(meta_db) as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT, status TEXT, chunk_count INTEGER)")
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                dataset_id TEXT,
                file_name TEXT,
                status TEXT,
                chunk_count INTEGER
            )
            """
        )
        conn.execute("INSERT INTO datasets (id, name, status, chunk_count) VALUES ('cad', 'CAD_BIM_Index', 'INDEXED', 20)")
        conn.executemany(
            "INSERT INTO documents (id, dataset_id, file_name, status, chunk_count) VALUES (?, 'cad', ?, 'INDEXED', ?)",
            [
                ("doc-a1", "CAD_BIM/exports/cad_bim_json_imp_a.md", 12),
                ("doc-a2", "cad_bim_json_imp_a.md", 12),
                ("doc-b1", "cad_bim_json_imp_b.md", 10),
            ],
        )

    inventory = cad_bim_import_inventory(db_path=db_path, meta_db_path=meta_db)

    assert inventory["totals"]["imports"] == 3
    assert inventory["totals"]["duplicate_groups"] == 1
    assert inventory["duplicate_groups"][0]["import_ids"] == ["imp_a", "imp_b"]
    by_id = {item["id"]: item for item in inventory["imports"]}
    assert by_id["imp_a"]["projection_index_status"] == "duplicate_indexed"
    assert by_id["imp_a"]["indexed_count"] == 2
    assert by_id["imp_b"]["projection_index_status"] == "indexed"
    assert by_id["tiny"]["quality_status"] == "minimal"


@pytest.mark.asyncio
async def test_cad_bim_imports_route_returns_inventory(monkeypatch):
    monkeypatch.setattr(
        speckle,
        "cad_bim_import_inventory",
        lambda *, limit: {"limit": limit, "totals": {"imports": 1}, "imports": []},
    )

    result = await speckle.cad_bim_imports(limit=50, _user=object())

    assert result["limit"] == 50
    assert result["totals"]["imports"] == 1
