"""Operator-visible LSR readiness: coverage vs norms vs prices, plus file packaging."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from proxy.services.lsr_source_coverage_service import (
    build_source_coverage,
    canonicalize_row_role,
    inferred_row_role,
)

SCHEMA = "les.lsr-result-readiness.v1"

_ABSENT_CODES = frozenset({"", "missing", "нет", "не найдено", "—"})
_CHOSEN_STATUSES = frozenset(
    {
        "EXACT",
        "ANALOGUE",
        "ANALOGUE_CANDIDATE",
        "EXACT_VERIFIED",
        "ANALOGUE_VERIFIED",
    }
)
_OPEN_STATUSES = frozenset(
    {"MISSING", "NEEDS_RESEARCH", "CONFLICT", "UNVERIFIED", ""}
)
_PRICE_SOURCE_LABEL = {
    "needs_kac": "КАЦ или выбранная ценовая книга",
    "needs_labor_rate": "ставка ОЗП",
    "needs_machinist_rate": "ставка ЗПМ",
    "needs_fgis_price": "цена эксплуатации машины ФГИС ЦС",
    "needs_price": "подтверждённая цена",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm_code(row: Mapping[str, Any]) -> str:
    return _text(row.get("norm_code") or row.get("code") or row.get("basis"))


def _norm_status(row: Mapping[str, Any]) -> str:
    return _text(row.get("norm_status")).upper()


def _locator(row: Mapping[str, Any]) -> str:
    return _text(row.get("source_row"))


def _preview(items: Sequence[str], *, limit: int = 8) -> str:
    values = [_text(item) for item in items if _text(item)]
    if not values:
        return ""
    shown = ", ".join(values[:limit])
    extra = len(values) - limit
    if extra > 0:
        shown += f" и ещё {extra}"
    return shown


def _structured_price_gaps(
    missing: Sequence[str],
    extra: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in extra:
        if not isinstance(item, Mapping):
            continue
        resource = _text(item.get("resource") or item.get("code"))
        key = resource or _text(item.get("action"))
        if not key or key in seen:
            continue
        seen.add(key)
        required = _text(item.get("required_source")) or _PRICE_SOURCE_LABEL.get(
            _text(item.get("price_action")), "подтверждённая цена"
        )
        quantity = item.get("quantity")
        action = _text(item.get("action")) or (
            f"Задайте цену для {resource or 'ресурса'}"
            + (f", количество {quantity}" if quantity not in (None, "") else "")
            + f". Источник: {required}."
        )
        gaps.append(
            {
                "resource": resource,
                "quantity": quantity,
                "required_source": required,
                "action": action,
            }
        )
    for item in missing:
        text = _text(item)
        if not text.startswith("price_missing:"):
            continue
        code = text.split(":", 1)[-1].strip()
        if not code or code in seen:
            continue
        seen.add(code)
        gaps.append(
            {
                "resource": code,
                "quantity": None,
                "required_source": "подтверждённая цена или выбранная ценовая книга",
                "action": (
                    f"Задайте цену для ресурса {code}. "
                    "Отсутствие цены не отменяет выбранную норму."
                ),
            }
        )
    return gaps


def _unbound_locators(missing: Sequence[str]) -> list[str]:
    locators: list[str] = []
    for item in missing:
        text = _text(item)
        if text.startswith("row:"):
            locators.append(text.split(":", 1)[-1].strip())
    return locators


def classify_norm_gap(row: Mapping[str, Any]) -> str:
    """Why this model row is not a closed professional selection."""

    role = inferred_row_role(row)
    if role in {"material", "equipment", "resource", "unresolved"}:
        return ""
    if canonicalize_row_role(row.get("row_role")) == "header":
        # A heading is accounted as structure; it never requires a mounting norm.
        return ""
    status = _norm_status(row)
    code = _norm_code(row)
    if status in _OPEN_STATUSES or code.casefold() in _ABSENT_CODES:
        if status == "CONFLICT":
            return "conflict"
        if status == "NEEDS_RESEARCH":
            return "needs_research"
        return "missing_norm"
    if status and status not in _CHOSEN_STATUSES:
        return "open_status"
    if not code:
        return "missing_norm"
    return ""


def build_lsr_result_readiness(
    *,
    packaged: bool,
    packaging_failed: bool = False,
    packaging_code: str = "",
    rows: Sequence[Mapping[str, Any]] = (),
    missing: Sequence[str] = (),
    pricing_status: str = "",
    paused: bool = False,
    remaining_locators: Sequence[str] = (),
    catalog_work_count: int = 0,
    catalog_locators: Sequence[str] = (),
    price_gaps: Sequence[Mapping[str, Any]] = (),
    calculated_positions: int = -1,
    confirmed_amount: float = -1.0,
    preliminary_amount: float = -1.0,
) -> dict[str, Any]:
    """Split technical file readiness from coverage, norms, and prices."""

    work_rows = [dict(row) for row in rows if isinstance(row, Mapping) and _locator(row)]
    remaining = [_text(item) for item in remaining_locators if _text(item)]
    cited = {_locator(row) for row in work_rows}
    wanted = [_text(item) for item in catalog_locators if _text(item)]
    if not wanted:
        wanted = list(dict.fromkeys([_locator(row) for row in work_rows] + remaining))
    coverage = build_source_coverage(
        catalog_locators=wanted,
        rows=work_rows,
        remaining_locators=remaining,
    )
    incomplete = set(coverage["incomplete_locators"])
    remaining = list(dict.fromkeys(
        [item for item in remaining if item not in cited or item in incomplete]
        + coverage["incomplete_locators"]
    ))
    norm_gaps: list[dict[str, str]] = []
    for row in work_rows:
        kind = classify_norm_gap(row)
        if not kind:
            continue
        locator = _locator(row)
        if kind == "conflict":
            action = (
                f"Проверьте применимость выбранного шифра {_norm_code(row) or 'без кода'} "
                f"для строки {locator}; код его не подменяет."
            )
        elif kind == "needs_research":
            action = (
                f"Продолжите поиск нормы для строки {locator}. "
                "Уже принятые строки повторно не ищутся."
            )
        else:
            action = (
                f"Модель должна выбрать норму для строки {locator} "
                "или явно оставить пропуск. Код шифр не подставляет."
            )
        norm_gaps.append({"locator": locator, "kind": kind, "action": action})
    for locator in remaining:
        norm_gaps.append(
            {
                "locator": locator,
                "kind": "structure_incomplete" if locator in cited else "unprocessed",
                "action": (
                    f"Продолжите незакрытую строку {locator}. "
                    "Повторный поиск уже обработанных строк не выполняется."
                ),
            }
        )

    structured_prices = _structured_price_gaps(missing, price_gaps)
    unbound = _unbound_locators(missing)
    priced_complete = (
        not structured_prices
        and _text(pricing_status) in {"", "priced_final"}
        and not packaging_failed
    )
    if packaged and _text(pricing_status) in {"priced_partial", "norm_selection_required"}:
        priced_complete = False
    if structured_prices:
        priced_complete = False

    if packaged and not packaging_failed:
        file_status = "ready"
        file_action = "Файл собран из сохранённых решений модели."
    elif packaging_failed:
        file_status = "failed"
        code = _text(packaging_code) or "WORKBOOK_GENERATION_FAILED"
        file_action = (
            f"Пересоберите файл без модели ({code}). "
            "Строки решения не пересматриваются."
        )
    elif work_rows:
        file_status = "missing"
        file_action = (
            "Пересоберите файл без модели по сохранённым строкам. "
            "Новый вызов модели не нужен."
        )
    else:
        file_status = "missing"
        file_action = "Сначала получите таблицу решений модели."

    norms_complete = not norm_gaps and (
        not catalog_work_count or len(cited) >= int(catalog_work_count)
    )
    if remaining:
        norms_complete = False
    coverage_complete = bool(coverage.get("complete"))
    if remaining:
        coverage_complete = False

    if paused and remaining:
        continue_action = (
            "Нажмите «Продолжить незакрытые строки». "
            "Источники и решения сохранены; поиск уже обработанного не повторяется."
        )
    elif paused:
        continue_action = (
            "Сборка остановлена. Можно пересобрать файл без модели "
            "или продолжить, если остались пробелы."
        )
    else:
        continue_action = ""

    if coverage_complete:
        coverage_action = "Все исходные строки учтены как работа, материал, ресурс, заголовок или вопрос."
    else:
        coverage_action = (
            "Закройте покрытие исходника: каждая строка должна иметь роль. "
            f"{_preview([str(item.get('locator') or '') for item in coverage.get('gaps') or []])}."
        ).strip()

    if norms_complete:
        norms_action = "Все работы имеют выбранную норму или явный пропуск."
    elif remaining:
        norms_action = (
            "Продолжите незакрытые строки: "
            f"{_preview(remaining)}. Код нормы не выбирает."
        )
    else:
        norms_action = (
            "Закройте пробелы норм по конкретным строкам ниже. "
            "Код не подтверждает и не заменяет шифр."
        )

    if priced_complete:
        prices_action = "Цены закрыты по выбранным ресурсам."
    elif structured_prices:
        prices_action = (
            "Задайте подтверждённые цены: "
            f"{_preview([str(item.get('resource') or '') for item in structured_prices])}."
        )
    elif unbound:
        prices_action = (
            "Сначала закройте нормы у строк "
            f"{_preview(unbound)}, затем пересоберите файл без модели."
        )
    else:
        prices_action = (
            "Пересоберите файл без модели после закрытия норм; "
            "цены подставляются из выбранной книги. Отсутствие цены не обнуляет норму."
        )

    counts = {
        "works": sum(1 for row in work_rows if inferred_row_role(row) == "work"),
        "materials": sum(1 for row in work_rows if inferred_row_role(row) == "material"),
        "equipment": sum(1 for row in work_rows if inferred_row_role(row) == "equipment"),
        "headers": sum(1 for row in work_rows if canonicalize_row_role(row.get("row_role")) == "header"),
        "unresolved": sum(1 for row in work_rows if inferred_row_role(row) == "unresolved"),
        "norms_selected": sum(1 for row in work_rows if _norm_code(row) and not classify_norm_gap(row)),
    }
    if calculated_positions >= 0:
        counts["calculated_positions"] = int(calculated_positions)
    if confirmed_amount >= 0:
        counts["confirmed_amount"] = round(float(confirmed_amount), 2)
    if preliminary_amount >= 0:
        counts["preliminary_amount"] = round(float(preliminary_amount), 2)

    technical_complete = file_status == "ready"
    estimate_complete = bool(
        coverage_complete and norms_complete and priced_complete and technical_complete
    )

    dimensions = {
        "file": {
            "ready": file_status == "ready",
            "status": file_status,
            "action": file_action,
        },
        "coverage": {
            "complete": bool(coverage_complete),
            "gap_count": int(coverage.get("gap_count") or 0),
            "accounted": int(coverage.get("accounted") or 0),
            "catalog_count": int(coverage.get("catalog_count") or 0),
            "gaps": list(coverage.get("gaps") or [])[:80],
            "action": coverage_action,
        },
        "norms": {
            "complete": bool(norms_complete),
            "gap_count": len(norm_gaps),
            "gaps": norm_gaps[:80],
            "action": norms_action,
        },
        "prices": {
            "complete": bool(priced_complete),
            "gap_count": len(structured_prices),
            "codes": [
                str(item.get("resource") or "")
                for item in structured_prices
                if item.get("resource")
            ][:40],
            "gaps": structured_prices[:80],
            "action": prices_action,
        },
    }
    actions: list[dict[str, str]] = []
    if file_status != "ready" and work_rows:
        actions.append({"id": "repack", "label": "Пересобрать файл", "kind": "repack"})
    if remaining or paused:
        actions.append(
            {"id": "resume", "label": "Продолжить незакрытые строки", "kind": "resume"}
        )
    if work_rows and not estimate_complete and (not coverage_complete or not norms_complete):
        actions.append(
            {"id": "refine", "label": "Уточнить выбранные строки", "kind": "refine"}
        )
    if work_rows and not estimate_complete:
        actions.append(
            {
                "id": "enter_data",
                "label": "Внести подтверждённые данные",
                "kind": "enter_data",
            }
        )
    if file_status == "ready" and not estimate_complete:
        actions.append({"id": "repack", "label": "Пересобрать файл", "kind": "repack"})

    unique_actions: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in actions:
        key = item["id"]
        if key in seen:
            continue
        seen.add(key)
        unique_actions.append(item)

    return {
        "schema": SCHEMA,
        "paused": bool(paused),
        "remaining_locators": remaining,
        "catalog_work_count": int(catalog_work_count or len(wanted) or 0),
        "row_count": len(work_rows),
        "technical_complete": technical_complete,
        "estimate_complete": estimate_complete,
        "counts": counts,
        "coverage": coverage,
        "dimensions": dimensions,
        "actions": unique_actions,
        "continue_action": continue_action,
    }


def format_lsr_readiness_notice(
    readiness: Mapping[str, Any] | None,
    *,
    filename: str = "",
) -> str:
    """Visible coverage / norms / prices status next to the workbook link."""

    payload = dict(readiness or {})
    dimensions = payload.get("dimensions") if isinstance(payload.get("dimensions"), Mapping) else {}
    file_dim = dimensions.get("file") if isinstance(dimensions.get("file"), Mapping) else {}
    coverage_dim = (
        dimensions.get("coverage") if isinstance(dimensions.get("coverage"), Mapping) else {}
    )
    norms_dim = dimensions.get("norms") if isinstance(dimensions.get("norms"), Mapping) else {}
    prices_dim = dimensions.get("prices") if isinstance(dimensions.get("prices"), Mapping) else {}
    file_bit = f" Файл: {filename}." if filename else ""
    file_ready = bool(file_dim.get("ready"))
    coverage_complete = bool(coverage_dim.get("complete"))
    norms_complete = bool(norms_dim.get("complete"))
    prices_complete = bool(prices_dim.get("complete"))
    if file_ready and coverage_complete and norms_complete and prices_complete:
        return f"ЛСР собрана.{file_bit}".strip()
    parts = [f"ЛСР собрана частично.{file_bit}".strip()]
    counts = payload.get("counts") if isinstance(payload.get("counts"), Mapping) else {}
    if counts:
        composition = (
            f"Состав: работ {int(counts.get('works') or 0)}, материалов "
            f"{int(counts.get('materials') or 0)}, оборудования {int(counts.get('equipment') or 0)}, "
            f"заголовков {int(counts.get('headers') or 0)}, нерешённых {int(counts.get('unresolved') or 0)}; "
            f"норм выбрано {int(counts.get('norms_selected') or 0)}"
        )
        if counts.get("calculated_positions") is not None:
            composition += f", позиций рассчитано {int(counts['calculated_positions'])}"
        if counts.get("confirmed_amount") is not None:
            composition += (
                f". Подтверждённая сумма {float(counts['confirmed_amount']):g}, "
                f"предварительная {float(counts.get('preliminary_amount') or 0):g}"
            )
        parts.append(composition + ".")
    file_label = "файл готов" if file_ready else "файл не готов"
    parts.append(f"Файл: {file_label}. {_text(file_dim.get('action'))}".strip())
    if coverage_complete:
        parts.append("Покрытие исходника: полное.")
    else:
        parts.append(
            f"Покрытие исходника: не полное ({int(coverage_dim.get('gap_count') or 0)}). "
            f"{_text(coverage_dim.get('action'))}".strip()
        )
    if norms_complete:
        parts.append("Нормы: полные.")
    else:
        parts.append(
            f"Нормы: не полные ({int(norms_dim.get('gap_count') or 0)}). "
            f"{_text(norms_dim.get('action'))}".strip()
        )
    if prices_complete:
        parts.append("Цены: полные.")
    else:
        parts.append(
            f"Цены: не полные ({int(prices_dim.get('gap_count') or 0)}). "
            f"{_text(prices_dim.get('action'))}".strip()
        )
    continue_action = _text(payload.get("continue_action"))
    if continue_action:
        parts.append(continue_action)
    gap_lists = list(coverage_dim.get("gaps") or []) + list(norms_dim.get("gaps") or [])
    gap_lists.extend(list(prices_dim.get("gaps") or []))
    concrete = [
        _text(item.get("action"))
        for item in gap_lists[:6]
        if isinstance(item, Mapping) and _text(item.get("action"))
    ]
    if concrete:
        parts.append("Требуемые действия: " + " ".join(concrete))
    return " ".join(part for part in parts if part)
