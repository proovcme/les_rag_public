from fastapi import FastAPI
from fastapi.testclient import TestClient

from proxy.routers import settings
from proxy.security import RequestUser, require_admin
from sovushka.pages.diag import _web_research_probe_failed


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(settings.router)

    async def _admin() -> RequestUser:
        return RequestUser(role="admin", holder="fixture-admin", source="test")

    app.dependency_overrides[require_admin] = _admin
    return TestClient(app)


def test_web_research_status_never_returns_token(monkeypatch):
    monkeypatch.setenv("LES_WEB_SEARCH_MODE", "extended")
    monkeypatch.setenv("LES_SEARXNG_URL", "http://127.0.0.1:8081")
    monkeypatch.setenv("LES_CRAWL4AI_URL", "http://127.0.0.1:11235")
    monkeypatch.setenv("LES_CRAWL4AI_TOKEN", "secret-token")

    response = _client().get("/api/settings/web-research")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["crawl4ai_token_set"] is True
    assert payload["config"]["mode"] == "extended"
    assert "secret-token" not in repr(payload)
    assert payload["services"]["simple"]["status"] == "available"
    assert payload["services"]["searxng"]["status"] == "configured"
    assert payload["services"]["crawl4ai"]["status"] == "configured"


def test_probe_reports_search_and_reader_independently(monkeypatch):
    expected = {
        "config": {"mode": "extended", "crawl4ai_token_set": False},
        "services": {
            "simple": {"status": "available"},
            "searxng": {"status": "ok"},
            "crawl4ai": {"status": "error"},
        },
    }
    monkeypatch.setattr(settings, "probe_web_research_services", lambda _config: expected)

    response = _client().post("/api/settings/web-research/probe")

    assert response.status_code == 200
    assert response.json() == expected
    assert set(response.json()["services"]) == {"simple", "searxng", "crawl4ai"}


def test_normal_status_does_not_probe_or_crawl(monkeypatch):
    def unexpected(_config):
        raise AssertionError("normal GET must not contact providers")

    monkeypatch.setattr(settings, "probe_web_research_services", unexpected)

    response = _client().get("/api/settings/web-research")

    assert response.status_code == 200


def test_diag_has_explicit_web_mode_selector_and_probe_without_local_styling():
    source = open("sovushka/pages/diag.py", encoding="utf-8").read()
    assert "Веб-поиск" in source
    assert "Простой" in source
    assert "Расширенный" in source
    assert "Фактически используется" in source
    assert "Проверить веб-поиск" in source
    assert "web_mode_select = select_field" in source
    assert "/api/settings/web-research/probe" in source
    assert "web_research_feedback" in source
    assert "web_research_panel.style(" not in source


def test_extended_probe_treats_missing_services_as_degraded():
    payload = {
        "config": {"mode": "extended"},
        "services": {
            "simple": {"status": "available"},
            "searxng": {"status": "missing"},
            "crawl4ai": {"status": "missing"},
        },
    }

    assert _web_research_probe_failed(payload) is True


def test_simple_probe_does_not_require_extended_services():
    payload = {
        "config": {"mode": "simple"},
        "services": {
            "simple": {"status": "available"},
            "searxng": {"status": "missing"},
            "crawl4ai": {"status": "missing"},
        },
    }

    assert _web_research_probe_failed(payload) is False


def test_web_status_renderer_does_not_mutate_colbert_policy():
    source = open("sovushka/pages/diag.py", encoding="utf-8").read()
    renderer = source.split("def render_web_research_status", 1)[1].split(
        "async def load_web_research", 1
    )[0]

    assert 'policy["colbert"]' not in renderer


def test_colbert_cpu_build_switch_round_trips_through_advanced_policy():
    source = open("sovushka/pages/diag.py", encoding="utf-8").read()
    loader = source.split("async def load_rag_advanced", 1)[1].split(
        "async def load_rag_preflight", 1
    )[0]
    saver = source.split("async def save_rag_advanced", 1)[1].split(
        "async def load_runtime_registry", 1
    )[0]

    assert "colbert_cpu_build_switch.value = bool(" in loader
    assert 'colbert.get("allow_cpu_full_build", False)' in loader
    assert 'policy["colbert"]["allow_cpu_full_build"] = bool(' in saver
    assert 'colbert.get("allow_cpu_full_build"' not in saver
