"""Composition-checker состава ПД по ПП РФ №87 от 16.02.2008 (T2.5, implementation_plan.md).

АРХИТЕКТУРА: детерминированная сверка обязательных разделов проектной документации (перечень —
``config/checklists/pp87_composition.yaml``) с inventory датасета. Реальные файлы корпуса ПД
именуются «Раздел ПД №N. Часть M. <код раздела>...» (СЕССИЯ, запись 16/implementation_plan.md
§блокер 4) — сопоставление ведётся regex-паттернами по имени файла, БЕЗ похода в LLM/RAG/Qdrant.

Как и остальные механизмы ``checklist_review_service`` (``_run_presence``/``_run_calculation``),
``check_composition`` — чистая функция: config и inventory приходят параметрами, ни одного
обращения к живым сервисам внутри модуля. Загрузка конфига (``load_pp87_config``) — отдельная
fail-closed функция по образцу ``normcontrol_review_map_service.load_review_map`` /
``checklist_param_rules.load_param_rules``: любая кривизна схемы -> ``ValueError``, не молчаливый
дефолт.

Статусы раздела:
  - ``present``  — найден >=1 файл, совпавший с filename_patterns раздела;
  - ``missing``  — required=always, файлов не найдено (нарушение состава);
  - ``unknown``  — required=conditional, файлов не найдено — ОТСУТСТВИЕ EVIDENCE НЕ РАВНО
    НАРУШЕНИЮ (тот же принцип, что и в presence/calculation/parametric — правило 3
    implementation_plan.md): кондиционный раздел мог быть не нужен для конкретного объекта,
    код не имеет права утверждать нарушение без экспертной оценки применимости.

Ни одного LLM-вызова. Используется ``checklist_review_service``/API-слоем как источник
computed-evidence для top-level поля ``pp87_composition`` контракта ``checklist_review_v1``
(см. промпт T2.5 и docstring ``checklist_review_service`` — намеренно НЕ привязано к items
дисциплины «Общее», см. Запись 17 SESSION_LOG.md: ни один из 5 критериев «Общее» не про состав
разделов ПД).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_VALID_REQUIRED = {"always", "conditional"}

_PP87_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "checklists" / "pp87_composition.yaml"
)


def _need(section: dict, key: str, ctx: str):
    value = section.get(key)
    if value in (None, ""):
        raise ValueError(f"pp87_composition {ctx}: пустое/отсутствует обязательное поле '{key}'")
    return value


def load_pp87_config(path: str | Path | None = None) -> dict[str, Any]:
    """Грузит и валидирует ``pp87_composition.yaml`` (fail-closed — любая кривизна схемы поднимает
    ``ValueError``/``FileNotFoundError``, а не молча пропускает битую запись). ``path`` —
    переопределение файла (тесты); по умолчанию — канонический конфиг репозитория."""
    yaml_path = Path(path) if path is not None else _PP87_CONFIG_PATH
    if not yaml_path.exists():
        raise FileNotFoundError(f"pp87_composition: файл не найден: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    raw_sections = data.get("sections") or []
    if not raw_sections:
        raise ValueError(f"pp87_composition {yaml_path}: пустой список sections")

    sections: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for i, raw in enumerate(raw_sections):
        ctx = f"sections[{i}]"
        if not isinstance(raw, dict):
            raise ValueError(f"pp87_composition {ctx}: раздел должен быть словарём")

        code = str(_need(raw, "code", ctx))
        if code in seen_codes:
            raise ValueError(f"pp87_composition: дублирующийся code '{code}'")
        seen_codes.add(code)

        title = str(_need(raw, "title", code))

        required = str(_need(raw, "required", code))
        if required not in _VALID_REQUIRED:
            raise ValueError(
                f"pp87_composition {code}: неизвестный required '{required}', "
                f"допустимые: {sorted(_VALID_REQUIRED)}"
            )

        filename_patterns = raw.get("filename_patterns") or []
        if not isinstance(filename_patterns, list) or not filename_patterns:
            raise ValueError(f"pp87_composition {code}: filename_patterns не должен быть пустым")
        for pat in filename_patterns:
            try:
                re.compile(pat, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"pp87_composition {code}: неверный regex '{pat}': {exc}") from exc

        requirement_ref = str(_need(raw, "requirement_ref", code))

        sections.append({
            "code": code,
            "title": title,
            "required": required,
            "filename_patterns": [str(p) for p in filename_patterns],
            "requirement_ref": requirement_ref,
        })

    return {"meta": data.get("meta") or {}, "sections": sections}


def _matches_section(file_name: str, patterns: list[str]) -> bool:
    low = file_name.lower().replace("ё", "е")
    return any(re.search(pat, low, re.IGNORECASE) for pat in patterns)


def check_composition(inventory: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """Сопоставляет ``inventory`` (список ``{file_name, ...}``, как из
    ``checklist_review_service`` inventory_provider) с разделами ``config`` (dict из
    ``load_pp87_config`` либо совместимой структуры — см. тесты с мини-конфигом).

    Чистая функция, 0 LLM, 0 обращений к живым сервисам. Возвращает::

        {
          "sections": [
            {"code", "title", "required", "status": "present|missing|unknown",
             "matched_files": [...], "requirement_ref"},
            ...
          ],
          "summary": {"total", "present", "missing", "unknown", "all_required_present"},
        }
    """
    file_names = [
        str(item.get("file_name") or "")
        for item in inventory
        if str((item or {}).get("file_name") or "").strip()
    ]

    out_sections: list[dict[str, Any]] = []
    present = 0
    missing = 0
    unknown = 0
    all_required_present = True

    for section in config.get("sections") or []:
        patterns = section.get("filename_patterns") or []
        matched = [fn for fn in file_names if _matches_section(fn, patterns)]

        if matched:
            status = "present"
            present += 1
        elif section.get("required") == "always":
            status = "missing"
            missing += 1
            all_required_present = False
        else:
            status = "unknown"
            unknown += 1

        out_sections.append({
            "code": section.get("code", ""),
            "title": section.get("title", ""),
            "required": section.get("required", ""),
            "status": status,
            "matched_files": matched,
            "requirement_ref": section.get("requirement_ref", ""),
        })

    summary = {
        "total": len(out_sections),
        "present": present,
        "missing": missing,
        "unknown": unknown,
        "all_required_present": all_required_present,
    }

    return {"sections": out_sections, "summary": summary}
