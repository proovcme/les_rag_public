"""Ярус 2 — агент-роутер + реестр проектов. Без живого LLM (мок) и без сети."""
from __future__ import annotations

import pytest

from proxy.services import agent_router_service as ar
from proxy.services import project_registry_chat_service as reg
from proxy.services.query_router import QueryIntent


# ── реестр ──

@pytest.mark.parametrize("q,hit", [
    ("реестр проектов", True),
    ("какие у нас объекты", True),
    ("покажи общую карту папок", True),
    ("сколько кабеля на L5", False),
])
def test_registry_intent(q, hit):
    assert reg.is_registry_query(q) is hit


def test_registry_tool_result_shape(monkeypatch):
    monkeypatch.setattr("proxy.services.project_service.build_registry",
                        lambda: {"projects": [{"id": 3, "name": "Котельная", "stage": "РД",
                                               "code": "Ш-1", "address": "СПб", "folders": ["/x"],
                                               "datasets": 0, "has_les_md": True}], "count": 1})
    res = reg.registry_tool_result()
    assert res["operation"] == "project_registry_lookup"
    assert res["registry"]["projects"][0]["name"] == "Котельная"
    assert "answer" not in res


def test_registry_empty(monkeypatch):
    monkeypatch.setattr("proxy.services.project_service.build_registry",
                        lambda: {"projects": [], "count": 0})
    result = reg.registry_tool_result()
    assert result["status"] == "empty"
    assert "answer" not in result


# ── агент-роутер ──

def test_agent_off_returns_none(monkeypatch):
    monkeypatch.delenv("LES_AGENT_LOOP", raising=False)
    monkeypatch.setenv("LES_ROUTER_PRIMARY", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: pytest.fail("legacy agent loop must stay off"))
    assert ar.maybe_agent_route("реестр проектов") is None


def test_router_primary_defaults_off(monkeypatch):
    monkeypatch.delenv("LES_ROUTER_PRIMARY", raising=False)
    assert ar.router_primary() is False


def test_router_runtime_config_falls_back_to_local_mlx(monkeypatch):
    monkeypatch.delenv("LES_ROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("LES_ROUTER_MODEL", raising=False)
    monkeypatch.delenv("LES_ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MLX_MODEL", raising=False)
    monkeypatch.setenv("MLX_URL", "http://127.0.0.1:8080")

    cfg = ar._router_runtime_config()

    assert cfg["base"] == "http://127.0.0.1:8080/v1"
    assert cfg["key"] == "local"
    assert cfg["timeout"] == 2.0
    assert cfg["model"] == "mlx-community/Qwen3.5-9B-OptiQ-4bit"


def test_router_runtime_config_uses_cloud_only_with_key(monkeypatch):
    monkeypatch.delenv("LES_ROUTER_BASE_URL", raising=False)
    monkeypatch.delenv("LES_ROUTER_MODEL", raising=False)
    monkeypatch.delenv("LES_ROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openai.api.proxyapi.ru/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    cfg = ar._router_runtime_config()

    assert cfg["base"] == "https://openai.api.proxyapi.ru/v1"
    assert cfg["model"] == "gpt-4.1"
    assert cfg["key"] == "secret"


def test_query_intent_exposes_channel_as_compatibility_intent():
    route = QueryIntent("rag", "NTD_FIRE", "fire_safety_keyword")

    assert route.intent == "rag"


def test_router_runtime_config_uses_active_freetoken(monkeypatch):
    for key in (
        "LES_ROUTER_BASE_URL",
        "LES_ROUTER_MODEL",
        "LES_ROUTER_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LES_LLM_PROVIDER", "freetoken")
    monkeypatch.setenv("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1")
    monkeypatch.setenv("FREETOKEN_MODEL", "Qwen3.6-35B-A3B-NVFP4")

    cfg = ar._router_runtime_config()

    assert cfg["provider"] == "freetoken"
    assert cfg["base"] == "http://127.0.0.1:1919/v1"
    assert cfg["model"] == "Qwen3.6-35B-A3B-NVFP4"
    assert cfg["key"] == "local"


def test_route_llm_text_applies_freetoken_no_thinking(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "freetoken")
    monkeypatch.setenv("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1")
    monkeypatch.setenv("FREETOKEN_MODEL", "Qwen3.6-35B-A3B-NVFP4")
    monkeypatch.setenv("LES_ROUTER_TIMEOUT", "5")
    for key in ("LES_ROUTER_BASE_URL", "LES_ROUTER_MODEL", "LES_ROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"tool":"project_registry"}'}}]}

    def fake_post(url, *, headers, timeout, json):
        captured.update({"url": url, "headers": headers, "timeout": timeout, "json": json})
        return Response()

    monkeypatch.setattr("httpx.post", fake_post)

    result = ar._route_llm_text("route this", max_tokens=40)

    assert result == '{"tool":"project_registry"}'
    assert captured["url"] == "http://127.0.0.1:1919/v1/chat/completions"
    assert captured["json"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["json"]["max_tokens"] == 40


def test_route_with_name_router_unavailable_sentinel(monkeypatch):
    monkeypatch.setenv("LES_ROUTER_PRIMARY", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: (_ for _ in ()).throw(ar.RouterUnavailable("timeout")))
    assert ar.route_with_name("реестр проектов") == ("unavailable", None)


def test_classify_parses_json(monkeypatch):
    # _classify зовёт _route_llm_text (не les_md_service._llm_text) — мокаем реальный путь, без сети
    monkeypatch.setattr(ar, "_route_llm_text", lambda *a, **k: '{"tool": "asbuilt"}')
    assert ar._classify("вытащи объём") == "asbuilt"


def test_classify_bare_name(monkeypatch):
    monkeypatch.setattr(ar, "_route_llm_text", lambda *a, **k: "project_registry")
    assert ar._classify("какие объекты") == "project_registry"


def test_agent_routes_to_tool(monkeypatch):
    monkeypatch.setenv("LES_AGENT_LOOP", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: "project_registry")
    monkeypatch.setattr(
        "proxy.services.project_registry_chat_service.registry_tool_result",
        lambda: {"operation": "project_registry_lookup", "registry": {"projects": []}},
    )
    res = ar.maybe_agent_route("что у нас за объекты")
    assert res["agent_tool"] == "project_registry"
    assert res["tool_result"]["registry"] == {"projects": []}
    assert "answer" not in res


def test_agent_none_tool_falls_back(monkeypatch):
    monkeypatch.setenv("LES_AGENT_LOOP", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: "none")
    assert ar.maybe_agent_route("просто вопрос по нормативам") is None


def test_agent_handler_declines_falls_back(monkeypatch):
    monkeypatch.setenv("LES_AGENT_LOOP", "true")
    monkeypatch.setattr(ar, "_classify", lambda q: "asbuilt")
    monkeypatch.setattr("proxy.services.asbuilt_chat_service.maybe_handle_asbuilt_query",
                        lambda q, project_id=0: None)  # обработчик не смог
    assert ar.maybe_agent_route("вытащи объём без пути") is None
