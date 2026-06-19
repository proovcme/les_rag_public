"""MCP-сервер ЛЕС — ЗАГЛУШКА/КАРКАС (W11.17).

Идея: выставить детерминированные инструменты ЛЕС наружу по Model Context Protocol,
чтобы внешние агенты (Claude и др.) вызывали их как tools. Числа/факты считает код
ЛЕС (ADR-11), агент только оркестрирует.

СТАТУС: каркас. Каталог инструментов и тонкие обёртки к существующим сервисам готовы;
транспорт MCP (stdio) НЕ подключён (нужен пакет `mcp` — ставить по одобрению). Запуск
сейчас печатает статус и список инструментов, реальный сервер не поднимает.

Подключение транспорта (когда решим ставить `mcp`):
    uv add mcp        # по одобрению
    # затем в main(): from mcp.server.fastmcp import FastMCP; зарегистрировать TOOLS и server.run()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

_STORAGE = Path("storage/datasets")


# ── тонкие обёртки к существующим сервисам (числа считает ЛЕС, 0 LLM) ──

def tool_table_sum(question: str, dataset_ids: list[str]) -> dict[str, Any]:
    """Сумма/количество по таблицам датасетов (детерминированно по Parquet)."""
    from proxy.services.table_query_service import maybe_answer_table_query, parquet_ref_chunks_for_datasets

    chunks = parquet_ref_chunks_for_datasets(dataset_ids, storage_root=_STORAGE)
    res = maybe_answer_table_query(question, chunks, storage_root=_STORAGE)
    return res.payload() if res else {"answer": None, "note": "не распознан табличный запрос"}


def tool_reconcile(dataset_ids: list[str]) -> dict[str, Any]:
    """Сверка количеств между документами (ВОР↔КС-2↔смета↔ИД) по оси документа."""
    from proxy.services.reconcile_service import reconcile_datasets

    return reconcile_datasets(dataset_ids, storage_root=_STORAGE, by="dataset")


def tool_bor(dataset_id: str) -> dict[str, Any]:
    """Свод ВОР из спецификаций датасета."""
    from proxy.services.bor_service import generate_bor

    return generate_bor(dataset_id, storage_root=_STORAGE)


def tool_spec_to_bor(dataset_id: str) -> dict[str, Any]:
    """ВОР работ из спецификации (форма 9)."""
    from proxy.services.spec_to_bor_service import generate_spec_bor

    return generate_spec_bor(dataset_id, storage_root=_STORAGE)


def tool_project_summary(dataset_ids: list[str]) -> dict[str, Any]:
    """Сводка проекта: стадия + ТЭП + состав документов."""
    from proxy.services.project_summary_service import build_project_summary

    return build_project_summary(dataset_ids, storage_root=_STORAGE)


def tool_form_generate(form_id: str, fmt: str = "xlsx", project_id: int | None = None) -> dict[str, Any]:
    """Сгенерировать типовую форму (спецификация/ВОР/смета/АОСР)."""
    from proxy.services.forms_service import generate

    out = generate(form_id, fmt, project_id=project_id)
    return {"form_id": form_id, "fmt": fmt, "path": out.get("path"), "html": out.get("html")}


# Каталог MCP-инструментов: имя → (описание, обработчик).
TOOLS: dict[str, tuple[str, Callable[..., Any]]] = {
    "les_table_sum": ("Сумма/кол-во по таблицам (Parquet), без LLM", tool_table_sum),
    "les_reconcile": ("Сверка ВОР↔КС-2↔смета↔ИД по количествам", tool_reconcile),
    "les_bor": ("Свод ВОР из спецификаций", tool_bor),
    "les_spec_to_bor": ("ВОР работ из спецификации (форма 9)", tool_spec_to_bor),
    "les_project_summary": ("Сводка проекта: ТЭП/стадии/состав", tool_project_summary),
    "les_form_generate": ("Генерация формы: спецификация/ВОР/смета/АОСР", tool_form_generate),
}


def manifest() -> list[dict[str, str]]:
    """Каталог инструментов для манифеста MCP/диагностики."""
    return [{"name": name, "description": desc} for name, (desc, _fn) in TOOLS.items()]


def main() -> None:
    print("MCP-сервер ЛЕС — ЗАГЛУШКА (транспорт не подключён).")
    print("Планируемые инструменты:")
    for item in manifest():
        print(f"  • {item['name']} — {item['description']}")
    print("\nДля запуска реального сервера: uv add mcp (по одобрению), затем зарегистрировать TOOLS в FastMCP.")


if __name__ == "__main__":
    main()
