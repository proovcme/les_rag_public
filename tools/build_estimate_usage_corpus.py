"""Свод применённых расценок из архива готовых смет: раздел → норма → частота.

ЗАЧЕМ. Подбор нормы по одному лексическому сходству ищет среди 49 747 позиций и
находит бестраншейную прокладку в полосе отвода железных дорог для кабеля U/UTP.
Реальные сметы показывают рабочее ядро: раздел связи закрывается сотней норм. Это
сужение пространства поиска в сотни раз.

ОТКУДА СВЯЗЬ. Территориальные расценки строятся на федеральных элементных нормах и
сохраняют их нумерацию: `ТЕРм10-03-001-01` → `ГЭСНм10-03-001-01`, то же название и
единица. Проверка на 9 655 строках архива: 95 % кодов находятся в ФСНБ-2022 по тому
же номеру, 91 % из них совпадают названием. Расхождения — региональные добавки.

КАК ОПРЕДЕЛЯЕТСЯ РАЗДЕЛ. По наименованию из шапки листа — его писали люди русскими
словами («Демонтаж. Структурированная кабельная система»), — и лишь если раздел там
не назван, по шифру в имени файла. Единица разбора — лист, а не файл: в архиве есть
книги, где ведомости объёмов работ по всем разделам этапа разложены по листам.

ЧТО ОТБРАСЫВАЕТСЯ. Объектные и сводные расчёты: они складывают итоги локальных смет
и собственных расценок не содержат — иначе одни и те же строки считались бы дважды.

ЧЕМ ЭТО НЕ ЯВЛЯЕТСЯ. Корпус не исчерпывает допустимые нормы раздела: в конкретных
проектах применялись не все позиции. Он задаёт вектор раздела — что здесь уместно, —
поэтому потребитель обязан использовать его как положительный сигнал и никогда как
запрет: отсутствие нормы в корпусе ничего не доказывает.

Запуск:
    python -m tools.build_estimate_usage_corpus --source "E:/Сметы" --out data/smeta_base/estimate_usage_corpus.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.runtime_paths import mutable_path
from proxy.smeta_core.section_taxonomy import classify_estimate


SCHEMA = "les.smeta.estimate-usage-corpus.v1"
DEFAULT_OUT = mutable_path("data/smeta_base/estimate_usage_corpus.json")
DEFAULT_BASE = mutable_path("data/smeta_base/les_smeta_base.sqlite")

# Код расценки: семейство, необязательная буква части, номер сборника-отдела-таблицы.
RATE_CODE = re.compile(r"^(?:ТЕР|ФЕР)(м|р|п|мр)?(\d{2}-\d{2}-\d{3}-\d{2})")

# Шапка листа: «ЛОКАЛЬНЫЙ СМЕТНЫЙ РАСЧЕТ № 02-05-03», ниже — наименование работ.
HEADER_ROWS = 26
HEADER_MARK = re.compile(r"СМЕТН\w*\s+РАСЧ\w*|ВЕДОМОСТЬ\s+ОБЪЕМОВ", re.IGNORECASE)
CAPTION = re.compile(r"^\(наименование", re.IGNORECASE)
# Служебные подписи бланка, наименованием не являющиеся.
SERVICE_CELLS = {"на", "на строительство", "(локальная смета)", "(объектная смета)", "-", "—"}

LOCAL = "локальная"
OBJECT = "объектная"
SUMMARY = "сводная"


# Сметная программа дописывает к наименованию служебный хвост: индекс к позиции с
# территориальной расценкой, накладные, коэффициенты к расходу. В корпусе он лишний и
# опасен: в базе LES только ГЭСН, и текст «ТЕР15-04-006-03», дойдя до модели, подсказал
# бы ей несуществующий шифр.
TITLE_TAIL = re.compile(
    r"\s*(?:ИНДЕКС\s+К\s+ПОЗИЦИИ|НР\s*\(|СП\s*\(|\(МАТ=|\(ОЗП=|ТЕР[а-яa-z]*\d|ФЕР[а-яa-z]*\d).*$",
    re.IGNORECASE | re.DOTALL,
)


def clean_norm_title(title: str) -> str:
    """Наименование работы без служебного хвоста сметной программы."""
    text = TITLE_TAIL.sub("", str(title or "")).strip()
    return " ".join(text.split())


def norm_code_of(rate_code: str) -> str:
    """`ТЕРм10-03-001-01` → `ГЭСНм10-03-001-01`; пусто, если это не код расценки."""
    match = RATE_CODE.match(str(rate_code or "").strip())
    if not match:
        return ""
    return f"ГЭСН{match.group(1) or ''}{match.group(2)}"


def document_kind(line: str) -> str:
    """Тип расчёта по строке шапки: локальный, объектный или сводный."""
    upper = str(line or "").upper()
    if "СВОДН" in upper:
        return SUMMARY
    if "ОБЪЕКТН" in upper:
        return OBJECT
    return LOCAL


def read_header(rows: list[list[str]]) -> tuple[str, str]:
    """Тип расчёта и наименование работ из шапки листа."""
    for index, row in enumerate(rows):
        line = " ".join(value for value in row if value)
        if not HEADER_MARK.search(line):
            continue
        parts: list[str] = []
        for follower in rows[index + 1 : index + 9]:
            cells = [value for value in follower if value]
            if not cells:
                continue
            if CAPTION.match(cells[0]):
                break
            for value in cells:
                clean = value.strip()
                if clean.lower() in SERVICE_CELLS or clean.startswith("("):
                    continue
                if clean and clean not in parts:
                    parts.append(clean)
        return document_kind(line), ", ".join(parts)[:250]
    return "", ""


def scan_workbook(path: Path) -> list[dict[str, Any]]:
    """Листы одной книги: раздел, тип расчёта и применённые нормы. Битые файлы молчат."""
    import openpyxl

    sheets: list[dict[str, Any]] = []
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            head: list[list[str]] = []
            found: list[tuple[str, str, str]] = []
            examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
            try:
                rows = sheet.iter_rows(min_row=1, max_row=min(sheet.max_row or 0, 5000), values_only=True)
            except Exception:  # noqa: BLE001
                continue
            for number, row in enumerate(rows):
                if not row:
                    continue
                if number < HEADER_ROWS:
                    head.append([("" if cell is None else str(cell).strip()) for cell in row])
                if len(row) < 4:
                    continue
                norm = norm_code_of(str(row[1] or ""))
                if norm:
                    found.append((norm, clean_norm_title(row[2])[:120], str(row[3] or "").strip()[:40]))
                    examples[norm].append({
                        "document": str(path), "sha256": digest, "sheet": sheet.title,
                        "work_row": number + 1, "material_row": None,
                        "original_code": RATE_CODE.match(str(row[1]).strip()).group(0),
                        "raw_code": str(row[1]), "edition": None,
                        "norm_title": clean_norm_title(row[2]), "raw_title": str(row[2]),
                        "norm_unit": str(row[3] or "").strip(), "work_steps": None,
                        "link_kind": "work_occurrence", "context_complete": False,
                    })
            kind, title = read_header(head)
            sheets.append({
                "kind": kind or LOCAL,
                "title": title,
                "section": classify_estimate(title, path.name),
                "norms": found,
                "examples": dict(examples),
            })
    finally:
        workbook.close()
    return sheets


def build_corpus(
    source: Path,
    *,
    base_path: Path | None = None,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    """Обойти архив смет и собрать применения норм по разделам.

    `exclude` — относительные пути каталогов или файлов, которые в корпус не попадают.
    Именно пути, а не имена: одно и то же имя («01-01-01 АР Д …») встречается в разных
    проектах, и отбор по имени вычистил бы чужие сметы, оставив свои. Нужен для
    проверки — измерять подбор на сметах, чьи строки уже лежат в корпусе, значит
    спрашивать ответ у самого ответа.
    """
    root = Path(source)
    skipped_paths = {str(Path(item)).replace("\\", "/").strip("/") for item in (exclude or ())}
    usage: dict[str, Counter] = defaultdict(Counter)
    titles: dict[str, str] = {}
    units: dict[str, str] = {}
    files: Counter = Counter()
    skipped: Counter = Counter()
    unresolved: list[str] = []
    unreadable: list[str] = []
    rows_total = 0
    examples: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for path in sorted(Path(source).rglob("*.xlsx")):
        if path.name.startswith("~$"):
            continue
        if skipped_paths:
            relative = str(path.relative_to(root)).replace("\\", "/")
            if any(relative == item or relative.startswith(item + "/") for item in skipped_paths):
                skipped["исключено"] += 1
                continue
        try:
            sheets = scan_workbook(path)
        except Exception:  # noqa: BLE001 — битый файл не роняет обход, но и не молчит
            unreadable.append(path.name)
            continue
        for sheet in sheets:
            if sheet["kind"] != LOCAL:
                skipped[sheet["kind"]] += 1
                continue
            if not sheet["norms"]:
                continue
            section = sheet["section"] or "other"
            if section == "other":
                unresolved.append(f"{path.name} | {sheet['title'][:80]}")
            files[section] += 1
            for norm, occurrences in (sheet.get("examples") or {}).items():
                examples[(section, norm)].extend(occurrences)
            for norm, title, unit in sheet["norms"]:
                usage[section][norm] += 1
                rows_total += 1
                titles.setdefault(norm, clean_norm_title(title))
                units.setdefault(norm, unit)

    # База может быть недоступна — тогда «есть в базе» неизвестно, и записать `true`
    # значит выдать непроверенное за проверенное. Третье состояние: None.
    known: set[str] | None = None
    target = Path(base_path or DEFAULT_BASE)
    if target.is_file():
        with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as conn:
            known = {row[0] for row in conn.execute("select display_code from norms")}
        if not known:
            known = None

    sections: dict[str, Any] = {}
    for section, counter in usage.items():
        sections[section] = {
            "files": files[section],
            "applications": sum(counter.values()),
            "norms": [
                {
                    "norm_code": norm,
                    "count": count,
                    "unit": units.get(norm, ""),
                    "title": titles.get(norm, ""),
                    "in_base": None if known is None else (norm in known),
                    "examples": examples[(section, norm)],
                }
                for norm, count in counter.most_common()
            ],
        }
    return {
        "schema": SCHEMA,
        "source": str(source),
        "revision": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "base_checked": known is not None,
        "rows_total": rows_total,
        "skipped": dict(skipped),
        "unresolved": sorted(set(unresolved)),
        "unreadable": sorted(set(unreadable)),
        "sections": sections,
    }


def _publish(out: Path, corpus: dict[str, Any]) -> None:
    """Опубликовать корпус целиком или не публиковать вовсе.

    Сборка идёт по двум с лишним тысячам книг и занимает минуты. Запись поверх живого
    файла оставляла бы обрыв на середине как «корпус»: читатели держатся за размер и
    время правки и ничего бы не заподозрили. Поэтому пишем во временный файл рядом и
    подменяем одним движением.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    staged = out.with_name(out.name + ".partial")
    try:
        with staged.open("w", encoding="utf-8") as handle:
            json.dump(corpus, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, out)
    finally:
        staged.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="каталог с готовыми сметами")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument(
        "--allow-unreadable",
        action="store_true",
        help="записать корпус, даже если часть книг не прочиталась (список останется в корпусе)",
    )
    args = parser.parse_args(argv)

    # Съёмный диск с архивом отпадает после сна: обход даёт ноль строк, и запись
    # затирает рабочий корпус пустым файлом — так и случилось 10.09. Пустой результат
    # это отказ, а не результат.
    if not args.source.is_dir():
        print(f"источник не найден: {args.source} — корпус не тронут")
        return 2

    corpus = build_corpus(args.source, base_path=args.base)
    if not corpus["rows_total"]:
        print(f"в источнике {args.source} не найдено ни одной расценки — корпус не тронут")
        return 3
    # Неполный обход — повод остановиться: рабочий свод молча потерял бы часть архива.
    # Оператор может принять известные потери явным флагом; список остаётся в корпусе.
    if corpus["unreadable"] and not args.allow_unreadable:
        print(
            f"не прочитан{'ы' if len(corpus['unreadable']) > 1 else ''} "
            f"{len(corpus['unreadable'])} файл(ов), корпус не тронут: "
            + ", ".join(corpus["unreadable"][:5])
            + " (повторите с --allow-unreadable, если потери известны и приемлемы)"
        )
        return 4
    if corpus["unreadable"]:
        print(f"принято оператором, не прочитано книг: {', '.join(corpus['unreadable'][:5])}")

    _publish(args.out, corpus)

    print(f"строк расценок: {corpus['rows_total']}")
    for section, payload in sorted(corpus["sections"].items(), key=lambda kv: -len(kv[1]["norms"])):
        missing = sum(1 for item in payload["norms"] if item["in_base"] is False)
        state = f"вне базы {missing}" if corpus["base_checked"] else "база не проверялась"
        print(
            f"  {section:22} {len(payload['norms']):5} норм из {payload['applications']:6} применений"
            f" ({payload['files']} листов, {state})"
        )
    print(f"пропущено расчётов: {corpus['skipped']}")
    print(f"листов без раздела: {len(corpus['unresolved'])}")
    print(f"\nкорпус: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
