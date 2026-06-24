"""Чат-канал глоссария: «что такое ВОР/КАЦ/ЛСР/КС…» → ответ из доменной онтологии.

Детерминированный канал ДО RAG (0 LLM): определение + зачем + из чего выходит → во что,
с нормативной основой. Закрывает кейс, когда RAG-роутинг уводит сметный вопрос в TABLE-домен
и отвечает NO_DATA. Источник истины — `config/domain/smeta_ontology.yaml` (см. [[smeta-ontology]]).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from proxy.services import smeta_ontology_service as onto

# Триггеры «спрашивают определение». Группа 1 — искомый термин (остаток вопроса).
_TRIGGERS = (
    r"что\s+так(?:ое|ая|ой)\s+(.+)",
    r"что\s+значит\s+(.+)",
    r"что\s+это\s+за\s+(.+)",
    r"расскажи\s+(?:про|о|об)\s+(.+)",
    r"объясни,?\s+что\s+так(?:ое|ой|ая)\s+(.+)",
    r"объясни\s+(.+)",
    r"дай\s+определение\s+(.+)",
    r"определение\s+(.+)",
)


def _extract_term(question: str) -> Optional[str]:
    q = " ".join(str(question or "").split())
    for pat in _TRIGGERS:
        m = re.search(pat, q, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(" ?.!»«\"'")
    return None


# v0.18 фикс greedy-матча: предлоги/служебные слова НЕ резолвим в концепты. Корень бага —
# onto.get_concept('на') → 'ozr' (ОЖР), из-за чего «расскажи про котельную НА лесном 64» уходил
# в глоссарий (определение ОЖР) вместо RAG. Термины глоссария (ВОР/КАЦ/ЛСР/ОЖР) стоп-словами не бывают.
_STOPWORDS = frozenset({
    "на", "по", "в", "во", "и", "или", "о", "об", "с", "со", "к", "ко", "за", "из", "изо",
    "от", "ото", "до", "у", "не", "ни", "ну", "да", "для", "при", "над", "под", "про", "без",
    "что", "это", "как", "так", "там", "тут", "же", "бы", "ли", "то", "вот", "его", "её", "их",
})


def _resolve(candidate: str):
    """Концепт по кандидату: целиком, затем по 2-словным и одиночным ЗНАЧИМЫМ токенам.
    Стоп-слова (предлоги и пр.) не резолвим — иначе «на»→ОЖР перехватывал нарративные запросы."""
    cand = (candidate or "").strip()
    if not cand or cand.lower() in _STOPWORDS:
        return None
    node = onto.get_concept(cand)
    if node is not None:
        return node
    words = [w for w in re.split(r"[\s,]+", cand) if len(w) >= 2 and w.lower() not in _STOPWORDS]
    for n in (2, 1):
        for i in range(len(words) - n + 1):
            node = onto.get_concept(" ".join(words[i:i + n]))
            if node is not None:
                return node
    return None


def _format(node: dict[str, Any]) -> str:
    by_id = onto.load_ontology()["by_id"]
    lines = [str(node.get("term", "")).strip()]
    if node.get("what"):
        lines.append(f"Что это: {node['what']}")
    if node.get("why"):
        lines.append(f"Зачем: {node['why']}")
    if node.get("inputs"):
        terms = ", ".join(by_id.get(i, {}).get("term", i) for i in node["inputs"])
        lines.append(f"Из чего выходит: {terms}")
    if node.get("outputs"):
        terms = ", ".join(by_id.get(o, {}).get("term", o) for o in node["outputs"])
        lines.append(f"Во что превращается / что питает: {terms}")
    if node.get("basis"):
        lines.append(f"Нормативная основа: {node['basis']}")
    lines.append("(из доменной онтологии ЛЕС — config/domain/smeta_ontology.yaml)")
    return "\n".join(lines)


def maybe_handle_glossary_query(question: str, *, project_id: int = 0) -> Optional[dict[str, Any]]:
    """«что такое X» → определение из онтологии. None — не глоссарный вопрос/термин не найден."""
    from proxy.services import sovushka_tone

    if sovushka_tone.wants_model(question):   # «своими словами» → уступаем дорогу модели
        return None
    term = _extract_term(question)
    if not term:
        return None
    node = _resolve(term)
    if node is None:
        return None
    return {"answer": sovushka_tone.flavor(_format(node), "glossary", seed=term),
            "operation": "glossary", "concept": node.get("id")}
