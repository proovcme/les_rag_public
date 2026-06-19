"""MCP-сервер ЛЕС — выставляет детерминированные инструменты наружу по Model Context Protocol.

Внешние агенты (Claude, IDE, любой MCP-клиент) вызывают инструменты ЛЕС как tools; числа/
факты считает код ЛЕС (ADR-11), агент только оркеструет. Транспорт — stdio (FastMCP).

Запуск:
    uv run python tools/les_mcp_server.py            # stdio-сервер (запускает MCP-клиент)
    uv run python tools/les_mcp_server.py --list      # показать каталог инструментов

Регистрация в Claude Code / Desktop (пример MCP-клиента):
    { "mcpServers": { "les": { "command": "uv", "args": ["run","python","tools/les_mcp_server.py"],
                               "cwd": "/Users/ovc/LES" } } }

Импорт FastMCP — ленивый (в build_server), чтобы модуль читался без пакета `mcp`
(для манифеста/тестов). Сервисы ЛЕС импортируются внутри инструментов.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_STORAGE = Path("storage/datasets")


# ── инструменты: тонкие обёртки к существующим сервисам ЛЕС (0 LLM) ──

def les_table_sum(question: str, dataset_ids: list[str]) -> dict[str, Any]:
    """Сумма/количество по таблицам датасетов — детерминированно по Parquet, без LLM.

    question — что считать («сколько кабеля 3х1,5»); dataset_ids — где (id датасетов).
    """
    from proxy.services.table_query_service import maybe_answer_table_query, parquet_ref_chunks_for_datasets

    chunks = parquet_ref_chunks_for_datasets(dataset_ids, storage_root=_STORAGE)
    res = maybe_answer_table_query(question, chunks, storage_root=_STORAGE)
    return res.payload() if res else {"answer": None, "note": "не распознан табличный запрос"}


def les_reconcile(dataset_ids: list[str]) -> dict[str, Any]:
    """Сверка количеств между документами (ВОР↔КС-2↔смета↔ИД) по оси документа."""
    from proxy.services.reconcile_service import reconcile_datasets

    return reconcile_datasets(dataset_ids, storage_root=_STORAGE, by="dataset")


def les_bor(dataset_id: str) -> dict[str, Any]:
    """Свод ВОР из спецификаций датасета."""
    from proxy.services.bor_service import generate_bor

    return generate_bor(dataset_id, storage_root=_STORAGE)


def les_spec_to_bor(dataset_id: str) -> dict[str, Any]:
    """ВОР работ из спецификации (форма 9 ГОСТ 21.110)."""
    from proxy.services.spec_to_bor_service import generate_spec_bor

    return generate_spec_bor(dataset_id, storage_root=_STORAGE)


def les_project_summary(dataset_ids: list[str]) -> dict[str, Any]:
    """Сводка проекта: стадия (ПД/РД) + ТЭП + состав документов."""
    from proxy.services.project_summary_service import build_project_summary

    return build_project_summary(dataset_ids, storage_root=_STORAGE)


def les_form_generate(form_id: str, fmt: str = "xlsx", project_id: int | None = None) -> dict[str, Any]:
    """Сгенерировать типовую форму (spec_gost21110 / vor / smeta_lsr / aosr) в html/xlsx/docx."""
    from proxy.services.forms_service import generate

    out = generate(form_id, fmt, project_id=project_id)
    return {"form_id": form_id, "fmt": fmt, "path": out.get("path"), "html": out.get("html")}


# Каталог: имя инструмента → (описание, функция). Источник истины для сервера и манифеста.
TOOLS: dict[str, tuple[str, Any]] = {
    "les_table_sum": ("Сумма/кол-во по таблицам (Parquet), без LLM", les_table_sum),
    "les_reconcile": ("Сверка ВОР↔КС-2↔смета↔ИД по количествам", les_reconcile),
    "les_bor": ("Свод ВОР из спецификаций", les_bor),
    "les_spec_to_bor": ("ВОР работ из спецификации (форма 9)", les_spec_to_bor),
    "les_project_summary": ("Сводка проекта: ТЭП/стадии/состав", les_project_summary),
    "les_form_generate": ("Генерация формы: спецификация/ВОР/смета/АОСР", les_form_generate),
}


def manifest() -> list[dict[str, str]]:
    """Каталог инструментов (для диагностики/манифеста)."""
    return [{"name": name, "description": desc} for name, (desc, _fn) in TOOLS.items()]


def build_server():
    """Собрать FastMCP-сервер с зарегистрированными инструментами ЛЕС."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("les-rag")
    for name, (desc, fn) in TOOLS.items():
        server.tool(name=name, description=desc)(fn)
    return server


def main() -> None:
    if "--list" in sys.argv:
        print("MCP-сервер ЛЕС · инструменты:")
        for item in manifest():
            print(f"  • {item['name']} — {item['description']}")
        return
    try:
        server = build_server()
    except ImportError:
        print("Пакет 'mcp' не установлен. Установка: uv add mcp (в рантайм — uv pip install mcp).",
              file=sys.stderr)
        sys.exit(1)
    server.run()  # stdio-транспорт по умолчанию


if __name__ == "__main__":
    main()
