#!/usr/bin/env python3
"""PDF-препроцессор комплектов перед индексацией — W1.3 (LES3_PLAN).

Спека 2026-06-07 + правки Приложения А:
  1) оригиналы НЕ удаляются — перемещаются в _originals/ (удаление только --delete-originals);
  2) идемпотентность: .pdf_preprocess_state.json (mtime+size) — обработанное пропускается,
     иначе очистка меняет mtime и метабаза переиндексирует уже готовые файлы;
  3) сплит по структуре: жадная упаковка страниц по фактическим байтам с подтяжкой границ
     к закладкам верхнего уровня; в metadata частей пишется JSON {part_index, part_total,
     original_name};
  4) лечение причины таймаутов (постраничная конвертация) — отдельно, W1.4.

Очистка: garbage=4 + deflate (+deflate_images). Файлы > max-mb после очистки режутся
на части `_частьN.pdf`. Никогда не бросает исключений из preprocess_dir.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

STATE_FILE = ".pdf_preprocess_state.json"
ARCHIVE_DIRNAME = "_originals"
DEFAULT_MAX_MB = 40
PART_SUFFIX = "_часть"
# Подтяжка границы части к закладке: ищем закладку в пределах ±10% страниц части.
TOC_SNAP_WINDOW = 0.10


def log(event: str, **fields) -> None:
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **fields}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


@dataclass
class CleanResult:
    path: Path
    original_bytes: int
    new_bytes: int


@dataclass
class SplitResult:
    original_path: Path  # перемещён в _originals/ (или удалён при --delete-originals)
    parts: list[Path]


@dataclass
class FileResult:
    path: Path
    action: Literal["clean", "clean+split", "skip", "error"]
    clean: CleanResult | None = None
    split: SplitResult | None = None
    error: str | None = None


# ── состояние (идемпотентность, правка 2) ──


def _load_state(directory: Path) -> dict:
    state_path = directory / STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_state(directory: Path, state: dict) -> None:
    (directory / STATE_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8"
    )


def _stat_sig(path: Path) -> dict:
    st = path.stat()
    return {"mtime": round(st.st_mtime, 3), "size": st.st_size}


def _is_processed(state: dict, rel: str, path: Path) -> bool:
    entry = state.get(rel)
    return bool(entry) and entry == _stat_sig(path)


# ── очистка ──


def clean_pdf(src: Path, archive_dir: Path | None = None) -> CleanResult:
    """garbage=4 + deflate; оригинал предварительно архивируется (правка 1)."""
    import fitz

    original_bytes = src.stat().st_size
    if archive_dir is not None:
        archive_dir.mkdir(parents=True, exist_ok=True)
        backup = archive_dir / src.name
        if not backup.exists():
            shutil.copy2(src, backup)

    tmp = src.with_name(src.stem + "_tmp" + src.suffix)
    doc = fitz.open(src)
    try:
        doc.save(tmp, garbage=4, deflate=True, deflate_images=True)
    finally:
        doc.close()
    tmp.replace(src)
    return CleanResult(path=src, original_bytes=original_bytes, new_bytes=src.stat().st_size)


# ── сплит (правка 3) ──


def _toc_pages(doc) -> list[int]:
    """0-based страницы закладок верхнего уровня."""
    try:
        return sorted({entry[2] - 1 for entry in doc.get_toc(simple=True) if entry[0] == 1 and entry[2] >= 1})
    except Exception:
        return []


def _snap_to_toc(boundary: int, toc_pages: list[int], window: int) -> int:
    """Ближайшая закладка в пределах окна; иначе исходная граница."""
    best = boundary
    best_dist = window + 1
    for page in toc_pages:
        dist = abs(page - boundary)
        if dist <= window and dist < best_dist:
            best, best_dist = page, dist
    return best


def _part_ranges(doc, max_bytes: int) -> list[tuple[int, int]]:
    """Диапазоны страниц частей: равные доли + подтяжка границ к закладкам."""
    total_pages = doc.page_count
    total_bytes = len(doc.tobytes(garbage=2, deflate=True))
    n_parts = max(2, math.ceil(total_bytes / int(max_bytes * 0.9)))
    n_parts = min(n_parts, total_pages)  # часть не может быть меньше страницы
    per_part = total_pages / n_parts
    toc = _toc_pages(doc)
    window = max(1, int(per_part * TOC_SNAP_WINDOW))

    boundaries = [0]
    for i in range(1, n_parts):
        raw = round(i * per_part)
        snapped = _snap_to_toc(raw, toc, window)
        if snapped <= boundaries[-1]:
            snapped = max(raw, boundaries[-1] + 1)
        boundaries.append(min(snapped, total_pages - 1))
    boundaries.append(total_pages)
    return [(boundaries[i], boundaries[i + 1] - 1) for i in range(n_parts) if boundaries[i] <= boundaries[i + 1] - 1]


def _write_part(doc, start: int, end: int, out_path: Path, part_index: int, part_total: int, original_name: str) -> None:
    import fitz

    part = fitz.open()
    try:
        part.insert_pdf(doc, from_page=start, to_page=end)
        part.set_metadata({
            **doc.metadata,
            "subject": json.dumps(
                {"part_index": part_index, "part_total": part_total, "original_name": original_name},
                ensure_ascii=False,
            ),
        })
        tmp = out_path.with_name(out_path.stem + "_tmp" + out_path.suffix)
        part.save(tmp, garbage=4, deflate=True)
        tmp.replace(out_path)
    finally:
        part.close()


def split_pdf(
    src: Path,
    max_bytes: int = DEFAULT_MAX_MB * 1024 * 1024,
    archive_dir: Path | None = None,
    delete_original: bool = False,
) -> SplitResult:
    """Режет src на части < max_bytes. Атомарно: tmp→rename; при сбое — tmp удаляются,
    оригинал не тронут. Успех: оригинал в архив (правка 1) или удалён по флагу."""
    import fitz

    doc = fitz.open(src)
    written: list[Path] = []
    try:
        ranges = _part_ranges(doc, max_bytes)
        part_total = len(ranges)
        for idx, (start, end) in enumerate(ranges, 1):
            out_path = src.with_name(f"{src.stem}{PART_SUFFIX}{idx}{src.suffix}")
            _write_part(doc, start, end, out_path, idx, part_total, src.name)
            written.append(out_path)
            if out_path.stat().st_size > max_bytes and (end - start) > 0:
                # страховка: часть всё ещё велика — бисекция диапазона
                out_path.unlink()
                written.pop()
                mid = (start + end) // 2
                for sub_idx, (s, e) in enumerate(((start, mid), (mid + 1, end))):
                    sub_path = src.with_name(f"{src.stem}{PART_SUFFIX}{idx}.{sub_idx + 1}{src.suffix}")
                    _write_part(doc, s, e, sub_path, idx, part_total, src.name)
                    written.append(sub_path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        for tmp in src.parent.glob(f"{src.stem}{PART_SUFFIX}*_tmp{src.suffix}"):
            tmp.unlink(missing_ok=True)
        doc.close()
        raise
    doc.close()

    if archive_dir is not None and not delete_original:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), archive_dir / src.name)
    else:
        src.unlink()
    return SplitResult(original_path=src, parts=written)


# ── обход каталога ──


def preprocess_dir(
    directory: Path,
    max_bytes: int = DEFAULT_MAX_MB * 1024 * 1024,
    dry_run: bool = False,
    delete_originals: bool = False,
) -> list[FileResult]:
    """Очистка+сплит всех *.pdf. Никогда не бросает; ошибки — в FileResult."""
    results: list[FileResult] = []
    if not directory.exists():
        return results
    state = _load_state(directory)
    archive_dir = directory / ARCHIVE_DIRNAME
    saved_mb_total = 0.0
    errors = 0

    for pdf in sorted(directory.rglob("*.pdf")):
        if archive_dir in pdf.parents or pdf.name.startswith("."):
            continue
        rel = pdf.relative_to(directory).as_posix()
        if _is_processed(state, rel, pdf):
            results.append(FileResult(path=pdf, action="skip"))
            continue
        if dry_run:
            would_split = pdf.stat().st_size > max_bytes
            log("dry_run", file=rel, size_mb=round(pdf.stat().st_size / 2**20, 1), would_split=would_split)
            results.append(FileResult(path=pdf, action="skip"))
            continue
        try:
            clean = clean_pdf(pdf, archive_dir=archive_dir)
            saved_mb = (clean.original_bytes - clean.new_bytes) / 2**20
            saved_mb_total += max(0.0, saved_mb)
            log("clean", file=rel, before_mb=round(clean.original_bytes / 2**20, 1),
                after_mb=round(clean.new_bytes / 2**20, 1), saved_mb=round(saved_mb, 1))
            if clean.new_bytes > max_bytes:
                split = split_pdf(pdf, max_bytes=max_bytes, archive_dir=archive_dir,
                                  delete_original=delete_originals)
                log("split", file=rel, parts=len(split.parts),
                    part_files=[p.name for p in split.parts])
                state.pop(rel, None)
                for part in split.parts:
                    state[part.relative_to(directory).as_posix()] = _stat_sig(part)
                results.append(FileResult(path=pdf, action="clean+split", clean=clean, split=split))
            else:
                state[rel] = _stat_sig(pdf)
                results.append(FileResult(path=pdf, action="clean", clean=clean))
        except Exception as err:
            reason = "permission_denied" if isinstance(err, PermissionError) else "open_failed"
            log("skip", file=rel, reason=reason, error=str(err)[:200])
            results.append(FileResult(path=pdf, action="error", error=str(err)))
            errors += 1

    if not dry_run:
        _save_state(directory, state)
    processed = sum(1 for r in results if r.action in ("clean", "clean+split"))
    log("summary", processed=processed, skipped=sum(1 for r in results if r.action == "skip"),
        errors=errors, saved_mb=round(saved_mb_total, 1))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Очистка и нарезка PDF перед индексацией (W1.3)")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delete-originals", action="store_true",
                        help="удалять оригинал после сплита (по умолчанию — в _originals/)")
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"Каталог не найден: {args.directory}", file=sys.stderr)
        return 1
    results = preprocess_dir(
        args.directory,
        max_bytes=int(args.max_mb * 1024 * 1024),
        dry_run=args.dry_run,
        delete_originals=args.delete_originals,
    )
    return 2 if any(r.action == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
