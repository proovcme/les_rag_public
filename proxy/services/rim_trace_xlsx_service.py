"""Рендерер РИМ-трассы ЛСР в XLSX по форме **Приложения № 4** к Методике 421/пр (форма ГРАНД-Сметы).

НЕ калькулятор: берёт ГОТОВУЮ трассу и раскладывает её строки по графам формы ЛСР. Два входа:

* :func:`render_trace_xlsx` — ОДНА позиция (``rim_lsr_trace_service.build_position_trace``);
* :func:`render_lsr_xlsx` — МНОГОПОЗИЦИОННАЯ ЛСР (``rim_lsr_trace_service.build_lsr_trace``):
  шапка с общим итогом + разделы (заголовок раздела → позиции с непрерывной нумерацией → «Итого по
  разделу N») + общий свод «ВСЕГО по смете».

Оба рендера делят шапку/графы/строки позиции/финализацию — числа НЕ пересчитываются (Σ уже сделана в
трассе). 0 LLM. Графы формы (эталон): № п/п · Обоснование · Наименование · Ед.изм. · Кол-во (на ед./
коэф./всего) · Сметная стоимость (на ед./всего). Колонки trace.columns 2-12 ложатся на них напрямую.
ЛСР = Приложение № 4 (Прил.3 = объектный расчёт).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# trace.columns (str) → колонка openpyxl (1-индекс) по форме Приложения 4.
#  "2"Обоснование→B · "3"Наименование→C · "4"Ед→H · "5"кол/ед→I · "6"коэф→J · "7"всего→K
#  "10"стоим/ед→L · "12"всего стоим→N.  Графа № п/п → A (col 1, только строки-работы).
_COL: dict[str, int] = {"2": 2, "3": 3, "4": 8, "5": 9, "6": 10, "7": 11, "10": 12, "12": 14}
_NUM_COLS = {9, 10, 11, 12, 14}  # I,J,K,L,N — числовые

_GROUP_TYPES = {"group_labor", "group_machine", "group_machinist", "group_material",
                "direct_total", "fot", "nr", "sp", "position_total"}
_TOTAL_TYPES = {"direct_total", "fot", "nr", "sp", "position_total"}
# Формулировки трассы → формулировки формы ГРАНД (эталон).
_LABEL_FIX = {"Итого по позиции": "Всего по позиции"}

_TABLE_HEADERS = {1: "№ п/п", 2: "Обоснование", 3: "Наименование работ и затрат", 8: "Ед. изм.",
                  9: "Кол-во на ед.", 10: "коэф.", 11: "Кол-во всего", 12: "Цена на ед., руб.",
                  14: "Стоимость всего, руб."}
_WIDTHS = {1: 6, 2: 18, 3: 40, 4: 10, 5: 8, 6: 6, 7: 6, 8: 9, 9: 11, 10: 7, 11: 12, 12: 13, 13: 7, 14: 15}


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
    """Границы по графам 1-14 строки + опц. заливка (итоги/разделы)."""
    for c in range(1, 15):
        cc = ws.cell(row=r, column=c)
        cc.border = S["border"]
        if fill is not None:
            cc.fill = fill


def _header_block(ws, put, S: dict[str, Any], *, name: str, summary: dict[str, Any],
                  meta: dict[str, Any]) -> int:
    """Шапка формы (стройка/объект/ЛСР №/наименование/метод/уровень цен/субъект + сметная стоимость
    и её разбивка). Возвращает номер строки шапки таблицы (графы)."""
    r = 1
    put(r, 12, "Приложение № 4", font=S["dim"], align="right"); r += 1
    put(r, 12, "к Методике (приказ Минстроя России от 04.08.2020 № 421/пр)", font=S["dim"], align="right"); r += 2
    put(r, 1, meta.get("stroika", "(наименование стройки)"), font=S["dim"]); r += 1
    put(r, 1, meta.get("object", "(наименование объекта капитального строительства)"), font=S["dim"]); r += 2
    put(r, 1, "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ (СМЕТА) № " + str(meta.get("lsr_no", "____")), font=S["bold"]); r += 1
    put(r, 1, name or "(наименование работ и затрат)", font=S["small"]); r += 1
    put(r, 1, "Составлен ресурсным методом", font=S["dim"]); r += 1
    put(r, 1, "Основание: " + str(meta.get("osnovanie", "—")), font=S["dim"]); r += 1
    put(r, 1, "Составлен(а) в текущем уровне цен: " + str(meta.get("price_level", "—")), font=S["dim"]); r += 1
    put(r, 1, "Наименование субъекта РФ: " + str(meta.get("subject", "—")), font=S["dim"]); r += 2
    put(r, 1, "Сметная стоимость", font=S["bold"])
    put(r, 4, _f(summary.get("total", 0)), font=S["bold"], num=True)
    put(r, 6, "руб.", font=S["dim"]); r += 1
    put(r, 1, "  средства на оплату труда рабочих", font=S["dim"]); put(r, 4, _f(summary.get("ozp", 0)), font=S["dim"], num=True); r += 1
    put(r, 1, "  средства на оплату труда машинистов", font=S["dim"]); put(r, 4, _f(summary.get("zpm", 0)), font=S["dim"], num=True); r += 1
    put(r, 1, "  нормативные затраты труда рабочих, чел.-ч", font=S["dim"]); put(r, 4, _f(summary.get("labor_qty", 0)), font=S["dim"], num=True); r += 1
    put(r, 1, "  нормативные затраты труда машинистов, чел.-ч", font=S["dim"]); put(r, 4, _f(summary.get("machinist_qty", 0)), font=S["dim"], num=True); r += 2
    return r


def _table_header(ws, put, S: dict[str, Any], head_r: int) -> int:
    """Шапка таблицы (графы № п/п…Стоимость всего)."""
    for c, t in _TABLE_HEADERS.items():
        cell = put(head_r, c, t, font=S["bold"], align="center")
        cell.fill = S["fill_head"]
        cell.border = S["border"]
        cell.alignment = S["Alignment"](horizontal="center", vertical="center", wrap_text=True)
    return head_r


def _position_rows(ws, put, S: dict[str, Any], rows: list[dict[str, Any]], start_r: int,
                   pp_start: int) -> tuple[int, int]:
    """Строки одной позиции (работа → ОТ/ЭМ/ОТм/М → прямые/ФОТ/НР/СП/Всего) из готовой трассы.
    Непрерывная нумерация: ``pp_start`` → возвращается обновлённый счётчик. Возвращает (next_r, pp)."""
    r = start_r
    pp = pp_start
    for row in rows:
        cols = row.get("columns", {}) or {}
        rtype = row.get("type", "")
        is_group = rtype in _GROUP_TYPES
        is_total = rtype in _TOTAL_TYPES
        if rtype == "work":
            pp += 1
            put(r, 1, pp, font=S["bold"], align="center")
        for key, xc in _COL.items():
            if key in cols:
                val = _LABEL_FIX.get(str(cols[key]), cols[key]) if key == "3" else cols[key]
                put(r, xc, val, font=(S["bold"] if is_group else S["small"]), num=(xc in _NUM_COLS))
        # наименование группы/итога, если в columns нет "3"
        if "3" not in cols:
            label = row.get("label", "")
            if label:
                put(r, 3, label, font=(S["bold"] if is_group else S["small"]))
        _border_row(ws, S, r, fill=(S["fill_total"] if is_total else None))
        r += 1
    return r, pp


def _section_title(ws, put, S: dict[str, Any], r: int, idx: int, sec_name: str) -> int:
    """Строка-заголовок раздела «Раздел N. <наименование>»."""
    label = f"Раздел {idx}. {sec_name}" if sec_name and sec_name != "Без раздела" else f"Раздел {idx}"
    put(r, 3, label, font=S["bold"])
    _border_row(ws, S, r, fill=S["fill_section"])
    return r + 1


def _section_subtotal(ws, put, S: dict[str, Any], r: int, idx: int, total: Any) -> int:
    """Строка «Итого по разделу N» с суммой по разделу в графе «Стоимость всего»."""
    put(r, 3, f"Итого по разделу {idx}", font=S["bold"])
    put(r, 14, _f(total), font=S["bold"], num=True)
    _border_row(ws, S, r, fill=S["fill_total"])
    return r + 1


def _grand_summary(ws, put, S: dict[str, Any], r: int, summary: dict[str, Any]) -> int:
    """Общий свод сметы: прямые/ФОТ/НР/СП + «ВСЕГО по смете» (Σ уже в трассе, не пересчёт)."""
    for label, key in (("Итого прямые затраты по смете", "direct"), ("В том числе ФОТ", "fot"),
                       ("Накладные расходы", "nr"), ("Сметная прибыль", "sp")):
        put(r, 3, label, font=S["bold"])
        put(r, 14, _f(summary.get(key, 0)), font=S["bold"], num=True)
        _border_row(ws, S, r, fill=S["fill_total"])
        r += 1
    put(r, 3, "ВСЕГО по смете", font=S["bold"])
    put(r, 14, _f(summary.get("total", 0)), font=S["bold"], num=True)
    _border_row(ws, S, r, fill=S["fill_grand"])
    return r + 1


def _finalize(ws, head_r: int) -> None:
    """Ширины граф + закрепление шапки таблицы."""
    import openpyxl

    for c, w in _WIDTHS.items():
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=head_r + 1, column=1)


def _new_sheet():
    """Новая книга + лист «ЛСР (Прил.4)» + стили + `put`."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ЛСР (Прил.4)"
    S = _styles()
    return wb, ws, S, _make_put(ws, S)


def render_trace_xlsx(trace: dict[str, Any], out_path: str | Path, *,
                      title: str | None = None, meta: Optional[dict[str, Any]] = None) -> Path:
    """Трасса ОДНОЙ позиции → XLSX по форме Приложения 4 к 421/пр (стиль ГРАНД). Возвращает путь."""
    meta = meta or {}
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb, ws, S, put = _new_sheet()
    head_r = _header_block(ws, put, S, name=trace.get("name", ""),
                           summary=trace.get("summary", {}) or {}, meta=meta)
    _table_header(ws, put, S, head_r)
    _position_rows(ws, put, S, trace.get("rows", []), head_r + 1, 0)
    _finalize(ws, head_r)
    wb.save(path)
    return path


def render_lsr_xlsx(lsr: dict[str, Any], out_path: str | Path, *,
                    title: str | None = None, meta: Optional[dict[str, Any]] = None) -> Path:
    """Многопозиционная ЛСР (``build_lsr_trace``) → XLSX по форме Приложения 4: шапка с общим итогом +
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
    multi = len(sections) > 1
    for idx, sec in enumerate(sections, 1):
        sec_name = str(sec.get("section", "") or "")
        show_sec = multi or (sec_name and sec_name != "Без раздела")
        if show_sec:
            r = _section_title(ws, put, S, r, idx, sec_name)
        for trace in sec.get("positions", []) or []:
            r, pp = _position_rows(ws, put, S, trace.get("rows", []), r, pp)
        if show_sec:
            r = _section_subtotal(ws, put, S, r, idx, sec.get("total", 0))
    _grand_summary(ws, put, S, r, summary)
    _finalize(ws, head_r)
    wb.save(path)
    return path
