"""Explicit, operator-triggered LES release checks and Windows installer launch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import base64
from pathlib import Path
from pathlib import PurePosixPath
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
VPS_PATCH_MANIFEST_URL = os.getenv(
    "LES_VPS_PATCH_MANIFEST_URL", "https://les.ovc.me/updates/latest.json"
).strip()
VPS_PATCH_FEED_SCHEMA = "les.vps-patch-feed.v1"
VPS_PATCH_SCHEMA = "les.vps-patch.v2"
VPS_PATCH_ALLOWED_ROOTS = ("backend/", "proxy/", "sovushka/", "config/prompts/", "skills/", "docs/")
MAC_UPDATE_FEED_SCHEMA = "les.mac-update-feed.v1"
MAC_UPDATE_SCHEMA = "les.mac-update.v1"
MAC_UPDATE_DENIED_PARTS = {
    ".env",
    ".git",
    "__pycache__",
    "data",
    "storage",
    "RAG_Content",
    "local_private_archive",
    "dist",
    "installers",
    "desktop",
}
MAC_UPDATE_ALLOWED_ROOTS = (
    "proxy/",
    "backend/",
    "sovushka/",
    "tools/",
    "config/",
    "skills/",
    "qdrant_visualizer/",
)
MAC_UPDATE_ALLOWED_FILES = {"sovushka_ng.py", "proxy_server.py", "mlx_host.py"}
MAC_UPDATE_ALLOWED_SUFFIXES = {
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".js",
}
VPS_PATCH_ALLOWED_FILES = {
    "sovushka_ng.py",
    "proxy_server.py",
    "tools/vps_patch_apply.py",
    "tools/windows_update_engine.py",
    "config/version.json",
    "installers/windows/start-light.ps1",
    "installers/windows/stop-light.ps1",
    "installers/windows/runtime-process.ps1",
    "installers/windows/state.ps1",
    "installers/windows/app/bootstrap.ps1",
}
VPS_PATCH_DENIED_PARTS = {"__pycache__", ".git", "migrations", "baseline", "desktop"}
VPS_PATCH_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".css", ".js", ".html", ".ps1"}
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
    build_number = int(payload.get("build_number") or 0)
    target_commit = str(
        payload.get("commit")
        or payload.get("target_commit")
        or payload.get("build_commit")
        or ""
    )
    desktop_version = str(payload.get("desktop_version") or "")
    identity_complete = (
        build_number > 0
        and re.fullmatch(r"[0-9a-f]{40}", target_commit) is not None
        and re.fullmatch(r"\d+\.\d+\.\d+", desktop_version) is not None
    )
    return {
        "current_version": current_version,
        "latest_version": latest,
        "available": available,
        "install_supported": sys.platform.startswith("win"),
        "package_complete": identity_complete,
        "build_number": build_number,
        "target_commit": target_commit,
        "desktop_version": desktop_version,
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


def _trusted_patch_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname == "les.ovc.me" and parsed.path.startswith("/updates/")


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


async def _download(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    *,
    max_bytes: int,
    trusted_url=_trusted_release_url,
) -> None:
    if not trusted_url(url):
        raise UpdateError("Обновление содержит недоверенный адрес загрузки")
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
        raise UpdateError(
            "Полный выпуск не содержит точный commit, build number или версию оболочки"
        )

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

    application = application_root()
    state_root = update_root().parents[1]
    helper = root / "windows_update_engine.py"
    shutil.copy2(runtime_root() / "tools" / "windows_update_engine.py", helper)
    status = hard_update_status_path()
    job = root / "hard-update-job.json"
    update_id = f"release-{info['latest_version']}-{info['build_number']}"
    job.write_text(
        json.dumps(
            {
                "schema": "les.windows-hard-update.v1",
                "update_id": update_id,
                "installer": str(installer),
                "installer_sha256": actual,
                "install_root": str(application),
                "state_root": str(state_root),
                "status_path": str(status),
                "product_version": info["latest_version"],
                "build_number": info["build_number"],
                "desktop_version": info["desktop_version"],
                "target_commit": info["target_commit"],
                "branch": "release",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    task_name, encoded_command = _detached_task_command(
        helper,
        f'"{helper}" --job "{job}"',
        update_id,
        prefix="LES-Hard-Update",
    )
    job_payload = json.loads(job.read_text(encoding="utf-8"))
    job_payload["helper_task_name"] = task_name
    job.write_text(
        json.dumps(job_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    status.write_text(
        json.dumps(
            {
                "schema": "les.windows-hard-update-status.v1",
                "state": "starting",
                "stage": "downloaded",
                "update_id": update_id,
                "message": "Выпуск проверен; готовлю замену приложения",
                "helper_task_name": task_name,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    launched = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_command],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        creationflags=0x08000000,
    )
    if launched.returncode != 0:
        raise UpdateError("Windows не смог запустить транзакцию переустановки")
    return {
        **info,
        "status": "starting",
        "state": "starting",
        "sha256": actual,
        "installer": str(installer),
        "update_id": update_id,
        "message": "Выпуск проверен и передан транзакционному установщику",
    }


def runtime_root() -> Path:
    return Path(__file__).resolve().parents[2]


def application_root() -> Path:
    runtime = runtime_root()
    candidates = (runtime.parent, runtime.parent.parent)
    for candidate in candidates:
        if (candidate / "les-desktop.exe").is_file():
            return candidate
    raise UpdateError("Не удалось определить корень установленного приложения")


def patch_status_path() -> Path:
    return update_root() / "vps-patch-status.json"


def hard_update_status_path() -> Path:
    return update_root() / "hard-update-status.json"


def read_hard_update_status() -> dict:
    path = hard_update_status_path()
    if not path.is_file():
        return {
            "schema": "les.windows-hard-update-status.v1",
            "state": "idle",
            "message": "Переустановка выпуска не запускалась",
        }
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {
            "schema": "les.windows-hard-update-status.v1",
            "state": "failed",
            "message": "Не удалось прочитать состояние переустановки",
        }


def _ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _detached_task_command(
    helper: Path,
    arguments: str,
    update_id: str,
    *,
    prefix: str,
) -> tuple[str, str]:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "-", update_id)[:32] or "update"
    task_name = f"{prefix}-{safe_id}"
    python_executable = Path(sys.executable)
    pythonw = python_executable.with_name("pythonw.exe")
    if pythonw.is_file():
        python_executable = pythonw
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$name={_ps_literal(task_name)}; "
        "Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue; "
        f"$action=New-ScheduledTaskAction -Execute {_ps_literal(str(python_executable))} "
        f"-Argument {_ps_literal(arguments)}; "
        "$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1); "
        "$principal=New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited; "
        "Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null; "
        "Start-ScheduledTask -TaskName $name"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return task_name, encoded


def _patch_task_command(helper: Path, job: Path, patch_id: str) -> tuple[str, str]:
    return _detached_task_command(
        helper,
        f'"{helper}" --job "{job}"',
        patch_id,
        prefix="LES-Patch",
    )


def _validate_patch_feed(payload: dict) -> dict:
    if payload.get("schema") != VPS_PATCH_FEED_SCHEMA:
        raise UpdateError("Неподдерживаемая схема быстрого обновления")
    patch = payload.get("patch")
    if not isinstance(patch, dict) or patch.get("schema") != VPS_PATCH_SCHEMA:
        raise UpdateError("Манифест быстрого обновления повреждён")
    product_version = str(patch.get("product_version") or "")
    build_number = int(patch.get("build_number") or 0)
    target_commit = str(patch.get("target_commit") or "")
    base_commit = str(patch.get("base_commit") or "")
    patch_id = str(patch.get("patch_id") or "")
    if (
        not product_version
        or build_number <= 0
        or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", patch_id)
        or not re.fullmatch(r"[0-9a-f]{40}", base_commit)
        or not re.fullmatch(r"[0-9a-f]{40}", target_commit)
    ):
        raise UpdateError("В быстром обновлении отсутствует безопасный id, версия, сборка или commit")
    archive_url = str(payload.get("archive_url") or "")
    archive_sha256 = str(payload.get("archive_sha256") or "").lower()
    if not _trusted_patch_url(archive_url) or not re.fullmatch(r"[0-9a-f]{64}", archive_sha256):
        raise UpdateError("Быстрое обновление опубликовано с недоверенного адреса или без SHA-256")
    files = patch.get("files")
    if not isinstance(files, list) or not files or len(files) > 200:
        raise UpdateError("В быстром обновлении некорректный список файлов")
    root = runtime_root()
    target_matches = 0
    compatible_files = 0
    total_bytes = 0
    seen: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise UpdateError("Некорректная запись файла в обновлении")
        scope = str(entry.get("scope") or "runtime")
        rel = PurePosixPath(str(entry.get("path") or ""))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise UpdateError("Обновление содержит небезопасный путь")
        normalized = rel.as_posix()
        identity = f"{scope}:{normalized}"
        if identity in seen:
            raise UpdateError("Обновление содержит повторяющийся файл")
        seen.add(identity)
        if scope == "app":
            if normalized != "les-desktop.exe":
                raise UpdateError("Обновление пытается заменить неизвестный файл оболочки")
            target = root.parent / "les-desktop.exe"
        elif scope == "runtime":
            if any(part in VPS_PATCH_DENIED_PARTS for part in rel.parts):
                raise UpdateError("Обновление пытается изменить запрещённую часть приложения")
            if not (normalized in VPS_PATCH_ALLOWED_FILES or normalized.startswith(VPS_PATCH_ALLOWED_ROOTS)):
                raise UpdateError("Обновление пытается выйти за список заменяемых файлов")
            if Path(normalized).suffix.lower() not in VPS_PATCH_SUFFIXES:
                raise UpdateError("Обновление содержит неподдерживаемый тип файла")
            target = root / Path(*rel.parts)
        else:
            raise UpdateError("Обновление содержит неизвестную область назначения")
        current = sha256_file(target) if target.is_file() else None
        target_hash = str(entry.get("sha256") or "").lower()
        base_hash_value = entry.get("base_sha256")
        accepted_values = entry.get("accepted_sha256") or []
        size = entry.get("bytes")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", target_hash)
            or (
                base_hash_value is not None
                and not re.fullmatch(r"[0-9a-fA-F]{64}", str(base_hash_value))
            )
            or not isinstance(accepted_values, list)
            or any(
                not isinstance(value, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", value)
                for value in accepted_values
            )
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise UpdateError("Обновление содержит некорректный SHA-256 или размер файла")
        total_bytes += size
        if total_bytes > 128 * 1024 * 1024:
            raise UpdateError("Распакованный размер обновления превышает допустимый")
        accepted_hashes = {
            str(value).lower()
            for value in accepted_values
        }
        accepted_hashes.update(
            str(value).lower()
            for value in (entry.get("base_sha256"), target_hash)
            if value
        )
        if current == target_hash:
            target_matches += 1
        if current in accepted_hashes or (
            current is None
            and (entry.get("base_sha256") is None or bool(entry.get("accepted_missing")))
        ):
            compatible_files += 1
    available = target_matches != len(files)
    compatible = compatible_files == len(files)
    return {
        "patch_id": patch_id,
        "base_commit": base_commit,
        "target_commit": target_commit,
        "product_version": product_version,
        "build_number": build_number,
        "files": len(files),
        "bytes": int(payload.get("archive_bytes") or 0),
        "available": available,
        "compatible": compatible,
        "message": (
            "Быстрое обновление доступно"
            if available and compatible
            else "Обновление уже установлено"
            if not available
            else "Текущие файлы не соответствуют базе патча; требуется полный выпуск"
        ),
        "archive_url": archive_url,
        "archive_sha256": archive_sha256,
        "patch": patch,
    }


async def check_vps_patch(*, client: httpx.AsyncClient | None = None) -> dict:
    if not _trusted_patch_url(VPS_PATCH_MANIFEST_URL):
        raise UpdateError("Задан недоверенный адрес быстрых обновлений")
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        response = await client.get(VPS_PATCH_MANIFEST_URL, headers={"User-Agent": "LES-vps-updater"})
        if response.status_code == 404:
            return {
                "patch_id": "",
                "available": False,
                "compatible": True,
                "files": 0,
                "message": "Быстрых обновлений пока нет",
            }
        response.raise_for_status()
        return _validate_patch_feed(response.json())
    except UpdateError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise UpdateError(f"Не удалось проверить быстрое обновление: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()


def read_vps_patch_status() -> dict:
    path = patch_status_path()
    if not path.is_file():
        return {"schema": "les.vps-patch-status.v1", "state": "idle", "message": "Обновление не запускалось"}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"schema": "les.vps-patch-status.v1", "state": "failed", "message": "Не удалось прочитать состояние обновления"}


async def download_and_launch_vps_patch() -> dict:
    if not sys.platform.startswith("win"):
        raise UpdateError("Быстрое обновление поддерживается только в Windows-сборке")
    info = await check_vps_patch()
    if not info["available"]:
        raise UpdateError("Быстрое обновление уже установлено")
    if not info["compatible"]:
        raise UpdateError(info["message"])
    root = update_root() / "vps" / info["patch_id"]
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "patch.zip"
    async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
        await _download(
            client,
            info["archive_url"],
            archive,
            max_bytes=64 * 1024 * 1024,
            trusted_url=_trusted_patch_url,
        )
    actual = sha256_file(archive)
    if actual != info["archive_sha256"]:
        archive.unlink(missing_ok=True)
        raise UpdateError("Контрольная сумма быстрого обновления не совпала")
    try:
        with zipfile.ZipFile(archive) as bundle:
            bundled = json.loads(bundle.read("manifest.json"))
            if bundled != info["patch"]:
                raise UpdateError("Манифест внутри архива не совпадает с опубликованным")
            names = set(bundle.namelist())
            expected = {
                "manifest.json",
                *(
                    f"payload/@app/{entry['path']}"
                    if str(entry.get("scope") or "runtime") == "app"
                    else f"payload/{entry['path']}"
                    for entry in bundled["files"]
                ),
            }
            if names != expected:
                raise UpdateError("Архив быстрого обновления содержит лишние или отсутствующие файлы")
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as exc:
        raise UpdateError(f"Архив быстрого обновления повреждён: {exc}") from exc
    state_root = update_root().parents[1]
    helper = root / "vps_patch_apply.py"
    shutil.copy2(runtime_root() / "tools" / "vps_patch_apply.py", helper)
    shutil.copy2(
        runtime_root() / "tools" / "windows_update_engine.py",
        root / "windows_update_engine.py",
    )
    status = patch_status_path()
    job = root / "job.json"
    job.write_text(
        json.dumps(
            {
                "runtime_root": str(runtime_root()),
                "state_root": str(state_root),
                "archive": str(archive),
                "archive_sha256": actual,
                "status_path": str(status),
                "patch_id": info["patch_id"],
                "helper_task_name": "",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    task_name, encoded_command = _patch_task_command(helper, job, info["patch_id"])
    job_payload = json.loads(job.read_text(encoding="utf-8"))
    job_payload["helper_task_name"] = task_name
    job.write_text(json.dumps(job_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    status.write_text(json.dumps({"schema": "les.vps-patch-status.v1", "state": "starting", "stage": "downloaded", "patch_id": info["patch_id"], "message": "Обновление проверено, начинаю установку"}, ensure_ascii=False, indent=2), encoding="utf-8")
    launched = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_command],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        creationflags=0x08000000,
    )
    if launched.returncode != 0:
        raise UpdateError("Windows не смог запустить независимую задачу обновления")
    return {**info, "state": "starting", "message": "Обновление проверено и запущено"}


def mac_update_root() -> Path:
    configured = os.getenv("LES_MAC_UPDATE_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()
    return (runtime_root().parent / "LES_update_cache" / "mac").resolve()


def mac_update_status_path() -> Path:
    return mac_update_root() / "status.json"


def _path_inside(root: Path, value: str, label: str) -> Path:
    path = Path(value).resolve()
    if path != root and root not in path.parents:
        raise UpdateError(f"{label} находится вне локального каталога обновлений")
    return path


def _validate_mac_update_feed(payload: dict) -> dict:
    if payload.get("schema") != MAC_UPDATE_FEED_SCHEMA:
        raise UpdateError("Неподдерживаемая схема Mac-обновления")
    update = payload.get("update")
    if not isinstance(update, dict) or update.get("schema") != MAC_UPDATE_SCHEMA:
        raise UpdateError("Манифест Mac-обновления повреждён")
    files = update.get("files")
    if not isinstance(files, list) or not files or len(files) > 500:
        raise UpdateError("В Mac-обновлении некорректный список файлов")
    root = mac_update_root()
    archive = _path_inside(root, str(payload.get("archive") or ""), "Архив")
    helper = _path_inside(root, str(payload.get("helper") or ""), "Helper")
    archive_sha = str(payload.get("archive_sha256") or "").lower()
    helper_sha = str(payload.get("helper_sha256") or "").lower()
    if (
        not archive.is_file()
        or not helper.is_file()
        or not re.fullmatch(r"[0-9a-f]{64}", archive_sha)
        or not re.fullmatch(r"[0-9a-f]{64}", helper_sha)
        or sha256_file(archive) != archive_sha
        or sha256_file(helper) != helper_sha
    ):
        raise UpdateError("Подготовленный Mac-пакет отсутствует или не прошёл SHA-256")

    target_matches = 0
    compatible_files = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise UpdateError("Некорректная запись файла в Mac-обновлении")
        rel = PurePosixPath(str(entry.get("path") or "").replace("\\", "/"))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise UpdateError("Mac-обновление содержит небезопасный путь")
        if any(part in MAC_UPDATE_DENIED_PARTS for part in rel.parts):
            raise UpdateError("Mac-обновление пытается изменить пользовательские данные")
        normalized = rel.as_posix()
        if not (
            normalized in MAC_UPDATE_ALLOWED_FILES
            or normalized.startswith(MAC_UPDATE_ALLOWED_ROOTS)
        ) or Path(normalized).suffix.lower() not in MAC_UPDATE_ALLOWED_SUFFIXES:
            raise UpdateError("Mac-обновление пытается выйти за список runtime-файлов")
        operation = str(entry.get("operation") or "")
        if operation not in {"replace", "delete"}:
            raise UpdateError("Mac-обновление содержит неизвестную операцию")
        target = runtime_root() / Path(*rel.parts)
        current = sha256_file(target) if target.is_file() else None
        base_hash = str(entry.get("base_sha256") or "") or None
        target_hash = str(entry.get("sha256") or "") or None
        accepted_hashes = {
            str(value).lower()
            for value in (entry.get("accepted_sha256") or [])
            if re.fullmatch(r"[0-9a-fA-F]{64}", str(value))
        }
        if operation == "delete":
            target_is_current = current is None
        else:
            target_is_current = current == target_hash
        if target_is_current:
            target_matches += 1
        if current in {base_hash, target_hash, *accepted_hashes} or (
            current is None and bool(entry.get("accepted_missing"))
        ):
            compatible_files += 1

    available = target_matches != len(files)
    compatible = compatible_files == len(files)
    return {
        "update_id": str(update.get("update_id") or ""),
        "base_commit": str(update.get("base_commit") or ""),
        "target_commit": str(update.get("target_commit") or ""),
        "product_version": str(update.get("product_version") or ""),
        "build_number": int(update.get("build_number") or 0),
        "files": len(files),
        "bytes": int(payload.get("archive_bytes") or archive.stat().st_size),
        "available": available,
        "compatible": compatible,
        "message": (
            "Mac-обновление готово к установке"
            if available and compatible
            else "Mac уже обновлён"
            if not available
            else "Файлы Mac runtime отличаются от подготовленной базы; установка заблокирована"
        ),
        "archive": str(archive),
        "archive_sha256": archive_sha,
        "helper": str(helper),
        "helper_sha256": helper_sha,
        "update": update,
        "published": False,
        "user_data_untouched": True,
    }


def check_mac_update() -> dict:
    if sys.platform != "darwin":
        raise UpdateError("Локальное Mac-обновление доступно только на macOS")
    feed = mac_update_root() / "latest.json"
    if not feed.is_file():
        return {
            "available": False,
            "compatible": True,
            "files": 0,
            "bytes": 0,
            "message": "Подготовленного Mac-обновления нет",
            "published": False,
        }
    try:
        return _validate_mac_update_feed(json.loads(feed.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        raise UpdateError(f"Не удалось прочитать Mac-обновление: {exc}") from exc


def read_mac_update_status() -> dict:
    path = mac_update_status_path()
    if not path.is_file():
        return {
            "schema": "les.mac-update-status.v1",
            "state": "idle",
            "message": "Обновление не запускалось",
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "schema": "les.mac-update-status.v1",
            "state": "failed",
            "message": "Не удалось прочитать состояние Mac-обновления",
        }


def launch_mac_update() -> dict:
    info = check_mac_update()
    if not info["available"]:
        raise UpdateError("Mac уже обновлён или пакет не подготовлен")
    if not info["compatible"]:
        raise UpdateError(info["message"])
    root = mac_update_root()
    status = mac_update_status_path()
    job = root / f"{info['update_id']}.job.json"
    job_payload = {
        "runtime_root": str(runtime_root()),
        "archive": info["archive"],
        "archive_sha256": info["archive_sha256"],
        "status_path": str(status),
        "recovery_root": str(runtime_root().parent / "LES_recovery" / "mac-updates"),
    }
    temporary = job.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(job_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, job)
    status.write_text(
        json.dumps(
            {
                "schema": "les.mac-update-status.v1",
                "state": "starting",
                "stage": "prepared",
                "update_id": info["update_id"],
                "message": "Пакет проверен, начинаю установку",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log = root / f"{info['update_id']}.log"
    with log.open("ab", buffering=0) as output:
        process = subprocess.Popen(  # noqa: S603 - local checksum-verified helper
            [sys.executable, info["helper"], "--job", str(job)],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    return {
        **info,
        "state": "starting",
        "pid": process.pid,
        "message": "Mac-обновление проверено и запущено",
    }
