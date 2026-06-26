"""РИМ-трасса ЛСР по Приложению 4 к Методике 421/пр (форма локального сметного расчёта).

Сервис строит объяснимые строки ЛСР: работа -> ресурсы -> цены -> ОЗП/ЭМ/М ->
ФОТ -> НР/СП -> всего. Это не рендер XLSX и не новый калькулятор вместо
``lsr_assembly_service``; это методический слой evidence для проверки граф 2-12.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

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


@dataclass(frozen=True)
class PriceTrace:
    price: Optional[float]
    source: str
    column_8: Optional[float] = None
    column_9: Optional[float] = None
    column_10: Optional[float] = None
    basis: str = ""


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

    return PriceTrace(price=None, source="missing")


def _position_resources(position: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Вернуть норму и ресурсы с ``per_unit``; explicit resources поддержаны для тестов/ручного ввода."""
    code = str(position.get("code") or "").strip()
    if code and not position.get("resources"):
        norm = gesn_service.get_norm(code)
        if norm is None:
            return None, []
        return norm, list(norm.get("resources") or [])

    work_qty = _f(position.get("qty")) or 1.0
    resources: list[dict[str, Any]] = []
    for res in position.get("resources") or []:
        line = dict(res)
        if line.get("per_unit") in (None, ""):
            line["per_unit"] = _f(line.get("qty")) / work_qty if work_qty else _f(line.get("qty"))
        resources.append(line)
    return None, resources


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
    flags: list[str] = []
    if position.get("code") and norm is None and not position.get("resources"):
        flags.append(f"норма ГЭСН не найдена: {position.get('code')}")

    work_code = position.get("code") or (norm or {}).get("code") or ""
    work_name = position.get("name") or (norm or {}).get("name") or ""
    work_unit = position.get("unit") or (norm or {}).get("unit") or ""
    nr_sp = nr_sp_service.resolve(work_name)
    nr_pct = _f(position.get("nr_pct") if position.get("nr_pct") not in (None, "") else (norm or {}).get("nr_pct", nr_sp["nr_pct"]))
    sp_pct = _f(position.get("sp_pct") if position.get("sp_pct") not in (None, "") else (norm or {}).get("sp_pct", nr_sp["sp_pct"]))

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
            flags.append(f"нет цены: {res.get('name','?')} ({res.get('code','—')})")
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
                meta={"basis": price.basis, "kind": kind},
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

    rows: list[dict[str, Any]] = [
        _row("work", work_name, columns={2: work_code, 3: work_name, 4: work_unit, 5: work_qty, 6: 1, 7: work_qty}, source="gesn"),
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
            _row("position_total", "Итого по позиции", columns={3: "Итого по позиции", 12: total}),
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
            "flags": flags,
        },
    }
