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
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from tools import (
    github_patch_release,
    patch_release,
    release_receipt,
    windows_release_acceptance,
)
from tools.release_classification import ReleaseClassification, ReleaseTrigger, classify_release


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


def resolve_tree(root: Path, value: str = "HEAD") -> str:
    tree = _run(
        ("git", "rev-parse", "--verify", f"{value}^{{tree}}"),
        root=Path(root),
        capture=True,
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise RuntimeError("release target tree is not exact")
    return tree


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


def sync_public_main(*, root: Path, target: str) -> dict[str, Any]:
    """Fast-forward the public mirror to an already accepted release commit."""
    root = Path(root).resolve()
    target_commit = resolve_commit(root, target)
    _run(("git", "fetch", "public", "main"), root=root)
    before = resolve_commit(root, "refs/remotes/public/main")
    if before == target_commit:
        return {"before": before, "after": target_commit, "fast_forwarded": False}
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", before, target_commit],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if ancestry.returncode != 0:
        raise RuntimeError(
            "public main is not a fast-forward ancestor of the accepted release"
        )
    _run(
        ("git", "push", "public", f"{target_commit}:refs/heads/main"),
        root=root,
    )
    _run(("git", "fetch", "public", "main"), root=root)
    after = resolve_commit(root, "refs/remotes/public/main")
    if after != target_commit:
        raise RuntimeError("public main fast-forward verification failed")
    return {"before": before, "after": after, "fast_forwarded": True}


def current_branch(root: Path) -> str:
    branch = _run(
        ("git", "branch", "--show-current"), root=Path(root), capture=True
    ).stdout.strip()
    if not branch:
        raise RuntimeError("release preparation cannot run from detached HEAD")
    return branch


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
    args = _kwargs.get("args")
    installed_runtime = (
        Path(args.runtime).resolve()
        if args is not None and getattr(args, "runtime", None)
        else None
    )
    feed = github_patch_release.build_github_patch_release(
        base,
        target,
        public,
        full_feed=Path(full_feed),
        progress=_print_patch_progress,
        installed_runtime=installed_runtime,
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
        "candidate_assets": [public_archive],
        "acceptance_path": acceptance,
        "build": feed,
    }


def _print_patch_progress(event: dict[str, Any]) -> None:
    stage = str(event.get("stage") or "")
    current = int(event.get("current") or 0)
    total = int(event.get("total") or 0)
    if current not in {1, total} and current % 10 != 0:
        return
    if stage == "history":
        message = f"История патча: {current}/{total}"
    elif stage == "files":
        path = str(event.get("path") or "")
        message = f"Файлы патча: {current}/{total} — {path}"
    else:
        message = f"Патч: {current}/{total}"
    print(message, flush=True)


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
    local_build = is_local_host(args.host)
    if local_build:
        command = (
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(args.root) / "tools" / "windows_prepare_update.ps1"),
            "-Version",
            str(contract["product_version"]),
            "-BuildNumber",
            str(int(contract["build_number"])),
            "-BuildCommit",
            target,
            "-RepoRoot",
            str(Path(args.root).resolve()),
            "-SmetaBaselineArchive",
            str(baseline),
        )
        try:
            completed = _run(command, root=Path(args.root), capture=True)
        except subprocess.CalledProcessError as exc:
            details = "\n".join(
                part.strip()
                for part in (exc.stdout, exc.stderr)
                if isinstance(part, str) and part.strip()
            )
            if len(details) > 12_000:
                details = details[-12_000:]
            suffix = f":\n{details}" if details else ""
            raise RuntimeError(
                f"local Windows update preparation failed{suffix}"
            ) from exc
        prepared = _remote_json(completed.stdout)
        if (
            prepared.get("schema") != "les.windows.prepared-package.v1"
            or prepared.get("status") != "prepared"
            or prepared.get("commit") != target
        ):
            raise RuntimeError("local Windows package boundary is not valid")
    else:
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
        if (
            prepared.get("schema") != "les.windows.prepared-package.v1"
            or prepared.get("status") != "prepared"
            or prepared.get("commit") != target
        ):
            raise RuntimeError("remote Windows package boundary is not valid")
    output = Path(output).resolve()
    public = output / "public"
    acceptance = output / "acceptance"
    public.mkdir(parents=True)
    installer = public / "LES-Setup.exe"
    if local_build:
        acceptance.mkdir(parents=True)
        shutil.copy2(Path(str(prepared["installer"])), installer)
    else:
        _run(("scp", f"{args.host}:{str(prepared['installer']).replace(chr(92), '/')}", str(installer)), root=Path(args.root))
    if _sha256(installer) != str(prepared.get("installer_sha256") or "").lower():
        expected_sha = str(prepared.get("sha256") or "").lower()
        if _sha256(installer) != expected_sha:
            raise RuntimeError("fetched full candidate differs from prepared installer")
    (public / "LES-Setup.exe.sha256").write_text(
        f"{_sha256(installer)}  LES-Setup.exe\n", encoding="ascii"
    )
    acceptance_path: Path = Path(str(prepared["installer"]))
    if local_build:
        acceptance_installer = acceptance / installer.name
        shutil.copy2(installer, acceptance_installer)
        job = {
            "schema": "les.windows-hard-update.v1",
            "update_id": f"acceptance-{target}",
            "installer": str(acceptance_installer.resolve()),
            "installer_sha256": _sha256(acceptance_installer),
            "install_root": str(Path(args.install).resolve()),
            "state_root": str(Path(args.state).resolve()),
            "status_path": str(
                (Path(args.state).resolve() / "artifacts" / "updates" / "hard-update-status.json")
            ),
            "product_version": str(contract["product_version"]),
            "build_number": int(contract["build_number"]),
            "desktop_version": str(prepared["desktop_version"]),
            "target_commit": target,
            "branch": str(args.branch),
        }
        (acceptance / "hard-update-job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        acceptance_path = acceptance
    return {
        "assets": sorted(public.iterdir()),
        "candidate_assets": [installer],
        "acceptance_path": acceptance_path,
        "build": prepared,
    }


def _latest_path(work_root: Path) -> Path:
    return Path(work_root).resolve() / "latest.json"


def _write_latest(
    work_root: Path, state_path: Path, release_id: str, *, artifact: bool = False
) -> None:
    target = _latest_path(work_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    pointer = (
        {"artifact_id": release_id, "artifact_path": str(Path(state_path).resolve())}
        if artifact
        else {"release_id": release_id, "state_path": str(Path(state_path).resolve())}
    )
    temporary.write_text(
        json.dumps(
            pointer,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def resolve_full_feed(args: argparse.Namespace) -> Path:
    """Resolve the attested full-release feed used as the cumulative patch base."""
    configured = getattr(args, "full_feed", None)
    candidates = (
        [Path(configured)]
        if configured is not None
        else [
            Path(args.work_root) / "full-base" / "latest.json",
            Path(getattr(args, "repo_root", ROOT))
            / "dist"
            / "release-work"
            / "full-base"
            / "latest.json",
        ]
    )
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_file():
            return resolved
    checked = ", ".join(str(candidate.resolve()) for candidate in candidates)
    raise RuntimeError(f"attested full-release feed is missing; checked: {checked}")


def _base_from_args(args: argparse.Namespace) -> str:
    if str(getattr(args, "base", "") or ""):
        try:
            args.full_feed = resolve_full_feed(args)
        except RuntimeError:
            if not bool(getattr(args, "skip_gates", False)):
                raise
        return resolve_commit(args.root, args.base)
    args.full_feed = resolve_full_feed(args)
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


def validate_patch_pipeline(classification: ReleaseClassification) -> None:
    """Fail before expensive gates when any patch layer rejects a classified file."""
    if classification.kind != "patch":
        return
    from proxy.services import update_service
    from tools import vps_patch, vps_patch_apply

    for path in classification.runtime_files:
        normalized = vps_patch.normalize_path(path)
        vps_patch_apply.safe_relative_path(normalized)
        if not (
            normalized in update_service.VPS_PATCH_ALLOWED_FILES
            or normalized.startswith(update_service.VPS_PATCH_ALLOWED_ROOTS)
        ):
            raise ValueError(f"path is outside updater patch allowlist: {normalized}")


def _desktop_version(contract: dict[str, Any]) -> str:
    return str(contract.get("desktop_version") or f"5.1.{int(contract['build_number'])}")


def _gate_receipt_for_prepare(
    *,
    args: argparse.Namespace,
    root: Path,
    work_root: Path,
    branch: str,
    target: str,
    contract: dict[str, Any],
) -> Path:
    tree = resolve_tree(root, target)
    upstream = resolve_commit(root, f"origin/{branch}")
    configured = getattr(args, "gate_receipt", None)
    if configured:
        path = Path(configured).resolve()
        receipt = release_receipt.load_gate_receipt(path)
        release_receipt.verify_gate_receipt(
            receipt,
            target_commit=target,
            target_tree=tree,
            product_version=str(contract["product_version"]),
            build_number=int(contract["build_number"]),
            desktop_version=_desktop_version(contract),
            branch=branch,
            upstream_commit=upstream,
            policy=PREPARE_GATES,
        )
        return path
    results = run_prepare_gates(root)
    return release_receipt.create_gate_receipt(
        root=work_root,
        target_commit=target,
        target_tree=tree,
        product_version=str(contract["product_version"]),
        build_number=int(contract["build_number"]),
        desktop_version=_desktop_version(contract),
        branch=branch,
        upstream_commit=upstream,
        policy=PREPARE_GATES,
        results=results,
        clean=True,
    )


def gate(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    work_root = Path(args.work_root).resolve()
    branch = str(getattr(args, "branch", "") or "") or current_branch(root)
    target = require_release_source(root=root, branch=branch, target=args.target)
    contract = load_contract(root)
    path = _gate_receipt_for_prepare(
        args=argparse.Namespace(gate_receipt=None),
        root=root,
        work_root=work_root,
        branch=branch,
        target=target,
        contract=contract,
    )
    return {**release_receipt.load_gate_receipt(path), "gate_path": str(path)}


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    work_root = Path(args.work_root).resolve()
    branch = str(getattr(args, "branch", "") or "") or current_branch(root)
    args.branch = branch
    target = (
        resolve_commit(root, args.target)
        if args.skip_gates
        else require_release_source(root=root, branch=branch, target=args.target)
    )
    contract = load_contract(root)
    base = _base_from_args(args)
    classification = classify_release(base, target, root=root)
    if getattr(args, "force_full", False) and classification.kind == "patch":
        classification = ReleaseClassification(
            kind="full",
            runtime_files=classification.runtime_files,
            triggers=(
                *classification.triggers,
                ReleaseTrigger(
                    "<installed-runtime>",
                    "operator forced a full transaction",
                ),
            ),
            ignored_version_surfaces=classification.ignored_version_surfaces,
        )
    validate_patch_pipeline(classification)
    gate_path = None
    if not args.skip_gates:
        gate_path = _gate_receipt_for_prepare(
            args=args,
            root=root,
            work_root=work_root,
            branch=branch,
            target=target,
            contract=contract,
        )
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
    if gate_path is not None:
        artifact_path = release_receipt.create_artifact_receipt(
            root=work_root,
            gate_receipt=gate_path,
            release_class=classification.kind,
            target_commit=target,
            base_commits=[base],
            product_version=str(contract["product_version"]),
            build_number=int(contract["build_number"]),
            desktop_version=_desktop_version(contract),
            assets=list(built.get("candidate_assets") or built["assets"]),
            candidate_root=candidate_root,
            acceptance_path=Path(built["acceptance_path"]),
            runtime_manifest_sha256=_sha256(root / "config/windows_runtime_manifest.json"),
            entrypoint_registry_sha256=_sha256(
                root / "installers/windows/runtime-entrypoints.json"
            ),
            build_evidence={
                "classification": _classification_evidence(classification),
                "build": built.get("build", {}),
            },
            publishable=True,
        )
        artifact = release_receipt.load_artifact_receipt(artifact_path)
        _write_latest(
            work_root, artifact_path, str(artifact["artifact_id"]), artifact=True
        )
        return {**artifact, "artifact_path": str(artifact_path)}
    state_path = release_receipt.create_attempt(
        root=work_root / "attempts",
        release_class=classification.kind,
        product_version=str(contract["product_version"]),
        build_number=int(contract["build_number"]),
        target_commit=target,
        base_commits=[base],
        host=args.host,
        assets=list(built.get("candidate_assets") or built["assets"]),
    )
    prepared = release_receipt.transition(
        state_path,
        expected="planned",
        target="prepared",
        evidence={
            "gates": [],
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


def _artifact_path(args: argparse.Namespace) -> Path:
    if getattr(args, "artifact", None):
        return Path(args.artifact).resolve()
    latest = json.loads(_latest_path(args.work_root).read_text(encoding="utf-8-sig"))
    raw = latest.get("artifact_path") or latest.get("state_path")
    if not raw:
        raise RuntimeError("latest release pointer has no artifact receipt")
    return Path(str(raw)).resolve()


def _prepared_evidence(attempt: dict[str, Any]) -> dict[str, Any]:
    for item in attempt.get("transitions", []):
        if item.get("stage") == "prepared":
            evidence = item.get("evidence")
            if isinstance(evidence, dict):
                return evidence
    raise RuntimeError("prepared release evidence is missing")


def _artifact_paths(attempt: dict[str, Any]) -> list[Path]:
    records = attempt.get("assets") or attempt.get("artifacts") or []
    return [Path(str(item["path"])).resolve() for item in records]


def _verify_artifact_source_contract(
    artifact: dict[str, Any], *, root: Path
) -> None:
    root = Path(root).resolve()
    contract = load_contract(root)
    expected = {
        "product_version": str(contract["product_version"]),
        "build_number": int(contract["build_number"]),
        "desktop_version": _desktop_version(contract),
        "runtime_manifest_sha256": _sha256(
            root / "config/windows_runtime_manifest.json"
        ),
        "entrypoint_registry_sha256": _sha256(
            root / "installers/windows/runtime-entrypoints.json"
        ),
    }
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise RuntimeError("release source contract changed since artifact creation")


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
        "local",
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
        job = Path(acceptance_path) / "hard-update-job.json"
    if not Path(job).is_file():
        raise RuntimeError("full local acceptance requires a prepared hard-update job")
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
    patch_release._prepare_remote_update_checkout(
        host=args.host,
        repo_root=args.repo_root,
        branch=args.branch,
        commit=str(attempt["target_commit"]),
    )
    release_id = str(attempt.get("artifact_id") or attempt.get("release_id"))
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
                for item in (attempt.get("assets") or attempt.get("artifacts") or [])
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


def _accept_artifact(
    args: argparse.Namespace, *, retry_of: str | None = None
) -> dict[str, Any]:
    artifact_path = _artifact_path(args)
    artifact = release_receipt.load_artifact_receipt(artifact_path)
    if list((artifact_path.parent / "revocations").glob("*.json")):
        raise RuntimeError("artifact is revoked")
    try:
        release_receipt.verify_artifact_receipt(
            artifact,
            commit=resolve_commit(args.root, "HEAD"),
            assets=_artifact_paths(artifact),
        )
        _verify_artifact_source_contract(artifact, root=Path(args.root))
    except (OSError, RuntimeError, ValueError) as exc:
        release_receipt.revoke_artifact(artifact_path, reason=str(exc))
        raise
    history = release_receipt.acceptance_attempts(artifact_path)
    if any(item.get("result") == "running" for item in history):
        raise RuntimeError("unresolved running acceptance attempt blocks mutation")
    attempt_path = release_receipt.create_acceptance_attempt(
        artifact_path,
        host=args.host,
        retry_of=retry_of,
    )
    acceptance_path = Path(str(artifact["acceptance_path"]))
    try:
        result = (
            run_local_acceptance(
                attempt=artifact,
                acceptance_path=acceptance_path,
                args=args,
            )
            if is_local_host(args.host)
            else run_remote_acceptance(
                attempt=artifact,
                acceptance_path=acceptance_path,
                args=args,
            )
        )
        if result.get("accepted") is not True:
            raise RuntimeError("Legion acceptance did not return accepted=true")
        return release_receipt.complete_acceptance_attempt(
            attempt_path,
            evidence=result,
        )
    except Exception as exc:
        release_receipt.fail_acceptance_attempt(
            attempt_path,
            failed_stage="legion_acceptance",
            error=str(exc),
            recovery={"runner_completed": False},
        )
        raise


def retry(args: argparse.Namespace) -> dict[str, Any]:
    artifact_path = _artifact_path(args)
    attempts = release_receipt.acceptance_attempts(artifact_path)
    failed = [
        item for item in attempts if item.get("result") in {"failed", "interrupted"}
    ]
    if not failed:
        raise RuntimeError("retry requires a prior failed or interrupted acceptance")
    return _accept_artifact(args, retry_of=str(failed[-1]["acceptance_id"]))


def accept(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "artifact", None):
        return _accept_artifact(args)
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


def status(
    attempt_path: Path | None = None, *, artifact_path: Path | None = None
) -> dict[str, Any]:
    if artifact_path is not None:
        path = Path(artifact_path).resolve()
        artifact = release_receipt.load_artifact_receipt(path)
        revocations = sorted((path.parent / "revocations").glob("*.json"))
        return {
            "artifact": artifact,
            "acceptance_attempts": release_receipt.acceptance_attempts(path),
            "revoked": bool(revocations),
            "revocations": [str(item) for item in revocations],
        }
    if attempt_path is None:
        raise RuntimeError("status requires --artifact or --attempt")
    return release_receipt.load_attempt(Path(attempt_path))


def _bind_public_receipt(
    *, attempt_path: Path, public: Path, feed_name: str
) -> tuple[Path, Path]:
    receipt = public / "release-receipt.json"
    if not receipt.is_file():
        receipt = release_receipt.write_public_receipt(attempt_path, receipt)
    else:
        public_receipt = json.loads(receipt.read_text(encoding="utf-8-sig"))
        attempt = release_receipt.load_attempt(attempt_path)
        if (
            public_receipt.get("schema") != release_receipt.PUBLIC_SCHEMA
            or public_receipt.get("release_id") != attempt.get("release_id")
            or public_receipt.get("target_commit") != attempt.get("target_commit")
        ):
            raise RuntimeError("existing public receipt differs from release attempt")
    feed_path = public / feed_name
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"publication feed is unreadable: {feed_name}") from exc
    feed["acceptance_receipt"] = {
        "name": receipt.name,
        "bytes": receipt.stat().st_size,
        "sha256": _sha256(receipt),
    }
    feed_path.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt, feed_path


def _bind_artifact_public_receipt(
    *, artifact_path: Path, acceptance_path: Path, public: Path, feed_name: str
) -> tuple[Path, Path]:
    receipt = public / "release-receipt.json"
    if not receipt.is_file():
        release_receipt.write_public_artifact_receipt(
            artifact_path, acceptance_path, receipt
        )
    else:
        public_receipt = json.loads(receipt.read_text(encoding="utf-8-sig"))
        artifact = release_receipt.load_artifact_receipt(artifact_path)
        acceptance = release_receipt.load_acceptance_attempt(acceptance_path)
        if (
            public_receipt.get("schema") != release_receipt.PUBLIC_ARTIFACT_SCHEMA
            or public_receipt.get("artifact_id") != artifact.get("artifact_id")
            or public_receipt.get("acceptance_id") != acceptance.get("acceptance_id")
            or public_receipt.get("target_commit") != artifact.get("target_commit")
        ):
            raise RuntimeError("existing public receipt differs from accepted artifact")
    feed_path = public / feed_name
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"publication feed is unreadable: {feed_name}") from exc
    feed["acceptance_receipt"] = {
        "name": receipt.name,
        "bytes": receipt.stat().st_size,
        "sha256": _sha256(receipt),
    }
    feed_path.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return receipt, feed_path


def publish_artifact_candidate(
    *,
    artifact_path: Path,
    acceptance_path: Path,
    artifact: dict[str, Any],
    public: Path,
    stage_callback,
    root: Path,
    resume_stage: str = "accepted",
) -> dict[str, Any]:
    if artifact["release_class"] == "patch":
        _bind_artifact_public_receipt(
            artifact_path=artifact_path,
            acceptance_path=acceptance_path,
            public=public,
            feed_name="les-update.json",
        )
        assets = [public / name for name in github_patch_release.PUBLISHED_ASSET_NAMES]
        return github_patch_release.publish_github_patch_release(
            f"v{artifact['product_version']}",
            assets,
            public / "release-notes.md",
            artifact_path=artifact_path,
            acceptance_path=acceptance_path,
            stage_callback=stage_callback,
            resume_stage=resume_stage,
        )
    latest = public / "latest.json"
    if not latest.is_file():
        latest.write_text(
            json.dumps(
                {
                    "schema": "les.update.v1",
                    "version": artifact["product_version"],
                    "build_number": artifact["build_number"],
                    "desktop_version": artifact["desktop_version"],
                    "target_commit": artifact["target_commit"],
                    "build_commit": artifact["target_commit"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    notes = public / "release-notes.md"
    if not notes.is_file():
        notes.write_text(
            f"## ЛЕС {artifact['product_version']}\n\nПринятый полный выпуск.\n",
            encoding="utf-8",
        )
    receipt, _feed = _bind_artifact_public_receipt(
        artifact_path=artifact_path,
        acceptance_path=acceptance_path,
        public=public,
        feed_name="latest.json",
    )
    return patch_release.publish(
        load_contract(root),
        extra_assets=[receipt],
        artifact_path=artifact_path,
        acceptance_path=acceptance_path,
        stage_callback=stage_callback,
        dist=public,
        resume_stage=resume_stage,
    )


def publish_patch_candidate(
    *,
    attempt_path: Path,
    attempt: dict[str, Any],
    public: Path,
    stage_callback,
    resume_stage: str = "accepted",
) -> dict[str, Any]:
    _bind_public_receipt(
        attempt_path=attempt_path, public=public, feed_name="les-update.json"
    )
    assets = [public / name for name in github_patch_release.PUBLISHED_ASSET_NAMES]
    return github_patch_release.publish_github_patch_release(
        f"v{attempt['product_version']}",
        assets,
        public / "release-notes.md",
        attempt_path=attempt_path,
        stage_callback=stage_callback,
        resume_stage=resume_stage,
    )


def publish_full_candidate(
    *,
    attempt_path: Path,
    attempt: dict[str, Any],
    public: Path,
    stage_callback,
    root: Path,
    resume_stage: str = "accepted",
) -> dict[str, Any]:
    contract = load_contract(root)
    latest = public / "latest.json"
    if not latest.is_file():
        latest.write_text(
            json.dumps(
                {
                    "schema": "les.update.v1",
                    "version": attempt["product_version"],
                    "build_number": attempt["build_number"],
                    "desktop_version": contract["desktop_version"],
                    "target_commit": attempt["target_commit"],
                    "build_commit": attempt["target_commit"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    notes = public / "release-notes.md"
    if not notes.is_file():
        notes.write_text(
            f"## ЛЕС {attempt['product_version']}\n\nПринятый полный выпуск.\n",
            encoding="utf-8",
        )
    receipt, _feed = _bind_public_receipt(
        attempt_path=attempt_path, public=public, feed_name="latest.json"
    )
    return patch_release.publish(
        contract,
        extra_assets=[receipt],
        attempt_path=attempt_path,
        stage_callback=stage_callback,
        dist=public,
        resume_stage=resume_stage,
    )


def verify_public_provenance(
    *, attempt: dict[str, Any], assets: Sequence[Path]
) -> dict[str, Any]:
    tag = f"v{attempt['product_version']}"
    repository = github_patch_release.REPOSITORY
    head_response = _run(
        ("gh", "api", f"repos/{repository}/git/ref/heads/main"),
        root=ROOT,
        capture=True,
    )
    tag_response = _run(
        ("gh", "api", f"repos/{repository}/git/ref/tags/{tag}"),
        root=ROOT,
        capture=True,
    )
    public_main = json.loads(head_response.stdout).get("object", {}).get("sha", "")
    public_tag = json.loads(tag_response.stdout).get("object", {}).get("sha", "")
    target = str(attempt["target_commit"])
    if public_main != target or public_tag != target:
        raise RuntimeError("critical immutable-release incident: public refs differ")
    expected = {Path(path).name: _sha256(Path(path)) for path in assets}
    with tempfile.TemporaryDirectory(prefix="les-release-postflight-") as temporary:
        _run(
            (
                "gh",
                "release",
                "download",
                tag,
                "--repo",
                repository,
                "--dir",
                temporary,
            ),
            root=ROOT,
        )
        downloaded = {
            path.name: _sha256(path)
            for path in Path(temporary).iterdir()
            if path.is_file()
        }
        if downloaded != expected:
            raise RuntimeError("critical immutable-release incident: public asset hashes differ")
        receipt = json.loads(
            (Path(temporary) / "release-receipt.json").read_text(encoding="utf-8-sig")
        )
        feed_name = "les-update.json" if attempt["release_class"] == "patch" else "latest.json"
        feed = json.loads(
            (Path(temporary) / feed_name).read_text(encoding="utf-8-sig")
        )
    feed_target = str(feed.get("target_commit") or feed.get("build_commit") or "")
    if receipt.get("target_commit") != target or feed_target != target:
        raise RuntimeError("critical immutable-release incident: public metadata differs")
    return {
        "ok": True,
        "target_commit": target,
        "public_main": public_main,
        "public_tag": public_tag,
        "asset_hashes": expected,
    }


def publish(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "artifact", None):
        artifact_path = _artifact_path(args)
        artifact = release_receipt.load_artifact_receipt(artifact_path)
        if list((artifact_path.parent / "revocations").glob("*.json")):
            raise RuntimeError("artifact is revoked")
        try:
            release_receipt.verify_artifact_receipt(
                artifact,
                commit=resolve_commit(args.root, "HEAD"),
                assets=_artifact_paths(artifact),
            )
            _verify_artifact_source_contract(artifact, root=Path(args.root))
        except (OSError, RuntimeError, ValueError) as exc:
            release_receipt.revoke_artifact(artifact_path, reason=str(exc))
            raise
        accepted = release_receipt.accepted_attempts(artifact_path)
        if not accepted:
            raise RuntimeError("successful acceptance required for publication")
        acceptance = accepted[-1]
        acceptance_path = (
            artifact_path.parent / "acceptance" / f"{acceptance['acceptance_id']}.json"
        )
        publication_path = release_receipt.create_publication(
            artifact_path, acceptance_path=acceptance_path
        )
        publication_state = release_receipt.load_publication(publication_path)
        current_stage = str(publication_state["stage"])
        if current_stage == "accepted" and "public_main_sync" not in publication_state.get(
            "checkpoints", {}
        ):
            public_main_sync = sync_public_main(
                root=Path(args.root), target=str(artifact["target_commit"])
            )
            publication_state = release_receipt.record_publication_checkpoint(
                publication_path,
                expected="accepted",
                name="public_main_sync",
                evidence=public_main_sync,
            )
        public = Path(str(artifact["candidate_root"])) / "public"
        expected_for_stage = {
            "draft_uploaded": "accepted",
            "draft_verified": "draft_uploaded",
            "published": "draft_verified",
        }

        def advance_artifact(stage: str, evidence: dict[str, Any]) -> None:
            release_receipt.transition_publication(
                publication_path,
                expected=expected_for_stage[stage],
                target=stage,
                evidence=evidence,
            )

        if current_stage == "published":
            asset_names = (
                github_patch_release.PUBLISHED_ASSET_NAMES
                if artifact["release_class"] == "patch"
                else (
                    "LES-Setup.exe",
                    "LES-Setup.exe.sha256",
                    "latest.json",
                    "release-receipt.json",
                )
            )
            publication = {
                "published": True,
                "assets": [str(public / name) for name in asset_names],
            }
        else:
            publication = publish_artifact_candidate(
                artifact_path=artifact_path,
                acceptance_path=acceptance_path,
                artifact=artifact,
                public=public,
                stage_callback=advance_artifact,
                root=Path(args.root),
                resume_stage=current_stage,
            )
        postflight = verify_public_provenance(
            attempt=artifact,
            assets=[Path(path) for path in publication["assets"]],
        )
        completed = release_receipt.transition_publication(
            publication_path,
            expected="published",
            target="postflight_verified",
            evidence=postflight,
        )
        return {**completed, "publication_path": str(publication_path)}
    state_path = _attempt_path(args)
    attempt = release_receipt.load_attempt(state_path)
    current_stage = str(attempt.get("stage") or "")
    if (
        current_stage
        not in {"accepted", "draft_uploaded", "draft_verified", "published"}
        or attempt.get("publishable") is not True
    ):
        raise RuntimeError("installed acceptance required before publication")
    release_receipt.verify_binding(
        attempt,
        commit=resolve_commit(args.root, "HEAD"),
        assets=_artifact_paths(attempt),
    )
    public_main_sync: dict[str, Any] | None = None
    if current_stage == "accepted":
        public_main_sync = sync_public_main(
            root=Path(args.root),
            target=str(attempt["target_commit"]),
        )
        attempt = release_receipt.record_checkpoint(
            state_path,
            expected="accepted",
            name="public_main_sync",
            evidence=public_main_sync,
        )
    prepared = _prepared_evidence(attempt)
    public = Path(str(prepared["candidate_root"])) / "public"

    expected_for_stage = {
        "draft_uploaded": "accepted",
        "draft_verified": "draft_uploaded",
        "published": "draft_verified",
    }

    def advance(stage: str, evidence: dict[str, Any]) -> None:
        release_receipt.transition(
            state_path,
            expected=expected_for_stage[stage],
            target=stage,
            evidence=evidence,
        )

    if current_stage == "published":
        asset_names = (
            github_patch_release.PUBLISHED_ASSET_NAMES
            if attempt["release_class"] == "patch"
            else (
                "LES-Setup.exe",
                "LES-Setup.exe.sha256",
                "latest.json",
                "release-receipt.json",
            )
        )
        publication = {
            "published": True,
            "assets": [str(public / name) for name in asset_names],
        }
    else:
        publication = (
            publish_patch_candidate(
                attempt_path=state_path,
                attempt=attempt,
                public=public,
                stage_callback=advance,
                resume_stage=current_stage,
            )
            if attempt["release_class"] == "patch"
            else publish_full_candidate(
                attempt_path=state_path,
                attempt=attempt,
                public=public,
                stage_callback=advance,
                root=Path(args.root),
                resume_stage=current_stage,
            )
        )
    assets = [Path(path) for path in publication["assets"]]
    postflight = verify_public_provenance(attempt=attempt, assets=assets)
    completed = release_receipt.transition(
        state_path,
        expected="published",
        target="postflight_verified",
        evidence=postflight,
    )
    return {**completed, "state_path": str(state_path)}


def run_release(args: argparse.Namespace) -> dict[str, Any]:
    if args.publish and args.skip_gates:
        raise RuntimeError("public release cannot skip prepare gates")
    prepared = prepare(args)
    if "artifact_path" in prepared:
        args.artifact = Path(prepared["artifact_path"])
    else:
        args.attempt = Path(prepared["state_path"])
    accepted = accept(args)
    if not args.publish:
        return accepted
    return publish(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(root=ROOT, work_root=DEFAULT_WORK_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    gate_cmd = sub.add_parser("gate")
    gate_cmd.add_argument("--root", type=Path, default=ROOT)
    gate_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    gate_cmd.add_argument("--branch", default="")
    gate_cmd.add_argument("--target", default="HEAD")
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--root", type=Path, default=ROOT)
    prepare_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    prepare_cmd.add_argument("--branch", default="")
    prepare_cmd.add_argument("--target", default="HEAD")
    prepare_cmd.add_argument("--base", default="")
    prepare_cmd.add_argument("--host", default="local")
    prepare_cmd.add_argument("--full-feed", type=Path)
    prepare_cmd.add_argument("--repo-root", default=r"C:\Users\Oleg\les_rag")
    prepare_cmd.add_argument("--smeta-baseline-archive", type=Path)
    prepare_cmd.add_argument("--gate-receipt", type=Path)
    prepare_cmd.add_argument("--force-full", action="store_true")
    prepare_cmd.add_argument("--skip-gates", action="store_true")
    accept_cmd = sub.add_parser("accept")
    accept_cmd.add_argument("--root", type=Path, default=ROOT)
    accept_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    accept_cmd.add_argument("--attempt", type=Path)
    accept_cmd.add_argument("--artifact", type=Path)
    accept_cmd.add_argument("--host", default="local")
    accept_cmd.add_argument("--repo-root", default=r"C:\Users\Oleg\les_rag")
    local = os.getenv("LOCALAPPDATA", "")
    accept_cmd.add_argument("--runtime", type=Path, default=Path(local) / "Programs" / "LES" / "runtime")
    accept_cmd.add_argument("--state", type=Path, default=Path(local) / "LES")
    accept_cmd.add_argument("--install", type=Path, default=Path(local) / "Programs" / "LES")
    accept_cmd.add_argument("--job", type=Path)
    retry_cmd = sub.add_parser("retry")
    retry_cmd.add_argument("--root", type=Path, default=ROOT)
    retry_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    retry_cmd.add_argument("--artifact", type=Path, required=True)
    retry_cmd.add_argument("--host", default="local")
    retry_cmd.add_argument("--repo-root", default=r"C:\Users\Oleg\les_rag")
    retry_cmd.add_argument("--runtime", type=Path, default=Path(local) / "Programs" / "LES" / "runtime")
    retry_cmd.add_argument("--state", type=Path, default=Path(local) / "LES")
    retry_cmd.add_argument("--install", type=Path, default=Path(local) / "Programs" / "LES")
    retry_cmd.add_argument("--job", type=Path)
    publish_cmd = sub.add_parser("publish")
    publish_cmd.add_argument("--root", type=Path, default=ROOT)
    publish_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    publish_cmd.add_argument("--attempt", type=Path)
    publish_cmd.add_argument("--artifact", type=Path)
    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--root", type=Path, default=ROOT)
    run_cmd.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
    run_cmd.add_argument("--branch", default="")
    run_cmd.add_argument("--target", default="HEAD")
    run_cmd.add_argument("--base", default="")
    run_cmd.add_argument("--host", default="local")
    run_cmd.add_argument("--full-feed", type=Path)
    run_cmd.add_argument("--repo-root", default=r"C:\Users\Oleg\les_rag")
    run_cmd.add_argument("--smeta-baseline-archive", type=Path)
    run_cmd.add_argument("--gate-receipt", type=Path)
    run_cmd.add_argument("--force-full", action="store_true")
    run_cmd.add_argument("--skip-gates", action="store_true")
    run_cmd.add_argument("--publish", action="store_true")
    run_cmd.add_argument("--attempt", type=Path)
    local = os.getenv("LOCALAPPDATA", "")
    run_cmd.add_argument("--runtime", type=Path, default=Path(local) / "Programs" / "LES" / "runtime")
    run_cmd.add_argument("--state", type=Path, default=Path(local) / "LES")
    run_cmd.add_argument("--install", type=Path, default=Path(local) / "Programs" / "LES")
    run_cmd.add_argument("--job", type=Path)
    status_cmd = sub.add_parser("status")
    status_group = status_cmd.add_mutually_exclusive_group(required=True)
    status_group.add_argument("--attempt", type=Path)
    status_group.add_argument("--artifact", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    if args.command == "gate":
        result = gate(args)
    elif args.command == "prepare":
        result = prepare(args)
    elif args.command == "accept":
        result = accept(args)
    elif args.command == "retry":
        result = retry(args)
    elif args.command == "publish":
        result = publish(args)
    elif args.command == "run":
        result = run_release(args)
    else:
        result = status(args.attempt, artifact_path=args.artifact)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Release orchestration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
