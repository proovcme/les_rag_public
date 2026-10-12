"""Чем посчитали такое же изделие в готовых сметах.

ЗАЧЕМ. Поиск норм ищет наименование изделия среди названий работ, а это разные
категории: «Hyperline UUTP4-C5E-S24-IN-LSZH-GY-305» и «Кабель до 35 кВ в проложенных
трубах» не имеют общих слов, и вектор их не сближает. Замер 11.09 по 56 нерешённым
строкам прогона `sks-unit-20260911-0806`: выдача поиска пересеклась с реально
применяемыми нормами в 11 случаях, а «Ответвитель горизонтальный» получил в ответ
«Пароперегреватель радиационный».

ЧТО ЗДЕСЬ. Поиск по индексу `tools/build_material_norm_index.py`, где изделия названы
так же, как в ведомости поставщика: наименование сравнивается с наименованием. По тому
же замеру top-1 попал в профильный сборник в 53 случаях из 56.

КАК СЧИТАЕТСЯ БЛИЗОСТЬ. Наименование разбирается на две части. Русские слова дают
основу в шесть букв — «ответвитель» и «ответвителя» должны совпадать. Латиница и цифры
берутся целиком: в «UUTP4-C5E-S24» и «PC-LPM-UTP-RJ45» значение несут именно куски
артикула, и обрезать их нельзя. Вес куска — обратная частота в индексе: «кабель»
встречается в тысячах наименований и почти ничего не различает, «CM200802» встречается
в одном и указывает на него точно.

ПОЧЕМУ БЛИЗОСТЬ НОРМИРОВАНА. Сумма весов совпавших кусков зависит от размера индекса:
на архиве в 20 277 изделий редкий артикул весит около девяти, на десятке изделий — меньше
единицы, и любой порог, выставленный по одному, врёт на другом (воспроизведено тестом
11.09). Поэтому считается косинус на весах: доля общего веса от длин обоих наименований.
Значение лежит в отрезке от нуля до единицы и означает одно и то же при любом объёме
индекса.

ГРАНИЦА ПРИМЕНЕНИЯ. Совпадение наименования говорит, какой нормой посчитали похожее
изделие в чужой смете, и не говорит, что это верно здесь. Демонтажные нормы лежат в
индексе рядом с монтажными и помечены: без пометки «Кабель BC5E-4-LSHF» тянул бы за
собой «Демонтаж кабеля» молча. Количества и коэффициенты не переносятся — соотношение
«штук на измеритель» выводится из объёмов конкретного объекта.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.runtime_paths import mutable_path


SCHEMA = "les.smeta.material-norm-index.v1"

# Слова, которые есть почти в каждом наименовании: различают они нулево, а совпадение по
# ним создаёт видимость близости.
STOP_WORDS = frozenset({
    "для", "при", "или", "без", "над", "под", "тип", "типа", "шт", "штук", "мм", "см",
    "цвет", "цвета", "серый", "белый", "черный", "длина", "длиной",
})

# Основа русского слова: «ответвитель» и «ответвителя» должны попасть в один ключ.
RUSSIAN_STEM = 6
MIN_RUSSIAN = 4
MIN_LATIN = 2

_RUSSIAN = re.compile(r"[а-я]{%d,}" % MIN_RUSSIAN)
_LATIN = re.compile(r"[a-z0-9]{%d,}" % MIN_LATIN)

# Доля общего веса, ниже которой совпадение объясняется словами вроде «кабель», а не
# изделием. Значения нормированы, поэтому пороги не зависят от объёма индекса.
WEAK_SCORE = 0.25
# Выше этого совпала значимая часть обоих наименований.
STRONG_SCORE = 0.5


def index_path() -> Path:
    return Path(mutable_path("data/smeta_base/material_norm_index.json"))


def index_revision(path: str | None = None) -> str:
    """Отпечаток файла индекса: размер и время правки в наносекундах.

    Кеш держится за него, иначе процесс запомнит состояние «индекса нет» и не заметит
    появившийся файл; посекундная точность не различала бы две пересборки внутри секунды.
    """
    target = Path(path) if path else index_path()
    try:
        stat = target.stat()
    except OSError:
        return "absent"
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def tokens(text: str) -> frozenset[str]:
    """Куски наименования, по которым изделия сравниваются.

    Русское и латинское помечены разными префиксами: «pc» из артикула и «пс» из слова
    не должны слиться, а совпадение «м» с «m» ничего не значило бы.
    """
    lowered = str(text or "").lower().replace("ё", "е")
    found: set[str] = set()
    for word in _RUSSIAN.findall(lowered):
        if word not in STOP_WORDS:
            found.add("р:" + word[:RUSSIAN_STEM])
    for word in _LATIN.findall(lowered):
        if word not in STOP_WORDS:
            found.add("л:" + word)
    return frozenset(found)


def load_index(path: str | None = None) -> dict[str, Any]:
    """Прочитать индекс; отсутствие файла означает «подсказок нет»."""
    return _load_index_cached(path, index_revision(path))


@lru_cache(maxsize=2)
def _load_index_cached(path: str | None, revision: str) -> dict[str, Any]:
    target = Path(path) if path else index_path()
    empty: dict[str, Any] = {
        "schema": SCHEMA,
        "materials": [],
        "weights": {},
        "revision": revision,
    }
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict) or str(raw.get("schema") or "") != SCHEMA:
        return empty

    # Записи приходят парами «изделие + норма»; для поиска нужна одна запись на изделие
    # со списком норм, иначе одно и то же наименование сравнивается по многу раз.
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_entries = 0
    for entry in raw.get("entries") or []:
        if not isinstance(entry, dict):
            invalid_entries += 1
            continue
        try:
            count = int(entry.get("count") or 0)
        except (TypeError, ValueError, OverflowError):
            invalid_entries += 1
            continue
        if count < 0:
            invalid_entries += 1
            continue
        name = str(entry.get("material") or "").strip()
        if not name:
            continue
        grouped[name].append(entry)

    document_frequency: Counter = Counter()
    materials: list[dict[str, Any]] = []
    for name, entries in grouped.items():
        parts = tokens(name)
        if not parts:
            continue
        document_frequency.update(parts)
        materials.append({
            "material": name,
            "tokens": parts,
            "norms": sorted(entries, key=lambda item: -int(item.get("count") or 0)),
        })

    total = len(materials)
    weights = {
        token: math.log(total / (1 + count)) for token, count in document_frequency.items()
    }
    return {
        "schema": SCHEMA,
        "materials": materials,
        "weights": weights,
        "revision": revision,
        "source": str(raw.get("source") or ""),
        "invalid_entries": invalid_entries,
        "pairs_total": int(raw.get("pairs_total") or 0),
    }


def _weight_of(parts: frozenset[str], weights: dict[str, float]) -> float:
    return sum(weights.get(token, 0.0) ** 2 for token in parts)


def _score(
    query: frozenset[str],
    item: dict[str, Any],
    weights: dict[str, float],
    query_weight: float,
) -> float:
    """Косинус на весах кусков: доля общего веса от длин обоих наименований.

    Деление на длину кандидата обязательно: без него длинное описание с десятком слов
    обгоняет короткое точное совпадение просто за счёт числа шансов совпасть.
    """
    common = query & item["tokens"]
    if not common:
        return 0.0
    shared = sum(weights.get(token, 0.0) ** 2 for token in common)
    candidate_weight = _weight_of(item["tokens"], weights)
    if query_weight <= 0 or candidate_weight <= 0:
        return 0.0
    return shared / math.sqrt(query_weight * candidate_weight)


def similar_applications(
    title: str,
    *,
    limit: int = 5,
    path: str | None = None,
    include_demolition: bool = True,
) -> list[dict[str, Any]]:
    """Нормы, которыми считали изделия с похожим наименованием.

    Порядок — по близости наименований с поправкой на практику близких изделий: частая
    норма чужого изделия хуже редкой нормы того же самого изделия, но среди почти
    одинаково похожих изделий норма, которой их считали десятки раз, идёт раньше разовой.
    """
    index = load_index(path)
    materials = index.get("materials") or []
    if not materials:
        return []
    query = tokens(title)
    if not query:
        return []
    weights: dict[str, float] = index.get("weights") or {}
    query_weight = _weight_of(query, weights)

    scored: list[tuple[float, dict[str, Any]]] = []
    for item in materials:
        value = _score(query, item, weights, query_weight)
        if value > 0:
            scored.append((value, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["material"]))
    if not scored:
        return []

    # Каждая норма представлена самым похожим изделием. Живая проверка 17.09: витую пару
    # в готовых сметах 50 раз считали ГЭСНм08-02-148-01, а первой шла норма, применённая
    # один раз, — у того изделия совпал бренд. Поэтому к близости добавляется практика:
    # сколько раз норму применяли к изделиям почти той же близости (не ниже 0.8 от лучшей
    # для этой нормы). Логарифм не даёт частоте заглушить близость, а норма изделия вдвое
    # менее похожего, чем лучшее, в показ не поднимается.
    top = scored[0][0]
    best: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
    practice: dict[str, int] = defaultdict(int)
    for value, item in scored:
        for norm in item["norms"]:
            code = str(norm.get("norm_code") or "")
            if not code or norm.get("in_base") is False:
                continue
            if not include_demolition and norm.get("demolition"):
                continue
            if code not in best:
                if value < 0.5 * top:
                    continue
                best[code] = (value, item, norm)
            if value >= 0.8 * best[code][0]:
                practice[code] += int(norm.get("count") or 0)
    ranked = sorted(
        best.items(),
        key=lambda pair: (-pair[1][0] * (1.0 + math.log10(1 + practice[pair[0]])),
                          -pair[1][0], pair[1][1]["material"]),
    )

    found: list[dict[str, Any]] = []
    for code, (value, item, norm) in ranked:
        found.append({
            "norm_code": code,
            "norm_title": str(norm.get("norm_title") or ""),
            "norm_unit": str(norm.get("norm_unit") or ""),
            "material": item["material"],
            "material_unit": str(norm.get("material_unit") or ""),
            "applications": int(norm.get("count") or 0),
            "similar_applications": practice[code],
            "examples": norm.get("examples") or [],
            "source": index.get("source") or "",
            "revision": index.get("revision") or "",
            "invalid_entries": index.get("invalid_entries") or 0,
            "demolition": bool(norm.get("demolition")),
            "equipment": bool(norm.get("equipment")),
            "score": round(value, 3),
            "confidence": (
                "совпадение наименований" if value >= STRONG_SCORE
                else "частичное совпадение" if value >= WEAK_SCORE
                else "слабое совпадение"
            ),
        })
        if len(found) >= max(1, int(limit)):
            break
    return found
