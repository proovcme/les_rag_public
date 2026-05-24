"""Retrieval strategy helpers for chat."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from proxy.services.query_router import route_query


@dataclass
class RerankedStub:
    content: str
    doc_name: str


@dataclass(frozen=True)
class QueryRoute:
    dataset_filter: Optional[str]
    expanded_query: str
    reason: str


def classify_query(question: str) -> QueryRoute:
    intent = route_query(question)
    if intent.channel == "table":
        return QueryRoute(intent.dataset_filter or "TABLE", question, intent.reason)

    q = question.casefold()
    if (
        "постановлени" in q
        or "пп 87" in q
        or "постановление 87" in q
        or "градостроительн" in q
        or "гкрф" in q
    ):
        return QueryRoute("GKRF", _expand_gkrf_query(question), "gkrf_keyword")
    if any(token in q for token in ("эвакуац", "пожар", "огнестойк", "противодым", "13130")):
        return QueryRoute("NTD_FIRE", question, "fire_safety_keyword")
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
    if any(token in q for token in ("отоп", "вентиля", "кондицион", "теплов", "шум", "акуст")):
        return QueryRoute("NTD_HVAC", question, "hvac_keyword")
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
    return classify_query(question).expanded_query


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
            "Проектная документация на объекты капитального строительства состоит из 12 разделов. "
            "Раздел 1 Пояснительная записка. "
            "Раздел 2 Схема планировочной организации земельного участка. "
            "Раздел 3 Архитектурные решения. "
            "Раздел 4 Конструктивные и объемно-планировочные решения. "
            "Раздел 5 Сведения об инженерном оборудовании, сетях инженерно-технического обеспечения. "
            "Раздел 6 Проект организации строительства. "
            "Раздел 7 Проект организации работ по сносу или демонтажу. "
            "Раздел 8 Перечень мероприятий по охране окружающей среды. "
            "Раздел 9 Мероприятия по обеспечению пожарной безопасности. "
            "Раздел 10 Мероприятия по обеспечению доступа инвалидов. "
            "Раздел 11 Смета на строительство. "
            "Раздел 12 Иная документация. "
            "Состав разделов проектной документации на линейные объекты."
        )
    return question


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
        except Exception as e:
            logger.warning("[CHAT] dataset_filter resolve error: %s", e)
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
):
    retrieval_query = expand_retrieval_query(question)
    if reranker_available and reranker_enabled:
        raw_chunks = await rag_backend.retrieve(retrieval_query, dataset_ids=dataset_ids, top_k=8)
        if raw_chunks and len(raw_chunks) > 5:
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
                ranked = await reranker.rerank(question, rerank_input, top_k=5)
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
                return chunks
            except Exception as rerank_error:
                logger.warning("[RERANKER] Ошибка, fallback: %s", rerank_error)
                return raw_chunks[:5]
        return raw_chunks

    return await rag_backend.retrieve(retrieval_query, dataset_ids=dataset_ids, top_k=5)
