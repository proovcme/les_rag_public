"""W11.17b — MCP-сервер ЛЕС: каталог инструментов + сборка сервера."""

from __future__ import annotations

import asyncio

import pytest

import tools.les_mcp_server as m

_EXPECTED = {
    "les_table_sum", "les_reconcile", "les_bor",
    "les_spec_to_bor", "les_project_summary", "les_form_generate",
}


def test_manifest_lists_all_tools():
    names = {t["name"] for t in m.manifest()}
    assert names == _EXPECTED
    assert all(t["description"] for t in m.manifest())


def test_build_server_registers_tools():
    pytest.importorskip("mcp")  # сервер требует пакет mcp; без него — скип
    server = m.build_server()
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == _EXPECTED


def test_tool_wrappers_no_llm():
    import inspect

    src = inspect.getsource(m)
    for marker in ("import openai", "/v1/chat/completions", "/api/chat"):
        assert marker not in src
