"""Мультикласс через диалог — ADR-12, слой 1 «стадия 0» (W11.7).

ADR-12 прямо говорит: мультикласс — **через диалог (ответ + варианты), не авто-fan-out**.
Поэтому здесь — детерминированный (0 LLM) детектор классов запроса (норматив / смета /
письмо / проект) и сборщик suggestions-чипов: ответ строится по верхнему классу
(как и раньше — через query_router), а остальные распознанные классы предлагаются
пользователю чипами «посмотреть как …» для пере-задания запроса в их области.

Класс — верхняя ось ADR-12; датасет-фильтр (NTD/TABLE_SMETA/MAIL) — фасет внутри класса.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassHit:
    class_id: str            # normative | table | mail | project
    label: str               # человекочитаемый ярлык с эмодзи (стиль чипов Совушки)
    dataset_filter: str | None
    score: int


# Правила распознавания класса. Порядок — приоритет при равном счёте (узкие выше).
# (class_id, label, dataset_filter, токены)
CLASS_RULES: tuple[tuple[str, str, str | None, tuple[str, ...]], ...] = (
    ("mail", "✉️ Письма и переписка", "MAIL",
     ("письм", "почт", "переписк", "входящ", "исходящ", "от кого", "адресат", "вложени", "e-mail", "емейл")),
    ("table", "📊 Сметы и таблицы", "TABLE_SMETA",
     ("смет", "ведомост", "расценк", "кс-2", "кс2", "спецификац", "кол-во", "количеств",
      "объём работ", "объем работ", "стоимост", "позиц")),
    ("normative", "📚 Нормативы (СП/ГОСТ)", "NTD",
     ("сп ", "снип", "гост", "норматив", "требован", "пуэ", "13130", "эвакуац", "пожар",
      "огнестойк", "противодым", "заземл")),
    ("project", "🏗️ Проектная документация", None,
     ("проект", "раздел", "чертеж", "чертёж", "лист", "эом", "осв", " ов", " вк", " ас", " кж",
      "марк", "стади", "рабочая документац")),
)


def detect_classes(question: str) -> list[ClassHit]:
    """Распознать классы запроса по словарю. Отсортировано по убыванию счёта. Без LLM."""
    q = f" {(question or '').lower().replace('ё', 'е')} "
    hits: list[ClassHit] = []
    for order, (class_id, label, dataset_filter, tokens) in enumerate(CLASS_RULES):
        score = sum(1 for tok in tokens if tok.replace("ё", "е") in q)
        if score:
            hits.append(ClassHit(class_id, label, dataset_filter, score))
    # больший счёт выше; при равенстве — порядок правил (узкие раньше).
    order_index = {cid: i for i, (cid, *_rest) in enumerate(CLASS_RULES)}
    hits.sort(key=lambda h: (-h.score, order_index[h.class_id]))
    return hits


def build_class_suggestions(
    question: str,
    *,
    primary_filter: str | None = None,
    max_suggestions: int = 3,
) -> list[dict]:
    """Чипы-варианты для классов, кроме верхнего/уже выбранного. Пусто, если запрос моноклассовый.

    Каждый чип: {class, label, dataset_filter, query} — query совпадает с исходным
    вопросом (переспрос в области другого класса; сужает scope, не меняет смысл).
    """
    hits = detect_classes(question)
    if len(hits) < 2:
        return []  # моноклассовый запрос — диалог-вариантов не предлагаем

    # Верхний класс уже отвечает; если задан реальный primary_filter — он и есть текущий.
    primary = hits[0]
    suggestions: list[dict] = []
    seen: set[str] = set()
    for hit in hits:
        if hit.class_id == primary.class_id:
            continue
        if hit.dataset_filter and hit.dataset_filter == primary_filter:
            continue
        if hit.class_id in seen:
            continue
        seen.add(hit.class_id)
        suggestions.append({
            "class": hit.class_id,
            "label": hit.label,
            "dataset_filter": hit.dataset_filter,
            "query": question,
        })
        if len(suggestions) >= max_suggestions:
            break
    return suggestions
