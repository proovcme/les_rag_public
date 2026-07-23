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
async def test_lemonade_rerank_maps_reranking_response(monkeypatch):
    host = _reload_lemonade_host(monkeypatch)
    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "model": "Qwen3-Reranker-0.6B-Q8_0-GGUF",
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
    assert captured["json"]["model"] == "Qwen3-Reranker-0.6B-Q8_0-GGUF"
    assert result == {
        "model": "Qwen3-Reranker-0.6B-Q8_0-GGUF",
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
