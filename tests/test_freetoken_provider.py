import importlib.util
import inspect
import json

import httpx

import pytest

from backend.inference.routing import decide_provider, is_cloud_provider
from proxy.routers.chat import _llm_runtime
from proxy.services import llm_transport_profile_service as transport_profile
from proxy.services.llm_transport_profile_service import (
    apply_transport_options,
    fit_prompt_sections,
    provider_prompt_max_chars,
    provider_is_local,
)
from proxy.services.runtime_admission import chat_memory_guard_for_provider
from proxy.services import smeta_chat_adapter_service as smeta_adapter
from sovushka.components.header import _smeta_runtime_settings, build_header


def test_freetoken_cache_reconciler_rebuilds_physical_kv_to_configured_target():
    spec = importlib.util.find_spec("proxy.services.freetoken_cache_profile_service")
    assert spec is not None, "FreeToken physical cache reconciler is missing"

    from proxy.services.freetoken_cache_profile_service import reconcile_freetoken_cache

    requests: list[tuple[str, str]] = []
    posted_bodies: list[dict] = []

    def handler(request):
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={
                "state": "serving",
                "geometry": {
                    "num_pages": 8226,
                    "moe_cache_size": 900,
                    "num_mamba_slots": 24,
                    "num_swa_pages": 0,
                    "cache_budget_bytes": 3376257433,
                    "unit_bytes": {
                        "kv_per_token": 20480,
                        "moe_per_expert": 1775616,
                        "mamba_per_slot": 64389120,
                        "swa_per_token": 0,
                    },
                    "limits": {"moe_experts": {"min": 256, "max": 1901}},
                },
            })
        posted_bodies.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={
            "status": "ok", "num_pages": 30000, "moe_cache_size": 600,
            "mamba_slots": 24, "num_swa_pages": 0,
        })

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = reconcile_freetoken_cache(
            "http://127.0.0.1:1919/v1", 30000, client=client
        )

    assert result["status"] == "synchronized"
    assert result["desired_kv_tokens"] == 30000
    assert result["effective_kv_tokens"] == 30000
    assert requests == [("GET", "/v1/cache/status"), ("POST", "/v1/cache/rebuild")]
    assert "num_swa_pages" not in posted_bodies[0]


def test_freetoken_transport_disables_thinking_without_mutating_input():
    original = {"model": "Qwen3.6-35B-A3B-NVFP4", "max_tokens": 400}

    result = apply_transport_options(original, "freetoken")

    assert result == {
        "model": "Qwen3.6-35B-A3B-NVFP4",
        "max_tokens": 400,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert original == {"model": "Qwen3.6-35B-A3B-NVFP4", "max_tokens": 400}


def test_freetoken_stream_reads_reasoning_content_delta():
    delta = {"content": "", "reasoning_content": "Готово"}

    parser = getattr(transport_profile, "assistant_delta_text", None)
    assert callable(parser), "shared stream delta parser is missing"
    assert parser(delta) == "Готово"


def test_freetoken_transport_preserves_other_template_options():
    original = {"chat_template_kwargs": {"custom_flag": "kept"}}

    result = apply_transport_options(original, "freetoken")

    assert result["chat_template_kwargs"] == {
        "custom_flag": "kept",
        "enable_thinking": False,
    }


def test_freetoken_is_local_for_privacy_and_memory_routing(monkeypatch):
    assert provider_is_local("freetoken") is True
    assert is_cloud_provider("freetoken") is False
    route = decide_provider("freetoken", ["P0"], consent=False)
    assert route.provider == "freetoken"
    assert route.downgraded is False

    monkeypatch.setenv("LES_LLM_PROVIDER", "freetoken")
    monkeypatch.setenv("LES_CHAT_MEMORY_GUARD", "true")
    assert chat_memory_guard_for_provider() is True


def test_llm_runtime_resolves_freetoken_environment(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "freetoken")
    monkeypatch.setenv("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1")
    monkeypatch.setenv("FREETOKEN_MODEL", "Qwen3.6-35B-A3B-NVFP4")
    monkeypatch.delenv("FREETOKEN_API_KEY", raising=False)

    runtime = _llm_runtime()

    assert runtime.provider == "freetoken"
    assert runtime.base_url == "http://127.0.0.1:1919/v1"
    assert runtime.chat_url == "http://127.0.0.1:1919/v1/chat/completions"
    assert runtime.model == "Qwen3.6-35B-A3B-NVFP4"
    assert runtime.api_key == ""
    assert runtime.supports_validation is False


def test_smeta_runtime_inherits_active_freetoken_without_stale_model_override(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "freetoken")
    monkeypatch.setenv("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1")
    monkeypatch.setenv("FREETOKEN_MODEL", "Qwen3.6-35B-A3B-NVFP4")
    monkeypatch.delenv("LES_SMETA_DOCUMENT_PROVIDER", raising=False)
    monkeypatch.setenv("LES_SMETA_DOCUMENT_MODEL", "qwen3.5:9b")

    runtime = smeta_adapter._smeta_model_runtime("LES_SMETA_DOCUMENT_PROVIDER")

    assert runtime.provider == "freetoken"
    assert runtime.base_url == "http://127.0.0.1:1919/v1"
    assert runtime.chat_url == "http://127.0.0.1:1919/v1/chat/completions"
    assert runtime.model == "Qwen3.6-35B-A3B-NVFP4"


def test_native_smeta_settings_inherit_the_active_runtime():
    assert _smeta_runtime_settings("native", "qwen3.5:9b") == {
        "smeta_document_provider": "",
        "smeta_document_model": "",
    }


def test_settings_ui_exposes_the_effective_freetoken_runtime():
    source = inspect.getsource(build_header)

    assert '"freetoken": "FreeToken — локально"' in source
    assert '"Адрес FreeToken"' in source
    assert '"Модель FreeToken"' in source
    assert 'providers.get("freetoken")' in source
    assert '"freetoken_base_url": set_freetoken_url.value' in source
    assert '"freetoken_model": set_freetoken_model.value' in source


def test_freetoken_prompt_limit_reserves_generation_context(monkeypatch):
    monkeypatch.setenv("FREETOKEN_CONTEXT_TOKENS", "8253")
    monkeypatch.delenv("FREETOKEN_PROMPT_MAX_CHARS", raising=False)
    monkeypatch.delenv("FREETOKEN_PROMPT_CHARS_PER_TOKEN", raising=False)

    assert provider_prompt_max_chars("freetoken") == 14106

    monkeypatch.setenv("FREETOKEN_PROMPT_MAX_CHARS", "7000")
    assert provider_prompt_max_chars("freetoken") == 7000


def test_freetoken_prompt_budget_derives_from_operator_context_window():
    derive = getattr(transport_profile, "freetoken_prompt_chars_for_context", None)

    assert callable(derive), "capacity-derived FreeToken prompt budget is missing"
    assert derive(8253) == 14106
    assert derive(30000) == 57600


def test_freetoken_default_prompt_fit_keeps_multi_document_evidence(monkeypatch):
    monkeypatch.setenv("FREETOKEN_CONTEXT_TOKENS", "8253")
    monkeypatch.delenv("FREETOKEN_PROMPT_MAX_CHARS", raising=False)
    monkeypatch.delenv("FREETOKEN_PROMPT_CHARS_PER_TOKEN", raising=False)
    evidence = "\n\n".join(
        f"[Источник {index} | file-{index}.pdf]:\n" + (f"Факт {index}. " * 90)
        for index in range(1, 9)
    )
    question = "Вопрос: Дай обзор проекта по найденным материалам."

    fitted, trace = fit_prompt_sections(
        [("evidence", evidence)],
        required_tail=question,
        max_chars=provider_prompt_max_chars("freetoken") - 4910,
    )

    assert "[Источник 8 | file-8.pdf]" in fitted
    assert fitted.endswith(question)
    assert trace["sections"]["evidence"] > 3906


def test_prompt_fitter_omits_oversized_whole_source_and_keeps_question():
    evidence = "[Источник 1] Паспорт клапана\n" + ("EI60 подтверждено. " * 8000)
    question = "Вопрос: Какой предел огнестойкости применять?"

    fitted, trace = fit_prompt_sections(
        [
            ("evidence", evidence),
            ("navigation", "Карта проекта " * 3000),
        ],
        required_tail=question,
        max_chars=5000,
    )

    assert len(fitted) <= 5000
    assert "[Источник 1]" not in fitted
    assert fitted.endswith(question)
    assert trace["truncated"] is True
    assert trace["output_chars"] == len(fitted)
    assert trace["omissions"][0]["cursor"].startswith("ctx:evidence:")


@pytest.mark.asyncio
async def test_disabled_reranker_is_not_loaded_during_warmup(monkeypatch):
    from proxy import app

    monkeypatch.setenv("RERANKER_ENABLED", "false")

    def unexpected_load():
        raise AssertionError("disabled reranker must not be instantiated")

    monkeypatch.setattr(app, "_select_reranker_cls", unexpected_load)

    assert await app._warmup_reranker() is False
