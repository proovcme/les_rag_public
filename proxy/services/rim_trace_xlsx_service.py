"""Рендерер РИМ-трассы ЛСР в XLSX по форме **Приложения № 3** к Методике 421/пр.

НЕ калькулятор: берёт ГОТОВУЮ трассу и раскладывает её строки по графам формы ЛСР. Два входа:

* :func:`render_trace_xlsx` — ОДНА позиция (``rim_lsr_trace_service.build_position_trace``);
* :func:`render_lsr_xlsx` — МНОГОПОЗИЦИОННАЯ ЛСР (``rim_lsr_trace_service.build_lsr_trace``):
  шапка с общим итогом + разделы (заголовок раздела → позиции с непрерывной нумерацией → «Итого по
  разделу N») + общий свод «ВСЕГО по смете».

Оба рендера делят шапку/графы/строки позиции/финализацию — числа НЕ пересчитываются (Σ уже сделана в
трассе). 0 LLM. Графы формы РИМ: № п/п · Обоснование · Наименование · Ед. изм. · Количество
(на ед./коэф./всего) · Сметная стоимость (базис/индекс/текущий уровень/коэф./всего).
Колонки trace.columns 2-12 ложатся на графы формы напрямую.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path
import tempfile
from typing import Any, Optional
from xml.etree import ElementTree
from zipfile import ZipFile

# trace.columns (str) → колонка openpyxl (1-индекс) по форме Приложения 3.
# Графа № п/п → A (col 1, только строки-работы), графы 2-12 ложатся напрямую.
_COL: dict[str, int] = {str(i): i for i in range(2, 13)}
_NUM_COLS = {5, 6, 7, 8, 9, 10, 11, 12}

_GROUP_TYPES = {"group_labor", "group_machine", "group_machinist", "group_material",
                "direct_total", "fot", "nr", "sp", "position_total"}
_TOTAL_TYPES = {"direct_total", "fot", "nr", "sp", "position_total"}
_LABEL_FIX = {"Итого по позиции": "Всего по позиции"}

_TABLE_HEADERS = {
    1: "№ п/п",
    2: "Обоснование",
    3: "Наименование работ и затрат",
    4: "Ед. изм.",
    5: "Кол-во на ед.",
    6: "коэф.",
    7: "Кол-во всего",
    8: "Сметная стоимость в базисном уровне цен на ед., руб.",
    9: "Индекс",
    10: "Сметная стоимость в текущем уровне цен на ед., руб.",
    11: "коэф.",
    12: "Сметная стоимость в текущем уровне цен всего, руб.",
}
_WIDTHS = {1: 6, 2: 18, 3: 44, 4: 9, 5: 11, 6: 7, 7: 12, 8: 16, 9: 9, 10: 16, 11: 7, 12: 18}


def _f(value: Any) -> float:
    try:
        return float(str(value).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _styles() -> dict[str, Any]:
    """Стили формы (шрифты/границы/заливки), собираются один раз на лист."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color="B0B8C0")
    return {
        "Alignment": Alignment,
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
        "bold": Font(bold=True, size=9),
        "small": Font(size=9),
        "dim": Font(size=8, color="606060"),
        "fill_head": PatternFill("solid", fgColor="D9EAF7"),    # шапка таблицы
        "fill_total": PatternFill("solid", fgColor="F2F6FA"),   # итоговые строки (позиция/раздел)
        "fill_section": PatternFill("solid", fgColor="EAF1F8"),  # заголовок раздела
        "fill_grand": PatternFill("solid", fgColor="CFE2F3"),   # «ВСЕГО по смете»
        "fill_warning": PatternFill("solid", fgColor="FCE8E6"),
        "warning": Font(bold=True, size=10, color="9C0006"),
        "formula_values": {},
    }


def _make_put(ws, S: dict[str, Any]):
    """Фабрика ячеечного `put`, замкнутого на лист + стили."""
    Alignment = S["Alignment"]

    def _put(r: int, c: int, v: Any, *, font=None, num: bool = False, align: str = "left"):
        cell = ws.cell(row=r, column=c, value=v)
        cell.font = font or S["small"]
        if num and isinstance(v, (int, float)):
            cell.number_format = "#,##0.00"
            cell.alignment = Alignment(horizontal="right")
        else:
            cell.alignment = Alignment(horizontal=align, vertical="top", wrap_text=(c == 3))
        return cell

    return _put


def _border_row(ws, S: dict[str, Any], r: int, *, fill=None) -> None:
    """Границы по графам 1-12 строки + опц. заливка (итоги/разделы)."""
    for c in range(1, 13):
        cc = ws.cell(row=r, column=c)
        cc.border = S["border"]
        if fill is not None:
            cc.fill = fill


def _header_block(ws, put, S: dict[str, Any], *, name: str, summary: dict[str, Any],
                  meta: dict[str, Any]) -> int:
    """Шапка формы (стройка/объект/ЛСР №/наименование/метод/уровень цен/субъект + сметная стоимость
    и её разбивка). Возвращает номер строки шапки таблицы (графы)."""
    r = 1
    put(r, 10, "Приложение № 3", font=S["dim"], align="right"); r += 1
    put(r, 10, "к Методике (приказ Минстроя России от 04.08.2020 № 421/пр)", font=S["dim"], align="right"); r += 2
    put(r, 1, meta.get("stroika", "(наименование стройки)"), font=S["dim"]); r += 1
    put(r, 1, meta.get("object", "(наименование объекта капитального строительства)"), font=S["dim"]); r += 2
    put(r, 1, "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ (СМЕТА) № " + str(meta.get("lsr_no", "____")), font=S["bold"]); r += 1
    put(r, 1, name or "(наименование работ и затрат)", font=S["small"]); r += 1
    put(
        r,
        1,
        str(meta.get("calculation_method") or "Составлен ресурсно-индексным методом (РИМ)"),
        font=S["dim"],
    ); r += 1
    basis = str(meta.get("osnovanie", "—"))
    if basis.startswith(("/", "file://")) or ":\\" in basis:
        basis = Path(basis.replace("file://", "")).name
    put(r, 1, "Основание: " + basis, font=S["dim"]); r += 1
    put(r, 1, "Составлен(а) в текущем уровне цен: " + str(meta.get("price_level", "—")), font=S["dim"]); r += 1
    put(r, 1, "Наименование субъекта РФ: " + str(meta.get("subject", "—")), font=S["dim"]); r += 1
    basis_note = str(meta.get("price_basis_note") or "")
    if basis_note:
        if str(meta.get("price_basis_match") or "") == "mismatch":
            put(r, 1, basis_note, font=S["warning"])
            for c in range(1, 13):
                ws.cell(row=r, column=c).fill = S["fill_warning"]
        else:
            put(r, 1, basis_note, font=S["dim"])
        r += 1
    r += 1
    result_status = str(summary.get("result_status") or "").strip()
    if result_status and result_status != "priced_final":
        put(
            r,
            1,
            f"РАСЧЁТ НЕ ЗАВЕРШЁН ({result_status.upper()}) — НЕ ДЛЯ СОГЛАСОВАНИЯ",
            font=S["warning"],
        )
        for c in range(1, 13):
            ws.cell(row=r, column=c).fill = S["fill_warning"]
        r += 1
    input_rows = int(summary.get("input_rows") or 0)
    bound_rows = int(summary.get("bound_rows") or 0)
    open_rows = int(summary.get("open_rows", summary.get("unbound_rows")) or 0)
    covered_rows = int(summary.get("covered_rows") or 0)
    closed_rows = bound_rows + covered_rows
    low_coverage = (
        input_rows > 0
        and open_rows > 0
        and (open_rows / input_rows >= 0.30 or closed_rows / input_rows < 0.70)
    )
    if low_coverage:
        put(
            r,
            1,
            (
                f"ПОКРЫТИЕ НИЗКОЕ: привязано {bound_rows} из {input_rows} строк"
                f"{', ещё ' + str(covered_rows) + ' покрыто соседними' if covered_rows else ''}. "
                "Сумма в шапке — только по привязанным, не итог ведомости."
            ),
            font=S["warning"],
        )
        for c in range(1, 13):
            ws.cell(row=r, column=c).fill = S["fill_warning"]
        r += 2
    elif result_status and result_status != "priced_final":
        r += 1
    amount_complete = summary.get("full_amount") is not None
    cost_label = (
        f"Стоимость только привязанной части ({bound_rows}/{input_rows})"
        if low_coverage
        else ("Сметная стоимость" if amount_complete else "Стоимость рассчитанной части")
    )
    put(r, 1, cost_label, font=S["bold"])
    put(r, 4, _f(summary.get("total_with_vat", summary.get("total", 0))), font=S["bold"], num=True)
    put(r, 6, "руб.", font=S["dim"]); r += 1
    put(r, 1, "  средства на оплату труда рабочих", font=S["dim"]); put(r, 4, _f(summary.get("ozp", 0)), font=S["dim"], num=True); r += 1
    put(r, 1, "  средства на оплату труда машинистов", font=S["dim"]); put(r, 4, _f(summary.get("zpm", 0)), font=S["dim"], num=True); r += 1
    put(r, 1, "  нормативные затраты труда рабочих, чел.-ч", font=S["dim"]); put(r, 4, summary.get("labor_qty", 0), font=S["dim"], num=True); r += 1
    put(r, 1, "  нормативные затраты труда машинистов, чел.-ч", font=S["dim"]); put(r, 4, summary.get("machinist_qty", 0), font=S["dim"], num=True); r += 2
    return r


def _table_header(ws, put, S: dict[str, Any], head_r: int) -> int:
    """Шапка таблицы (графы № п/п…Стоимость всего)."""
    for c, t in _TABLE_HEADERS.items():
        cell = put(head_r, c, t, font=S["bold"], align="center")
        cell.fill = S["fill_head"]
        cell.border = S["border"]
        cell.alignment = S["Alignment"](horizontal="center", vertical="center", wrap_text=True)
    return head_r


def _sum_formula(rows: list[int], column: str = "L") -> str:
    return "=SUM(" + ",".join(f"{column}{row}" for row in rows) + ")" if rows else "=0"


def _set_formula(ws, row: int, column: int, formula: str, values: dict) -> None:
    """Keep the calculator's numeric value while making the cell editable."""
    cell = ws.cell(row=row, column=column)
    value = cell.value
    if type(value) in (int, float) and math.isfinite(value):
        values[cell.coordinate] = value
    else:
        values.pop(cell.coordinate, None)
    cell.value = formula


_DOCUMENT_EPOCH_ISO = "2000-01-01T00:00:00Z"


def _save_calculated_workbook(wb, path: Path, values: dict) -> None:
    """Store trace values as OOXML formula caches; never evaluate workbook code.

    openpyxl emits empty <v> nodes for formulas. Preserve its formula and all
    other parts, injecting only numeric values already supplied by the trace.
    Unknown prices stay blank. Excel still recalculates after an engineer edits.
    """
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"
    import re  # локально: нужен только нормализующий замену метаданных путь
    wb.save(path)
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".xlsx", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with ZipFile(path) as source, ZipFile(temporary, "w") as target:
            for info in source.infolist():
                content = source.read(info)
                if info.filename == "docProps/core.xml":
                    # openpyxl при сохранении перезаписывает `dcterms:modified` текущим временем
                    # (openpyxl/writer/excel.py:292), поэтому свойства документа фиксируются здесь.
                    # Пересборка тех же сохранённых решений обязана давать то же содержимое файла:
                    # иначе «тот же документ» нельзя сверить по хешу после повторной доставки
                    # (§ 7 «пересчёт скачанных байтов», § 1 «скачать актуальную ревизию»).
                    # Числа, строки и формулы этим не затрагиваются — правка только про метаданные.
                    text = content.decode("utf-8")
                    for tag in ("created", "modified"):
                        text = re.sub(rf"(<dcterms:{tag}[^>]*>)[^<]*(</dcterms:{tag}>)",
                                      rf"\g<1>{_DOCUMENT_EPOCH_ISO}\g<2>", text)
                    content = text.encode("utf-8")
                if info.filename == "xl/worksheets/sheet1.xml":
                    sheet = ElementTree.fromstring(content)
                    for cell in sheet.iter(ns + "c"):
                        address = cell.get("r")
                        if address not in values or cell.find(ns + "f") is None:
                            continue
                        cached = cell.find(ns + "v")
                        if cached is None:
                            cached = ElementTree.SubElement(cell, ns + "v")
                        cached.text = str(values[address])
                    content = ElementTree.tostring(sheet, encoding="utf-8")
                target.writestr(info, content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _xlsx_work_name(row: dict[str, Any], value: Any) -> Any:
    source = str(value or "").strip()
    meta = row.get("meta") or {}
    official = str(meta.get("official_name") or "").strip()
    if official and source and " ".join(official.lower().split()) != " ".join(source.lower().split()):
        name = f"{official} / {source}"
    else:
        name = official or value
    quantity = meta.get("quantity_trace") or {}
    if not isinstance(quantity, Mapping) or quantity.get("status") not in {
        "cited_calc_quantity", "cited_conversion_factor",
    }:
        return name
    basis = str(quantity.get("conversion_source") or "").strip()
    formula = str(quantity.get("formula") or "").strip()
    if not basis or not formula:
        return name
    amount = quantity.get("source_quantity")
    amount = format(amount, "g") if isinstance(amount, (int, float)) and not isinstance(amount, bool) else str(amount)
    unit = str(quantity.get("source_unit") or "").strip()
    explanation = formula if basis in formula else f"{formula}. Основание: {basis}"
    return f"{name}\nИсходный объём: {amount} {unit}; расчётный эквивалент: {explanation}"


def _position_rows(ws, put, S: dict[str, Any], rows: list[dict[str, Any]], start_r: int,
                   pp_start: int) -> tuple[int, int, dict[str, list[int]]]:
    """Строки одной позиции (работа → ОТ/ЭМ/ОТм/М → прямые/ФОТ/НР/СП/Всего) из готовой трассы.
    Непрерывная нумерация: ``pp_start`` → возвращается обновлённый счётчик. Возвращает (next_r, pp)."""
    r = start_r
    pp = pp_start
    by_type: dict[str, list[int]] = {}
    row_meta_by_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        cols = row.get("columns", {}) or {}
        rtype = row.get("type", "")
        by_type.setdefault(str(rtype), []).append(r)
        if rtype == "position_total":
            row_meta_by_type["position_total"] = row.get("meta") or {}
        is_group = rtype in _GROUP_TYPES
        is_total = rtype in _TOTAL_TYPES
        if rtype == "work":
            pp += 1
            put(r, 1, pp, font=S["bold"], align="center")
        for key, xc in _COL.items():
            if key in cols:
                val = _LABEL_FIX.get(str(cols[key]), cols[key]) if key == "3" else cols[key]
                if rtype == "work" and key == "3":
                    val = _xlsx_work_name(row, val)
                    if isinstance(val, str) and "\nИсходный объём:" in val:
                        # Keep the cited formula readable in print as well as
                        # in the cell editor; Excel does not reliably auto-fit
                        # wrapped rows written by another application.
                        lines = sum(max(1, math.ceil(len(line) / 40)) for line in val.splitlines())
                        ws.row_dimensions[r].height = min(409, max(30, 12 * lines))
                put(r, xc, val, font=(S["bold"] if is_group else S["small"]), num=(xc in _NUM_COLS))
        # наименование группы/итога, если в columns нет "3"
        if "3" not in cols:
            label = row.get("label", "")
            if label:
                put(r, 3, label, font=(S["bold"] if is_group else S["small"]))
        _border_row(ws, S, r, fill=(S["fill_total"] if is_total else None))
        r += 1
    # Editable workbook formulas. JSON trace remains the immutable calculation
    # record, while Excel recalculates after quantity/price edits.
    for rtype in ("resource_labor", "resource_machine", "resource_machinist", "resource_material"):
        for row_no in by_type.get(rtype, []):
            if ws.cell(row=row_no, column=8).value not in (None, "") and ws.cell(row=row_no, column=9).value not in (None, ""):
                _set_formula(ws, row_no, 10, f"=ROUND(H{row_no}*I{row_no},2)", S["formula_values"])
            if all(ws.cell(row=row_no, column=column).value not in (None, "") for column in (7, 10, 11, 12)):
                _set_formula(ws, row_no, 12, f"=ROUND(G{row_no}*J{row_no}*K{row_no},2)", S["formula_values"])
            else:
                ws.cell(row=row_no, column=12).value = None
    group_rows = {
        "labor": (by_type.get("group_labor") or [None])[0],
        "machine": (by_type.get("group_machine") or [None])[0],
        "machinist": (by_type.get("group_machinist") or [None])[0],
        "material": (by_type.get("group_material") or [None])[0],
    }
    detail_rows = {
        "labor": by_type.get("resource_labor", []),
        "machine": by_type.get("resource_machine", []),
        "machinist": by_type.get("resource_machinist", []),
        "material": by_type.get("resource_material", []),
    }
    for kind, row_no in group_rows.items():
        if row_no is None:
            continue
        if all(ws.cell(row=detail, column=7).value not in (None, "") for detail in detail_rows[kind]):
            _set_formula(ws, row_no, 7, _sum_formula(detail_rows[kind], "G"), S["formula_values"])
        else:
            ws.cell(row=row_no, column=7).value = None
        cost_rows = detail_rows[kind]
        if kind == "machine":
            cost_rows = cost_rows + detail_rows["machinist"]
        _set_formula(ws, row_no, 12, _sum_formula(cost_rows), S["formula_values"])
    direct_row = (by_type.get("direct_total") or [None])[0]
    fot_row = (by_type.get("fot") or [None])[0]
    nr_row = (by_type.get("nr") or [None])[0]
    sp_row = (by_type.get("sp") or [None])[0]
    total_row = (by_type.get("position_total") or [None])[0]
    if direct_row:
        refs = [group_rows[k] for k in ("labor", "machine", "material") if group_rows[k]]
        _set_formula(ws, direct_row, 12, _sum_formula(refs), S["formula_values"])
    if fot_row:
        refs = [group_rows[k] for k in ("labor", "machinist") if group_rows[k]]
        _set_formula(ws, fot_row, 12, _sum_formula(refs), S["formula_values"])
    for accrual_row in (nr_row, sp_row):
        if accrual_row and fot_row:
            # A blank rate is unknown, not 0%. Only expose the editable formula
            # when the trace actually calculated this accrual (literal 0 counts).
            if all(ws.cell(accrual_row, column).value not in (None, "") for column in (5, 12)):
                _set_formula(ws, accrual_row, 12, f"=ROUND(L{fot_row}*E{accrual_row}/100,2)", S["formula_values"])
    if total_row:
        operator_price_value = (
            row_meta_by_type.get("position_total") or {}
        ).get("operator_confirmed_price")
        if operator_price_value is not None:
            ws.cell(
                row=total_row,
                column=12,
                value=round(float(operator_price_value), 2),
            )
        else:
            refs = [row_no for row_no in (direct_row, nr_row, sp_row) if row_no]
            _set_formula(ws, total_row, 12, _sum_formula(refs), S["formula_values"])
    return r, pp, by_type


def _section_title(ws, put, S: dict[str, Any], r: int, idx: int, sec_name: str) -> int:
    """Строка-заголовок раздела «Раздел N. <наименование>»."""
    label = f"Раздел {idx}. {sec_name}" if sec_name and sec_name != "Без раздела" else f"Раздел {idx}"
    put(r, 3, label, font=S["bold"])
    _border_row(ws, S, r, fill=S["fill_section"])
    return r + 1


def _section_subtotal(
    ws, put, S: dict[str, Any], r: int, idx: int, total: Any, *, position_total_rows: list[int] | None = None
) -> int:
    """Строка «Итого по разделу N» с суммой по разделу в графе «Стоимость всего»."""
    put(r, 3, f"Итого по разделу {idx}", font=S["bold"])
    put(r, 12, _f(total), font=S["bold"], num=True)
    if position_total_rows is not None:
        _set_formula(ws, r, 12, _sum_formula(position_total_rows), S["formula_values"])
    _border_row(ws, S, r, fill=S["fill_total"])
    return r + 1


def _grand_summary(
    ws, put, S: dict[str, Any], r: int, summary: dict[str, Any], *, formula_rows: dict[str, list[int]] | None = None
) -> tuple[int, dict[str, int]]:
    """Общий свод сметы: прямые/ФОТ/НР/СП + «ВСЕГО по смете» (Σ уже в трассе, не пересчёт)."""
    output_rows: dict[str, int] = {}
    for label, key in (("Итого прямые затраты по смете", "direct_total"), ("В том числе ФОТ", "fot"),
                       ("Накладные расходы", "nr"), ("Сметная прибыль", "sp")):
        put(r, 3, label, font=S["bold"])
        summary_key = "direct" if key == "direct_total" else key
        put(r, 12, _f(summary.get(summary_key, 0)), font=S["bold"], num=True)
        if formula_rows is not None:
            _set_formula(ws, r, 12, _sum_formula(formula_rows.get(key, [])), S["formula_values"])
        output_rows[key] = r
        _border_row(ws, S, r, fill=S["fill_total"])
        r += 1
    total_label = "ВСЕГО по смете без НДС" if summary.get("full_amount") is not None else "ИЗВЕСТНАЯ РАССЧИТАННАЯ ЧАСТЬ БЕЗ НДС"
    put(r, 3, total_label, font=S["bold"])
    put(r, 12, _f(summary.get("total_without_vat", summary.get("total", 0))), font=S["bold"], num=True)
    if formula_rows is not None:
        _set_formula(ws, r, 12, _sum_formula(formula_rows.get("position_total", [])), S["formula_values"])
    output_rows["total_without_vat"] = r
    _border_row(ws, S, r, fill=S["fill_grand"])
    if summary.get("vat_pct") not in (None, ""):
        r += 1
        put(r, 3, f"НДС {float(summary.get('vat_pct')):g}%", font=S["bold"])
        put(r, 12, _f(summary.get("vat", 0)), font=S["bold"], num=True)
        _set_formula(ws, r, 12, f"=ROUND(L{output_rows['total_without_vat']}*{float(summary.get('vat_pct')):g}/100,2)", S["formula_values"])
        output_rows["vat"] = r
        _border_row(ws, S, r, fill=S["fill_total"])
        r += 1
        gross_label = "ВСЕГО по смете с НДС" if summary.get("full_amount") is not None else "ИЗВЕСТНАЯ РАССЧИТАННАЯ ЧАСТЬ С НДС"
        put(r, 3, gross_label, font=S["bold"])
        put(r, 12, _f(summary.get("total_with_vat", 0)), font=S["bold"], num=True)
        _set_formula(ws, r, 12, f"=L{output_rows['total_without_vat']}+L{output_rows['vat']}", S["formula_values"])
        output_rows["total_with_vat"] = r
        _border_row(ws, S, r, fill=S["fill_grand"])
    return r + 1, output_rows


def _finalize(ws, head_r: int) -> None:
    """Ширины граф, закрепление экрана и печатная форма на одну страницу по ширине."""
    import openpyxl
    from openpyxl.worksheet.page import PageMargins

    for c, w in _WIDTHS.items():
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=head_r + 1, column=1)
    # Без явного print setup Calc/Excel разрезают 12 граф РИМ на отдельные
    # вертикальные страницы: на первых листах остаются названия, а суммы
    # печатаются отдельно. Форма должна быть длинной, но всегда цельной по ширине.
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.scale = None
    ws.page_margins = PageMargins(left=0.2, right=0.2, top=0.35, bottom=0.35, header=0.15, footer=0.15)
    ws.print_options.horizontalCentered = True
    ws.print_title_rows = f"{head_r}:{head_r}"
    ws.print_area = f"A1:L{ws.max_row}"


def _new_sheet():
    """Новая книга + лист «ЛСР РИМ» + стили + `put`."""
    import openpyxl
    from datetime import datetime

    wb = openpyxl.Workbook()
    # Метаданные не должны штамповаться текущим временем: пересборка тех же сохранённых
    # решений обязана давать те же байты, иначе «тот же документ» нельзя сверить по хешу
    # после повторной доставки (§ 7 «пересчёт скачанных байтов»). Дата, которую читает
    # оператор, остаётся в листе и приходит из той же трассы.
    wb.properties.created = datetime(2000, 1, 1)
    wb.properties.modified = datetime(2000, 1, 1)
    ws = wb.active
    ws.title = "ЛСР РИМ"
    S = _styles()
    return wb, ws, S, _make_put(ws, S)


def _set_header_total_formula(ws, total_row: int | None, values: dict) -> None:
    if not total_row:
        return
    for row_no in range(1, min(ws.max_row, 40) + 1):
        label = str(ws.cell(row=row_no, column=1).value or "")
        if label in {"Сметная стоимость", "Стоимость рассчитанной части"} or label.startswith(
            "Стоимость только привязанной части"
        ):
            _set_formula(ws, row_no, 4, f"=L{total_row}", values)
            return


def _readiness_label(value: Any) -> str:
    """One visible word per readiness question.

    ``True``/``False`` stay «да»/«нет»; a third state carries its own wording so a
    price that exists but belongs to nobody is not shown as a settled price.
    """

    if value is True:
        return "да"
    if value is False:
        return "нет"
    text = str(value or "").strip()
    return text or "н/п"


def _review_sheet(wb, lsr: dict[str, Any]) -> None:
    """Visible decisions/gaps; JSON remains the full immutable trace.

    Task 2026-09-29 § 4: every column of this sheet is filled from a decision or a
    calculation fact the revision already carries — the seven questions of an
    operation, the analogue's own unanswered match facts, the resources of the
    position and the reason each one is still open.  Where a route produces no such
    fact the cell says «н/п», which is a statement about the document, not an
    invented opinion: a heading has no applicability question, and an empty cell used
    to be indistinguishable from a broken one (tracker #54).
    """

    from openpyxl.styles import Alignment, Font, PatternFill

    from proxy.services.lsr_norm_quality_gate_service import (
        MATCH_FIELD_LABELS,
        is_analogue_norm_status,
        open_analogue_match_fields,
    )
    from proxy.services.rim_lsr_trace_service import (
        OPERATION_QUESTIONS,
        PRICE_REASON_PREFIXES,
        price_action_label,
    )

    ws = wb.create_sheet("Проверка")
    headers = [
        "Строка", "№ позиции", "work_id", "Связь операций", "Статус", "Готовность строки",
        "Норма", "Тип выбора", "Причина выбора",
        "Ограничения аналога", "Проверка ресурсов", "Решения по ресурсам",
        "Труд", "Машины", "Материалы", "Повторная проверка влияния",
    ]
    member_provenance = any(
        isinstance(item.get("source_row"), Mapping)
        and isinstance(item["source_row"].get("_catalog_source_origin"), Mapping)
        for item in lsr.get("row_bindings") or []
    )
    if member_provenance:
        headers.extend(["Файл источника", "Исходная строка"])
    last_column = len(headers)
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
    not_produced = "н/п"

    def review_line(binding: Mapping[str, Any], status_key: str, reason_key: str) -> str:
        """The calculator's own review statement for this row, or «н/п»."""

        return " — ".join(
            filter(None, [str(binding.get(status_key) or ""), str(binding.get(reason_key) or "")])
        ) or not_produced

    projected_rows = list(lsr.get("row_projection") or [])
    for index, item in enumerate(lsr.get("row_bindings") or []):
        # § 4: the position number and the operation links are read off the revision's
        # own projection when it is present, so the sheet and the readiness card state
        # the same identity for the same row.
        projected = (
            projected_rows[index]
            if index < len(projected_rows)
            and str(projected_rows[index].get("locator") or "") == str(item.get("row") or "")
            else item
        )
        readiness = item.get("readiness") or {}
        model_row = item.get("source_row")
        model_row = model_row if isinstance(model_row, Mapping) else {}
        position = item.get("position")
        position = position if isinstance(position, Mapping) else {}
        open_reasons = [str(value) for value in (readiness.get("open_reasons") or [])]
        # § 4 (tracker #54): the calculator's own per-resource decisions come first,
        # because they state the price that was actually used.  A route that never
        # reached the calculator can only show the resources it proposed itself.
        priced_resources = [
            entry for entry in (item.get("resource_decisions") or ()) if isinstance(entry, Mapping)
        ] or [
            entry for entry in (position.get("resources") or ()) if isinstance(entry, Mapping)
        ]
        resource_lines = []
        for entry in priced_resources:
            identity = str(entry.get("code") or entry.get("name") or "?")
            # The calculator names the resource it could not price after the colon of
            # its own reason tag, so the row states *why* it is still open instead of
            # leaving the operator to guess which of several prices is missing (§ 4).
            matched_reason = next((
                reason for reason in open_reasons
                if ":" in reason and reason.split(":", 1)[1] == identity
                and reason.startswith(PRICE_REASON_PREFIXES)
            ), "")
            gap_kind = str(entry.get("price_gap_kind") or "")
            if not gap_kind and matched_reason:
                # The reason list is the same one the remarks block below prints, so
                # a row cannot be «цена есть» in one column and open in the other.
                gap_kind = price_action_label(matched_reason.split(":", 1)[0])
            if gap_kind:
                price_note = gap_kind
            elif entry.get("price_used") is not None or entry.get("price") is not None:
                price_note = "цена есть"
            else:
                price_note = "цена не задана"
            unit_note = ""
            if f"quantity_missing:{identity}" in open_reasons:
                unit_note += " — неизвестный расход"
            if f"resource_amount_nonfinite:{identity}" in open_reasons:
                unit_note += " — стоимость вне числового диапазона"
            if str(entry.get("price_book_unit") or ""):
                unit_note += f" — единица книги: {entry.get('price_book_unit')}"
            # § 3: a derived шифр must never read as the card's own.  The ОЗП line of a
            # norm card names only a разряд, so when the calculator priced it from a
            # tariff code it worked out, the sheet says where that code came from.
            derivation = str(entry.get("code_derivation") or "")
            if derivation:
                unit_note += f" — {derivation}"
            resource_lines.append(
                f"{entry.get('kind') or '?'} {identity} "
                f"{entry.get('qty') if entry.get('qty') is not None else ''} "
                f"{entry.get('unit') or ''} — {price_note}{unit_note}"
            )
        # Applied exclusion has no surviving priced row. Keep the authored
        # action and its actual application visible on the same check sheet.
        action_labels = {"add": "добавить", "replace": "заменить",
                         "exclude": "исключить", "reuse": "повторно использовать"}
        for audit in item.get("resource_binding_audit") or ():
            if not isinstance(audit, Mapping):
                continue
            proposal = audit.get("proposal")
            proposal = proposal if isinstance(proposal, Mapping) else {}
            identity = str(proposal.get("target_resource_code") or proposal.get("target_resource_name")
                           or proposal.get("resource_code") or proposal.get("resource_name") or "ресурс не указан")
            action = action_labels.get(str(proposal.get("action") or ""), "некорректное действие")
            status = "применено" if audit.get("status") == "applied" else "не применено — требуется уточнение"
            refs = proposal.get("source_refs")
            refs = refs if isinstance(refs, (list, tuple)) else []
            basis = "; ".join(str(ref) for ref in refs)
            if proposal.get("basis_ref"):
                basis = "; ".join(filter(None, [basis, str(proposal["basis_ref"])]))
            reason = str(proposal.get("reason") or "основание не указано")
            resource_lines.append(f"Решение: {action} {identity} — {status}; {reason}"
                                  + (f"; источник: {basis}" if basis else ""))
        for audit in item.get("separate_supply_review_audit") or ():
            if not isinstance(audit, Mapping):
                continue
            proposal = audit.get("proposal")
            proposal = proposal if isinstance(proposal, Mapping) else {}
            refs = proposal.get("evidence_refs")
            refs = refs if isinstance(refs, list) else []
            status = "решение модели; ссылки проверены" if audit.get("status") == "confirmed" else "требуется уточнение связи"
            resource_lines.append(f"Отдельная поставка {proposal.get('source_row') or 'не указана'} — {status}; "
                                  f"{proposal.get('reason') or 'основание не указано'}"
                                  + ("; карточка: " + "; ".join(map(str, refs)) if refs else ""))
        analogue_lines = [
            str(value) for value in (item.get("analog_limitations") or ()) if str(value).strip()
        ]
        chosen_status = item.get("norm_status") or model_row.get("norm_status")
        if is_analogue_norm_status(chosen_status):
            analogue_lines += [
                f"не проверено: {MATCH_FIELD_LABELS.get(field, field)}"
                for field in open_analogue_match_fields(
                    {**model_row, "norm_status": chosen_status}
                )
            ]
        # § 4: «связь нескольких операций с одной исходной строкой» has to be visible
        # in the file — a locator carrying two operations, a supply line attached to a
        # work, a row covered by another row's cipher.
        links: list[str] = []
        siblings = int(projected.get("locator_operations") or 1)
        if siblings > 1:
            links.append(f"на строке {siblings} операции")
        parent = str(projected.get("parent_locator") or item.get("work_row") or "")
        if parent and parent != str(item.get("row") or ""):
            links.append(f"относится к {parent}")
        covered_by = str(projected.get("covered_by_work_id") or item.get("covered_by_work_id") or "")
        if covered_by:
            links.append(f"учтена в {covered_by}")
        operation_id = str(projected.get("operation_id") or "")
        if operation_id:
            links.append(operation_id)
        values = [
            item.get("row"),
            projected.get("position_no") if projected.get("position_no") else not_produced,
            item.get("work_id"),
            "; ".join(links) or not_produced,
            item.get("status"),
            " | ".join(
                [f"{label}={_readiness_label(readiness.get(name))}"
                 for name, label, _meaning in OPERATION_QUESTIONS]
                # «цены» is not one of the seven § 4 questions — it is the price
                # ladder's own statement and stays visible where it was before.
                + ([f"цены={_readiness_label(readiness.get('prices_provided'))}"]
                   if readiness.get("prices_provided") is not None else [])
            ),
            item.get("code"),
            item.get("selection_kind") or ("covered_by " + str(item.get("covered_by_work_id")) if item.get("covered_by_work_id") else "")
            or str(item.get("norm_status") or model_row.get("norm_status") or ""),
            item.get("reason") or item.get("coverage_reason") or model_row.get("open_gap") or not_produced,
            "\n".join(analogue_lines) or not_produced,
            review_line(item, "resource_review_status", "resource_review_reason"),
            "\n".join(resource_lines) or not_produced,
            review_line(item, "labor_review_status", "labor_review_reason"),
            review_line(item, "machine_review_status", "machine_review_reason"),
            review_line(item, "material_review_status", "material_review_reason"),
            review_line(item, "dominant_review_status", "dominant_review_reason"),
        ]
        if member_provenance:
            origin = model_row.get("_catalog_source_origin")
            origin = origin if isinstance(origin, Mapping) else {}
            values.extend([origin.get("original_name"), origin.get("original_locator")])
        ws.append(values)
        if member_provenance:
            for column in (last_column - 1, last_column):
                cell = ws.cell(ws.max_row, column)
                if isinstance(cell.value, str):
                    cell.data_type = "s"
    ws.append([])
    ws.append(["Общие замечания и незакрытые позиции"])
    section_row = ws.max_row
    ws.merge_cells(start_row=section_row, start_column=1, end_row=section_row, end_column=last_column)
    ws.cell(section_row, 1).font = Font(bold=True)
    ws.cell(section_row, 1).fill = PatternFill("solid", fgColor="FCE4D6")
    ws.append(["Код", "work_id", "Тип", "Сообщение"])
    issue_header_row = ws.max_row
    ws.merge_cells(start_row=issue_header_row, start_column=4, end_row=issue_header_row, end_column=last_column)
    for cell in ws[issue_header_row]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="FFF2CC")

    def append_issue(item, issue_type: str) -> None:
        payload = item if isinstance(item, dict) else {}
        code = str(payload.get("code") or issue_type)
        work_id = str(payload.get("work_id") or "")
        message = str(payload.get("reason") or payload.get("message") or item)
        ws.append([code, work_id, issue_type, message])
        issue_row = ws.max_row
        ws.merge_cells(start_row=issue_row, start_column=4, end_row=issue_row, end_column=last_column)
        ws.row_dimensions[issue_row].height = max(30, min(90, 15 * (1 + len(message) // 110)))

    for item in lsr.get("blockers") or []:
        append_issue(item, "blocker")
    for item in lsr.get("warnings") or []:
        append_issue(item, "warning")
    if (lsr.get("row_projection")
            and not (lsr.get("blockers") or lsr.get("warnings"))):
        # § 4: an empty remarks block reads the same as an unproduced one.  This line
        # reports only what the file itself decided — the projection left no question
        # unanswered — together with the calculator's own status, so a finished
        # document is distinguishable from a section nobody filled in.  No expertise
        # is claimed here: the status stays the calculator's word.
        status = str((lsr.get("summary") or {}).get("result_status") or "") or "неизвестен"
        ws.append([
            "", "", "note",
            f"по спроецированным строкам открытых вопросов не осталось: каждая из них "
            f"ответила на свои вопросы; статус расчёта всей ревизии — {status}.",
        ])
        note_row = ws.max_row
        ws.merge_cells(start_row=note_row, start_column=4, end_row=note_row, end_column=last_column)
        ws.row_dimensions[note_row].height = 30
    widths = {
        "A": 28, "B": 10, "C": 16, "D": 34, "E": 22, "F": 70, "G": 14, "H": 50,
        "I": 48, "J": 42, "K": 55, "L": 38, "M": 38, "N": 38, "O": 42, "P": 42,
    }
    for column, width in widths.items():
        ws.column_dimensions[column].width = width
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "A2"


def render_trace_xlsx(trace: dict[str, Any], out_path: str | Path, *,
                      title: str | None = None, meta: Optional[dict[str, Any]] = None) -> Path:
    """Трасса ОДНОЙ позиции → XLSX по форме Приложения 3 к 421/пр. Возвращает путь."""
    meta = meta or {}
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb, ws, S, put = _new_sheet()
    head_r = _header_block(ws, put, S, name=trace.get("name", ""),
                           summary=trace.get("summary", {}) or {}, meta=meta)
    _table_header(ws, put, S, head_r)
    _, _, formula_rows = _position_rows(ws, put, S, trace.get("rows", []), head_r + 1, 0)
    _set_header_total_formula(ws, (formula_rows.get("position_total") or [None])[0], S["formula_values"])
    _finalize(ws, head_r)
    _save_calculated_workbook(wb, path, S["formula_values"])
    return path


def render_lsr_xlsx(lsr: dict[str, Any], out_path: str | Path, *,
                    title: str | None = None, meta: Optional[dict[str, Any]] = None) -> Path:
    """Многопозиционная ЛСР (``build_lsr_trace``) → XLSX по форме Приложения 3: шапка с общим итогом +
    разделы (заголовок → позиции с непрерывной нумерацией → «Итого по разделу N») + «ВСЕГО по смете».

    Рендер ГОТОВОЙ трассы — числа те же, что у каждой позиции в /rim-trace, и Σ — в свод. 0 LLM."""
    meta = meta or {}
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = lsr.get("summary", {}) or {}
    sections = lsr.get("sections", []) or []
    wb, ws, S, put = _new_sheet()
    head_r = _header_block(ws, put, S, name=lsr.get("name", ""), summary=summary, meta=meta)
    _table_header(ws, put, S, head_r)

    r = head_r + 1
    pp = 0
    all_formula_rows: dict[str, list[int]] = {}
    multi = len(sections) > 1
    for idx, sec in enumerate(sections, 1):
        section_position_totals: list[int] = []
        sec_name = str(sec.get("section", "") or "")
        show_sec = multi or (sec_name and sec_name != "Без раздела")
        if show_sec:
            r = _section_title(ws, put, S, r, idx, sec_name)
        for trace in sec.get("positions", []) or []:
            r, pp, formula_rows = _position_rows(ws, put, S, trace.get("rows", []), r, pp)
            for key, values in formula_rows.items():
                all_formula_rows.setdefault(key, []).extend(values)
            section_position_totals.extend(formula_rows.get("position_total", []))
        if show_sec:
            r = _section_subtotal(
                ws, put, S, r, idx, sec.get("total", 0), position_total_rows=section_position_totals
            )
    for binding in lsr.get("row_bindings") or []:
        if binding.get("status") != "covered":
            continue
        source = binding.get("source_row") or {}
        put(r, 2, binding.get("row"))
        put(r, 3, f"{source.get('title') or ''}. {binding.get('message') or ''}")
        put(r, 4, source.get("unit"))
        put(r, 7, source.get("quantity"))
        ws.row_dimensions[r].height = 56
        r += 1
    _, grand_rows = _grand_summary(ws, put, S, r, summary, formula_rows=all_formula_rows)
    _set_header_total_formula(
        ws,
        grand_rows.get("total_with_vat") or grand_rows.get("total_without_vat"),
        S["formula_values"],
    )
    _finalize(ws, head_r)
    _review_sheet(wb, lsr)
    _save_calculated_workbook(wb, path, S["formula_values"])
    return path
