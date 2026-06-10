"""W12.1: дифф CAD-графов и текстовых документов — офлайн-тесты, без LLM."""

import json
import sqlite3

import pytest

from proxy.services.cad_bim_graph import init_graph_db
from proxy.services.diff_service import (
    diff_cad_imports,
    diff_texts,
    split_clauses,
)


# ── фикстура графа ──

@pytest.fixture()
def graph_db(tmp_path):
    db_path = tmp_path / "cad_bim_graph.db"
    init_graph_db(db_path)
    with sqlite3.connect(db_path) as conn:
        for import_id in ("imp_a", "imp_b"):
            conn.execute(
                "INSERT INTO cad_bim_imports (id, source, source_kind, profile, created_at) "
                "VALUES (?, 'test', 'json', 'revit', '2026-06-10')",
                (import_id,),
            )
        conn.commit()
    return db_path


def _add_element(db_path, import_id, source_id, *, name="Стена", level="Этаж 1",
                 object_type="IfcWall", props=None, attributes=None):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO cad_bim_elements (id, import_id, source_id, object_type, name, "
            "level, attributes_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '2026-06-10')",
            (f"{import_id}:{source_id}", import_id, source_id, object_type, name, level,
             json.dumps(attributes or {}, ensure_ascii=False)),
        )
        for prop_name, value in (props or {}).items():
            conn.execute(
                "INSERT INTO cad_bim_properties (id, import_id, element_id, source_id, "
                "name, value, created_at) VALUES (?, ?, ?, ?, ?, ?, '2026-06-10')",
                (f"{import_id}:{source_id}:{prop_name}", import_id,
                 f"{import_id}:{source_id}", source_id, prop_name, str(value)),
            )
        conn.commit()


# ── CAD-дифф ──

def test_cad_diff_added_removed(graph_db):
    _add_element(graph_db, "imp_a", "w1")
    _add_element(graph_db, "imp_b", "w1")
    _add_element(graph_db, "imp_b", "w2", name="Новая стена")
    diff = diff_cad_imports("imp_a", "imp_b", db_path=graph_db)
    assert diff.added_count == 1 and diff.added[0]["source_id"] == "w2"
    assert diff.removed_count == 0
    assert diff.unchanged_count == 1


def test_cad_diff_field_change(graph_db):
    _add_element(graph_db, "imp_a", "w1", level="Этаж 1")
    _add_element(graph_db, "imp_b", "w1", level="Этаж 2")
    diff = diff_cad_imports("imp_a", "imp_b", db_path=graph_db)
    assert diff.changed_count == 1
    assert diff.changed[0]["changes"]["level"] == {"old": "Этаж 1", "new": "Этаж 2"}


def test_cad_diff_property_change_and_removal(graph_db):
    _add_element(graph_db, "imp_a", "w1", props={"Толщина": "200", "Огнестойкость": "EI45"})
    _add_element(graph_db, "imp_b", "w1", props={"Толщина": "250"})
    diff = diff_cad_imports("imp_a", "imp_b", db_path=graph_db)
    changes = diff.changed[0]["changes"]
    assert changes["prop:Толщина"] == {"old": "200", "new": "250"}
    assert changes["prop:Огнестойкость"] == {"old": "EI45", "new": None}


def test_cad_diff_identical_imports(graph_db):
    _add_element(graph_db, "imp_a", "w1", props={"Толщина": "200"})
    _add_element(graph_db, "imp_b", "w1", props={"Толщина": "200"})
    diff = diff_cad_imports("imp_a", "imp_b", db_path=graph_db)
    assert diff.added_count == diff.removed_count == diff.changed_count == 0
    assert diff.unchanged_count == 1


# ── split_clauses ──

def test_split_clauses_numbered():
    text = "5.1 Общие требования\nтело один\n5.2 Частные требования\nтело два"
    blocks = dict(split_clauses(text))
    assert "5.1" in blocks and "тело один" in blocks["5.1"]
    assert "5.2" in blocks and "тело два" in blocks["5.2"]


def test_split_clauses_preamble_unkeyed():
    blocks = split_clauses("Преамбула без номера\n\n7.1 Пункт\nтело")
    assert blocks[0][0] == "" and "Преамбула" in blocks[0][1]


# ── текстовый дифф ──

def test_text_diff_changed_clause():
    a = "5.1 Требования\nТолщина стены 200 мм\n5.2 Другое\nбез изменений"
    b = "5.1 Требования\nТолщина стены 250 мм\n5.2 Другое\nбез изменений"
    diff = diff_texts(a, b)
    assert len(diff.changed) == 1
    assert diff.changed[0]["clause"] == "5.1"
    assert "200" in diff.changed[0]["diff"] and "250" in diff.changed[0]["diff"]
    assert diff.unchanged_count == 1


def test_text_diff_added_removed_clause():
    a = "5.1 Старый пункт\nтело"
    b = "5.1 Старый пункт\nтело\n5.2 Новый пункт\nновое тело"
    diff = diff_texts(a, b)
    assert [entry["clause"] for entry in diff.added] == ["5.2"]
    assert not diff.removed


def test_text_diff_whitespace_insensitive():
    a = "5.1 Пункт\nтекст   с    пробелами"
    b = "5.1 Пункт\nтекст с пробелами"
    diff = diff_texts(a, b)
    assert not diff.changed and diff.unchanged_count == 1


def test_text_diff_clause_sort_numeric():
    a = "5.2 Б\nx"
    b = "5.2 Б\nx\n5.10 В\ny\n5.9 А\nz"
    diff = diff_texts(a, b)
    assert [e["clause"] for e in diff.added] == ["5.9", "5.10"]


def test_diff_service_uses_no_llm():
    """ADR-11: модуль диффа не импортирует HTTP/LLM-клиентов."""
    import inspect

    import proxy.services.diff_service as ds

    source = inspect.getsource(ds)
    for marker in ("import httpx", "import openai", "import requests", "/api/chat", "completions"):
        assert marker not in source, f"LLM/HTTP-маркер '{marker}' в diff_service"
