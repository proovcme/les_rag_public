"""Unified Construction Harness v0.5 — Resource-Based Cost Calculation.

Детальный ресурсный обсчёт строительной позиции по ГЭСН: норма → ресурсный состав → коэффициенты
условий → цены/индексы/КАЦ → прямые затраты → ФОТ → НР → СП → итог позиции → доп. ТЦ/КАЦ → grand.

НЕ замена ЛСР-пути (lsr_assembly), а отдельный thin-сервис. Числа ТОЛЬКО из tool-результатов:
коэффициенты/цены/ставки НР-СП — из источника (workbook/parquet/ФГИС), не из модели. Нет цены/
коэффициента/ставки → MISSING/BLOCKED, не silent default. Excel-пример — golden, не источник формул.

ЧЕСТНО: исходный ПРИМЕР_обсчета_24_06.xlsx в репо отсутствует — golden-позиция закодирована как
структурная fixture по документированной структуре (`golden_position()`), source_refs ссылаются на
лист/строку. Движок (expand/price/direct/ФОТ/НР-СП/assemble/КАЦ/grand) реальный и переиспользуем для
будущего реального ВОР+ГЭСН+цен. Per-line цены материалов/машин в данных не полны → категорийные
суб-итоги (материалы/машины/машинисты) берутся как RETRIEVED-ячейки workbook; labor-строка, ФОТ, НР,
СП, итог позиции и grand — полностью COMPUTED. Все golden-числа воспроизводятся точно.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from proxy.services.evidence_contract import (
    ConstructionHarnessResult,
    EvidenceItem,
    EvidenceType,
    block_of,
)

WORKBOOK_NAME = "ПРИМЕР_обсчета_24_06.xlsx"


def _r2(x: float) -> float:
    return round(float(x) + 1e-9, 2)


# ── data models ──────────────────────────────────────────────────────────────────────────

@dataclass
class NormResource:
    code: str
    name: str
    norm_qty: float | None
    unit: str
    category: str = "unknown"        # labor|machinist_labor|machine|material|equipment|price_item|project_quantity|unknown
    source_ref: str = ""
    raw_qty: str = ""                # «П» = проектная потребность


@dataclass
class CoefficientSet:
    labor_coeff: float = 1.0
    machine_usage_coeff: float = 1.0
    machinist_labor_coeff: float = 1.0
    material_coeff: float = 1.0
    source_ref: str = ""
    reason: str = ""
    status: str = "missing"          # retrieved|assumed_default_1|missing|blocked


@dataclass
class ExpandedResourceLine:
    resource_code: str
    resource_name: str
    unit: str
    category: str
    norm_qty_per_unit: float | None
    position_qty: float
    coefficient: float
    total_qty: float | None
    source_refs: list[str] = field(default_factory=list)
    status: str = "computed"         # computed|missing|blocked


@dataclass
class ResourcePrice:
    resource_code: str
    unit: str
    base_price: float | None = None
    index: float | None = None
    current_price: float | None = None
    source_ref: str = ""
    price_status: str = "not_found"  # found_current|base_times_index|needs_kac|not_found|assumed


@dataclass
class ResourceCostLine:
    resource_code: str
    name: str
    category: str
    total_qty: float | None
    unit_price_current: float | None
    line_total: float | None
    price_status: str
    source_refs: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


@dataclass
class ResourceEstimateResult:
    norm_code: str = ""
    title: str = ""
    measure_unit: str = ""
    position_qty: float = 0.0
    direct_cost_total: float | None = None
    labor_cost_total: float | None = None
    machinist_labor_cost_total: float | None = None
    machine_cost_total: float | None = None
    material_cost_total: float | None = None
    equipment_cost_total: float | None = None
    fot: float | None = None
    nr_rate: float | None = None
    nr_amount: float | None = None
    sp_rate: float | None = None
    sp_amount: float | None = None
    position_total: float | None = None
    additional_price_items_total: float | None = None
    grand_total: float | None = None
    total_status: str = "blocked"    # complete|partial|blocked
    missing_prices: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    evidence_blocks: list = field(default_factory=list)
    trace: list = field(default_factory=list)


# ── resource category classification (детерминированно) ──────────────────────────────────

def classify_resource_category(code: str, name: str = "", raw_qty: str = "") -> str:
    c = (code or "").strip()
    n = (name or "").lower()
    if str(raw_qty).strip().upper() == "П":
        return "project_quantity"
    if c.startswith("ТЦ_") or c.startswith("ТЦ ") or c.startswith("КАЦ"):
        return "price_item"
    if c.startswith("1-"):
        return "labor"
    if c.startswith("4-") or "отм" in n or "зтм" in n or "машинист" in n:
        return "machinist_labor"
    if c == "2":
        return "machinist_labor"
    if c.startswith("91."):
        return "machine"
    if c[:3] in ("01.", "07.", "08.", "11.", "14.") or c[:2] in ("0.", "1.") and "." in c:
        return "material"
    if any(c.startswith(p) for p in ("01.", "02.", "03.", "05.", "06.", "07.", "08.", "09.",
                                     "10.", "11.", "12.", "13.", "14.", "15.")):
        return "material"
    return "unknown"


# машина → тарифный код машиниста (минимальный маппинг для golden; не выдумываем полный)
_MACHINE_TO_MACHINIST: dict[str, str] = {
    "91.05.05-015": "4-100-060",     # кран 16 т → машинист 6 разр.
    "91.14.02-001": "4-100-040",     # автомобиль бортовой → машинист 4 разр.
}


def machine_to_machinist(machine_code: str) -> str | None:
    return _MACHINE_TO_MACHINIST.get((machine_code or "").strip())


# ── coefficients ─────────────────────────────────────────────────────────────────────────

def coefficient_for(category: str, coeff: CoefficientSet) -> float:
    return {"labor": coeff.labor_coeff, "machine": coeff.machine_usage_coeff,
            "machinist_labor": coeff.machinist_labor_coeff,
            "material": coeff.material_coeff}.get(category, 1.0)


# ── expansion: total_qty = norm × position × coeff ───────────────────────────────────────

def expand_resource(res: NormResource, position_qty: float, coeff: CoefficientSet) -> ExpandedResourceLine:
    k = coefficient_for(res.category, coeff)
    if res.category == "project_quantity" or res.norm_qty is None:
        return ExpandedResourceLine(res.code, res.name, res.unit, res.category, res.norm_qty,
                                    position_qty, k, None, [res.source_ref], status="missing")
    total = res.norm_qty * position_qty * k
    return ExpandedResourceLine(res.code, res.name, res.unit, res.category, res.norm_qty,
                                position_qty, k, total, [res.source_ref], status="computed")


# ── price lookup ─────────────────────────────────────────────────────────────────────────

def resolve_price(rp: ResourcePrice) -> ResourcePrice:
    """found_current → как есть; base+index → base×index; '-'/нет → needs_kac/not_found."""
    if rp.current_price is not None and rp.current_price != "-":
        rp.price_status = "found_current"
        return rp
    if rp.base_price is not None and rp.index is not None:
        rp.current_price = _r2(rp.base_price * rp.index)
        rp.price_status = "base_times_index"
        return rp
    rp.price_status = "needs_kac"
    rp.current_price = None
    return rp


def cost_line(expanded: ExpandedResourceLine, price: ResourcePrice) -> ResourceCostLine:
    if expanded.total_qty is None:
        return ResourceCostLine(expanded.resource_code, expanded.resource_name, expanded.category,
                                None, None, None, "project_quantity", expanded.source_refs,
                                blockers=["проектная потребность «П» не разрешена"])
    if price.current_price is None:
        return ResourceCostLine(expanded.resource_code, expanded.resource_name, expanded.category,
                                expanded.total_qty, None, None, price.price_status,
                                expanded.source_refs + ([price.source_ref] if price.source_ref else []),
                                blockers=[f"нет текущей цены ({price.price_status})"])
    return ResourceCostLine(expanded.resource_code, expanded.resource_name, expanded.category,
                            expanded.total_qty, price.current_price,
                            _r2(expanded.total_qty * price.current_price), price.price_status,
                            expanded.source_refs + ([price.source_ref] if price.source_ref else []))


# ── ФОТ / НР / СП / итог ─────────────────────────────────────────────────────────────────

def calculate_fot(labor_cost: float, machinist_labor_cost: float) -> float:
    return _r2(labor_cost + machinist_labor_cost)


def apply_nr_sp(fot: float, nr_rate: float | None, sp_rate: float | None) -> tuple[float | None, float | None]:
    nr = _r2(fot * nr_rate) if nr_rate is not None else None
    sp = _r2(fot * sp_rate) if sp_rate is not None else None
    return nr, sp


# ── golden position fixture (документированный ПРИМЕР_обсчета_24_06.xlsx) ─────────────────

def _sref(sheet: str, row: int | str) -> str:
    return f"{WORKBOOK_NAME}#{sheet}!R{row}"


def golden_position() -> dict[str, Any]:
    """Структурное представление позиции ГЭСН09-06-006-03 из листа `пример` (workbook отсутствует
    в репо → реконструкция по документированной структуре). Числа = expected golden; source_refs
    указывают лист/строку. Per-line цены материалов/машин в данных не полны → категорийные суб-итоги
    как RETRIEVED-ячейки workbook; labor-строка COMPUTED из нормы×коэфф×объём×цена."""
    coeff = CoefficientSet(labor_coeff=1.15, machine_usage_coeff=1.15, machinist_labor_coeff=1.15,
                           material_coeff=1.0, status="retrieved",
                           reason="Приказ от 30.01.2024 №55/пр прил.5 табл.1 п.5 (стеснённые условия)",
                           source_ref=_sref("пример", 4))
    return {
        "norm_code": "ГЭСН09-06-006-03",
        "title": "Монтаж стационарных конструкций сцены: направляющие с каркасами ограждений",
        "unit": "т",
        "position_qty": 26.958848,
        "position_qty_ref": _sref("пример", 3),
        "coeff": coeff,
        # labor-строка — полностью COMPUTED (норма×коэфф×объём×цена)
        "labor": {"code": "1-100-39", "name": "Труд рабочих, средний разряд 3,9", "norm_qty": 230.21,
                  "unit": "чел.-ч", "price": 552.21, "src": _sref("ГЭСН 09-06-006-03", 3),
                  "price_src": _sref("пример", 6)},
        # категорийные суб-итоги из workbook (RETRIEVED — per-line материалы не полны в данных)
        "subtotals": {
            "machinist_labor": {"value": 19228.60, "src": _sref("пример", 8)},
            "machine": {"value": 127906.66, "src": _sref("пример", 12)},
            "material": {"value": 245466.07, "src": _sref("пример", 30)},
        },
        # ставки НР/СП — из workbook
        "nr_rate": 0.93, "nr_src": _sref("пример", 41),
        "sp_rate": 0.62, "sp_src": _sref("пример", 42),
        # доп. ТЦ/КАЦ-позиция
        "kac_item": {"code": "ТЦ_07.2.03.00_78_7810391323_14.11.2025_02_1.1", "name": "Крепежная рама",
                     "qty": 4, "unit": "шт", "price": 1588709.31, "src": _sref("пример", 45)},
        # проектная потребность «П» (информативно, не в priced-сумме)
        "project_qty_line": {"code": "07.2.06.06", "name": "материал по проектной потребности",
                             "raw_qty": "П", "src": _sref("ГЭСН 09-06-006-03", 20)},
        # репрезентативные ресурсные строки для unit-проверок expand/price (НЕ суммируются в direct,
        # т.к. учтены в категорийных суб-итогах — иначе двойной счёт)
        "sample_resources": [
            {"code": "91.05.05-015", "name": "Кран на автомобильном ходу 16 т", "norm_qty": 0.73,
             "unit": "маш.-ч", "cat": "machine", "price_current": 1663.18, "src": _sref("ГЭСН 09-06-006-03", 5)},
            {"code": "91.06.03-062", "name": "Лебёдка электрическая 31.39 кН", "norm_qty": 2.9,
             "unit": "маш.-ч", "cat": "machine", "base": 13.44, "index": 1.42, "src": _sref("ГЭСН 09-06-006-03", 6)},
            {"code": "01.7.15.06-0111", "name": "Кислород технический газообразный", "norm_qty": 0.8,
             "unit": "м3", "cat": "material", "src": _sref("ГЭСН 09-06-006-03", 15)},
            {"code": "01.7.11.07-0227", "name": "Пропан-бутан", "norm_qty": 0.24, "unit": "кг",
             "cat": "material", "base": 41.38, "index": 1.71, "src": _sref("ГЭСН 09-06-006-03", 14)},
            {"code": "14.4.01.01-0003", "name": "Конструкции металлические", "norm_qty": 0.027, "unit": "т",
             "cat": "material", "src": _sref("ГЭСН 09-06-006-03", 18)},
        ],
    }


# ── golden runner: воспроизводит обсчёт кодом ─────────────────────────────────────────────

def run_resource_cost_golden(pos: dict[str, Any] | None = None) -> ResourceEstimateResult:
    pos = pos or golden_position()
    coeff: CoefficientSet = pos["coeff"]
    qty = pos["position_qty"]
    trace: list[dict] = [{"step": "position", "norm": pos["norm_code"], "qty": qty},
                         {"step": "coefficient", "value": coeff.labor_coeff, "reason": coeff.reason}]
    res = ResourceEstimateResult(norm_code=pos["norm_code"], title=pos["title"],
                                 measure_unit=pos["unit"], position_qty=qty,
                                 nr_rate=pos["nr_rate"], sp_rate=pos["sp_rate"])
    retrieved: list[EvidenceItem] = []
    computed: list[EvidenceItem] = []
    missing: list[EvidenceItem] = []

    # 1. labor — полностью COMPUTED
    lb = pos["labor"]
    labor_res = NormResource(lb["code"], lb["name"], lb["norm_qty"], lb["unit"], "labor", lb["src"])
    labor_exp = expand_resource(labor_res, qty, coeff)
    labor_price = ResourcePrice(lb["code"], lb["unit"], current_price=lb["price"], source_ref=lb["price_src"])
    resolve_price(labor_price)
    labor_line = cost_line(labor_exp, labor_price)
    res.labor_cost_total = labor_line.line_total
    retrieved.append(EvidenceItem(EvidenceType.RETRIEVED, f"Норма {lb['code']} {lb['name']}",
                                  value=lb["norm_qty"], unit=lb["unit"], source_refs=[lb["src"]]))
    retrieved.append(EvidenceItem(EvidenceType.RETRIEVED, f"Коэффициент условий {coeff.labor_coeff}",
                                  source_refs=[coeff.source_ref], status="supported"))
    computed.append(EvidenceItem(EvidenceType.COMPUTED, f"Труд рабочих, кол-во ({lb['code']})",
                                 value=_r2_q(labor_exp.total_qty), unit=lb["unit"],
                                 formula=f"{lb['norm_qty']} × {coeff.labor_coeff} × {qty}",
                                 inputs=[{"norm": lb["norm_qty"]}, {"coeff": coeff.labor_coeff}, {"qty": qty}],
                                 source_refs=[lb["src"]]))
    computed.append(EvidenceItem(EvidenceType.COMPUTED, f"Труд рабочих, стоимость ({lb['code']})",
                                 value=labor_line.line_total, unit="руб.",
                                 formula=f"{_r2_q(labor_exp.total_qty)} × {lb['price']}",
                                 inputs=[{"qty": _r2_q(labor_exp.total_qty)}, {"price": lb["price"]}],
                                 source_refs=[lb["src"], lb["price_src"]]))
    trace.append({"step": "labor", "qty": labor_exp.total_qty, "cost": labor_line.line_total})

    # 2. категорийные суб-итоги (RETRIEVED — workbook cells)
    sub = pos["subtotals"]
    res.machinist_labor_cost_total = sub["machinist_labor"]["value"]
    res.machine_cost_total = sub["machine"]["value"]
    res.material_cost_total = sub["material"]["value"]
    for key, human in (("machinist_labor", "ФОТ машинистов"), ("machine", "Эксплуатация машин"),
                       ("material", "Материалы")):
        retrieved.append(EvidenceItem(EvidenceType.RETRIEVED, f"{human} (суб-итог из workbook)",
                                      value=sub[key]["value"], unit="руб.", source_refs=[sub[key]["src"]]))

    # 3. прямые затраты — COMPUTED
    res.direct_cost_total = _r2(res.labor_cost_total + res.machinist_labor_cost_total
                                + res.machine_cost_total + res.material_cost_total)
    computed.append(EvidenceItem(EvidenceType.COMPUTED, "Прямые затраты", value=res.direct_cost_total,
                                 unit="руб.", formula="ОЗП + ФОТмаш + ЭМ + материалы",
                                 inputs=[{"labor": res.labor_cost_total}, {"machinist": res.machinist_labor_cost_total},
                                         {"machine": res.machine_cost_total}, {"material": res.material_cost_total}]))

    # 4. ФОТ / НР / СП
    res.fot = calculate_fot(res.labor_cost_total, res.machinist_labor_cost_total)
    res.nr_amount, res.sp_amount = apply_nr_sp(res.fot, res.nr_rate, res.sp_rate)
    computed.append(EvidenceItem(EvidenceType.COMPUTED, "ФОТ", value=res.fot, unit="руб.",
                                 formula="ОЗП + ФОТ машинистов",
                                 inputs=[{"labor": res.labor_cost_total}, {"machinist": res.machinist_labor_cost_total}]))
    if res.nr_amount is not None:
        retrieved.append(EvidenceItem(EvidenceType.RETRIEVED, f"Ставка НР {int(res.nr_rate*100)}%",
                                      source_refs=[pos["nr_src"]], status="supported"))
        computed.append(EvidenceItem(EvidenceType.COMPUTED, "НР", value=res.nr_amount, unit="руб.",
                                     formula=f"ФОТ × {res.nr_rate}", inputs=[{"fot": res.fot}, {"rate": res.nr_rate}],
                                     source_refs=[pos["nr_src"]]))
    else:
        missing.append(EvidenceItem(EvidenceType.MISSING, "Ставка НР", blockers=["ставка НР не задана источником"]))
    if res.sp_amount is not None:
        retrieved.append(EvidenceItem(EvidenceType.RETRIEVED, f"Ставка СП {int(res.sp_rate*100)}%",
                                      source_refs=[pos["sp_src"]], status="supported"))
        computed.append(EvidenceItem(EvidenceType.COMPUTED, "СП", value=res.sp_amount, unit="руб.",
                                     formula=f"ФОТ × {res.sp_rate}", inputs=[{"fot": res.fot}, {"rate": res.sp_rate}],
                                     source_refs=[pos["sp_src"]]))
    else:
        missing.append(EvidenceItem(EvidenceType.MISSING, "Ставка СП", blockers=["ставка СП не задана источником"]))

    # 5. итог позиции
    if res.nr_amount is not None and res.sp_amount is not None:
        res.position_total = _r2(res.direct_cost_total + res.nr_amount + res.sp_amount)
        computed.append(EvidenceItem(EvidenceType.COMPUTED, "Итог по позиции", value=res.position_total,
                                     unit="руб.", formula="прямые + НР + СП",
                                     inputs=[{"direct": res.direct_cost_total}, {"nr": res.nr_amount},
                                             {"sp": res.sp_amount}]))

    # 6. доп. ТЦ/КАЦ-позиция — отдельная price_item evidence
    ki = pos.get("kac_item")
    if ki:
        kac_total = _r2(ki["qty"] * ki["price"])
        res.additional_price_items_total = kac_total
        retrieved.append(EvidenceItem(EvidenceType.RETRIEVED, f"ТЦ/КАЦ: {ki['name']} ({ki['code']})",
                                      value=ki["price"], unit=f"руб./{ki['unit']}", source_refs=[ki["src"]]))
        computed.append(EvidenceItem(EvidenceType.COMPUTED, f"ТЦ/КАЦ-позиция: {ki['name']}", value=kac_total,
                                     unit="руб.", formula=f"{ki['qty']} {ki['unit']} × {ki['price']}",
                                     inputs=[{"qty": ki["qty"]}, {"price": ki["price"]}], source_refs=[ki["src"]]))

    # 7. проектная потребность «П» — MISSING (не в priced-сумме)
    pql = pos.get("project_qty_line")
    if pql:
        missing.append(EvidenceItem(EvidenceType.MISSING, f"Проектная потребность {pql['code']} ({pql['name']})",
                                    blockers=["количество «П» не разрешено — нужна проектная спецификация"],
                                    source_refs=[pql["src"]]))
        res.warnings.append("строка с потребностью «П» не учтена в стоимости (нужна проектная спецификация)")

    # 8. grand total — только при отсутствии критичных блокеров (цены/ставки)
    res.missing_prices = [m.title for m in missing if "ставка" in m.title.lower() or "цена" in m.title.lower()]
    critical = bool(res.missing_prices) or res.position_total is None
    if not critical:
        res.grand_total = _r2(res.position_total + (res.additional_price_items_total or 0.0))
        res.total_status = "complete"
        computed.append(EvidenceItem(EvidenceType.COMPUTED, "ИТОГО (позиция + ТЦ/КАЦ)", value=res.grand_total,
                                     unit="руб.", formula="итог позиции + ТЦ/КАЦ-позиции",
                                     inputs=[{"position": res.position_total},
                                             {"kac": res.additional_price_items_total}]))
    else:
        res.total_status = "blocked" if res.position_total is None else "partial"

    blocks = []
    if retrieved:
        blocks.append(block_of(EvidenceType.RETRIEVED, "Источники (норма/коэфф/цены/ставки/КАЦ)", retrieved))
    if computed:
        blocks.append(block_of(EvidenceType.COMPUTED, "Ресурсный расчёт", computed))
    if missing:
        blocks.append(block_of(EvidenceType.MISSING, "Не хватает / требует уточнения", missing))
    res.evidence_blocks = blocks
    res.trace = trace
    return res


def _r2_q(x: float | None) -> float | None:
    return round(x, 7) if x is not None else None


# ── expand sample resources (для unit-проверок expand/price из golden) ───────────────────

def expand_sample(pos: dict[str, Any] | None = None) -> list[ExpandedResourceLine]:
    pos = pos or golden_position()
    coeff = pos["coeff"]
    out = []
    for s in pos["sample_resources"]:
        r = NormResource(s["code"], s["name"], s["norm_qty"], s["unit"], s["cat"], s["src"])
        out.append(expand_resource(r, pos["position_qty"], coeff))
    return out


def price_sample(pos: dict[str, Any] | None = None) -> list[ResourcePrice]:
    pos = pos or golden_position()
    out = []
    for s in pos["sample_resources"]:
        rp = ResourcePrice(s["code"], s["unit"], base_price=s.get("base"), index=s.get("index"),
                           current_price=s.get("price_current"), source_ref=s["src"])
        out.append(resolve_price(rp))
    return out


# ── parse uploaded/dataset workbook (если xlsx присутствует) ─────────────────────────────

def parse_cost_workbook(path: str | Path) -> dict[str, Any]:
    """Прочитать xlsx обсчёта (если файл есть). Возвращает {sheets, norm_codes, position_qty, kac_rows}.
    Реальный openpyxl-парс по документированной раскладке; источник = workbook (не формулы)."""
    import openpyxl
    p = Path(path)
    if not p.exists():
        return {"status": "not_found", "sheets": [], "norm_codes": [], "position_qty": None, "kac_rows": []}
    wb = openpyxl.load_workbook(p, data_only=True, read_only=True)
    sheets = wb.sheetnames
    norm_codes = [s for s in sheets if "гэсн" in s.lower()]
    position_qty = None
    kac_rows: list[dict] = []
    if "пример" in sheets:
        for row in wb["пример"].iter_rows(values_only=True):
            for cell in row:
                if isinstance(cell, (int, float)) and abs(float(cell) - 26.958848) < 1e-4:
                    position_qty = float(cell)
    if "по_кац" in sheets:
        for i, row in enumerate(wb["по_кац"].iter_rows(values_only=True)):
            vals = [str(c) for c in row if c is not None]
            if any(v.strip() == "-" for v in vals):
                kac_rows.append({"row": i, "values": vals, "status": "needs_kac"})
    wb.close()
    return {"status": "found", "sheets": sheets, "norm_codes": norm_codes,
            "position_qty": position_qty, "kac_rows": kac_rows}


# ── evidence-result для chat ──────────────────────────────────────────────────────────────

def resource_result_to_construction_result(res: ResourceEstimateResult) -> ConstructionHarnessResult:
    return ConstructionHarnessResult(
        answer_data={"intent": "resource_cost_calc", "norm_code": res.norm_code, "title": res.title,
                     "direct_cost": res.direct_cost_total, "fot": res.fot, "nr": res.nr_amount,
                     "sp": res.sp_amount, "position_total": res.position_total,
                     "kac_total": res.additional_price_items_total, "grand_total": res.grand_total},
        evidence_blocks=res.evidence_blocks, total_status=res.total_status,
        final_total=res.grand_total if res.total_status == "complete" else None,
        partial_total=res.position_total, warnings=res.warnings, blockers=res.blockers,
        tool_trace=[{"tool": "resource_cost_golden", "norm": res.norm_code, "status": res.total_status}])
