"""W11.17 — /-команды чата. Pure-разбор, без LLM."""

from __future__ import annotations

from proxy.services.command_service import handle_command, is_command, list_commands


def test_is_command():
    assert is_command("/спецификация")
    assert is_command("  /вор ")
    assert not is_command("сделай вор")


def test_form_command_returns_generate_action():
    r = handle_command("/спецификация")
    assert r["command"]["action"] == "generate_form"
    assert r["command"]["form_id"] == "spec_gost21110"
    assert "ГОСТ 21.110" in r["answer"]  # машина «понимает» документ (основание)


def test_form_aliases():
    assert handle_command("/спека")["command"]["form_id"] == "spec_gost21110"
    assert handle_command("/лср")["command"]["form_id"] == "smeta_lsr"
    assert handle_command("/аоср")["command"]["form_id"] == "aosr"


def test_rewrite_command():
    r = handle_command("/сводка")
    assert r.get("rewrite") == "дай сводку проекта"
    assert "answer" not in r


def test_mcp_stub_not_msproject():
    r = handle_command("/мсп")
    assert r["command"]["feature"] == "mcp_server"
    assert "MCP" in r["answer"]
    assert "MS Project" not in r["answer"]  # это НЕ MS Project


def test_help_lists_commands():
    r = handle_command("/команды")
    assert r["command"]["action"] == "help"
    assert "/спецификация" in r["answer"] and "/мсп" in r["answer"]


def test_unknown_command():
    r = handle_command("/абракадабра")
    assert r["command"]["action"] == "unknown"


def test_not_a_command_returns_none():
    assert handle_command("сколько кабеля") is None


def test_list_commands_shape():
    cmds = list_commands()
    ids = {c["cmd"] for c in cmds}
    assert {"/спецификация", "/вор", "/смета", "/акт", "/сводка", "/сверка", "/мсп", "/команды"} <= ids
    assert all("desc" in c and "title" in c for c in cmds)
