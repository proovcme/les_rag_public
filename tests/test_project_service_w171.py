"""W17.1 — сущность объекта + привязки + резолв области (проектный режим).
Детерминированно, 0 LLM. Метабаза изолируется через RAG_META_DB_PATH в tmp.
"""
import importlib

import pytest


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    import backend.rag_config as rc
    importlib.reload(rc)
    import proxy.services.project_service as ps
    importlib.reload(ps)
    return ps


def test_create_list_get_project(svc):
    p = svc.create_project("ЖК Сосновый", code="SOSNA-1", address="ул. Лесная, 1")
    assert p["id"] >= 1
    assert p["name"] == "ЖК Сосновый"
    assert p["code"] == "SOSNA-1"
    assert p["status"] == "active"
    rows = svc.list_projects()
    assert len(rows) == 1 and rows[0]["name"] == "ЖК Сосновый"
    got = svc.get_project(p["id"])
    assert got["address"] == "ул. Лесная, 1"
    assert got["links"] == []


def test_create_rejects_empty_name(svc):
    with pytest.raises(ValueError):
        svc.create_project("   ")


def test_link_and_project_dataset_ids(svc):
    p = svc.create_project("Объект A")
    pid = p["id"]
    svc.link_entity(pid, "dataset", "ds-fire")
    svc.link_entity(pid, "dataset", "ds-hvac")
    svc.link_entity(pid, "cad_bim_import", "imp-123")
    svc.link_entity(pid, "field_zahvatka", "Б2")
    # повторная привязка идемпотентна (UNIQUE)
    svc.link_entity(pid, "dataset", "ds-fire")

    assert sorted(svc.project_dataset_ids(pid)) == ["ds-fire", "ds-hvac"]
    all_links = svc.list_links(pid)
    assert len(all_links) == 4
    assert {l["kind"] for l in all_links} == {"dataset", "cad_bim_import", "field_zahvatka"}
    assert len(svc.list_links(pid, kind="dataset")) == 2


def test_link_rejects_unknown_kind_and_missing_project(svc):
    p = svc.create_project("Объект B")
    with pytest.raises(ValueError):
        svc.link_entity(p["id"], "bogus", "x")
    with pytest.raises(ValueError):
        svc.link_entity(99999, "dataset", "ds-x")


def test_unlink_and_delete(svc):
    p = svc.create_project("Объект C")
    pid = p["id"]
    svc.link_entity(pid, "dataset", "ds-1")
    assert svc.unlink_entity(pid, "dataset", "ds-1") is True
    assert svc.project_dataset_ids(pid) == []
    assert svc.unlink_entity(pid, "dataset", "ds-1") is False  # уже нет
    svc.link_entity(pid, "task", "7")
    assert svc.delete_project(pid) is True
    assert svc.get_project(pid) is None
    assert svc.list_links(pid) == []  # привязки тоже удалены


def test_set_status(svc):
    p = svc.create_project("Объект D")
    upd = svc.set_project_status(p["id"], "archived")
    assert upd["status"] == "archived"
    with pytest.raises(ValueError):
        svc.set_project_status(p["id"], "bogus")


def test_empty_scope_means_no_narrowing(svc):
    """Объект без привязанных датасетов → пустая область → chat остаётся обычным RAG."""
    p = svc.create_project("Объект без области")
    assert svc.project_dataset_ids(p["id"]) == []
