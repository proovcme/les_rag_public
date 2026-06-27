"""W11.17b — MCP-сервер ЛЕС: каталог инструментов + сборка сервера."""

from __future__ import annotations

import asyncio

import pytest

import tools.les_mcp_server as m

# Ядро compute-инструментов, которое НЕ должно ломаться при росте каталога.
_CORE = {
    "les_table_sum", "les_reconcile", "les_bor",
    "les_spec_to_bor", "les_project_summary", "les_form_generate",
    "les_price_lookup", "les_glossary", "les_kac", "les_stesnennost",
    "les_lsr_assemble", "les_gesn_expand", "les_table_agg", "les_gesn_fetch",
}
# Ярус 3 — action-инструменты (меняют состояние).
_ACTIONS = {"les_smeta_save", "les_journal_append"}


def test_manifest_lists_all_tools():
    names = {t["name"] for t in m.manifest()}
    assert names == set(m.TOOLS)              # манифест == источник истины (каталог)
    assert _CORE <= names                      # 14 compute-инструментов не потеряны
    assert _ACTIONS <= names                   # action-инструменты добавлены
    assert all(t["description"] for t in m.manifest())


def test_build_server_registers_tools():
    pytest.importorskip("mcp")  # сервер требует пакет mcp; без него — скип
    server = m.build_server()
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == set(m.TOOLS)
    assert (_CORE | _ACTIONS) <= {t.name for t in tools}


def test_tool_wrappers_no_llm():
    import inspect

    src = inspect.getsource(m)
    for marker in ("import openai", "/v1/chat/completions", "/api/chat"):
        assert marker not in src
