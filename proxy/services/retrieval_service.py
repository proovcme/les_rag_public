"""Retrieval strategy helpers for chat."""

from __future__ import annotations

import logging
import os
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
    if (
        "постановлени" in q
        or "пп 87" in q
        or "постановление 87" in q
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
            candidates = _dataset_name_candidates(effective_filter)
            matches = [dataset for dataset in ds_list if dataset.name in candidates]
            if not matches and effective_filter.startswith("NTD_"):
                matches = [dataset for dataset in ds_list if dataset.name == "NTD_Index"]
            if matches:
                ids = [dataset.id for dataset in matches]
                logger.info("[CHAT] dataset_filter='%s' -> ids=%s", effective_filter, ids)
                return ids
            logger.warning("[CHAT] dataset_filter='%s' not found", effective_filter)
            return []
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
    if reranker_available and reranker_enabled:
        raw_chunks = await rag_backend.retrieve(retrieval_query, dataset_ids=dataset_ids, top_k=RERANK_POOL_K)
        if raw_chunks and len(raw_chunks) > RERANK_TOP_K:
            try:
                reranker = reranker_cls(mlx_url=mlx_url, mode="batch")
                rerank_input = [
                    {
                        "text": chunk.content,
                        "metadata": {"doc_name": chunk.doc_name},
                        "score": getattr(chunk, "score", 0.0),
                    }
                    for chunk in raw_chunks
                ]
                if llm_semaphore is None:
                    ranked = await reranker.rerank(question, rerank_input, top_k=RERANK_TOP_K)
                else:
                    async with llm_semaphore:
                        ranked = await reranker.rerank(question, rerank_input, top_k=RERANK_TOP_K)
                chunks = []
                for ranked_chunk in ranked:
                    match = next(
                        (chunk for chunk in raw_chunks if chunk.content == ranked_chunk.text),
                        None,
                    )
                    if match:
                        chunks.append(match)
                    else:
                        chunks.append(
                            RerankedStub(
                                content=ranked_chunk.text,
                                doc_name=ranked_chunk.metadata.get("doc_name", "?"),
                            )
                        )
                logger.info("[RERANKER] %s -> %s чанков", len(raw_chunks), len(chunks))
                if not return_trace:
                    return chunks
                trace = RetrievalTrace(
                    mode="reranker",
                    vector_count=len(raw_chunks),
                    lexical_count=0,
                    merged_count=len(chunks),
                )
                quality = evaluate_retrieval_quality(question=question, chunks=chunks, trace=trace, kot=kot)
                trace.quality_status = quality.status
                trace.quality_detail = quality.detail
                return RetrievalResult(chunks, trace, kot, quality)
            except Exception as rerank_error:
                logger.warning("[RERANKER] Ошибка, fallback: %s", rerank_error)
                chunks = raw_chunks[:RERANK_TOP_K]
                if not return_trace:
                    return chunks
                trace = RetrievalTrace(
                    mode="vector",
                    vector_count=len(raw_chunks),
                    lexical_count=0,
                    merged_count=len(chunks),
                    fallback_reason="reranker_error",
                )
                quality = evaluate_retrieval_quality(question=question, chunks=chunks, trace=trace, kot=kot)
                trace.quality_status = quality.status
                trace.quality_detail = quality.detail
                return RetrievalResult(chunks, trace, kot, quality)
        if not return_trace:
            return raw_chunks
        trace = RetrievalTrace(mode="vector", vector_count=len(raw_chunks), merged_count=len(raw_chunks))
        quality = evaluate_retrieval_quality(question=question, chunks=raw_chunks, trace=trace, kot=kot)
        trace.quality_status = quality.status
        trace.quality_detail = quality.detail
        return RetrievalResult(raw_chunks, trace, kot, quality)


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
    vector_chunks = await rag_backend.retrieve(retrieval_query, dataset_ids=dataset_ids, top_k=vector_top_k)
    chunks, trace = _hybrid_merge(question, vector_chunks, dataset_ids, rag_backend, logger, retrieval_query=retrieval_query, pool_k=pool_k, limit=merged_top_k)
    quality = evaluate_retrieval_quality(question=question, chunks=chunks, trace=trace, kot=kot)

    if return_trace and quality.status == "weak":
        retry_query = expanded_quality_query(question, kot)
        if retry_query != question:
            retry_vector = await rag_backend.retrieve(retry_query, dataset_ids=dataset_ids, top_k=vector_top_k)
            retry_chunks, retry_trace = _hybrid_merge(retry_query, retry_vector, dataset_ids, rag_backend, logger, retrieval_query=retry_query, pool_k=pool_k, limit=merged_top_k)
            retry_trace.retry_count = 1
            retry_quality = evaluate_retrieval_quality(question=question, chunks=retry_chunks, trace=retry_trace, kot=kot)
            if retry_quality.status != "weak" or len(retry_chunks) >= len(chunks):
                chunks, trace, quality = retry_chunks, retry_trace, retry_quality

    trace.quality_status = quality.status
    trace.quality_detail = quality.detail
    if return_trace:
        return RetrievalResult(chunks, trace, kot, quality)
    return chunks


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
) -> tuple[list[Any], RetrievalTrace]:
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
        if status.get("ready") and not status.get("stale"):
            lexical_chunks = index.search(retrieval_query or question, collection=collection, dataset_ids=dataset_ids, limit=pool_k)
        elif status.get("stale"):
            logger.info("[HYBRID] lexical index stale for %s: %s", collection, status)
    except Exception as error:
        logger.warning("[HYBRID] lexical fallback: %s", error)
    merged, trace = merge_rrf(vector_chunks, lexical_chunks, question=retrieval_query or question, limit=limit)
    if not lexical_chunks and not trace.fallback_reason:
        trace.fallback_reason = "lexical_index_empty_or_unavailable"
    return merged, trace
