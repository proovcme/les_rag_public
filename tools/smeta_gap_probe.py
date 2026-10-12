"""Разбор нерешённых строк: что за ними стоит на самом деле.

ЗАЧЕМ. Фраза модели «нет подходящей нормы» сообщает результат попытки, но не причину
(ревью Codex 11.09). За ней может стоять неудачный запрос, неполная карточка, ошибка
выбора, нехватка исходных данных или то, что нормы на такую позицию и не бывает —
и это четыре разных задачи с разной ценой.

ЧТО ЗДЕСЬ. По каждой нерешённой строке зонд сам обращается к поиску норм: берёт
наименование позиции, спрашивает базу и показывает, что оттуда приходит, с измерителем
каждой карточки. Модель не участвует — проверяется именно поиск.

ЧТО ЭТО РАЗЛИЧАЕТ. Приходит ли на запрос по строке хоть что-то по теме. Признаком
служит общее значимое слово наименований, а не совпадение измерителя: измеритель ничего
не говорит о смысле — «Каландр четырехвалковый кордный» имеет ту же единицу «шт», что и
патч-корд, а верная для разъёма норма «Разъемы штепсельные» считалась недостижимой
из-за «упак» против «шт» (ревью Codex 11.09).

ЧТО ЭТО НЕ ДОКАЗЫВАЕТ. Общее слово не делает норму правильной: это признак того, что
поиск попал в тему, а не что норма пригодна. Решение остаётся за сметчиком.

Запуск:
    uv run python -m tools.smeta_gap_probe --registry registry.json --limit 12
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


# Состояния реестра, по которым строку стоит зондировать.
UNRESOLVED = {"норма не найдена", "без объяснения", "заявлено включение в работу"}

# Служебный хвост наименования: артикулы, размеры, цвета. Для поиска нормы они шум.
_NOISE = re.compile(
    r"[A-Z0-9]{2,}[-/][A-Z0-9-]{2,}|\b\d+[xх×]\d+(?:[xх×]\d+)?\b|\bRAL\s*\d+\b",
    re.IGNORECASE,
)


def search_phrase(title: str) -> str:
    """Наименование позиции без артикулов и размеров — как спросил бы сметчик."""
    text = _NOISE.sub(" ", str(title or ""))
    text = re.sub(r"[«»\"(),;]+", " ", text)
    words = [word for word in text.split() if len(word) > 2 and not word.isdigit()]
    return " ".join(words[:9])


def _unit_base(unit: str) -> str:
    """Единица без множителя: «100 м» → «м», «10 шт» → «шт»."""
    parts = str(unit or "").strip().split()
    return (parts[-1] if parts else "").strip().casefold().rstrip(".")


# Слова, общие для любой строки сметы: их совпадение ничего не значит.
_EMPTY_WORDS = frozenset({
    "для", "при", "или", "без", "над", "под", "тип", "типа", "шт", "мм", "см",
    "установка", "монтаж", "устройство", "работ", "работы", "прочие", "другие",
})


def _content_words(text: str) -> set[str]:
    """Значимые основы наименования — по ним видно, попал ли поиск в тему."""
    words = re.findall(r"[а-яa-z]{4,}", str(text or "").casefold().replace("ё", "е"))
    return {word[:6] for word in words if word not in _EMPTY_WORDS}


def probe_row(row: dict[str, Any], *, limit: int = 5) -> dict[str, Any]:
    """Что поиск отдаёт по этой строке и попал ли он в тему."""
    from proxy.services.model_research_tool_service import retrieve_smeta_norm_cards

    phrase = search_phrase(row.get("title") or "")
    cards: list[dict[str, Any]] = []
    if phrase:
        try:
            payload = retrieve_smeta_norm_cards(phrase, limit=limit, discipline="")
            cards = list(payload.get("cards") or [])
        except Exception as error:  # noqa: BLE001 — зонд не должен ронять разбор
            return {"phrase": phrase, "error": f"{type(error).__name__}: {error}", "cards": []}
    row_unit = _unit_base(row.get("unit") or "")
    row_words = _content_words(row.get("title") or "")
    found: list[dict[str, Any]] = []
    for card in cards:
        title = str(card.get("title") or "")
        shared = sorted(row_words & _content_words(title))
        found.append({
            "norm_code": str(card.get("norm_code") or ""),
            "title": title[:70],
            "unit": str(card.get("measure_unit") or ""),
            "unit_fits": _unit_base(card.get("measure_unit") or "") == row_unit,
            "shared_words": shared,
            "on_topic": bool(shared),
        })
    return {
        "phrase": phrase,
        "row_unit": row_unit,
        "cards": found,
        "on_topic": any(item["on_topic"] for item in found),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--rows", type=int, default=0, help="сколько строк разобрать")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    targets = [row for row in registry if row.get("accounted_by") in UNRESOLVED]
    if args.rows:
        targets = targets[: args.rows]

    report: list[dict[str, Any]] = []
    reachable = 0
    for row in targets:
        probe = probe_row(row, limit=args.limit)
        report.append({**{k: row.get(k) for k in ("source_row", "title", "unit", "accounted_by")}, **probe})
        reachable += 1 if probe.get("on_topic") else 0
        mark = "поиск в теме " if probe.get("on_topic") else "поиск мимо   "
        print(f"{str(row.get('source_row')):>5} [{mark}] {str(row.get('title'))[:44]}")
        print(f"      запрос: «{probe.get('phrase')}»  единица строки: {probe.get('row_unit')}")
        for card in probe.get("cards", [])[:3]:
            mark_topic = "•" if card["on_topic"] else " "
            fit = "ед✓" if card["unit_fits"] else "   "
            print(
                f"        {mark_topic} {fit} {card['norm_code']:<20} "
                f"{card['unit']:<12} {card['title'][:40]}"
            )
    print()
    print(f"разобрано строк: {len(targets)}")
    print(f"  поиск попал в тему хотя бы одной карточкой: {reachable}")
    print(f"  выдача целиком не по теме:                  {len(targets) - reachable}")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
