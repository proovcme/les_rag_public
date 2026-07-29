"""DeterministicFinalPolicy — детерминированный visible final только для control-plane.

Любой professional-domain канал не имеет права становиться финальным visible answer:
код может вернуть модели структурированный tool-result, но ответ формулирует модель.
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


# каналы-команды (явные императивы/режимы) — не относятся к professional-domain answer.
_COMMAND_CHANNELS = frozenset({
    "tasks", "preset", "les_md", "decision", "memory", "help", "agent_command",
})
# professional-domain каналы должны быть tools/model-context, а не финальным ответом кода.
_PROFESSIONAL_DOMAIN_CHANNELS = frozenset({
    "asbuilt", "doc_registry", "field", "glossary", "registry", "smeta",
})


def can_return_deterministic_final(channel: str, question: str, *, project_id: int = 0,
                                   dataset_filter: str = "", candidate: dict | None = None) -> tuple[bool, str]:
    """Разрешён ли детерминированный FINAL-ответ канала. → (allowed, reason). Отказ → запрос идёт
    в unified/router/RAG (а не выдаёт случайный термин/глобальный реестр)."""
    if channel in _PROFESSIONAL_DOMAIN_CHANNELS:
        return False, "professional_domain_requires_model_final"
    if channel in _COMMAND_CHANNELS:
        return True, "command_or_tool_channel"
    return False, "deterministic_final_not_allowed"
