"""W17.4 — слой решений (DecisionRecord) + типизированные рёбра. 0 LLM."""
import importlib

import pytest


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    import backend.rag_config as rc
    importlib.reload(rc)
    import proxy.services.edge_service as es
    importlib.reload(es)
    import proxy.services.decision_service as ds
    importlib.reload(ds)
    return ds


def test_create_decision_derives_typed_edges(svc):
    rec = svc.create_decision(
        "Балку увеличить до 400 мм",
        question="Почему такой размер балки?",
        rationale="Прогиб по СП 20.13330 для пролёта Source ID: beam-12 и [[корпус Б]]",
        project_id=2, at="Захватка-3",
    )
    out = rec["backlinks"]["out"]
    # обоснование → норматив (justified_by)
    assert any(e["dst_id"] == "СП 20.13330" for e in out.get("justified_by", []))
    # касается элемента (concerns)
    assert any(e["dst_id"] == "beam-12" for e in out.get("concerns", []))
    # ссылка (references) на [[вики]]
    assert any(e["dst_id"] == "корпус Б" for e in out.get("references", []))
    # привязка к захватке (at)
    assert any(e["dst_id"] == "Захватка-3" for e in out.get("at", []))


def test_list_partitioned_by_project(svc):
    svc.create_decision("реш объекта 2", project_id=2)
    svc.create_decision("глобальное", project_id=0)
    assert [d["decision"] for d in svc.list_decisions(project_id=2)] == ["реш объекта 2"]
    assert len(svc.list_decisions()) == 2


def test_backlinks_grouped_by_edge_type(svc):
    rec = svc.create_decision("X", rationale="по ГОСТ 27751 и СП 16.13330")
    just = rec["backlinks"]["out"]["justified_by"]
    assert {e["dst_id"] for e in just} == {"ГОСТ 27751", "СП 16.13330"}


def test_supersede_marks_old_and_links(svc):
    old = svc.create_decision("старое решение", project_id=2)
    new = svc.create_decision("новое решение", project_id=2)
    res = svc.supersede_decision(new["id"], old["id"])
    assert svc.get_decision(old["id"])["status"] == "superseded"
    out = res["backlinks"]["out"].get("supersedes", [])
    assert any(e["dst_id"] == str(old["id"]) for e in out)


def test_create_rejects_empty(svc):
    with pytest.raises(ValueError):
        svc.create_decision("   ")


# ── чат-команды ──────────────────────────────────────────────────────

def test_chat_create_with_rationale(svc):
    reply = svc.maybe_handle_decision_command(
        "реши: перенести ввод ВРУ в осях 3-4 обоснование: по СП 256.1325800", project_id=2
    )
    assert reply["operation"] == "decision_create"
    rec = svc.get_decision(reply["decision_id"])
    assert rec["decision"].startswith("перенести ввод ВРУ")
    assert "СП 256.1325800" in rec["rationale"]
    assert any(e["dst_id"] == "СП 256.1325800" for e in rec["backlinks"]["out"].get("justified_by", []))
    assert rec["project_id"] == 2


def test_chat_list(svc):
    svc.create_decision("реш1", project_id=2)
    reply = svc.maybe_handle_decision_command("решения по объекту", project_id=2)
    assert reply["operation"] == "decisions_list"
    assert reply["count"] == 1


def test_chat_passthrough_non_command(svc):
    assert svc.maybe_handle_decision_command("какая ширина эвакуационного выхода?") is None
