"""Retrieval strategy helpers for chat."""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from proxy.services.kot_service import analyze_question, extract_norm_refs
from proxy.services.lexical_index_service import LexicalIndex, RetrievalTrace, lexical_enabled, merge_rrf
from proxy.services.query_router import route_query
from proxy.services.retrieval_quality_service import (
    RetrievalQuality,
    evaluate_retrieval_quality,
    expanded_quality_query,
)


CHAT_TOP_K = int(os.getenv("RAG_CHAT_TOP_K", "8"))
RERANK_POOL_K = int(os.getenv("RAG_CHAT_RERANK_POOL_K", "12"))
RERANK_TOP_K = int(os.getenv("RAG_CHAT_RERANK_TOP_K", "6"))
_SOURCE_EXACT_RE = re.compile(
    r"(?iu)(?:"
    r"[\w./\\:-]+\.(?:md|json|jsonl|dwg|dxf|rvt|rfa|ifc|ifczip|pdf|xlsx?|docx?)"
    r"|[\w./\\:-]*[/\\:_][\w./\\:-]{3,}"
    r"|[a-f0-9]{10,}"
    r"|[a-f0-9]{8}-[a-f0-9-]{8,}"
    r")"
)
_SOURCE_NAME_TOKEN_RE = re.compile(r"(?iu)[\wа-яё]{3,}")
_SOURCE_NAME_STOPWORDS = {
    "cad",
    "bim",
    "json",
    "projection",
    "source",
    "import",
    "domain",
    "canonical",
    "format",
    "formats",
    "dxf",
    "dwg",
    "rvt",
    "ifc",
    "md",
    "les",
    "rag",
    "content",
    "users",
    "овс",
    "для",
    "или",
    "как",
    "что",
    "это",
    "где",
    "дай",
    "покажи",
    "план",
}
_FIRST_ORDINAL_QUERY_RE = re.compile(r"(?iu)(?:\bfirst\b|перв\w*|начал\w*)")
_TABLE_ROW_QUERY_RE = re.compile(r"(?iu)(?:позици\w*|строк\w*|\brows?\b|\bitems?\b)")
_CAD_POSITION_RE = re.compile(r"(?iu)(?:\bposition\s+|\bпозиция\s+)(\d{1,5})")


@dataclass
class RerankedStub:
    content: str
    doc_name: str


@dataclass(frozen=True)
class QueryRoute:
    dataset_filter: Optional[str]
    expanded_query: str
    reason: str


@dataclass
class RetrievalResult:
    chunks: list[Any]
    trace: RetrievalTrace
    kot: Any
    quality: RetrievalQuality

    def payload(self) -> dict[str, Any]:
        trace = self.trace.payload()
        trace["quality"] = self.quality.payload()
        return trace


def _source_exact_terms(question: str) -> list[str]:
    terms: list[str] = []
    for match in _SOURCE_EXACT_RE.findall(question or ""):
        term = match.strip(" \t\r\n\"'`.,;()[]{}<>")
        if len(term) < 6:
            continue
        folded = term.casefold()
        if folded not in terms:
            terms.append(folded)
    return terms[:12]


def _chunk_exact_source_score(chunk: Any, terms: list[str]) -> int:
    if not terms:
        return 0
    meta = getattr(chunk, "meta", {}) or {}
    doc_name = str(getattr(chunk, "doc_name", "") or meta.get("file_name") or meta.get("doc_name") or "")
    doc_haystack = doc_name.casefold()
    content_haystack = str(getattr(chunk, "content", "") or "").casefold()
    score = 0
    for term in terms:
        if term in doc_haystack:
            score += 4
        elif term in content_haystack:
            score += 2
    return score


def _promote_exact_source_matches(chunks: list[Any], question: str) -> tuple[list[Any], list[str]]:
    terms = _source_exact_terms(question)
    if not terms or len(chunks) < 2:
        return chunks, []
    scored = [(_chunk_exact_source_score(chunk, terms), index, chunk) for index, chunk in enumerate(chunks)]
    matched = [term for term in terms if any(_chunk_exact_source_score(chunk, [term]) > 0 for chunk in chunks)]
    if not matched:
        return chunks, []
    ordered = [chunk for _score, _index, chunk in sorted(scored, key=lambda item: (-item[0], item[1]))]
    return ordered, matched


def _source_name_terms(question: str) -> list[str]:
    terms: list[str] = []
    for token in _SOURCE_NAME_TOKEN_RE.findall(question or ""):
        folded = token.casefold().replace("ё", "е")
        if folded in _SOURCE_NAME_STOPWORDS or folded.isdigit():
            continue
        has_cyrillic = any("а" <= ch <= "я" for ch in folded)
        if len(folded) < 4 and not has_cyrillic and not any(ch.isdigit() for ch in folded):
            continue
        if folded not in terms:
            terms.append(folded)
    return terms[:16]


def _source_name_haystack(chunk: Any) -> str:
    meta = getattr(chunk, "meta", {}) or {}
    parts = [
        getattr(chunk, "doc_name", "") or "",
        meta.get("file_name") or "",
        meta.get("doc_name") or "",
        meta.get("source_path") or "",
        str(getattr(chunk, "content", "") or "")[:5000],
    ]
    haystack = " ".join(str(part) for part in parts if part).casefold().replace("ё", "е")
    compact = re.sub(r"(?iu)[\W_]+", "", haystack)
    return f"{haystack} {compact}"


def _chunk_source_name_score(chunk: Any, terms: list[str]) -> int:
    if len(terms) < 2:
        return 0
    haystack = _source_name_haystack(chunk)
    matched = sum(1 for term in terms if term in haystack)
    if matched < 2:
        return 0
    return matched


def _promote_source_name_matches(chunks: list[Any], question: str) -> tuple[list[Any], list[str]]:
    terms = _source_name_terms(question)
    if len(terms) < 2 or len(chunks) < 2:
        return chunks, []
    scored = [(_chunk_source_name_score(chunk, terms), index, chunk) for index, chunk in enumerate(chunks)]
    max_score = max((score for score, _index, _chunk in scored), default=0)
    if max_score < 2:
        return chunks, []
    ordered = [chunk for _score, _index, chunk in sorted(scored, key=lambda item: (-item[0], item[1]))]
    matched = [term for term in terms if any(term in _source_name_haystack(chunk) for chunk in ordered[:3])]
    return ordered, matched[:8]


def _chunk_meta(chunk: Any) -> dict[str, Any]:
    meta = getattr(chunk, "meta", {}) or {}
    if not meta:
        meta = getattr(chunk, "metadata", {}) or {}
    return meta if isinstance(meta, dict) else {}


def _chunk_ordinal(chunk: Any, fallback: int) -> int:
    meta = _chunk_meta(chunk)
    for key in ("chunk_ord", "child_ord", "ordinal"):
        try:
            return int(meta.get(key))
        except (AttributeError, TypeError, ValueError):
            continue
    return fallback


def _first_ordinal_haystack(chunk: Any) -> str:
    meta = _chunk_meta(chunk)
    parts = [
        meta.get("section_heading") or "",
        meta.get("parent_heading") or "",
        str(getattr(chunk, "content", "") or "")[:4000],
    ]
    return " ".join(str(part) for part in parts if part).casefold()


def _first_position_number(text: str) -> int | None:
    values: list[int] = []
    for match in _CAD_POSITION_RE.finditer(text or ""):
        try:
            values.append(int(match.group(1)))
        except (TypeError, ValueError):
            continue
    return min(values) if values else None


def _promote_first_ordinal_chunks(
    chunks: list[Any],
    question: str,
    *,
    doc_filter: list[str] | None = None,
) -> tuple[list[Any], bool]:
    if not doc_filter or len(chunks) < 2:
        return chunks, False
    if not (_FIRST_ORDINAL_QUERY_RE.search(question or "") and _TABLE_ROW_QUERY_RE.search(question or "")):
        return chunks, False
    scored: list[tuple[int, int, int, Any]] = []
    for index, chunk in enumerate(chunks):
        haystack = _first_ordinal_haystack(chunk)
        if "first positions" not in haystack and "первые три позиции" not in haystack:
            continue
        if "position " not in haystack and "позиция " not in haystack:
            continue
        first_position = _first_position_number(haystack)
        position_rank = first_position if first_position is not None else 1_000_000
        scored.append((position_rank, _chunk_ordinal(chunk, index), index, chunk))
    if not scored:
        return chunks, False
    promoted = min(scored, key=lambda item: (item[0], item[1], item[2]))[3]
    try:
        setattr(promoted, "_rank_pin", 1000.0)
        setattr(promoted, "_rank_pin_reason", "first_ordinal_guard")
    except Exception:
        pass
    if chunks[0] is promoted:
        return chunks, False
    ordered = [promoted]
    ordered.extend(chunk for chunk in chunks if chunk is not promoted)
    return ordered, True


def _kot_reason_alias(dataset_filter: str | None, reason: str) -> str:
    aliases = {
        "NTD_FIRE": "fire_safety_keyword",
        "NTD_ELECTRICAL": "electrical_keyword",
        "NTD_STRUCTURAL": "structural_keyword",
        "NTD_SPDS": "spds_keyword",
        "NTD_GEOTECH": "geotech_keyword",
        "NTD_HVAC": "hvac_keyword",
        "NTD_WATER": "water_keyword",
        "GKRF": "gkrf_keyword",
        "TABLE": "table_smeta_keyword",
    }
    return aliases.get(dataset_filter or "", reason)


def classify_query(question: str) -> QueryRoute:
    intent = route_query(question)
    if intent.channel == "table":
        return QueryRoute(intent.dataset_filter or "TABLE", question, intent.reason)
    if intent.channel == "mail":
        return QueryRoute(intent.dataset_filter or "MAIL", question, intent.reason)

    kot = analyze_question(question)
    if kot.dataset_filter:
        expanded = _expand_query_for_dataset(question, kot.dataset_filter)
        return QueryRoute(kot.dataset_filter, expanded, _kot_reason_alias(kot.dataset_filter, kot.reason))

    q = question.casefold()
    # Нормализуем разделители, чтобы ловить ПП87 в любом написании: «пп87», «пп 87»,
    # «пп-87», «пп. 87», «пп №87». Иначе «пп87» слитно промахивался мимо «пп 87» и
    # каноничный перечень разделов (через _expand_gkrf_query) не подставлялся.
    q_compact = q.replace(" ", "").replace("-", "").replace(".", "").replace("№", "")
    if (
        "постановлени" in q
        or "пп87" in q_compact
        or "постановление87" in q_compact
        or "градостроительн" in q
        or "гкрф" in q
    ):
        return QueryRoute("GKRF", _expand_gkrf_query(question), "gkrf_keyword")
    if any(token in q for token in ("эвакуац", "пожар", "огнестойк", "противодым", "дымоудал", "13130")):
        return QueryRoute("NTD_FIRE", _expand_fire_query(question), "fire_safety_keyword")
    if any(token in q for token in ("пуэ", "электр", "кабел", "заземл", "молниезащит", "освещен", "напряжен")):
        return QueryRoute("NTD_ELECTRICAL", question, "electrical_keyword")
    if any(token in q for token in ("конструкц", "нагрузк", "фундамент", "основан", "железобетон")):
        return QueryRoute("NTD_STRUCTURAL", question, "structural_keyword")
    if any(token in q for token in ("спдс", "рабочая документац", "проектная документац", "гост 21")):
        return QueryRoute("NTD_SPDS", question, "spds_keyword")
    if any(token in q for token in ("грунт", "геотех", "сейсми", "землетряс", "основания и фундаменты")):
        return QueryRoute("NTD_GEOTECH", question, "geotech_keyword")
    if any(token in q for token in ("дорог", "мост", "тоннел", "железн", "аэродром", "транспорт")):
        return QueryRoute("NTD_TRANSPORT", question, "transport_keyword")
    if any(
        token in q
        for token in (
            "отоп",
            "вентиля",
            "кондицион",
            "теплов",
            "шум",
            "акуст",
            "воздухообмен",
            "расход воздуха",
            "микроклимат",
            "холодопроизвод",
            "сп 60",
            "60.13330",
        )
    ):
        return QueryRoute("NTD_HVAC", _expand_hvac_query(question), "hvac_keyword")
    if any(token in q for token in ("водоснаб", "водоотвед", "канализац", "гидротех", "мелиоратив")):
        return QueryRoute("NTD_WATER", question, "water_keyword")
    if any(token in q for token in ("трубопровод", "газопровод", "нефтепровод", "магистральн")):
        return QueryRoute("NTD_PIPELINES", question, "pipeline_keyword")
    if any(token in q for token in ("жил", "обществен", "градостро", "территор", "доступность", "городская среда")):
        return QueryRoute("NTD_ARCH_URBAN", question, "arch_urban_keyword")
    if any(token in q for token in ("организация строительства", "приемк", "приёмк", "производство работ")):
        return QueryRoute("NTD_CONSTRUCTION", question, "construction_keyword")
    if any(token in q for token in ("bim", "информационное модел", "обследован", "эксплуатац", "мониторинг")):
        return QueryRoute("NTD_BIM_OPERATION", question, "bim_operation_keyword")
    if any(token in q for token in ("ссбт", "охрана труда", "защитные сооружения", "опасн")):
        return QueryRoute("NTD_SAFETY", question, "safety_keyword")
    if any(token in q for token in ("материал", "изоляц", "опалуб", "полы", "покрыт", "стены")):
        return QueryRoute("NTD_MATERIALS", question, "materials_keyword")
    if any(token in q for token in ("смет", "ведомост", "таблиц", "расценк")):
        return QueryRoute("TABLE_SMETA", question, "table_smeta_keyword")
    if any(token in q for token in ("сп ", "норматив", "снип", "гост")):
        return QueryRoute("NTD", question, "generic_normative_keyword")
    return QueryRoute(None, question, "no_route")


def infer_dataset_filter(question: str) -> Optional[str]:
    return classify_query(question).dataset_filter


def expand_retrieval_query(question: str) -> str:
    from proxy.services.kot_service import expand_query_synonyms
    expanded = classify_query(question).expanded_query
    return expand_query_synonyms(expanded)


def _expand_gkrf_query(question: str) -> str:
    q = question.casefold()
    if (
        "раздел" in q
        and "проектн" in q
        and ("87" in q or "постановлен" in q or "гкрф" in q)
    ):
        return (
            f"{question}\n"
            "Положение устанавливает состав разделов проектной документации. "
            "Проектная документация на объекты капитального строительства состоит из 12 разделов: "
            "Раздел 1: Пояснительная записка. "
            "Раздел 2: Схема планировочной организации земельного участка. "
            "Раздел 3: Архитектурные решения. "
            "Раздел 4: Конструктивные и объемно-планировочные решения. "
            "Раздел 5: Сведения об инженерном оборудовании, о сетях инженерно-технического обеспечения, перечень инженерно-технических мероприятий, содержание технологических решений. "
            "Раздел 6: Проект организации строительства. "
            "Раздел 7: Проект организации работ по сносу или демонтажу объектов капитального строительства. "
            "Раздел 8: Перечень мероприятий по охране окружающей среды. "
            "Раздел 9: Мероприятия по обеспечению пожарной безопасности. "
            "Раздел 10: Мероприятия по обеспечению доступа инвалидов. "
            "Раздел 11: Смета на строительство объектов капитального строительства. "
            "Раздел 12: Иная документация в случаях, предусмотренных федеральными законами.\n"
            "Проектная документация на линейные объекты состоит из 10 разделов: "
            "Раздел 1: Пояснительная записка. "
            "Раздел 2: Проект полосы отвода. "
            "Раздел 3: Технологические и конструктивные решения линейного объекта. Искусственные сооружения. "
            "Раздел 4: Здания, строения и сооружения, входящие в инфраструктуру линейного объекта. "
            "Раздел 5: Проект организации строительства. "
            "Раздел 6: Проект организации работ по сносу (демонтажу) линейного объекта. "
            "Раздел 7: Мероприятия по охране окружающей среды. "
            "Раздел 8: Мероприятия по обеспечению пожарной безопасности. "
            "Раздел 9: Смета на строительство. "
            "Раздел 10: Иная документация в случаях, предусмотренных федеральными законами."
        )
    return question


def _expand_query_for_dataset(question: str, dataset_filter: str) -> str:
    if dataset_filter == "GKRF":
        return _expand_gkrf_query(question)
    if dataset_filter == "NTD_FIRE":
        return _expand_fire_query(question)
    if dataset_filter == "NTD_HVAC":
        return _expand_hvac_query(question)
    return question


def _append_query_hints(question: str, hints: list[str]) -> str:
    q = question.casefold()
    unique = [hint for hint in dict.fromkeys(hints) if hint and hint.casefold() not in q]
    if not unique:
        return question
    return question + "\n" + " ".join(unique[:24])


def _expand_fire_query(question: str) -> str:
    q = question.casefold()
    hints: list[str] = []
    if "7.13130" in q or "дымоудал" in q or "противодым" in q:
        hints.extend(["СП 7.13130", "противодымная вентиляция", "дымоудаление", "не предусматривать", "допускается не оборудовать", "вытяжной"])
    if "соуэ" in q or "оповещ" in q or ("управлен" in q and "эвакуац" in q):
        hints.extend(["СП 3.13130", "ГОСТ Р 59639", "система оповещения и управления эвакуацией"])
    if "спс" in q or "сигнализац" in q:
        hints.extend(["СП 484.1311500", "ГОСТ Р 59638", "системы пожарной сигнализации"])
    if "эвакуац" in q:
        hints.extend(["СП 1.13130", "эвакуационные пути", "эвакуационные выходы"])
    if "огнестойк" in q:
        hints.extend(["СП 2.13130", "предел огнестойкости"])
    if "проезд" in q and "пожар" in q:
        hints.extend(["СП 4.13130", "проезды пожарных автомобилей"])
    return _append_query_hints(question, hints)


def _expand_hvac_query(question: str) -> str:
    q = question.casefold()
    hints: list[str] = []
    # Основные HVAC-запросы: отопление / вентиляция / кондиционирование / воздухообмен / микроклимат
    if any(token in q for token in ("сп 60", "60.13330", "отоп", "вентиля", "воздухообмен", "микроклимат", "расход воздуха", "кондициониров")):
        hints.extend([
            "СП 60.13330",
            "СП 60.13330.2020 Отопление вентиляция и кондиционирование воздуха",
            "отопление вентиляция кондиционирование",
            "воздухообмен микроклимат нормируемые параметры",
        ])
    # Тепловые сети
    if ("теплов" in q and "сет" in q) or "тепловые сети" in q or "124.13330" in q:
        hints.extend(["СП 124.13330", "СП 74.13330", "тепловые сети теплоснабжение"])
    # Шумоглушение воздуховодов (только если явно упомянуто)
    if "шумоглуш" in q or "271.1325800" in q:
        hints.extend(["СП 271.1325800", "системы шумоглушения воздуховодов"])
    # Защита от шума (только если явно упомянуто)
    if "защит" in q and "шум" in q or "акуст" in q or "51.13330" in q or "353.1325800" in q:
        hints.extend(["СП 51.13330", "СП 353.1325800", "защита от шума"])
    # Тепловая изоляция (только если явно упомянуто)
    if ("тепл" in q and "изоляц" in q) or "61.13330" in q:
        hints.extend(["СП 61.13330", "тепловая изоляция оборудования трубопроводов"])
    # Холодопроизводительность / кондиционер (только если явно упомянуто)
    if "холодопроизвод" in q or "кондиционер" in q or "26963" in q:
        hints.extend(["ГОСТ 26963", "кондиционер холодопроизводительность"])
    return _append_query_hints(question, hints)


def _dataset_name_candidates(dataset_filter: str) -> list[str]:
    normalized = dataset_filter.strip()
    if not normalized:
        return []
    if normalized.endswith("_Index"):
        return [normalized]
    if normalized == "NTD":
        return [
            "NTD_FIRE_Index",
            "NTD_ELECTRICAL_Index",
            "NTD_STRUCTURAL_Index",
            "NTD_GEOTECH_Index",
            "NTD_SPDS_Index",
            "NTD_HVAC_Index",
            "NTD_WATER_Index",
            "NTD_PIPELINES_Index",
            "NTD_TRANSPORT_Index",
            "NTD_ARCH_URBAN_Index",
            "NTD_CONSTRUCTION_Index",
            "NTD_BIM_OPERATION_Index",
            "NTD_SAFETY_Index",
            "NTD_MATERIALS_Index",
            "NTD_GENERAL_Index",
            "NTD_OTHER_Index",
            "NTD_Index",
        ]
    if normalized == "TABLE":
        return [
            "TABLE_SMETA_Index",
            "TABLE_SPEC_Index",
            "TABLE_KS2_Index",
            "TABLE_AOSR_Index",
            "TABLE_TABLE_Index",
        ]
    return [f"{normalized}_Index"]


async def resolve_dataset_ids(
    rag_backend,
    dataset_ids: Optional[list[str]],
    dataset_filter: Optional[str],
    logger: logging.Logger,
    question: str = "",
) -> Optional[list[str]]:
    effective_filter = dataset_filter
    ds_list = None
    if not effective_filter and not dataset_ids:
        route = classify_query(question)
        effective_filter = route.dataset_filter
        if effective_filter:
            logger.info("[CHAT] query_route='%s' dataset_filter='%s'", route.reason, effective_filter)

    if effective_filter and not dataset_ids:
        try:
            ds_list = await rag_backend.list_datasets()
            exact_matches = [
                dataset for dataset in ds_list
                if str(getattr(dataset, "id", "")) == effective_filter
                or str(getattr(dataset, "name", "")) == effective_filter
            ]
            if exact_matches:
                ids = [dataset.id for dataset in exact_matches]
                logger.info("[CHAT] dataset_filter='%s' exact -> ids=%s", effective_filter, ids)
                return ids
            candidates = _dataset_name_candidates(effective_filter)
            matches = [dataset for dataset in ds_list if dataset.name in candidates]
            if not matches and effective_filter.startswith("NTD_"):
                # СНАЧАЛА конкретный датасет по ПРЕФИКСУ (NTD_FIRE → NTD_FIRE_Index) — быстро+релевантно
                # (один датасет, малый контекст). Имена в рантайме: NTD_FIRE_Index/GENERAL/CONSTRUCTION/…
                matches = [d for d in ds_list if str(d.name).startswith(effective_filter)]
                if not matches:
                    # конкретного нет (напр. NTD_HVAC отсутствует) → ВЕСЬ нормативный корпус (все NTD_*),
                    # чтобы вопрос всё равно достал документ (медленнее, но не пусто). RAG-first.
                    matches = [d for d in ds_list if str(d.name).startswith("NTD_")]
            if matches:
                ids = [dataset.id for dataset in matches]
                logger.info("[CHAT] dataset_filter='%s' -> ids=%s", effective_filter, ids)
                return ids
            # RAG-first: keyword-scope не нашёл датасет по имени → НЕ загоняем в пустой scope
            # («нет данных»), а ищем ШИРОКО по всему корпусу (None) — семантика+реранк разберутся.
            logger.warning("[CHAT] dataset_filter='%s' не найден → broad RAG по всему корпусу", effective_filter)
            return None
        except Exception as e:
            logger.warning("[CHAT] dataset_filter resolve error: %s", e)
    if dataset_ids is None and ds_list is None:
        try:
            ds_list = await rag_backend.list_datasets()
            if not ds_list:
                logger.info("[CHAT] no datasets available for retrieval")
                return []
        except Exception as e:
            logger.warning("[CHAT] dataset list error: %s", e)
    return dataset_ids


async def retrieve_chat_chunks(
    *,
    question: str,
    dataset_ids: Optional[list[str]],
    rag_backend,
    reranker_enabled: bool,
    reranker_available: bool,
    reranker_cls,
    mlx_url: str,
    logger: logging.Logger,
    llm_semaphore: Any | None = None,
    return_trace: bool = False,
    doc_filter: Optional[list[str]] = None,
):
    kot = analyze_question(question)
    retrieval_query = expand_retrieval_query(question)
    if dataset_ids == []:
        trace = RetrievalTrace(mode="empty", fallback_reason="no_datasets")
        quality = evaluate_retrieval_quality(question=question, chunks=[], trace=trace, kot=kot)
        trace.quality_status = quality.status
        trace.quality_detail = quality.detail
        if return_trace:
            return RetrievalResult([], trace, kot, quality)
        return []
    # W2.3 (ADR-3): ранней реранк-ветки больше нет — реранкер работает ПОВЕРХ
    # гибридного пула (vector + lexical → RRF → rerank), а не вместо него.

    # Dynamic top-k scaling for structured, legal, or technical queries
    is_structured = any(word in question.casefold() for word in ("перечен", "состав", "список", "разделы", "все разделы", "перечисли"))
    effective_filter = dataset_ids or classify_query(question).dataset_filter
    is_technical_or_legal = bool(effective_filter and "MAIL" not in str(effective_filter))
    
    merged_top_k = CHAT_TOP_K
    if is_structured or is_technical_or_legal:
        merged_top_k = 24
        
    has_refs = bool(extract_norm_refs(question) or extract_norm_refs(retrieval_query))
    pool_k = max(36, merged_top_k * 2) if has_refs or is_structured or is_technical_or_legal else RERANK_POOL_K
    vector_top_k = pool_k if return_trace and lexical_enabled() else merged_top_k
    # ADR-12 стадия-1: для технических/правовых классов сначала маршрутизируем запрос
    # к документам-узлам (LLM-роутер по каталогу, см. doc_router), затем стадия-2 ищет
    # ТОЛЬКО в них. За флагом LES_TYPED_RETRIEVAL; пусто/сбой → плоский поиск.
    effective_doc_filter = list(doc_filter or [])
    _rt: dict[str, float] = {}  # под-фазовый тайминг ретрива (профилирование латентности)
    if os.getenv("LES_TYPED_RETRIEVAL", "false").strip().lower() == "true" and is_technical_or_legal:
        _s = time.monotonic()
        try:
            from proxy.services.doc_router import route_documents
            routed_doc_filter = await route_documents(
                question=question, expanded_query=retrieval_query,
                dataset_ids=dataset_ids, rag_backend=rag_backend,
            ) or None
            effective_doc_filter = effective_doc_filter or routed_doc_filter or []
        except Exception as _route_err:  # noqa: BLE001 — роутинг best-effort
            logger.warning("[DOC_ROUTER] fallback на плоский поиск: %s", _route_err)
            effective_doc_filter = effective_doc_filter or []
        _rt["route"] = round(time.monotonic() - _s, 3)
    used_native_hybrid = False
    if hybrid_backend() == "qdrant_native" and hasattr(rag_backend, "retrieve_native_hybrid"):
        _s = time.monotonic()
        try:
            native_chunks = await rag_backend.retrieve_native_hybrid(
                retrieval_query,
                dataset_ids=dataset_ids,
                top_k=merged_top_k,
                doc_filter=effective_doc_filter or None,
            )
            _rt["native"] = round(time.monotonic() - _s, 3)
            trace = RetrievalTrace(
                mode="qdrant_native_hybrid",
                vector_count=len(native_chunks),
                lexical_count=0,
                merged_count=len(native_chunks),
            )
            if effective_doc_filter:
                trace.exact_refs.extend([f"file:{name}" for name in effective_doc_filter])
            chunks = native_chunks
            try:
                merged_chunks, merged_trace = _hybrid_merge(
                    question,
                    native_chunks,
                    dataset_ids,
                    rag_backend,
                    logger,
                    retrieval_query=retrieval_query,
                    pool_k=pool_k,
                    limit=merged_top_k,
                    sparse_chunks=None,
                    doc_filter=effective_doc_filter or None,
                )
                if merged_trace.lexical_count:
                    chunks = merged_chunks
                    trace = merged_trace
                    trace.mode = f"qdrant_native_{merged_trace.mode}"
                    trace.vector_count = len(native_chunks)
                    if effective_doc_filter:
                        trace.exact_refs.extend([f"file:{name}" for name in effective_doc_filter])
                    _rt["native_lexical"] = merged_trace.lexical_count
            except Exception as native_merge_error:  # noqa: BLE001
                logger.warning("[HYBRID] qdrant_native lexical safety merge skipped: %s", native_merge_error)
            used_native_hybrid = True
        except Exception as native_error:  # noqa: BLE001
            logger.warning("[HYBRID] qdrant_native fallback to legacy hybrid: %s", native_error)
    if not used_native_hybrid:
        _s = time.monotonic()
        vector_chunks = await rag_backend.retrieve(
            retrieval_query,
            dataset_ids=dataset_ids,
            top_k=vector_top_k,
            doc_filter=effective_doc_filter or None,
        )
        _rt["vec"] = round(time.monotonic() - _s, 3)
        # W2.4: BGE-M3 learned-sparse рядом с dense (Qdrant-native гибрид). За флагом
        # RAG_SPARSE_ENABLED; при сбое/пустом sparse — молча падаем на dense+FTS.
        _s = time.monotonic()
        sparse_chunks = await _retrieve_sparse_safe(
            rag_backend,
            retrieval_query,
            dataset_ids,
            pool_k,
            logger,
            doc_filter=effective_doc_filter or None,
        )
        _rt["sparse"] = round(time.monotonic() - _s, 3)
        _s = time.monotonic()
        chunks, trace = _hybrid_merge(
            question,
            vector_chunks,
            dataset_ids,
            rag_backend,
            logger,
            retrieval_query=retrieval_query,
            pool_k=pool_k,
            limit=merged_top_k,
            sparse_chunks=sparse_chunks,
            doc_filter=effective_doc_filter or None,
        )
        if effective_doc_filter:
            trace.exact_refs.extend([f"file:{name}" for name in effective_doc_filter])
        _rt["merge"] = round(time.monotonic() - _s, 3)
    logger.info("[RETR] подфазы=%s", _rt)
    chunks, exact_terms = _promote_exact_source_matches(chunks, question)
    if exact_terms:
        if "source_exact" not in trace.mode:
            trace.mode = f"{trace.mode}+source_exact"
        for term in exact_terms:
            ref = f"source:{term}"
            if ref not in trace.exact_refs:
                trace.exact_refs.append(ref)
    elif any(token in question.casefold() for token in ("cad", "bim", "dwg", "dxf", "rvt", "ifc", "атм", "гсв")):
        chunks, source_name_terms = _promote_source_name_matches(chunks, question)
        if source_name_terms and "source_name_boost" not in trace.mode:
            trace.mode = f"{trace.mode}+source_name_boost"
    # ADR-12 (Ц9): подъём ТАБЛИЧНЫХ ПРИЛОЖЕНИЙ норм. Если узлы-документы известны
    # (doc_filter из стадии-1) и запрос «табличный» (перечень/приложение/категория
    # помещений) — аддитивно подмешиваем pipe-table чанки ЭТИХ узлов в пул, чтобы
    # реранк поднял приложение (эмбеддинг строки таблицы ≠ запрос → плоско тонет).
    # Пусто/нет интента/нет узлов → no-op, плоский пул нетронут.
    table_appendix_chunks: list[Any] = []
    if effective_doc_filter:
        try:
            from proxy.services.table_appendix_service import (
                fetch_table_appendix_chunks,
                merge_table_appendix,
            )
            table_appendix_chunks = await fetch_table_appendix_chunks(
                question=question, retrieval_query=retrieval_query,
                doc_filter=effective_doc_filter, dataset_ids=dataset_ids,
                rag_backend=rag_backend, logger=logger,
            )
            if table_appendix_chunks:
                before = len(chunks)
                chunks = merge_table_appendix(chunks, table_appendix_chunks)
                if len(chunks) != before:
                    trace.mode = f"{trace.mode}+table_appendix"
        except Exception as _tbl_err:  # noqa: BLE001 — best-effort, флат не страдает
            logger.warning("[TABLE_APPENDIX] fallback на плоский пул: %s", _tbl_err)
    # NB: hot-path дедуп по content_hash снят — измерено 0.7% дублей / 3 кросс-кластера на 6000
    # (tools/ingestion_quality_report). Кросс-датасетные дубли — задача ingestion QA, не рантайма.
    quality = evaluate_retrieval_quality(question=question, chunks=chunks, trace=trace, kot=kot)

    if return_trace and quality.status == "weak":
        retry_query = expanded_quality_query(question, kot)
        if retry_query != question:
            retry_vector = await rag_backend.retrieve(
                retry_query,
                dataset_ids=dataset_ids,
                top_k=vector_top_k,
                doc_filter=effective_doc_filter or None,
            )
            retry_sparse = await _retrieve_sparse_safe(
                rag_backend,
                retry_query,
                dataset_ids,
                pool_k,
                logger,
                doc_filter=effective_doc_filter or None,
            )
            retry_chunks, retry_trace = _hybrid_merge(
                retry_query,
                retry_vector,
                dataset_ids,
                rag_backend,
                logger,
                retrieval_query=retry_query,
                pool_k=pool_k,
                limit=merged_top_k,
                sparse_chunks=retry_sparse,
                doc_filter=effective_doc_filter or None,
            )
            retry_trace.retry_count = 1
            retry_quality = evaluate_retrieval_quality(question=question, chunks=retry_chunks, trace=retry_trace, kot=kot)
            if retry_quality.status != "weak" or len(retry_chunks) >= len(chunks):
                chunks, trace, quality = retry_chunks, retry_trace, retry_quality

    # W2.3: cross-encoder реранк гибридного пула — переупорядочивает, не режет
    # (downstream-фокусировка сама сузит). Сопоставление по индексу через
    # metadata._idx (не по тексту). Сбой → исходный гибридный порядок.
    if reranker_available and reranker_enabled and len(chunks) > 3:
        try:
            reranker = reranker_cls(mlx_url=mlx_url, mode="batch")
            rerank_input = [
                {
                    "text": chunk.content,
                    "metadata": {"doc_name": chunk.doc_name, "_idx": idx},
                    "score": getattr(chunk, "score", 0.0),
                }
                for idx, chunk in enumerate(chunks)
            ]
            # Семафор нужен только LLM-реранкеру (держит Metal); cross-encoder — нет.
            needs_semaphore = llm_semaphore is not None and reranker_cls.__name__ == "Reranker"
            if needs_semaphore:
                async with llm_semaphore:
                    ranked = await reranker.rerank(question, rerank_input, top_k=len(chunks))
            else:
                ranked = await reranker.rerank(question, rerank_input, top_k=len(chunks))
            reordered = []
            seen = set()
            for ranked_chunk in ranked:
                idx = ranked_chunk.metadata.get("_idx")
                if isinstance(idx, int) and 0 <= idx < len(chunks) and idx not in seen:
                    seen.add(idx)
                    reordered.append(chunks[idx])
            for idx, chunk in enumerate(chunks):  # хвост, не вернувшийся из реранка
                if idx not in seen:
                    reordered.append(chunk)
            chunks = reordered
            chunks, exact_terms = _promote_exact_source_matches(chunks, question)
            if exact_terms and "source_exact_guard" not in trace.mode:
                trace.mode = f"{trace.mode}+source_exact_guard"
            elif not exact_terms and any(token in question.casefold() for token in ("cad", "bim", "dwg", "dxf", "rvt", "ifc", "атм", "гсв")):
                chunks, source_name_terms = _promote_source_name_matches(chunks, question)
                if source_name_terms and "source_name_boost" not in trace.mode:
                    trace.mode = f"{trace.mode}+source_name_boost"
            trace.mode = f"{trace.mode}+rerank"
            logger.info("[RERANK-CE] гибридный пул %s переупорядочен", len(chunks))
        except Exception as rerank_error:
            logger.warning("[RERANKER] Ошибка, гибридный порядок без реранка: %s", rerank_error)
            trace.fallback_reason = trace.fallback_reason or "rerank_error"

    # ADR-12 (Ц9): после реранка гарантируем табличным приложениям места в видимом
    # окне ответа — иначе cross-encoder топит сырой текст таблицы под прозой и
    # приложение не доезжает. Аддитивно: без подмешанных таблиц — no-op.
    if table_appendix_chunks:
        try:
            from proxy.services.table_appendix_service import guarantee_table_appendix
            # Окно гарантии — ВИДИМЫЙ срез ответа (CHAT_TOP_K), а не весь пул:
            # пользователь читает первые CHAT_TOP_K, под ними приложение бесполезно.
            promoted = guarantee_table_appendix(chunks, table_appendix_chunks, window=CHAT_TOP_K)
            if promoted is not chunks and [id(c) for c in promoted] != [id(c) for c in chunks]:
                chunks = promoted
                if "table_appendix_guarantee" not in trace.mode:
                    trace.mode = f"{trace.mode}+table_appendix_guarantee"
        except Exception as _g_err:  # noqa: BLE001 — best-effort
            logger.warning("[TABLE_APPENDIX] guarantee fallback: %s", _g_err)

    chunks, ordinal_promoted = _promote_first_ordinal_chunks(
        chunks,
        question,
        doc_filter=effective_doc_filter or None,
    )
    if ordinal_promoted and "first_ordinal_guard" not in trace.mode:
        trace.mode = f"{trace.mode}+first_ordinal_guard"

    trace.quality_status = quality.status
    trace.quality_detail = quality.detail
    if return_trace:
        return RetrievalResult(chunks, trace, kot, quality)
    return chunks


def sparse_enabled() -> bool:
    """W2.4: BGE-M3 learned-sparse в гибриде (флаг; включается после миграции коллекции)."""
    return os.getenv("RAG_SPARSE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def hybrid_backend() -> str:
    value = os.getenv("RAG_HYBRID_BACKEND", "lexical").strip().lower()
    return value if value in {"lexical", "sidecar_sparse", "qdrant_native"} else "lexical"


def _lexical_status_usable(status: dict[str, Any]) -> tuple[bool, str]:
    if not status.get("ready"):
        return False, "not_ready"
    if not status.get("stale"):
        return True, "ready"
    try:
        point_count = int(status.get("point_count") or 0)
        chunks = int(status.get("chunks") or 0)
    except (TypeError, ValueError):
        return False, "stale_unknown_count"
    if point_count <= 0:
        return False, "stale_unknown_point_count"
    missing_ratio = max(point_count - chunks, 0) / max(point_count, 1)
    tolerance = float(os.getenv("RAG_LEXICAL_STALE_TOLERANCE", "0.02") or "0.02")
    if missing_ratio <= max(tolerance, 0.0):
        return True, f"minor_stale:{missing_ratio:.6f}"
    return False, f"stale:{missing_ratio:.6f}"


async def _retrieve_sparse_safe(rag_backend, query: str, dataset_ids, pool_k: int, logger: logging.Logger, doc_filter=None) -> list[Any]:
    if (
        hybrid_backend() != "sidecar_sparse"
        or not sparse_enabled()
        or not hasattr(rag_backend, "retrieve_sparse")
    ):
        return []
    try:
        return await rag_backend.retrieve_sparse(query, dataset_ids=dataset_ids, top_k=pool_k, doc_filter=doc_filter)
    except Exception as error:
        logger.warning("[HYBRID] sparse fallback: %s", error)
        return []


def _hybrid_merge(
    question: str,
    vector_chunks: list[Any],
    dataset_ids: Optional[list[str]],
    rag_backend,
    logger: logging.Logger,
    *,
    retrieval_query: str = "",
    pool_k: int = RERANK_POOL_K,
    limit: int = CHAT_TOP_K,
    sparse_chunks: Optional[list[Any]] = None,
    doc_filter: Optional[list[str]] = None,
) -> tuple[list[Any], RetrievalTrace]:
    # W2.4: learned-sparse (BGE-M3) ЗАМЕНЯЕТ самописный FTS в гибриде (план: FTS
    # остаётся для clause lookup). Если sparse пуст/выключен — падаем на FTS.
    if sparse_chunks:
        merged, trace = merge_rrf(vector_chunks, sparse_chunks, question=retrieval_query or question, limit=limit)
        trace.mode = "hybrid+sparse"
        return merged, trace

    if not lexical_enabled():
        trace = RetrievalTrace(
            mode="vector",
            vector_count=len(vector_chunks),
            lexical_count=0,
            merged_count=len(vector_chunks),
            fallback_reason="hybrid_disabled",
        )
        return vector_chunks[:limit], trace

    collection = getattr(rag_backend, "collection_name", "")
    if not collection:
        trace = RetrievalTrace(
            mode="vector",
            vector_count=len(vector_chunks),
            lexical_count=0,
            merged_count=len(vector_chunks),
            fallback_reason="missing_collection_name",
        )
        return vector_chunks[:limit], trace
    lexical_chunks: list[Any] = []
    try:
        index = LexicalIndex()
        status = index.status(collection)
        lexical_usable, lexical_reason = _lexical_status_usable(status)
        if lexical_usable:
            if status.get("stale"):
                logger.info("[HYBRID] lexical minor drift allowed for %s: %s %s", collection, lexical_reason, status)
            lexical_chunks = index.search(
                retrieval_query or question,
                collection=collection,
                dataset_ids=dataset_ids,
                doc_filter=doc_filter,
                limit=pool_k,
            )
        elif status.get("stale"):
            logger.info("[HYBRID] lexical index stale for %s: %s %s", collection, lexical_reason, status)
    except Exception as error:
        logger.warning("[HYBRID] lexical fallback: %s", error)
    merged, trace = merge_rrf(vector_chunks, lexical_chunks, question=retrieval_query or question, limit=limit)
    if not lexical_chunks and not trace.fallback_reason:
        trace.fallback_reason = "lexical_index_empty_or_unavailable"
    return merged, trace
