"""Пакетная обработка стройсканов: папка → по каждому листу детект таблиц (CV) →
классификация типа + извлечение → отчёт «что в пачке».

Автономно (без оператора): большие чертежи обрабатываются тоже — table_detect
находит таблицы-регионы вместо ручной рамки, каждый регион классифицируется и
извлекается. LLM-минимализм: детект и классификация — детерминированы; vision
только на извлечение содержимого региона.

    uv run python tools/scan_batch.py "<папка>" --max-files 5 --max-tables 3 --out data/batch_out
    uv run python tools/scan_batch.py "<папка>" --classify-only      # быстрая разведка типов
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy.services import table_detect  # noqa: E402
from proxy.services.verify_service import (  # noqa: E402
    _load_page_image, _safe_path, classify_region, render_and_extract,
)

EXTS = (".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg")


def _files(target: str) -> list[str]:
    if os.path.isdir(target):
        out = []
        for ext in EXTS:  # рекурсивно — сканы лежат и в подпапках
            out += glob.glob(os.path.join(target, "**", f"*{ext}"), recursive=True)
            out += glob.glob(os.path.join(target, "**", f"*{ext.upper()}"), recursive=True)
        return sorted(set(out))
    return sorted(glob.glob(target))


def process_file(path: str, max_tables: int, classify_only: bool) -> dict:
    rec: dict = {"file": os.path.basename(path), "tables": [], "error": None}
    try:
        img = _load_page_image(_safe_path(path), 0)
        rec["img"] = list(img.size)
        regions = table_detect.detect_table_regions(img)
        rec["n_regions"] = len(regions)
        for reg in regions[:max_tables]:
            if classify_only:  # дёшево: тип по названию+шапке, без построчного извлечения
                dt = classify_region(path, 0, reg)
                if dt.get("type") == "неизвестно":
                    continue  # шум (легенда/рамка/штамп) — не таблица данных
                rec["tables"].append({
                    "region": [round(v, 3) for v in reg],
                    "type": dt.get("label"), "route": dt.get("route"),
                    "confidence": dt.get("confidence"),
                })
                continue
            res = render_and_extract(path, 0, "local", region=reg)
            rows = res.get("rows") or []
            if not rows:
                continue
            dt = res.get("doc_type") or {}
            rec["tables"].append({
                "region": [round(v, 3) for v in reg],
                "type": dt.get("label"), "route": dt.get("route"),
                "confidence": dt.get("confidence"), "n_rows": len(rows),
                "columns": res.get("columns"), "rows": rows,
            })
    except Exception as exc:  # один битый файл не валит пакет
        rec["error"] = str(exc)[:160]
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Пакетная обработка стройсканов по типу таблиц.")
    ap.add_argument("target", help="папка или glob со сканами")
    ap.add_argument("--max-files", type=int, default=0, help="ограничить число файлов (0=все)")
    ap.add_argument("--max-tables", type=int, default=3, help="макс. таблиц на лист")
    ap.add_argument("--classify-only", action="store_true", help="только детект таблиц, без vision-извлечения")
    ap.add_argument("--out", default="data/batch_out", help="куда сложить результаты")
    args = ap.parse_args(argv)

    files = _files(args.target)
    if args.max_files:
        files = files[: args.max_files]
    if not files:
        print("файлов не найдено"); return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"пакет: {len(files)} файлов, max_tables={args.max_tables}, "
          f"режим={'разведка' if args.classify_only else 'извлечение'}\n")

    results = []
    t0 = time.time()
    by_type: dict[str, int] = {}
    total_rows = 0
    for i, f in enumerate(files, 1):
        rec = process_file(f, args.max_tables, args.classify_only)
        results.append(rec)
        tabs = rec.get("tables") or []
        for t in tabs:
            by_type[t.get("type") or "—"] = by_type.get(t.get("type") or "—", 0) + 1
            total_rows += t.get("n_rows", 0)
        if tabs:
            tag = f"{len(tabs)} табл: " + ", ".join(
                t["type"] + (f"({t['n_rows']})" if t.get("n_rows") is not None else "") for t in tabs)
        elif args.classify_only:
            tag = f"{rec.get('n_regions', 0)} регионов — тип не опознан"
        else:
            tag = "таблиц с данными нет"
        print(f"[{i}/{len(files)}] {rec['file'][:58]:60} → {tag}" + (f"  ОШИБКА:{rec['error']}" if rec.get("error") else ""))

    (out_dir / "batch_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== ИТОГ за {time.time() - t0:.0f}с ===")
    print(f"файлов: {len(files)} | таблиц с данными: {sum(len(r.get('tables') or []) for r in results)} | строк: {total_rows}")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")
    print(f"\nдетали → {out_dir / 'batch_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
