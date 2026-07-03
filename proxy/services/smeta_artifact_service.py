"""Build user-facing smeta artifacts from model-written estimate answers.

The service is intentionally shallow: it does not choose works, norms, rates or
quantities.  It only extracts Markdown tables already produced by the estimator
model, computes visible table totals, and prepares a separate artifact payload.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proxy.services.estimate_math_service import parse_ru_number


@dataclass(frozen=True)
class SmetaTable:
    title: str
    kind: str
    headers: list[str]
    rows: list[list[str]]
    markdown: str
    amount_total: float | None = None


_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_MONEY_HEADER_TOKENS = ("сумм", "стоим", "итого", "руб")
_LSR_FORM_HEADERS = {
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
_LSR_FORM_MAX_COL = 12


def _split_cells(line: str) -> list[str]:
    text = str(line or "").strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_table_header(line: str, next_line: str) -> bool:
    return "|" in str(line or "") and bool(_SEPARATOR_RE.match(str(next_line or "")))


def _clean_title(line: str) -> str:
    text = str(line or "").strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = text.strip("*").strip()
    return text


def _nearest_title(lines: list[str], start: int) -> str:
    for idx in range(start - 1, max(-1, start - 8), -1):
        text = lines[idx].strip()
        if not text:
            continue
        if text.startswith("|"):
            continue
        if text.startswith("#") or text.startswith("**"):
            return _clean_title(text)
        if len(text) <= 90:
            return _clean_title(text)
    return "Сметная таблица"


def _classify_table(headers: list[str], title: str) -> str:
    joined = " ".join([title, *headers]).casefold()
    if "поставка" in joined or "материал" in joined and "работ" not in joined:
        return "supply"
    if "развилк" in joined or "вариант" in joined and "объ" in joined:
        return "quantity_conflict"
    if ("рим" in joined and "рын" in joined) or "гэсн" in joined and "рын" in joined:
        return "method_comparison"
    if any(token in joined for token in ("сумм", "стоим", "ставк", "руб")):
        return "work_cost"
    if any(token in joined for token in ("работ", "вор", "ед.", "кол-во", "количество")):
        return "bor"
    return "table"


def _amount_column_indexes(headers: list[str]) -> list[int]:
    out: list[int] = []
    for idx, header in enumerate(headers):
        low = header.casefold()
        if "ставк" in low or "цена" in low and "итого" not in low:
            continue
        if any(token in low for token in _MONEY_HEADER_TOKENS):
            out.append(idx)
    return out


def _parse_money_cell(cell: str) -> float | None:
    text = str(cell or "")
    if not re.search(r"\d", text):
        return None
    value = parse_ru_number(text.replace("**", ""))
    if value is None:
        return None
    return float(value)


def _table_amount_total(headers: list[str], rows: list[list[str]]) -> float | None:
    indexes = _amount_column_indexes(headers)
    if not indexes:
        return None
    total = 0.0
    found = False
    for row in rows:
        first = row[0].casefold() if row else ""
        if "итого" in first or "всего" in first:
            continue
        row_value: float | None = None
        for idx in indexes:
            if idx < len(row):
                parsed = _parse_money_cell(row[idx])
                if parsed is not None:
                    row_value = parsed
        if row_value is not None:
            total += row_value
            found = True
    return total if found else None


def _find_header_index(headers: list[str], *tokens: str) -> int | None:
    for idx, header in enumerate(headers):
        low = str(header or "").casefold()
        if all(token in low for token in tokens):
            return idx
    return None


def _first_index(*values: int | None) -> int | None:
    for value in values:
        if value is not None:
            return value
    return None


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return str(row[idx] or "").strip()


def _looks_total_row(row: list[str]) -> bool:
    first = str(row[0] if row else "").casefold()
    return "итого" in first or "всего" in first


def _normative_basis(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(
        r"(ГЭСН(?:м|мр|п|р)?\s*\d{1,2}[-–]\d{2}[-–]\d{3}[-–]\d{2}|"
        r"ГЭСН(?:м|мр|п|р)?\s*\d{1,2}|"
        r"ФЕР(?:м|мр|п|р)?\s*\d{1,2}[-–]\d{2}[-–]\d{3}[-–]\d{2})",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(1).replace("–", "-") if match else text


def _lsr_rows_from_table(table: SmetaTable) -> list[dict[str, Any]]:
    headers = table.headers
    work_idx = _first_index(
        _find_header_index(headers, "работ"),
        _find_header_index(headers, "наименование"),
        _find_header_index(headers, "раздел"),
    )
    qty_idx = _first_index(_find_header_index(headers, "кол"), _find_header_index(headers, "объ"))
    unit_idx = _find_header_index(headers, "ед")
    basis_idx = _first_index(
        _find_header_index(headers, "норма"),
        _find_header_index(headers, "гэсн"),
        _find_header_index(headers, "источник"),
        _find_header_index(headers, "рим"),
    )
    price_idx = _first_index(_find_header_index(headers, "ставк"), _find_header_index(headers, "цена"))
    amount_indexes = _amount_column_indexes(headers)
    status_idx = _first_index(
        _find_header_index(headers, "статус"),
        _find_header_index(headers, "коммент"),
        _find_header_index(headers, "источник"),
    )
    out: list[dict[str, Any]] = []
    for row in table.rows:
        if not row or _looks_total_row(row):
            continue
        title = _cell(row, work_idx)
        if not title and len(row) > 1:
            title = _cell(row, 1)
        amount: float | None = None
        for idx in amount_indexes:
            if idx < len(row):
                parsed = _parse_money_cell(row[idx])
                if parsed is not None:
                    amount = parsed
        if not title and amount is None:
            continue
        out.append(
            {
                "basis": _normative_basis(_cell(row, basis_idx)),
                "title": title or "Позиция сметы",
                "unit": _cell(row, unit_idx),
                "quantity": _cell(row, qty_idx),
                "unit_price": _cell(row, price_idx),
                "amount": amount,
                "status": _cell(row, status_idx) or table.title,
                "source_table": table.title,
            }
        )
    return out


def _select_lsr_source_tables(tables: list[SmetaTable]) -> list[SmetaTable]:
    """Pick the visible table(s) that should feed the display LSR form.

    The model may output both a detailed work-cost table and a shorter
    "preliminary LSR" table. Those are alternate presentations of the same
    estimate, not additive sections. Keep the artifact renderer shallow: select
    the most complete visible cost table and do not merge duplicate forms.
    """
    candidates = [table for table in tables if table.kind in {"work_cost", "method_comparison"}]
    if not candidates:
        return []
    explicit_lsr = [table for table in candidates if "лср" in table.title.casefold()]
    non_lsr = [table for table in candidates if table not in explicit_lsr]
    if explicit_lsr and not non_lsr:
        return [max(explicit_lsr, key=lambda table: (len(table.rows), table.amount_total or 0.0))]
    if explicit_lsr and non_lsr:
        best_non_lsr = max(non_lsr, key=lambda table: (len(table.rows), table.amount_total or 0.0))
        best_lsr = max(explicit_lsr, key=lambda table: (len(table.rows), table.amount_total or 0.0))
        if len(best_lsr.rows) >= len(best_non_lsr.rows):
            return [best_lsr]
        return [best_non_lsr]
    return [max(candidates, key=lambda table: (len(table.rows), table.amount_total or 0.0))]


def build_lsr_form(tables: list[SmetaTable]) -> dict[str, Any] | None:
    """Build an LSR-shaped output view from model-written cost tables.

    This is a display form only: no works, norms, quantities or prices are
    invented here. Rows are copied from visible estimate tables.
    """
    rows: list[dict[str, Any]] = []
    source_tables = _select_lsr_source_tables(tables)
    for table in source_tables:
        rows.extend(_lsr_rows_from_table(table))
    if not rows:
        return None
    total = sum(float(row["amount"] or 0.0) for row in rows if row.get("amount") is not None)
    status_blob = " ".join(str(row.get("status") or "") for row in rows).casefold()
    scenario_like = any(token in status_blob for token in ("scenario", "сценар", "допущ"))
    return {
        "schema": "lsr_rim_display_form_v1",
        "title": "Локальный сметный расчет (смета)",
        "note": (
            "Предварительная ЛСР-форма по видимым строкам сметного ответа. "
            "Код не добавляет позиции, не выбирает нормы и не придумывает ставки. "
            "Без расчетной трассы РИМ/ресурсов/цен это не финальная ЛСР по Приложению №3."
        ),
        "finality": "scenario_display" if scenario_like else "display_form",
        "is_priced_final": False,
        "headers": [str(_LSR_FORM_HEADERS.get(col, "")) for col in range(1, _LSR_FORM_MAX_COL + 1)],
        "rows": rows,
        "source_tables": [table.title for table in source_tables],
        "amount_total": total if total > 0 else None,
    }


def _lsr_markdown(lsr_form: dict[str, Any] | None) -> list[str]:
    if not lsr_form:
        return []
    lines = [
        "## ЛСР РИМ (форма 421/пр)",
        "",
        "Приложение № 3 к Методике (приказ Минстроя России от 04.08.2020 № 421/пр)",
        "",
        "**ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ (СМЕТА) № ____**",
        "",
        str(lsr_form.get("title") or "Локальный сметный расчет (смета)"),
        "",
        "Составлен ресурсным методом / сценарной формой выдачи по видимым строкам ответа.",
        "",
        str(lsr_form.get("note") or ""),
        "",
    ]
    if lsr_form.get("amount_total") is not None:
        lines += [
            f"Сметная стоимость: **{_fmt_money(float(lsr_form['amount_total']))}**",
            "",
        ]
    lines += [
        "| № п/п | Обоснование | Наименование работ и затрат | Ед. изм. | Кол-во на ед. | коэф. | Кол-во всего | Базис на ед., руб. | Индекс | Текущий на ед., руб. | коэф. | Текущий всего, руб. |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        "| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |",
    ]
    for idx, row in enumerate(lsr_form.get("rows") or [], 1):
        amount = _fmt_money(float(row["amount"])) if row.get("amount") is not None else ""
        cells = [
            str(idx),
            str(row.get("basis") or ""),
            str(row.get("title") or ""),
            str(row.get("unit") or ""),
            str(row.get("quantity") or ""),
            "1",
            str(row.get("quantity") or ""),
            "",
            "",
            str(row.get("unit_price") or ""),
            "1",
            amount,
        ]
        lines.append("| " + " | ".join(cell.replace("|", "/") for cell in cells) + " |")
    if lsr_form.get("amount_total") is not None:
        lines.append(
            f"|  |  | **ВСЕГО по смете** |  |  |  |  |  |  |  |  | **{_fmt_money(float(lsr_form['amount_total']))}** |"
        )
    source_rows = [
        row for row in (lsr_form.get("rows") or [])
        if str(row.get("status") or row.get("source_table") or "").strip()
    ]
    if source_rows:
        lines += [
            "",
            "**Источники и статус строк**",
            "",
            "| № п/п | Источник / статус | Исходная таблица |",
            "|---:|---|---|",
        ]
        for idx, row in enumerate(source_rows, 1):
            lines.append(
                "| "
                + " | ".join(
                    str(cell or "").replace("|", "/")
                    for cell in (idx, row.get("status") or "", row.get("source_table") or "")
                )
                + " |"
            )
    return lines


def _fmt_money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " руб."


def _safe_sheet_title(title: str, used: set[str]) -> str:
    text = re.sub(r"[\[\]:*?/\\]", " ", str(title or "Таблица")).strip() or "Таблица"
    text = re.sub(r"\s+", " ", text)[:31]
    base = text or "Таблица"
    candidate = base
    idx = 2
    while candidate in used:
        suffix = f" {idx}"
        candidate = (base[: 31 - len(suffix)] + suffix).strip()
        idx += 1
    used.add(candidate)
    return candidate


def extract_smeta_tables(answer: str) -> list[SmetaTable]:
    """Extract Markdown tables from a smeta answer without interpreting domain logic."""
    lines = str(answer or "").splitlines()
    tables: list[SmetaTable] = []
    idx = 0
    while idx < len(lines) - 1:
        if not _is_table_header(lines[idx], lines[idx + 1]):
            idx += 1
            continue
        start = idx
        idx += 2
        while idx < len(lines) and "|" in lines[idx]:
            idx += 1
        raw = lines[start:idx]
        headers = _split_cells(raw[0])
        rows = [_split_cells(line) for line in raw[2:] if line.strip()]
        title = _nearest_title(lines, start)
        kind = _classify_table(headers, title)
        tables.append(SmetaTable(
            title=title,
            kind=kind,
            headers=headers,
            rows=rows,
            markdown="\n".join(raw),
            amount_total=_table_amount_total(headers, rows),
        ))
    return tables


def build_smeta_artifact(answer: str, *, question: str = "") -> dict[str, Any] | None:
    """Return a Markdown artifact payload for visible smeta tables, if any."""
    tables = extract_smeta_tables(answer)
    if not tables:
        return None
    lsr_form = build_lsr_form(tables)
    lines = ["# Сметный артефакт", ""]
    if question:
        lines += ["## Запрос", str(question).strip(), ""]
    lines += [
        "## Свод таблиц",
        "| Таблица | Тип | Строк | Сумма по видимым строкам |",
        "|---|---|---:|---:|",
    ]
    for table in tables:
        amount = _fmt_money(table.amount_total) if table.amount_total is not None else ""
        lines.append(f"| {table.title} | {table.kind} | {len(table.rows)} | {amount} |")
    if lsr_form:
        lines += ["", *_lsr_markdown(lsr_form)]
    for num, table in enumerate(tables, start=1):
        lines += ["", f"## {num}. {table.title}", "", table.markdown]
    total = lsr_form.get("amount_total") if lsr_form else None
    if total is not None and total > 0:
        source_tables = ", ".join(str(x) for x in (lsr_form.get("source_tables") or []) if x) if lsr_form else ""
        source_note = f" Источник ЛСР: {source_tables}." if source_tables else ""
        lines += ["", "## Арифметика", f"Сумма выбранной ЛСР-формы: **{_fmt_money(total)}**.{source_note}"]
    return {
        "mode": "markdown",
        "title": "Сметный артефакт",
        "content": "\n".join(lines).strip(),
        "tables": [
            {
                "title": table.title,
                "kind": table.kind,
                "rows": len(table.rows),
                "amount_total": table.amount_total,
                "headers": table.headers,
                "data": table.rows,
            }
            for table in tables
        ],
        **({"lsr_form": lsr_form, "rim_lsr_form": lsr_form} if lsr_form else {}),
    }


def persist_smeta_artifact_exports(
    artifact: dict[str, Any] | None,
    *,
    output_dir: str | Path = "storage/smeta_artifacts",
    prefix: str = "smeta_artifact",
) -> dict[str, Any] | None:
    """Write XLSX and CSV downloads for an already built smeta artifact.

    The export preserves model-written tables.  It does not add works, choose
    norms, change rates, or recalculate hidden positions.
    """
    if not artifact:
        return None
    tables = [t for t in artifact.get("tables") or [] if t.get("headers") and t.get("data")]
    if not tables:
        return artifact

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    import time

    stamp = int(time.time() * 1000)
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("_") or "smeta_artifact"
    xlsx_name = f"{safe_prefix}_{stamp}.xlsx"
    csv_name = f"{safe_prefix}_{stamp}.csv"
    xlsx_path = out_dir / xlsx_name
    csv_path = out_dir / csv_name

    import openpyxl

    wb = openpyxl.Workbook()
    summary_ws = wb.active
    summary_ws.title = "Свод"
    summary_ws.append(["Таблица", "Тип", "Строк", "Сумма по видимым строкам"])
    for table in tables:
        summary_ws.append([
            table.get("title") or "",
            table.get("kind") or "",
            table.get("rows") or 0,
            table.get("amount_total") or "",
        ])
    used = {"Свод"}
    lsr_form = artifact.get("rim_lsr_form") if isinstance(artifact.get("rim_lsr_form"), dict) else None
    if not lsr_form:
        lsr_form = artifact.get("lsr_form") if isinstance(artifact.get("lsr_form"), dict) else None
    if lsr_form:
        ws = wb.create_sheet("ЛСР РИМ")
        from openpyxl.utils import get_column_letter
        from openpyxl.styles import Alignment, Font, PatternFill, Side, Border

        max_col = _LSR_FORM_MAX_COL
        title_fill = PatternFill(fill_type="solid", fgColor="F2F6FA")
        header_fill = PatternFill(fill_type="solid", fgColor="D9EAF7")
        total_fill = PatternFill(fill_type="solid", fgColor="CFE2F3")
        note_fill = PatternFill(fill_type="solid", fgColor="FFF2CC")
        thin = Side(style="thin", color="B7C9D6")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        def put(row: int, col: int, value: Any, *, bold: bool = False, size: int = 9, align: str = "left") -> None:
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = Font(bold=bold, size=size)
            cell.alignment = Alignment(horizontal=align, vertical="top", wrap_text=True)

        put(1, 10, "Приложение № 3", size=8, align="right")
        put(2, 8, "к Методике (приказ Минстроя России от 04.08.2020 № 421/пр)", size=8, align="right")
        ws.merge_cells(start_row=2, start_column=8, end_row=2, end_column=12)
        put(4, 1, "(наименование стройки)", size=8)
        put(5, 1, "(наименование объекта капитального строительства)", size=8)
        put(7, 1, "ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЁТ (СМЕТА) № ____", bold=True, size=11, align="center")
        ws.merge_cells(start_row=7, start_column=1, end_row=7, end_column=max_col)
        put(8, 1, str(lsr_form.get("title") or "Локальный сметный расчет (смета)"), align="center")
        ws.merge_cells(start_row=8, start_column=1, end_row=8, end_column=max_col)
        put(9, 1, "Составлен ресурсным методом / сценарной формой выдачи по видимым строкам ответа", size=8)
        ws.merge_cells(start_row=9, start_column=1, end_row=9, end_column=max_col)
        put(10, 1, str(lsr_form.get("note") or ""), size=8)
        ws.merge_cells(start_row=10, start_column=1, end_row=10, end_column=max_col)
        ws.cell(row=10, column=1).fill = note_fill
        put(12, 1, "Сметная стоимость", bold=True)
        if lsr_form.get("amount_total") is not None:
            put(12, 4, float(lsr_form.get("amount_total") or 0), bold=True, align="right")
            ws.cell(row=12, column=4).number_format = '# ##0'
        put(12, 6, "руб.", size=8)

        header_row = 15
        number_row = 16
        for col in range(1, max_col + 1):
            header = _LSR_FORM_HEADERS.get(col, "")
            cell = ws.cell(row=header_row, column=col, value=header)
            cell.font = Font(bold=True, size=9)
            cell.fill = header_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            num_cell = ws.cell(row=number_row, column=col, value=col)
            num_cell.font = Font(size=8)
            num_cell.fill = header_fill
            num_cell.border = border
            num_cell.alignment = Alignment(horizontal="center", vertical="center")

        data_start = number_row + 1
        for idx, row in enumerate(lsr_form.get("rows") or [], 1):
            row_idx = data_start + idx - 1
            ws.cell(row=row_idx, column=1, value=idx)
            ws.cell(row=row_idx, column=2, value=row.get("basis") or "")
            ws.cell(row=row_idx, column=3, value=row.get("title") or "")
            ws.cell(row=row_idx, column=4, value=row.get("unit") or "")
            ws.cell(row=row_idx, column=5, value=row.get("quantity") or "")
            ws.cell(row=row_idx, column=6, value=1)
            ws.cell(row=row_idx, column=7, value=row.get("quantity") or "")
            ws.cell(row=row_idx, column=10, value=row.get("unit_price") or "")
            ws.cell(row=row_idx, column=11, value=1)
            ws.cell(row=row_idx, column=12, value=row.get("amount") if row.get("amount") is not None else "")
        if lsr_form.get("amount_total") is not None:
            total_row = data_start + len(lsr_form.get("rows") or [])
            ws.cell(row=total_row, column=3, value="ВСЕГО по смете")
            ws.cell(row=total_row, column=12, value=lsr_form.get("amount_total"))
            ws.cell(row=total_row, column=12).number_format = '# ##0'
            for col in range(1, max_col + 1):
                ws.cell(row=total_row, column=col).fill = total_fill
                ws.cell(row=total_row, column=col).font = Font(bold=True, size=9)

        for row_idx in range(4, 13):
            for col in range(1, max_col + 1):
                ws.cell(row=row_idx, column=col).fill = title_fill
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=max_col):
            for cell in row:
                cell.border = border
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for row_idx in range(data_start, ws.max_row + 1):
            ws.cell(row=row_idx, column=12).number_format = '# ##0'
        ws.freeze_panes = ws.cell(row=data_start, column=1)
        ws.auto_filter.ref = f"A{header_row}:{ws.cell(row=ws.max_row, column=max_col).coordinate}"
        widths = {1: 6, 2: 18, 3: 48, 4: 9, 5: 12, 6: 7, 7: 12, 8: 16, 9: 9, 10: 18, 11: 7, 12: 18}
        for col_idx, width in widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        src_ws = wb.create_sheet("Источники ЛСР")
        src_ws.append(["№ п/п", "Источник / статус", "Исходная таблица", "Обоснование", "Наименование работ и затрат"])
        for idx, row in enumerate(lsr_form.get("rows") or [], 1):
            src_ws.append([
                idx,
                row.get("status") or "",
                row.get("source_table") or "",
                row.get("basis") or "",
                row.get("title") or "",
            ])
        for column_cells in src_ws.columns:
            width = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 80)
            src_ws.column_dimensions[column_cells[0].column_letter].width = width
        used.add("ЛСР РИМ")
        used.add("Источники ЛСР")
    for table in tables:
        ws = wb.create_sheet(_safe_sheet_title(str(table.get("title") or "Таблица"), used))
        ws.append([str(h) for h in table.get("headers") or []])
        for row in table.get("data") or []:
            ws.append([str(cell) for cell in row])
        for column_cells in ws.columns:
            width = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 60)
            ws.column_dimensions[column_cells[0].column_letter].width = width
    wb.save(xlsx_path)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh, delimiter=";")
        if lsr_form:
            writer.writerow(["ЛСР РИМ (форма 421/пр)"])
            writer.writerow([_LSR_FORM_HEADERS.get(col, "") for col in range(1, _LSR_FORM_MAX_COL + 1)])
            writer.writerow([col for col in range(1, _LSR_FORM_MAX_COL + 1)])
            for idx, row in enumerate(lsr_form.get("rows") or [], 1):
                csv_row = [""] * _LSR_FORM_MAX_COL
                csv_row[0] = idx
                csv_row[1] = row.get("basis") or ""
                csv_row[2] = row.get("title") or ""
                csv_row[3] = row.get("unit") or ""
                csv_row[4] = row.get("quantity") or ""
                csv_row[5] = 1
                csv_row[6] = row.get("quantity") or ""
                csv_row[9] = row.get("unit_price") or ""
                csv_row[10] = 1
                csv_row[11] = row.get("amount") if row.get("amount") is not None else ""
                writer.writerow(csv_row)
            if lsr_form.get("amount_total") is not None:
                csv_row = [""] * _LSR_FORM_MAX_COL
                csv_row[2] = "ВСЕГО по смете"
                csv_row[11] = lsr_form.get("amount_total")
                writer.writerow(csv_row)
            writer.writerow([])
            writer.writerow(["Источники ЛСР"])
            writer.writerow(["№ п/п", "Источник / статус", "Исходная таблица", "Обоснование", "Наименование работ и затрат"])
            for idx, row in enumerate(lsr_form.get("rows") or [], 1):
                writer.writerow([
                    idx,
                    row.get("status") or "",
                    row.get("source_table") or "",
                    row.get("basis") or "",
                    row.get("title") or "",
                ])
            writer.writerow([])
        for table in tables:
            writer.writerow([str(table.get("title") or "Таблица")])
            writer.writerow([str(h) for h in table.get("headers") or []])
            for row in table.get("data") or []:
                writer.writerow([str(cell) for cell in row])
            writer.writerow([])

    artifact = dict(artifact)
    artifact["downloads"] = {
        "xlsx": f"/api/smeta-artifacts/download?path={xlsx_name}",
        "csv": f"/api/smeta-artifacts/download?path={csv_name}",
    }
    artifact["files"] = {
        "xlsx_path": str(xlsx_path),
        "csv_path": str(csv_path),
    }
    return artifact


def compact_smeta_answer(answer: str, artifact: dict[str, Any] | None) -> str:
    """Keep chat readable when the answer contains long estimate tables.

    Short tables stay in the chat. Long tables are replaced with a short marker;
    the full table remains in the artifact payload.
    """
    if not artifact:
        return answer
    tables = extract_smeta_tables(answer)
    if not tables or sum(len(table.rows) for table in tables) < 5:
        return answer

    result_lines: list[str] = []
    lsr_form = artifact.get("rim_lsr_form") if isinstance(artifact.get("rim_lsr_form"), dict) else None
    if not lsr_form:
        lsr_form = artifact.get("lsr_form") if isinstance(artifact.get("lsr_form"), dict) else None
    if lsr_form and lsr_form.get("rows"):
        rows_count = len(lsr_form.get("rows") or [])
        amount = f", сумма {_fmt_money(float(lsr_form['amount_total']))}" if lsr_form.get("amount_total") is not None else ""
        source_tables = ", ".join(str(x) for x in (lsr_form.get("source_tables") or []) if x)
        source_note = f" Источник: {source_tables}." if source_tables else ""
        result_lines.extend([
            f"ЛСР-форма вынесена в артефакт/XLSX: {rows_count} строк{amount}.",
            f"Проверка строк артефакта имеет приоритет над ручным итогом в тексте ответа.{source_note}",
            "Исходные таблицы ниже сокращены в чате, полная форма и источники лежат в артефакте.",
            "",
        ])
    lines = str(answer or "").splitlines()
    idx = 0
    table_num = 0
    while idx < len(lines):
        if idx < len(lines) - 1 and _is_table_header(lines[idx], lines[idx + 1]):
            start = idx
            idx += 2
            while idx < len(lines) and "|" in lines[idx]:
                idx += 1
            table = tables[table_num] if table_num < len(tables) else None
            table_num += 1
            if table and len(table.rows) >= 4:
                amount = f", сумма строк {_fmt_money(table.amount_total)}" if table.amount_total is not None else ""
                result_lines.append(f"Таблица вынесена в артефакт: {table.title} ({len(table.rows)} строк{amount}).")
            else:
                result_lines.extend(lines[start:idx])
            continue
        result_lines.append(lines[idx])
        idx += 1
    compacted = "\n".join(result_lines)
    compacted = re.sub(r"\n{3,}", "\n\n", compacted).strip()
    return compacted or answer
