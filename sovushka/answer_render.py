"""Evidence UI helpers (v0.16) — чистые функции рендера ответа Совушки.

Делают видимым evidence-контракт: статус, типы (RETRIEVED/COMPUTED/ASSUMED/MISSING/BLOCKED),
source-chips, trace-summary. Чистые (без NiceGUI) → юнит-тестируемые; GUI вызывает их при рендере.
Никогда не выдумывают источник: нет source_ref → chip помечается «без ссылки», не фейк-линк.
"""

from __future__ import annotations

import re
from urllib.parse import quote
from typing import Any

# ── strip markdown из ячеек таблицы (фикс `**Тип котельной**` в ячейке) ───────────────────

_MD_TOKENS = re.compile(r"\*\*|__|\*|`|~~")


def strip_markdown_cell(value: Any) -> str:
    """Убрать inline-markdown из значения ячейки: `**Тип**` → `Тип`. Числа/коды не трогает по сути,
    только снимает оформление. None → ''."""
    if value is None:
        return ""
    s = str(value)
    s = _MD_TOKENS.sub("", s)
    s = re.sub(r"^\s*#{1,6}\s*", "", s)      # ведущий markdown-заголовок
    return s.strip()


def clean_table_rows(rows: list[dict]) -> list[dict]:
    """Снять markdown со всех ячеек (и значений, и ключей-колонок) — для display и CSV/JSON."""
    out = []
    for r in rows or []:
        out.append({strip_markdown_cell(k): strip_markdown_cell(v) for k, v in r.items()})
    return out


# ── evidence status (хедер ответа) ───────────────────────────────────────────────────────

_EVIDENCE_ORDER = ["RETRIEVED", "COMPUTED", "ASSUMED", "MISSING", "BLOCKED"]
_STATUS_HUMAN = {"complete": "ГОТОВО", "partial": "ЧАСТИЧНО", "blocked": "ЗАБЛОКИРОВАНО",
                 "no_data": "НЕТ ДАННЫХ"}
_STATUS_TONE = {"complete": "ok", "partial": "warn", "blocked": "err", "no_data": "dim"}
# семантический цвет бейджа типа evidence (CSS-класс-суффикс)
_EVIDENCE_TONE = {"RETRIEVED": "acc", "COMPUTED": "acc", "ASSUMED": "warn",
                  "MISSING": "warn", "BLOCKED": "err"}


def evidence_badges(evidence_summary: dict | None) -> list[dict]:
    """[{type, count, tone}] в каноническом порядке — для бейджей в хедере. Пусто → []."""
    es = evidence_summary or {}
    out = []
    for t in _EVIDENCE_ORDER:
        n = int(es.get(t, 0) or 0)
        if n > 0:
            out.append({"type": t, "count": n, "tone": _EVIDENCE_TONE.get(t, "dim")})
    return out


def answer_status(total_status: str | None) -> dict:
    """{label, tone} для статус-полоски ответа."""
    s = (total_status or "").strip()
    return {"label": _STATUS_HUMAN.get(s, s.upper() or "—"), "tone": _STATUS_TONE.get(s, "dim")}


def header_summary(query_route: dict | None, evidence_summary: dict | None,
                   sources_count: int = 0, total_status: str | None = None) -> dict:
    """Сводка для хедера: intent, статус, бейджи evidence, число источников, версия. Graceful: пустой
    query_route → минимальный хедер; не unified-ответ → has_evidence=False (старый рендер)."""
    qr = query_route or {}
    badges = evidence_badges(evidence_summary)
    return {
        "intent": qr.get("intent") or qr.get("channel") or "",
        "source_scope": qr.get("source_scope") or "",
        "provenance": qr.get("provenance") or "",
        "version": qr.get("version") or "",
        "status": answer_status(total_status),
        "badges": badges,
        "sources_count": int(sources_count or 0),
        "has_evidence": bool(badges) or bool(total_status),
    }


# ── source chips (вместо `[Источник 1,2,4]`) ─────────────────────────────────────────────

_KIND_HUMAN = {"parquet_row": "таблица", "file_body": "текст", "eml_message": "письмо",
               "extracted_body": "извлечено", "workbook_cell": "ячейка", "lexical_chunk": "индекс",
               "vector_chunk": "vector", "filename_metadata": "имя файла"}


def source_chip(source: Any, index: int | None = None) -> dict:
    """source (строка source_ref или dict) → {n, file, locator, kind, has_ref, weak}. Нет ref → has_ref=False
    (chip помечается «без ссылки», не делаем фейк-линк)."""
    ref = ""
    kind = ""
    if isinstance(source, dict):
        ref = str(source.get("source_ref") or source.get("ref") or source.get("path") or "")
        kind = str(source.get("source_kind") or source.get("kind") or "")
    else:
        ref = str(source or "")
    # ref вида "ds/file.docx#para85" или "file.xlsx#Лист!R12"
    file_part, _, loc = ref.partition("#")
    file_name = file_part.rsplit("/", 1)[-1] if file_part else ""
    # локатор человекочитаемо: para85→абз.85, p3→стр.3, row5→стр.5, Лист!R12→Лист R12, chunk2→чанк2
    loc_h = loc
    for pat, rep in ((r"^para(\d+)", r"абз.\1"), (r"^p(\d+)$", r"стр.\1"), (r"^row(\d+)", r"стр.\1"),
                     (r"^L(\d+)", r"стр.\1"), (r"^chunk(\d+)?", r"чанк\1")):
        loc_h = re.sub(pat, rep, loc_h)
    return {"n": index, "file": file_name or (ref[:40] if ref else ""), "locator": loc_h,
            "kind": _KIND_HUMAN.get(kind, kind), "has_ref": bool(ref), "weak": kind in ("vector_chunk",)}


def source_chips(sources: list, max_n: int = 12) -> list[dict]:
    return [source_chip(s, i + 1) for i, s in enumerate((sources or [])[:max_n])]


def citation_artifact(sources: list) -> dict:
    """v0.17 §7: артефакт «Цитаты» — source chips + сниппеты (письма ТОЛЬКО snippet, не полное тело).
    Нет source_ref → has_ref=False (предупреждение, не фейк-линк)."""
    items = []
    for i, s in enumerate((sources or []), 1):
        c = source_chip(s, i)
        snippet = ""
        if isinstance(s, dict):
            snippet = str(s.get("snippet") or s.get("excerpt") or "")[:240]
        items.append({"n": i, "file": c["file"], "locator": c["locator"], "kind": c["kind"],
                      "source_ref": (s.get("source_ref") if isinstance(s, dict) else str(s)) if c["has_ref"] else "",
                      "snippet": snippet, "has_ref": c["has_ref"], "weak": c["weak"]})
    return {"type": "citations", "title": "Цитаты", "count": len(items), "items": items}


def citation_drawer_item(source: Any, index: int | None = None) -> dict:
    """One source → drawer payload for GUI.

    A chip may open the drawer only when it has a real ``source_ref``. Direct file opening is best-effort:
    if the ref looks like a file path, expose a raw-file URL; otherwise return a clear unavailable reason.
    """
    item = citation_artifact([source])["items"][0]
    item["n"] = index or item["n"]
    source_ref = str(item.get("source_ref") or "")
    file_part, _, location = source_ref.partition("#")
    open_url = ""
    unavailable_reason = ""
    if not item.get("has_ref"):
        unavailable_reason = "У источника нет source_ref: открыть нельзя, можно только проверить текст ответа."
    elif item.get("weak"):
        unavailable_reason = "Источник слабый/vector: точное место не гарантировано, доступно копирование source_ref."
    elif "/" in file_part or re.search(r"\.(pdf|docx?|xlsx?|csv|md|txt|eml|jsonl?)$", file_part, re.I):
        open_url = f"/lite-api/rag/file/raw?path={quote(file_part)}"
    else:
        unavailable_reason = "source_ref есть, но прямой путь к файлу не определён; скопируй ref для проверки."
    item.update({
        "location": location,
        "open_url": open_url,
        "unavailable_reason": unavailable_reason,
        "copy_text": source_ref if source_ref else item.get("file", ""),
    })
    return item


# ── §8 evidence-секции (группировка по типу для рендера) ──────────────────────────────────

_SECTION_TITLE = {"RETRIEVED": "Найдено", "COMPUTED": "Вычислено", "ASSUMED": "Допущено",
                  "MISSING": "Не хватает", "BLOCKED": "Заблокировано", "CONFLICT": "Проверить"}


def group_evidence_sections(evidence_blocks: list) -> list[dict]:
    """evidence_blocks → секции в каноническом порядке. MISSING/BLOCKED НЕ прячем (идут со своим
    заголовком и тоном). Принимает блоки с .type (Enum/строка) и .items."""
    order = ["RETRIEVED", "COMPUTED", "ASSUMED", "MISSING", "BLOCKED", "CONFLICT"]
    buckets: dict[str, list] = {k: [] for k in order}
    for b in evidence_blocks or []:
        t = getattr(getattr(b, "type", None), "name", None) or getattr(b, "type", None) or ""
        t = str(t).upper()
        if t in buckets:
            buckets[t].extend(getattr(b, "items", None) or (b.get("items") if isinstance(b, dict) else []) or [])
    out = []
    for k in order:
        if buckets[k]:
            out.append({"type": k, "title": _SECTION_TITLE[k], "tone": _EVIDENCE_TONE.get(k, "dim"),
                        "count": len(buckets[k]), "items": buckets[k]})
    return out


# ── §9 conflict-блок (разные версии параметра — не сливать молча) ──────────────────────────

def answer_copy_text(answer: str, sources: list | None = None, *, with_sources: bool = False) -> str:
    """v0.20: чистый текст ответа для «Копировать». Без скрытого trace, без UI-мусора. with_sources →
    добавить список источников (письма — без полного тела, только chip-локатор). Числа/таблицы как есть
    (markdown)."""
    text = (answer or "").strip()
    if with_sources and sources:
        lines = ["", "Источники:"]
        for c in source_chips(sources):
            loc = f" · {c['locator']}" if c["locator"] else ""
            ref = "" if c["has_ref"] else " (без ссылки)"
            lines.append(f"  [{c['n']}] {c['file']}{loc}{ref}")
        text += "\n" + "\n".join(lines)
    return text


def conflict_block(variants: list[dict]) -> dict | None:
    """v0.17 §9: ≥2 варианта значения параметра → отдельный блок «Проверить» с источниками каждого.
    variants: [{label, value, sources:[...]}]. <2 → None (нет конфликта)."""
    vs = [v for v in (variants or []) if v]
    if len(vs) < 2:
        return None
    return {"type": "conflict", "title": "Проверить: найдены разные версии параметра", "tone": "warn",
            "variants": [{"label": v.get("label", ""), "value": v.get("value", ""),
                          "chips": source_chips(v.get("sources") or [])} for v in vs]}


# ── trace summary (компактно; без тел писем) ──────────────────────────────────────────────

def trace_summary(unified_trace: dict | None) -> str:
    """Однострочная сводка trace: route · tiers · sources. Без чувствительного (тел писем нет)."""
    ut = unified_trace or {}
    parts = []
    if ut.get("intent"):
        parts.append(f"route: {ut['intent']}")
    tiers = ut.get("searched_tiers") or []
    if tiers:
        parts.append("tiers: " + ", ".join(tiers))
    astat = ut.get("adapter_statuses") or {}
    real = [f"{k}={v}" for k, v in astat.items() if k in ("vector", "mail") and v]
    if real:
        parts.append("adapters: " + ", ".join(real))
    if ut.get("sources_count") is not None:
        parts.append(f"sources: {ut['sources_count']}")
    return " · ".join(parts)
