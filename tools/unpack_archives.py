#!/usr/bin/env python3
"""unpack_archives.py — препроцесс: распаковать архивы (.7z/.zip/.rar) перед индексацией.

ЛЕС индексирует файлы, не архивы. Этот шаг разворачивает архивы во вложенную папку
``<имя>__unpacked/`` рядом, чтобы их содержимое попало в обычный intake. Идемпотентно
(пропускает уже распакованные). .zip — stdlib; .7z — нужен ``py7zr`` (pip); .rar — ``rarfile``.

  uv run python tools/unpack_archives.py "<папка>" --dry-run
  uv run python tools/unpack_archives.py "<папка>"
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def _unpack_zip(path: Path, dest: Path) -> int:
    with zipfile.ZipFile(path) as z:
        z.extractall(dest)
        return len(z.namelist())


def _unpack_7z(path: Path, dest: Path) -> int:
    try:
        import py7zr
    except ImportError:
        raise RuntimeError("для .7z нужен py7zr: uv pip install py7zr")
    with py7zr.SevenZipFile(path, "r") as z:
        z.extractall(dest)
        return len(z.getnames())


def _unpack_rar(path: Path, dest: Path) -> int:
    try:
        import rarfile
    except ImportError:
        raise RuntimeError("для .rar нужен rarfile + unar/unrar: uv pip install rarfile")
    with rarfile.RarFile(path) as r:
        r.extractall(dest)
        return len(r.namelist())


_HANDLERS = {".zip": _unpack_zip, ".7z": _unpack_7z, ".rar": _unpack_rar}


def main() -> int:
    ap = argparse.ArgumentParser(description="Распаковать архивы перед индексацией ЛЕС")
    ap.add_argument("path", help="папка с архивами (рекурсивно)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.path)
    archives = [p for p in root.rglob("*") if p.suffix.lower() in _HANDLERS]
    if not archives:
        print("Архивов не найдено."); return 0

    ok = skipped = failed = 0
    for arc in archives:
        dest = arc.parent / f"{arc.stem}__unpacked"
        if dest.exists():
            print(f"  ∙ уже распакован: {arc.name}"); skipped += 1; continue
        if args.dry_run:
            print(f"  → {arc.name} → {dest.name}/"); continue
        try:
            dest.mkdir(parents=True, exist_ok=True)
            n = _HANDLERS[arc.suffix.lower()](arc, dest)
            print(f"  ✔ {arc.name} → {dest.name}/ ({n} файлов)"); ok += 1
        except Exception as err:  # noqa: BLE001
            print(f"  ✗ {arc.name}: {err}"); failed += 1
            if dest.exists() and not any(dest.iterdir()):
                dest.rmdir()
    if not args.dry_run:
        print(f"\nраспаковано: {ok} · пропущено: {skipped} · ошибок: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
