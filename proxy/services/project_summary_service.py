"""Сводка проекта: ТЭП + стадия + состав документов — W11.15 (каркас).

«Дай сводку проекта» одним детерминированным ответом: стадия (ПД/РД), технико-экономические
показатели (ТЭП) и состав документов. Источник — нормализованные Parquet-строки (числа из
таблиц) + имена документов. ADR-11: числа/факты считает код, не LLM. ТЭП-якоря калибруются
на реальных документах (котельная) — каркас уже рабочий.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from proxy.services.reconcile_service import collect_rows_by_doc_type
from proxy.services.spec_to_bor_service import _row_qty

logger = logging.getLogger(__name__)

# Стадия проекта по маркерам в именах/заголовках документов.
_STAGE_RD = ("рабочая документац", "рабочий проект", " рд ", "_рд", "стадия р", "(р)")
_STAGE_PD = ("проектная документац", " пд ", "_пд", "стадия п", "пояснительная записк", "(п)")

# ТЭП на уровне ТАБЛИЦЫ (весь лист/таблица = ТЭП): якоря в doc_title/section.
_TEP_TABLE_ANCHORS = (
    "технико-эконом", "технико эконом", "тэп", "основные показател",
    "основные технические", "технические характеристики", "общие данные",
)
# ТЭП на уровне СТРОКИ: наименование показателя (котельная и общестрой).
_TEP_ROW_ANCHORS = (
    "мощност", "теплопроизводит", "производительност", "кпд", "расход топлив",
    "расход газа", "расход воды", "топлив", "котл", "температурн", "график",
    "категория надежн", "категория надёжн", "давлени", "теплоноситель",
    "годовая выработк", "число часов", "площад", "объем здани", "объём здани",
    "этажност", "строительный объем", "строительный объём",
)


def _norm(s: Any) -> str:
    return str(s or "").lower().replace("ё", "е")


def is_project_summary_query(question: str) -> bool:
    """Намерение «дай сводку проекта / ТЭП / стадия / что за проект». Без LLM."""
    q = _norm(question)
    if any(t in q for t in ("сводк", "тэп", "технико-эконом", "технико эконом", "основные показател")):
        return True
    # «дай/сделай/покажи + проект/котельн» или «что за проект», «опиши проект»
    if ("проект" in q or "котельн" in q or "объект" in q) and any(
        v in q for v in ("сводк", "сводн", "что за", "опиши", "паспорт", "стади", "кратко о", "обзор")
    ):
        return True
    return False


def _detect_stage(rows: list[dict]) -> str:
    blob = " ".join(_norm(r.get("source_file")) + " " + _norm(r.get("doc_title")) for r in rows)
    pd = any(m in blob for m in _STAGE_PD)
    rd = any(m in blob for m in _STAGE_RD)
    if pd and rd:
        return "ПД + РД"
    if rd:
        return "РД (рабочая документация)"
    if pd:
        return "ПД (проектная документация)"
    return "не определена"


def extract_tep(rows: list[dict], *, limit: int = 40) -> list[dict[str, Any]]:
    """Кандидаты ТЭП: строки из ТЭП-таблиц (по якорю в заголовке) + показатели по якорю имени.

    Возвращает [{indicator, value, unit, source}]. Числа — из Parquet (qty/объём), не LLM.
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        name = " ".join(str(row.get("name") or row.get("work_name") or "").split())
        if not name or len(name) < 3:
            continue
        title_blob = _norm(row.get("doc_title")) + " " + _norm(row.get("section"))
        low_name = _norm(name)
        in_tep_table = any(a in title_blob for a in _TEP_TABLE_ANCHORS)
        is_indicator = any(a in low_name for a in _TEP_ROW_ANCHORS)
        if not (in_tep_table or is_indicator):
            continue
        value = _row_qty(row)
        # Без числа показатель малоинформативен, кроме явных ТЭП-таблиц (там может быть текст-значение).
        if value is None and not in_tep_table:
            continue
        key = low_name[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "indicator": name,
            "value": round(value, 4) if value is not None else None,
            "unit": str(row.get("unit") or "").strip(),
            "source": str(row.get("source_file") or "").strip(),
        })
        if len(out) >= limit:
            break
    return out


def build_project_summary(
    dataset_ids: list[str],
    *,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    """Сводка по датасетам проекта: стадия + ТЭП + состав документов. Без LLM."""
    rows: list[dict] = []
    for ds in dataset_ids:
        for _dt, rws in collect_rows_by_doc_type(ds, storage_root=storage_root).items():
            rows.extend(rws)

    documents = sorted({str(r.get("source_file") or "").strip() for r in rows if r.get("source_file")})
    return {
        "dataset_ids": dataset_ids,
        "stage": _detect_stage(rows),
        "tep": extract_tep(rows),
        "documents": documents,
        "document_count": len(documents),
        "table_rows": len(rows),
    }


def format_project_summary(result: dict[str, Any], label: str = "") -> str:
    lines = [f"Сводка проекта{(' · ' + label) if label else ''}:",
             f"Стадия: {result['stage']}",
             f"Документов с таблицами: {result['document_count']} · табличных строк: {result['table_rows']}"]
    tep = result.get("tep") or []
    if tep:
        lines.append(f"\nТехнико-экономические показатели (кандидаты, {len(tep)}):")
        for t in tep[:25]:
            val = (f"{t['value']} {t['unit']}".strip() if t["value"] is not None else "—")
            lines.append(f"  • {t['indicator']} — {val}")
    else:
        lines.append("\nТЭП-таблица не распозналась автоматически. Уточни запрос по «Общим данным» / "
                     "пояснительной записке, либо пришли документ с ТЭП — докалибрую якоря.")
    docs = result.get("documents") or []
    if docs:
        lines.append(f"\nДокументы проекта ({len(docs)}):")
        for d in docs[:20]:
            lines.append(f"  • {d}")
    lines.append("\nЧисла — из Parquet (0 LLM). Состав разделов целиком — спроси «состав разделов проекта».")
    return "\n".join(lines)
