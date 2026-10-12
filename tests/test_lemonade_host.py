from __future__ import annotations

import importlib

import pytest


def _reload_lemonade_host(monkeypatch, **env):
    for key in (
        "LEMONADE_MODEL",
        "LLM_MODEL",
        "MLX_VAL_MODEL",
        "LEMONADE_VAL_MODEL",
        "LEMONADE_BASE_URL",
        "LEMONADE_URL",
        "LEMONADE_OPENAI_BASE_URL",
        "LEMONADE_API_BASE_URL",
        "LES_LEMONADE_IDLE_UNLOAD_SEC",
    ):
        if key in env:
            monkeypatch.setenv(key, env[key])
        else:
            monkeypatch.delenv(key, raising=False)
    import lemonade_host

    return importlib.reload(lemonade_host)


def test_lemonade_host_default_main_model_is_light(monkeypatch):
    host = _reload_lemonade_host(monkeypatch)

    assert host.LLM_MODEL == "qwen3.5-4b-FLM"


@pytest.mark.parametrize("value,expected", [("", 600), ("bad", 600), ("0", 0), ("45", 45)])
def test_lemonade_idle_unload_env_is_robust(monkeypatch, value, expected):
    host = _reload_lemonade_host(monkeypatch, LES_LEMONADE_IDLE_UNLOAD_SEC=value)

    assert host.IDLE_UNLOAD_SEC == expected


def test_lemonade_url_candidates_accept_api_v1_base(monkeypatch):
    host = _reload_lemonade_host(
        monkeypatch,
        LEMONADE_BASE_URL="http://127.0.0.1:13305/api/v1",
    )

    assert host._openai_candidates("/chat/completions") == [
        "http://127.0.0.1:13305/api/v1/chat/completions",
        "http://127.0.0.1:13305/v1/chat/completions",
    ]
    assert host._api_candidates("/reranking") == [
        "http://127.0.0.1:13305/api/v1/reranking",
    ]


@pytest.mark.asyncio
async def test_lemonade_switch_model_updates_live_main_model(monkeypatch):
    host = _reload_lemonade_host(monkeypatch, LEMONADE_MODEL="qwen3.5-4b-FLM")

    result = await host.switch_model(
        host.SwitchModelRequest(target="main", model="qwen3.5-9b-FLM")
    )

    assert result == {"status": "switched", "target": "main", "model": "qwen3.5-9b-FLM"}
    assert host.LLM_MODEL == "qwen3.5-9b-FLM"


@pytest.mark.asyncio
async def test_lemonade_validate_uses_rules_before_network(monkeypatch):
    host = _reload_lemonade_host(monkeypatch)

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise AssertionError("rules-verifiable validation should not call Lemonade")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(host.httpx, "AsyncClient", FailingClient)

    result = await host.validate_answer(
        host.ValidateRequest(question="Сколько будет 2+2?", answer="4", context="2+2=4")
    )

    assert result["status"] == "VERIFIED"
    assert result["backend"] == "rules"


@pytest.mark.asyncio
async def test_lemonade_health_requires_matching_vendor_evidence_for_loaded_models(monkeypatch):
    host = _reload_lemonade_host(monkeypatch, LEMONADE_MODEL="configured-chat")

    async def vendor_health(*_args, **_kwargs):
        return {"status": "ok", "all_models_loaded": []}

    monkeypatch.setattr(host, "_get_json", vendor_health)

    result = await host.health()

    assert result["status"] == "degraded"
    assert result["reason"] == "required_models_not_ready"
    assert all(
        result[role]["loaded"] is False
        for role in ("main_model", "val_model", "embed_model", "rerank_model")
    )


@pytest.mark.asyncio
async def test_lemonade_embeddings_reject_mismatch_and_attest_exact_identity(monkeypatch):
    host = _reload_lemonade_host(monkeypatch)

    with pytest.raises(host.HTTPException) as mismatch:
        await host.embeddings({"model": "unapproved-embedding", "input": ["x"]})
    assert mismatch.value.status_code == 409
    assert mismatch.value.detail == "embedding_model_mismatch"

    captured = {}

    async def post_embeddings(urls, payload, *, timeout):
        captured["urls"] = urls
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {"data": []}

    monkeypatch.setattr(host, "_post_json", post_embeddings)

    result = await host.embeddings({"model": f"{host.EMBED_MODEL}:latest", "input": ["x"]})

    assert captured["payload"]["model"] == "Qwen3-Embedding-0.6B-GGUF"
    assert result["embedding_model"] == "Qwen3-Embedding-0.6B-GGUF"
    assert result["embedding_backend"] == "llama_cpp"
    assert result["embedding_identity"] == {
        "family": "Qwen/Qwen3-Embedding-0.6B",
        "model": "Qwen3-Embedding-0.6B-GGUF",
        "backend": "llama_cpp",
        "vector_size": 1024,
        "chunk_tokens": 430,
        "chunk_overlap": 50,
    }


@pytest.mark.asyncio
async def test_lemonade_rerank_maps_reranking_response(monkeypatch):
    host = _reload_lemonade_host(monkeypatch)
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "model": "bge-reranker-v2-m3-GGUF",
                "results": [
                    {"index": 1, "relevance_score": 0.92},
                    {"index": 0, "score": 0.13},
                ],
            }

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr(host.httpx, "AsyncClient", FakeClient)

    result = await host.rerank_endpoint(
        host.RerankRequest(
            query="СП 60 вентиляция",
            documents=["шум", "СП 60 про вентиляцию"],
            top_k=2,
        )
    )

    assert captured["url"].endswith("/api/v1/reranking")
    assert captured["json"]["model"] == "bge-reranker-v2-m3-GGUF"
    assert result == {
        "model": "bge-reranker-v2-m3-GGUF",
        "results": [{"index": 1, "score": 0.92}, {"index": 0, "score": 0.13}],
    }


@pytest.mark.asyncio
async def test_lemonade_chat_completions_relays_sse_stream(monkeypatch):
    host = _reload_lemonade_host(monkeypatch)
    chunks = [
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    class FakeStream:
        def raise_for_status(self):
            return None

        async def aiter_bytes(self):
            for chunk in chunks:
                yield chunk

    class FakeStreamContext:
        async def __aenter__(self):
            return FakeStream()

        async def __aexit__(self, *args):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method, url, json=None):
            return FakeStreamContext()

        async def post(self, url, json=None):
            raise AssertionError("stream:true must not go through post/json")

    monkeypatch.setattr(host.httpx, "AsyncClient", FakeClient)

    from starlette.responses import StreamingResponse

    response = await host.chat_completions(
        {"messages": [{"role": "user", "content": "hi"}], "stream": True}
    )

    assert isinstance(response, StreamingResponse)
    body = b""
    async for chunk in response.body_iterator:
        body += chunk if isinstance(chunk, (bytes, bytearray)) else chunk.encode()
    assert b'"content":"Hel"' in body
    assert b"[DONE]" in body


@pytest.mark.asyncio
async def test_lemonade_ps_reports_loaded_models_not_the_catalogue(monkeypatch):
    """`/api/ps` обязан отвечать на вопрос «что сейчас в памяти», а не «что скачано».

    Замер 08.09: при нуле загруженных моделей адаптер отдавал все 13 записей каталога,
    и сборщик метрик выводил «72 ГБ занято моделями» на машине с 31 ГБ ОЗУ.
    """
    host = _reload_lemonade_host(monkeypatch)

    async def vendor(urls, **_kwargs):
        assert any(url.endswith("/health") for url in urls), urls
        return {
            "status": "ok",
            "all_models_loaded": [
                {
                    "model_name": "Qwen3.6-35B-A3B-GGUF-UD-IQ2_XXS-unsloth",
                    "loaded": True,
                    "is_busy": False,
                    "is_streaming": False,
                    "pid": 46984,
                    "recipe": "llamacpp",
                    "last_use": 318879784,
                },
                {
                    "model_name": "Qwen3-Embedding-0.6B-GGUF",
                    "loaded": True,
                    "is_busy": False,
                    "is_streaming": False,
                    "pid": 46152,
                    "recipe": "llamacpp",
                    "last_use": 318852164,
                },
                {"model_name": "выгруженная", "loaded": False},
            ],
        }

    monkeypatch.setattr(host, "_get_json", vendor)

    result = await host.api_ps()
    names = [item["name"] for item in result["models"]]

    assert names == [
        "Qwen3.6-35B-A3B-GGUF-UD-IQ2_XXS-unsloth",
        "Qwen3-Embedding-0.6B-GGUF",
    ]
    assert all(item.get("size") == 0 for item in result["models"]), result["models"]


@pytest.mark.asyncio
async def test_lemonade_ps_returns_empty_list_when_nothing_is_loaded(monkeypatch):
    """Пустая память — пустой список; выдумывать запасную запись нельзя."""
    host = _reload_lemonade_host(monkeypatch)

    async def vendor(*_args, **_kwargs):
        return {"status": "ok", "all_models_loaded": []}

    monkeypatch.setattr(host, "_get_json", vendor)
    assert await host.api_ps() == {"models": []}


@pytest.mark.asyncio
async def test_lemonade_ps_stays_empty_when_vendor_is_unreachable(monkeypatch):
    """Недоступный вендор — не повод объявить модель загруженной."""
    host = _reload_lemonade_host(monkeypatch)

    async def vendor(*_args, **_kwargs):
        raise RuntimeError("vendor down")

    monkeypatch.setattr(host, "_get_json", vendor)
    assert await host.api_ps() == {"models": []}


@pytest.mark.asyncio
async def test_lemonade_chat_uses_role_model_instead_of_environment(monkeypatch):
    """Адаптер перестал быть вторым источником истины о выбранной модели.

    Прежняя редакция затирала модель каждого запроса своим LEMONADE_MODEL, поэтому
    служебные вызовы LES поднимали у вендора вторую 35B-модель рядом с выбранной.
    """
    host = _reload_lemonade_host(
        monkeypatch, LEMONADE_MODEL="Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S"
    )
    monkeypatch.setattr(host, "_role_answer_model", lambda: "role-selected-model")

    async def catalogue(*_args, **_kwargs):
        return {"data": [{"id": "role-selected-model"}, {"id": "qwen3.5-9b-FLM"}]}

    sent: dict[str, object] = {}

    async def capture(_urls, payload, **_kwargs):
        sent.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(host, "_get_json", catalogue)
    monkeypatch.setattr(host, "_post_json", capture)

    # Имя MLX-модели вендору неизвестно — уходит модель роли, а не окружение.
    await host.chat_completions({"model": "mlx-community/Qwen3.5-9B-OptiQ-4bit", "messages": []})
    assert sent["model"] == "role-selected-model"

    # Явно названная и существующая модель больше не переписывается.
    await host.chat_completions({"model": "qwen3.5-9b-FLM", "messages": []})
    assert sent["model"] == "qwen3.5-9b-FLM"


@pytest.mark.asyncio
async def test_lemonade_chat_falls_back_to_environment_without_registry(monkeypatch):
    """Без реестра остаётся прежнее поведение — но именно как запасное."""
    host = _reload_lemonade_host(monkeypatch, LEMONADE_MODEL="configured-chat")
    monkeypatch.setattr(host, "_role_answer_model", lambda: "")

    async def catalogue(*_args, **_kwargs):
        raise RuntimeError("vendor down")

    sent: dict[str, object] = {}

    async def capture(_urls, payload, **_kwargs):
        sent.update(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(host, "_get_json", catalogue)
    monkeypatch.setattr(host, "_post_json", capture)

    await host.chat_completions({"model": "", "messages": []})
    assert sent["model"] == "configured-chat"


@pytest.mark.asyncio
async def test_lemonade_health_reports_the_role_model_as_main(monkeypatch):
    """Health обязан называть выбранную роль, а не устаревшее имя из окружения."""
    host = _reload_lemonade_host(monkeypatch, LEMONADE_MODEL="stale-env-model")
    monkeypatch.setattr(host, "_role_answer_model", lambda: "role-selected-model")

    async def vendor_health(*_args, **_kwargs):
        return {"status": "ok", "all_models_loaded": []}

    monkeypatch.setattr(host, "_get_json", vendor_health)

    result = await host.health()
    assert result["main_model"]["path"] == "role-selected-model"


@pytest.mark.asyncio
async def test_validation_never_sends_a_model_the_vendor_does_not_know(monkeypatch):
    """Валидатор шлёт имя из каталога вендора, иначе запрос отвергается.

    Роль валидатора хранит историческое MLX-имя `mlx-community/Qwen3.5-4B-OptiQ-4bit`.
    Опыт на живом стенде 18.09: вендор отвечает на него 404 model_not_found, то есть
    валидация падала бы на каждом вызове. Правило то же, что у чата (см. role_model).
    """
    host = _reload_lemonade_host(
        monkeypatch,
        MLX_VAL_MODEL="mlx-community/Qwen3.5-4B-OptiQ-4bit",
        LEMONADE_MODEL="Qwen3.6-35B-A3B-GGUF-UD-IQ2_M",
    )
    sent = {}

    async def vendor_models():
        return ["Qwen3.6-35B-A3B-GGUF-UD-IQ2_M", "qwen3.5-9b-FLM"]

    async def post_json(urls, payload, timeout=None):
        sent.update(payload)
        return {"choices": [{"message": {"content": "VERIFIED"}}]}

    monkeypatch.setattr(host, "_vendor_model_ids", vendor_models)
    monkeypatch.setattr(host, "_post_json", post_json)
    monkeypatch.setattr(host, "_role_answer_model", lambda: "Qwen3.6-35B-A3B-GGUF-UD-IQ2_M")

    await host.validate_answer(
        host.ValidateRequest(
            question="Какой норматив выбран?",
            answer="Выбран норматив накладных расходов для монтажных работ.",
            context="Карточка описывает порядок хранения кабельной продукции на складе.",
        )
    )

    assert sent["model"] == "Qwen3.6-35B-A3B-GGUF-UD-IQ2_M"
