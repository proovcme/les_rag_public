"""Local cloud-drive folder discovery for external dataset intake.

This is intentionally local-first: Google Drive Desktop and Yandex Disk expose
ordinary synced folders on the operator machine, so LES can reuse the existing
in-place external dataset path without OAuth credentials or file copies.
"""

from __future__ import annotations

import os
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from proxy.config import rag_upload_suffixes


GOOGLE_API = "https://www.googleapis.com/drive/v3"
YANDEX_API = "https://cloud-api.yandex.net/v1/disk"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}


class CloudDriveError(RuntimeError):
    """Operator-facing cloud drive error."""

def _truthy_env(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in {"0", "false", "no", "off"}


def _classify_provider(path: Path, label: str = "") -> str:
    text = f"{label} {path}".lower()
    if "yandex" in text or "яндекс" in text:
        return "yandex_disk"
    if "googledrive" in text or "google drive" in text or "google" in text:
        return "google_drive"
    return "cloud_drive"


def _provider_title(provider: str) -> str:
    return {
        "google_drive": "Google Drive",
        "yandex_disk": "Яндекс Диск",
    }.get(provider, "Облачный диск")


def _safe_resolve(path: Path, *, strict: bool = False) -> Path | None:
    try:
        return path.expanduser().resolve(strict=strict)
    except (OSError, RuntimeError):
        return None


def _add_root(
    roots: list[dict[str, Any]],
    seen: set[str],
    path: Path,
    *,
    provider: str | None = None,
    label: str = "",
    source: str,
    include_missing: bool,
) -> None:
    resolved = _safe_resolve(path, strict=False)
    if not resolved:
        return
    exists = resolved.exists()
    is_dir = resolved.is_dir()
    if not include_missing and not is_dir:
        return
    key = resolved.as_posix()
    if key in seen:
        return
    seen.add(key)
    provider_name = provider or _classify_provider(resolved, label)
    display = label.strip() or _provider_title(provider_name)
    if resolved.name and resolved.name not in display:
        display = f"{display} · {resolved.name}"
    roots.append(
        {
            "provider": provider_name,
            "provider_title": _provider_title(provider_name),
            "label": display,
            "path": key,
            "exists": exists,
            "is_dir": is_dir,
            "source": source,
        }
    )


def _env_roots() -> list[tuple[str, Path]]:
    raw = os.getenv("LES_CLOUD_DRIVE_ROOTS", "").strip()
    if not raw:
        return []
    roots: list[tuple[str, Path]] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        label = ""
        path_text = item
        if "=" in item:
            label, path_text = item.split("=", 1)
        roots.append((label.strip(), Path(path_text.strip())))
    return roots


def discover_cloud_drive_roots(
    *,
    home: Path | None = None,
    include_missing: bool = False,
) -> list[dict[str, Any]]:
    """Return local Google/Yandex sync folders that can be used as datasets."""
    if not _truthy_env("LES_CLOUD_DRIVE_DISCOVERY", "1"):
        return []

    base_home = home or Path.home()
    roots: list[dict[str, Any]] = []
    seen: set[str] = set()

    for label, path in _env_roots():
        _add_root(roots, seen, path, label=label, source="env", include_missing=include_missing)

    cloud_storage = base_home / "Library" / "CloudStorage"
    for google_root in sorted(cloud_storage.glob("GoogleDrive-*")) if cloud_storage.exists() else []:
        children = [
            child
            for child in (
                google_root / "My Drive",
                google_root / "Мой диск",
                google_root / "Shared drives",
                google_root / "Общие диски",
            )
            if child.exists()
        ]
        if children:
            for child in children:
                _add_root(
                    roots,
                    seen,
                    child,
                    provider="google_drive",
                    label="Google Drive",
                    source="auto",
                    include_missing=include_missing,
                )
        else:
            _add_root(
                roots,
                seen,
                google_root,
                provider="google_drive",
                label="Google Drive",
                source="auto",
                include_missing=include_missing,
            )

    for pattern in ("YandexDisk*", "Яндекс*"):
        for yandex_root in sorted(cloud_storage.glob(pattern)) if cloud_storage.exists() else []:
            _add_root(
                roots,
                seen,
                yandex_root,
                provider="yandex_disk",
                label="Яндекс Диск",
                source="auto",
                include_missing=include_missing,
            )

    for yandex_root in (
        base_home / "Yandex.Disk",
        base_home / "Yandex.Disk.localized",
        base_home / "Яндекс.Диск",
    ):
        _add_root(
            roots,
            seen,
            yandex_root,
            provider="yandex_disk",
            label="Яндекс Диск",
            source="auto",
            include_missing=include_missing,
        )

    roots.sort(key=lambda item: (str(item.get("provider_title") or ""), str(item.get("path") or "").lower()))
    return roots


def cloud_drive_root_paths() -> list[Path]:
    return [Path(item["path"]) for item in discover_cloud_drive_roots() if item.get("is_dir")]


def _google_token() -> str:
    return os.getenv("LES_GOOGLE_DRIVE_ACCESS_TOKEN") or os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN") or ""


def _yandex_token() -> str:
    return os.getenv("LES_YANDEX_DISK_TOKEN") or os.getenv("YANDEX_DISK_TOKEN") or ""


def cloud_drive_provider_status() -> dict[str, Any]:
    return {
        "google_drive": {
            "configured": bool(_google_token()),
            "auth": "env: LES_GOOGLE_DRIVE_ACCESS_TOKEN",
            "label": "Google Drive",
        },
        "yandex_disk": {
            "configured": bool(_yandex_token()),
            "auth": "env: LES_YANDEX_DISK_TOKEN",
            "label": "Яндекс Диск",
        },
    }


def _require_token(provider: str) -> str:
    token = _google_token() if provider == "google_drive" else _yandex_token() if provider == "yandex_disk" else ""
    if not token:
        raise CloudDriveError(
            "Для web-доступа нужен токен: "
            + ("LES_GOOGLE_DRIVE_ACCESS_TOKEN" if provider == "google_drive" else "LES_YANDEX_DISK_TOKEN")
        )
    return token


def _safe_name(value: str, fallback: str = "item") -> str:
    text = (value or fallback).strip().replace("/", " ").replace("\\", " ")
    text = re.sub(r"[\x00-\x1f:]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text or fallback)[:160]


def _mirror_root() -> Path:
    raw = os.getenv("LES_CLOUD_DRIVE_MIRROR_ROOT", "storage/cloud_drives")
    return Path(raw).expanduser().resolve()


def _mirror_dir(provider: str, locator: str, dataset_name: str = "") -> Path:
    digest = hashlib.sha256(f"{provider}|{locator}".encode("utf-8")).hexdigest()[:16]
    title = _safe_name(dataset_name or locator or provider, fallback=provider)[:64]
    root = _mirror_root() / provider / f"{title}-{digest}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_manifest(root: Path, payload: dict[str, Any]) -> None:
    payload = {**payload, "updated_at": time.time()}
    (root / ".les_cloud_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _google_folder_id(locator: str) -> str:
    raw = (locator or "").strip()
    if not raw:
        return "root"
    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        match = re.search(r"/folders/([^/?#]+)", parsed.path)
        if match:
            return match.group(1)
        query = parse_qs(parsed.query)
        if query.get("id"):
            return query["id"][0]
    return raw


def _yandex_path(locator: str) -> str:
    raw = (locator or "").strip()
    if not raw:
        return "disk:/"
    if raw.startswith("disk:/"):
        return raw
    if raw.startswith("/"):
        return "disk:" + raw
    return raw


def _headers(provider: str) -> dict[str, str]:
    return {"Authorization": f"OAuth {_require_token(provider)}" if provider == "yandex_disk" else f"Bearer {_require_token(provider)}"}


def _http_error_text(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
    except Exception:  # noqa: BLE001
        body = exc.response.text[:500]
    return f"{exc.response.status_code}: {body}"


def list_google_drive_folder(locator: str, *, limit: int = 200) -> dict[str, Any]:
    folder_id = _google_folder_id(locator)
    params = {
        "q": f"'{folder_id}' in parents and trashed=false",
        "pageSize": min(max(int(limit), 1), 1000),
        "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink),nextPageToken",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{GOOGLE_API}/files", headers=_headers("google_drive"), params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise CloudDriveError("Google Drive list failed: " + _http_error_text(exc)) from exc
    except httpx.HTTPError as exc:
        raise CloudDriveError(f"Google Drive list failed: {exc}") from exc
    items = []
    for item in data.get("files") or []:
        mime = str(item.get("mimeType") or "")
        items.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": "folder" if mime == GOOGLE_FOLDER_MIME else "file",
                "mime_type": mime,
                "size": int(item.get("size") or 0),
                "modified": item.get("modifiedTime"),
                "web_url": item.get("webViewLink"),
            }
        )
    return {"provider": "google_drive", "locator": locator, "folder_id": folder_id, "items": items}


def list_yandex_disk_folder(locator: str, *, limit: int = 200) -> dict[str, Any]:
    path = _yandex_path(locator)
    params = {"path": path, "limit": min(max(int(limit), 1), 1000), "preview_size": "S"}
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{YANDEX_API}/resources", headers=_headers("yandex_disk"), params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise CloudDriveError("Yandex Disk list failed: " + _http_error_text(exc)) from exc
    except httpx.HTTPError as exc:
        raise CloudDriveError(f"Yandex Disk list failed: {exc}") from exc
    items = []
    for item in ((data.get("_embedded") or {}).get("items") or []):
        items.append(
            {
                "id": item.get("resource_id") or item.get("path"),
                "name": item.get("name"),
                "type": item.get("type"),
                "mime_type": item.get("mime_type") or item.get("media_type"),
                "size": int(item.get("size") or 0),
                "modified": item.get("modified"),
                "path": item.get("path"),
            }
        )
    return {"provider": "yandex_disk", "locator": locator, "path": path, "items": items}


def list_cloud_drive_folder(provider: str, locator: str, *, limit: int = 200) -> dict[str, Any]:
    if provider == "google_drive":
        return list_google_drive_folder(locator, limit=limit)
    if provider == "yandex_disk":
        return list_yandex_disk_folder(locator, limit=limit)
    raise CloudDriveError(f"unknown provider: {provider}")


def _download_url(client: httpx.Client, url: str, target: Path, headers: dict[str, str] | None = None) -> int:
    with client.stream("GET", url, headers=headers, follow_redirects=True, timeout=120.0) as response:
        response.raise_for_status()
        target.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with target.open("wb") as handle:
            for chunk in response.iter_bytes(1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                handle.write(chunk)
        return total


def sync_google_drive_folder(
    locator: str,
    *,
    dataset_name: str = "",
    max_files: int = 500,
    max_depth: int = 6,
) -> dict[str, Any]:
    root = _mirror_dir("google_drive", locator, dataset_name)
    suffixes = rag_upload_suffixes()
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    folder_id = _google_folder_id(locator)

    def walk(client: httpx.Client, current_id: str, rel_dir: Path, depth: int) -> None:
        if len(downloaded) >= max_files:
            return
        if depth > max_depth:
            skipped.append({"path": rel_dir.as_posix(), "reason": "max_depth"})
            return
        listing = list_google_drive_folder(current_id, limit=1000)
        for item in listing.get("items") or []:
            if len(downloaded) >= max_files:
                return
            name = _safe_name(str(item.get("name") or "file"))
            mime = str(item.get("mime_type") or "")
            if item.get("type") == "folder":
                walk(client, str(item.get("id")), rel_dir / name, depth + 1)
                continue
            export = GOOGLE_EXPORTS.get(mime)
            target_name = name
            url = f"{GOOGLE_API}/files/{item.get('id')}?alt=media&supportsAllDrives=true"
            if export:
                export_mime, suffix = export
                url = f"{GOOGLE_API}/files/{item.get('id')}/export?mimeType={export_mime}"
                if not Path(target_name).suffix:
                    target_name += suffix
            suffix = Path(target_name).suffix.lower()
            if suffix and suffix not in suffixes:
                skipped.append({"path": (rel_dir / target_name).as_posix(), "reason": "unsupported_suffix", "suffix": suffix})
                continue
            try:
                size = _download_url(client, url, root / rel_dir / target_name, headers=_headers("google_drive"))
                downloaded.append({"file_name": (rel_dir / target_name).as_posix(), "size": size, "cloud_id": item.get("id")})
            except httpx.HTTPError as exc:
                skipped.append({"path": (rel_dir / target_name).as_posix(), "reason": f"download_error:{exc}"})

    with httpx.Client(timeout=60.0) as client:
        walk(client, folder_id, Path(), 0)
    manifest = {
        "provider": "google_drive",
        "locator": locator,
        "folder_id": folder_id,
        "local_path": root.as_posix(),
        "downloaded": downloaded,
        "skipped": skipped,
    }
    _write_manifest(root, manifest)
    return {**manifest, "downloaded_count": len(downloaded), "skipped_count": len(skipped)}


def sync_yandex_disk_folder(
    locator: str,
    *,
    dataset_name: str = "",
    max_files: int = 500,
    max_depth: int = 6,
) -> dict[str, Any]:
    root = _mirror_dir("yandex_disk", locator, dataset_name)
    suffixes = rag_upload_suffixes()
    downloaded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    start_path = _yandex_path(locator)

    def list_path(path: str, limit: int = 1000) -> list[dict[str, Any]]:
        listing = list_yandex_disk_folder(path, limit=limit)
        return list(listing.get("items") or [])

    def download_href(client: httpx.Client, path: str) -> str:
        response = client.get(f"{YANDEX_API}/resources/download", headers=_headers("yandex_disk"), params={"path": path})
        response.raise_for_status()
        return str(response.json().get("href") or "")

    def walk(client: httpx.Client, current_path: str, rel_dir: Path, depth: int) -> None:
        if len(downloaded) >= max_files:
            return
        if depth > max_depth:
            skipped.append({"path": rel_dir.as_posix(), "reason": "max_depth"})
            return
        for item in list_path(current_path):
            if len(downloaded) >= max_files:
                return
            name = _safe_name(str(item.get("name") or "file"))
            cloud_path = str(item.get("path") or "")
            if item.get("type") == "dir":
                walk(client, cloud_path, rel_dir / name, depth + 1)
                continue
            suffix = Path(name).suffix.lower()
            if suffix and suffix not in suffixes:
                skipped.append({"path": (rel_dir / name).as_posix(), "reason": "unsupported_suffix", "suffix": suffix})
                continue
            try:
                href = download_href(client, cloud_path)
                size = _download_url(client, href, root / rel_dir / name)
                downloaded.append({"file_name": (rel_dir / name).as_posix(), "size": size, "cloud_path": cloud_path})
            except httpx.HTTPError as exc:
                skipped.append({"path": (rel_dir / name).as_posix(), "reason": f"download_error:{exc}"})

    with httpx.Client(timeout=60.0) as client:
        walk(client, start_path, Path(), 0)
    manifest = {
        "provider": "yandex_disk",
        "locator": locator,
        "path": start_path,
        "local_path": root.as_posix(),
        "downloaded": downloaded,
        "skipped": skipped,
    }
    _write_manifest(root, manifest)
    return {**manifest, "downloaded_count": len(downloaded), "skipped_count": len(skipped)}


def sync_cloud_drive_folder(
    provider: str,
    locator: str,
    *,
    dataset_name: str = "",
    max_files: int = 500,
    max_depth: int = 6,
) -> dict[str, Any]:
    if provider == "google_drive":
        return sync_google_drive_folder(locator, dataset_name=dataset_name, max_files=max_files, max_depth=max_depth)
    if provider == "yandex_disk":
        return sync_yandex_disk_folder(locator, dataset_name=dataset_name, max_files=max_files, max_depth=max_depth)
    raise CloudDriveError(f"unknown provider: {provider}")
