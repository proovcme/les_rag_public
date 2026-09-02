"""Build the Tauri 2 desktop shell with a clean LES runtime resource tree."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import urllib.request
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable

from tools.build_release_artifacts import ROOT, iter_files


TAURI_ROOT = ROOT / "desktop" / "tauri"
SRC_TAURI = TAURI_ROOT / "src-tauri"
RESOURCES = SRC_TAURI / "resources"
WINDOWS_UV_CONTRACT_PATH = ROOT / "config" / "windows_uv.json"
WINDOWS_PYTHON_CONTRACT_PATH = ROOT / "config" / "windows_python.json"
WINDOWS_RUNTIME_MANIFEST_PATH = ROOT / "config" / "windows_runtime_manifest.json"
DESKTOP_VERSION_MAJOR = 5
DESKTOP_VERSION_MINOR = 1
WINDOWS_DEPENDENCY_FINGERPRINT_SCHEMA = "les.windows-dependency-fingerprint.v2"
PERSISTENT_RUNTIME_ROOTS = frozenset(
    {"data", "storage", "rag_content", "logs", "artifacts"}
)


def _is_persistent_runtime_path(value: str) -> bool:
    normalized = str(value).replace("\\", "/").strip("/")
    return bool(normalized) and normalized.split("/", 1)[0].casefold() in PERSISTENT_RUNTIME_ROOTS


@lru_cache(maxsize=1)
def windows_runtime_manifest() -> tuple[frozenset[str], tuple[str, ...]]:
    payload = json.loads(WINDOWS_RUNTIME_MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("schema") != "les.windows-runtime-manifest.v1":
        raise RuntimeError("invalid Windows runtime manifest schema")
    files = tuple(str(item).replace("\\", "/") for item in payload.get("include_files") or ())
    prefixes = tuple(str(item).replace("\\", "/") for item in payload.get("include_prefixes") or ())
    if not files or not prefixes:
        raise RuntimeError("Windows runtime manifest must declare files and prefixes")
    invalid = [
        item
        for item in (*files, *prefixes)
        if not item or item.startswith(("/", "../")) or "/../" in item
    ]
    if invalid or any(not prefix.endswith("/") for prefix in prefixes):
        raise RuntimeError(f"invalid Windows runtime manifest paths: {invalid}")
    persistent = [
        item for item in (*files, *prefixes) if _is_persistent_runtime_path(item)
    ]
    if persistent:
        raise RuntimeError(
            f"Windows runtime manifest cannot include persistent state: {persistent}"
        )
    return frozenset(files), prefixes


def windows_runtime_manifest_allows(path: Path) -> bool:
    """Return whether a tracked repository file belongs in installed Windows LES."""
    relative = path.relative_to(ROOT).as_posix()
    files, prefixes = windows_runtime_manifest()
    return relative in files or relative.startswith(prefixes)


def release_contract() -> dict[str, object]:
    path = ROOT / "config" / "version.json"
    return json.loads(path.read_text(encoding="utf-8"))


def desktop_semver(version: str, build_number: int | None = None) -> str:
    """Return the internal Tauri/NSIS version for a product release.

    New releases pass the separate monotonic build number and map it to the
    established ``5.1.BUILD`` desktop line. Legacy four-part inputs remain
    accepted only so old build callers fail neither silently nor abruptly.
    """
    if build_number is not None:
        if int(build_number) < 0:
            raise ValueError("build number must be non-negative")
        return f"{DESKTOP_VERSION_MAJOR}.{DESKTOP_VERSION_MINOR}.{int(build_number)}"
    parts = version.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return version
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return f"{DESKTOP_VERSION_MAJOR}.{DESKTOP_VERSION_MINOR}.{int(parts[-1])}"
    raise ValueError(f"version must be numeric X.Y.Z or W.X.Y.Z, got {version!r}")


def npm_executable(platform: str | None = None) -> str:
    """Resolve npm without relying on POSIX executable semantics.

    The Windows Node installer exposes ``npm.cmd``.  ``subprocess`` does not
    reliably resolve the bare ``npm`` command through PATHEXT when shell=False,
    so a release build from an ordinary PowerShell otherwise fails after the
    expensive runtime staging step.
    """
    target = platform or os.sys.platform
    candidates = ("npm.cmd", "npm.exe", "npm") if target.startswith("win") else ("npm",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError("npm executable not found; install Node.js before building Tauri")


def windows_uv_contract() -> dict[str, str]:
    payload = json.loads(WINDOWS_UV_CONTRACT_PATH.read_text(encoding="utf-8"))
    required = ("schema", "version", "archive_url", "archive_sha256", "binary_sha256", "binary_name")
    missing = [key for key in required if not str(payload.get(key) or "").strip()]
    if payload.get("schema") != "les.windows-uv.v1" or missing:
        raise RuntimeError(f"invalid Windows uv contract: missing={missing}")
    for key in ("archive_sha256", "binary_sha256"):
        digest = str(payload[key]).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RuntimeError(f"invalid Windows uv {key} SHA-256")
    return {key: str(payload[key]) for key in required}


def stage_windows_uv(runtime: Path, *, archive_path: str | Path | None = None) -> int:
    """Place a verified uv.exe in the Windows runtime; end users must not install uv."""
    contract = windows_uv_contract()
    if archive_path:
        archive = Path(archive_path)
        if not archive.is_file():
            raise RuntimeError(f"Windows uv archive is missing: {archive}")
        blob = archive.read_bytes()
    else:
        local_archive = os.getenv("LES_WINDOWS_UV_ARCHIVE", "").strip()
        if local_archive:
            archive = Path(local_archive)
            if not archive.is_file():
                raise RuntimeError(f"LES_WINDOWS_UV_ARCHIVE is missing: {archive}")
            blob = archive.read_bytes()
        else:
            try:
                with urllib.request.urlopen(contract["archive_url"], timeout=60) as response:
                    blob = response.read()
            except Exception as error:  # release builder needs a precise, actionable failure
                raise RuntimeError(
                    "could not download bundled Windows uv; set LES_WINDOWS_UV_ARCHIVE to a verified archive"
                ) from error
    actual = hashlib.sha256(blob).hexdigest()
    if actual != contract["archive_sha256"].lower():
        raise RuntimeError(f"Windows uv archive SHA-256 mismatch: expected {contract['archive_sha256']}, got {actual}")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            member = next(
                (name for name in zf.namelist() if name.replace("\\", "/").endswith(f"/{contract['binary_name']}")
                 or name == contract["binary_name"]),
                None,
            )
            if member is None:
                raise RuntimeError(f"Windows uv archive does not contain {contract['binary_name']}")
            binary = zf.read(member)
    except zipfile.BadZipFile as error:
        raise RuntimeError("Windows uv archive is not a ZIP") from error
    if not binary:
        raise RuntimeError("bundled Windows uv.exe is empty")
    binary_digest = hashlib.sha256(binary).hexdigest()
    if binary_digest != contract["binary_sha256"].lower():
        raise RuntimeError(
            f"Windows uv.exe SHA-256 mismatch: expected {contract['binary_sha256']}, got {binary_digest}"
        )
    target_dir = runtime / "installers" / "windows" / "tools"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / contract["binary_name"]).write_bytes(binary)
    (target_dir / "uv-contract.json").write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1


def windows_python_contract() -> dict[str, str]:
    payload = json.loads(WINDOWS_PYTHON_CONTRACT_PATH.read_text(encoding="utf-8"))
    required = (
        "schema", "version", "archive_url", "archive_sha256", "archive_name", "python_relative_path",
    )
    missing = [key for key in required if not str(payload.get(key) or "").strip()]
    digest = str(payload.get("archive_sha256") or "").lower()
    if (
        payload.get("schema") != "les.windows-python.v2"
        or missing
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise RuntimeError(f"invalid Windows Python contract: missing={missing}")
    return {key: str(payload[key]) for key in required}


def stage_windows_python(runtime: Path, *, archive_path: str | Path | None = None) -> int:
    """Place a verified portable CPython archive in the Windows runtime."""
    contract = windows_python_contract()
    if archive_path:
        archive = Path(archive_path)
        if not archive.is_file():
            raise RuntimeError(f"Windows Python archive is missing: {archive}")
        blob = archive.read_bytes()
    else:
        local_archive = os.getenv("LES_WINDOWS_PYTHON_ARCHIVE", "").strip()
        if local_archive:
            archive = Path(local_archive)
            if not archive.is_file():
                raise RuntimeError(f"LES_WINDOWS_PYTHON_ARCHIVE is missing: {archive}")
            blob = archive.read_bytes()
        else:
            try:
                with urllib.request.urlopen(contract["archive_url"], timeout=120) as response:
                    blob = response.read()
            except Exception as error:  # release builder needs a precise, actionable failure
                raise RuntimeError(
                    "could not download bundled Windows Python; set LES_WINDOWS_PYTHON_ARCHIVE "
                    "to a verified archive"
                ) from error
    actual = hashlib.sha256(blob).hexdigest()
    if actual != contract["archive_sha256"].lower():
        raise RuntimeError(
            f"Windows Python archive SHA-256 mismatch: expected {contract['archive_sha256']}, got {actual}"
        )
    target_dir = runtime / "installers" / "windows" / "tools"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / contract["archive_name"]).write_bytes(blob)
    (target_dir / "python-contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 1


def _build_windows_uv_cache(runtime: Path, archive: Path) -> None:
    """Resolve the locked Windows environment into a portable offline uv cache."""
    tools_dir = runtime / "installers" / "windows" / "tools"
    uv = tools_dir / "uv.exe"
    python_contract = json.loads((tools_dir / "python-contract.json").read_text(encoding="utf-8"))
    python_archive = tools_dir / str(python_contract["archive_name"])
    if not uv.is_file() or not python_archive.is_file():
        raise RuntimeError("Windows offline cache requires staged Python and uv")
    with tempfile.TemporaryDirectory(prefix="les-windows-uv-cache-") as raw_tmp:
        tmp = Path(raw_tmp)
        python_root = tmp / "python"
        python_root.mkdir()
        with zipfile.ZipFile(python_archive) as zf:
            zf.extractall(python_root)
        python = python_root / str(python_contract["python_relative_path"])
        cache = tmp / "cache"
        environment = tmp / "environment"
        env = dict(os.environ)
        env["UV_CACHE_DIR"] = str(cache)
        env["UV_PROJECT_ENVIRONMENT"] = str(environment)
        env["UV_SYSTEM_PYTHON"] = "0"
        subprocess.run(
            [
                str(uv), "sync", "--locked", "--python", str(python),
                "--no-python-downloads", "--extra", "windows-reranker",
            ],
            cwd=runtime,
            env=env,
            check=True,
        )
        verify_environment = tmp / "verify-environment"
        verify_env = dict(env)
        verify_env["UV_PROJECT_ENVIRONMENT"] = str(verify_environment)
        subprocess.run(
            [
                str(uv), "sync", "--locked", "--offline", "--python", str(python),
                "--no-python-downloads", "--extra", "windows-reranker",
            ],
            cwd=runtime,
            env=verify_env,
            check=True,
        )
        files = [path for path in cache.rglob("*") if path.is_file()]
        if not files:
            raise RuntimeError("Windows uv sync produced an empty offline cache")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for path in files:
                zf.write(path, path.relative_to(cache).as_posix())


def windows_dependency_fingerprint(
    lock_path: str | Path,
    tools_dir: str | Path,
    *,
    extra: str = "windows-reranker",
) -> str:
    """Hash resolved third-party dependencies without release-only project version churn."""

    lock = Path(lock_path)
    payload = tomllib.loads(lock.read_text(encoding="utf-8"))
    packages = payload.get("package")
    if not isinstance(packages, list):
        packages = []
    normalized_project = False
    for package in packages:
        if not isinstance(package, dict):
            continue
        source = package.get("source")
        if isinstance(source, dict) and source.get("editable") == ".":
            if normalized_project:
                raise RuntimeError("uv.lock contains multiple editable root projects")
            package["version"] = "<editable-project-version>"
            normalized_project = True
    if not normalized_project and packages:
        raise RuntimeError("uv.lock does not contain the editable root project")
    digest = hashlib.sha256()
    digest.update(WINDOWS_DEPENDENCY_FINGERPRINT_SCHEMA.encode("ascii"))
    digest.update(b"\0")
    digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8"))
    digest.update(b"\0")
    digest.update(extra.encode("utf-8"))
    contract_root = Path(tools_dir)
    for contract_name in ("python-contract.json", "uv-contract.json"):
        contract_path = contract_root / contract_name
        digest.update(b"\0")
        digest.update(contract_name.encode("ascii"))
        digest.update(b"\0")
        if contract_path.is_file():
            contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))
            digest.update(
                json.dumps(contract_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
    return digest.hexdigest()


def _legacy_windows_uv_cache_fingerprint(lock: Path, tools_dir: Path) -> str:
    """Locate one cache produced by the pre-v1 dependency fingerprint builder."""

    digest = hashlib.sha256()
    digest.update(lock.read_bytes())
    digest.update(b"\0windows-reranker\0")
    for contract_name in ("python-contract.json", "uv-contract.json"):
        contract_path = tools_dir / contract_name
        if contract_path.is_file():
            digest.update(contract_path.read_bytes())
    return digest.hexdigest()


def stage_windows_uv_cache(
    runtime: Path,
    *,
    archive_path: str | Path | None = None,
    lock_path: str | Path | None = None,
    cache_dir: str | Path | None = None,
) -> int:
    """Bundle a lock-bound cache so first launch never downloads Python packages."""
    lock = Path(lock_path) if lock_path else runtime / "uv.lock"
    if not lock.is_file():
        raise RuntimeError(f"Windows offline cache requires uv.lock: {lock}")
    configured = str(archive_path or os.getenv("LES_WINDOWS_UV_CACHE_ARCHIVE", "")).strip()
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if configured:
            archive = Path(configured)
            if not archive.is_file():
                raise RuntimeError(f"Windows uv cache archive is missing: {archive}")
        else:
            tools_dir = runtime / "installers" / "windows" / "tools"
            dependency_fingerprint = windows_dependency_fingerprint(lock, tools_dir)
            persistent_dir = Path(
                cache_dir
                or os.getenv("LES_WINDOWS_RELEASE_CACHE_DIR", "")
                or ROOT / "dist" / "release-cache"
            )
            persistent_dir.mkdir(parents=True, exist_ok=True)
            archive = persistent_dir / f"windows-uv-cache-{dependency_fingerprint}.zip"
            legacy_archive = persistent_dir / (
                f"windows-uv-cache-{_legacy_windows_uv_cache_fingerprint(lock, tools_dir)}.zip"
            )
            if not archive.is_file() and legacy_archive.is_file():
                os.replace(legacy_archive, archive)
            if not archive.is_file():
                temporary = tempfile.TemporaryDirectory(prefix="les-windows-uv-cache-archive-")
                candidate = Path(temporary.name) / "windows-uv-cache.zip"
                _build_windows_uv_cache(runtime, candidate)
                temporary_target = archive.with_suffix(".zip.tmp")
                shutil.copyfile(candidate, temporary_target)
                os.replace(temporary_target, archive)
        try:
            with zipfile.ZipFile(archive) as zf:
                members = [name for name in zf.namelist() if name and not name.endswith("/")]
                if not members:
                    raise RuntimeError("Windows uv cache archive is empty")
                for name in members:
                    normalized = Path(name.replace("\\", "/"))
                    if normalized.is_absolute() or ".." in normalized.parts:
                        raise RuntimeError(f"unsafe path in Windows uv cache archive: {name}")
        except zipfile.BadZipFile as error:
            raise RuntimeError("Windows uv cache archive is not a ZIP") from error
        blob = archive.read_bytes()
        target_dir = runtime / "installers" / "windows" / "tools"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "windows-uv-cache.zip"
        target.write_bytes(blob)
        contract = {
            "schema": "les.windows-uv-cache.v1",
            "fingerprint_schema": WINDOWS_DEPENDENCY_FINGERPRINT_SCHEMA,
            "dependency_fingerprint": windows_dependency_fingerprint(lock, target_dir),
            "archive_name": target.name,
            "archive_sha256": hashlib.sha256(blob).hexdigest(),
            "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            "extra": "windows-reranker",
        }
        (target_dir / "uv-cache-contract.json").write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()


def stage_windows_deploy_stamp(runtime: Path) -> int:
    """Embed the exact release identity required by subsequent soft updates."""
    from proxy.services.version_service import write_deploy_stamp

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if len(commit) != 40:
        raise RuntimeError("Windows installer requires an exact 40-character Git commit")
    write_deploy_stamp(
        dev_root=ROOT,
        runtime_root=runtime,
        deployed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        deployed_commit=commit,
        deployed_branch=branch or "release",
        notes=["embedded by Windows installer build"],
    )
    return 1


def stage_runtime(
    platform: str | None = None,
    *,
    smeta_baseline_archive: str | Path | None = None,
    windows_uv_archive: str | Path | None = None,
    windows_uv_cache_archive: str | Path | None = None,
) -> int:
    target_platform = platform or os.sys.platform
    runtime = RESOURCES / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    count = 0
    for source in iter_files():
        relative = source.relative_to(ROOT)
        if target_platform.startswith("win") and not windows_runtime_manifest_allows(source):
            continue
        if relative.parts[:2] == ("desktop", "tauri"):
            continue
        if target_platform.startswith("win") and relative.parts[:2] == ("installers", "macos"):
            continue
        if target_platform == "darwin" and relative.parts[:2] == ("installers", "windows"):
            continue
        target = runtime / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        count += 1
    if target_platform.startswith("win") and smeta_baseline_archive:
        baseline = Path(smeta_baseline_archive)
        if not baseline.is_file():
            raise RuntimeError(f"Windows smeta baseline archive is missing: {baseline}")
        from tools.smeta_release_baseline import verify_archive

        verify_archive(baseline)
        target = runtime / "installers" / "windows" / "baseline" / "LES-smeta-baseline.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(baseline, target)
        count += 1
    if target_platform.startswith("win"):
        count += stage_windows_uv(runtime, archive_path=windows_uv_archive)
        count += stage_windows_python(runtime)
        count += stage_windows_uv_cache(runtime, archive_path=windows_uv_cache_archive)
        count += stage_windows_deploy_stamp(runtime)
    bootstrap = RESOURCES / "bootstrap.sh"
    if target_platform == "darwin":
        shutil.copy2(ROOT / "installers/macos/app/bootstrap.sh", bootstrap)
        bootstrap.chmod(0o755)
    else:
        bootstrap.unlink(missing_ok=True)
    return count


def set_version(version: str) -> None:
    config_path = SRC_TAURI / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["version"] = version
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cargo_path = SRC_TAURI / "Cargo.toml"
    cargo = cargo_path.read_text(encoding="utf-8")
    lines = cargo.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("version = "):
            lines[index] = f'version = "{version}"'
            break
    cargo_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(
    version: str,
    bundles: str | None,
    *,
    build_number: int | None = None,
    prebundle_runner: Callable[[Path], object] | None = None,
) -> Path:
    desktop_version = desktop_semver(version, build_number)
    set_version(desktop_version)
    if desktop_version != version:
        print(f"[tauri] LES {version} -> desktop {desktop_version}")
    smeta_baseline = None
    if os.sys.platform.startswith("win"):
        smeta_baseline = os.getenv("LES_SMETA_BASELINE_ARCHIVE", "").strip()
        if not smeta_baseline:
            raise RuntimeError("Windows release build requires LES_SMETA_BASELINE_ARCHIVE")
    count = stage_runtime(smeta_baseline_archive=smeta_baseline)
    print(f"[tauri] staged clean runtime: {count} files")
    if os.sys.platform.startswith("win"):
        if prebundle_runner is None:
            from tools.windows_prebundle_smoke import run_prebundle_smoke

            prebundle_runner = run_prebundle_smoke
        prebundle_runner(RESOURCES / "runtime")
    npm = npm_executable()
    subprocess.run([npm, "install"], cwd=TAURI_ROOT, check=True)
    command = [npm, "run", "tauri", "--", "build"]
    tauri_bundles = bundles
    if os.sys.platform == "darwin" and bundles:
        requested = [item.strip() for item in bundles.split(",") if item.strip()]
        # Sign the .app ourselves before creating the canonical DMG. A DMG made
        # by Tauri before ad-hoc signing contains a bundle Gatekeeper rejects.
        requested = [item for item in requested if item != "dmg"]
        if "app" not in requested:
            requested.append("app")
        tauri_bundles = ",".join(requested)
    if tauri_bundles:
        command.extend(["--bundles", tauri_bundles])
    env = dict(os.environ)
    env["PATH"] = f"{Path.home() / '.cargo/bin'}:{env.get('PATH', '')}"
    subprocess.run(command, cwd=TAURI_ROOT, env=env, check=True)
    bundle_root = SRC_TAURI / "target" / "release" / "bundle"
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    if os.sys.platform == "darwin":
        apps = sorted((bundle_root / "macos").glob("*.app"))
        if apps:
            subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", str(apps[-1])],
                check=True,
            )
            target_app = dist / "LES.app"
            if target_app.exists():
                shutil.rmtree(target_app)
            shutil.copytree(apps[-1], target_app, symlinks=True)
            if bundles and "dmg" in bundles.split(","):
                from tools.build_macos_dmg import build_dmg

                build_dmg(version, sign=False)
    elif os.sys.platform.startswith("win"):
        installers = sorted((bundle_root / "nsis").glob("*.exe"))
        if installers:
            shutil.copy2(installers[-1], dist / "LES-Setup.exe")
    return bundle_root


def main() -> int:
    contract = release_contract()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=str(contract["product_version"]))
    parser.add_argument("--build-number", type=int, default=int(contract["build_number"]))
    parser.add_argument("--bundles", default=None, help="Tauri bundle list, e.g. app,dmg or nsis")
    args = parser.parse_args()
    print(build(args.version, args.bundles, build_number=args.build_number))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
