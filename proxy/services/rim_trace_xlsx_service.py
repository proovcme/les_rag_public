"""Рендерер РИМ-трассы ЛСР в XLSX по форме **Приложения № 4** к Методике 421/пр (форма ГРАНД-Сметы).

НЕ калькулятор: берёт ГОТОВУЮ трассу (``rim_lsr_trace_service.build_position_trace``) и раскладывает её
строки по графам формы ЛСР (как эталон ГРАНД-Сметы): шапка (стройка/объект/наименование/ресурсный метод/
уровень цен/субъект + сметная стоимость и её разбивка) + таблица позиций/ресурсов по графам 1-13 + свод
(прямые/ФОТ/НР/СП/Всего). 0 LLM.

Графы формы (эталон): № п/п · Обоснование · Наименование · Ед.изм. · Кол-во (на ед./коэф./всего) ·
Сметная стоимость (на ед./коэф./всего). Колонки trace.columns 2-12 ложатся на них напрямую.
ЛСР = Приложение № 4 (Прил.3 = объектный расчёт) — прежний ярлык «Приложение 3» исправлен.
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


def render_trace_xlsx(trace: dict[str, Any], out_path: str | Path, *,
                      title: str | None = None, meta: Optional[dict[str, Any]] = None) -> Path:
    """Трасса позиции → XLSX по форме Приложения 4 к 421/пр (стиль ГРАНД). Возвращает путь."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    meta = meta or {}
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ЛСР (Прил.4)"

    rows = trace.get("rows", [])
    summary = trace.get("summary", {}) or {}
    code = trace.get("code", "")
    name = trace.get("name", "")
    unit = trace.get("unit", "")
    qty = trace.get("qty", "")
    # нормативные затраты труда (чел.-ч) — из групп-строк трассы
    def _grp_qty(t: str) -> Any:
        for r in rows:
            if r.get("type") == t:
                return (r.get("columns") or {}).get("7", "")
        return ""

    thin = Side(style="thin", color="B0B8C0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    bold = Font(bold=True, size=9)
    small = Font(size=9)
    dim = Font(size=8, color="606060")

    def _put(r: int, c: int, v: Any, *, font: Font = small, num: bool = False, align: str = "left"):
        cell = ws.cell(row=r, column=c, value=v)
        cell.font = font
        if num and isinstance(v, (int, float)):
            cell.number_format = "#,##0.00"
            cell.alignment = Alignment(horizontal="right")
        else:
            cell.alignment = Alignment(horizontal=align, vertical="top", wrap_text=(c == 3))
        return cell

    # ── ШАПКА формы ───────────────────────────────────────────────────────────
    r = 1
    _put(r, 12, "Приложение № 4", font=dim, align="right"); r += 1
    _put(r, 12, "к Методике (приказ Минстроя России от 04.08.2020 № 421/пр)", font=dim, align="right"); r += 2
    _put(r, 1, meta.get("stroika", "(наименование стройки)"), font=dim); r += 1
    _put(r, 1, meta.get("object", "(наименование объекта капитального строительства)"), font=dim); r += 2
    _put(r, 1, "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ (СМЕТА) № " + str(meta.get("lsr_no", "____")), font=bold); r += 1
    _put(r, 1, name or "(наименование работ и затрат)", font=small); r += 1
    _put(r, 1, "Составлен ресурсным методом", font=dim); r += 1
    _put(r, 1, "Основание: " + str(meta.get("osnovanie", "—")), font=dim); r += 1
    _put(r, 1, "Составлен(а) в текущем уровне цен: " + str(meta.get("price_level", "—")), font=dim); r += 1
    _put(r, 1, "Наименование субъекта РФ: " + str(meta.get("subject", "—")), font=dim); r += 2
    total = summary.get("total", 0)
    _put(r, 1, "Сметная стоимость", font=bold); _put(r, 4, total, font=bold, num=True); _put(r, 6, "руб.", font=dim); r += 1
    _put(r, 1, "  средства на оплату труда рабочих", font=dim); _put(r, 4, summary.get("ozp", 0), font=dim, num=True); r += 1
    _put(r, 1, "  средства на оплату труда машинистов", font=dim); _put(r, 4, summary.get("zpm", 0), font=dim, num=True); r += 1
    _put(r, 1, "  нормативные затраты труда рабочих, чел.-ч", font=dim); _put(r, 4, _grp_qty("group_labor"), font=dim, num=True); r += 1
    _put(r, 1, "  нормативные затраты труда машинистов, чел.-ч", font=dim); _put(r, 4, _grp_qty("group_machinist"), font=dim, num=True); r += 2

    # ── ШАПКА ТАБЛИЦЫ (графы) ─────────────────────────────────────────────────
    head_r = r
    headers = {1: "№ п/п", 2: "Обоснование", 3: "Наименование работ и затрат", 8: "Ед. изм.",
               9: "Кол-во на ед.", 10: "коэф.", 11: "Кол-во всего", 12: "Цена на ед., руб.",
               14: "Стоимость всего, руб."}
    for c, t in headers.items():
        cell = _put(head_r, c, t, font=bold, align="center")
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    r += 1

    # ── СТРОКИ позиции/ресурсов из трассы ─────────────────────────────────────
    pp = 0
    for row in rows:
        cols = row.get("columns", {}) or {}
        rtype = row.get("type", "")
        is_group = rtype in _GROUP_TYPES
        is_total = rtype in _TOTAL_TYPES
        if rtype == "work":
            pp += 1
            _put(r, 1, pp, font=bold, align="center")
        for key, xc in _COL.items():
            if key in cols:
                val = _LABEL_FIX.get(str(cols[key]), cols[key]) if key == "3" else cols[key]
                _put(r, xc, val, font=(bold if is_group else small), num=(xc in _NUM_COLS))
        # наименование группы/итога, если в columns нет "3"
        if "3" not in cols:
            label = row.get("label", "")
            if label:
                _put(r, 3, label, font=(bold if is_group else small))
        for c in range(1, 15):
            cc = ws.cell(row=r, column=c)
            cc.border = border
            if is_total:
                cc.fill = PatternFill("solid", fgColor="F2F6FA")
        r += 1

    # ширины колонок
    widths = {1: 6, 2: 18, 3: 40, 4: 10, 5: 8, 6: 6, 7: 6, 8: 9, 9: 11, 10: 7, 11: 12, 12: 13, 13: 7, 14: 15}
    for c, w in widths.items():
        ws.column_dimensions[openpyxl.utils.get_column_letter(c)].width = w
    ws.freeze_panes = ws.cell(row=head_r + 1, column=1)
    wb.save(path)
    return path
