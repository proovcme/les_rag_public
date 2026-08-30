#!/usr/bin/env python3
"""Prepare immutable LES candidates and prove them on Legion before publication."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from tools import (
    github_patch_release,
    patch_release,
    release_receipt,
    windows_release_acceptance,
)
from tools.release_classification import ReleaseClassification, classify_release


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = ROOT / "dist" / "release-work"
PREPARE_GATES = (
    ("version", ("uv", "run", "python", "tools/sync_version_contract.py", "--check")),
    ("runtime_map", ("uv", "run", "python", "tools/code_runtime_map.py", "--check")),
    ("verify", ("make", "verify")),
    ("test", ("make", "test")),
    ("updater", ("make", "test-updater")),
    ("public", ("make", "public-check")),
)


def _run(command: Sequence[str], *, root: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=root,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )


def resolve_commit(root: Path, value: str = "HEAD") -> str:
    commit = _run(
        ("git", "rev-parse", "--verify", f"{value}^{{commit}}"),
        root=Path(root),
        capture=True,
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise RuntimeError("release target is not an exact Git commit")
    return commit


def require_release_source(*, root: Path, branch: str, target: str) -> str:
    root = Path(root).resolve()
    if _run(("git", "status", "--porcelain"), root=root, capture=True).stdout.strip():
        raise RuntimeError("release preparation requires a clean checkout")
    current = _run(("git", "branch", "--show-current"), root=root, capture=True).stdout.strip()
    if current != branch:
        raise RuntimeError(f"release preparation requires branch {branch}, current is {current}")
    _run(("git", "fetch", "origin", branch), root=root)
    commit = resolve_commit(root, target)
    upstream = resolve_commit(root, f"origin/{branch}")
    if commit != upstream or resolve_commit(root, "HEAD") != commit:
        raise RuntimeError("release target, HEAD, and pushed branch must be identical")
    return commit


def load_contract(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads((Path(root) / "config" / "version.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("release version contract is unreadable") from exc
    if (
        re.fullmatch(r"\d+\.\d+\.\d+", str(payload.get("product_version") or "")) is None
        or int(payload.get("build_number") or 0) <= 0
    ):
        raise RuntimeError("release version contract is invalid")
    return payload


def run_prepare_gates(root: Path) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for label, command in PREPARE_GATES:
        started = time.monotonic()
        _run(command, root=Path(root))
        evidence.append(
            {
                "gate": label,
                "command": " ".join(command),
                "exit_code": 0,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
    return evidence


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_patch_candidate(
    *, base: str, target: str, output: Path, full_feed: Path, **_kwargs: Any
) -> dict[str, Any]:
    output = Path(output).resolve()
    public = output / "public"
    acceptance = output / "acceptance"
    public.mkdir(parents=True)
    acceptance.mkdir(parents=True)
    feed = github_patch_release.build_github_patch_release(
        base, target, public, full_feed=Path(full_feed)
    )
    public_archive = public / "les-patch.zip"
    acceptance_archive = acceptance / public_archive.name
    shutil.copy2(public_archive, acceptance_archive)
    local_feed = {
        "schema": "les.vps-patch-feed.v1",
        "patch": feed["patch"],
        "archive_url": acceptance_archive.name,
        "archive_sha256": _sha256(acceptance_archive),
        "archive_bytes": acceptance_archive.stat().st_size,
    }
    (acceptance / "latest.json").write_text(
        json.dumps(local_feed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if _sha256(public_archive) != _sha256(acceptance_archive):
        raise RuntimeError("acceptance patch differs from public candidate bytes")
    return {
        "assets": sorted(path for path in public.iterdir() if path.is_file()),
        "acceptance_path": acceptance,
        "build": feed,
    }


def build_full_candidate(
    *,
    target: str,
    output: Path,
    contract: dict[str, Any],
    args: argparse.Namespace,
    **_kwargs: Any,
) -> dict[str, Any]:
    baseline = getattr(args, "smeta_baseline_archive", None)
    if baseline is None:
        raise RuntimeError("full release preparation requires --smeta-baseline-archive")
    baseline = Path(baseline).resolve()
    if not baseline.is_file():
        raise RuntimeError("verified smeta baseline archive is missing")
    prepared = patch_release.remote_prepare_update(
        host=args.host,
        repo_root=args.repo_root,
        branch=args.branch,
        version=str(contract["product_version"]),
        build_number=int(contract["build_number"]),
        commit=target,
        smeta_baseline_archive=baseline,
        smeta_baseline_sha256=_sha256(baseline),
    )
    public = Path(output).resolve() / "public"
    public.mkdir(parents=True)
    installer = public / "LES-Setup.exe"
    _run(("scp", f"{args.host}:{str(prepared['installer']).replace(chr(92), '/')}", str(installer)), root=Path(args.root))
    if _sha256(installer) != str(prepared.get("installer_sha256") or "").lower():
        raise RuntimeError("fetched full candidate differs from prepared installer")
    (public / "LES-Setup.exe.sha256").write_text(
        f"{_sha256(installer)}  LES-Setup.exe\n", encoding="ascii"
    )
    return {
        "assets": sorted(public.iterdir()),
        "acceptance_path": Path(str(prepared["installer"])),
        "build": prepared,
    }


def _latest_path(work_root: Path) -> Path:
    return Path(work_root).resolve() / "latest.json"


def _write_latest(work_root: Path, state_path: Path, release_id: str) -> None:
    target = _latest_path(work_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(
            {"release_id": release_id, "state_path": str(Path(state_path).resolve())},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _base_from_args(args: argparse.Namespace) -> str:
    if str(getattr(args, "base", "") or ""):
        return resolve_commit(args.root, args.base)
    try:
        feed = json.loads(Path(args.full_feed).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("full-release feed is required to determine the patch base") from exc
    base = str(feed.get("target_commit") or feed.get("build_commit") or "")
    return resolve_commit(args.root, base)


def _classification_evidence(classification: ReleaseClassification) -> dict[str, Any]:
    return {
        "kind": classification.kind,
        "runtime_files": list(classification.runtime_files),
        "triggers": [
            {"path": trigger.path, "reason": trigger.reason}
            for trigger in classification.triggers
        ],
        "ignored_version_surfaces": list(classification.ignored_version_surfaces),
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    work_root = Path(args.work_root).resolve()
    target = (
        resolve_commit(root, args.target)
        if args.skip_gates
        else require_release_source(root=root, branch=args.branch, target=args.target)
    )
    contract = load_contract(root)
    base = _base_from_args(args)
    classification = classify_release(base, target, root=root)
    gates = [] if args.skip_gates else run_prepare_gates(root)
    candidate_root = work_root / "candidates" / target
    if candidate_root.exists():
        raise RuntimeError(f"candidate output already exists: {candidate_root}")
    builder = build_patch_candidate if classification.kind == "patch" else build_full_candidate
    built = builder(
        base=base,
        target=target,
        output=candidate_root,
        full_feed=args.full_feed,
        contract=contract,
        args=args,
    )
    state_path = release_receipt.create_attempt(
        root=work_root / "attempts",
        release_class=classification.kind,
        product_version=str(contract["product_version"]),
        build_number=int(contract["build_number"]),
        target_commit=target,
        base_commits=[base],
        host=args.host,
        assets=list(built["assets"]),
    )
    prepared = release_receipt.transition(
        state_path,
        expected="planned",
        target="prepared",
        evidence={
            "gates": gates,
            "classification": _classification_evidence(classification),
            "candidate_root": str(candidate_root),
            "acceptance_path": str(built["acceptance_path"]),
        },
    )
    if args.skip_gates:
        prepared = release_receipt.mark_non_publishable(
            state_path, reason="prepare gates were skipped"
        )
    _write_latest(work_root, state_path, str(prepared["release_id"]))
    return {**prepared, "state_path": str(state_path)}


def _attempt_path(args: argparse.Namespace) -> Path:
    if getattr(args, "attempt", None):
        return Path(args.attempt).resolve()
    latest = json.loads(_latest_path(args.work_root).read_text(encoding="utf-8-sig"))
    return Path(str(latest["state_path"])).resolve()


def _prepared_evidence(attempt: dict[str, Any]) -> dict[str, Any]:
    for item in attempt.get("transitions", []):
        if item.get("stage") == "prepared":
            evidence = item.get("evidence")
            if isinstance(evidence, dict):
                return evidence
    raise RuntimeError("prepared release evidence is missing")


def _artifact_paths(attempt: dict[str, Any]) -> list[Path]:
    return [Path(str(item["path"])).resolve() for item in attempt.get("artifacts", [])]


def _verify_patch_install_bytes(attempt: dict[str, Any], acceptance_path: Path) -> None:
    public = next(
        (path for path in _artifact_paths(attempt) if path.name == "les-patch.zip"),
        None,
    )
    local = Path(acceptance_path) / "les-patch.zip"
    if public is None or not local.is_file() or _sha256(public) != _sha256(local):
        raise RuntimeError("installed patch bytes differ from accepted public candidate")


def is_local_host(host: str) -> bool:
    label = str(host).split("@")[-1].split(".")[0].casefold()
    names = {
        "localhost",
        "127",
        platform.node().split(".")[0].casefold(),
        os.getenv("COMPUTERNAME", "").split(".")[0].casefold(),
    }
    return label in names


def run_local_acceptance(
    *, attempt: dict[str, Any], acceptance_path: Path, args: argparse.Namespace
) -> dict[str, Any]:
    expected = {
        "product_version": attempt["product_version"],
        "build_number": attempt["build_number"],
        "target_commit": attempt["target_commit"],
    }
    if attempt["release_class"] == "patch":
        _verify_patch_install_bytes(attempt, acceptance_path)
        return windows_release_acceptance.accept_patch(
            package_dir=acceptance_path,
            runtime=Path(args.runtime),
            state=Path(args.state),
            expected=expected,
        )
    job = getattr(args, "job", None)
    if job is None:
        raise RuntimeError("full local acceptance requires --job")
    return windows_release_acceptance.accept_full(
        job_path=Path(job),
        install=Path(args.install),
        state=Path(args.state),
        expected=expected,
    )


def _remote_json(output: str) -> dict[str, Any]:
    starts = [index for index, char in enumerate(output) if char == "{"]
    for index in reversed(starts):
        try:
            payload = json.loads(output[index:])
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("Legion acceptance returned no JSON result")


def run_remote_acceptance(
    *, attempt: dict[str, Any], acceptance_path: Path, args: argparse.Namespace
) -> dict[str, Any]:
    release_id = str(attempt["release_id"])
    remote_dir = f"{args.repo_root.rstrip(chr(92))}\\dist\\release-work\\incoming\\{release_id}"
    prepare_script = (
        "$ErrorActionPreference='Stop';"
        f"$p='{remote_dir.replace(chr(39), chr(39) * 2)}';"
        "New-Item -ItemType Directory -Force -Path $p|Out-Null;"
        f"$head=(git -C '{args.repo_root}' rev-parse HEAD).Trim();"
        f"if($head -ne '{attempt['target_commit']}'){{throw 'Legion checkout identity mismatch'}}"
    )
    encoded = base64.b64encode(prepare_script.encode("utf-16le")).decode("ascii")
    _run(("ssh", args.host, "powershell", "-NoProfile", "-EncodedCommand", encoded), root=Path(args.root))
    expected = {
        "product_version": attempt["product_version"],
        "build_number": attempt["build_number"],
        "target_commit": attempt["target_commit"],
    }
    expected_json = json.dumps(expected, ensure_ascii=True, separators=(",", ":"))
    expected_literal = expected_json.replace("'", "''")
    if attempt["release_class"] == "patch":
        _verify_patch_install_bytes(attempt, acceptance_path)
        for path in sorted(Path(acceptance_path).iterdir()):
            if path.is_file():
                _run(
                    (
                        "scp",
                        str(path),
                        f"{args.host}:{remote_dir.replace(chr(92), '/')}/{path.name}",
                    ),
                    root=Path(args.root),
                )
        execution_script = (
            "$ErrorActionPreference='Stop';"
            f"$work='{remote_dir.replace(chr(39), chr(39) * 2)}';"
            "$expected=Join-Path $work 'expected.json';"
            f"[IO.File]::WriteAllText($expected,'{expected_literal}',(New-Object Text.UTF8Encoding($false)));"
            f"Set-Location -LiteralPath '{args.repo_root.replace(chr(39), chr(39) * 2)}';"
            f"& uv run python tools/windows_release_acceptance.py patch --state '{str(args.state)}' "
            f"--runtime '{str(args.runtime)}' --package-dir $work --expected $expected;"
            "if($LASTEXITCODE -ne 0){throw 'Legion patch acceptance failed'}"
        )
    else:
        installer_record = next(
            (
                item
                for item in attempt.get("artifacts", [])
                if item.get("name") == "LES-Setup.exe"
            ),
            None,
        )
        if installer_record is None:
            raise RuntimeError("full release attempt has no installer binding")
        installer = str(acceptance_path).replace("'", "''")
        repo = str(args.repo_root).replace("'", "''")
        execution_script = (
            "$ErrorActionPreference='Stop';"
            f"$work='{remote_dir.replace(chr(39), chr(39) * 2)}';"
            f"$installer='{installer}';"
            "if(-not(Test-Path -LiteralPath $installer)){throw 'Prepared installer is missing'};"
            f"if((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{installer_record['sha256']}')"
            "{throw 'Prepared installer binding changed'};"
            "$state=Join-Path $env:LOCALAPPDATA 'LES';"
            "$install=Join-Path $env:LOCALAPPDATA 'Programs\\LES';"
            "$status=Join-Path $state 'artifacts\\updates\\hard-update-status.json';"
            "$prepared=Get-Content -LiteralPath (Join-Path (Split-Path $installer) 'manifest.json') -Raw|ConvertFrom-Json;"
            "$job=Join-Path $work 'hard-update-job.json';"
            "$expected=Join-Path $work 'expected.json';"
            f"[IO.File]::WriteAllText($expected,'{expected_literal}',(New-Object Text.UTF8Encoding($false)));"
            "$payload=[ordered]@{schema='les.windows-hard-update.v1';"
            f"update_id='acceptance-{release_id}';installer=$installer;installer_sha256='{installer_record['sha256']}';"
            f"install_root=$install;state_root=$state;status_path=$status;product_version='{attempt['product_version']}';"
            f"build_number={int(attempt['build_number'])};desktop_version=[string]$prepared.desktop_version;"
            f"target_commit='{attempt['target_commit']}';branch='acceptance'}};"
            "[IO.File]::WriteAllText($job,($payload|ConvertTo-Json -Depth 6),(New-Object Text.UTF8Encoding($false)));"
            f"Set-Location -LiteralPath '{repo}';"
            "& uv run python tools/windows_release_acceptance.py full --state $state --install $install --job $job --expected $expected;"
            "if($LASTEXITCODE -ne 0){throw 'Legion full acceptance failed'}"
        )
    execution_encoded = base64.b64encode(execution_script.encode("utf-16le")).decode("ascii")
    completed = _run(
        (
            "ssh",
            args.host,
            "powershell",
            "-NoProfile",
            "-EncodedCommand",
            execution_encoded,
        ),
        root=Path(args.root),
        capture=True,
    )
    return _remote_json(completed.stdout)


def _advance_acceptance(state_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    steps = (
        ("prepared", "legion_installed", result.get("first_install") or {}),
        ("legion_installed", "legion_smoke_passed", result.get("first_smoke") or {}),
        (
            "legion_smoke_passed",
            "rollback_passed",
            {
                "rollback": result.get("rollback") or {},
                "restored_smoke": result.get("restored_smoke") or {},
            },
        ),
        ("rollback_passed", "legion_reinstalled", result.get("second_install") or {}),
        (
            "legion_reinstalled",
            "accepted",
            {
                "final_smoke": result.get("final_smoke") or {},
                "final_identity": result.get("final_identity") or {},
            },
        ),
    )
    current: dict[str, Any] = {}
    for expected, target, evidence in steps:
        current = release_receipt.transition(
            state_path, expected=expected, target=target, evidence=evidence
        )
    return current


def accept(args: argparse.Namespace) -> dict[str, Any]:
    state_path = _attempt_path(args)
    attempt = release_receipt.load_attempt(state_path)
    if attempt.get("stage") != "prepared":
        raise RuntimeError("prepared release attempt required for Legion acceptance")
    if str(args.host).casefold() != str(attempt.get("host") or "").casefold():
        raise RuntimeError("release host differs from prepared attempt")
    release_receipt.verify_binding(
        attempt,
        commit=resolve_commit(args.root, "HEAD"),
        assets=_artifact_paths(attempt),
    )
    acceptance_path = Path(str(_prepared_evidence(attempt)["acceptance_path"]))
    try:
        result = (
            run_local_acceptance(attempt=attempt, acceptance_path=acceptance_path, args=args)
            if is_local_host(args.host)
            else run_remote_acceptance(attempt=attempt, acceptance_path=acceptance_path, args=args)
        )
        if result.get("accepted") is not True:
            raise RuntimeError("Legion acceptance did not return accepted=true")
        accepted = _advance_acceptance(state_path, result)
        return {**accepted, "state_path": str(state_path)}
    except Exception as exc:
        release_receipt.fail_attempt(
            state_path,
            stage="legion_acceptance",
            error=str(exc),
            recovery={"runner_completed": False},
        )
        raise


def status(attempt_path: Path) -> dict[str, Any]:
    return release_receipt.load_attempt(Path(attempt_path))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(root=ROOT, work_root=DEFAULT_WORK_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--root", type=Path, default=ROOT)
    prepare_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    prepare_cmd.add_argument("--branch", default="codex/les-0.30.0-bootstrap-updater")
    prepare_cmd.add_argument("--target", default="HEAD")
    prepare_cmd.add_argument("--base", default="")
    prepare_cmd.add_argument("--host", default="legion")
    prepare_cmd.add_argument("--full-feed", type=Path, default=ROOT / "dist" / "latest.json")
    prepare_cmd.add_argument("--repo-root", default=r"C:\Users\Oleg\les_rag")
    prepare_cmd.add_argument("--smeta-baseline-archive", type=Path)
    prepare_cmd.add_argument("--skip-gates", action="store_true")
    accept_cmd = sub.add_parser("accept")
    accept_cmd.add_argument("--root", type=Path, default=ROOT)
    accept_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    accept_cmd.add_argument("--attempt", type=Path)
    accept_cmd.add_argument("--host", default="legion")
    accept_cmd.add_argument("--repo-root", default=r"C:\Users\Oleg\les_rag")
    local = os.getenv("LOCALAPPDATA", "")
    accept_cmd.add_argument("--runtime", type=Path, default=Path(local) / "Programs" / "LES" / "runtime")
    accept_cmd.add_argument("--state", type=Path, default=Path(local) / "LES")
    accept_cmd.add_argument("--install", type=Path, default=Path(local) / "Programs" / "LES")
    accept_cmd.add_argument("--job", type=Path)
    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--attempt", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        result = prepare(args)
    elif args.command == "accept":
        result = accept(args)
    else:
        result = status(args.attempt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Release orchestration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
