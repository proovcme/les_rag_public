"""Deterministic query routing between table SQL and semantic RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

from proxy.services.kot_service import analyze_question


QueryChannel = Literal["table", "mail", "field", "rag"]


@dataclass(frozen=True)
class QueryIntent:
    channel: QueryChannel
    dataset_filter: Optional[str]
    reason: str


_TOKEN_RE_CACHE: dict[str, "re.Pattern[str]"] = {}


def _has_token(q: str, tokens) -> bool:
    """Токен на ГРАНИЦЕ слова, не подстрокой (мина substring). Короткий (≤3 симв.) — полная граница
    с обеих сторон («кац» не ловит специфиКАЦия, «сп» не ловит спОсоб); длинный — граница слева,
    словоформа справа разрешена («смет»→сметы/сметная). Регэкспы кэшируются."""
    for t in tokens:
        pat = _TOKEN_RE_CACHE.get(t)
        if pat is None:
            esc = re.escape(t)
            if len(t) <= 3:
                pat = re.compile(rf"(?<![а-яёa-z0-9]){esc}(?![а-яёa-z0-9])")
            else:
                pat = re.compile(rf"(?<![а-яёa-z0-9]){esc}")
            _TOKEN_RE_CACHE[t] = pat
        if pat.search(q):
            return True
    return False


TABLE_AGGREGATE_TOKENS = (
    "сколько",
    "итого",
    "сумм",
    "колич",
    "кол-во",
    "объем",
    "объём",
    "стоимост",
    "цена",
    "масса",
    "вес",
    "топ",
    "позици",
)

TABLE_CONTEXT_TOKENS = (
    "проект",
    "смете",
    "смет",
    "спецификац",
    "ведомост",
    "кс-2",
    "кс2",
    "таблиц",
    "кабел",
    "оборудован",
    "материал",
    "работ",
)

NORMATIVE_TOKENS = (
    "требован",
    "норм",
    "норматив",
    "нтд",
    "гост",
    "сп ",
    "снип",
    "пуэ",
    "допуска",
    "должн",
    "разреш",
    "запрещ",
    "минимальн",
    "максимальн",
)

# Журнал полевых объёмов (W8.4): сильные сигналы + «глагол выполнения + объём».
FIELD_STRONG_TOKENS = (
    "захватк",
    "журнал объ",
    "полевы",
    "полевой журнал",
)
FIELD_WORK_VERBS = (
    "выполнен",
    "смонтирован",
    "уложен",
    "залит",
    "забетонирован",
    "вывезен",
    "освоен",
)
FIELD_VOLUME_TOKENS = ("объем", "объём", "сколько", "итого", "сумм", "освоен")

# Маршрутизация в MAIL-канал = только SCOPE на mail-датасет (не пресет понимания).
# Содержательный ответ строит обычный семантический RAG над этим scope. Морфология
# «письмо/письма/писем/письмах» покрыта двумя корнями (письм/писем) — иначе
# «поручения из писем» промахивались мимо MAIL и тонули в общем RAG как «слишком
# широко».
MAIL_TOKENS = (
    "почт",
    "письм",
    "писем",
    "email",
    "e-mail",
    "переписк",
    "вложени",
    "кто кому",
    "цепочк",
    "thread",
    "отправил",
    "получил",
)

FIRE_SAFETY_TOKENS = (
    "эвакуац",
    "пожар",
    "огнестойк",
    "противодым",
    "дымоудал",
    "13130",
)

HVAC_TOKENS = (
    "отоп",
    "вентиля",
    "кондицион",
    "теплов",
    "акуст",
    "шум",
    "воздухообмен",
    "расход воздуха",
    "микроклимат",
    "холодопроизвод",
    "сп 60",
    "60.13330",
)

RAG_QUESTION_TOKENS = (
    "какие",
    "какой",
    "какая",
    "в каких",
    "для каких",
    "как ",
    "можно ли",
    "допускается ли",
    "требуется ли",
)


def route_query(
    question: str,
    *,
    dataset_filter: Optional[str] = None,
    dataset_ids: Optional[list[str]] = None,
) -> QueryIntent:
    q = question.casefold()
    if dataset_ids:
        return QueryIntent("rag", dataset_filter, "explicit_dataset_ids")
    if dataset_filter:
        if dataset_filter.startswith("TABLE"):
            return QueryIntent("table", dataset_filter, "explicit_table_filter")
        if dataset_filter == "MAIL":
            return QueryIntent("mail", dataset_filter, "explicit_mail_filter")
        if dataset_filter.startswith("NTD") or dataset_filter == "GKRF":
            return QueryIntent("rag", dataset_filter, "explicit_rag_filter")

    if _has_token(q, MAIL_TOKENS):
        return QueryIntent("mail", "MAIL", "mail_keyword")
    if _has_token(q, FIELD_STRONG_TOKENS) or (
        _has_token(q, FIELD_WORK_VERBS)
        and _has_token(q, FIELD_VOLUME_TOKENS)
    ):
        return QueryIntent("field", "FIELD", "field_volume_keyword")
    if _has_token(q, FIRE_SAFETY_TOKENS):
        return QueryIntent("rag", "NTD_FIRE", "fire_safety_keyword")
    if _has_token(q, HVAC_TOKENS):
        return QueryIntent("rag", "NTD_HVAC", "hvac_keyword")

    has_normative = _has_token(q, NORMATIVE_TOKENS)
    has_rag_form = _has_token(q, RAG_QUESTION_TOKENS)
    if has_normative and has_rag_form:
        return QueryIntent("rag", None, "normative_question")
    if has_normative and not _has_token(q, ("смет", "спецификац", "ведомост", "таблиц")):
        return QueryIntent("rag", None, "normative_keyword")

    has_aggregate = _has_token(q, TABLE_AGGREGATE_TOKENS)
    has_table_context = _has_token(q, TABLE_CONTEXT_TOKENS)
    if has_aggregate and has_table_context:
        return QueryIntent("table", "TABLE", "table_aggregate_context")
    if _has_token(q, ("смет", "спецификац", "ведомост", "кс-2", "кс2")):
        return QueryIntent("table", "TABLE", "table_document_keyword")

    kot = analyze_question(question)
    if kot.dataset_filter == "TABLE":
        return QueryIntent("table", "TABLE", kot.reason)
    if kot.dataset_filter == "MAIL":
        return QueryIntent("mail", "MAIL", kot.reason)
    if kot.dataset_filter:
        return QueryIntent("rag", kot.dataset_filter, kot.reason)

    return QueryIntent("rag", None, "default_rag")
