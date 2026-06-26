"""Рендерер РИМ-трассы ЛСР в XLSX по форме Приложения 3 к Методике 421/пр.

НЕ калькулятор и НЕ замена lsr_assembly_service: берёт ГОТОВУЮ трассу
(``rim_lsr_trace_service.build_position_trace``) и раскладывает её строки по графам 1-12 формы +
колонка «Источник / основание» (происхождение граф 8-10: ФГИС ЦС тек./база×индекс, явная, КАЦ, нет цены).
Итоговые группы (ОТ/ЭМ/ОТм/М/прямые/ФОТ/НР/СП/итог) уже присутствуют в trace.rows — рендерим как есть. 0 LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Графы формы Приложения 3 (ресурсный метод). Ключ — номер графы в trace.columns (строки str).
_GRAPHS: list[tuple[str, str]] = [
    ("1", "№ п/п"),
    ("2", "Шифр, № норматива / код ресурса"),
    ("3", "Наименование работ и затрат"),
    ("4", "Ед. изм."),
    ("5", "Кол-во на ед."),
    ("6", "Коэф."),
    ("7", "Кол-во всего"),
    ("8", "Цена баз., руб."),
    ("9", "Индекс / коэф. пересч."),
    ("10", "Цена тек., руб."),
    ("11", "Множитель"),
    ("12", "Стоимость, руб."),
]

_SOURCE_RU = {
    "gesn": "ГЭСН (норма)",
    "coefficient": "коэффициент",
    "fgis_current": "ФГИС ЦС (текущая)",
    "fgis_base_index": "ФГИС ЦС (база×индекс)",
    "manual": "явная цена",
    "kac": "КАЦ",
    "missing": "нет цены",
    "Пр/812": "НР (Приказ 812/пр)",
    "Пр/774": "СП (Приказ 774/пр)",
}

# Строки-итоги/группы (жирные, с заливкой); № п/п им не присваивается.
_GROUP_TYPES = {
    "group_labor", "group_machine", "group_machinist", "group_material",
    "direct_total", "fot", "nr", "sp", "position_total",
}
_NUM_GRAPHS = {"5", "6", "7", "8", "9", "10", "11", "12"}
_COL_WIDTHS = {"A": 6, "B": 22, "C": 46, "D": 9, "E": 11, "F": 8, "G": 11,
               "H": 13, "I": 13, "J": 13, "K": 10, "L": 15, "M": 24}


def render_trace_xlsx(trace: dict[str, Any], out_path: str | Path, *, title: str | None = None) -> Path:
    """Трасса одной позиции → XLSX по форме Приложения 3 к 421/пр. Возвращает путь к файлу."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Приложение 3"

    code = trace.get("code", "")
    name = trace.get("name", "")
    unit = trace.get("unit", "")
    qty = trace.get("qty", "")
    ws.append([title or "Локальный сметный расчёт (РИМ) — форма Приложения 3 к Методике 421/пр"])
    ws.append([f"Позиция: {code} — {name}"])
    ws.append([f"Единица: {unit}", "", f"Объём: {qty}"])
    ws.append([])

    headers = [label for _, label in _GRAPHS] + ["Источник / основание"]
    ws.append(headers)
    header_row = ws.max_row
    thin = Side(style="thin", color="B0B8C0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for cell in ws[header_row]:
        cell.font = Font(bold=True, size=9)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = border

    pp = 0
    for row in trace.get("rows", []):
        cols = row.get("columns", {})
        rtype = row.get("type", "")
        n: Any = ""
        if rtype == "work":
            pp += 1
            n = pp
        line: list[Any] = []
        for key, _ in _GRAPHS:
            if key == "1":
                line.append(n)
            elif key == "3":
                line.append(cols.get("3") or row.get("label", ""))
            else:
                line.append(cols.get(key, ""))
        line.append(_SOURCE_RU.get(row.get("source", ""), row.get("source", "")))
        ws.append(line)
        r = ws.max_row
        is_group = rtype in _GROUP_TYPES
        for idx, cell in enumerate(ws[r]):
            cell.border = border
            cell.font = Font(bold=is_group, size=9)
            col_key = _GRAPHS[idx][0] if idx < len(_GRAPHS) else None
            if col_key in _NUM_GRAPHS and isinstance(cell.value, (int, float)):
                cell.number_format = "0.000000" if col_key == "9" else "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            if is_group:
                cell.fill = PatternFill("solid", fgColor="F2F6FA")

    for letter, width in _COL_WIDTHS.items():
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = f"A{header_row + 1}"
    wb.save(path)
    return path
