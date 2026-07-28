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


def commits_match(actual: str, expected: str) -> bool:
    actual = str(actual or "").strip()
    expected = str(expected or "").strip()
    return (
        len(actual) >= 7
        and len(expected) >= 7
        and (actual == expected or actual.startswith(expected) or expected.startswith(actual))
    )


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


def require_platform_gate(commit: str) -> dict[str, Any]:
    """Require the macOS+Windows GitHub platform workflow for this exact commit."""
    raw = output(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            "verify.yml",
            "--commit",
            commit,
            "--limit",
            "10",
            "--json",
            "conclusion,status,headSha,url",
        ]
    )
    runs = json.loads(raw or "[]")
    matching = [
        item
        for item in runs
        if isinstance(item, dict) and str(item.get("headSha") or "") == commit
    ]
    if not matching:
        raise RuntimeError(f"macOS/Windows platform gate is missing for commit {commit}")
    successful = next(
        (
            item
            for item in matching
            if item.get("status") == "completed" and item.get("conclusion") == "success"
        ),
        None,
    )
    if successful is None:
        states = ", ".join(
            f"{item.get('status')}/{item.get('conclusion') or '-'}"
            for item in matching
        )
        raise RuntimeError(
            f"macOS/Windows platform gate is not successful for {commit}: {states}"
        )
    return successful


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
        "& git -C $repo fetch origin \"+${branch}:refs/remotes/origin/${branch}\"; "
        "if($LASTEXITCODE -ne 0){throw 'git fetch failed'}; "
        # A clean deployment checkout may still point at the previous amended
        # audit commit. Reset only this dedicated branch to its fetched origin
        # ref so the host installs the caller-verified exact SHA.
        "& git -C $repo checkout -B $branch \"refs/remotes/origin/$branch\"; "
        "if($LASTEXITCODE -ne 0){throw 'git checkout failed'}; "
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
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    offset = 0
    while offset < len(text):
        start = text.find("{", offset)
        if start < 0:
            break
        try:
            payload, end = decoder.raw_decode(text[start:])
        except (ValueError, TypeError):
            offset = start + 1
            continue
        if isinstance(payload, dict):
            objects.append(payload)
        offset = start + max(end, 1)
    if objects:
        return objects[-1]
    raise ValueError("no JSON object in output")


def _prepare_remote_update_checkout(
    *, host: str, repo_root: str, branch: str, commit: str
) -> None:
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$repo='{repo_root}'; $branch='{branch}'; $commit='{commit}'; "
        "$dirty=(& git -C $repo status --porcelain)-join \"`n\"; "
        "if($dirty){throw \"Legion checkout is dirty: $dirty\"}; "
        "& git -C $repo fetch origin \"+${branch}:refs/remotes/origin/${branch}\"; "
        "if($LASTEXITCODE -ne 0){throw 'git fetch failed'}; "
        "& git -C $repo checkout -B $branch \"refs/remotes/origin/$branch\"; "
        "if($LASTEXITCODE -ne 0){throw 'git checkout failed'}; "
        "$head=(& git -C $repo rev-parse HEAD).Trim(); "
        "if($head -ne $commit){throw \"Legion HEAD $head does not match $commit\"}; "
        "[ordered]@{ok=$true;head=$head}|ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = _last_json_object(
        output(["ssh", host, "powershell", "-NoProfile", "-EncodedCommand", encoded])
    )
    if result.get("head") != commit:
        raise RuntimeError("Legion prepared checkout does not match requested commit")


def _ensure_remote_baseline_cache(
    *,
    host: str,
    archive: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    script = (
        "$ErrorActionPreference='Stop'; "
        f"$sha='{expected_sha256}'; "
        "$root=Join-Path $env:LOCALAPPDATA 'LES\\update-cache\\baselines'; "
        "New-Item -ItemType Directory -Force -Path $root|Out-Null; "
        "$path=Join-Path $root ($sha+'.zip'); "
        "$cached=$false; "
        "if(Test-Path -LiteralPath $path){"
        "$actual=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant();"
        "$cached=($actual -eq $sha)}; "
        "[ordered]@{cached=$cached;path=$path;sha256=$sha}|ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    probe = _last_json_object(
        output(["ssh", host, "powershell", "-NoProfile", "-EncodedCommand", encoded])
    )
    if not probe.get("cached"):
        remote_path = str(probe["path"]).replace("\\", "/")
        run(["scp", str(archive), f"{host}:{remote_path}"])
        verify = _last_json_object(
            output(["ssh", host, "powershell", "-NoProfile", "-EncodedCommand", encoded])
        )
        if not verify.get("cached"):
            raise RuntimeError("Legion baseline cache checksum did not converge")
        probe = verify
        probe["transferred"] = True
    else:
        probe["transferred"] = False
    return probe


def remote_prepare_update(
    *,
    host: str,
    repo_root: str,
    branch: str,
    version: str,
    build_number: int,
    commit: str,
    smeta_baseline_archive: Path,
    smeta_baseline_sha256: str,
) -> dict[str, Any]:
    _prepare_remote_update_checkout(
        host=host,
        repo_root=repo_root,
        branch=branch,
        commit=commit,
    )
    baseline = _ensure_remote_baseline_cache(
        host=host,
        archive=smeta_baseline_archive,
        expected_sha256=smeta_baseline_sha256,
    )
    script = f"{repo_root.rstrip(chr(92))}\\tools\\windows_prepare_update.ps1"
    prepared = _last_json_object(
        output(
            [
                "ssh",
                host,
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script,
                "-Version",
                version,
                "-BuildNumber",
                str(build_number),
                "-BuildCommit",
                commit,
                "-RepoRoot",
                repo_root,
                "-SmetaBaselineArchive",
                str(baseline["path"]),
            ]
        )
    )
    if prepared.get("status") != "prepared" or prepared.get("commit") != commit:
        raise RuntimeError("Legion update preparation is not valid")
    return {
        "status": "prepared",
        "commit": commit,
        "cache_hit": bool(prepared.get("cache_hit")),
        "installer": prepared.get("installer"),
        "installer_sha256": prepared.get("sha256"),
        "baseline_sha256": baseline.get("sha256"),
        "baseline_transferred": bool(baseline.get("transferred")),
        "smoke": prepared.get("smoke"),
    }


def remote_apply_prepared_update(
    *,
    host: str,
    repo_root: str,
    version: str,
    build_number: int,
    commit: str,
) -> dict[str, Any]:
    script = f"{repo_root.rstrip(chr(92))}\\tools\\windows_apply_prepared_update.ps1"
    applied = _last_json_object(
        output(
            [
                "ssh",
                host,
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script,
                "-Version",
                version,
                "-BuildNumber",
                str(build_number),
                "-BuildCommit",
                commit,
                "-RepoRoot",
                repo_root,
            ]
        )
    )
    if applied.get("status") != "applied" or applied.get("commit") != commit:
        raise RuntimeError("Legion prepared update did not apply")
    applied["independent_persistence"] = verify_remote_production_persistence(
        host=host,
        expected_version=version,
        expected_build_number=build_number,
        expected_commit=commit,
    )
    return applied


def verify_remote_production_persistence(
    *,
    host: str,
    expected_version: str,
    expected_build_number: int | None = None,
    expected_commit: str = "",
) -> dict[str, Any]:
    """Probe production from a fresh SSH session after the build/deploy session has closed."""
    time.sleep(5)
    script = (
        "$ErrorActionPreference='Stop'; "
        "$version=Invoke-RestMethod -TimeoutSec 15 'http://127.0.0.1:8050/api/version'; "
        "$ui=Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 'http://127.0.0.1:8051/healthz'; "
        "$desktop=@(Get-Process -Name 'les-desktop' -ErrorAction SilentlyContinue).Count; "
        "[ordered]@{product_version=[string]$version.product_version;"
        "build_number=[int]$version.build_number;ui_status=[int]$ui.StatusCode;"
        "commit=[string]$(if($version.deployed_commit){$version.deployed_commit}else{$version.git_commit});"
        "desktop_processes=[int]$desktop}|ConvertTo-Json -Compress"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    last_failure = "probe did not run"
    for attempt in range(1, 7):
        try:
            raw = output(["ssh", host, "powershell", "-NoProfile", "-EncodedCommand", encoded])
            payload = _last_json_object(raw)
            if (
                payload.get("product_version") == expected_version
                and (
                    expected_build_number is None
                    or int(payload.get("build_number") or 0) == expected_build_number
                )
                and (
                    not expected_commit
                    or commits_match(str(payload.get("commit") or ""), expected_commit)
                )
                and int(payload.get("ui_status") or 0) == 200
                and int(payload.get("desktop_processes") or 0) >= 1
            ):
                return payload
            last_failure = f"unexpected production state: {payload}"
        except (subprocess.CalledProcessError, ValueError) as error:
            last_failure = str(error)
        if attempt < 6:
            time.sleep(5)
    raise RuntimeError(
        "production Legion did not survive release session after 6 attempts: "
        f"{last_failure}"
    )


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
    production_rag = production.get("rag") or {}
    production_mail = production.get("mail") or {}
    production_rollback = production.get("rollback") or {}
    if summary.get("build_commit") != commit or not smoke.get("ok"):
        raise RuntimeError("remote build commit or live smoke is not verified")
    if not smeta.get("ok") or int(smeta.get("norm_count") or 0) < 40_000:
        raise RuntimeError("clean-install smeta baseline was not verified")
    if (
        not production.get("ok")
        or production.get("les_version") != contract["product_version"]
        or not production_rag.get("index_contract_compatible")
        or production_rag.get("retrieval_proof") != "isolated_clean_install_smoke"
        or production_rag.get("user_corpus_mutated") is not False
        or production_mail.get("schedule") != "manual"
        or int(production_mail.get("trigger_count") or 0) != 0
        or production_mail.get("outlook_probe") != "ok"
        or production_rollback.get("available") is not True
        or production_rollback.get("data_untouched") is not True
    ):
        raise RuntimeError("production Legion deploy was not verified")
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


def publish(
    contract: dict[str, Any],
    *,
    extra_assets: Iterable[Path] = (),
) -> None:
    version = str(contract["product_version"])
    tag = f"v{version}"
    assets = [
        DIST / "LES-Setup.exe",
        DIST / "LES-Setup.exe.sha256",
        DIST / "latest.json",
        *(Path(path).resolve() for path in extra_assets),
    ]
    missing = [str(path) for path in assets if not path.is_file()]
    if missing:
        raise RuntimeError("release assets are missing: " + ", ".join(missing))
    names = [path.name for path in assets]
    if len(names) != len(set(names)):
        raise RuntimeError("release asset names must be unique")
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
            *(str(path) for path in assets),
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
        for asset in assets:
            if sha256(target / asset.name) != sha256(asset):
                raise RuntimeError(f"published {asset.name} differs from verified local artifact")


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
        "--extra-asset",
        action="append",
        default=[],
        type=Path,
        help="additional prebuilt verified asset to publish in the same release",
    )
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
    if args.publish:
        require_platform_gate(commit)
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
        publish(contract, extra_assets=args.extra_asset)
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
        publish(contract, extra_assets=args.extra_asset)
    print(json.dumps({"ok": True, "published": args.publish, **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"patch release failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
