from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.routers import profiles as profiles_router
from proxy.security import RequestUser, require_admin, require_user
from proxy.services.chat_profile_service import (
    PROFILE_PROMPT_MAX_CHARS,
    PROFILE_SKILL_MAX_CHARS,
)


def _admin():
    return RequestUser(role="admin", holder="test", source="trusted_network")


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(profiles_router, "_profiles_db_path", lambda: tmp_path / "meta.db")
    app = FastAPI()
    app.include_router(profiles_router.router)
    app.dependency_overrides[require_user] = _admin
    app.dependency_overrides[require_admin] = _admin
    return TestClient(app)


def test_profiles_api_publishes_selects_activates_and_binds(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    registry = client.get("/api/profiles")
    assert registry.status_code == 200
    search = next(item for item in registry.json()["profiles"] if item["mode"] == "search")

    prompt = client.post(
        "/api/profiles/text-revisions",
        json={"kind": "prompt", "name": "Точный поиск", "text": "Ищи итеративно."},
    )
    skill = client.post(
        "/api/profiles/text-revisions",
        json={"kind": "skill", "name": "Чтение", "text": "# Чтение\n\nОткрывай источник."},
    )
    assert prompt.status_code == skill.status_code == 200

    published = client.post(
        "/api/profiles/revisions",
        json={
            "mode": "search",
            "name": "Поиск v2",
            "prompt_revision_id": prompt.json()["revision_id"],
            "skill_revision_id": skill.json()["revision_id"],
            "tools": ["dataset_map", "search_sources"],
            "model_policy": {"temperature": 0.1},
            "rag_policy": {"grounded": True},
            "source_revision_id": search["active_revision_id"],
        },
    )
    assert published.status_code == 200
    revision_id = published.json()["revision_id"]

    activated = client.post(f"/api/profiles/search/activate/{revision_id}")
    assert activated.status_code == 200
    assert activated.json()["revision_id"] == revision_id

    binding = client.put(
        "/api/profiles/chats/chat-7/binding",
        json={"mode": "search", "profile_revision_id": revision_id},
    )
    assert binding.status_code == 200
    assert binding.json()["revision_id"] == revision_id


def test_profiles_api_rejects_base_delete_and_cross_mode_activation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    profiles = client.get("/api/profiles").json()["profiles"]
    search = next(item for item in profiles if item["mode"] == "search")
    agent = next(item for item in profiles if item["mode"] == "agent")

    deleted = client.delete(f"/api/profiles/profile/{search['active_revision_id']}")
    assert deleted.status_code == 409
    assert "Base" in deleted.json()["detail"]

    activated = client.post(
        f"/api/profiles/search/activate/{agent['active_revision_id']}"
    )
    assert activated.status_code == 409
    assert "другому режиму" in activated.json()["detail"]


def test_profile_mutations_require_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles_router, "_profiles_db_path", lambda: tmp_path / "meta.db")
    app = FastAPI()
    app.include_router(profiles_router.router)
    app.dependency_overrides[require_user] = _admin
    client = TestClient(app)

    assert client.get("/api/profiles").status_code == 200
    assert client.post(
        "/api/profiles/text-revisions",
        json={"kind": "prompt", "name": "x", "text": "y"},
    ).status_code in {401, 403}


def test_profiles_api_enforces_authoritative_prompt_and_skill_limits(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    for kind, limit in (
        ("prompt", PROFILE_PROMPT_MAX_CHARS),
        ("skill", PROFILE_SKILL_MAX_CHARS),
    ):
        accepted = client.post(
            "/api/profiles/text-revisions",
            json={"kind": kind, "name": "Граница", "text": "x" * limit},
        )
        rejected = client.post(
            "/api/profiles/text-revisions",
            json={"kind": kind, "name": "Выше границы", "text": "x" * (limit + 1)},
        )
        assert accepted.status_code == 200
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "profile_text_too_long"

    registry = client.get("/api/profiles").json()
    assert registry["text_limits"] == {
        "prompt": PROFILE_PROMPT_MAX_CHARS,
        "skill": PROFILE_SKILL_MAX_CHARS,
    }
