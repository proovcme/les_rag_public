"""РИМ-трасса ЛСР по Приложению 3 к Методике 421/пр (форма локального сметного расчёта РИМ).

Сервис строит объяснимые строки ЛСР: работа -> ресурсы -> цены -> ОЗП/ЭМ/М ->
ФОТ -> НР/СП -> всего. Это не рендер XLSX и не новый калькулятор вместо
``lsr_assembly_service``; это методический слой evidence для проверки граф 2-12.
"""

from __future__ import annotations

import re
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
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
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
) -> PriceTrace:
    """Вернуть цену ресурса с сохранением происхождения граф 8-10."""
    if res.get("price") not in (None, ""):
        price = _round(res.get("price"))
        return PriceTrace(price=price, source="manual", column_10=price, basis="explicit_resource_price")

    code = str(res.get("code") or "").strip()
    if code and pricebook is not None:
        rec = pricebook.lookup(code)
        if rec is not None:
            current = _num(rec.get("price_current"))
            if current is not None:
                price = _round(current)
                return PriceTrace(
                    price=price,
                    source="fgis_current",
                    column_10=price,
                    basis="split_form_col_8",
                )
            base = _num(rec.get("price_base"))
            index = _num(rec.get("index"))
            if base is not None and index is not None:
                price = _round(base * index)
                return PriceTrace(
                    price=price,
                    source="fgis_base_index",
                    column_8=_round(base),
                    column_9=_round(index, 6),
                    column_10=price,
                    basis="split_form_col_5_x_col_9",
                )
            eff = _num(rec.get("price_current_eff"))
            if eff is not None:
                price = _round(eff)
                return PriceTrace(
                    price=price,
                    source="fgis_effective",
                    column_10=price,
                    basis="split_form_effective_price",
                )

    if str(res.get("kind")) == "material" and kac_map:
        price = kac_map.get(_norm_name(res.get("name")))
        if price is not None:
            price = _round(price)
            return PriceTrace(price=price, source="kac", column_10=price, basis="kac")

    action = _missing_price_action(res)
    return PriceTrace(price=None, source=action, basis=action, action=action)


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
        norm = gesn_service.get_norm(code)
        if norm is None:
            return None, []
        from proxy.smeta_core.resource_normalizer import normalize_norm_resources

        return norm, normalize_norm_resources(list(norm.get("resources") or []))

    norm = gesn_service.get_norm(code) if code else None
    work_qty = _f(position.get("qty")) or 1.0
    resources: list[dict[str, Any]] = []
    for res in position.get("resources") or []:
        line = dict(res)
        if line.get("per_unit") in (None, ""):
            line["per_unit"] = _f(line.get("qty")) / work_qty if work_qty else _f(line.get("qty"))
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
    norm, resources = _position_resources(position)
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
    qty_sums = {"labor": 0.0, "machine": 0.0, "machinist": 0.0, "material": 0.0}

    for res in resources:
        kind = str(res.get("kind") or "")
        coeff = _resource_coeff(kind, k_ozp=k_ozp, k_em=k_em)
        per_unit = _f(res.get("per_unit"))
        total_qty = round(per_unit * coeff * work_qty, 6)
        price = _resolve_price_trace(res, pricebook=pricebook, kac_map=kac_lookup)
        cost = 0.0 if price.price is None else round(total_qty * price.price, 2)
        if price.price is None:
            action_label = {
                "needs_kac": "нужен КАЦ",
                "needs_labor_rate": "нужна ставка ОЗП",
                "needs_machinist_rate": "нужна ставка ЗПМ",
                "needs_fgis_price": "нужна цена эксплуатации машины",
            }.get(price.action or price.source, "нужна цена")
            flags.append(f"{action_label}: {res.get('name','?')} ({res.get('code','—')})")
            completeness_reasons.append(f"price_missing:{res.get('code') or res.get('name') or '?'}")
        if kind not in detail_rows:
            flags.append(f"неизвестный вид ресурса: {kind!r}")
            continue
        sums[kind] = round(sums[kind] + cost, 2)
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
                    "price_source_ref": res.get("price_source_ref") or "",
                    "resource_binding": res.get("resource_binding") or {},
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
                "official_name": position.get("official_name") or (norm or {}).get("name") or "",
                "selection_kind": position.get("selection_kind") or "",
                "is_analog": bool(position.get("is_analog")),
                "analog_limitations": list(position.get("analog_limitations") or []),
                "binding_reason": position.get("binding_reason") or "",
            },
        ),
    ]
    if k_ozp != 1.0 or k_em != 1.0:
        rows.append(
            _row(
                "coefficient",
                coefficient_basis or "Повышающие коэффициенты",
                columns={3: coefficient_basis or "Повышающие коэффициенты", 6: 1},
                source="coefficient",
                meta={"k_ozp": k_ozp, "k_em": k_em},
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
            summary["labor_qty"] = round(summary["labor_qty"] + _f(s.get("labor_qty")), 6)
            summary["machinist_qty"] = round(summary["machinist_qty"] + _f(s.get("machinist_qty")), 6)
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


def positions_from_visible_lsr_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind already visible/selected LSR rows to trace positions.

    This function does not search or select norms. It only accepts rows that
    already contain a norm code, converts their quantities to the norm unit and
    returns skipped rows as explicit bindings for the model/user to fix.
    """
    positions: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    for idx, row in enumerate(rows or [], 1):
        code = _code_from_visible_row(row)
        if not code:
            bindings.append({
                "row": idx,
                "status": "norm_selection_required",
                "message": "в строке нет шифра нормы",
                "source_row": row,
            })
            continue
        norm = gesn_service.get_norm(code)
        if norm is None:
            bindings.append({
                "row": idx,
                "code": code,
                "status": "norm_not_found",
                "message": "шифр нормы не найден в нормативной базе",
                "source_row": row,
            })
            continue
        norm_qty, qty_trace = _norm_qty_from_visible_row(row, code, norm)
        if norm_qty is None:
            bindings.append({
                "row": idx,
                "code": code,
                "status": qty_trace.get("status") or "needs_input",
                "quantity_trace": qty_trace,
                "source_row": row,
            })
            continue
        title = str(_first_value(row, "title", "name", "work", "наименование", "работа") or "")
        position = {
            "code": code,
            "qty": norm_qty,
            "section": str(_first_value(row, "section", "раздел") or "").strip() or "Без раздела",
            "source_row": idx,
            "quantity_trace": qty_trace,
        }
        if title:
            position["name"] = title
        if norm and norm.get("unit"):
            position["unit"] = norm.get("unit")
        positions.append(position)
        bindings.append({
            "row": idx,
            "code": code,
            "status": "bound",
            "quantity_trace": qty_trace,
            "position": {k: v for k, v in position.items() if k != "source_row"},
        })
    return {"positions": positions, "row_bindings": bindings}


def build_lsr_trace_from_visible_rows(
    rows: list[dict[str, Any]],
    *,
    pricebook=None,
    kac_map: dict[str, float] | None = None,
    k_ozp: float = 1.0,
    k_em: float = 1.0,
    coefficient_basis: str = "",
    name: str = "",
) -> dict[str, Any]:
    """Visible/BOR/LSR rows with selected norm codes -> priced_partial/final RIM trace."""
    bound = positions_from_visible_lsr_rows(rows)
    lsr = build_lsr_trace(
        bound["positions"],
        pricebook=pricebook,
        kac_map=kac_map,
        k_ozp=k_ozp,
        k_em=k_em,
        coefficient_basis=coefficient_basis,
        name=name,
    )
    binding_flags = [
        f"строка {b.get('row')}: {b.get('message') or b.get('status')}"
        for b in bound["row_bindings"]
        if b.get("status") != "bound"
    ]
    summary = lsr.setdefault("summary", {})
    summary["input_rows"] = len(rows or [])
    summary["bound_rows"] = len(bound["positions"])
    summary["unbound_rows"] = max(0, len(rows or []) - len(bound["positions"]))
    if binding_flags:
        summary["flags"] = list(summary.get("flags") or []) + binding_flags
    if not bound["positions"]:
        summary["result_status"] = "norm_selection_required"
    elif summary.get("flags"):
        summary["result_status"] = "priced_partial"
    else:
        summary["result_status"] = "priced_final"
    lsr["row_bindings"] = bound["row_bindings"]
    return lsr
