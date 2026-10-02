#!/usr/bin/env python3
"""unpack_archives.py — препроцесс: распаковать архивы (.7z/.zip/.rar) перед индексацией.

ЛЕС индексирует файлы, не архивы. Этот шаг разворачивает архивы во вложенную папку
``<имя>__unpacked/`` рядом, чтобы их содержимое попало в обычный intake. Завершение
подтверждается marker с SHA архива и manifest файлов; частичный каталог проверяется
повторно. Пользовательские файлы не перезаписываются. .zip — stdlib; .7z — ``py7zr``;
.rar — ``rarfile``. Ошибка любого архива даёт ненулевой exit code.

  uv run python tools/unpack_archives.py "<папка>" --dry-run
  uv run python tools/unpack_archives.py "<папка>"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PureWindowsPath


_MARKER = ".les-unpack-complete.json"
_SCHEMA = "les.archive-completion.v1"
_STAGING_PREFIX = ".les-unpack-"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_path(root: Path, path: Path) -> Path:
    """Check both lexical scope and existing links before any filesystem write."""
    relative = path.absolute().relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink() or current.is_junction():
            raise ValueError(f"ссылки в пути распаковки запрещены: {current}")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"путь вне выбранной папки: {path}")
    return resolved


def _member_path(name: str) -> Path:
    """Use one portable name contract, including Windows drive/ADS rules."""
    windows = PureWindowsPath(name)
    parts = name.replace("\\", "/").rstrip("/").split("/")
    if windows.drive or windows.root or any(
        not part or part in {".", ".."} or ":" in part or "\x00" in part
        or part.endswith((".", " ")) or PureWindowsPath(part).is_reserved()
        or part.casefold() == _MARKER.casefold()
        for part in parts
    ):
        raise ValueError(f"небезопасное имя в архиве: {name!r}")
    return Path(*parts)


def _validate_names(names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        key = _member_path(name).as_posix().casefold()
        if key in seen:
            raise ValueError(f"повторяющееся имя в архиве: {name!r}")
        seen.add(key)


def _link_flag(item: object, name: str) -> bool:
    flag = getattr(item, name, False)
    return bool(flag() if callable(flag) else flag)


def _unpack_zip(path: Path, dest: Path) -> int:
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        _validate_names([info.filename for info in infos])
        for info in infos:
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError(f"ссылка или специальный файл в ZIP: {info.filename}")
        for info in infos:
            target = _checked_path(dest, dest / _member_path(info.filename))
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
        return sum(not info.is_dir() for info in infos)


def _unpack_7z(path: Path, dest: Path) -> int:
    try:
        import py7zr
    except ImportError:
        raise RuntimeError("для .7z нужен установленный py7zr; архив не распакован") from None
    with py7zr.SevenZipFile(path, "r") as z:
        _validate_names(z.getnames())
        files = getattr(z, "files", None)
        if files is None or any(not hasattr(item, "is_symlink") for item in files):
            raise RuntimeError("py7zr не предоставляет проверяемые сведения о ссылках")
        if any(_link_flag(item, kind) for item in files for kind in ("is_symlink", "is_junction", "is_socket")):
            raise ValueError("ссылка или специальный файл в 7z")
        z.extractall(dest)
        return len(z.getnames())


def _unpack_rar(path: Path, dest: Path) -> int:
    try:
        import rarfile
    except ImportError:
        raise RuntimeError("для .rar нужны установленные rarfile и unar/unrar; архив не распакован") from None
    with rarfile.RarFile(path) as r:
        infos = r.infolist()
        _validate_names([info.filename for info in infos])
        for info in infos:
            if not hasattr(info, "is_symlink") and not hasattr(info, "file_redir"):
                raise RuntimeError("rarfile не предоставляет проверяемые сведения о ссылках")
            if _link_flag(info, "is_symlink") or getattr(info, "file_redir", None):
                raise ValueError(f"ссылка в RAR: {info.filename}")
        r.extractall(dest)
        return len(r.namelist())


_HANDLERS = {".zip": _unpack_zip, ".7z": _unpack_7z, ".rar": _unpack_rar}


def _read_marker(root: Path, dest: Path) -> dict | None:
    path = _checked_path(root, dest / _MARKER)
    if not path.exists():
        return None
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ValueError(f"существующий marker не распознан и сохранён: {path}") from err
    if not isinstance(marker, dict) or marker.get("schema") != _SCHEMA:
        raise ValueError(f"существующий файл marker не принадлежит preprocess и сохранён: {path}")
    return marker


def _complete(root: Path, dest: Path, marker: dict | None, arc: Path, sha: str) -> bool:
    if marker is None or marker.get("source_sha256") != sha or marker.get("source_name") != arc.name:
        return False
    files, directories = marker.get("files"), marker.get("directories")
    if not isinstance(files, list) or not isinstance(directories, list):
        return False
    try:
        for item in files:
            path = _checked_path(root, dest / _member_path(item["path"]))
            if not path.is_file() or path.stat().st_size != item["size"] or _sha256(path) != item["sha256"]:
                return False
        return all(_checked_path(root, dest / _member_path(name)).is_dir() for name in directories)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _inventory(stage: Path) -> tuple[list[dict], list[str]]:
    files: list[dict] = []
    directories: list[str] = []
    for path in sorted(stage.rglob("*")):
        _checked_path(stage, path)
        name = path.relative_to(stage).as_posix()
        _member_path(name)
        if path.is_dir():
            directories.append(name)
        elif stat.S_ISREG(path.stat().st_mode):
            files.append({"path": name, "size": path.stat().st_size, "sha256": _sha256(path)})
        else:
            raise ValueError(f"специальный файл после распаковки: {name}")
    return files, directories


def _publish(root: Path, stage: Path, dest: Path, files: list[dict], directories: list[str]) -> None:
    """Check all conflicts first. Copy new files exclusively; retain identical files."""
    _checked_path(root, dest)
    if dest.exists() and not dest.is_dir():
        raise ValueError(f"вместо папки распаковки существует файл: {dest}")
    for name in directories:
        target = _checked_path(root, dest / _member_path(name))
        if target.exists() and not target.is_dir():
            raise ValueError(f"пользовательский файл конфликтует с папкой архива: {target}")
    for item in files:
        target = _checked_path(root, dest / _member_path(item["path"]))
        if target.exists() and (
            not target.is_file() or target.stat().st_size != item["size"] or _sha256(target) != item["sha256"]
        ):
            raise ValueError(f"пользовательский файл сохранён; конфликт с архивом: {target}")
    dest.mkdir(parents=True, exist_ok=True)
    for name in directories:
        _checked_path(root, dest / _member_path(name)).mkdir(parents=True, exist_ok=True)
    for item in files:
        target = _checked_path(root, dest / _member_path(item["path"]))
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with (stage / _member_path(item["path"])).open("rb") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _check_retired_owned_files(root: Path, dest: Path, previous: dict | None, files: list[dict]) -> None:
    """An updated archive must not silently retain obsolete searchable evidence."""
    if previous is None:
        return
    prior_files = previous.get("files")
    if not isinstance(prior_files, list):
        raise ValueError("предыдущий manifest файлов не распознан; marker сохранён")
    current_names = {_member_path(item["path"]).as_posix().casefold() for item in files}
    for item in prior_files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("предыдущий manifest файлов не распознан; marker сохранён")
        relative = _member_path(item["path"])
        if relative.as_posix().casefold() not in current_names:
            target = _checked_path(root, dest / relative)
            if target.exists():
                raise ValueError(
                    f"устаревший файл прежнего архива сохранён: {target}; "
                    "новая версия не отмечена завершённой, используйте отдельную папку"
                )


def _unpack(root: Path, arc: Path, dest: Path, sha: str, previous: dict | None) -> int:
    # Only this fresh, scope-checked temporary directory is cleaned up. User files
    # and incomplete destination directories are never removed.
    with tempfile.TemporaryDirectory(prefix=_STAGING_PREFIX, dir=root) as temp:
        stage = _checked_path(root, Path(temp))
        _HANDLERS[arc.suffix.lower()](arc, stage)
        files, directories = _inventory(stage)
        if _sha256(arc) != sha:
            raise ValueError("исходный архив изменился во время распаковки")
        _check_retired_owned_files(root, dest, previous, files)
        _publish(root, stage, dest, files, directories)
        marker = {"schema": _SCHEMA, "source_name": arc.name, "source_sha256": sha,
                  "files": files, "directories": directories}
        if not _complete(root, dest, marker, arc, sha) or _sha256(arc) != sha:
            raise ValueError("проверка файлов после распаковки не пройдена")
        if _read_marker(root, dest) != previous:
            raise ValueError("marker изменился во время распаковки; существующий файл сохранён")
        marker_temp = stage / _MARKER
        marker_temp.write_text(json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        marker_temp.replace(_checked_path(root, dest / _MARKER))
    return len(files)


def main() -> int:
    ap = argparse.ArgumentParser(description="Распаковать архивы перед индексацией ЛЕС")
    ap.add_argument("path", help="папка с архивами (рекурсивно)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        root = Path(args.path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("путь должен указывать на папку")
        archives = sorted(p for p in root.rglob("*") if p.suffix.lower() in _HANDLERS
                          and not p.is_dir() and not any(part.startswith(_STAGING_PREFIX) for part in p.relative_to(root).parts))
    except (OSError, ValueError) as err:
        print(f"Ошибка папки: {err}")
        return 1
    if not archives:
        print("Архивов не найдено."); return 0

    ok = skipped = failed = 0
    for arc in archives:
        dest = arc.parent / f"{arc.stem}__unpacked"
        try:
            _checked_path(root, arc)
            _checked_path(root, dest)
            if args.dry_run:
                print(f"  → {arc.name} → {dest.name}/")
                continue
            sha = _sha256(arc)
            marker = _read_marker(root, dest)
            if _complete(root, dest, marker, arc, sha):
                print(f"  ∙ подтверждённая распаковка: {arc.name}")
                skipped += 1
                continue
            n = _unpack(root, arc, dest, sha, marker)
            print(f"  ✔ {arc.name} → {dest.name}/ ({n} файлов)"); ok += 1
        except Exception as err:  # noqa: BLE001
            print(f"  ✗ {arc.name}: {err}"); failed += 1
    if not args.dry_run:
        print(f"\nраспаковано: {ok} · пропущено: {skipped} · ошибок: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
