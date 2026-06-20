"""Offline tests for async extraction + provider wiring (no network)."""

from __future__ import annotations

import asyncio
import json

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
