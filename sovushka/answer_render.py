"""Evidence UI helpers (v0.16) — чистые функции рендера ответа Совушки.

Делают видимым evidence-контракт: статус, типы (RETRIEVED/COMPUTED/ASSUMED/MISSING/BLOCKED),
source-chips, trace-summary. Чистые (без NiceGUI) → юнит-тестируемые; GUI вызывает их при рендере.
Никогда не выдумывают источник: нет source_ref → chip помечается «без ссылки», не фейк-линк.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode
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
_ROUTE_HUMAN = {
    "command": "Команда",
    "doc_review": "Нормоконтроль",
    "generic": "Поиск",
    "harness_mode": "Смета",
    "mail": "Почта",
    "memory": "Память",
    "rag": "Поиск",
    "review_mode": "Нормоконтроль",
    "smeta": "Смета",
    "smeta_harness": "Смета",
    "smeta_mode": "Смета",
    "source_lookup": "Источник",
    "table": "Таблица",
}
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
    intent_raw = str(qr.get("intent") or qr.get("channel") or "").strip()
    return {
        "intent": _ROUTE_HUMAN.get(intent_raw, intent_raw if not intent_raw.endswith("_mode") else ""),
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

_EMBEDDED_VIEW_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".xlsm", ".pptx", ".eml",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
    ".txt", ".md", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".log",
    ".ini", ".cfg", ".sql", ".py", ".html", ".svg", ".csv", ".tsv",
}


def source_chip(source: Any, index: int | None = None) -> dict:
    """source (строка source_ref или dict) → {n, file, locator, kind, has_ref, weak}. Нет ref → has_ref=False
    (chip помечается «без ссылки», не делаем фейк-линк)."""
    ref = ""
    kind = ""
    doc_id = ""
    display_name = ""
    if isinstance(source, dict):
        ref = str(source.get("source_ref") or source.get("ref") or source.get("path") or "")
        kind = str(source.get("source_kind") or source.get("kind") or "")
        doc_id = str(source.get("doc_id") or "")
        display_name = str(source.get("doc_name") or source.get("file") or source.get("name") or "")
    else:
        ref = str(source or "")
    # ref вида "ds/file.docx#para85" или "file.xlsx#Лист!R12"
    file_part, _, loc = ref.partition("#")
    if not loc and isinstance(source, dict):
        locator = source.get("locator")
        if isinstance(locator, dict):
            page_value = locator.get("page") or locator.get("page_number") or locator.get("source_page")
            loc = f"p{page_value}" if page_value else str(locator.get("label") or "")
        elif locator:
            loc = str(locator)
        if not loc:
            page_value = source.get("source_page") or source.get("page") or source.get("page_number")
            loc = f"p{page_value}" if page_value else ""
    file_name = file_part.rsplit("/", 1)[-1] if file_part else display_name
    # локатор человекочитаемо: para85→абз.85, p3→стр.3, row5→стр.5, Лист!R12→Лист R12, chunk2→чанк2
    loc_h = loc
    for pat, rep in ((r"^para(\d+)", r"абз.\1"), (r"^p(\d+)$", r"стр.\1"), (r"^row(\d+)", r"стр.\1"),
                     (r"^L(\d+)", r"стр.\1"), (r"^chunk(\d+)?", r"чанк\1")):
        loc_h = re.sub(pat, rep, loc_h)
    return {"n": index, "file": file_name or (ref[:40] if ref else ""), "locator": loc_h,
            "kind": _KIND_HUMAN.get(kind, kind), "has_ref": bool(ref or doc_id),
            "weak": kind in ("vector_chunk",)}


def source_chips(sources: list, max_n: int = 12) -> list[dict]:
    return [source_chip(s, i + 1) for i, s in enumerate((sources or [])[:max_n])]


def citation_sources(sources: list, source_map: Any = None) -> list:
    """Prefer the exact prompt-visible source map over legacy filename chips.

    The map carries stable ``doc_id`` and precise locators.  Legacy ``sources``
    remain the fallback for old history records and non-RAG tool responses.
    """
    mapped = source_map if isinstance(source_map, list) else []
    if not mapped:
        return list(sources or [])
    normalized: list[dict[str, Any]] = []
    for item in mapped:
        if not isinstance(item, dict):
            continue
        source = dict(item)
        source.setdefault("file", source.get("doc_name") or "")
        source.setdefault("excerpt", source.get("snippet") or "")
        normalized.append(source)
    return normalized or list(sources or [])


_INLINE_MATH_RE = re.compile(r"(?<!\\)(?<!\$)\$([^$\n]+)\$(?!\$)")


def normalize_inline_math(text: str) -> str:
    """Remove unsupported inline-LaTeX delimiters without touching currency.

    NiceGUI's Markdown renderer does not enable a TeX plugin, so model output
    such as ``$P_{уст} = 841,4$`` otherwise exposes literal dollar signs.
    Escaped currency (``\\$100``), unmatched dollars and display ``$$`` blocks
    are preserved.
    """
    def _plain(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        expression = re.sub(r"_\{([^{}]+)\}", r"_\1", expression)
        expression = re.sub(r"\^\{([^{}]+)\}", r"^\1", expression)
        expression = re.sub(r"\\(?:mathrm|text)\{([^{}]+)\}", r"\1", expression)
        expression = expression.replace(r"\,", " ")
        expression = re.sub(r"(?<!\\)_", r"\\_", expression)
        return expression

    return _INLINE_MATH_RE.sub(_plain, str(text or ""))


def source_usage(source: Any, index: int, answer: str = "") -> dict[str, str]:
    """Operator label for a retrieved source without exposing ranking internals."""
    chip = source_chip(source, index)
    explicit = ""
    if isinstance(source, dict):
        explicit = str(
            source.get("citation_status")
            or source.get("usage")
            or ("used" if source.get("used") is True else "")
        ).casefold()
    cited_numbers: set[int] = set()
    for marker in re.findall(
        r"\[Источники?\s+([0-9,\s;|]+)\]",
        str(answer or ""),
        flags=re.IGNORECASE,
    ):
        cited_numbers.update(int(value) for value in re.findall(r"\d+", marker))
    marker_used = int(index) in cited_numbers
    if chip["weak"] or explicit in {"weak", "rejected"}:
        return {"code": "weak", "label": "Слабый", "tone": "warn"}
    if marker_used or explicit in {"used", "cited", "accepted"}:
        return {"code": "used", "label": "Использован", "tone": "ok"}
    return {"code": "found", "label": "Найден", "tone": "muted"}


def retrieval_notice(trace: dict | None) -> dict[str, str]:
    """Human notice for loud degraded/blocked retrieval states."""
    value = trace if isinstance(trace, dict) else {}
    status = str(value.get("status") or "ok").casefold()
    code = str(value.get("error_code") or value.get("fallback_reason") or "")
    if status == "degraded":
        return {
            "status": status,
            "title": "Поиск работает с ограничениями",
            "detail": code or "Часть обязательного поискового контура недоступна.",
            "tone": "warn",
        }
    if status == "blocked":
        return {
            "status": status,
            "title": "Поиск заблокирован",
            "detail": code or "Обязательный поисковый контур недоступен.",
            "tone": "error",
        }
    return {}


def citation_artifact(sources: list) -> dict:
    """v0.17 §7: артефакт «Цитаты» — source chips + сниппеты (письма ТОЛЬКО snippet, не полное тело).
    Нет source_ref → has_ref=False (предупреждение, не фейк-линк)."""
    items = []
    for i, s in enumerate((sources or []), 1):
        c = source_chip(s, i)
        snippet = ""
        if isinstance(s, dict):
            snippet = str(s.get("snippet") or s.get("excerpt") or "")[:240]
        usage = source_usage(s, i)
        items.append({"n": i, "file": c["file"], "locator": c["locator"], "kind": c["kind"],
                      "source_ref": (s.get("source_ref") if isinstance(s, dict) else str(s)) if c["has_ref"] else "",
                      "doc_id": str(s.get("doc_id") or "") if isinstance(s, dict) else "",
                      "dataset_id": str(s.get("dataset_id") or "") if isinstance(s, dict) else "",
                      "snippet": snippet, "has_ref": c["has_ref"], "weak": c["weak"],
                      "usage": usage["code"], "usage_label": usage["label"]})
    return {"type": "citations", "title": "Цитаты", "count": len(items), "items": items}


_SOURCE_MARKER_RE = re.compile(r"\[Источник\s+\d+(?:\s*\|[^\]]+)?\]")
_SOURCE_NOTE_RE = re.compile(r"^\s*(?:>\s*)?(?:[-*]\s*)?Источники\s*:", re.I)


def split_inline_source_notes(text: str) -> tuple[str, list[dict]]:
    """Strip explicit ``Источники: ...`` service lines from the visible answer.

    Inline markers such as ``[Источник 1]`` stay in normal prose. Full source
    note lines move to a separate artifact so the chat bubble does not become a
    wall of green quote blocks.
    """
    body_lines: list[str] = []
    notes: list[dict] = []
    for line in str(text or "").splitlines():
        raw = line.rstrip()
        stripped = raw.strip()
        if stripped and _SOURCE_NOTE_RE.match(stripped):
            clean = re.sub(r"^\s*>\s*", "", raw).strip()
            clean = re.sub(r"^\s*[-*]\s*", "", clean).strip()
            markers = _SOURCE_MARKER_RE.findall(clean)
            notes.append({"text": clean, "markers": markers})
            continue
        body_lines.append(raw)
    body = "\n".join(body_lines)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body, notes


def citation_drawer_item(source: Any, index: int | None = None) -> dict:
    """One source → drawer payload for GUI.

    A chip may open the drawer only when it has a real ``source_ref``. Direct file opening is best-effort:
    if the ref looks like a file path, expose a raw-file URL; otherwise return a clear unavailable reason.
    """
    item = citation_artifact([source])["items"][0]
    item["n"] = index or item["n"]
    source_ref = str(item.get("source_ref") or "")
    doc_id = str(item.get("doc_id") or "")
    file_part, _, location = source_ref.partition("#")
    if not location and isinstance(source, dict):
        locator = source.get("locator")
        if isinstance(locator, dict):
            if locator.get("page") not in (None, ""):
                location = f"p{locator['page']}"
            elif locator.get("paragraph") not in (None, ""):
                location = f"para{locator['paragraph']}"
        elif source.get("page") not in (None, ""):
            location = f"p{source['page']}"
    suffix_match = re.search(r"(\.[a-z0-9]+)$", file_part or str(item.get("file") or ""), re.I)
    suffix = suffix_match.group(1).lower() if suffix_match else ""
    open_url = ""
    viewer_url = ""
    unavailable_reason = ""
    if not item.get("has_ref"):
        unavailable_reason = "У источника нет source_ref: открыть нельзя, можно только проверить текст ответа."
    elif item.get("weak"):
        unavailable_reason = "Источник слабый/vector: точное место не гарантировано, доступно копирование source_ref."
    elif doc_id:
        open_url = f"/api/documents/by-id/{quote(doc_id, safe='')}/raw"
        page_match = re.search(r"(?:^|[#;&])(?:p|page=?)\s*(\d+)(?:$|[#;&])", location, re.I)
        if suffix == ".pdf" and page_match:
            open_url += f"#page={int(page_match.group(1))}"
        if suffix == ".pdf" or suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            viewer_url = open_url
        elif suffix in _EMBEDDED_VIEW_EXTENSIONS:
            params: dict[str, object] = {}
            if location:
                params["locator"] = location
            if isinstance(source, dict) and source.get("sheet"):
                params["sheet"] = source["sheet"]
            query = f"?{urlencode(params)}" if params else ""
            viewer_url = f"/api/documents/by-id/{quote(doc_id, safe='')}/viewer{query}"
    elif "/" in file_part or suffix in _EMBEDDED_VIEW_EXTENSIONS or suffix in {".doc", ".xls"}:
        open_url = f"/lite-api/rag/file/raw?path={quote(file_part)}"
        page_match = re.search(r"(?:^|[#;&])(?:p|page=?)\s*(\d+)(?:$|[#;&])", location, re.I)
        page_number = int(page_match.group(1)) if page_match else 1
        if suffix == ".pdf" and page_match:
            open_url += f"#page={page_number}"
        if suffix in _EMBEDDED_VIEW_EXTENSIONS:
            params: dict[str, str | int] = {"path": file_part, "locator": location}
            if suffix == ".pdf":
                params["page"] = page_number
                bbox_value: Any = None
                if isinstance(source, dict):
                    bbox_value = source.get("bbox") or source.get("bbox_pt")
                if not bbox_value and isinstance(source, dict):
                    fragments = source.get("pdf_fragment_bboxes") or []
                    if fragments and isinstance(fragments[0], dict):
                        bbox_value = fragments[0].get("bbox") or fragments[0].get("bbox_pt")
                if isinstance(bbox_value, (list, tuple)) and len(bbox_value) == 4:
                    try:
                        params["bbox"] = ",".join(str(float(value)) for value in bbox_value)
                    except (TypeError, ValueError):
                        pass
            viewer_url = f"/lite-api/rag/file/viewer?{urlencode(params)}"
    native_open_url = (
        f"/api/documents/by-id/{quote(doc_id, safe='')}/open-native"
        if doc_id else
        f"/api/documents/open-native-by-ref?path={quote(file_part)}"
        if item.get("has_ref") and file_part else ""
    )
    # Нормативные/расчётные refs вида "ГЭСН-2022#06-..." или "ГОСТ...#clause=..."
    # не являются локальными файлами. Не пугаем оператора техническим предупреждением: ref остаётся
    # в copy_text, а drawer просто показывает название источника и цитату/сниппет.
    item.update({
        "location": location,
        "open_url": open_url,
        "viewer_url": viewer_url,
        "native_open_url": native_open_url,
        "is_pdf": file_part.lower().endswith(".pdf"),
        "unavailable_reason": unavailable_reason,
        "copy_text": source_ref if source_ref else item.get("file", ""),
        "stamp_status": source.get("pdf_stamp_status") or source.get("stamp_status") if isinstance(source, dict) else "",
        "sheet_number": source.get("pdf_sheet_number") or source.get("sheet_number") if isinstance(source, dict) else "",
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
    topic_trace = ut.get("topic_guided_retrieval") if isinstance(ut.get("topic_guided_retrieval"), dict) else {}
    if topic_trace:
        selected_topics = topic_trace.get("selected_topics") or []
        topic_labels = [
            str(item.get("label") or item.get("id") or "")
            for item in selected_topics
            if isinstance(item, dict) and str(item.get("label") or item.get("id") or "").strip()
        ]
        topic_part = ", ".join(topic_labels[:2]) if topic_labels else "topic-guided"
        targeted = topic_trace.get("targeted_chunk_count")
        fallback = topic_trace.get("wide_fallback_chunk_count")
        promoted = topic_trace.get("wide_fallback_promoted") if isinstance(topic_trace.get("wide_fallback_promoted"), dict) else {}
        promoted_doc = str(promoted.get("doc_name") or "").rsplit("/", 1)[-1]
        suffix = []
        if targeted is not None:
            suffix.append(f"targeted {targeted}")
        if fallback is not None:
            suffix.append(f"fallback {fallback}")
        if promoted_doc:
            suffix.append(f"promoted {promoted_doc}")
        parts.append("topic: " + topic_part + (f" ({', '.join(suffix)})" if suffix else ""))
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
