"""Q3 — партиционирование задач/объёмов/заметок по объекту (project_id). 0 LLM."""
import importlib

import pytest


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    import backend.rag_config as rc
    importlib.reload(rc)
    mods = {}
    for name in ("proxy.services.edge_service", "proxy.services.task_service",
                 "proxy.services.memory_service", "proxy.services.field_intake_service",
                 "proxy.services.ontology_service", "proxy.services.project_service"):
        mods[name.split(".")[-1]] = importlib.reload(importlib.import_module(name))
    return mods


# ── задачи ───────────────────────────────────────────────────────────

def test_tasks_partitioned(svc):
    ts = svc["task_service"]
    ts.create_task("задача объекта 2", project_id=2)
    ts.create_task("глобальная задача", project_id=0)
    assert {t["title"] for t in ts.list_tasks(project_id=2)} == {"задача объекта 2"}
    assert {t["title"] for t in ts.list_tasks(project_id=0)} == {"глобальная задача"}
    assert len(ts.list_tasks()) == 2  # без фильтра — все


def test_task_chat_command_tags_project(svc):
    ts = svc["task_service"]
    ts.maybe_handle_task_command("поставь задачу проверить узел", project_id=2)
    assert len(ts.list_tasks(project_id=2)) == 1
    assert ts.list_tasks(project_id=5) == []


# ── заметки ──────────────────────────────────────────────────────────

def test_notes_partitioned(svc):
    ms = svc["memory_service"]
    ms.create_note("заметка по объекту", project_id=2)
    ms.create_note("общая заметка", project_id=0)
    assert {n["text"] for n in ms.list_notes(project_id=2)} == {"заметка по объекту"}
    assert len(ms.list_notes()) == 2


def test_note_chat_command_tags_project(svc):
    ms = svc["memory_service"]
    ms.maybe_handle_memory_command("запомни: бетон B30 на захватке 2", project_id=2)
    assert len(ms.list_notes(project_id=2)) == 1
    assert ms.list_notes(project_id=9) == []


# ── объёмы ───────────────────────────────────────────────────────────

def test_volumes_partitioned(svc):
    fs = svc["field_intake_service"]
    fs.create_entry("Бетон", 10.0, "м3", status="confirmed", project_id=2)
    fs.create_entry("Бетон", 99.0, "м3", status="confirmed", project_id=0)
    agg2 = fs.aggregate_volumes(status="confirmed", project_id=2)
    assert sum(r["total"] for r in agg2) == 10.0
    assert sum(r["total"] for r in fs.aggregate_volumes(status="confirmed")) == 109.0  # все


def test_field_chat_command_tags_project(svc):
    fs = svc["field_intake_service"]
    fs.maybe_handle_field_command("запиши объём 5 м3 монолитная плита захватка 1", project_id=2)
    assert sum(r["total"] for r in fs.aggregate_volumes(project_id=2)) == 5.0
    assert fs.aggregate_volumes(project_id=7) == []


# ── досье строго в рамках объекта ────────────────────────────────────

def test_dossier_is_project_scoped(svc):
    ps, ts, ms, fs = svc["project_service"], svc["task_service"], svc["memory_service"], svc["field_intake_service"]
    pid = ps.create_project("БЦ Тест")["id"]
    ts.create_task("задача БЦ", project_id=pid)
    ts.create_task("чужая задача", project_id=999)
    ms.create_note("заметка БЦ", project_id=pid)
    ms.create_note("чужая заметка", project_id=999)
    fs.create_entry("Кирпич", 100.0, "шт", status="confirmed", project_id=pid)
    fs.create_entry("Чужой объём", 50.0, "м3", status="confirmed", project_id=999)

    d = ps.build_dossier(pid)
    assert [t["title"] for t in d["open_tasks"]] == ["задача БЦ"]
    assert d["notes_count"] == 1
    assert d["volumes"]["total"] == 100.0
