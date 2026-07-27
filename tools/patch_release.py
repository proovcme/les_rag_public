"""Build, smoke and optionally publish one Windows patch release.

The public product version comes from config/version.json. The monotonically
increasing Windows package build stays separate and is never shown as a fourth
product-version component.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION_CONFIG = ROOT / "config" / "version.json"
PUBLIC_REPOSITORY = "proovcme/les_rag_public"


def load_contract(path: Path = VERSION_CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {"product_version", "build_number", "desktop_version"}
    missing = sorted(required - payload.keys())
    if missing:
        raise RuntimeError(f"version contract misses: {', '.join(missing)}")
    product = str(payload["product_version"])
    if len(product.split(".")) != 3 or any(not part.isdigit() for part in product.split(".")):
        raise RuntimeError(f"product_version must be SemVer X.Y.Z, got {product!r}")
    build = int(payload["build_number"])
    expected_desktop = f"5.1.{build}"
    if str(payload["desktop_version"]) != expected_desktop:
        raise RuntimeError(f"desktop_version must be {expected_desktop}")
    return payload


def run(command: Iterable[str], *, cwd: Path = ROOT, capture: bool = False) -> subprocess.CompletedProcess[str]:
    args = [str(item) for item in command]
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )


def output(command: Iterable[str], *, cwd: Path = ROOT) -> str:
    return run(command, cwd=cwd, capture=True).stdout.strip()


def require_tools(names: Iterable[str]) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise RuntimeError("required release tools are missing: " + ", ".join(missing))


def require_clean_pushed_branch(branch: str) -> str:
    if output(["git", "status", "--porcelain"]):
        raise RuntimeError("local checkout must be clean before patch release")
    current = output(["git", "branch", "--show-current"])
    if current != branch:
        raise RuntimeError(f"patch release must run from {branch}, current branch is {current}")
    run(["git", "fetch", "origin", branch])
    head = output(["git", "rev-parse", "HEAD"])
    remote = output(["git", "rev-parse", f"origin/{branch}"])
    if head != remote:
        raise RuntimeError(f"local {branch} is not identical to origin/{branch}")
    return head


def run_local_gates() -> None:
    for command in (
        ["make", "verify"],
        ["make", "test-mail-release"],
        ["make", "test-release"],
        ["make", "public-check"],
        ["uv", "lock", "--check"],
        ["git", "diff", "--check"],
    ):
        run(command)


def remote_build(
    *,
    host: str,
    repo_root: str,
    branch: str,
    version: str,
    build_number: int,
    commit: str,
    smeta_baseline_archive: Path,
) -> None:
    # The release script itself may not exist in an older checkout. Prepare the
    # canonical branch with an inline bootstrap first, then execute the
    # versioned script from the exact requested commit.
    prepare = (
        "$ErrorActionPreference='Stop'; try { "
        f"$repo='{repo_root}'; $branch='{branch}'; $commit='{commit}'; "
        "$dirty=(& git -C $repo status --porcelain)-join \"`n\"; "
        "if($dirty){throw \"Legion checkout is dirty before release: $dirty\"}; "
        "& git -C $repo fetch origin \"${branch}:refs/remotes/origin/${branch}\"; "
        "if($LASTEXITCODE -ne 0){throw 'git fetch failed'}; "
        "& git -C $repo show-ref --verify --quiet \"refs/heads/$branch\"; "
        "if($LASTEXITCODE -eq 0){"
        "& git -C $repo checkout $branch"
        "}else{"
        "& git -C $repo checkout -b $branch \"refs/remotes/origin/$branch\""
        "}; if($LASTEXITCODE -ne 0){throw 'git checkout failed'}; "
        "& git -C $repo pull --ff-only origin $branch; if($LASTEXITCODE -ne 0){throw 'git pull failed'}; "
        "$head=(& git -C $repo rev-parse HEAD).Trim(); "
        "if($head -ne $commit){throw \"Legion HEAD $head does not match $commit\"}; "
        "$dist=Join-Path $repo 'dist'; New-Item -ItemType Directory -Force -Path $dist | Out-Null; "
        "exit 0 } catch { Write-Error $_; exit 1 }"
    )
    encoded_prepare = base64.b64encode(prepare.encode("utf-16le")).decode("ascii")
    run(["ssh", host, "powershell", "-NoProfile", "-EncodedCommand", encoded_prepare])
    remote_baseline = f"{repo_root.replace('\\', '/')}/dist/LES-smeta-baseline.zip"
    run(["scp", str(smeta_baseline_archive), f"{host}:{remote_baseline}"])
    remote_script = f"{repo_root.rstrip('\\/')}\\tools\\windows_patch_release.ps1"
    run(
        [
            "ssh", host, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            remote_script,
            "-Version", version,
            "-BuildNumber", str(build_number),
            "-BuildCommit", commit,
            "-Branch", branch,
            "-RepoRoot", repo_root,
            "-SmetaBaselineArchive", f"{repo_root.rstrip('\\/')}\\dist\\LES-smeta-baseline.zip",
        ]
    )


def fetch_remote_artifacts(*, host: str, repo_root: str) -> None:
    DIST.mkdir(exist_ok=True)
    for name in ("LES-Setup.exe", "LES-Setup.exe.sha256", "windows-patch-release.json"):
        run(["scp", f"{host}:{repo_root.replace('\\', '/')}/dist/{name}", str(DIST / name)])


def _last_json_object(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("no JSON object in output")


def verify_remote_production_persistence(*, host: str, expected_version: str) -> dict[str, Any]:
    """Probe production from a fresh SSH session after the build/deploy session has closed."""
    time.sleep(5)
    script = (
        "$ErrorActionPreference='Stop'; "
        "$version=Invoke-RestMethod -TimeoutSec 15 'http://127.0.0.1:8050/api/version'; "
        "$ui=Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 'http://127.0.0.1:8051/healthz'; "
        "$desktop=@(Get-Process -Name 'les-desktop' -ErrorAction SilentlyContinue).Count; "
        "[ordered]@{product_version=[string]$version.product_version;"
        "build_number=[int]$version.build_number;ui_status=[int]$ui.StatusCode;"
        "desktop_processes=[int]$desktop}|ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    raw = output(["ssh", host, "powershell", "-NoProfile", "-EncodedCommand", encoded])
    try:
        payload = _last_json_object(raw)
    except ValueError as error:
        raise RuntimeError(f"independent Legion persistence probe returned invalid JSON: {raw[-500:]}") from error
    if (
        payload.get("product_version") != expected_version
        or int(payload.get("ui_status") or 0) != 200
        or int(payload.get("desktop_processes") or 0) < 1
    ):
        raise RuntimeError(f"production Legion did not survive release session: {payload}")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_local_artifacts(contract: dict[str, Any], commit: str) -> dict[str, Any]:
    summary = json.loads((DIST / "windows-patch-release.json").read_text(encoding="utf-8-sig"))
    checksum = (DIST / "LES-Setup.exe.sha256").read_text(encoding="ascii").split()[0].lower()
    actual = sha256(DIST / "LES-Setup.exe")
    if actual != checksum or actual != str(summary.get("sha256") or "").lower():
        raise RuntimeError("installer SHA-256 does not match release summary")
    if summary.get("product_version") != contract["product_version"]:
        raise RuntimeError("remote product version does not match config/version.json")
    if int(summary.get("build_number") or -1) != int(contract["build_number"]):
        raise RuntimeError("remote build number does not match config/version.json")
    smoke = summary.get("smoke") or {}
    production = summary.get("production") or {}
    smeta = smoke.get("smeta_baseline") or {}
    expected_pdf_count = int(production.get("expected_pdf_count") or 0)
    if summary.get("build_commit") != commit or not smoke.get("ok"):
        raise RuntimeError("remote build commit or live smoke is not verified")
    if not smeta.get("ok") or int(smeta.get("norm_count") or 0) < 40_000:
        raise RuntimeError("clean-install smeta baseline was not verified")
    if (
        not production.get("ok")
        or production.get("les_version") != contract["product_version"]
        or expected_pdf_count < 4
        or int(production.get("indexed_files") or 0) != expected_pdf_count
        or int(production.get("indexed_chunks") or 0) <= 0
        or not production.get("smoke_dataset_removed")
    ):
        raise RuntimeError("production Legion heavy-PDF deploy was not verified")
    return summary


def create_release_files(contract: dict[str, Any], commit: str, notes: str) -> None:
    version = str(contract["product_version"])
    manifest = {
        "schema": "les.update.v1",
        "version": version,
        "name": f"ЛЕС {version}",
        "notes": notes.strip(),
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "html_url": f"https://github.com/{PUBLIC_REPOSITORY}/releases/tag/v{version}",
        "build_number": int(contract["build_number"]),
        "build_commit": commit,
    }
    (DIST / "latest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (DIST / "release-notes.md").write_text(
        f"## ЛЕС {version}\n\n{notes.strip()}\n", encoding="utf-8"
    )


def publish(contract: dict[str, Any]) -> None:
    version = str(contract["product_version"])
    tag = f"v{version}"
    probe = subprocess.run(
        ["gh", "release", "view", tag, "--repo", PUBLIC_REPOSITORY],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if probe.returncode == 0:
        raise RuntimeError(f"release {tag} already exists")
    run(
        [
            "gh", "release", "create", tag,
            str(DIST / "LES-Setup.exe"),
            str(DIST / "LES-Setup.exe.sha256"),
            str(DIST / "latest.json"),
            "--repo", PUBLIC_REPOSITORY,
            "--title", f"ЛЕС {version}",
            "--notes-file", str(DIST / "release-notes.md"),
        ]
    )
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        run(["gh", "release", "download", tag, "--repo", PUBLIC_REPOSITORY, "--dir", str(target)])
        if sha256(target / "LES-Setup.exe") != sha256(DIST / "LES-Setup.exe"):
            raise RuntimeError("published installer differs from verified local artifact")
        published = json.loads((target / "latest.json").read_text(encoding="utf-8"))
        if published.get("version") != version:
            raise RuntimeError("published latest.json has the wrong product version")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--legion-host", default="legion")
    parser.add_argument("--legion-root", default=r"C:\Users\Oleg\les_rag")
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument(
        "--smeta-baseline-root",
        type=Path,
        default=None,
        help="operator root containing the verified data/gesn_base and data/smeta_base baseline",
    )
    parser.add_argument(
        "--smeta-baseline-archive",
        type=Path,
        default=None,
        help="reuse an already verified LES-smeta-baseline.zip",
    )
    parser.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--resume-verified-commit",
        default="",
        help="publish already fetched/verified Legion artifacts for this ancestor runtime commit",
    )
    parser.add_argument("--skip-gates", action="store_true", help="local development only; cannot publish")
    args = parser.parse_args(argv)

    if args.smeta_baseline_root and args.smeta_baseline_archive:
        raise RuntimeError("choose either --smeta-baseline-root or --smeta-baseline-archive")
    if args.publish and args.skip_gates:
        raise RuntimeError("publishing cannot skip local gates")
    require_tools(("git", "uv", "make", "ssh", "scp", *( ("gh",) if args.publish else () )))
    contract = load_contract()
    commit = require_clean_pushed_branch(args.branch)
    if args.resume_verified_commit:
        if not args.publish:
            raise RuntimeError("resume requires --publish")
        run(["git", "merge-base", "--is-ancestor", args.resume_verified_commit, commit])
        fetch_remote_artifacts(host=args.legion_host, repo_root=args.legion_root)
        summary = verify_local_artifacts(contract, args.resume_verified_commit)
        notes = args.notes_file.read_text(encoding="utf-8") if args.notes_file else (
            "Исправительное обновление ЛЕС. Подробности зафиксированы в журнале выпуска."
        )
        create_release_files(contract, args.resume_verified_commit, notes)
        publish(contract)
        print(json.dumps({"ok": True, "published": True, "resumed": True, **summary}, ensure_ascii=False, indent=2))
        return 0
    from tools.smeta_release_baseline import create_archive, verify_archive

    if args.smeta_baseline_archive:
        baseline = args.smeta_baseline_archive.resolve()
        verify_archive(baseline)
    else:
        baseline = DIST / "LES-smeta-baseline.zip"
        create_archive((args.smeta_baseline_root or ROOT).resolve(), baseline)
    if not args.skip_gates:
        run_local_gates()
    remote_build(
        host=args.legion_host,
        repo_root=args.legion_root,
        branch=args.branch,
        version=str(contract["product_version"]),
        build_number=int(contract["build_number"]),
        commit=commit,
        smeta_baseline_archive=baseline,
    )
    persistence = verify_remote_production_persistence(
        host=args.legion_host,
        expected_version=str(contract["product_version"]),
    )
    fetch_remote_artifacts(host=args.legion_host, repo_root=args.legion_root)
    summary = verify_local_artifacts(contract, commit)
    summary["independent_persistence"] = persistence
    notes = args.notes_file.read_text(encoding="utf-8") if args.notes_file else (
        "Исправительное обновление ЛЕС. Подробности зафиксированы в журнале выпуска."
    )
    create_release_files(contract, commit, notes)
    if args.publish:
        publish(contract)
    print(json.dumps({"ok": True, "published": args.publish, **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"patch release failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
