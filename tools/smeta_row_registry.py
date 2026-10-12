"""Реестр строк ведомости: что с каждой из 70 позиций на самом деле.

ЗАЧЕМ. «Решено 12, остаток 0» означает конец очереди попыток, а не готовую смету
(ревью Codex 11.09). Пока по каждой строке не видно, чем именно она учтена, судить
о готовности нельзя, а решать — что чинить — тем более: поиск, учёт материала или
нехватку исходных данных.

ЧТО ЗДЕСЬ. Сведение трёх источников в одну таблицу: исходная строка ведомости,
решение модели со снимком свидетельств, состояние курсора и результат расчёта из
книги. Ничего не додумывает: чего нет — помечено как отсутствующее.

Запуск:
    uv run python -m tools.smeta_row_registry --session sks-unit-20260911-0806 \
        --attachment "путь к сохранённому тексту скрепки" --book "путь к XLSX"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from backend.runtime_paths import mutable_path


# Состояния строки. Отдельная норма — не единственный законный исход: крепёж входит в
# норму на монтаж основного изделия, оборудование идёт самостоятельной стоимостью.
# Но и «нет подходящей нормы» — не то же самое, что «учтено в другой работе»: первое
# признаёт пробел, второе утверждает учёт. Смешивать их значит выдавать признание за
# результат (ревью Codex 11.09).
CALCULATED = "норма в книге"
REJECTED = "отвергнута расчётом"
NOT_IN_BOOK = "норма выбрана, в книге нет"
QUANTITY_UNMATCHED = "количество не сошлось"
CLAIMED_IN_WORK = "заявлено включение в работу"
NO_NORM_FOUND = "норма не найдена"
UNCLEAR = "без объяснения"
NOT_REVIEWED = "не рассмотрена"

# Заявление о включении в другую работу. Формулировка должна утверждать учёт, а не
# признавать пробел. Отрицание переворачивает смысл: «не входит в состав работ» — это
# ровно противоположное утверждение (ревью Codex 11.09).
_CLAIM_MARKERS = (
    "учитывается в", "учтено в", "учтена в", "учтены в", "входит в", "входят в",
    "в составе", "в стоимости", "включено в", "включается в", "включена в",
    "включены в", "по норме на монтаж",
)
_GAP_MARKERS = (
    "нет подходящей", "не найдена", "не найдено", "отсутствует норма",
    "требуется поиск", "нужен поиск", "нет нормы", "нет отдельной нормы",
    "не подобрана", "не установлена",
)


def _claimed(text: str) -> bool:
    """Есть ли утверждение об учёте — без отрицания прямо перед ним."""
    for marker in _CLAIM_MARKERS:
        start = 0
        while True:
            found = text.find(marker, start)
            if found == -1:
                break
            prefix = text[max(0, found - 12):found].rstrip()
            if not prefix.endswith("не"):
                return True
            start = found + 1
    return False


def _classify_without_norm(coverage: str) -> str:
    """Пробел, заявление об учёте или невнятность — это три разных состояния.

    Заявление засчитывается, только когда оно утверждает учёт: «не входит в состав
    работ; требуется поиск» — признание пробела, а не объяснение.
    """
    text = " ".join(str(coverage or "").split()).casefold()
    if not text:
        return UNCLEAR
    claim = _claimed(text)
    gap = any(marker in text for marker in _GAP_MARKERS)
    if claim and not gap:
        return CLAIMED_IN_WORK
    if gap:
        # «Нет отдельной нормы на гайку; учитывается в норме на монтаж» — здесь есть и
        # то и другое. Утверждение об учёте сильнее: пробел объяснён.
        return CLAIMED_IN_WORK if claim else NO_NORM_FOUND
    return UNCLEAR


def _cursor_rows(db: Path, session: str, revision: str) -> dict[str, dict[str, Any]]:
    """Записи одной ведомости одной сессии.

    Фильтр по ревизии обязателен: одна сессия может пройти несколько вложений, и без
    него реестр смешивал бы решения по разным ведомостям (ревью Codex 11.09).
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT anchor, decision_json, row_state, attempts FROM smeta_portion_done"
            " WHERE session_id=? AND source_revision=? ORDER BY rowid",
            (session, revision),
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            decision = json.loads(row["decision_json"] or "{}")
        except (TypeError, ValueError):
            decision = {}
        out[str(row["anchor"])] = {
            "state": str(row["row_state"] or ""),
            "attempts": int(row["attempts"] or 0),
            "decision": decision if isinstance(decision, dict) else {},
        }
    return out


def _book_positions(book: Path | None) -> list[dict[str, Any]]:
    """Позиции книги в порядке листа: шифр, единица и посчитанное количество."""
    if book is None or not book.is_file():
        return []
    import openpyxl

    sheet = openpyxl.load_workbook(book, data_only=True).worksheets[0]
    found: list[dict[str, Any]] = []
    for values in sheet.iter_rows(values_only=True):
        cells = [("" if cell is None else str(cell)) for cell in values]
        if len(cells) > 6 and cells[1].startswith("ГЭСН"):
            found.append({
                "code": cells[1], "no": cells[0], "unit": cells[3],
                "per_unit": cells[4], "total": cells[6], "taken": False,
            })
    return found


def _as_number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _take_position(
    positions: list[dict[str, Any]], code: str, quantity: Any
) -> dict[str, Any] | None:
    """Занять позицию книги под эту строку — по шифру и количеству, и только раз.

    Сопоставление по одному шифру засчитывало одну позицию нескольким строкам: две
    строки с общей нормой считались учтёнными, даже когда вторую расчёт отверг (ревью
    Codex 11.09). Поэтому позиция расходуется, а количество сверяется: измеритель
    делит исходное число, и совпадение подтверждает, что в книге именно эта строка.
    """
    wanted = _as_number(quantity)
    same_code = [item for item in positions if item["code"] == code and not item["taken"]]
    if not same_code:
        return None
    if wanted is not None:
        for item in same_code:
            total = _as_number(item["total"])
            if total is None:
                continue
            # Множитель берётся из измерителя книги («10 шт», «100 м кабеля»), а не из
            # единицы ведомости: 2 шт при измерителе «10 шт» дают в книге 0,2.
            #
            # Ожидаемое значение ровно одно. Раньше принималось и «как есть», и после
            # деления — тогда 120 шт при измерителе «100 шт» и числом 120 в книге
            # сходились, хотя это ошибка в сто раз (ревью Codex 11.09).
            factor = _as_number(str(item["unit"] or "").strip().split(" ", 1)[0]) or 1.0
            expected = wanted / factor
            if abs(total - expected) <= max(1e-6, abs(expected) * 1e-9):
                item["taken"] = True
                return item
    # Количество не сошлось — позиция этой строке не принадлежит. Занять первую
    # попавшуюся с тем же шифром значит приписать строке чужой расчёт.
    return None


def session_revisions(db: Path, session: str) -> list[tuple[str, int]]:
    """Какие ведомости проходила эта сессия и сколько строк у каждой."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return [
            (str(revision), int(count))
            for revision, count in conn.execute(
                "SELECT source_revision, COUNT(*) FROM smeta_portion_done"
                " WHERE session_id=? GROUP BY source_revision ORDER BY COUNT(*) DESC",
                (session,),
            )
        ]
    finally:
        conn.close()


def registry(
    *,
    session: str,
    attachment_text: str,
    book: Path | None,
    db: Path | None = None,
    revision: str = "",
) -> list[dict[str, Any]]:
    """Строка ведомости → решение → расчёт. Порядок исходной ведомости сохраняется."""
    from proxy.smeta_core.vor_rows import (
        row_anchor,
        rows_from_attachment_text,
        source_revision,
    )

    store = db or Path(mutable_path("storage/smeta_portions.db"))
    vor = rows_from_attachment_text(attachment_text)
    # Отпечаток считается по вложению. Явный `revision` нужен для записей, сделанных
    # прежней формулой отпечатка: подменять его догадкой нельзя, а читать чужую
    # ведомость под видом своей — тем более.
    cursor = _cursor_rows(store, session, revision or source_revision(vor))
    positions = _book_positions(book)
    from tools import smeta_book_audit
    evidence_book = smeta_book_audit.read_book(book) if book and book.is_file() else {}
    report: list[dict[str, Any]] = []
    for row in vor:
        anchor = row_anchor(row)
        record = cursor.get(anchor)
        decision = (record or {}).get("decision") or {}
        code = str(decision.get("norm_code") or "").strip()
        coverage = str(decision.get("coverage") or "").strip()
        rejected = str(decision.get("rejected_reason") or "").strip()
        placed = None
        if record is None:
            state = NOT_REVIEWED
        elif code and rejected:
            state = REJECTED
        elif code:
            placed = _take_position(positions, code, row.get("quantity"))
            if placed:
                state = CALCULATED
            elif any(item["code"] == code for item in positions):
                # Позиция с таким шифром в книге есть, но количество не сошлось ни с
                # одной — принадлежность строки не установлена.
                state = QUANTITY_UNMATCHED
            else:
                state = NOT_IN_BOOK
        else:
            state = _classify_without_norm(coverage)
        operation_evidence = {}
        if decision.get('work_id') or isinstance(decision.get('operations'), list):
            operation_evidence = smeta_book_audit.classify(row, decision, evidence_book)
            states = [item['state'] for item in operation_evidence.get('operations') or [operation_evidence]]
            if rejected:
                state = REJECTED
            elif all(value in {smeta_book_audit.PRICED, smeta_book_audit.PARTIAL_PRICE,
                               smeta_book_audit.FORMULA_UNCACHED, smeta_book_audit.IN_BOOK_NO_PRICE}
                     for value in states):
                state = CALCULATED  # presence/quantity only; price evidence stays separate
            else:
                state = operation_evidence['state']
        report.append({
            "anchor": anchor,
            "source_row": row.get("source_row"),
            "title": row.get("title"),
            "unit": row.get("unit"),
            "quantity": row.get("quantity_text") or row.get("quantity"),
            "cursor_state": (record or {}).get("state") or "нет записи",
            "attempts": (record or {}).get("attempts", 0),
            "norm_code": code or None,
            "coverage": coverage or None,
            "rejected_reason": rejected or None,
            "evidence": [
                {"query": item.get("query"), "norm_code": item.get("norm_code")}
                for item in (decision.get("evidence_snapshot") or [])
            ],
            "book_cells": placed,
            "accounted_by": state,
            **({'operation_evidence': operation_evidence} if operation_evidence else {}),
        })
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--attachment", required=True, type=Path)
    parser.add_argument("--book", type=Path)
    parser.add_argument("--db", type=Path)
    parser.add_argument(
        "--revision", default="",
        help="ревизия ведомости, если записи сделаны прежней формулой отпечатка",
    )
    parser.add_argument("--json", type=Path, help="куда сохранить полный реестр")
    args = parser.parse_args(argv)

    rows = registry(
        session=args.session,
        attachment_text=args.attachment.read_text(encoding="utf-8"),
        book=args.book,
        db=args.db,
        revision=args.revision,
    )
    if all(row["accounted_by"] == NOT_REVIEWED for row in rows):
        store = args.db or Path(mutable_path("storage/smeta_portions.db"))
        known = session_revisions(store, args.session)
        if known:
            print("Записей под отпечатком этой ведомости нет. В сессии есть:")
            for revision, count in known:
                print(f"  --revision {revision}  ({count} строк)")
            print()
    if args.json:
        args.json.write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    from collections import Counter

    by_account = Counter(row["accounted_by"] for row in rows)
    print(f"строк ведомости: {len(rows)}")
    for name in (CALCULATED, REJECTED, NOT_IN_BOOK, QUANTITY_UNMATCHED,
                 CLAIMED_IN_WORK, NO_NORM_FOUND, UNCLEAR, NOT_REVIEWED):
        print(f"  {name:<28} {by_account.get(name, 0)}")

    print()
    print(f"{'строка':>7} {'состояние':<28} {'норма':<20} курсор")
    for row in rows:
        print(
            f"{str(row['source_row']):>7} {row['accounted_by']:<28} "
            f"{str(row['norm_code'] or '—'):<20} {row['cursor_state']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
