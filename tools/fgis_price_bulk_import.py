"""Наполнение/обновление ЛОКАЛЬНОЙ ценовой базы ФГИС ЦС («Сплит-форма» → Parquet). 0 LLM.

Зачем
=====
Цены ФГИС ЦС доступны ТОЛЬКО файлом-выгрузкой «Сплит-формы» на пару (ценовая зона,
период) — per-code JSON-API закрыт (401 Bearer; доказано в ``fgis_price_fetch_service``).
Поэтому «добор цены» = (пере)загрузка полной книги региона в локальный Parquet.
**Локальный Parquet И ЕСТЬ ценовая база.** Query-time костинг читает только его.

Канал-безопасно: короткий таймаут на метаданные + щедрый на файл, retry с лимитом,
вежливая пауза между регионами, graceful при сбое (регион пропускается, не падаем).

Запуск
------
    # один регион (СПб, 2 кв. 2025) — основной кейс:
    uv run python -m tools.fgis_price_bulk_import \
        --subject "Петербург" --quarter "2 квартал 2025" --name spb_2kv2025

    # несколько регионов одной командой (имена-stem генерятся из субъекта/квартала):
    uv run python -m tools.fgis_price_bulk_import \
        --subject "Петербург" --subject "Москва" --quarter "2 квартал 2025"

    # перечислить доступные субъекты / периоды зоны (разведка, без загрузки):
    uv run python -m tools.fgis_price_bulk_import --list-subjects
    uv run python -m tools.fgis_price_bulk_import --subject "Петербург" --list-periods

    # ПОЛНЫЙ добор всех регионов (часы; файл ≈8 МБ × ~85 субъектов): --all-subjects
    uv run python -m tools.fgis_price_bulk_import --all-subjects --quarter "2 квартал 2025"

    # через VPS-egress, если прямой канал режется: env LES_FGIS_VIA_SSH=root@HOST
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Any, Iterable, Optional

from proxy.services import fgis_price_fetch_service as pf


def _slug(subject: str, quarter: str) -> str:
    """('Санкт-Петербург', '2 квартал 2025 г.') → 'sankt-peterburg_2kv2025' (stem Parquet)."""
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya", " ": "-", "-": "-",
    }
    base = "".join(translit.get(ch, "") for ch in subject.casefold())
    base = re.sub(r"-+", "-", base).strip("-")
    qm = re.search(r"(\d)\s*квартал\D*(\d{4})", quarter.casefold())
    q = f"{qm.group(1)}kv{qm.group(2)}" if qm else re.sub(r"\W+", "", quarter.casefold())
    return f"{base}_{q}"


def run(
    *,
    subjects: list[str],
    quarter: str,
    name: Optional[str] = None,
    rate: float = 0.3,
    log: Any = sys.stderr,
) -> dict[str, Any]:
    """Загрузить книгу цен для каждого субъекта → Parquet. Возвращает сводку.

    name — переопределение stem (только при единственном субъекте); иначе авто-slug.
    rate — регионов/сек (вежливость к каналу); пауза = 1/rate между регионами.
    """
    delay = 1.0 / rate if rate > 0 else 0.0
    stats = {"done": 0, "failed": 0, "rows": 0, "books": []}

    def _emit(msg: str) -> None:
        print(msg, file=log, flush=True)

    for i, subject in enumerate(subjects):
        stem = name if (name and len(subjects) == 1) else _slug(subject, quarter)
        _emit(f"[..] {subject} / {quarter} → {stem}.parquet")
        res = pf.import_region(subject=subject, quarter=quarter, name=stem)
        if res.get("ok"):
            stats["done"] += 1
            stats["rows"] += res["rows"]
            stats["books"].append(res["name"])
            _emit(f"[ok] {res['region']} {res['quarter']}: {res['rows']} строк "
                  f"({res['bytes']//1024} КБ) → {res['parquet']}")
        else:
            stats["failed"] += 1
            _emit(f"[ERR] {subject}: stage={res.get('stage')} — {res.get('note')}")
        if delay and i < len(subjects) - 1:
            time.sleep(delay)
    return stats


def _main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Наполнение локальной ценовой базы ФГИС ЦС")
    ap.add_argument("--subject", action="append", default=[],
                    help="субъект РФ (подстрока, напр. 'Петербург'); можно несколько")
    ap.add_argument("--all-subjects", action="store_true",
                    help="все субъекты ФГИС ЦС (часы; ≈8 МБ × ~85)")
    ap.add_argument("--quarter", default="2 квартал 2025",
                    help="период (подстрока, напр. '2 квартал 2025')")
    ap.add_argument("--name", default=None,
                    help="stem Parquet (только при единственном субъекте; иначе авто-slug)")
    ap.add_argument("--rate", type=float, default=0.3, help="регионов/сек (вежливость, дефолт 0.3)")
    ap.add_argument("--list-subjects", action="store_true", help="перечислить субъекты и выйти")
    ap.add_argument("--list-periods", action="store_true",
                    help="перечислить периоды зоны (с --subject) и выйти")
    args = ap.parse_args(list(argv) if argv is not None else None)

    if args.list_subjects:
        for s in pf.list_subjects():
            print(f"{s['id']:>4}  {s['name']}")
        return 0

    if args.list_periods:
        if not args.subject:
            print("--list-periods требует --subject", file=sys.stderr)
            return 2
        subj = pf.resolve_subject(args.subject[0])
        if not subj:
            print(f"субъект {args.subject[0]!r} не найден", file=sys.stderr)
            return 1
        zones = pf.price_zones(subj["id"])
        if not zones:
            print(f"нет зон у {subj['name']!r}", file=sys.stderr)
            return 1
        for p in pf.periods(zones[0]["id"]):
            print(f"{p['id']:>4}  {p['name']}")
        return 0

    if args.all_subjects:
        subjects = [s["name"] for s in pf.list_subjects()]
    elif args.subject:
        subjects = args.subject
    else:
        ap.error("укажите --subject … (можно несколько) или --all-subjects, либо --list-subjects")
        return 2

    try:
        stats = run(subjects=subjects, quarter=args.quarter, name=args.name, rate=args.rate)
    except KeyboardInterrupt:
        print("\nпрервано (готовые книги сохранены порегионно)", file=sys.stderr)
        return 130
    print(f"OK: книг залито={stats['done']} ошибок={stats['failed']} | "
          f"+{stats['rows']} строк | {', '.join(stats['books'])}")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())
