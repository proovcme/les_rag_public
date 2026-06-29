"""Offline tests for async extraction + provider wiring (no network)."""

from __future__ import annotations

import asyncio
import json
import sys

from proxy.services import extract_service as svc
from proxy.services import structured_extract as se


SCHEMA = {
    "type": "object",
    "required": ["poz", "qty"],
    "properties": {"poz": {"type": "integer"}, "qty": {"type": "number"}},
}


def _ascripted(replies):
    it = iter(replies)
    seen = []

    async def call(prompt, response_format):
        seen.append((prompt, response_format))
        return next(it)

    call.seen = seen
    return call


def test_aextract_valid_first_try():
    call = _ascripted(['{"poz": 1, "qty": 5}'])
    res = asyncio.run(se.aextract(SCHEMA, "i", "doc", call))
    assert res.ok and res.attempts == 1 and res.data["qty"] == 5


def test_aextract_repairs():
    call = _ascripted(['{"poz": 1}', '{"poz": 1, "qty": 9}'])
    res = asyncio.run(se.aextract(SCHEMA, "i", "doc", call, max_attempts=3))
    assert res.ok and res.attempts == 2
    assert "не прошёл валидацию" in call.seen[1][0]


def test_endpoint_cloud_vs_mlx(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    url, model, headers, is_cloud = svc._endpoint()
    assert is_cloud and "Authorization" in headers and model == "gpt-5.4-mini"

    monkeypatch.setenv("LES_LLM_PROVIDER", "mlx")
    url2, _m, headers2, is_cloud2 = svc._endpoint()
    assert is_cloud2 is False and "Authorization" not in headers2 and "/v1/chat/completions" in url2


def test_needs_completion_tokens():
    assert svc._needs_completion_tokens("gpt-5.4-mini") is True
    assert svc._needs_completion_tokens("o3") is True
    assert svc._needs_completion_tokens("qwen3.5-4b") is False


def test_extract_max_tokens_env(monkeypatch):
    monkeypatch.delenv("LES_EXTRACT_MAX_TOKENS", raising=False)
    assert svc._max_tokens() == 8192
    monkeypatch.setenv("LES_EXTRACT_MAX_TOKENS", "128")
    assert svc._max_tokens() == 256
    monkeypatch.setenv("LES_EXTRACT_MAX_TOKENS", "8192")
    assert svc._max_tokens() == 8192
    monkeypatch.setenv("LES_EXTRACT_MAX_TOKENS", "nope")
    assert svc._max_tokens() == 8192


def test_request_body_tunes_gpt5_for_structured_json(monkeypatch):
    monkeypatch.delenv("LES_EXTRACT_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LES_EXTRACT_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("LES_EXTRACT_VERBOSITY", raising=False)
    body = svc._request_body("p", "gpt-5.2", {"type": "json_object"})
    assert body["max_completion_tokens"] == 8192
    assert "max_tokens" not in body
    assert body["reasoning_effort"] == "minimal"
    assert body["verbosity"] == "low"


def test_request_body_can_disable_gpt5_tuning(monkeypatch):
    monkeypatch.setenv("LES_EXTRACT_REASONING_EFFORT", "low")
    monkeypatch.setenv("LES_EXTRACT_VERBOSITY", "medium")
    body = svc._request_body("p", "gpt-5.2", None, include_tuning=False)
    assert "reasoning_effort" not in body
    assert "verbosity" not in body
    assert body["max_completion_tokens"] == 8192


def test_request_body_prefixes_no_think_for_local_structured_calls():
    body = svc._request_body("Верни JSON", "mlx-community/Qwen3.5-9B-MLX-4bit", None, local_no_think=True)
    assert body["messages"][0]["content"].startswith("/no_think\n")

    already = svc._request_body("/no_think\nВерни JSON", "mlx-community/Qwen3.5-9B-MLX-4bit", None, local_no_think=True)
    assert already["messages"][0]["content"].count("/no_think") == 1


def test_message_content_handles_list_content():
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": '{"poz": 1,'},
                        {"type": "text", "text": '"qty": 3}'},
                    ]
                }
            }
        ]
    }
    assert svc._message_content(payload) == '{"poz": 1,\n"qty": 3}'


def test_provider_call_retries_without_gpt5_tuning_on_400(monkeypatch):
    monkeypatch.setattr(svc, "_endpoint", lambda: ("http://x/v1/chat/completions", "gpt-5.2", {}, True))
    posts = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"status {self.status_code}")

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json, headers):
            posts.append(json)
            if len(posts) == 1:
                return FakeResponse(400, {})
            return FakeResponse(200, {"choices": [{"message": {"content": '{"poz": 1, "qty": 5}'}}]})

    httpx = sys.modules.get("httpx")
    if httpx is None:
        import httpx as httpx_module

        httpx = httpx_module
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    out = asyncio.run(svc._provider_call("p", None))
    assert out == '{"poz": 1, "qty": 5}'
    assert posts[0]["reasoning_effort"] == "minimal"
    assert posts[0]["verbosity"] == "low"
    assert "reasoning_effort" not in posts[1]
    assert "verbosity" not in posts[1]


def test_run_structured_extraction_uses_provider_call(monkeypatch):
    # Cloud → use_cloud_response_format True → _provider_call receives a response_format.
    monkeypatch.setattr(svc, "_endpoint", lambda: ("http://x/v1/chat/completions", "gpt-5.4-mini", {}, True))
    seen = {}

    async def fake_call(prompt, response_format):
        seen["rf"] = response_format
        return json.dumps({"poz": 1, "qty": 7})

    monkeypatch.setattr(svc, "_provider_call", fake_call)
    res = asyncio.run(svc.run_structured_extraction(SCHEMA, "i", "doc"))
    assert res.ok and res.data["qty"] == 7
    assert seen["rf"] is not None and seen["rf"]["type"] == "json_schema"


def test_run_structured_extraction_falls_back_when_cloud_structured_returns_no_json(monkeypatch):
    monkeypatch.setattr(svc, "_endpoint", lambda: ("http://x/v1/chat/completions", "gpt-5.4-mini", {}, True))
    seen = []

    async def fake_call(prompt, response_format):
        seen.append(response_format)
        if response_format is not None:
            return "не json"
        return json.dumps({"poz": 1, "qty": 11})

    monkeypatch.setattr(svc, "_provider_call", fake_call)
    res = asyncio.run(svc.run_structured_extraction(SCHEMA, "i", "doc", max_attempts=1))
    assert res.ok and res.data["qty"] == 11
    assert seen == [seen[0], None]
    assert seen[0] is not None and seen[0]["type"] == "json_schema"


def test_run_structured_extraction_transport_error(monkeypatch):
    monkeypatch.setattr(svc, "_endpoint", lambda: ("http://x", "m", {}, False))

    async def boom(prompt, response_format):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(svc, "_provider_call", boom)
    res = asyncio.run(svc.run_structured_extraction(SCHEMA, "i", "doc"))
    assert res.ok is False and any("provider error" in e for e in res.errors)


def test_router_handler(monkeypatch):
    from proxy.routers import extract as extract_router

    async def fake_run(schema, instruction, context, *, max_attempts=3):
        return se.ExtractResult(ok=True, data={"poz": 1, "qty": 3}, attempts=1, errors=[])

    monkeypatch.setattr(extract_router.extract_service, "run_structured_extraction", fake_run)
    req = extract_router.StructuredExtractRequest(schema=SCHEMA, context="doc")
    out = asyncio.run(extract_router.structured(req))
    assert out["ok"] is True and out["data"]["qty"] == 3 and out["attempts"] == 1
