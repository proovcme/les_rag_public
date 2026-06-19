"""Команды чата (/-палитра) — W11.17.

«Как у взрослых»: набор именованных команд, которые ЛЕС понимает и исполняет. Часть —
создаёт документы (спецификация/ВОР/смета/акт) через сервис форм; часть — алиасы к
естественно-языковым интентам (сводка/сверка); МСП (MS Project) — заглушка. 0 LLM на разбор.

Команда возвращает один из вариантов:
- {"answer": str, "command": {...}}  — детерминированный ответ (+ опц. действие для GUI);
- {"rewrite": str}                   — переформулировать вопрос и пропустить через обычный конвейер.
"""

from __future__ import annotations

from typing import Any

# Назначение документов — чтобы машина «понимала», что это такое (краткая суть).
_DOC_PURPOSE = {
    "spec_gost21110": "перечень оборудования, изделий и материалов для комплектации и монтажа",
    "vor": "наименования и объёмы строительно-монтажных работ (основа для сметы)",
    "smeta_lsr": "стоимость работ и затрат по объекту (локальный сметный расчёт)",
    "aosr": "освидетельствование скрытых работ перед закрытием (исполнительная документация)",
}

# Реестр команд. kind: form | rewrite | stub | help.
COMMANDS: tuple[dict[str, Any], ...] = (
    {"cmd": "/спецификация", "aliases": ("/спека", "/spec"), "kind": "form", "form": "spec_gost21110",
     "title": "Спецификация (ГОСТ 21.110)", "desc": "Бланк спецификации оборудования/материалов"},
    {"cmd": "/вор", "aliases": ("/ведомость",), "kind": "form", "form": "vor",
     "title": "Ведомость объёмов работ", "desc": "Бланк ВОР (наименования работ + объёмы)"},
    {"cmd": "/смета", "aliases": ("/лср", "/smeta"), "kind": "form", "form": "smeta_lsr",
     "title": "Локальная смета (ЛСР)", "desc": "Бланк сметы по Методике 421/пр"},
    {"cmd": "/акт", "aliases": ("/аоср", "/aosr"), "kind": "form", "form": "aosr",
     "title": "Акт скрытых работ (АОСР)", "desc": "Акт освидетельствования скрытых работ"},
    {"cmd": "/сводка", "aliases": ("/тэп",), "kind": "rewrite", "rewrite": "дай сводку проекта",
     "title": "Сводка проекта", "desc": "Стадия, ТЭП, состав документов"},
    {"cmd": "/сверка", "aliases": ("/сверь",), "kind": "rewrite", "rewrite": "сверь ведомости и акты, где расхождения",
     "title": "Сверка документов", "desc": "ВОР ↔ КС-2 ↔ смета ↔ ИД по количествам"},
    {"cmd": "/мсп", "aliases": ("/mcp", "/mcp-server", "/мсп-сервер"), "kind": "stub",
     "title": "MCP-сервер ЛЕС", "desc": "Инструменты ЛЕС наружу по Model Context Protocol (готов)"},
    {"cmd": "/команды", "aliases": ("/help", "/?", "/команда"), "kind": "help",
     "title": "Список команд", "desc": "Показать все команды"},
)

_BY_NAME: dict[str, dict[str, Any]] = {}
for _c in COMMANDS:
    _BY_NAME[_c["cmd"]] = _c
    for _a in _c.get("aliases", ()):
        _BY_NAME[_a] = _c


def is_command(question: str) -> bool:
    return (question or "").strip().startswith("/")


def list_commands() -> list[dict[str, str]]:
    """Для GUI-палитры: команда + ярлык + описание (без алиасов и внутренних полей)."""
    return [{"cmd": c["cmd"], "title": c["title"], "desc": c["desc"]} for c in COMMANDS]


def _explain_doc(form_id: str) -> str:
    from proxy.services.forms_service import load_descriptor

    d = load_descriptor(form_id) or {}
    title = d.get("title", form_id)
    basis = d.get("legal_basis", "")
    purpose = _DOC_PURPOSE.get(form_id, "")
    cols = d.get("columns", []) or []
    parts = [f"**{title}**"]
    if purpose:
        parts.append(f"Назначение: {purpose}.")
    if basis:
        parts.append(f"Основание: {basis}.")
    if cols:
        parts.append("Графы: " + " · ".join(cols) + ".")
    parts.append("Генерирую бланк xlsx — скачается; для docx/html — Инструменты → Формы.")
    return "\n".join(parts)


def _help_text() -> str:
    lines = ["Команды ЛЕС (можно набрать в чате или выбрать в «/»-меню):"]
    for c in COMMANDS:
        al = (" · " + ", ".join(c["aliases"])) if c.get("aliases") else ""
        lines.append(f"  {c['cmd']}{al} — {c['desc']}")
    return "\n".join(lines)


def handle_command(question: str, *, project_id: int | None = None) -> dict[str, Any] | None:
    """Разобрать и исполнить команду. None — если это не команда."""
    text = (question or "").strip()
    if not text.startswith("/"):
        return None
    token = text.split()[0].lower()
    entry = _BY_NAME.get(token)
    if entry is None:
        return {"answer": f"Неизвестная команда «{token}». Набери /команды — покажу список.",
                "command": {"action": "unknown"}}

    kind = entry["kind"]
    if kind == "rewrite":
        return {"rewrite": entry["rewrite"]}
    if kind == "help":
        return {"answer": _help_text(), "command": {"action": "help", "commands": list_commands()}}
    if kind == "stub":
        return {
            "answer": ("✅ MCP-сервер ЛЕС готов — инструменты доступны внешним агентам по Model "
                       "Context Protocol (Claude Code/Desktop, IDE):\n"
                       "  • les_table_sum — счёт по таблицам (суммы/кол-ва из Parquet);\n"
                       "  • les_reconcile — сверка ВОР↔КС-2↔смета↔ИД по количествам;\n"
                       "  • les_bor / les_spec_to_bor — ВОР (свод и работы из спецификации);\n"
                       "  • les_project_summary — сводка проекта (ТЭП/стадии/состав);\n"
                       "  • les_form_generate — генерация спецификации/ВОР/сметы/АОСР.\n"
                       "Запуск: uv run python tools/les_mcp_server.py (stdio). Регистрация в MCP-клиенте:\n"
                       '  {"mcpServers":{"les":{"command":"uv","args":["run","python",'
                       '"tools/les_mcp_server.py"],"cwd":"/Users/ovc/LES"}}}'),
            "command": {"action": "mcp_info", "feature": "mcp_server"},
        }
    if kind == "form":
        form_id = entry["form"]
        return {
            "answer": _explain_doc(form_id),
            "command": {"action": "generate_form", "form_id": form_id, "fmt": "xlsx",
                        "title": entry["title"]},
        }
    return None
