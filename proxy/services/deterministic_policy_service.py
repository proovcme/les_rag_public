"""DeterministicFinalPolicy (v0.18) — детерминированный final-ответ разрешён ТОЛЬКО при явном намерении.

Класс-фикс взамен точечного stopword-фикса: legacy deterministic-каналы (glossary/registry) больше не
перехватывают проектные/descriptive/source-scoped вопросы. Glossary — только если литеральный термин
реально в запросе. Registry — только точный глобальный реестр. Лёгкий, без unified-стека (runtime-safe).
"""

from __future__ import annotations

import re
from typing import Any

# ── классификаторы запроса (нормализованного) ─────────────────────────────────────────────

_SCOPE_MARKERS = (
    "в актах", "в акте", "в спецификац", "в почте", "в письм", "в вор", "в ведомост",
    "в кс-2", "в кс2", "в исполнительн", "в журнале", "в смете", "в лср", "в реестре документ",
)


def is_source_scoped_query(q: str) -> bool:
    """«найди X в актах/спецификации/почте/ВОР/КС-2/исполнительной…» — источник-ограниченный запрос."""
    return any(m in q for m in _SCOPE_MARKERS)


_DESCRIPTIVE = (
    "расскажи про", "расскажи о ", "расскажи об", "что знаешь о", "что ты знаешь", "что вы знаете",
    "характеристик", "опиши проект", "опиши объект", "опиши котельн", "что есть по", "что известно про",
    "про котельн", "про объект", "на лесном", "документац", "документы", "документов", "докум",
    "реестр документ", "состав проектн", "не мусорн", "сведения о", "инфо по", "сводка по",
)


def is_project_descriptive_query(q: str) -> bool:
    """Описательный/проектный вопрос («расскажи про …», «характеристики …», «документация …»)."""
    return any(m in q for m in _DESCRIPTIVE)


def has_project_scope(project_id: int | None, dataset_filter: str | None) -> bool:
    df = (dataset_filter or "").strip()
    return (isinstance(project_id, int) and project_id > 0) or (bool(df) and df != "(все датасеты)")


_TERM_TRIGGERS = (
    r"что\s+так(?:ое|ая|ой)\s+", r"что\s+значит\s+", r"что\s+означает\s+", r"расшифру\w+\s+",
    r"дай\s+определени\w+\s+", r"^\s*определени\w+\s+", r"\bтермин\s+", r"объясни\s+термин\s+",
)


def is_explicit_term_query(q: str) -> bool:
    """Явный запрос определения: «что такое X», «расшифруй X», «термин X», «ОЖР?»."""
    if re.match(r"^\s*[A-ZА-ЯЁ\d][\wА-Яа-яЁё\-\.]{1,14}\?\s*$", q.strip()):   # «ОЖР?»
        return True
    return any(re.search(p, q) for p in _TERM_TRIGGERS)


_GLOBAL_REG = (
    "реестр проект", "список проект", "какие проект", "покажи проект", "все проекты", "перечень проект",
    "какие объект", "реестр объект", "список объект", "карта проект", "карту проект",
)


def is_global_project_registry_query(q: str) -> bool:
    """Точный глобальный «реестр/список ПРОЕКТОВ» (не документация одного объекта)."""
    if any(s in q for s in ("документ", "докум")):     # «реестр документации» — не глобальный
        return False
    return any(m in q for m in _GLOBAL_REG)


_CODE_RE = re.compile(r"\b\d{2}[.\-]\d{2}[.\-]\d{2,3}(?:[.\-]\d{2,4})?\b|\b(?:ГЭСН|ФЕР|ТЕР)\w*\d", re.I)


def exact_code_present(q: str) -> bool:
    return bool(_CODE_RE.search(q))


def glossary_term_in_query(concept_id: str | None, question: str) -> bool:
    """Литеральное присутствие: термин/аббревиатура/алиас концепта реально есть в запросе.
    Корень класса багов — fuzzy-токен (предлог «на», имя объекта) резолвился в концепт, которого в
    тексте нет. Здесь требуем буквальное вхождение → фейк-резолв отсекается."""
    if not concept_id:
        return False
    try:
        from proxy.services import smeta_ontology_service as onto
        node = onto.load_ontology()["by_id"].get(concept_id)
        if not node:
            return False
        qn = onto._norm(question)
        term = str(node.get("term", ""))
        forms = [term, re.split(r"[—–-]", term)[0].strip()] + list(node.get("aliases", []) or [])
        return any(onto._norm(f) and onto._norm(f) in qn for f in forms)
    except Exception:  # noqa: BLE001
        return False


# каналы-команды (явные императивы/режимы) — не относятся к hijack-классу, пропускаем как есть
_COMMAND_CHANNELS = frozenset({
    "tasks", "preset", "asbuilt", "les_md", "field", "decision", "memory", "help",
    "doc_registry", "agent_command", "smeta",
})
# каналы, которые МОГУТ перехватить нарративный/проектный вопрос → жёсткая policy
_GATED_CHANNELS = frozenset({"glossary", "registry"})


def can_return_deterministic_final(channel: str, question: str, *, project_id: int = 0,
                                   dataset_filter: str = "", candidate: dict | None = None) -> tuple[bool, str]:
    """Разрешён ли детерминированный FINAL-ответ канала. → (allowed, reason). Отказ → запрос идёт
    в unified/router/RAG (а не выдаёт случайный термин/глобальный реестр)."""
    q = (question or "").lower().replace("ё", "е")
    cand = candidate or {}
    if channel not in _GATED_CHANNELS:
        return True, "command_or_tool_channel"

    scoped = is_source_scoped_query(q)
    descriptive = is_project_descriptive_query(q)
    has_scope = has_project_scope(project_id, dataset_filter)

    if channel == "glossary":
        concept = cand.get("concept") or cand.get("concept_id")
        if not glossary_term_in_query(concept, question):
            return False, "matched_term_not_in_query"        # фейк-резолв («на»→ОЖР) отсекается
        # явное «что такое X» с литеральным термином — определение (даже с контекстом «… в смете»)
        if is_explicit_term_query(q):
            return True, "explicit_term_literal_present"
        if scoped:
            return False, "source_scoped_query"
        if has_scope and descriptive:
            return False, "project_scope_preempts_glossary"  # проект выбран + descriptive → проектный путь
        return True, "term_literal_present"

    if channel == "registry":
        if scoped:
            return False, "source_scoped_query"
        if is_global_project_registry_query(q):
            return True, "global_registry_exact"
        return False, "not_global_registry_query"

    return False, "deterministic_final_not_allowed"
