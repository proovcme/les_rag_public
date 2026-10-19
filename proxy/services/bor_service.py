"""Генератор ведомостей объёмов работ (ВОР) из спецификаций — W11.1 (LES3_PLAN).

ADR-11: ядро без LLM. Источник — нормализованные Parquet-строки табличного
конвейера (backend/parquet_writer.py, STANDARD_SCHEMA) в
storage/datasets/{dataset_id}/_parquet/**.parquet. Группировка, свод
количеств и экспорт в xlsx — детерминированные.
"""

from __future__ import annotations

import logging
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from backend.runtime_paths import mutable_path

from backend.parquet_writer import load_parquet

logger = logging.getLogger(__name__)

# Типы документов, из которых строится ВОР (см. DOC_TYPES в parquet_writer).
BOR_SOURCE_DOC_TYPES = ("SPEC", "VEDOMOST")

# Нормализация единиц измерения: разнобой написания → каноническая форма.
UNIT_ALIASES = {
    "шт": "шт", "шт.": "шт", "штук": "шт", "штука": "шт", "штуки": "шт",
    "компл": "компл", "компл.": "компл", "к-т": "компл", "комплект": "компл", "комплектов": "компл",
    "м": "м", "м.": "м", "метр": "м", "метров": "м",
    "пог.м": "пог.м", "п.м": "пог.м", "п.м.": "пог.м", "пог. м": "пог.м", "пм": "пог.м",
    "м2": "м²", "м²": "м²", "кв.м": "м²", "кв. м": "м²", "кв.м.": "м²",
    "м3": "м³", "м³": "м³", "куб.м": "м³", "куб. м": "м³", "куб.м.": "м³",
    "кг": "кг", "кг.": "кг",
    "т": "т", "т.": "т", "тн": "т", "тонн": "т",
    "л": "л", "л.": "л", "литр": "л", "литров": "л",
}

VOR_PRINT_SHEET = "Ведомость работ"
VOR_PRINT_MARKER = "_LES_VOR_PRINT_VIEW_V1"


def _vor_print_plan(workbook):
    """Derive a presentation only from the complete, unchanged decision register."""
    from proxy.services.lsr_source_coverage_service import canonicalize_row_role
    from proxy.services.vor_result_integrity_service import vor_has_complete_derived_measure, vor_quantity_number

    if "ВОР" not in workbook.sheetnames:
        return None
    register = workbook["ВОР"]
    if [register.cell(3, col).value for col in (1, 2, 3, 4)] != ["№", "Раздел", "Наименование", "Код/Шифр"]:
        return None
    authored = {}
    if register.max_row > 3:
        if "Решения модели" not in workbook.sheetnames:
            return None
        pieces = {}
        for target, _part, literal, *_rest in workbook["Решения модели"].iter_rows(min_row=4, values_only=True):
            if target is not None:
                pieces.setdefault(str(target), []).append(str(literal)[len("JSON: "):])
        try:
            authored = {key: json.loads("".join(value)) for key, value in pieces.items()}
        except (ValueError, RecursionError):
            return None
        if set(authored) != {f"ВОР!R{index}" for index in range(4, register.max_row + 1)}:
            return None
    plan = [
        {"kind": "party", "values": ["Заказчик:", None, None, "Объект:", None]},
        {"kind": "blank", "values": []},
        {"kind": "full", "values": ["Ген. подрядчик:"]},
        {"kind": "title", "values": ["Ведомость объёмов работ"]},
        {"kind": "full", "values": [register["A1"].value if register["A1"].value != "Ведомость объёмов работ" else None]},
        {"kind": "status", "values": [register["A2"].value]},
        {"kind": "columns", "values": ["№ пп", "Наименование", "Ед. изм.", "Кол-во", "Примечание"]},
        {"kind": "numbers", "values": [1, 2, 3, 4, 5]},
    ]
    section, ordinal = "", 0
    for index in range(4, register.max_row + 1):
        decision = authored[f"ВОР!R{index}"]
        role = canonicalize_row_role(decision.get("row_role"))
        if role == "header":
            label = register.cell(index, 3).value
            if label and label != section:
                plan.append({"kind": "section", "values": [label]})
                section, ordinal = label, 0
        if role != "work":
            continue
        label = register.cell(index, 2).value
        if label and label != section:
            plan.append({"kind": "section", "values": [label]})
            section, ordinal = label, 0
        ordinal += 1
        unit, quantity = register.cell(index, 5).value, register.cell(index, 6).value
        notes = []
        for key in ("note", "notes", "comment", "remarks"):
            value = decision.get(key)
            if isinstance(value, str) and value.strip() and value not in notes:
                notes.append(value)
        source_note = register.cell(index, 12).value
        if source_note and source_note not in notes:
            notes.append(str(source_note))
        if vor_has_complete_derived_measure(decision):
            unit, quantity = decision["calc_unit"], vor_quantity_number(decision["calc_quantity"])
            notes.append(str(decision["conversion_source"]))
        if quantity is None:
            notes.append("Объём не указан.")
        if not unit:
            notes.append("Единица измерения не указана.")
        plan.append({"kind": "work", "values": [ordinal, register.cell(index, 3).value,
                    unit, quantity, "\n".join(notes) or None], "target": f"#'ВОР'!C{index}"})
    if not any(row["kind"] == "work" for row in plan):
        plan.append({"kind": "status", "values": ["Работы не сформированы. См. лист «ВОР» и замечания."]})
    plan.extend([{"kind": "blank", "values": []},
                 {"kind": "signature", "values": ["Составил"]},
                 {"kind": "signature", "values": ["Проверил"]}])
    return plan


def _vor_print_merges(plan):
    ranges = []
    for number, row in enumerate(plan, 1):
        if row["kind"] == "party":
            ranges.extend((f"A{number}:C{number}", f"D{number}:E{number}"))
        elif row["kind"] == "signature":
            ranges.extend((f"A{number}:B{number}", f"C{number}:E{number}"))
        elif row["kind"] in {"full", "title", "status", "section"}:
            ranges.append(f"A{number}:E{number}")
    return set(ranges)


def is_verified_vor_print_view(workbook, worksheet) -> bool:
    """A marker alone never excludes an arbitrary or edited source worksheet."""
    marker = workbook.defined_names.get(VOR_PRINT_MARKER)
    if (worksheet.title != VOR_PRINT_SHEET or marker is None
            or marker.attr_text != f"'{VOR_PRINT_SHEET}'!$A$1"):
        return False
    from proxy.services.attachment_source_catalog_service import _is_vor_model_audit

    if ("ВОР" not in workbook.sheetnames
            or (workbook["ВОР"].max_row > 3 and (
                "Решения модели" not in workbook.sheetnames
                or not _is_vor_model_audit(workbook["Решения модели"], workbook)))):
        return False
    plan = _vor_print_plan(workbook)
    if (plan is None or worksheet.max_row != len(plan) or worksheet.max_column != 5
            or {str(value) for value in worksheet.merged_cells.ranges} != _vor_print_merges(plan)):
        return False
    for number, row in enumerate(plan, 1):
        expected = list(row["values"]) + [None] * (5 - len(row["values"]))
        for column, value in enumerate(expected, 1):
            cell = worksheet.cell(number, column)
            target = row.get("target") if column == 2 else None
            if (cell.value != value or cell.data_type == "f"
                    or (cell.hyperlink.target if cell.hyperlink else None) != target):
                return False
    return True


def _add_vor_print_view(workbook):
    """Add the owner's five-column print form without moving canonical row addresses."""
    from math import ceil
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.page import PageMargins
    from openpyxl.workbook.defined_name import DefinedName

    plan = _vor_print_plan(workbook)
    if plan is None:
        return
    view = workbook.create_sheet(VOR_PRINT_SHEET, 0)
    for row in plan:
        view.append(row["values"])
    for value in _vor_print_merges(plan):
        view.merge_cells(value)
    thin = Side(style="thin", color="000000")
    widths = (6, 49, 9, 11, 33)
    for column, width in zip("ABCDE", widths, strict=True):
        view.column_dimensions[column].width = width
    for number, row in enumerate(plan, 1):
        kind = row["kind"]
        lines = 1
        for column, value in enumerate(row["values"], 1):
            cell = view.cell(number, column)
            if isinstance(cell.value, str):
                cell.data_type = "s"
            cell.font = Font(name="Times New Roman", size=12 if kind == "title" else 10,
                             bold=kind in {"party", "title", "columns", "section", "status"})
            cell.alignment = Alignment(wrap_text=True, vertical="top",
                                       horizontal="center" if kind in {"columns", "numbers", "title"}
                                       or (kind == "work" and column in (1, 3, 4)) else "left")
            width = sum(widths) if kind in {"full", "title", "status", "section"} else widths[column - 1]
            lines = max(lines, sum(max(1, ceil(len(line) / max(1, width - 1))) for line in str(value or "").split("\n")))
        view.row_dimensions[number].height = max(16, 13 * lines + 3)
        if kind in {"work", "section", "columns", "numbers"}:
            for cell in view[number]:
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        if kind == "section":
            view.cell(number, 1).fill = PatternFill("solid", fgColor="F2F2F2")
        if kind == "signature":
            view.row_dimensions[number].height = 27
            for column in range(3, 6):
                view.cell(number, column).border = Border(bottom=thin)
        if kind == "work":
            view.cell(number, 2).hyperlink = row["target"]
            view.cell(number, 4).number_format = "General"
    view.freeze_panes = "A9"
    view.sheet_view.showGridLines = False
    view.page_setup.orientation = "portrait"
    view.page_setup.paperSize = view.PAPERSIZE_A4
    view.page_setup.fitToWidth, view.page_setup.fitToHeight = 1, 0
    view.sheet_properties.pageSetUpPr.fitToPage = True
    view.page_margins = PageMargins(left=.3, right=.3, top=.4, bottom=.4)
    view.print_title_rows = "7:8"
    view.print_area = f"A1:E{len(plan)}"
    view.oddFooter.right.text = "Страница &P из &N"
    workbook.defined_names.add(DefinedName(VOR_PRINT_MARKER, attr_text=f"'{VOR_PRINT_SHEET}'!$A$1"))
    workbook.active = 0


def normalize_unit(unit: str | None) -> str:
    if not unit:
        return ""
    cleaned = str(unit).strip().lower().replace("ё", "е")
    return UNIT_ALIASES.get(cleaned, cleaned)


def _normalize_name(name: str) -> str:
    """Ключ группировки: схлопнутые пробелы, без регистра."""
    return re.sub(r"\s+", " ", str(name)).strip().casefold()


@dataclass
class BorLine:
    """Одна строка ВОР — свод одинаковых позиций по всем источникам."""

    section: str
    name: str
    code: str
    mark: str
    unit: str
    qty: float | None          # None — ни в одной исходной строке не было количества
    qty_missing_rows: int = 0  # строк-источников без количества (вошли в свод без суммы)
    source_rows: int = 0
    sources: list[str] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "section": self.section,
            "name": self.name,
            "code": self.code,
            "mark": self.mark,
            "unit": self.unit,
            "qty": self.qty,
            "qty_missing_rows": self.qty_missing_rows,
            "source_rows": self.source_rows,
            "sources": self.sources,
        }


def rows_from_parquet(parquet_path: Path) -> list[dict]:
    """load_parquet отдаёт колоночный dict — разворачиваем в строки."""
    columns = load_parquet(str(parquet_path))
    if not columns:
        return []
    keys = list(columns.keys())
    length = len(columns[keys[0]]) if keys else 0
    return [{key: columns[key][i] for key in keys} for i in range(length)]


def collect_spec_rows(
    dataset_id: str,
    storage_root: Path = mutable_path("storage/datasets"),
    doc_types: tuple[str, ...] = BOR_SOURCE_DOC_TYPES,
) -> list[dict]:
    """Все строки спецификаций/ведомостей датасета с наименованием."""
    parquet_root = storage_root / dataset_id / "_parquet"
    rows: list[dict] = []
    if not parquet_root.exists():
        return rows
    for parquet_path in sorted(parquet_root.rglob("*.parquet")):
        for row in rows_from_parquet(parquet_path):
            if row.get("doc_type") not in doc_types:
                continue
            name = str(row.get("name") or row.get("work_name") or "").strip()
            if not name:
                continue
            rows.append(row)
    return rows


def build_bor(rows: list[dict]) -> list[BorLine]:
    """Свод: группировка по (раздел, наименование, код, марка, ед.изм.), сумма qty."""
    lines: dict[tuple, BorLine] = {}
    for row in rows:
        name = str(row.get("name") or row.get("work_name") or "").strip()
        section = str(row.get("section") or "").strip()
        code = str(row.get("code") or "").strip()
        mark = str(row.get("mark") or "").strip()
        unit = normalize_unit(row.get("unit"))
        key = (section.casefold(), _normalize_name(name), code.casefold(), mark.casefold(), unit)

        line = lines.get(key)
        if line is None:
            line = BorLine(section=section, name=re.sub(r"\s+", " ", name), code=code, mark=mark, unit=unit, qty=None)
            lines[key] = line

        qty = row.get("qty")
        if qty is not None:
            try:
                line.qty = (line.qty or 0.0) + float(qty)
            except (TypeError, ValueError):
                line.qty_missing_rows += 1
        else:
            line.qty_missing_rows += 1

        line.source_rows += 1
        source = str(row.get("source_file") or "").strip()
        pos = str(row.get("pos") or row.get("position") or "").strip()
        ref = f"{source}#{pos}" if pos else source
        if ref and ref not in line.sources:
            line.sources.append(ref)

    return sorted(lines.values(), key=lambda l: (l.section.casefold(), l.name.casefold(), l.code))


def bor_to_xlsx(lines: list[BorLine], output_path: Path, title: str = "Ведомость объёмов работ") -> int:
    """Экспорт ВОР в xlsx. Возвращает число строк."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    ws = wb.active
    ws.title = "ВОР"

    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    headers = ["№", "Раздел", "Наименование", "Код/Шифр", "Марка", "Ед. изм.", "Кол-во", "Строк-источников", "Источники"]
    ws.append(headers)
    for cell in ws[3]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True)

    for idx, line in enumerate(lines, 1):
        qty_cell = round(line.qty, 4) if line.qty is not None else "—"
        ws.append([
            idx,
            line.section,
            line.name + (f" (без кол-ва: {line.qty_missing_rows} строк)" if line.qty_missing_rows else ""),
            line.code,
            line.mark,
            line.unit,
            qty_cell,
            line.source_rows,
            "; ".join(line.sources[:10]),
        ])

    widths = {"A": 6, "B": 18, "C": 60, "D": 14, "E": 14, "F": 10, "G": 12, "H": 10, "I": 50}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    logger.info("[BOR] %s строк → %s", len(lines), output_path)
    return len(lines)


def source_rows_to_vor_xlsx(
    rows: list[dict], output_path: Path, *, title: str = "Ведомость объёмов работ",
    document_issues: list[dict] | None = None, draft: bool = False,
) -> int:
    """Render source rows without grouping, changing quantities or losing provenance."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "ВОР"
    sheet.append([title])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet.append([])
    if any(row.get("requires_decision") or row.get("open_gap") or row.get("source_audit") for row in rows):
        sheet["A2"] = "ЧЕРНОВИК — есть вопросы к исходным объёмам или решениям; см. примечания строк"
    if draft or document_issues:
        sheet["A2"] = "ВОР НЕ ЗАВЕРШЁН — промежуточная ревизия; см. лист «Проверка»"
    authored_columns = any(row.get("row_role") or row.get("work_row") or row.get("open_gap") or row.get("source_audit") or row.get("_authored_decision") for row in rows)
    authored_metadata = any(isinstance(row.get("_authored_decision"), dict) for row in rows)
    authored_derivation = any(row.get("_derived_quantity") for row in rows)
    headers = ["№", "Раздел", "Наименование", "Код/Шифр", "Ед. изм.", "Кол-во",
               "Источник", "Предполагаемая работа", "Статус решения"]
    if authored_columns:
        headers += ["Тип строки", "Связанная работа", "Замечания / проверка исходника"]
    if authored_metadata:
        headers += ["ID операции", "Учтено работой", "Полное решение модели"]
    if authored_derivation:
        headers[4:6] = ["Ед. изм. в решении", "Кол-во в решении"]
        headers += ["Расчётная единица", "Результат расчёта", "Коэффициент перевода", "Основание расчёта"]
    sheet.append(headers)
    if authored_derivation:
        sheet.row_dimensions[3].height = 30
    for cell in sheet[3]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True)

    audit_rows: dict[int, int] = {}
    operation_rows: dict[str, list[int]] = {}
    if authored_metadata:
        from proxy.services.attachment_source_catalog_service import VOR_MODEL_AUDIT_HEADERS, VOR_MODEL_AUDIT_SCHEMA

        audit = workbook.create_sheet("Решения модели")
        audit.append([VOR_MODEL_AUDIT_SCHEMA])
        audit.append(["Полные авторские поля сохранены; для одной строки соедините JSON-фрагменты в порядке записи."])
        audit.append(list(VOR_MODEL_AUDIT_HEADERS))
        for index, row in enumerate(rows, 4):
            decision = row.get("_authored_decision")
            if not isinstance(decision, dict):
                continue
            audit_rows[index] = audit.max_row + 1
            operation = str(decision.get("operation_id") or "")
            if operation:
                operation_rows.setdefault(operation, []).append(index)
            literal = json.dumps(decision, ensure_ascii=False, separators=(",", ":"))
            # Excel silently truncates a string cell above 32767 characters.
            # Fragmenting its literal JSON preserves every field and character.
            fragments = [literal[offset:offset + 32000] for offset in range(0, len(literal), 32000)]
            for part, fragment in enumerate(fragments, 1):
                audit.append([f"ВОР!R{index}", f"Фрагмент {part}/{len(fragments)}", f"JSON: {fragment}"])
                audit.cell(audit.max_row, 1).hyperlink = f"#'ВОР'!A{index}"
        for column, width in {"A": 24, "B": 18, "C": 100}.items():
            audit.column_dimensions[column].width = width
        for row in audit.iter_rows(min_row=3):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    for index, row in enumerate(rows, 1):
        source = str(row.get("source_file") or "").strip()
        position = str(row.get("pos") or row.get("position") or "").strip()
        locator = f"{source}#{position}" if source and position else source
        source_row = str(row.get("source_row") or "").strip()
        if source_row:
            locator = f"{locator} ({source_row})" if locator else source_row
        requires_decision = bool(row.get("requires_decision"))
        proposed = str(row.get("derived_work") or "").strip()
        values = [
            index,
            str(row.get("section") or "").strip(),
            str(row.get("name") or row.get("work_name") or "").strip(),
            str(row.get("code") or row.get("mark") or "").strip(),
            str(row.get("unit") or "").strip(),
            row.get("qty"),
            locator,
            proposed,
            (
                "ТРЕБУЕТ ПЕРЕСЧЁТА ИСХОДНОГО ФАЙЛА"
                if row.get("quantity_issue") == "formula_without_cached_value"
                else "ТРЕБУЕТ РЕШЕНИЯ" if requires_decision
                else "подтверждено" if proposed else ""
            ),
        ]
        if authored_columns:
            values += [str(row.get("row_role") or ""), str(row.get("work_row") or ""),
                       "; ".join(str(row.get(key) or "").strip() for key in ("open_gap", "source_audit") if row.get(key))]
        decision = row.get("_authored_decision")
        if authored_metadata:
            decision = decision if isinstance(decision, dict) else {}
            audit_row = audit_rows.get(index + 3)
            values += [str(decision.get("operation_id") or ""), str(decision.get("covered_by_work_id") or ""),
                       f"Решения модели!R{audit_row}" if audit_row is not None else ""]
        if authored_derivation:
            from proxy.services.vor_result_integrity_service import vor_quantity_number

            def authored_cell(value, *, numeric=False):
                if value is None:
                    return None
                number = vor_quantity_number(value) if numeric else None
                if number is not None:
                    return number
                literal = (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
                # An authored expression is evidence text, never an Excel formula.
                return "'" + literal if literal.startswith("=") else literal

            derived = row.get("_derived_quantity") or {}
            values += [authored_cell(derived.get("calc_unit")),
                       authored_cell(derived.get("calc_quantity"), numeric=True),
                       authored_cell(derived.get("conversion_factor"), numeric=True),
                       authored_cell(derived.get("conversion_source"))]
        sheet.append(values)
        # Source provenance is literal text, including filenames beginning with "=".
        source_cell = sheet.cell(sheet.max_row, 7)
        if isinstance(source_cell.value, str):
            source_cell.data_type = "s"
        if authored_metadata and audit_row is not None:
            sheet.cell(index + 3, 15).hyperlink = f"#'Решения модели'!C{audit_row}"
            covered = str(decision.get("covered_by_work_id") or "")
            targets = operation_rows.get(covered, [])
            if len(targets) == 1:
                sheet.cell(index + 3, 14).hyperlink = f"#'ВОР'!M{targets[0]}"

    for column, width in {"A": 6, "B": 18, "C": 60, "D": 16, "E": 10, "F": 12, "G": 42,
                          "H": 46, "I": 18, **({"J": 14, "K": 20, "L": 64} if authored_columns else {}),
                          **({"M": 28, "N": 28, "O": 32} if authored_metadata else {})}.items():
        sheet.column_dimensions[column].width = width
    if authored_derivation:
        from openpyxl.utils import get_column_letter

        first_column = len(headers) - 3
        for offset, width in enumerate((22, 20, 22, 80)):
            sheet.column_dimensions[get_column_letter(first_column + offset)].width = width
        for row in sheet.iter_rows(min_row=4, min_col=first_column, max_col=first_column + 3):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    if draft or document_issues:
        check = workbook.create_sheet("Проверка")
        check.append([sheet["A2"].value])
        check["A1"].font = Font(bold=True, size=13)
        check.append([])
        check.append(["Код", "Причина", "Незакрытые исходные строки", "Диагностика"])
        for issue in document_issues or []:
            check.append([str(issue.get("code") or ""), str(issue.get("reason") or ""),
                          ", ".join(str(item) for item in issue.get("remaining_locators") or []),
                          json.dumps(issue, ensure_ascii=False)])
        for column, width in {"A": 42, "B": 72, "C": 55, "D": 80}.items():
            check.column_dimensions[column].width = width
        for row in check.iter_rows(min_row=3):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    if authored_metadata or not rows:
        _add_vor_print_view(workbook)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    workbook.close()
    return len(rows)


def generate_bor(
    dataset_id: str,
    storage_root: Path = mutable_path("storage/datasets"),
    output_dir: Path | None = None,
    title: str | None = None,
) -> dict:
    """Полный цикл: parquet датасета → свод → xlsx. Без LLM (ADR-11)."""
    from datetime import datetime

    rows = collect_spec_rows(dataset_id, storage_root=storage_root)
    lines = build_bor(rows)
    result: dict = {
        "dataset_id": dataset_id,
        "source_rows": len(rows),
        "bor_lines": len(lines),
        "lines": [line.payload() for line in lines],
        "xlsx_path": None,
    }
    if output_dir is not None and lines:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        xlsx_path = output_dir / f"bor_{dataset_id}_{stamp}.xlsx"
        bor_to_xlsx(lines, xlsx_path, title=title or f"Ведомость объёмов работ — {dataset_id}")
        result["xlsx_path"] = str(xlsx_path)
    return result
