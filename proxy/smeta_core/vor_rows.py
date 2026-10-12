"""Строки ведомости объёмов работ со стабильными якорями.

ЗАЧЕМ. Длинную ведомость нельзя закрыть за один проход, и это измерено, а не выведено:
в окно модели помещаются свидетельства примерно по 18 запросам из 51 — 32 768 токенов
контекста, 22 528 на вход этапа ответа, минус профиль сметчика и текст самой ведомости
оставляют 14 031 токен на карточки норм. Настройка бюджета этого не меняет.

ЧТО ЗДЕСЬ. Разбор ведомости в строки с якорем, по которому проход продолжается с того
места, где остановился предыдущий. Якорь — номер из первой колонки: тот, что видит
сметчик и на который ссылается модель в поле `source_row`. Номер поискового запроса
для этого не годится: соответствия один к одному со строками у него нет — на 80 строк
модель формулировала 51, 55 и 59 запросов в разных прогонах.

Ни сети, ни модели: только чтение файла и чистые правила.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "les.smeta.vor-row-anchors.v1"

# Номер позиции — текстовая метка: «984», «1.10», «1.10.1», а не десятичное число.
# Разделы без единицы и объёма отсеиваются отдельно, сохраняя контекст следующих строк.
POSITION = re.compile(r"^\d{1,6}(?:\.\d{1,6})*$")
# Строка-заголовок раздела: номер есть, но вместо позиции — название главы.
SECTION_TITLE = re.compile(r"^(?:раздел|подраздел)\b", re.IGNORECASE)
HEADER_LIMIT = 40


def source_revision(rows: Sequence[Mapping[str, Any]]) -> str:
    """Отпечаток содержимого ведомости — то, по чему узнаётся «та же ведомость».

    Считается по строкам, а не по тексту скрепки: текст начинается с «Файл: имя.xlsx»,
    и переименование файла обнуляло прогресс, хотя ведомость та же (ревью Codex, R3).
    Изменение любой ячейки позиции ревизию меняет — продолжать чужой разбор нельзя.
    """
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row_anchor(row).encode("utf-8"))
        digest.update(b"\x00")
        # Только то, что пришло из файла: сами ячейки, шапка листа и раздел. Разобранные
        # поля — наименование, единица, количество — из них выводятся, и включать их
        # значит ронять продолжение при любой починке разбора: правка `quantity_text`
        # превратила «2,50» в «2.5», отпечаток сменился, и сохранённые решения перестали
        # находиться (ревью Codex 11.09).
        digest.update(json.dumps(
            {key: row.get(key) for key in ("raw", "cells", "header", "section")},
            ensure_ascii=False, sort_keys=True,
        ).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def row_anchor(row: Mapping[str, Any]) -> str:
    """Якорь строки: лист и номер позиции.

    Номер позиции сам по себе не уникален — в ведомости из нескольких листов позиция №1
    есть на каждом, и продолжение по такому якорю топталось на первом совпадении
    (ревью Codex 10.09, R3). Для строк без листа якорем остаётся номер.
    """
    anchor = str(row.get("anchor") or "").strip()
    if anchor:
        return anchor
    sheet = str(row.get("sheet") or "").strip()
    source_row = str(row.get("source_row") or "").strip()
    return f"{sheet}!{source_row}" if sheet else source_row


def decision_anchor(row: Mapping[str, Any], anchors: Sequence[str]) -> str:
    """Resolve a model label only when it identifies exactly one offered source row."""
    label = row_anchor(row)
    allowed = set(anchors)
    if label in allowed:
        return label
    # The attachment renderer exposes this marker. Copying its wrapper must not
    # sever an otherwise exact source reference. Resolve only the complete marker;
    # never rewrite the authored row or extract an anchor from arbitrary prose.
    marker = re.fullmatch(r"\[Строка ВОР:\s*(?:source_row\s*=\s*)?([^\[\]\r\n]+)\]", label)
    if marker:
        label = marker.group(1).strip()
        if label in allowed:
            return label
    matches = [anchor for anchor in allowed if anchor.rsplit("!", 1)[-1] == label]
    return matches[0] if len(matches) == 1 else ""


def explicit_norm_absence(value: Any) -> bool:
    """Recognize explicit absence markers without changing the model's decision."""
    marker = str(value or "").strip().strip("*_` ").strip()
    if len(marker) >= 2 and (marker[0], marker[-1]) in {("(", ")"), ("[", "]")}:
        marker = marker[1:-1].strip()
    return marker.casefold() in {"", "—", "-", "–", "−", "нет", "н/д", "n/a", "na"}


def _make_anchor(sheet: str, source_row: str) -> str:
    sheet = str(sheet or "").strip()
    return f"{sheet}!{source_row}" if sheet else str(source_row)


def _quantity_text(value: Any) -> str:
    """Количество в том виде, в каком оно стоит в ведомости.

    Формат `:g` держит шесть значащих цифр и портил исходные числа: 1234567.89
    превращалось в 1.23457e+06 ещё до модели (ревью Codex 10.09, R2).
    """
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: Any) -> float | None:
    """Количество из ячейки; None, если это не число."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


COLUMN_MARKS = {
    "title": ("наименование",),
    "unit": ("ед. изм", "ед.изм", "единица"),
    "quantity": ("объем", "объём", "кол-во", "количество"),
}


def _column_map(cells: Sequence[str]) -> dict[str, int] | None:
    """Индексы колонок по строке заголовка таблицы; None, если это не заголовок."""
    found: dict[str, int] = {}
    for index, cell in enumerate(cells):
        text = " ".join(str(cell or "").split()).casefold()
        if not text:
            continue
        for name, marks in COLUMN_MARKS.items():
            if name not in found and any(mark in text for mark in marks):
                found[name] = index
    return found if {"title", "unit", "quantity"} <= set(found) else None


def row_anchors(path: Path | str, *, sheet: str = "") -> list[dict[str, Any]]:
    """Строки ведомости с якорями: номер позиции, номер строки листа, наименование.

    Колонки читаются по заголовку таблицы, а не угадываются по порядку: между
    наименованием и единицей у этой ведомости стоят артикул и производитель, и разбор
    «первый текст после наименования» подставлял в единицу «Hyperline».

    Строка нумерации колонок и явные заголовки разделов пропускаются. Нумерованная
    строка с отсутствующими единицей и количеством остаётся видимой: эти пропуски
    не доказывают, что перед нами заголовок группы. Явный раздел запоминается:
    он объясняет, к чему относится позиция, и различает похожие наименования.

    Исходные ячейки сохраняются целиком (`cells`, `raw`): выбор нормы делается по всей
    строке, а не по наименованию с количеством.
    """
    import openpyxl

    source = Path(path)
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        worksheet = workbook[sheet] if sheet else workbook.worksheets[0]
        sheet_name = str(worksheet.title or "")
        columns: dict[str, int] | None = None
        header_cells: list[str] = []
        section = ""
        rows: list[dict[str, Any]] = []
        for index, values in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if not values:
                continue
            cells = [("" if cell is None else str(cell).strip()) for cell in values]
            while cells and not cells[-1]:
                cells.pop()
            if columns is None:
                columns = _column_map(cells)
                if columns is not None:
                    header_cells = list(cells)
                continue
            cells += [''] * max(0, len(header_cells) - len(cells))
            head = cells[0] if cells else ""
            if not POSITION.match(head):
                candidate = " ".join(part for part in cells if part).strip()
                if candidate and _number(candidate) is None:
                    section = candidate
                continue
            title = cells[columns["title"]] if len(cells) > columns["title"] else ""
            unit = cells[columns["unit"]] if len(cells) > columns["unit"] else ""
            quantity = _number(cells[columns["quantity"]]) if len(cells) > columns["quantity"] else None
            if not title:
                continue
            if SECTION_TITLE.match(title):
                section = title
                continue
            # Строка нумерации колонок «1 | 2 | 3 | 4»: наименование в ней — цифра.
            if POSITION.match(title):
                continue
            # Missing unit/quantity cannot prove that a numbered source row is a heading.
            rows.append({
                "source_row": head,
                "sheet": sheet_name,
                "anchor": _make_anchor(sheet_name, head),
                "sheet_row": index,
                "title": title,
                "unit": unit,
                "quantity": quantity,
                "quantity_text": _quantity_text(
                    cells[columns["quantity"]] if len(cells) > columns["quantity"] else ""
                ) or _quantity_text(quantity),
                "section": section,
                "cells": list(cells),
                "raw": " | ".join(part for part in cells if part),
                "header": list(header_cells),
            })
        return rows
    finally:
        workbook.close()


def _unit_and_quantity(cells: Sequence[str], columns: Mapping[str, int], *, header_width: int | None = None, fixed_width: bool = False) -> tuple[str, float | None]:
    """Единица и количество строки, даже если колонки в ней сдвинуты.

    В историческом сжатом транспорте незаполненный артикул сдвигал ячейки влево:
    «1001 | Розетка… |
    Simon | шт. | 4» против «984 | Шкаф… | TTR-4281 | Hyperline | шт. | 2».
    Полная строка сохраняет значения по заголовку, включая неизвестное количество.
    Поиск пары «единица, количество» допустим только для короткой legacy-строки
    с отсутствующей или числовой ячейкой на месте единицы.
    """
    unit = cells[columns["unit"]] if len(cells) > columns["unit"] else ""
    quantity = _number(cells[columns["quantity"]]) if len(cells) > columns["quantity"] else None
    expected_width = header_width if header_width is not None else max(columns.values()) + 1
    if fixed_width or len(cells) >= expected_width or (unit and _number(unit) is None):
        return unit, quantity
    # Поиск идёт строго правее наименования: иначе «Оборудование | 0 | 0» превращается
    # в единицу «Оборудование» с количеством ноль, и заголовок группы становится позицией.
    for index in range(len(cells) - 2, int(columns["title"]), -1):
        candidate = cells[index].strip()
        follower = _number(cells[index + 1])
        if candidate and _number(candidate) is None and follower is not None and len(candidate) <= 12:
            return candidate, follower
    return ("" if _number(unit) is not None else unit), quantity


# Строка вложения в чате: «СКС!R6: 984 | наименование | артикул | шт. | 2».
ATTACHMENT_ROW = re.compile(r"^(?P<sheet>[^!]+)!R(?P<row>\d+):\s*(?P<body>.*)$")


def _attachment_cells(body: str, *, escaped: bool) -> list[str]:
    if not escaped:
        return [part.strip() for part in body.split('|')]
    cells: list[str] = []
    current: list[str] = []
    pending_escape = False
    for character in body:
        if pending_escape:
            if character not in ('\\', '|'):
                current.append('\\')
            current.append(character)
            pending_escape = False
        elif character == '\\':
            pending_escape = True
        elif character == '|':
            cells.append(''.join(current).strip())
            current = []
        else:
            current.append(character)
    if pending_escape:
        current.append('\\')
    cells.append(''.join(current).strip())
    return cells


def rows_from_attachment_text(text: str) -> list[dict[str, Any]]:
    """Позиции ведомости из текста скрепки чата.

    Вложение доходит до сборки строкой, а не файлом, поэтому разбирается то, что есть:
    лезть за файлом в хранилище ради номеров строк незачем. Колонки определяются по
    строке заголовка — у этой ведомости между наименованием и единицей стоят артикул и
    производитель, и счёт по порядку подставил бы в единицу «Hyperline».

    Исходные ячейки сохраняются целиком. Разобранные поля нужны для нарезки и якорей, но
    выбор нормы делается по всей строке: артикул, производитель и раздел различают
    похожие позиции, а порция, отдающая лишь наименование с количеством, обедняет
    свидетельство ещё до модели (ревью Codex 10.09, R2).

    Заголовок таблицы читается для каждого листа отдельно: у листов разная разметка, а
    одна карта колонок на всю книгу разъезжается на втором же листе.
    """
    columns: dict[str, int] | None = None
    rows: list[dict[str, Any]] = []
    sheet = ""
    section = ""
    header_cells: list[str] = []
    fixed_width = False
    for line in str(text or "").splitlines():
        if line.strip().startswith('Файл:'):
            fixed_width = False
            columns = None
            sheet = ''
            section = ''
            header_cells = []
        if line.strip() == 'Формат ячеек: les.tabular.cells.v2':
            fixed_width = True
            continue
        match = ATTACHMENT_ROW.match(line.strip())
        if not match:
            continue
        if match.group("sheet").strip() != sheet:
            sheet = match.group("sheet").strip()
            columns = None
            section = ""
            header_cells = []
        sheet_row = int(match.group("row"))
        body = match.group("body")
        cells = _attachment_cells(body, escaped=fixed_width)
        if columns is None:
            columns = _column_map(cells)
            if columns is not None:
                header_cells = list(cells)
            continue
        if fixed_width:
            cells += [''] * max(0, len(header_cells) - len(cells))
        head = cells[0] if cells else ""
        title = cells[columns["title"]] if len(cells) > columns["title"] else ""
        if not POSITION.match(head):
            # Строка без номера позиции с текстом — заголовок раздела. Он не закрывается
            # нормой, но объясняет следующие строки и потому запоминается.
            candidate = " ".join(part for part in cells if part).strip()
            if candidate and _number(candidate) is None:
                section = candidate
            continue
        if not title or POSITION.match(title):
            continue
        if SECTION_TITLE.match(title):
            section = title
            continue
        unit, quantity = _unit_and_quantity(cells, columns, header_width=len(header_cells), fixed_width=fixed_width)
        rows.append({
            "source_row": head,
            "sheet": sheet,
            "anchor": _make_anchor(sheet, head),
            "sheet_row": sheet_row,
            "title": title,
            "unit": unit,
            "quantity": quantity,
            # Текст количества берётся из того же разбора, что и число: у строк без
            # артикула колонки сдвинуты, и чтение по индексу заголовка приносило из
            # примечания целое наименование вместо числа (строка 1052 ведомости СКС).
            "quantity_text": (_quantity_text(cells[columns['quantity']])
                if len(cells) > columns['quantity'] and (fixed_width or len(cells) >= len(header_cells))
                else _quantity_text(quantity)),
            "section": section,
            "cells": list(cells),
            "raw": body.strip(),
            "header": list(header_cells),
        })
    return rows


def slice_rows(
    rows: Sequence[dict[str, Any]],
    *,
    limit: int,
    after: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Порция строк для одного прохода и остаток на следующие.

    `after` — якорь последней закрытой строки в виде «лист!позиция» (см. `row_anchor`).
    Неизвестный якорь означает начало: молча потерять всю ведомость хуже, чем повторить
    её первую часть.
    """
    ordered = list(rows)
    start = 0
    anchor = str(after or "").strip()
    if anchor:
        for index, row in enumerate(ordered):
            if row_anchor(row) == anchor:
                start = index + 1
                break
    window = max(1, int(limit))
    return ordered[start : start + window], ordered[start + window :]
