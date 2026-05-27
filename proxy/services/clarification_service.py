"""Deterministic clarification gate for broad chat requests."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from proxy.services.kot_service import analyze_question
from proxy.services.retrieval_service import classify_query


@dataclass(frozen=True)
class QueryClassification:
    dataset_filter: Optional[str]
    route_reason: str
    domains: list[str]
    intent: str
    scope: str
    reasons: list[str]
    kot: dict | None = None


@dataclass(frozen=True)
class ClarificationDecision:
    needs_clarification: bool
    answer: str
    questions: list[str]
    suggested_filters: list[str]
    classification: QueryClassification

    def payload(self) -> dict:
        return {
            "needs_clarification": self.needs_clarification,
            "questions": self.questions,
            "suggested_filters": self.suggested_filters,
            "classification": asdict(self.classification),
        }


DOMAIN_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("NTD_FIRE", "fire_safety", ("эвакуац", "пожар", "огнестойк", "противодым", "13130")),
    (
        "NTD_ELECTRICAL",
        "electrical",
        ("пуэ", "электр", "кабел", "заземл", "молниезащит", "освещен", "напряжен"),
    ),
    ("NTD_STRUCTURAL", "structural", ("конструкц", "нагрузк", "фундамент", "основан", "железобетон")),
    ("TABLE_SMETA", "smeta", ("смет", "ведомост", "расценк", "кс-2", "кс2")),
    ("GKRF", "gkrf", ("постановлени", "пп 87", "постановление 87", "градостроительн", "гкрф")),
    ("NTD", "normative", ("сп ", "снип", "гост", "норматив", "требован")),
)

BROAD_INTENT_TOKENS = (
    "проверь",
    "проверить",
    "проанализируй",
    "анализ",
    "что не так",
    "ошибк",
    "нарушен",
    "замечан",
    "весь проект",
    "все документы",
    "комплект",
    "документац",
)

LOOKUP_INTENT_TOKENS = (
    "найди",
    "покажи",
    "дай",
    "какой",
    "какая",
    "какие",
    "в каких",
    "для каких",
    "сколько",
    "где написано",
    "допускается",
    "допускаются",
    "допускается ли",
    "не предусматривать",
    "не выполнять",
    "требован",
    "норма",
    "список",
    "перечисли",
)

COMPARE_INTENT_TOKENS = ("сравни", "отлич", "разниц", "верси")
SCOPE_TOKENS = ("файл", "раздел", "датасет", "источник", "объект", "проект ", "том ", "лист ")


def build_clarification_decision(
    question: str,
    *,
    dataset_ids: Optional[list[str]] = None,
    dataset_filter: Optional[str] = None,
) -> ClarificationDecision:
    classification = classify_for_clarification(question, dataset_ids=dataset_ids, dataset_filter=dataset_filter)
    needs = bool(classification.reasons)
    questions = _questions_for(classification) if needs else []
    answer = (
        "Запрос слишком широкий для надежного поиска по базе знаний. "
        "Уточните область и задачу, чтобы я не смешал разные документы."
        if needs
        else ""
    )
    return ClarificationDecision(
        needs_clarification=needs,
        answer=answer,
        questions=questions,
        suggested_filters=_suggested_filters(classification),
        classification=classification,
    )


def classify_for_clarification(
    question: str,
    *,
    dataset_ids: Optional[list[str]] = None,
    dataset_filter: Optional[str] = None,
) -> QueryClassification:
    q = question.casefold().strip()
    words = [word for word in q.replace("\n", " ").split(" ") if word]
    route = classify_query(question)
    kot = analyze_question(question, dataset_filter=dataset_filter, dataset_ids=dataset_ids)
    explicit_scope = bool(dataset_ids or dataset_filter)

    domains = (
        [(match.dataset_filter, match.label) for match in kot.matched_domains]
        if kot.matched_domains
        else _domains(q)
    )
    intent = _intent(q)
    scope = "explicit" if explicit_scope else ("mentioned" if any(token in q for token in SCOPE_TOKENS) else "missing")

    reasons: list[str] = []
    if not explicit_scope:
        if route.dataset_filter is None and intent == "broad_review":
            reasons.append("broad_review_without_domain")
        if route.dataset_filter is None and len(words) <= 4:
            reasons.append("short_unrouted_query")
        if kot.ambiguous and intent not in ("lookup", "compare") and route.dataset_filter is None:
            reasons.append("ambiguous_kot_match")
        if len({filter_name for filter_name, _domain in domains}) > 1 and intent == "broad_review":
            reasons.append("multi_domain_review")
        if intent == "broad_review" and scope == "missing":
            reasons.append("missing_scope")

    return QueryClassification(
        dataset_filter=dataset_filter or route.dataset_filter,
        route_reason=route.reason,
        domains=[domain for _filter_name, domain in domains],
        intent=intent,
        scope=scope,
        reasons=_dedupe(reasons),
        kot=kot.payload(),
    )


def _domains(q: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for filter_name, domain, tokens in DOMAIN_RULES:
        if any(token in q for token in tokens):
            found.append((filter_name, domain))
    return found


def _intent(q: str) -> str:
    if any(token in q for token in COMPARE_INTENT_TOKENS):
        return "compare"
    if any(token in q for token in BROAD_INTENT_TOKENS):
        return "broad_review"
    if any(token in q for token in LOOKUP_INTENT_TOKENS):
        return "lookup"
    return "unknown"


def _questions_for(classification: QueryClassification) -> list[str]:
    questions: list[str] = []
    if classification.dataset_filter is None or "broad_review_without_domain" in classification.reasons:
        questions.append("С какой областью работаем: нормативы, проектная документация, сметы/таблицы или вся база?")
    if classification.intent in ("unknown", "broad_review"):
        questions.append("Что именно нужно сделать: найти норму, проверить противоречия, составить перечень замечаний или сравнить документы?")
    if classification.scope == "missing":
        questions.append("Ограничить поиск конкретным объектом, файлом, разделом или датасетом?")
    return questions[:3]


def _suggested_filters(classification: QueryClassification) -> list[str]:
    if classification.dataset_filter:
        return [classification.dataset_filter]
    by_domain = {
        "fire_safety": "NTD_FIRE",
        "electrical": "NTD_ELECTRICAL",
        "structural": "NTD_STRUCTURAL",
        "smeta": "TABLE_SMETA",
        "gkrf": "GKRF",
        "normative": "NTD",
    }
    suggestions = [by_domain[domain] for domain in classification.domains if domain in by_domain]
    if suggestions:
        return _dedupe(suggestions)
    return ["NTD", "TABLE_SMETA", "GKRF"]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
