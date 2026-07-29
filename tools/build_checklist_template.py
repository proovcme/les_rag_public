#!/usr/bin/env python3
"""CLI-генератор боевого ChecklistTemplate JSON из XLSX чек-листа Glorax (T1.3).

Тонкая обёртка над `proxy.services.checklist_template_importer.import_checklist_template`:
читает исходный XLSX, строит template и пишет его на диск как JSON
(`ensure_ascii=False, indent=2` — читаемая кириллица, без принудительной сортировки ключей,
порядок items сохраняется как есть — по листам/строкам, как в исходнике).

Утилита для всех будущих прогонов (ПД сейчас, РД — Phase 7): исходные XLSX Glorax часто
открыты оператором в Excel во время прогона, из-за чего `openpyxl.load_workbook()` падает
с `PermissionError` при попытке читать файл напрямую (Windows file lock). В этом случае
генератор автоматически копирует файл во временную директорию (`tempfile.mkdtemp`), читает
копию, и удаляет временную директорию по завершении — независимо от исхода.

Использование:
    uv run python tools/build_checklist_template.py \
        --xlsx "C:/.../Чек_лист_входного_контроля_ПД_ГИПы_БУП.xlsx" \
        --stage PD \
        --name glorax_pd_2026 \
        --out config/checklists/glorax_pd_2026.json \
        --overrides config/checklists/glorax_pd_2026_overrides.json

`--overrides` (T1.4, опционально) — путь к JSON-файлу ручных правок классификации `kind`
(и опционально `comment`) по `item_id`: `{"PD-OB-007": {"kind": "manual_required",
"comment": "..."}}`. Применяются ПОСЛЕ эвристики `_classify_kind`
(`proxy/services/checklist_template_importer.import_checklist_template`) — используется,
когда инженер при просмотре результата находит конкретную ошибку автоматической
классификации, не покрываемую общим правилом (см. `docs/ALGO-glorax-checklist-review.md`).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxy.services.checklist_template_importer import import_checklist_template


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", required=True, type=Path, help="Путь к исходному XLSX чек-листа")
    parser.add_argument("--stage", required=True, choices=["PD", "RD"], help="Стадия: PD или RD")
    parser.add_argument("--name", required=True, help="Имя шаблона (записывается в поле 'name')")
    parser.add_argument("--out", required=True, type=Path, help="Путь к выходному JSON")
    parser.add_argument(
        "--overrides",
        required=False,
        type=Path,
        default=None,
        help=(
            "Путь к JSON-файлу ручных правок kind по item_id "
            "(config/checklists/glorax_pd_2026_overrides.json), применяются после эвристики"
        ),
    )
    return parser.parse_args(argv)


def _import_with_locked_file_fallback(
    xlsx_path: Path, stage: str, *, overrides: dict | None = None
) -> dict:
    """Импортирует template; при PermissionError (файл открыт в Excel) читает read-only
    копию во временной директории и удаляет её после прогона независимо от исхода."""
    try:
        return import_checklist_template(xlsx_path, stage=stage, overrides=overrides)
    except PermissionError:
        tmp_dir = Path(tempfile.mkdtemp(prefix="checklist_template_"))
        try:
            tmp_copy = tmp_dir / xlsx_path.name
            shutil.copy2(xlsx_path, tmp_copy)
            return import_checklist_template(tmp_copy, stage=stage, overrides=overrides)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _load_overrides(path: Path | None) -> dict:
    """Читает overrides-файл, игнорируя служебный ключ `_comment` (не item_id)."""
    if path is None:
        return {}
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    overrides = _load_overrides(args.overrides)
    template = _import_with_locked_file_fallback(args.xlsx, stage=args.stage, overrides=overrides)
    template["name"] = args.name

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
        f.write("\n")

    item_count = len(template["items"])
    disc_count = len(template["disciplines"])
    overrides_note = f", {len(overrides)} overrides применено" if overrides else ""
    print(f"OK: {args.out} — {item_count} items, {disc_count} дисциплин{overrides_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
