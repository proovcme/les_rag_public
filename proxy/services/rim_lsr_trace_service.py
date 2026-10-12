"""РИМ-трасса ЛСР по Приложению 3 к Методике 421/пр (форма локального сметного расчёта РИМ).

Сервис строит объяснимые строки ЛСР: работа -> ресурсы -> цены -> ОЗП/ЭМ/М ->
ФОТ -> НР/СП -> всего. Это не рендер XLSX и не новый калькулятор вместо
``lsr_assembly_service``; это методический слой evidence для проверки граф 2-12.
"""

from __future__ import annotations

import re
import math
import json
from dataclasses import dataclass
from typing import Any, Optional

from proxy.services.estimate_math_service import parse_ru_number
from proxy.services import gesn_service, nr_sp_service


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _round(value: Any, ndigits: int = 2) -> float:
    return round(_f(value), ndigits)


def _num(value: Any) -> Optional[float]:
    if value in (None, "", "-", "—", "–"):
        return None
    try:
        parsed = float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _norm_name(s: Any) -> str:
    import re

    return re.sub(r"\s+", " ", str(s or "").strip().lower().replace("ё", "е")).strip(" .,;:")


_NORM_REF_RE = re.compile(
    r"(ГЭСН(?:мр|м|п|р)?|ФЕР(?:мр|м|п|р)?|ТЕР(?:мр|м|п|р)?)?\s*:?\s*"
    r"(\d{2}[-–]\d{2}[-–]\d{3}[-–]\d{2})",
    flags=re.IGNORECASE,
)


def _norm_prefix(prefix: str) -> str:
    raw = str(prefix or "").strip().replace(" ", "")
    if not raw:
        return ""
    upper = raw.upper()
    for base in ("ГЭСН", "ФЕР", "ТЕР"):
        if upper.startswith(base):
            suffix = upper.replace(base, "", 1).lower()
            return base + suffix
    return raw


def _extract_norm_code(value: Any) -> str:
    """Extract a norm code from a visible LSR/BOR cell without choosing a norm."""
    match = _NORM_REF_RE.search(str(value or ""))
    if not match:
        return ""
    prefix = _norm_prefix(match.group(1) or "")
    bare = match.group(2).replace("–", "-")
    return f"{prefix}{bare}" if prefix else bare


def _canon_unit(unit: Any) -> str:
    s = str(unit or "").strip().lower().replace("³", "3").replace("²", "2")
    s = s.replace("куб.м", "м3").replace("кв.м", "м2").replace("куб м", "м3").replace("кв м", "м2")
    s = re.sub(r"\s+", "", s)
    s = s.replace("п.м.", "м").replace("п.м", "м").replace("м.п.", "м").replace("м.п", "м")
    s = re.sub(r"^\d+(?=[а-яa-z])", "", s).strip(".,;:")
    s = re.sub(r"[()]", "", s)
    aliases = {"мп": "м", "пм": "м", "meter": "м", "meters": "м", "m": "м", "m2": "м2", "m3": "м3"}
    if s in aliases:
        return aliases[s]
    if "линия" in s or "цепь" in s or s.startswith(("канал", "измерен")):
        return "линия"
    if s.startswith(("систем", "объект", "комплекс", "статив", "шкаф", "устройств", "аппарат", "точк", "порт", "мест", "номер", "отверст")):
        return "шт"
    if s.startswith(("шт", "штук", "компл", "комплект", "порт", "точк")):
        return "шт"
    if s.startswith("кг"):
        return "кг"
    if s.startswith(("тонн", "т")):
        return "т"
    if s.startswith("км"):
        return "км"
    if s.startswith("м3"):
        return "м3"
    if s.startswith("м2"):
        return "м2"
    if s == "м" or s.startswith(("м.", "мкаб", "мтруб", "мкороб", "мпровод")):
        return "м"
    return s


def _norm_unit_factor(unit: Any) -> tuple[float, str]:
    match = re.match(r"\s*(\d+(?:[.,]\d+)?)?\s*(.+)", str(unit or "").strip())
    if not match:
        return 1.0, _canon_unit(unit)
    factor = _num(match.group(1)) if match.group(1) else 1.0
    return float(factor or 1.0), _canon_unit(match.group(2))


def _same_unit_text(left: Any, right: Any) -> bool:
    a = re.sub(r"\s+", "", str(left or "").strip().lower().replace("³", "3").replace("²", "2"))
    b = re.sub(r"\s+", "", str(right or "").strip().lower().replace("³", "3").replace("²", "2"))
    return bool(a and a == b)


_SCALED_UNIT = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(\D.*)$")


def _price_unit_scale(resource_unit: Any, price_unit: Any) -> float | None:
    """Сколько единиц ресурса в одной единице цены: «1000 м» для «м» — 1000.

    ФССЦ часто даёт цену за укрупнённую единицу (кабель за 1000 м, изделия за 100 шт),
    а ведомость и норма — в базовой. Это одна физическая единица с множителем, то есть
    арифметика, а не физический пересчёт; разные физические единицы остаются конфликтом.
    """
    if _same_unit_text(resource_unit, price_unit):
        return 1.0

    def split(unit: Any) -> tuple[float, str]:
        text = str(unit or "").strip()
        match = _SCALED_UNIT.match(text)
        if not match:
            return 1.0, text
        return float(match.group(1).replace(",", ".")), match.group(2)

    resource_factor, resource_base = split(resource_unit)
    price_factor, price_base = split(price_unit)
    if resource_factor <= 0 or price_factor <= 0 or not _same_unit_text(resource_base, price_base):
        return None
    return price_factor / resource_factor


def _unit_conversion_factor(src: str, dst: str) -> float | None:
    if src == dst:
        return 1.0
    return {
        ("м", "км"): 0.001,
        ("км", "м"): 1000.0,
        ("кг", "т"): 0.001,
        ("т", "кг"): 1000.0,
    }.get((src, dst))


def _first_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


# Слова, после которых число — характеристика изделия, а не его длина. Диаметр муфты
# 50 мм пересчитывался в 0,05 м/шт, а «дальность передачи 100 м» у патч-корда длиной
# 2 м забирала верх (ревью Codex 11.09).
_NOT_A_LENGTH = (
    "диаметр", "сечени", "толщин", "ширин", "высот", "глубин", "радиус", "шаг",
    "дальност", "расстояни", "температур", "давлени", "напряжени", "частот",
    "погружени", "изгиб", "габарит", "размер",
)


def _piece_length_m_from_visible_row(row: dict[str, Any]) -> float | None:
    """Длина в одной штуке, если строка её сама называет: «(305 м)», «бухта 305 м».

    Тот же приём, что уже принят для площади: недостающий множитель берётся из самой
    строки ведомости, а не выдумывается. Кабель в ведомости стоит бухтами — «шт. × 120»,
    — а норма прокладки измеряется сотней метров; без длины бухты пересчёт невозможен,
    и расчёт законно отказывал. Длина при этом написана в наименовании (живой прогон
    11.09: строки 995 и 996 ведомости СКС).

    Правило намеренно узкое, потому что ошибка здесь тихо портит смету:

    * только метры и километры — миллиметры и сантиметры описывают габарит, а не длину
      изделия («муфта, диаметр 50 мм» давала 0,05 м/шт);
    * число после слова-характеристики не годится («дальность передачи 100 м» у
      патч-корда длиной 2 м забирала верх, потому что бралось наибольшее);
    * несколько разных кандидатов без скобок — отказ: угадывать нельзя.
    """
    text = " ".join(
        str(_first_value(row, key) or "")
        for key in ("title", "name", "work", "наименование", "работа", "description")
    )
    text = text.replace(",", ".").lower()
    bracketed: list[float] = []
    plain: list[float] = []
    for match in re.finditer(r"(?<![\dxх×.])(\d+(?:\.\d+)?)\s*(км|km|м|m)(?![\wа-я])", text):
        prefix = text[max(0, match.start() - 30):match.start()]
        if any(word in prefix for word in _NOT_A_LENGTH):
            continue
        if text[match.end():match.end() + 2].strip()[:1] in {"x", "х", "×"}:
            continue
        scale = 1000.0 if match.group(2) in {"км", "km"} else 1.0
        metres = float(match.group(1)) * scale
        if metres <= 0 or metres > 100000:
            continue
        opened = text.rfind("(", 0, match.start())
        closed = text.find(")", match.end())
        if opened != -1 and closed != -1 and text.find(")", opened, match.start()) == -1:
            bracketed.append(metres)
        else:
            plain.append(metres)
    if bracketed:
        return bracketed[0] if len(set(bracketed)) == 1 else None
    if not plain:
        return None
    return plain[0] if len(set(plain)) == 1 else None


def _piece_area_m2_from_visible_row(row: dict[str, Any]) -> float | None:
    text = " ".join(
        str(_first_value(row, key) or "")
        for key in ("title", "name", "work", "наименование", "работа", "description")
    )
    text = text.replace(",", ".").lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*[xх×]\s*(\d+(?:\.\d+)?)\s*(мм|mm|см|cm|м|m)?", text)
    if not match:
        return None
    left = float(match.group(1))
    right = float(match.group(2))
    unit = (match.group(3) or "мм").lower()
    if unit in {"мм", "mm"}:
        scale = 0.001
    elif unit in {"см", "cm"}:
        scale = 0.01
    else:
        scale = 1.0
    area = left * scale * right * scale
    if area <= 0:
        return None
    return area


@dataclass(frozen=True)
class PriceTrace:
    price: Optional[float]
    source: str
    column_8: Optional[float] = None
    column_9: Optional[float] = None
    column_10: Optional[float] = None
    basis: str = ""
    action: str = ""
    unit_price_precision: int = 2


def _missing_price_action(res: dict[str, Any]) -> str:
    kind = str(res.get("kind") or "")
    if kind == "material":
        return "needs_kac"
    if kind == "labor":
        return "needs_labor_rate"
    if kind == "machinist":
        return "needs_machinist_rate"
    if kind == "machine":
        return "needs_fgis_price"
    return "needs_price"


def _resolve_price_trace(
    res: dict[str, Any],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    ignore_source_price: bool = False,
) -> PriceTrace:
    """Вернуть цену ресурса с сохранением происхождения граф 8-10."""
    if not ignore_source_price and res.get("price") not in (None, ""):
        price = _num(res.get("price"))
        if price is None:
            return PriceTrace(price=None, source="invalid_resource_price", action="invalid_resource_price", basis="explicit_resource_price")
        price = round(price, 2)
        return PriceTrace(price=price, source="manual", column_10=price, basis="explicit_resource_price")

    code = str(res.get("code") or "").strip()
    if code and pricebook is not None:
        diagnostic = getattr(pricebook, 'lookup_diagnostic', lambda _code: {})(code)
        if diagnostic.get('status') == 'ambiguous':
            return PriceTrace(price=None, source='price_record_ambiguous', action='price_record_ambiguous',
                              basis='conflicting exact records: ' + code)
        rec = pricebook.lookup(code)
        if rec is not None:
            scale = _price_unit_scale(res.get('unit'), rec.get('unit'))
            if scale is None:
                return PriceTrace(price=None, source='price_unit_conflict', action='price_unit_conflict',
                    basis=f"resource unit={res.get('unit')}; pricebook unit={rec.get('unit')}")
            # Цена за укрупнённую единицу приводится к единице ресурса без округления
            # промежуточного значения: 56 223,48 ₽ за 1000 м × 8 500 м иначе теряют рубли.
            per_unit = (lambda value: _round(value) if scale == 1.0 else round(value / scale, 6))
            scale_note = "" if scale == 1.0 else f"; pricebook unit={rec.get('unit')} / {scale:g}"
            current = _num(rec.get("price_current"))
            if current is not None:
                price = per_unit(current)
                return PriceTrace(
                    price=price,
                    source="fgis_current",
                    column_10=price,
                    basis="split_form_col_8" + scale_note,
                )
            base = _num(rec.get("price_base"))
            index = _num(rec.get("index"))
            if base is not None and index is not None:
                price = per_unit(base * index)
                return PriceTrace(
                    price=price,
                    source="fgis_base_index",
                    # Keep the indexed-price operands precise after unit scaling.
                    # The final unit price is rounded once, identically in JSON and XLSX.
                    column_8=_round(base) if scale == 1.0 else base / scale,
                    column_9=_round(index, 6) if scale == 1.0 else index,
                    column_10=price,
                    basis="split_form_col_5_x_col_9" + scale_note,
                    unit_price_precision=2 if scale == 1.0 else 6,
                )
            eff = _num(rec.get("price_current_eff"))
            if eff is not None:
                price = per_unit(eff)
                return PriceTrace(
                    price=price,
                    source="fgis_effective",
                    column_10=price,
                    basis="split_form_effective_price" + scale_note,
                )

    if str(res.get("kind")) == "material" and kac_map:
        price = kac_map.get(_norm_name(res.get("name")))
        if price is not None:
            price = _round(price)
            return PriceTrace(price=price, source="kac", column_10=price, basis="kac")

    action = _missing_price_action(res)
    return PriceTrace(price=None, source=action, basis=action, action=action)


@dataclass(frozen=True)
class _NormSnapshot:
    norm: dict[str, Any]


def _position_norm(position: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve the authored norm against its delivered revision, never reselect it."""
    from proxy.smeta_core.norm_revision import NormRevisionConflict

    code = str(position.get("code") or "").strip()
    if not code:
        return None
    expected = position.get("normative_identity")
    status = position.get("normative_identity_status")
    if status == "conflict":
        raise NormRevisionConflict(expected or {},
            {"candidates": position.get("normative_identity_conflicts") or []},
            "conflicting_delivered_revisions")
    if status == "pinned" and not expected:
        raise NormRevisionConflict({}, {}, "normative_identity_missing")
    # The first exact read is kept for this calculation. Later material accounting
    # and trace rendering must not hydrate a different file revision mid-operation.
    snapshot = position.get("_norm_snapshot")
    if isinstance(snapshot, _NormSnapshot):
        return snapshot.norm
    return (gesn_service.get_norm(code, expected_identity=expected)
            if expected else gesn_service.get_norm(code))


def _revision_conflict(error) -> dict[str, Any]:
    return {"status": "conflict", "expected": error.expected,
            "actual": error.actual, "reason": error.reason}


def _position_resources(position: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Вернуть норму и ресурсы с ``per_unit``; explicit resources поддержаны для тестов/ручного ввода."""
    code = str(position.get("code") or "").strip()
    # ``resources`` is a tri-state contract:
    # - key absent: hydrate the norm's source resources;
    # - non-empty list: use the explicit model revision;
    # - empty list: the revision intentionally contains no confirmed resources.
    # Treating [] as "not supplied" resurrected the raw norm after an unresolved
    # model review and bypassed labor normalization.
    if code and "resources" not in position:
        norm = _position_norm(position)
        if norm is None:
            return None, []
        from proxy.smeta_core.resource_normalizer import normalize_norm_resources

        return norm, normalize_norm_resources(list(norm.get("resources") or []))

    norm = _position_norm(position) if code else None
    work_qty = _f(position.get("qty")) or 1.0
    resources: list[dict[str, Any]] = []
    for res in position.get("resources") or []:
        line = dict(res)
        if line.get("per_unit") in (None, ""):
            quantity = _num(line.get("qty"))
            line["per_unit"] = quantity / work_qty if quantity is not None and work_qty else quantity
        resources.append(line)
    return norm, resources


def _row(
    row_type: str,
    label: str,
    *,
    columns: dict[int, Any] | None = None,
    source: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": row_type,
        "label": label,
        "columns": {str(k): v for k, v in (columns or {}).items() if v not in (None, "")},
        "source": source,
        "meta": meta or {},
    }


def _resource_coeff(kind: str, *, k_ozp: float, k_em: float) -> float:
    if kind == "labor":
        return k_ozp
    if kind in {"machine", "machinist"}:
        return k_em
    return 1.0


def build_position_trace(
    position: dict[str, Any],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
) -> dict[str, Any]:
    """Построить доказательную РИМ-трассу одной позиции ЛСР.

    ``position`` обычно содержит ``code`` ГЭСН и ``qty`` объёма работ. Если ``resources`` не переданы,
    ресурсы берутся из ``gesn_service``. НР/СП берутся из позиции, из нормы или из ``nr_sp_service``.
    """
    kac_lookup = {_norm_name(k): _f(v) for k, v in (kac_map or {}).items()}
    work_qty = _f(position.get("qty")) or 0.0
    from proxy.smeta_core.norm_revision import NormRevisionConflict

    revision_conflict = None
    try:
        norm, resources = _position_resources(position)
    except NormRevisionConflict as error:
        norm, resources = None, []
        revision_conflict = _revision_conflict(error)
    from proxy.services import fsem_machinist_service as fsem

    if pricebook is not None:
        resources, fsem_trace = fsem.enrich_machinists(resources, quantity_field="per_unit")
    else:
        # A raw trace without a pricebook preserves explicit legacy/manual
        # machinist prices. Full FSEM replacement is meaningful only together
        # with the active tariff book that prices the derived driver codes.
        resources = [dict(item) for item in resources]
        fsem_trace = {
            "schema": "fsem_enrichment_v1",
            "status": "not_applied_without_pricebook",
        }
    flags: list[str] = []
    completeness_reasons: list[str] = []
    if position.get('_document_price_basis', {}).get('status', 'pinned') != 'pinned':
        completeness_reasons.append('price_basis_missing')
    if revision_conflict:
        flags.append("конфликт версии нормативной базы: " + json.dumps(revision_conflict, ensure_ascii=False))
        completeness_reasons.append("norm_revision_conflict")
    elif position.get("normative_identity_status") == "unpinned":
        flags.append("версия показанной модели нормативной карточки не сохранена; расчёт предварительный")
        completeness_reasons.append("normative_identity_missing")
    if position.get("coefficient_status") == "needs_basis":
        flags.append(str(position.get("coefficient_note") or "коэффициент не подтверждён"))
        completeness_reasons.append("coefficient_basis_required")
    if fsem_trace.get("status") == "unresolved":
        details = list(fsem_trace.get("reasons") or fsem_trace.get("missing_machine_codes") or [])
        flags.append("ФСЭМ не смог детализировать ОТм: " + "; ".join(str(item) for item in details))
        completeness_reasons.append("fsem_unresolved")
    norm_source_integrity: dict[str, Any] = {}
    if norm and str(norm.get("_source_kind") or "") == "structured_sqlite":
        from proxy.smeta_core.integrity import normative_base_integrity

        norm_source_integrity = normative_base_integrity(base_path=str(norm.get("_source_path") or ""))
        if not norm_source_integrity.get("trusted_for_pricing"):
            flags.append("нормативная база в карантине: semantic integrity gate не пройден")
            completeness_reasons.append("normative_source_untrusted")
    if position.get("code") and norm is None and not position.get("resources"):
        flags.append(f"норма ГЭСН не найдена: {position.get('code')}")
        completeness_reasons.append("norm_missing")

    review_was_required = "resource_review_status" in position
    resource_review_status = str(position.get("resource_review_status") or "not_required_raw_trace")
    resource_review_reason = str(position.get("resource_review_reason") or "")
    if review_was_required and resource_review_status not in {"keep_all_confirmed", "actions_confirmed"}:
        flags.append("ресурсный состав нормы не подтверждён моделью" + (f": {resource_review_reason}" if resource_review_reason else ""))
        completeness_reasons.append("resource_review_unresolved")
    component_review = {
        "labor": (
            str(position.get("labor_review_status") or ""),
            str(position.get("labor_review_reason") or ""),
        ),
        "machine": (
            str(position.get("machine_review_status") or ""),
            str(position.get("machine_review_reason") or ""),
        ),
        "material": (
            str(position.get("material_review_status") or ""),
            str(position.get("material_review_reason") or ""),
        ),
    }
    for component, (status, reason) in component_review.items():
        if status and status not in {"confirmed", "not_present"}:
            flags.append(
                f"компонент {component} не подтверждён моделью"
                + (f": {reason}" if reason else "")
            )
            completeness_reasons.append(f"{component}_review_unresolved")

    work_code = position.get("code") or (norm or {}).get("code") or ""
    work_name = position.get("name") or (norm or {}).get("name") or ""
    work_unit = position.get("unit") or (norm or {}).get("unit") or ""
    nr_sp = nr_sp_service.resolve(
        work_name,
        code=work_code,
        rule_id=str(position.get("nr_sp_rule_id") or "") or None,
    )
    nr_pct = _f(position.get("nr_pct") if position.get("nr_pct") not in (None, "") else (norm or {}).get("nr_pct", nr_sp["nr_pct"]))
    sp_pct = _f(position.get("sp_pct") if position.get("sp_pct") not in (None, "") else (norm or {}).get("sp_pct", nr_sp["sp_pct"]))
    if (
        not str(nr_sp.get("status") or "").startswith("resolved")
        and position.get("nr_pct") in (None, "")
        and position.get("sp_pct") in (None, "")
    ):
        flags.append("НР/СП не разрешены по виду работ: нужен нормативный источник/явный выбор")
        completeness_reasons.append("nr_sp_unresolved")

    detail_rows: dict[str, list[dict[str, Any]]] = {"labor": [], "machine": [], "machinist": [], "material": []}
    sums = {"labor": 0.0, "machine": 0.0, "machinist": 0.0, "material": 0.0}
    qty_sums: dict[str, float | None] = {"labor": 0.0, "machine": 0.0, "machinist": 0.0, "material": 0.0}

    for res in resources:
        kind = str(res.get("kind") or "")
        coeff = _resource_coeff(kind, k_ozp=k_ozp, k_em=k_em)
        coeff *= (position.get("resource_coefficients") or {}).get(kind, 1.0)
        per_unit = _num(res.get("per_unit"))
        total_qty = round(per_unit * coeff * work_qty, 6) if per_unit is not None else None
        price = _resolve_price_trace(res, pricebook=pricebook, kac_map=kac_lookup,
            ignore_source_price=bool(position.get('_current_prices_only') and not position.get('material_only')))
        current_card = pricebook.lookup(str(res.get('code') or '')) if pricebook is not None else None
        cost = round(total_qty * price.price, 2) if total_qty is not None and price.price is not None else None
        if res.get('excluded'):
            cost = 0.0  # Explicitly removed quantity has zero effect even without a current price.
        if per_unit is None and not res.get("excluded"):
            flags.append(f"неизвестный расход: {res.get('name','?')} ({res.get('code','—')})")
            completeness_reasons.append(f"quantity_missing:{res.get('code') or res.get('name') or '?'}")
        # Снятый решением модели ресурс в деньгах не участвует, и его цена не нужна. Флаг
        # ставит только проверенное снятие; нулевой или неизвестный ресурс без него проверку
        # цены не минует (проверка Codex 17.09).
        if price.price is None and not res.get("excluded"):
            action_label = {
                "needs_kac": "нужен КАЦ",
                "needs_labor_rate": "нужна ставка ОЗП",
                "needs_machinist_rate": "нужна ставка ЗПМ",
                "needs_fgis_price": "нужна цена эксплуатации машины",
                "price_unit_conflict": "несовместимые единицы ресурса и ценового справочника",
            }.get(price.action or price.source, "нужна цена")
            flags.append(f"{action_label}: {res.get('name','?')} ({res.get('code','—')})")
            completeness_reasons.append(f"price_missing:{res.get('code') or res.get('name') or '?'}")
        if kind not in detail_rows:
            flags.append(f"неизвестный вид ресурса: {kind!r}")
            continue
        if cost is not None:
            sums[kind] = round(sums[kind] + cost, 2)
        if total_qty is None:
            qty_sums[kind] = None
        elif qty_sums[kind] is not None:
            qty_sums[kind] = round(qty_sums[kind] + total_qty, 6)
        detail_rows[kind].append(
            _row(
                f"resource_{kind}",
                str(res.get("name") or ""),
                columns={
                    2: res.get("code") or "",
                    3: res.get("name") or "",
                    4: res.get("unit") or "",
                    5: per_unit,
                    6: coeff,
                    7: total_qty,
                    8: price.column_8,
                    9: price.column_9,
                    10: price.column_10,
                    11: 1,
                    12: cost,
                },
                source=price.source,
                meta={
                    "basis": price.basis,
                    "kind": kind,
                    "price_action": price.action,
                    "unit_price_precision": price.unit_price_precision,
                    "price_card_name": res.get("price_card_name") or "",
                    "price_source_ref": res.get("price_source_ref") or "",
                    "resource_binding": res.get("resource_binding") or {},
                    **({'normative_price': res.get('price')} if position.get('_current_prices_only')
                       and not position.get('material_only') and 'price' in res else {}),
                    **({'price_record_identity': current_card.get('price_record_identity')}
                       if current_card and price.source.startswith('fgis') else {}),
                    **{key: res[key] for key in ('source_resource_ids', 'source_resource_group_id',
                       'excluded', 'excluded_per_unit') if key in res},
                    **({'normative_identity': position.get('normative_identity')}
                       if res.get('source_resource_ids') else {}),
                },
            )
        )

    ozp = sums["labor"]
    zpm = sums["machinist"]
    em = round(sums["machine"] + zpm, 2)
    mat = sums["material"]
    direct = round(ozp + em + mat, 2)
    fot = round(ozp + zpm, 2)
    nr = round(fot * nr_pct / 100, 2)
    sp = round(fot * sp_pct / 100, 2)
    total = round(direct + nr + sp, 2)
    full_amount = total if not completeness_reasons else None
    position_total_label = "Всего по позиции" if full_amount is not None else "Известная стоимость позиции"

    rows: list[dict[str, Any]] = [
        _row(
            "work",
            work_name,
            columns={2: work_code, 3: work_name, 4: work_unit, 5: work_qty, 6: 1, 7: work_qty},
            source="gesn",
            meta={
                "normative_source": {
                    **({"identity": (norm or {}).get("normative_identity"),
                        "identity_status": position.get("normative_identity_status") or "unbound",
                        "expected_identity": position.get("normative_identity"),
                        "revision_conflict": revision_conflict}
                       if position.get("normative_identity_status") or (norm or {}).get("normative_identity") else {}),
                    **{key: (norm or {}).get(key, "")
                       for key in ("norm_id", "edition", "base_type", "key", "source_ref")},
                },
                **({'document_price_basis': position['_document_price_basis']}
                   if '_document_price_basis' in position else {}),
                "official_name": position.get("official_name") or (norm or {}).get("name") or "",
                "selection_kind": position.get("selection_kind") or "",
                "is_analog": bool(position.get("is_analog")),
                "analog_limitations": list(position.get("analog_limitations") or []),
                "binding_reason": position.get("binding_reason") or "",
                # Коэффициент, предложенный моделью и не принятый расчётом: рендер
                # ставит по нему примечание к графе «коэф.».
                "coefficient_status": position.get("coefficient_status") or "",
                "proposed_coefficient": position.get("proposed_coefficient"),
                "coefficient_note": position.get("coefficient_note") or "",
                "coefficient_basis": position.get("coefficient_basis") or "",
                "coefficient_target": position.get("coefficient_target") or "",
                "source_row": position.get("source_row"),
                "work_id": position.get("work_id"),
                "operation": position.get("operation") or "",
                "coverage": position.get("coverage") or "",
                "not_covered": position.get("not_covered") or "",
                "quantity_trace": position.get("quantity_trace") or {},
            },
        ),
    ]
    if k_ozp != 1.0 or k_em != 1.0 or position.get("resource_coefficients"):
        rows.append(
            _row(
                "coefficient",
                position.get("coefficient_basis") or coefficient_basis or "Повышающие коэффициенты",
                columns={3: position.get("coefficient_basis") or coefficient_basis or "Повышающие коэффициенты", 6: 1},
                source="coefficient",
                meta={"k_ozp": k_ozp, "k_em": k_em,
                      **({"resource_coefficients": position["resource_coefficients"]}
                         if position.get("resource_coefficients") else {})},
            )
        )

    rows.extend(
        [
            _row("group_labor", "ОТ(ЗТ)", columns={3: "ОТ(ЗТ)", 4: "чел.-ч", 7: qty_sums["labor"], 12: ozp}),
            *detail_rows["labor"],
            _row("group_machine", "ЭМ", columns={3: "ЭМ", 12: em}),
            *detail_rows["machine"],
            _row("group_machinist", "ОТм(ЗТм)", columns={3: "ОТм(ЗТм)", 4: "чел.-ч", 7: qty_sums["machinist"], 12: zpm}),
            *detail_rows["machinist"],
            _row("group_material", "М", columns={3: "М", 12: mat}),
            *detail_rows["material"],
            _row("direct_total", "Итого прямые затраты", columns={3: "Итого прямые затраты", 12: direct}),
            _row("fot", "ФОТ", columns={3: "ФОТ", 12: fot}),
            _row("nr", "НР", columns={3: "НР", 4: "%", 5: nr_pct, 7: nr_pct, 12: nr}, source="Пр/812"),
            _row("sp", "СП", columns={3: "СП", 4: "%", 5: sp_pct, 7: sp_pct, 12: sp}, source="Пр/774"),
            _row(
                "position_total",
                position_total_label,
                columns={3: position_total_label, 12: total},
                meta={
                    "amount_status": "complete" if full_amount is not None else "partial",
                    "completeness_reasons": list(dict.fromkeys(completeness_reasons)),
                },
            ),
        ]
    )

    return {
        "code": work_code,
        "name": work_name,
        "unit": work_unit,
        "qty": work_qty,
        "rows": rows,
        "summary": {
            "ozp": ozp,
            "machine": sums["machine"],
            "zpm": zpm,
            "em": em,
            "mat": mat,
            "direct": direct,
            "fot": fot,
            "nr_pct": nr_pct,
            "sp_pct": sp_pct,
            "nr": nr,
            "sp": sp,
            "total": total,
            "known_amount": total,
            "full_amount": full_amount,
            "amount_status": "complete" if full_amount is not None else "partial",
            "completeness_reasons": list(dict.fromkeys(completeness_reasons)),
            "resource_review_status": resource_review_status,
            "resource_review_reason": resource_review_reason,
            "component_review": component_review,
            "labor_qty": qty_sums["labor"],
            "machinist_qty": qty_sums["machinist"],
            "flags": flags,
            "norm_source_integrity": norm_source_integrity,
            "nr_sp_trace": nr_sp,
            "fsem_trace": fsem_trace,
        },
    }


def build_lsr_trace(
    positions: list[dict[str, Any]],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Многопозиционная РИМ-трасса ЛСР: позиции по разделам + итоги разделов + общий свод.

    Каждая позиция строится через :func:`build_position_trace` — числа те же, gold позиции сохраняется
    (один общий калькулятор, не дубль). Разделы — по полю ``position["section"]`` (порядок первого
    появления, позиции одного раздела группируются вместе). Свод — Σ позиций (код, не LLM):
    прямые/ФОТ/НР/СП/Всего и нормативные чел.-ч рабочих/машинистов для шапки формы.
    """
    sections: list[dict[str, Any]] = []
    by_section: dict[str, dict[str, Any]] = {}
    for pos in positions or []:
        trace = build_position_trace(
            pos,
            pricebook=pricebook,
            kac_map=kac_map,
            k_ozp=k_ozp,
            k_em=k_em,
            coefficient_basis=coefficient_basis,
        )
        sec_name = str(pos.get("section") or "").strip() or "Без раздела"
        trace = {**trace, "section": sec_name}
        if pos.get("work_id") is not None:
            trace["work_id"] = pos.get("work_id")
        if pos.get("source_row") is not None:
            trace["source_row"] = pos.get("source_row")
        if pos.get("source_refs") is not None:
            trace["source_refs"] = list(pos.get("source_refs") or [])
        entry = by_section.get(sec_name)
        if entry is None:
            entry = {"section": sec_name, "positions": [], "total": 0.0}
            by_section[sec_name] = entry
            sections.append(entry)
        entry["positions"].append(trace)
        entry["total"] = round(entry["total"] + _f(trace["summary"]["total"]), 2)

    money_keys = ("ozp", "zpm", "machine", "em", "mat", "direct", "fot", "nr", "sp", "total")
    summary: dict[str, Any] = {k: 0.0 for k in money_keys}
    summary["labor_qty"] = 0.0
    summary["machinist_qty"] = 0.0
    flags: list[str] = []
    all_positions_complete = True
    count = 0
    for entry in sections:
        for trace in entry["positions"]:
            s = trace["summary"]
            for k in money_keys:
                summary[k] = round(summary[k] + _f(s.get(k)), 2)
            for key in ("labor_qty", "machinist_qty"):
                if summary[key] is None or s.get(key) is None:
                    summary[key] = None
                else:
                    summary[key] = round(summary[key] + s[key], 6)
            flags.extend(s.get("flags") or [])
            all_positions_complete = all_positions_complete and s.get("full_amount") is not None
            count += 1
    summary["positions"] = count
    summary["flags"] = flags
    summary["known_amount"] = summary["total"]
    summary["full_amount"] = summary["total"] if count and all_positions_complete else None
    summary["amount_status"] = "complete" if summary["full_amount"] is not None else "partial"
    if count and all_positions_complete and not flags:
        summary["result_status"] = "priced_final"
    elif count:
        summary["result_status"] = "priced_partial"
    else:
        summary["result_status"] = "norm_selection_required"

    return {"name": name or "", "sections": sections, "summary": summary}


def _code_from_visible_row(row: dict[str, Any]) -> str:
    explicit = _first_value(row, "code", "norm_code", "basis", "justification", "обоснование")
    return _extract_norm_code(explicit)


def selected_norm_code(row: dict[str, Any]) -> str:
    """Шифр, который расчёт возьмёт из строки: одна точка истины для проверки и расчёта."""
    return _code_from_visible_row(dict(row))


def norm_codes_in_value(value: Any) -> list[str]:
    """Все шифры норм, записанные в одном поле, в порядке появления.

    Поле «…-05 (аналог …-02)» подтверждалось карточкой …-02, а считалось по …-05
    (аудит Codex 17.09): разные шифры в одном поле — конфликт формата, а не выбор.
    """
    out: list[str] = []
    for match in _NORM_REF_RE.finditer(str(value or "")):
        prefix = _norm_prefix(match.group(1) or "")
        bare = match.group(2).replace("–", "-")
        code = f"{prefix}{bare}" if prefix else bare
        if code not in out:
            out.append(code)
    return out


def _quantity_from_visible_row(row: dict[str, Any]) -> tuple[float | None, str, str]:
    raw_qty = _first_value(
        row,
        "qty",
        "quantity",
        "quantity_total",
        "volume",
        "amount_qty",
        "количество",
        "кол-во",
        "объем",
        "объём",
    )
    qty = parse_ru_number(raw_qty)
    unit = str(_first_value(row, "unit", "ед", "ед.", "единица", "единица измерения") or "").strip()
    return qty, unit, str(raw_qty or "")


def _norm_qty_from_visible_row(row: dict[str, Any], code: str, norm: dict[str, Any] | None) -> tuple[float | None, dict[str, Any]]:
    """Convert a visible physical quantity into the norm quantity.

    The model/user owns the row and norm binding. Code only converts units after
    that binding: e.g. 61 м2 with a norm unit 100 м2 becomes 0.61.
    """
    raw_qty, source_unit, raw_qty_text = _quantity_from_visible_row(row)
    if row.get('conversion_factor') not in (None, ''):
        from proxy.smeta_core.material_accounting import finite_number

        multiplier = finite_number(row.get('conversion_factor'))
        target_unit = str(row.get('conversion_unit') or '').strip()
        source_ref = str(row.get('conversion_source') or '').strip()
        if multiplier is None or multiplier <= 0 or not target_unit or not source_ref or raw_qty is None:
            return None, {'status': 'conversion_basis_required', 'source_quantity': raw_qty,
                          'source_unit': source_unit}
        converted_row = {key: value for key, value in row.items() if not key.startswith('conversion_')}
        converted_row.update(quantity=raw_qty * multiplier, unit=target_unit)
        value, detail = _norm_qty_from_visible_row(converted_row, code, norm)
        return value, {**detail, 'source_quantity': raw_qty, 'source_unit': source_unit,
                       'conversion_factor': multiplier, 'conversion_unit': target_unit,
                       'conversion_source': source_ref,
                       'formula': f'{raw_qty:g} {source_unit} × {multiplier:g} {target_unit}/{source_unit}; ' + str(detail.get('formula') or '')}
    if raw_qty is None:
        return None, {
            "status": "missing_quantity",
            "source_quantity": raw_qty_text,
            "source_unit": source_unit,
            "message": "нет количества для расчёта строки",
        }
    if norm is None:
        return float(raw_qty), {
            "status": "norm_not_found",
            "source_quantity": raw_qty,
            "source_unit": source_unit,
            "norm_unit": "",
            "formula": str(raw_qty),
        }

    norm_unit = str(norm.get("unit") or "")
    factor, norm_base_unit = _norm_unit_factor(norm_unit)
    if not source_unit:
        return float(raw_qty), {
            "status": "assumed_norm_quantity",
            "source_quantity": raw_qty,
            "source_unit": "",
            "norm_unit": norm_unit,
            "formula": f"{raw_qty} норм.-ед.",
            "message": "единица строки не указана; количество принято как количество нормы",
        }
    if _same_unit_text(source_unit, norm_unit):
        return float(raw_qty), {
            "status": "direct_norm_quantity",
            "source_quantity": raw_qty,
            "source_unit": source_unit,
            "norm_unit": norm_unit,
            "formula": f"{raw_qty} {source_unit}",
        }

    source_base_unit = _canon_unit(source_unit)
    if source_base_unit == "шт" and norm_base_unit == "м":
        length_m = _piece_length_m_from_visible_row(row)
        if length_m is not None:
            converted = round(float(raw_qty) * length_m, 9)
            norm_qty = round(converted / factor, 9)
            return norm_qty, {
                "status": "piece_length_conversion",
                "source_quantity": raw_qty,
                "source_unit": source_unit,
                "norm_unit": norm_unit,
                "formula": f"{raw_qty} {source_unit} × {length_m:g} м/шт / {factor:g} = {norm_qty}",
            }
    if source_base_unit == "шт" and norm_base_unit == "м2":
        area_m2 = _piece_area_m2_from_visible_row(row)
        if area_m2 is not None:
            converted = round(float(raw_qty) * area_m2, 9)
            norm_qty = round(converted / factor, 9)
            return norm_qty, {
                "status": "piece_area_conversion",
                "source_quantity": raw_qty,
                "source_unit": source_unit,
                "norm_unit": norm_unit,
                "formula": f"{raw_qty} {source_unit} × {area_m2:g} м2/шт / {factor:g} = {norm_qty}",
            }
    conv = _unit_conversion_factor(source_base_unit, norm_base_unit)
    if conv is None:
        return None, {
            "status": "unit_conflict",
            "source_quantity": raw_qty,
            "source_unit": source_unit,
            "norm_unit": norm_unit,
            "message": f"единица строки {source_unit!r} не переводится в измеритель нормы {norm_unit!r}",
        }
    converted = round(float(raw_qty) * conv, 9)
    norm_qty = round(converted / factor, 9)
    return norm_qty, {
        "status": "unit_conversion" if conv != 1.0 or factor != 1.0 else "direct_from_row",
        "source_quantity": raw_qty,
        "source_unit": source_unit,
        "norm_unit": norm_unit,
        "formula": f"{raw_qty} {source_unit} × {conv:g} / {factor:g} = {norm_qty}",
    }


def positions_from_visible_lsr_rows(rows: list[dict[str, Any]], *, pricebook=None) -> dict[str, Any]:
    """Bind already visible/selected LSR rows to trace positions.

    This function does not search or select norms. It only accepts rows that
    already contain a norm code, converts their quantities to the norm unit and
    returns skipped rows as explicit bindings for the model/user to fix.
    """
    positions: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    from collections import Counter
    from proxy.smeta_core.row_decision import SECTION, decision_kind, describe_decision, section_conflicting_fields, section_reason
    identities = Counter(str(row.get("work_id") or row.get("source_row") or idx)
                         for idx, row in enumerate(rows or [], 1))
    source_counts = Counter(str(row.get("source_row") or idx) for idx, row in enumerate(rows or [], 1))
    section_sources = {str(row.get("source_row") or idx) for idx, row in enumerate(rows or [], 1)
                       if decision_kind(row) == SECTION}
    for idx, row in enumerate(rows or [], 1):
        model_source_row = row.get("source_row")
        source_row = (
            model_source_row
            if (
                isinstance(model_source_row, int)
                and not isinstance(model_source_row, bool)
                and model_source_row > 0
            )
            or (isinstance(model_source_row, str) and bool(model_source_row.strip()))
            else idx
        )
        if row.get("parse_error"):
            bindings.append({
                "row": source_row, "status": "model_row_format_error",
                "message": "неоднозначное число ячеек: исходная строка сохранена, расчёт не выполнен",
                "source_row": dict(row),
            })
            continue
        if str(source_row) in section_sources:
            # Only an explicit authored kind enters this branch. Titles, formatting
            # and missing quantities never classify or remove a source row.
            conflicting_fields = section_conflicting_fields(row)
            conflict = source_counts[str(source_row)] > 1 or bool(conflicting_fields)
            duplicate = identities[str(row.get('work_id') or source_row)] > 1
            reason = section_reason(row)
            status = ("source_role_conflict" if conflict else
                      "duplicate_work_id" if duplicate else
                      "section_recognized" if reason else "section_reason_required")
            bindings.append({
                "row": source_row, "work_id": str(row.get("work_id") or source_row),
                "status": status, "decision_kind": decision_kind(row),
                "decision": describe_decision(row), "source_row": dict(row),
                "conflicting_fields": conflicting_fields,
                "message": ("раздел одновременно содержит расчётные указания или другие операции строки"
                            if conflict else "идентификатор решения повторён" if duplicate else
                            reason if reason else "модель не объяснила, почему строка является разделом"),
            })
            continue
        evidence_error = str(row.get("evidence_error") or "")
        if evidence_error:
            status, message = {
                "unknown_evidence_ref": (
                    "evidence_ref_unknown",
                    "ссылка нормы не указывает на карточку прохода: расчёт не выполнен",
                ),
                "norm_code_not_in_referenced_evidence": (
                    "evidence_card_mismatch",
                    "карточка ссылки относится к другой норме: расчёт не выполнен",
                ),
                "ambiguous_norm_code": (
                    "norm_code_ambiguous",
                    "в norm_code несколько шифров: расчёт не выполнен",
                ),
            }.get(evidence_error, (
                "evidence_ref_required",
                "норма выбрана без ссылки на карточку: расчёт не выполнен",
            ))
            bindings.append({
                "row": source_row, "status": status, "message": message,
                "source_row": dict(row),
            })
            continue
        if identities[str(row.get("work_id") or source_row)] > 1:
            bindings.append({"row": source_row, "status": "duplicate_work_id", "source_row": dict(row),
                             "message": "идентификатор операции повторён; расчёт неоднозначен"})
            continue
        code = _code_from_visible_row(row)
        from proxy.smeta_core.row_decision import RESOURCE, MATERIAL, decision_kind, describe_decision

        kind = decision_kind(row)
        if kind in (RESOURCE, MATERIAL):
            # A parent norm reference is not an instruction to repeat that work.
            # Preserve the model decision and expose the missing accounting step.
            bindings.append({
                "row": source_row,
                "code": code,
                "status": ("resource_accounting_unverified" if kind == RESOURCE
                           else "material_pricing_required"),
                "message": ("учёт ресурсом работы не подтверждён расчётом" if kind == RESOURCE
                            else "самостоятельный материал требует расчёта стоимости"),
                "decision": describe_decision(row),
                "source_row": dict(row),
            })
            continue
        if not code:
            bindings.append({
                "row": source_row,
                "status": "norm_selection_required",
                "message": "в строке нет шифра нормы",
                "source_row": row,
            })
            continue
        from proxy.smeta_core.norm_revision import NormRevisionConflict
        try:
            norm = _position_norm({**row, "code": code})
        except NormRevisionConflict as error:
            revision = _revision_conflict(error)
            bindings.append({"row": source_row, "code": code,
                             "status": "norm_revision_conflict", "source_row": dict(row),
                             "normative_revision": revision,
                             "message": "конфликт версии нормативной базы: " + json.dumps(revision, ensure_ascii=False)})
            continue
        if norm is None:
            bindings.append({
                "row": source_row,
                "code": code,
                "status": "norm_not_found",
                "message": "шифр нормы не найден в нормативной базе",
                "source_row": row,
            })
            continue
        norm_qty, qty_trace = _norm_qty_from_visible_row(row, code, norm)
        if norm_qty is None:
            bindings.append({
                "row": source_row,
                "code": code,
                "status": qty_trace.get("status") or "needs_input",
                "quantity_trace": qty_trace,
                "reason": str(qty_trace.get("message") or ""),
                "source_row": row,
            })
            continue
        title = str(_first_value(row, "title", "name", "work", "наименование", "работа") or "")
        position = {
            "code": code,
            "work_id": str(row.get("work_id") or source_row),
            "operation": str(row.get("operation") or ""),
            "coverage": str(row.get("coverage") or ""),
            "not_covered": str(row.get("not_covered") or ""),
            "binding_reason": str(row.get("analogue") or ""),
            "nr_sp_rule_id": str(row.get("nr_sp_rule_id") or "").strip().strip("—-").strip(),
            "qty": norm_qty,
            "section": str(_first_value(row, "section", "раздел") or "").strip() or "Без раздела",
            "source_row": source_row,
            "quantity_trace": qty_trace,
            "_norm_snapshot": _NormSnapshot(norm),
            **{key: row[key] for key in ("normative_identity", "normative_identity_status",
                "normative_identity_refs", "normative_identity_conflicts", "resource_delivery_proof") if key in row},
        }
        if title:
            position["name"] = title
        if norm and norm.get("unit"):
            position["unit"] = norm.get("unit")
        positions.append(position)
        binding = {
            "row": source_row,
            "code": code,
            "status": "bound",
            "quantity_trace": qty_trace,
            "position": {k: v for k, v in position.items() if k not in {"source_row", "_norm_snapshot"}},
        }
        # Коэффициент модели не применяется кодом и не исчезает молча. Повышающий
        # коэффициент в смете берётся из МДС или приложения к сборнику и требует
        # основания; применить предложенное число без него значит поменять деньги
        # догадкой. Поэтому он доходит до расчёта как отметка, требующая проверки
        # человеком (ревью Codex 11.09).
        proposed = _first_value(row, "coefficient", "коэффициент", "coef")
        try:
            proposed_value = float(str(proposed).replace(",", ".")) if proposed not in (None, "") else 1.0
        except (TypeError, ValueError):
            proposed_value = None
        if proposed_value is None or not math.isfinite(proposed_value) or abs(proposed_value - 1.0) > 1e-9:
            displayed_value = f"{proposed_value:g}" if proposed_value is not None and math.isfinite(proposed_value) else str(proposed)
            if proposed_value is None or not math.isfinite(proposed_value):
                proposed_value = str(proposed)
            binding["proposed_coefficient"] = proposed_value
            binding["coefficient_status"] = "needs_basis"
            # Та же отметка кладётся в позицию: из неё строится строка трассы, а из
            # строки — ячейка книги. Пока отметка жила только в разборе, до самой книги
            # она не доходила, то есть до проверяющего не доходила вовсе (шаг 3).
            position["proposed_coefficient"] = proposed_value
            position["coefficient_status"] = "needs_basis"
            basis = str(row.get("coefficient_basis") or "").strip()
            target = str(row.get("coefficient_target") or "").strip().casefold()
            targets = {part.strip() for part in target.replace(";", ",").split(",") if part.strip()}
            applicable = (isinstance(proposed_value, (int, float)) and proposed_value > 0
                          and basis.casefold() not in {"", "-", "—", "нет", "н/д", "n/a", "unknown", "неизвестно"}
                          and bool(targets)
                          and targets <= {"labor", "machines", "materials"})
            position.update(coefficient_basis=basis, coefficient_target=target)
            binding.update(coefficient_basis=basis, coefficient_target=target)
            position["coefficient_note"] = (
                f"модель предложила коэффициент {displayed_value}; в расчёт не принят "
                "без основания (МДС или приложение к сборнику)"
            )
            binding["quantity_trace"] = {
                **(qty_trace or {}),
                "proposed_coefficient": proposed_value,
                "coefficient_note": (
                    f"модель предложила коэффициент {displayed_value}; в расчёт не принят "
                    "без основания (МДС или приложение к сборнику)"
                ),
            }
            if applicable:
                components = {"labor": ("labor",), "machines": ("machine", "machinist"),
                              "materials": ("material",)}
                position["resource_coefficients"] = {
                    kind: proposed_value for component in targets for kind in components[component]}
                position["coefficient_status"] = binding["coefficient_status"] = "applied"
                position["coefficient_note"] = f"модель: коэффициент {displayed_value}; область {target}; основание {basis}"
                binding["quantity_trace"].update(coefficient_note=position["coefficient_note"],
                    coefficient_basis=basis, coefficient_target=target)
            else:
                binding["status"] = "coefficient_basis_required"
                position["coefficient_note"] += f"; заявленное основание: {basis or 'нет'}; область: {target or 'не указана'}"
        bindings.append(binding)
    for row, binding in zip(rows or [], bindings, strict=True):
        binding["work_id"] = str(row.get("work_id") or binding["row"])
        # Authored caveats must reach the existing XLSX review columns for every
        # operation, including standalone supplies. This projection does not grant
        # resource confirmation: apply_model_review still checks the exact receipt.
        for component in ("labor", "machine", "material", "dominant"):
            for suffix in ("status", "reason"):
                key = f"{component}_review_{suffix}"
                if key in row:
                    binding[key] = row[key]
    from proxy.smeta_core.material_accounting import account_material_rows

    return account_material_rows(positions, bindings, pricebook=pricebook)


def build_lsr_trace_from_visible_rows(
    rows: list[dict[str, Any]],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
    name: str = "",
    document_price_basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Visible/BOR/LSR rows with selected norm codes -> priced_partial/final RIM trace."""
    bound = positions_from_visible_lsr_rows(rows, pricebook=pricebook)
    if document_price_basis is not None:
        for position in bound['positions']:
            position['_current_prices_only'] = True
            position['_document_price_basis'] = document_price_basis
    lsr = build_lsr_trace(
        bound["positions"],
        pricebook=pricebook,
        kac_map=kac_map,
        k_ozp=k_ozp,
        k_em=k_em,
        coefficient_basis=coefficient_basis,
        name=name,
    )
    from proxy.smeta_core.row_decision import operation_executed, row_accounted, source_resolved, decision_resolved

    binding_flags = [
        f"строка {b.get('row')}: {b.get('message') or b.get('status')}"
        for b in bound["row_bindings"]
        if not decision_resolved(b.get("status"))
    ]
    summary = lsr.setdefault("summary", {})
    summary["input_rows"] = len(rows or [])
    from proxy.smeta_core.row_decision import aggregate_operation_statuses
    statuses = aggregate_operation_statuses([
        {"source_row": b["row"], "work_id": b.get("work_id"), "status": b["status"]}
        for b in bound["row_bindings"]])
    summary["bound_operations"] = sum(operation_executed(b.get('status')) for b in bound['row_bindings'])
    summary["bound_rows"] = sum(row_accounted(status) for status in (statuses or {}).values())
    summary["non_work_rows"] = sum(status == 'section_recognized' for status in (statuses or {}).values())
    summary["resolved_source_rows"] = sum(source_resolved(status) for status in (statuses or {}).values())
    summary["source_rows"] = len({str(binding["row"]) for binding in bound["row_bindings"]})
    summary["work_positions"] = sum(not p.get('material_only') for p in bound['positions'])
    summary["unbound_rows"] = max(0, summary['source_rows'] - summary['resolved_source_rows'])
    summary["unbound_operations"] = sum(not decision_resolved(b.get('status')) for b in bound['row_bindings'])
    # Строка, состоящая только из исполненных изменений состава, не учтена, хотя ни одна
    # её операция не упала: без флага книга назвала бы такой расчёт полным.
    binding_flags.extend(
        f"строка {key}: изменение состава без операции, учитывающей строку"
        for key, status in (statuses or {}).items()
        if not row_accounted(status) and operation_executed(status))
    if binding_flags:
        summary["flags"] = list(summary.get("flags") or []) + binding_flags
        summary["full_amount"] = None
        summary["amount_status"] = "partial"
    if not bound["positions"]:
        summary["result_status"] = ("norm_revision_conflict" if any(
            b.get("status") == "norm_revision_conflict" for b in bound["row_bindings"])
            else "no_calculated_positions" if summary['non_work_rows'] == summary['source_rows'] and summary['source_rows']
            else "norm_selection_required")
    elif summary.get("flags"):
        summary["result_status"] = "priced_partial"
    else:
        summary["result_status"] = "priced_final"
    lsr["row_bindings"] = bound["row_bindings"]
    if document_price_basis is not None:
        lsr['document_price_basis'] = document_price_basis
        if document_price_basis.get('status') != 'pinned':
            summary.update(full_amount=None, amount_status='partial', result_status='price_basis_missing')
            summary.setdefault('flags', []).append('price_basis_' + str(document_price_basis.get('status')))
    return lsr
