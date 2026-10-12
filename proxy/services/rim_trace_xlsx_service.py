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

import logging

from pathlib import Path
from typing import Any, Optional

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
    }


def _make_put(ws, S: dict[str, Any]):
    """Фабрика ячеечного `put`, замкнутого на лист + стили."""
    Alignment = S["Alignment"]

    def _put(r: int, c: int, v: Any, *, font=None, num: bool = False, align: str = "left"):
        cell = ws.cell(row=r, column=c, value=v)
        cell.font = font or S["small"]
        if num and isinstance(v, (int, float)):
            cell.number_format = "#,##0.#########" if c in {5, 6, 7, 9, 11} else "#,##0.00"
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
    put(r, 1, "Наименование субъекта РФ: " + str(meta.get("subject", "—")), font=S["dim"]); r += 2
    result_status = str(summary.get("result_status") or "").strip()
    review_required = int(summary.get("resource_review_required_operations") or 0)
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
    if review_required:
        put(r, 1, f"Требуют проверки модели: {review_required} операций. Их суммы включены в предварительный расчёт.", font=S["warning"])
        r += 1
    input_rows = int(summary.get("input_rows") or 0)
    non_work_rows = int(summary.get('non_work_rows') or 0)
    calculation_rows = max(0, input_rows - non_work_rows)
    if non_work_rows:
        put(r, 1, f"Исходных строк: {input_rows}. Строк-разделов по решению модели: {non_work_rows}. Расчётных строк: {calculation_rows}.", font=S['dim'])
        r += 1
    bound_rows = int(summary.get("bound_rows") or 0)
    open_rows = int(summary.get("open_rows", summary.get("unbound_rows")) or 0)
    covered_rows = int(summary.get("covered_rows") or 0)
    closed_rows = bound_rows + covered_rows
    low_coverage = (
        calculation_rows > 0
        and open_rows > 0
        and (open_rows / calculation_rows >= 0.30 or closed_rows / calculation_rows < 0.70)
    )
    if low_coverage:
        put(
            r,
            1,
            (
                f"ПОКРЫТИЕ НИЗКОЕ: привязано {bound_rows} из {calculation_rows} строк"
                f"{', ещё ' + str(covered_rows) + ' покрыто соседними' if covered_rows else ''}. "
                "Сумма относится к рассчитанным позициям и не является итогом ведомости."
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
        "Предварительная стоимость рассчитанной части"
        if result_status and result_status != "priced_final"
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


def _xlsx_work_name(row: dict[str, Any], value: Any) -> Any:
    source = str(value or "").strip()
    official = str((row.get("meta") or {}).get("official_name") or "").strip()
    if official and source and " ".join(official.lower().split()) != " ".join(source.lower().split()):
        return f"{official} / {source}"
    return official or value


def _mark_unapplied_coefficient(ws, S: dict[str, Any], row_no: int, row: dict[str, Any]) -> None:
    """Пометить в книге коэффициент, который модель предложила, а расчёт не принял.

    Коэффициент берётся из МДС или приложения к сборнику и требует основания: применить
    предложенное число без него значит поменять деньги догадкой. Но и молчать нельзя —
    строка уходит в смету по норме, а человек не узнаёт, что её считали нужным поднять.
    До 11.09 отметка жила только в `missing` разбора и до самой книги не доходила, то
    есть до проверяющего не доходила вовсе (ревью Codex 11.09, шаг 3).

    Значение ячейки не подменяется: в графе остаётся принятый расчётом коэффициент,
    а предложенный стоит рядом как примечание — иначе формулы считали бы по числу,
    которое никто не обосновал.
    """
    meta = row.get("meta") or {}
    if str(meta.get("coefficient_status") or "") != "needs_basis":
        return
    proposed = meta.get("proposed_coefficient")
    note = str(meta.get("coefficient_note") or "").strip() or (
        f"модель предложила коэффициент {proposed}; в расчёт не принят без основания"
        " (МДС или приложение к сборнику)"
    )
    try:
        from openpyxl.comments import Comment

        cell = ws.cell(row=row_no, column=6)
        cell.comment = Comment(note, "Л.Е.С.")
        # Заливкой строка видна и без наведения курсора: примечание в закрытой книге
        # ничем себя не выдаёт, а пропущенная проверка стоит денег.
        cell.fill = S["fill_head"]
    except Exception:  # noqa: BLE001 — пометка не должна ронять сборку книги
        logging.getLogger(__name__).warning(
            "[LSR_XLSX] пометка коэффициента не проставлена", exc_info=True
        )


def _position_rows(ws, put, S: dict[str, Any], rows: list[dict[str, Any]], start_r: int,
                   pp_start: int) -> tuple[int, int, dict[str, list[int]]]:
    """Строки одной позиции (работа → ОТ/ЭМ/ОТм/М → прямые/ФОТ/НР/СП/Всего) из готовой трассы.
    Непрерывная нумерация: ``pp_start`` → возвращается обновлённый счётчик. Возвращает (next_r, pp)."""
    r = start_r
    pp = pp_start
    by_type: dict[str, list[int]] = {}
    price_precision: dict[int, int] = {}
    excluded_rows: set[int] = set()
    for row in rows:
        cols = row.get("columns", {}) or {}
        rtype = row.get("type", "")
        price_precision[r] = int((row.get("meta") or {}).get("unit_price_precision", 2))
        if (row.get('meta') or {}).get('excluded'):
            excluded_rows.add(r)
        by_type.setdefault(str(rtype), []).append(r)
        is_group = rtype in _GROUP_TYPES
        is_total = rtype in _TOTAL_TYPES
        if rtype == "work":
            pp += 1
            put(r, 1, pp, font=S["bold"], align="center")
            _mark_unapplied_coefficient(ws, S, r, row)
            from openpyxl.comments import Comment

            metadata = row.get('meta') or {}
            source_notes = []
            if metadata.get('source_row') is not None:
                source_notes.append('source_row: ' + str(metadata['source_row']))
            if metadata.get('work_id') is not None:
                source_notes.append('work_id: ' + str(metadata['work_id']))
            source_notes.extend(f'{key}: {metadata[key]}' for key in
                                ('operation', 'coverage', 'not_covered', 'coefficient_basis', 'coefficient_target') if metadata.get(key))
            normative_source = metadata.get('normative_source') or {}
            if metadata.get('document_price_basis'):
                source_notes.append('document_price_basis: ' + str(metadata['document_price_basis']))
            source_notes.extend(
                f'{key}: {normative_source[key]}'
                for key in ('norm_id', 'edition', 'base_type', 'key', 'source_ref')
                if normative_source.get(key)
            )
            for key in ('identity', 'identity_status', 'expected_identity', 'revision_conflict'):
                if normative_source.get(key):
                    source_notes.append(f'{key}: {normative_source[key]}')
            if source_notes:
                ws.cell(r, 2).comment = Comment('\n'.join(source_notes), 'Л.Е.С.')
            quantity_trace = metadata.get('quantity_trace') or {}
            if quantity_trace:
                note = str(quantity_trace.get('formula') or '')
                if quantity_trace.get('conversion_source'):
                    note += '\nИсточник: ' + str(quantity_trace['conversion_source'])
                ws.cell(r, 5).comment = Comment(note, 'Л.Е.С.')
        for key, xc in _COL.items():
            if key in cols:
                val = _LABEL_FIX.get(str(cols[key]), cols[key]) if key == "3" else cols[key]
                if rtype == "work" and key == "3":
                    val = _xlsx_work_name(row, val)
                if rtype == "resource_material" and key == "3":
                    catalog_name = str((row.get("meta") or {}).get("price_card_name") or "").strip()
                    if catalog_name:
                        val = f"По справочнику: {catalog_name}\nПо решению модели: {val}"
                put(r, xc, val, font=(S["bold"] if is_group else S["small"]), num=(xc in _NUM_COLS))
        if rtype.startswith('resource_') and (row.get('meta') or {}).get('source_resource_ids'):
            from openpyxl.comments import Comment
            import json
            metadata = row['meta']
            ids = metadata['source_resource_ids']
            selector = 'row:' + str(ids[0]) if len(ids) == 1 else metadata.get('source_resource_group_id')
            ws.cell(r, 2).comment = Comment(json.dumps(dict(target_resource_id=selector,
                **{key: metadata[key] for key in ('source_resource_ids', 'source_resource_group_id',
                   'normative_identity', 'excluded', 'excluded_per_unit') if key in metadata}),
                ensure_ascii=False, sort_keys=True), 'Л.Е.С.')
        if rtype.startswith('resource_') and (row.get('meta') or {}).get('price_record_identity'):
            from openpyxl.comments import Comment
            import json
            ws.cell(r, 10).comment = Comment(json.dumps(row['meta']['price_record_identity'],
                ensure_ascii=False, sort_keys=True), 'Л.Е.С.')
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
                ws.cell(row=row_no, column=10, value=f"=ROUND(H{row_no}*I{row_no},{price_precision[row_no]})")
            if all(ws.cell(row=row_no, column=column).value not in (None, "") for column in (7, 10, 11)):
                ws.cell(row=row_no, column=12, value=f"=ROUND(G{row_no}*J{row_no}*K{row_no},2)")
            else:
                ws.cell(row=row_no, column=12).value = 0 if row_no in excluded_rows else None
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
        if all(ws.cell(row=detail_row, column=7).value is not None for detail_row in detail_rows[kind]):
            ws.cell(row=row_no, column=7, value=_sum_formula(detail_rows[kind], "G"))
        cost_rows = detail_rows[kind]
        if kind == "machine":
            cost_rows = cost_rows + detail_rows["machinist"]
        ws.cell(row=row_no, column=12, value=_sum_formula(cost_rows))
    direct_row = (by_type.get("direct_total") or [None])[0]
    fot_row = (by_type.get("fot") or [None])[0]
    nr_row = (by_type.get("nr") or [None])[0]
    sp_row = (by_type.get("sp") or [None])[0]
    total_row = (by_type.get("position_total") or [None])[0]
    if direct_row:
        refs = [group_rows[k] for k in ("labor", "machine", "material") if group_rows[k]]
        ws.cell(row=direct_row, column=12, value=_sum_formula(refs))
    if fot_row:
        refs = [group_rows[k] for k in ("labor", "machinist") if group_rows[k]]
        ws.cell(row=fot_row, column=12, value=_sum_formula(refs))
    if nr_row and fot_row:
        ws.cell(row=nr_row, column=12, value=f"=ROUND(L{fot_row}*E{nr_row}/100,2)")
    if sp_row and fot_row:
        ws.cell(row=sp_row, column=12, value=f"=ROUND(L{fot_row}*E{sp_row}/100,2)")
    if total_row:
        refs = [row_no for row_no in (direct_row, nr_row, sp_row) if row_no]
        ws.cell(row=total_row, column=12, value=_sum_formula(refs))
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
        ws.cell(row=r, column=12, value=_sum_formula(position_total_rows))
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
            ws.cell(row=r, column=12, value=_sum_formula(formula_rows.get(key, [])))
        output_rows[key] = r
        _border_row(ws, S, r, fill=S["fill_total"])
        r += 1
    total_label = "ВСЕГО по смете без НДС" if summary.get("full_amount") is not None else "ИЗВЕСТНАЯ РАССЧИТАННАЯ ЧАСТЬ БЕЗ НДС"
    put(r, 3, total_label, font=S["bold"])
    put(r, 12, _f(summary.get("total_without_vat", summary.get("total", 0))), font=S["bold"], num=True)
    if formula_rows is not None:
        ws.cell(row=r, column=12, value=_sum_formula(formula_rows.get("position_total", [])))
    output_rows["total_without_vat"] = r
    _border_row(ws, S, r, fill=S["fill_grand"])
    if summary.get("vat_pct") not in (None, ""):
        r += 1
        put(r, 3, f"НДС {float(summary.get('vat_pct')):g}%", font=S["bold"])
        put(r, 12, _f(summary.get("vat", 0)), font=S["bold"], num=True)
        ws.cell(row=r, column=12, value=f"=ROUND(L{output_rows['total_without_vat']}*{float(summary.get('vat_pct')):g}/100,2)")
        output_rows["vat"] = r
        _border_row(ws, S, r, fill=S["fill_total"])
        r += 1
        gross_label = "ВСЕГО по смете с НДС" if summary.get("full_amount") is not None else "ИЗВЕСТНАЯ РАССЧИТАННАЯ ЧАСТЬ С НДС"
        put(r, 3, gross_label, font=S["bold"])
        put(r, 12, _f(summary.get("total_with_vat", 0)), font=S["bold"], num=True)
        ws.cell(row=r, column=12, value=f"=L{output_rows['total_without_vat']}+L{output_rows['vat']}")
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

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ЛСР РИМ"
    S = _styles()
    return wb, ws, S, _make_put(ws, S)


def _set_header_total_formula(ws, total_row: int | None) -> None:
    if not total_row:
        return
    for row_no in range(1, min(ws.max_row, 40) + 1):
        label = str(ws.cell(row=row_no, column=1).value or "")
        if label in {"Сметная стоимость", "Стоимость рассчитанной части", "Предварительная стоимость рассчитанной части"} or label.startswith(
            "Стоимость только привязанной части"
        ):
            ws.cell(row=row_no, column=4, value=f"=L{total_row}")
            return


def _review_sheet(wb, lsr: dict[str, Any]) -> None:
    """Visible decisions/gaps; JSON remains the full immutable trace."""
    from openpyxl.styles import Alignment, Font, PatternFill

    ws = wb.create_sheet("Проверка")
    headers = [
        "Строка", "work_id", "Статус", "Норма", "Тип выбора", "Причина выбора",
        "Ограничения аналога", "Проверка ресурсов", "Решения по ресурсам",
        "Труд", "Машины", "Материалы", "Повторная проверка влияния",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
    for item in lsr.get("row_bindings") or []:
        resource_text = "\n".join(
            f"{entry.get('action')}: {entry.get('resource_code') or entry.get('resource_name')} "
            + (f"[{entry['target_resource_id']}] " if entry.get('target_resource_id') else '')
            +
            f"{entry.get('quantity') if entry.get('quantity') is not None else ''} {entry.get('unit') or ''}; "
            f"{entry.get('reason') or ''}; основание: {entry.get('basis_ref') or '—'}"
            + (f"; исходное количество снятия: {entry['excluded_quantity'] if entry.get('excluded_quantity') is not None else 'неизвестно'} {entry.get('excluded_unit') or ''}"
               if entry.get('action') == 'excluded' else '')
            for entry in (item.get("resource_bindings") or [])
        )
        ws.append([
            item.get("row"), item.get("work_id"), item.get("status"), item.get("code"),
            item.get("selection_kind") or ("covered_by " + str(item.get("covered_by_work_id") or "") if item.get("covered_by_work_id") else ""),
            item.get("reason") or item.get("coverage_reason") or item.get("message"),
            "\n".join(str(value) for value in (item.get("analog_limitations") or [])),
            " — ".join(filter(None, [
                str(item.get("resource_review_status") or ""),
                str(item.get("resource_review_reason") or ""),
            ])),
            resource_text,
            " — ".join(filter(None, [
                str(item.get("labor_review_status") or ""),
                str(item.get("labor_review_reason") or ""),
            ])),
            " — ".join(filter(None, [
                str(item.get("machine_review_status") or ""),
                str(item.get("machine_review_reason") or ""),
            ])),
            " — ".join(filter(None, [
                str(item.get("material_review_status") or ""),
                str(item.get("material_review_reason") or ""),
            ])),
            " — ".join(filter(None, [
                str(item.get("dominant_review_status") or ""),
                str(item.get("dominant_review_reason") or ""),
            ])),
        ])
    ws.append([])
    ws.append(["Общие замечания и незакрытые позиции"])
    section_row = ws.max_row
    ws.merge_cells(start_row=section_row, start_column=1, end_row=section_row, end_column=13)
    ws.cell(section_row, 1).font = Font(bold=True)
    ws.cell(section_row, 1).fill = PatternFill("solid", fgColor="FCE4D6")
    ws.append(["Код", "work_id", "Тип", "Сообщение"])
    issue_header_row = ws.max_row
    ws.merge_cells(start_row=issue_header_row, start_column=4, end_row=issue_header_row, end_column=13)
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
        ws.merge_cells(start_row=issue_row, start_column=4, end_row=issue_row, end_column=13)
        ws.row_dimensions[issue_row].height = max(30, min(90, 15 * (1 + len(message) // 110)))

    for item in lsr.get("blockers") or []:
        append_issue(item, "blocker")
    for item in lsr.get("warnings") or []:
        append_issue(item, "warning")
    widths = {
        "A": 28, "B": 16, "C": 22, "D": 24, "E": 14, "F": 50,
        "G": 48, "H": 42, "I": 55, "J": 38, "K": 38, "L": 38,
        "M": 42,
    }
    for column, width in widths.items():
        ws.column_dimensions[column].width = width
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            # Review content is authored text, never an executable Excel formula.
            if cell.data_type == 'f':
                cell.data_type = 's'
    ws.freeze_panes = "A2"


def _source_registry_sheet(wb, lsr: dict[str, Any]) -> None:
    """Source inventory is distinct from the model's authored operations."""
    registry = lsr.get('source_registry')
    if registry is None:
        return
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ws = wb.create_sheet('Исходные строки')
    ws.append(['Якорь позиции', 'Адрес в исходном файле', 'Раздел', 'Наименование',
               'Единица исходная', 'Количество исходное', 'Статус расчёта',
               'work_id операций', 'Исходная строка'])
    if registry.get('status') != 'parsed':
        ws.append(['Реестр исходных строк не прочитан. Полнота ведомости не подтверждена.'])
    for row in registry.get('rows') or []:
        ws.append([row.get('anchor'), f"{row.get('sheet')}!R{row.get('sheet_row')}",
                   row.get('section'), row.get('title'), row.get('unit'), row.get('quantity'),
                   row.get('status'), '\n'.join(row.get('work_ids') or []), row.get('raw')])
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill('solid', fgColor='D9EAF7')
    for index, width in enumerate([25, 25, 35, 65, 18, 22, 30, 30, 80], 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in ws:
        for cell in row:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
            # Source text is data, including any leading equals sign.
            if cell.data_type == 'f':
                cell.data_type = 's'
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions


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
    _set_header_total_formula(ws, (formula_rows.get("position_total") or [None])[0])
    _finalize(ws, head_r)
    wb.save(path)
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
    if lsr.get('document_price_basis') is not None:
        from openpyxl.comments import Comment
        import json
        ws.cell(1, 1).comment = Comment(json.dumps({
            'document_price_basis': lsr['document_price_basis'],
            'price_basis_conflict': lsr.get('price_basis_conflict')},
            ensure_ascii=False, sort_keys=True), 'Л.Е.С.')
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
    _, grand_rows = _grand_summary(ws, put, S, r, summary, formula_rows=all_formula_rows)
    _set_header_total_formula(
        ws,
        grand_rows.get("total_with_vat") or grand_rows.get("total_without_vat"),
    )
    _finalize(ws, head_r)
    _review_sheet(wb, lsr)
    _source_registry_sheet(wb, lsr)
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"
    wb.save(path)
    return path
