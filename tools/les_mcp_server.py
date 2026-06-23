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


def les_glossary(term: str) -> dict[str, Any]:
    """Что такое ВОР/КАЦ/ЛСР/КС и т.п.: определение + из чего выходит → во что (онтология, 0 LLM).

    term — термин или синоним (напр. «КАЦ», «смета», «конъюнктурный анализ»).
    """
    from proxy.services.smeta_ontology_service import derivation, get_concept

    node = get_concept(term)
    if node is None:
        return {"found": False, "term": term}
    der = derivation(term) or {}
    return {
        "found": True, "id": node["id"], "term": node.get("term"), "kind": node.get("kind"),
        "what": node.get("what"), "why": node.get("why"), "basis": node.get("basis"),
        "derived_from": der.get("direct_inputs", []), "produces": der.get("direct_outputs", []),
    }


def les_table_agg(dataset_ids: list[str], field: str = "amount", op: str = "sum",
                  contains: str | None = None, group_by: str | None = None) -> dict[str, Any]:
    """Агрегация по табличным датасетам с ГРУППИРОВКОЙ (сумма по разделам/типу и т.п.), 0 LLM.

    field: amount|qty|price|… · op: sum|count|avg|min|max · contains: фильтр по name/code ·
    group_by: section|doc_type|unit|… . Считает по ПОЛНОМУ parquet (не top-k).
    """
    from proxy.services.table_sql_service import aggregate

    return aggregate(dataset_ids, field=field, op=op, contains=contains, group_by=group_by)


def les_gesn_expand(code: str, qty: float = 1.0) -> dict[str, Any]:
    """Норма ГЭСН + объём → ресурсы (труд/машины/материалы × объём). 0 LLM.

    Дальше ресурсы идут в les_lsr_assemble (цены→стеснённость→НР/СП→Всего).
    """
    from proxy.services.gesn_service import expand_position, get_norm

    lines = expand_position(code, qty)
    if lines is None:
        return {"found": False, "code": code}
    norm = get_norm(code) or {}
    return {"found": True, "code": code, "name": norm.get("name"), "unit": norm.get("unit"),
            "qty": qty, "resources": lines}


def les_lsr_assemble(positions: list[dict], book: str | None = None,
                     kac_prices: dict | None = None, condition: str | None = None,
                     k_ozp: float | None = None, k_em: float | None = None) -> dict[str, Any]:
    """Сборка ЛСР: позиции (объём+ресурсы) → цены (ФГИС ЦС/КАЦ) → стеснённость → НР/СП → Всего → свод. 0 LLM.

    Каждая позиция: {code, name, unit, qty, section, nr_pct, sp_pct, resources:[{kind,name,unit,qty,price?,code?}]}.
    kind: labor|machinist|machine|material. book — книга цен; kac_prices — {наименование: цена}.
    """
    from proxy.services.lsr_assembly_service import assemble

    return assemble(positions, book=book, kac_prices=kac_prices,
                    condition=condition, k_ozp=k_ozp, k_em=k_em)


def les_stesnennost(positions: list[dict], condition: str | None = None,
                    k_ozp: float | None = None, k_em: float | None = None) -> dict[str, Any]:
    """Коэф. стеснённости → пересчёт позиций ЛСР (ОЗП/ЭМ → ФОТ/НР/СП/Всего). 0 LLM.

    positions — {name, ozp, em, zpm, mat, nr_pct, sp_pct}. Либо condition из каталога,
    либо явные k_ozp/k_em.
    """
    from proxy.services.stesnennost_service import apply

    return apply(positions, condition=condition, k_ozp=k_ozp, k_em=k_em)


def les_kac(quotes: list[dict], min_suppliers: int = 3, strategy: str = "min") -> dict[str, Any]:
    """КАЦ: котировки поставщиков (≥3 на материал) → выбор экономичного + линии для ЛСР. 0 LLM.

    quotes — список {material, supplier, unit, price, source}. strategy: 'min' | 'median'.
    """
    from proxy.services.kac_service import analyze_kac, kac_to_lsr_lines

    result = analyze_kac(quotes, min_suppliers=min_suppliers, strategy=strategy)
    return {"summary": result["summary"], "materials": result["materials"],
            "lsr_lines": kac_to_lsr_lines(result)}


def les_price_lookup(code: str, book: str | None = None, method: str = "index") -> dict[str, Any]:
    """Сметная цена ФГИС ЦС по коду ресурса (exact-match по «Сплит-форме»), без LLM.

    code — код ресурса (91.05.01-017); book — имя книги цен (без имени берётся единственная);
    method='index' — текущая цена (база×индекс/прямая), 'base' — базовая.
    """
    from pathlib import Path as _P
    from proxy.services import fgis_price_service as fps

    books = fps.available_pricebooks()
    if not books:
        return {"found": False, "note": "нет книг цен — импортируйте «Сплит-форму»"}
    path = next((p for p in books if _P(p).stem == book), None) if book else books[0]
    if path is None:
        return {"found": False, "note": f"книга {book!r} не найдена"}
    pb = fps.get_pricebook(path)
    rec = pb.lookup(code)
    if rec is None:
        return {"found": False, "code": code, "book": _P(path).stem}
    return {
        "found": True, "book": _P(path).stem, "region": pb.region, "quarter": pb.quarter,
        "method": method,
        "price": rec.get("price_current_eff") if method == "index" else rec.get("price_base"),
        "row": rec,
    }


# Каталог: имя инструмента → (описание, функция). Источник истины для сервера и манифеста.
TOOLS: dict[str, tuple[str, Any]] = {
    "les_table_sum": ("Сумма/кол-во по таблицам (Parquet), без LLM", les_table_sum),
    "les_reconcile": ("Сверка ВОР↔КС-2↔смета↔ИД по количествам", les_reconcile),
    "les_bor": ("Свод ВОР из спецификаций", les_bor),
    "les_spec_to_bor": ("ВОР работ из спецификации (форма 9)", les_spec_to_bor),
    "les_project_summary": ("Сводка проекта: ТЭП/стадии/состав", les_project_summary),
    "les_form_generate": ("Генерация формы: спецификация/ВОР/смета/АОСР", les_form_generate),
    "les_price_lookup": ("Цена ФГИС ЦС по коду ресурса (Сплит-форма)", les_price_lookup),
    "les_glossary": ("Что такое ВОР/КАЦ/ЛСР/КС: определение + деривация", les_glossary),
    "les_kac": ("КАЦ: ≥3 КП на материал → выбор экономичного + линии ЛСР", les_kac),
    "les_stesnennost": ("Коэф. стеснённости → пересчёт позиций ЛСР (ОЗП/ЭМ/НР/СП)", les_stesnennost),
    "les_lsr_assemble": ("Сборка ЛСР: объём+ресурсы→цены→стеснённость→НР/СП→Всего→свод", les_lsr_assemble),
    "les_gesn_expand": ("Норма ГЭСН + объём → ресурсы (труд/машины/материалы)", les_gesn_expand),
    "les_table_agg": ("Агрегация по таблицам с группировкой (сумма по разделам/типу)", les_table_agg),
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
