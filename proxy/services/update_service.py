"""Explicit, operator-triggered LES release checks and Windows installer launch."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from proxy.services.version_service import LES_VERSION


REPOSITORY = os.getenv("LES_UPDATE_REPOSITORY", "proovcme/les_rag_public").strip()
UPDATE_MANIFEST_URL = os.getenv(
    "LES_UPDATE_MANIFEST_URL",
    f"https://github.com/{REPOSITORY}/releases/latest/download/latest.json",
).strip()
INSTALLER_ASSET = "LES-Setup.exe"
CHECKSUM_ASSET = f"{INSTALLER_ASSET}.sha256"
_SHA256 = re.compile(r"\b([0-9a-fA-F]{64})\b")


class UpdateError(RuntimeError):
    pass


def version_tuple(value: str) -> tuple[int, ...]:
    normalized = str(value or "").strip().lstrip("vV")
    parts = normalized.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise UpdateError(f"Некорректная версия выпуска: {value!r}")
    return tuple(int(part) for part in parts)


def release_summary(payload: dict, *, current_version: str = LES_VERSION) -> dict:
    if payload.get("schema") != "les.update.v1":
        raise UpdateError("Неподдерживаемая схема файла обновления")
    latest = str(payload.get("version") or "").strip().lstrip("vV")
    current_key = version_tuple(current_version)
    latest_key = version_tuple(latest)
    tag = f"v{latest}"
    release_root = f"https://github.com/{REPOSITORY}/releases/download/{tag}"
    installer_url = f"{release_root}/{INSTALLER_ASSET}"
    checksum_url = f"{release_root}/{CHECKSUM_ASSET}"
    available = latest_key > current_key
    return {
        "current_version": current_version,
        "latest_version": latest,
        "available": available,
        "install_supported": sys.platform.startswith("win"),
        "package_complete": True,
        "name": str(payload.get("name") or tag),
        "notes": str(payload.get("notes") or "")[:4000],
        "published_at": payload.get("published_at"),
        "html_url": payload.get("html_url") or f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
        "installer_url": installer_url,
        "checksum_url": checksum_url,
    }


async def check_update(*, client: httpx.AsyncClient | None = None) -> dict:
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        if not _trusted_release_url(UPDATE_MANIFEST_URL):
            raise UpdateError("Задан недоверенный адрес файла обновления")
        response = await client.get(
            UPDATE_MANIFEST_URL,
            headers={"User-Agent": "LES-updater"},
        )
        response.raise_for_status()
        return release_summary(response.json())
    except UpdateError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise UpdateError(f"Не удалось проверить выпуск: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()


def update_root() -> Path:
    configured = os.getenv("LES_WINDOWS_STATE_ROOT", "").strip()
    if configured:
        root = Path(configured)
    else:
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if not local_app_data:
            raise UpdateError("LOCALAPPDATA не задан; обновление доступно только в Windows-сборке")
        root = Path(local_app_data) / "LES"
    return root / "artifacts" / "updates"


def _trusted_release_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in {"github.com", "objects.githubusercontent.com"}


def parse_checksum(text: str) -> str:
    match = _SHA256.search(text or "")
    if not match:
        raise UpdateError("В выпуске отсутствует корректная контрольная сумма SHA-256")
    return match.group(1).lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


async def _download(client: httpx.AsyncClient, url: str, target: Path, *, max_bytes: int) -> None:
    if not _trusted_release_url(url):
        raise UpdateError("Выпуск содержит недоверенный адрес загрузки")
    temporary = target.with_suffix(target.suffix + ".part")
    temporary.unlink(missing_ok=True)
    total = 0
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                async for block in response.aiter_bytes():
                    total += len(block)
                    if total > max_bytes:
                        raise UpdateError("Файл обновления превышает допустимый размер")
                    output.write(block)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


async def download_and_launch_update() -> dict:
    if not sys.platform.startswith("win"):
        raise UpdateError("Установка обновления этой кнопкой поддерживается только в Windows-сборке")
    info = await check_update()
    if not info["available"]:
        raise UpdateError("Новая версия не найдена")
    if not info["package_complete"]:
        raise UpdateError("В выпуске нет installer или файла SHA-256")

    root = update_root() / info["latest_version"]
    root.mkdir(parents=True, exist_ok=True)
    installer = root / INSTALLER_ASSET
    checksum = root / CHECKSUM_ASSET
    async with httpx.AsyncClient(timeout=1200.0, follow_redirects=True) as client:
        await _download(client, info["checksum_url"], checksum, max_bytes=16 * 1024)
        await _download(client, info["installer_url"], installer, max_bytes=1024 * 1024 * 1024)

    expected = parse_checksum(checksum.read_text(encoding="utf-8", errors="replace"))
    actual = sha256_file(installer)
    if actual != expected:
        installer.unlink(missing_ok=True)
        raise UpdateError(f"Контрольная сумма обновления не совпала: ожидалось {expected}, получено {actual}")

    subprocess.Popen([str(installer)], cwd=str(root), close_fds=True)  # noqa: S603 — verified local artifact
    return {
        **info,
        "status": "installer_launched",
        "sha256": actual,
        "installer": str(installer),
    }
