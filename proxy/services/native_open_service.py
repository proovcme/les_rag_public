"""Cross-platform native document launcher for LES / Л.И.С.Т.

Safely opens original source documents in the OS default application (Excel, Word, Acrobat,
AutoCAD, Mail, etc.) without altering the original file content.

Supports Windows (Legion), macOS, and Linux, with path guard security verification.
"""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Any

from proxy.services.file_viewer_service import VIEWABLE_SUFFIXES


def _is_path_allowed(resolved_path: Path) -> bool:
    """Validate that the path is within permitted source directories."""
    if not resolved_path.exists() or not resolved_path.is_file():
        return False

    allowed_roots: list[Path] = [
        Path("storage").resolve(),
        Path("RAG_Content").resolve(),
        Path("data").resolve(),
        Path(".").resolve(),
    ]

    # Include LES_EXTERNAL_SOURCE_ROOTS from env if defined
    extra_roots = os.environ.get("LES_EXTERNAL_SOURCE_ROOTS", "")
    if extra_roots:
        for root in extra_roots.split(os.pathsep):
            cleaned = root.strip()
            if cleaned:
                allowed_roots.append(Path(cleaned).resolve())

    for root in allowed_roots:
        try:
            if resolved_path.is_relative_to(root):
                return True
        except ValueError:
            continue

    return False


def open_native_file(source_path: str | Path) -> dict[str, Any]:
    """Open a local file in the system default application.

    Returns status dict with ``opened`` or error detail. Never modifies original.
    """
    path = Path(source_path).expanduser().resolve()

    if not path.exists() or not path.is_file():
        return {
            "status": "not_found",
            "error": "Файл не найден на диске",
            "file_name": path.name,
            "source_path": path.as_posix(),
            "returncode": -1,
        }

    if not _is_path_allowed(path):
        return {
            "status": "forbidden",
            "error": "Доступ к пути за пределами разрешённых директорий ограничен",
            "file_name": path.name,
            "source_path": path.as_posix(),
            "returncode": -1,
        }

    try:
        if sys.platform == "win32":
            # Windows: os.startfile is built-in and executes default association
            if hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined] # noqa: S606
                returncode = 0
            else:
                completed = subprocess.run(
                    ["cmd", "/c", "start", "", str(path)],
                    check=False,
                    timeout=5,
                )
                returncode = completed.returncode
        elif sys.platform == "darwin":
            # macOS: open command
            completed = subprocess.run(
                ["open", str(path)],
                check=False,
                timeout=5,
            )
            returncode = completed.returncode
        else:
            # Linux: xdg-open
            completed = subprocess.run(
                ["xdg-open", str(path)],
                check=False,
                timeout=5,
            )
            returncode = completed.returncode

        status = "opened" if returncode == 0 else "open_failed"
        return {
            "status": status,
            "file_name": path.name,
            "source_path": path.as_posix(),
            "returncode": returncode,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "open_failed",
            "error": f"{type(exc).__name__}: {exc}",
            "file_name": path.name,
            "source_path": path.as_posix(),
            "returncode": -1,
        }
