"""Детерминированная структура документа («состав/перечень разделов/статей»). 0 LLM.

Косяк, который чинит: семантический ретрив НЕ собирает перечень разделов нормативного
документа — заголовки разделов размазаны по десяткам чанков, единого чанка с полным
списком нет. Но полный текст в индексе есть. Поэтому на запросы вида «состав проектной
документации по ПП-87 / перечень разделов / структура документа» собираем все чанки
документа по порядку (`chunk_ord`) и regex-ом извлекаем нумерованную структуру —
бит-в-бит из источника, без LLM и без переиндексации.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# «Раздел 5 "Сведения…"», «Статья 12. …», «Глава 3 "…"». Кавычки разных видов.
_ITEM_RE = re.compile(
    r'(Раздел|Стать[яи]|Глав[аы]|Подраздел)\s+(\d+(?:\(\d+\))?)\s*[.\"«“]\s*([^\"»”\n.]{4,200})',
    re.IGNORECASE,
)
# Граница: заголовок части про линейные объекты (там другой перечень тех же номеров).
# Конкретно заголовок раздела/части, не любое упоминание «линейных объектов».
_LINEAR_RE = re.compile(
    r'(III\.\s*Состав разделов проектной документации на линейные'
    r'|Состав разделов проектной документации на линейные объект'
    r'|разделов проектной документации на линейные объекты)',
    re.IGNORECASE,
)

# Триггеры «дай структуру/перечень», а не «расскажи про раздел X».
_OUTLINE_TRIGGERS = (
    "состав", "перечень раздел", "перечень стат", "структур", "список раздел",
    "какие раздел", "сколько раздел", "из каких раздел", "оглавлен",
)


@dataclass
class OutlineItem:
    kind: str
    number: str
    title: str


def is_outline_query(question: str) -> bool:
    """Запрос просит структуру/перечень разделов документа (а не содержание одного)."""
    q = (question or "").lower()
    return any(t in q for t in _OUTLINE_TRIGGERS)


def parse_outline(full_text: str, *, capital_only: bool = True) -> list[OutlineItem]:
    """Извлечь нумерованную структуру из полного текста документа. Чистая функция.

    capital_only: отрезать часть про линейные объекты (для ПП-87 — Раздел III),
    чтобы не смешивать два перечня с одинаковыми номерами.
    """
    text = full_text or ""
    if capital_only:
        m = _LINEAR_RE.search(text)
        if m:
            text = text[: m.start()]

    items: dict[str, OutlineItem] = {}
    for match in _ITEM_RE.finditer(text):
        kind = match.group(1).strip()
        number = match.group(2).strip()
        title = re.sub(r"\s+", " ", match.group(3)).strip(" .,:;»\"”")
        key = f"{kind.lower()}|{number}"
        # первое вхождение номера — каноничное (заголовок раздела идёт раньше упоминаний)
        if key not in items and len(title) >= 4:
            items[key] = OutlineItem(kind=kind, number=number, title=title)

    # сортировка по номеру (с учётом N(1))
    def _sort_key(it: OutlineItem):
        base = re.match(r"(\d+)(?:\((\d+)\))?", it.number)
        return (int(base.group(1)), int(base.group(2) or 0)) if base else (9999, 0)

    return sorted(items.values(), key=_sort_key)


def format_outline(items: list[OutlineItem], doc_name: str = "") -> str:
    """Готовый текстовый ответ (детерминированный, без LLM)."""
    if not items:
        return ""
    head = f"Состав документа{(' — ' + doc_name) if doc_name else ''}: {len(items)} {items[0].kind.lower()}(ов)."
    lines = [f"{it.number}. {it.title}" for it in items]
    return head + "\n" + "\n".join(lines)


def fetch_doc_text(dataset_name: str, *, qdrant_url: str, collection: str, doc_name: str | None = None) -> tuple[str, str]:
    """Собрать полный текст документа из чанков Qdrant по порядку. Возвращает (text, doc_name)."""
    import json
    import urllib.request

    must = [{"key": "dataset_name", "match": {"value": dataset_name}}]
    if doc_name:
        must.append({"key": "file_name", "match": {"value": doc_name}})
    body = json.dumps({
        "filter": {"must": must},
        "limit": 1000,
        "with_payload": ["text", "chunk_ord", "file_name"],
    }).encode()
    req = urllib.request.Request(
        f"{qdrant_url}/collections/{collection}/points/scroll", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as r:
        points = json.load(r)["result"]["points"]
    points.sort(key=lambda p: p["payload"].get("chunk_ord") or 0)
    name = doc_name or (points[0]["payload"].get("file_name", "") if points else "")
    return "\n".join(p["payload"].get("text") or "" for p in points), name
