"""Свидетельство о том, применяют ли норму в этом разделе реальные сметы.

Корпус собран из архива готовых смет (`tools/build_estimate_usage_corpus.py`) и
показывает рабочее ядро раздела: связь закрывается сотней норм на фоне 49 747 в базе.

ЭТО НЕ ВЕС. Ревью 10.09 показало, что как слагаемое оценки частота двигает порядок
сильнее допустимого: норма с 40-го места при 13 применениях обгоняла первую по тексту,
и редкая верная норма могла не дойти до модели вовсе. Поэтому здесь только описание с
происхождением — сколько смет, какого раздела, из какого корпуса, — которое кладётся
рядом с карточкой. Решение остаётся за моделью и проверяющим.

ГРАНИЦА ПРИМЕНЕНИЯ. Частота применения не доказывает технологическую применимость, а
отсутствие нормы в архиве не доказывает ничего: корпус покрывает не все виды работ.
Поэтому у нормы, которой в архиве нет, свидетельства просто нет — и никакого штрафа.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from backend.runtime_paths import mutable_path


SCHEMA = "les.smeta.estimate-usage-corpus.v1"



def corpus_path() -> Path:
    return Path(mutable_path("data/smeta_base/estimate_usage_corpus.json"))


def corpus_revision(path: str | None = None) -> str:
    """Отпечаток файла корпуса: размер и время правки.

    Кеши держатся за него, иначе процесс запоминает состояние «корпуса нет» и не
    замечает появившийся файл — воспроизведено в ревью 10.09.

    Время берётся в наносекундах: посекундная точность не различала две пересборки
    одинакового размера внутри одной секунды, и кеш отдавал прежний корпус.
    """
    target = Path(path) if path else corpus_path()
    try:
        stat = target.stat()
    except OSError:
        return "absent"
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def load_corpus(path: str | None = None) -> dict[str, Any]:
    """Прочитать корпус применений; отсутствие файла означает «подсказок нет»."""
    return _load_corpus_cached(path, corpus_revision(path))


@lru_cache(maxsize=4)
def _load_corpus_cached(path: str | None, revision: str) -> dict[str, Any]:
    target = Path(path) if path else corpus_path()
    empty = {"schema": SCHEMA, "sections": {}, "source": "", "revision": revision}
    if not target.is_file():
        return empty
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(payload, Mapping):
        return empty
    sections = payload.get("sections")
    return {
        "schema": str(payload.get("schema") or SCHEMA),
        "sections": sections if isinstance(sections, Mapping) else {},
        "source": str(payload.get("source") or ""),
        "revision": str(payload.get("revision") or revision),
    }


def _section_index(section: str, path: str | None = None) -> dict[str, dict[str, Any]]:
    return _section_index_cached(section, path, corpus_revision(path))


@lru_cache(maxsize=64)
def _section_index_cached(section: str, path: str | None, revision: str) -> dict[str, dict[str, Any]]:
    payload = load_corpus(path).get("sections") or {}
    entry = payload.get(section)
    norms = (entry or {}).get("norms") if isinstance(entry, Mapping) else None
    index: dict[str, dict[str, Any]] = {}
    for item in norms or ():
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("norm_code") or "").strip()
        if code:
            index[code] = dict(item)
    return index


def usage_evidence(norm_code: str, section: str, *, path: str | None = None) -> dict[str, Any]:
    """Свидетельство о применении нормы в разделе — с происхождением цифры.

    Пустой словарь означает «архив об этой норме молчит»: это не довод против неё.
    """
    if not norm_code or not section:
        return {}
    index = _section_index(section, path)
    entry = index.get(str(norm_code).strip())
    if not entry:
        return {}
    try:
        count = int(entry.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return {}
    corpus = load_corpus(path)
    payload = corpus.get("sections") or {}
    section_entry = payload.get(section) if isinstance(payload, Mapping) else None
    files = 0
    if isinstance(section_entry, Mapping):
        try:
            files = int(section_entry.get("files") or 0)
        except (TypeError, ValueError):
            files = 0
    unit = str(entry.get("unit") or "").strip()
    return {
        "applications": count,
        "section": section,
        "section_files": files,
        "unit": unit,
        "source": str(corpus.get("source") or ""),
        "revision": str(corpus.get("revision") or ""),
        "examples": entry.get("examples") or [],
        "norm_title": str(entry.get("title") or ""),
        "note": _usage_note(count, files, unit),
    }


def _usage_note(count: int, files: int, unit: str) -> str:
    """Одно применение и девяносто — разные основания, и формулировка это разделяет."""
    scale = "единичный случай" if count == 1 else ("редко" if count < 5 else "регулярно")
    tail = f", единица «{unit}»" if unit else ""
    where = f" из {files} смет раздела" if files else ""
    return f"в архиве применяется {scale}: {count} раз{where}{tail}"


def usage_reason(norm_code: str, section: str, *, path: str | None = None) -> str:
    """Причина для листа проверки — со ссылкой на практику, а не на догадку."""
    evidence = usage_evidence(norm_code, section, path=path)
    return str(evidence.get("note") or "")


def archive_provenance(item: Mapping[str, Any], card: Mapping[str, Any]) -> dict[str, Any]:
    """Keep observations separate from an unverified mapping to today's catalogue."""
    examples = [dict(e) for e in (item.get("examples") or []) if isinstance(e, Mapping)]
    differences = []
    for archived, current in (("norm_title", "title"), ("norm_unit", "measure_unit")):
        values = {str(e.get(archived) or "").strip() for e in examples}
        values.add(str(item.get(archived) or item.get("unit" if archived == "norm_unit" else "title") or "").strip())
        values.discard("")
        if any(value != str(card.get(current) or "").strip() for value in values):
            differences.append(archived)
    editions = {str(e["edition"]) for e in examples if e.get("edition")}
    if len(editions) > 1 or (editions and str(card.get("edition") or "") not in editions):
        differences.append("edition")
    located = bool(examples) and all(
        all(e.get(k) for k in ("document", "sha256", "sheet", "work_row", "original_code"))
        for e in examples
    )
    return {
        "status": "source_located" if located else "incomplete",
        "source": str(item.get("source") or ""), "revision": str(item.get("revision") or ""),
        "examples": examples, "archive_title": str(item.get("norm_title") or item.get("title") or ""),
        "archive_unit": str(item.get("norm_unit") or item.get("unit") or ""),
        "identity_check": {"equivalent": False if differences else None, "differences": differences},
        "unknowns": ["соответствие издания и состава нормы", "условия монтажа на текущем объекте",
                     "включение изделия в ресурсы работы", "физическое количество текущей операции"],
    }


def archive_provenance_text(value: Mapping[str, Any]) -> str:
    examples = value.get("examples") or []
    origins = []
    for e in examples[:3]:
        origins.append(
            f"{e.get('document')} SHA256:{e.get('sha256')} {e.get('sheet')}!"
            f"работа:{e.get('work_row')}, изделие:{e.get('material_row')}; "
            f"{e.get('original_code')} [{e.get('norm_unit')}], {e.get('norm_title')}; "
            f"связь:{e.get('link_kind')}, оборудование:{e.get('equipment')}, издание:{e.get('edition')}"
        )
    if len(examples) > 3:
        origins.append(f"ещё {len(examples)-3} примеров в provenance snapshot")
    return (
        f"Архив: {value.get('archive_title')} [{value.get('archive_unit')}]. "
        + (" | ".join(origins) if origins else "Координаты исходника отсутствуют; provenance неполный.")
        + f" Соответствие активной норме не подтверждено; различия: {value.get('identity_check', {}).get('differences')}. "
        "Расположение после работы не доказывает ресурсную связь. Частота не доказывает пригодность. "
        "Неизвестны: " + "; ".join(value.get("unknowns") or []) + "."
    )


def section_examples(section: str, *, limit: int = 5, path: str | None = None) -> list[dict[str, Any]]:
    """Частые нормы раздела — подсказка модели о том, чем такие работы закрывают."""
    index = _section_index(section, path)
    ranked = sorted(index.values(), key=lambda item: -int(item.get("count") or 0))
    return [
        {
            "norm_code": item.get("norm_code"),
            "title": item.get("title"),
            "unit": item.get("unit"),
            "count": item.get("count"),
        }
        for item in ranked[: max(0, int(limit))]
    ]
