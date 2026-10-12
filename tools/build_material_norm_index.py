"""Какой нормой сметчики посчитали вот это изделие.

ЗАЧЕМ. Строка ведомости именует изделие — «Hyperline UUTP4-C5E-S24-IN-LSZH-GY-305».
Норма именует работу — «Кабель до 35 кВ в проложенных трубах, блоках и коробах». Общих
слов между ними нет, и векторная близость их не связывает: замер 11.09 по 56 нерешённым
строкам дал 11 попаданий из 56, а на «Ответвитель горизонтальный» поиск ответил
«Пароперегреватель радиационный» — там нет ни одного общего слова. Поиск ищет изделие
среди названий работ, то есть в другой категории.

В готовых сметах эта связь записана прямо: под строкой-нормой идут строки ресурсов, и
там изделие названо так же, как в ведомости поставщика.

    ТЕРм11-04-008-01 | Съемные и выдвижные блоки (модули, ячейки, ТЭЗ) | 1 шт. | 30
     О | Том 11.3.3 стр.12 п.1 | Процессор управления 3-Series Room Media | шт. | 30

ЧТО ЗДЕСЬ. Обход того же архива, что и `build_estimate_usage_corpus`, но собираются пары
«наименование изделия → шифр нормы, под которой оно стоит». Получается индекс, по
которому наименование из ведомости ищется среди наименований изделий, а не среди
названий работ.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Не истиной и не заменой сметчику: изделие под нормой означает, что
так посчитали в конкретной смете, а не что это единственно верно. Частота говорит,
насколько решение распространено, и ничего не говорит о его правильности. Демонтажные
нормы собираются наравне с монтажными и помечаются, иначе «Кабель BC5E-4-LSHF» тянул бы
за собой «Демонтаж кабеля» молча.

ЧЕГО ЗДЕСЬ НЕТ. Количеств и коэффициентов: соотношение «штук изделия на измеритель
нормы» в смете выводится из объёмов работ, а не из строки ресурса, и переносить его
между объектами нельзя.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

from backend.runtime_paths import mutable_path
from proxy.smeta_core.section_taxonomy import classify_estimate
from tools.build_estimate_usage_corpus import (
    HEADER_ROWS,
    LOCAL,
    clean_norm_title,
    norm_code_of,
    read_header,
)


SCHEMA = "les.smeta.material-norm-index.v1"
DEFAULT_OUT = mutable_path("data/smeta_base/material_norm_index.json")
DEFAULT_BASE = mutable_path("data/smeta_base/les_smeta_base.sqlite")

# Итоги, накрутки и пояснения бланка. Они стоят там же, где ресурсы, но изделием не
# являются: без отсева «Накладные расходы» попали бы в индекс как материал.
SERVICE_ROW = re.compile(
    r"^\s*(итого|всего|в том числе|накладные|сметная прибыль|нр\b|сп\b|фот\b|мдс\b"
    r"|производство\s+монтажных|справочно|стоимость материалов|материалы\b"
    r"|эксплуатация\s+машин|затраты\s+труда|оплата\s+труда|машины\s+и\s+механизмы"
    r"|коэффициент|индекс\b|раздел\b|поправ)",
    re.IGNORECASE,
)

# Наименование ресурса, ничего не сообщающее об изделии.
BLANK_TITLE = re.compile(r"^\s*[-—.\d\s]*$")

DEMOLITION = re.compile(r"демонтаж|разборк|снятие", re.IGNORECASE)

MIN_TITLE_CHARS = 6


def _cells(row: Any) -> list[str]:
    return ["" if cell is None else str(cell).strip() for cell in (row or ())]


def is_equipment(mark: str) -> bool:
    """Флаг «О» в графе номера — строка оборудования, а не расходного материала."""
    return str(mark or "").strip().upper() in {"О", "O"}


def material_title(text: str) -> str:
    """Наименование изделия без служебного хвоста сметной программы."""
    return clean_norm_title(text)


def looks_like_material(cells: list[str]) -> bool:
    """Строка ресурса под нормой: есть наименование и единица, нет шифра расценки."""
    if len(cells) < 4:
        return False
    if norm_code_of(cells[1]):
        return False
    title = cells[2]
    if len(title) < MIN_TITLE_CHARS or BLANK_TITLE.match(title):
        return False
    if SERVICE_ROW.match(title) or SERVICE_ROW.match(cells[1]):
        return False
    return bool(cells[3].strip())


def scan_workbook_pairs(path: Path) -> Iterator[dict[str, Any]]:
    """Пары «изделие → норма, под которой оно стоит» со всех локальных листов книги."""
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        for sheet in workbook.worksheets:
            head: list[list[str]] = []
            try:
                rows = sheet.iter_rows(
                    min_row=1, max_row=min(sheet.max_row or 0, 5000), values_only=True
                )
            except Exception:  # noqa: BLE001 — испорченный лист не роняет книгу
                continue
            current_norm = ""
            current_work = ""
            current_unit = ""
            current_source: dict[str, Any] = {}
            pending: list[dict[str, Any]] = []
            for number, row in enumerate(rows):
                cells = _cells(row)
                if number < HEADER_ROWS:
                    head.append(cells)
                if not any(cells):
                    continue
                code = norm_code_of(cells[1]) if len(cells) > 1 else ""
                if code:
                    current_norm = code
                    current_work = clean_norm_title(cells[2] if len(cells) > 2 else "")
                    current_unit = (cells[3] if len(cells) > 3 else "")[:40]
                    from tools.build_estimate_usage_corpus import RATE_CODE
                    current_source = {
                        "document": str(path), "sha256": digest, "sheet": sheet.title,
                        "work_row": number + 1, "original_code": RATE_CODE.match(cells[1]).group(0),
                        "raw_code": cells[1], "edition": None, "norm_title": current_work,
                        "raw_title": cells[2], "norm_unit": current_unit,
                        "work_steps": None, "context_complete": False,
                    }
                    continue
                # Ресурс без предшествующей нормы привязать не к чему: в начале листа
                # так выглядят строки шапки таблицы.
                if not current_norm or not looks_like_material(cells):
                    continue
                pending.append({
                    "material": material_title(cells[2])[:160],
                    "material_unit": cells[3][:24],
                    "norm_code": current_norm,
                    "norm_title": current_work[:120],
                    "norm_unit": current_unit,
                    "equipment": is_equipment(cells[0]),
                    "example": {**current_source, "material_row": number + 1,
                                "material": cells[2], "material_unit": cells[3],
                                "equipment": is_equipment(cells[0]),
                                "link_kind": "following_norm"},
                })
            kind, title = read_header(head)
            if (kind or LOCAL) != LOCAL or not pending:
                continue
            section = classify_estimate(title, path.name) or "other"
            for item in pending:
                yield {**item, "section": section}
    finally:
        workbook.close()


def build_index(source: Path, *, base_path: Path | None = None) -> dict[str, Any]:
    """Обойти архив смет и собрать индекс применений по наименованию изделия."""
    pairs: dict[tuple[str, str], Counter] = defaultdict(Counter)
    meta: dict[tuple[str, str], dict[str, Any]] = {}
    files = 0
    unreadable: list[str] = []
    sections: Counter = Counter()
    total = 0

    for path in sorted(Path(source).rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        try:
            found = list(scan_workbook_pairs(path))
        except Exception:  # noqa: BLE001 — битый файл не роняет обход, но и не молчит
            unreadable.append(path.name)
            continue
        if not found:
            continue
        files += 1
        for item in found:
            key = (item["material"], item["norm_code"])
            pairs[key][item["section"]] += 1
            total += 1
            sections[item["section"]] += 1
            meta.setdefault(key, {
                "material_unit": item["material_unit"],
                "norm_title": item["norm_title"],
                "norm_unit": item["norm_unit"],
                "equipment": item["equipment"],
                "demolition": bool(DEMOLITION.search(item["norm_title"])),
                "examples": [],
            })
            meta[key]["examples"].append(item["example"])

    # База может быть недоступна — тогда «есть в базе» неизвестно, и записать `true`
    # значит выдать непроверенное за проверенное. Третье состояние: None.
    known: set[str] | None = None
    target = Path(base_path or DEFAULT_BASE)
    if target.is_file():
        with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as conn:
            known = {row[0] for row in conn.execute("select display_code from norms")}
        if not known:
            known = None

    entries = []
    for (material, norm_code), counter in pairs.items():
        info = meta[(material, norm_code)]
        entries.append({
            "material": material,
            "norm_code": norm_code,
            "count": sum(counter.values()),
            "sections": dict(counter),
            "in_base": None if known is None else (norm_code in known),
            **info,
        })
    entries.sort(key=lambda item: (-item["count"], item["material"]))

    return {
        "schema": SCHEMA,
        "source": str(source),
        "files": files,
        "pairs_total": total,
        "materials": len({item["material"] for item in entries}),
        "entries": entries,
        "sections": dict(sections),
        "unreadable": unreadable,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="каталог архива смет")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--base", default=str(DEFAULT_BASE))
    args = parser.parse_args(argv)

    if not Path(args.source).is_dir():
        print("Источник недоступен; индекс не изменён")
        return 2

    index = build_index(Path(args.source), base_path=Path(args.base))
    out = Path(args.out)
    if not index["pairs_total"] or index["unreadable"]:
        print("Пустой или неполный обход; индекс не изменён")
        return 3
    from tools.build_estimate_usage_corpus import _publish
    _publish(out, index)

    print(f"файлов с парами:      {index['files']}")
    print(f"пар «изделие→норма»:  {index['pairs_total']}")
    print(f"уникальных изделий:   {index['materials']}")
    print(f"нечитаемых книг:      {len(index['unreadable'])}")
    print(f"записано:             {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
