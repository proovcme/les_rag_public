"""Принадлежность сметной нормы к дисциплине работ по её сборнику.

Подбор нормы одним лексическим сходством ставит первой «Бестраншейную прокладку
механизированной колонной в полосе отвода железных дорог» для кабеля U/UTP и
«Установку гипсовых штучных розеток» для компьютерной розетки: совпадают слова, а
не технология. Сборник, из которого взята норма, — независимый признак применимости,
и он уже присутствует в коде нормы.

Здесь только чистые правила. Знание о том, какие сборники относятся к дисциплине,
живёт в `config/domain/smeta_collection_scope.yaml` и опирается на официальные
названия сборников ФСНБ-2022.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ — ВЕСОМ. Замер на отложенной выборке (542 строки готовых смет,
корпус применений собран без файлов выборки, эталон — норма, применённая сметчиком)
показал: как слагаемое оценки сборник вредит. Точность первой позиции падала с 74,0 %
до 71,0 %, а без штрафа за чужой сборник — до 71,8 %. Причина в грубости признака:
профильный сборник содержит сотни норм, и принадлежность к нему поднимает любую из
них выше верной нормы из смежного сборника. Поэтому `search_norm` берёт отсюда только
пояснение к кандидату, а вес даёт практика раздела (`estimate_usage`, 77,9 %).

Область дисциплины никогда не запрещает кандидата: посторонняя норма остаётся в
списке с явной причиной, чтобы проверяющий видел основание сомнения.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from backend.runtime_paths import mutable_path


SCHEMA = "smeta_collection_scope_v1"

# Шкала принадлежности. Используется как пояснение и как признак для листа проверки;
# в оценку кандидата не входит — замер показал, что там она вредит (см. шапку модуля).
PRIMARY_WEIGHT = 1.0
RELATED_WEIGHT = 0.4
FOREIGN_WEIGHT = -1.2

_CODE = re.compile(r"(ГЭСНм|ГЭСНр|ГЭСНп|ГЭСН)\s*(\d{1,2})\b")


def _config_path() -> Path:
    candidate = Path("config/domain/smeta_collection_scope.yaml")
    if candidate.is_file():
        return candidate
    return Path(__file__).resolve().parents[2] / "config" / "domain" / "smeta_collection_scope.yaml"


@lru_cache(maxsize=1)
def load_scope(path: str | None = None) -> dict[str, Any]:
    """Прочитать области дисциплин; отсутствующий файл означает «правил нет»."""
    import yaml

    target = Path(path) if path else _config_path()
    if not target.is_file():
        return {"version": 0, "disciplines": {}}
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {"version": 0, "disciplines": {}}
    disciplines = payload.get("disciplines")
    return {
        "version": payload.get("version", 1),
        "disciplines": disciplines if isinstance(disciplines, Mapping) else {},
    }


def collection_key(norm_code: str) -> str:
    """`ГЭСНм10-01-055-02` → `ГЭСНм10`; пустая строка, если код не распознан."""
    match = _CODE.match(str(norm_code or "").strip())
    if not match:
        return ""
    return f"{match.group(1)}{int(match.group(2)):02d}"


def discipline_for_text(text: str, *, scope: Mapping[str, Any] | None = None) -> str:
    """Дисциплина по признакам в тексте работы; пустая строка, если признаков нет.

    Побеждает дисциплина с наибольшим числом совпавших признаков — одно случайное
    слово не должно перевешивать несколько профильных.
    """
    disciplines = (scope or load_scope()).get("disciplines") or {}
    haystack = str(text or "").casefold()
    if not haystack:
        return ""
    best_name, best_hits = "", 0
    for name, rules in disciplines.items():
        markers = (rules or {}).get("markers") or []
        hits = sum(1 for marker in markers if str(marker).casefold() in haystack)
        if hits > best_hits:
            best_name, best_hits = str(name), hits
    return best_name


def collection_affinity(norm_code: str, discipline: str, *, scope: Mapping[str, Any] | None = None) -> float:
    """Вес кандидата по его сборнику: профильный, смежный или посторонний."""
    if not discipline:
        return 0.0
    rules = ((scope or load_scope()).get("disciplines") or {}).get(discipline)
    if not isinstance(rules, Mapping):
        return 0.0
    key = collection_key(norm_code)
    if not key:
        return 0.0
    if key in {str(item) for item in rules.get("primary") or ()}:
        return PRIMARY_WEIGHT
    if key in {str(item) for item in rules.get("related") or ()}:
        return RELATED_WEIGHT
    return FOREIGN_WEIGHT


def collection_reason(norm_code: str, discipline: str, *, scope: Mapping[str, Any] | None = None) -> str:
    """Причина для листа проверки — с названием дисциплины, а не кодом."""
    weight = collection_affinity(norm_code, discipline, scope=scope)
    if not weight:
        return ""
    rules = ((scope or load_scope()).get("disciplines") or {}).get(discipline) or {}
    title = str(rules.get("title") or discipline)
    key = collection_key(norm_code)
    if weight >= PRIMARY_WEIGHT:
        return f"профильный сборник {key} для дисциплины «{title}»"
    if weight > 0:
        return f"смежный сборник {key} для дисциплины «{title}»"
    return f"сборник {key} вне дисциплины «{title}»"
