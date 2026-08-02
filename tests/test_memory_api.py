from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.memory_core.store import MemoryStore
from proxy.routers import memory as memory_router
from proxy.security import RequestUser, require_root_admin


def _root_user():
    return RequestUser(role="admin", holder="test", source="trusted_network")


def test_memory_api_is_root_admin_and_persists_config(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path / "memory.db")
    monkeypatch.setattr(memory_router, "get_memory_store", lambda create=True: store)
    app = FastAPI()
    app.include_router(memory_router.router)
    client = TestClient(app)

    assert client.get("/api/memory/status").status_code in {401, 403}

    app.dependency_overrides[require_root_admin] = _root_user
    saved = client.put("/api/memory/config", json={
        "mode": "on", "smeta_capture": True, "smeta_recall": "advisory",
    })
    assert saved.status_code == 200
    assert saved.json()["restart_required"] is True
    status = client.get("/api/memory/status")
    assert status.status_code == 200
    assert status.json()["mode"] == "on"
    assert status.json()["smeta_recall_mode"] == "advisory"


def test_memory_api_rejects_recall_when_memory_is_not_on(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path / "memory.db")
    monkeypatch.setattr(memory_router, "get_memory_store", lambda create=True: store)
    app = FastAPI()
    app.include_router(memory_router.router)
    app.dependency_overrides[require_root_admin] = _root_user
    client = TestClient(app)
    response = client.put("/api/memory/config", json={
        "mode": "shadow", "smeta_capture": True, "smeta_recall": "route_reuse",
    })
    assert response.status_code == 400


def test_memory_api_cannot_promote_project_fact(tmp_path, monkeypatch):
    from proxy.memory_core.contracts import EntryKind, MemoryEntry

    store = MemoryStore(tmp_path / "memory.db")
    store.insert_entry(MemoryEntry("fact", 1, EntryKind.ASSERTION, "Насос", "масса", 85))
    monkeypatch.setattr(memory_router, "get_memory_store", lambda create=True: store)
    app = FastAPI()
    app.include_router(memory_router.router)
    app.dependency_overrides[require_root_admin] = _root_user
    response = TestClient(app).post("/api/memory/entries/fact/promote", json={"scope": "global"})
    assert response.status_code == 409


def test_memory_api_reviews_smeta_trace_with_required_note(tmp_path, monkeypatch):
    from proxy.memory_core.contracts import SmetaSuccessTrace

    store = MemoryStore(tmp_path / "memory.db")
    assert store.save_smeta_trace(SmetaSuccessTrace(
        "trace-1", 7, "attachment", "a1", "rev:w1", "sha", "priced_draft", "q",
        {"title": "Кабель", "unit": "м"}, (), ("ГЭСНм10-01-001-01",), (), "FSNB-2022:r1",
    ))
    monkeypatch.setattr(memory_router, "get_memory_store", lambda create=True: store)
    app = FastAPI()
    app.include_router(memory_router.router)
    app.dependency_overrides[require_root_admin] = _root_user
    client = TestClient(app)

    assert client.post(
        "/api/memory/smeta-traces/trace-1/review", json={"action": "confirm", "note": ""}
    ).status_code == 400
    reviewed = client.post(
        "/api/memory/smeta-traces/trace-1/review",
        json={"action": "confirm", "note": "Проверено пользователем"},
    )
    assert reviewed.status_code == 200
    trace = store.get_smeta_traces(7)[0]
    assert trace.trust_level.value == "accepted_project"
