"""Нормы, которые в этом разделе действительно применяют.

ЗАЧЕМ. Корпус применений собран из 2 279 готовых смет и знает по разделу связи 252
нормы с 2 730 применениями — «Кроссировка в шкафу», «Включение в аппаратуру разъёмов»,
«Конфигурация сетевых компонентов». До сих пор он умел только одно: приписать «применялась
N раз» той карточке, которую поиск уже нашёл сам. Если поиск её не нашёл — практика
молчала. В живом прогоне 11.09 практика была у 2 карточек из 22 (ревью Codex 11.09).

ЧТО ЗДЕСЬ. Те же нормы, но как отдельная группа кандидатов: модель видит их карточками
со ссылками и может выбрать. Это добавление к поиску, а не замена — редкая норма вне
архива остаётся доступной ровно как раньше, порядок поисковой выдачи не меняется.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Не весом и не запретом: отсутствие нормы в архиве ничего не
доказывает, а частота применения не делает норму правильной для конкретной строки.
Решение принимает модель.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


SCHEMA = "les.smeta.practice-candidates.v1"

# Сколько норм раздела показывать. Больше — вытесним из окна карточки по самим строкам
# ведомости, ради которых запрос и делается.
DEFAULT_LIMIT = 8


def practice_candidate_codes(
    discipline: str, *, limit: int = DEFAULT_LIMIT, exclude: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Шифры раздела по частоте применения, кроме уже показанных."""
    from proxy.smeta_core.estimate_usage import load_corpus

    section = (load_corpus().get("sections") or {}).get(str(discipline or "")) or {}
    skip = {str(code).strip().upper() for code in exclude if str(code or "").strip()}
    picked: list[dict[str, Any]] = []
    for item in section.get("norms") or []:
        code = str(item.get("norm_code") or "").strip()
        if not code or code.upper() in skip:
            continue
        # Нормы вне активной базы показывать нельзя: модель сошлётся на карточку,
        # которой нет, и расчёт её отвергнет.
        if item.get("in_base") is False:
            continue
        picked.append({
            "norm_code": code,
            "applications": int(item.get("count") or 0),
            "title": str(item.get("title") or ""),
            "unit": str(item.get("unit") or ""),
        })
        if len(picked) >= max(1, int(limit)):
            break
    return picked


def practice_candidate_cards(
    discipline: str, *, limit: int = DEFAULT_LIMIT, exclude: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Карточки норм раздела из активной базы — в том же виде, что и поисковые.

    Карточка берётся из базы по точному шифру: модели нужен измеритель и состав работы,
    а не строка корпуса. Ненайденные молча пропускаются — база могла смениться.
    """
    from proxy.smeta_core.norm_browser import browse_norms
    from proxy.smeta_core.estimate_usage import usage_evidence, archive_provenance

    cards: list[dict[str, Any]] = []
    for item in practice_candidate_codes(discipline, limit=limit, exclude=exclude):
        try:
            found = (browse_norms(item["norm_code"], limit=1) or {}).get("cards") or []
        except Exception:  # noqa: BLE001 — подсказка не должна ронять ответ
            continue
        card = next(
            (
                dict(row)
                for row in found
                if str(row.get("norm_code") or "").strip() == item["norm_code"]
            ),
            None,
        )
        if card is None:
            continue
        card["usage_evidence"] = {
            **usage_evidence(item["norm_code"], discipline),
            "schema": "les.smeta.usage-evidence.v1",
            "applications": item["applications"],
            "section": discipline,
            "note": f"архивных применений с совпадающим номером: {item['applications']}; тождественность нормы требует проверки",
        }
        card["archive_provenance"] = archive_provenance(card["usage_evidence"], card)
        cards.append(card)
    return cards


def practice_query_label(discipline: str, count: int) -> str:
    """Заголовок группы: модель должна понимать, откуда эти карточки.

    Формулировка не велит выбирать из них — велеть значило бы подменить решение
    сметчика статистикой. Она объясняет происхождение.
    """
    return (
        f"Нормы, которые чаще всего применяли в готовых сметах этого раздела "
        f"({discipline}), — {count} шт. Это не обязательный выбор: бери, если подходит "
        "строке, и ищи дальше, если нет."
    )
