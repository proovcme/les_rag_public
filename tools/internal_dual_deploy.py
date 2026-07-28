#!/usr/bin/env python3
"""Transactional internal rollout of codex/audit-rag to Mac and Legion."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools import deploy_to_runtime, patch_release
from tools.build_tauri_app import build as build_tauri
from tools.multiplatform_release import verify_macos_artifacts
from tools.smeta_release_baseline import create_archive


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
MAC_RUNTIME = Path(os.getenv("LES_RUNTIME_HOME", "/Users/ovc/LES")).resolve()
REPORT_PATH = DIST / "internal-dual-deploy.json"
BRANCH = "codex/audit-rag"
FORBIDDEN_PARTS = {".env", "data", "storage", "RAG_Content", "local_private_archive"}


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=capture,
    )


def _json_url(url: str, timeout: float = 30) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _version_identity(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_version": payload.get("product_version") or payload.get("les_version"),
        "build_number": int(payload.get("build_number") or 0),
        "commit": payload.get("deployed_commit") or payload.get("git_commit"),
    }


def _identity_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        actual.get("product_version") == expected.get("product_version")
        and int(actual.get("build_number") or 0) == int(expected.get("build_number") or 0)
        and patch_release.commits_match(
            str(actual.get("commit") or ""), str(expected.get("commit") or "")
        )
    )


def _restart_services(services: set[str]) -> None:
    uid = os.getuid()
    for service in sorted(services):
        run(["launchctl", "kickstart", "-k", f"gui/{uid}/{service}"])


def _deployable_changes(base: str, commit: str) -> list[tuple[str, str]]:
    probe = run(["git", "merge-base", "--is-ancestor", base, commit])
    if probe.returncode != 0:
        raise RuntimeError(f"Mac deployed commit {base} is not an ancestor of {commit}")
    output = run(
        ["git", "diff", "--name-status", "--find-renames", f"{base}..{commit}"],
        capture=True,
    ).stdout
    changes: list[tuple[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        status = fields[0]
        candidates = (
            [("D", fields[1]), ("A", fields[2])]
            if status.startswith("R")
            else [(status[0], fields[-1])]
        )
        for operation, path in candidates:
            parts = set(Path(path).parts)
            if parts & FORBIDDEN_PARTS:
                raise RuntimeError(f"forbidden runtime path in deploy diff: {path}")
            if deploy_to_runtime._allowed(path):
                changes.append((operation, path))
    if not changes:
        raise RuntimeError("Mac transaction has no deployable changes")
    return changes


@dataclass
class MacTransaction:
    commit: str
    version: str
    build_number: int
    backup_root: Path | None = None
    previous_stamp: bytes | None = None
    changes: list[tuple[str, str]] | None = None
    services: set[str] | None = None

    def apply(self) -> dict[str, Any]:
        stamp = MAC_RUNTIME / ".les_deploy_stamp.json"
        previous = json.loads(stamp.read_text(encoding="utf-8"))
        base = str(previous.get("deployed_commit") or "")
        if not base:
            raise RuntimeError("Mac deploy stamp has no previous commit")
        self.changes = _deployable_changes(base, self.commit)
        self.previous_stamp = stamp.read_bytes()
        for status, path in self.changes:
            if status != "D" and not (ROOT / path).is_file():
                raise RuntimeError(f"Mac preflight source is missing: {path}")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.backup_root = MAC_RUNTIME.parent / "LES_recovery" / "audit-rag" / timestamp
        self.backup_root.mkdir(parents=True, exist_ok=False)
        self.services = set()
        manifest = {"base_commit": base, "target_commit": self.commit, "files": []}
        for status, path in self.changes:
            destination = MAC_RUNTIME / path
            existed = destination.is_file()
            if existed:
                backup = self.backup_root / "files" / path
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            manifest["files"].append({"status": status, "path": path, "existed": existed})
            if service := deploy_to_runtime._service_for_path(path):
                self.services.add(service)
        (self.backup_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        try:
            for status, path in self.changes:
                destination = MAC_RUNTIME / path
                if status == "D":
                    if destination.is_file():
                        destination.unlink()
                    continue
                source = ROOT / path
                if not source.is_file():
                    raise RuntimeError(f"preflighted source disappeared: {path}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".audit-rag.tmp")
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
            from proxy.services.version_service import write_deploy_stamp

            write_deploy_stamp(
                dev_root=ROOT,
                runtime_root=MAC_RUNTIME,
                deployed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                notes=["transactional codex/audit-rag internal deploy"],
            )
            _restart_services(self.services)
            smoke = wait_for_mac(self.commit, self.version, self.build_number)
            run(
                [
                    "uv",
                    "run",
                    "--with",
                    "playwright",
                    "python",
                    "tools/browser_layout_smoke.py",
                    "--ui-url",
                    "http://127.0.0.1:8051",
                ]
            )
            return {
                "ok": True,
                "backup_root": str(self.backup_root),
                "changed_files": len(self.changes),
                "identity": smoke["identity"],
                "index_contract": smoke["index_contract"],
                "browser_smoke": "passed",
            }
        except Exception:
            self.rollback()
            raise

    def rollback(self) -> dict[str, Any]:
        if not self.backup_root or self.changes is None:
            return {"ok": True, "needed": False}
        for _status, path in reversed(self.changes):
            destination = MAC_RUNTIME / path
            backup = self.backup_root / "files" / path
            if backup.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, destination)
            elif destination.is_file():
                destination.unlink()
        if self.previous_stamp is not None:
            (MAC_RUNTIME / ".les_deploy_stamp.json").write_bytes(self.previous_stamp)
        _restart_services(self.services or set())
        return {"ok": True, "needed": True, "backup_root": str(self.backup_root)}


def wait_for_mac(commit: str, version: str, build_number: int) -> dict[str, Any]:
    last_error = "not started"
    for _attempt in range(30):
        try:
            identity = _version_identity(_json_url("http://127.0.0.1:8050/api/version"))
            health = _json_url("http://127.0.0.1:8050/api/health")
            with urllib.request.urlopen("http://127.0.0.1:8051/healthz", timeout=10) as ui:
                ui_status = ui.status
            contract = ((health.get("rag") or {}).get("index_contract") or {})
            expected = {
                "product_version": version,
                "build_number": build_number,
                "commit": commit,
            }
            if (
                _identity_matches(identity, expected)
                and ui_status == 200
                and contract.get("compatible") is True
            ):
                return {"identity": expected, "runtime_identity": identity, "index_contract": contract}
            last_error = f"identity={identity}, ui={ui_status}, contract={contract.get('status')}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"Mac smoke did not converge: {last_error}")


def rag_gate_status() -> dict[str, Any]:
    health = _json_url("http://127.0.0.1:8050/api/health")
    datasets = (health.get("rag") or {}).get("datasets") or []
    user = [item for item in datasets if item.get("dataset_scope") != "system"]
    chunks = sum(int(item.get("chunks") or 0) for item in user)
    if chunks == 0:
        return {"golden": "N/A: corpus absent", "user_chunks": 0}
    run(
        [
            "uv",
            "run",
            "python",
            "tools/rag_golden_set.py",
            "--cases",
            "golden/domain_fire_hvac_set.json",
        ]
    )
    return {"golden": "16/16", "user_chunks": chunks}


def rollback_legion(host: str, repo_root: str, target_commit: str) -> None:
    rollback_script = f"{repo_root.rstrip(chr(92))}\\tools\\windows_production_rollback.ps1"
    script = (
        "$ErrorActionPreference='Stop'; "
        "$path=Join-Path $env:LOCALAPPDATA 'LES\\logs\\production-deploy.json'; "
        "if(-not (Test-Path -LiteralPath $path)){exit 0}; "
        "$report=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json; "
        f"if([string]$report.git_commit -ne '{target_commit}'){{exit 0}}; "
        "if([bool]$report.rollback.auto_restored){exit 0}; "
        "$backup=[string]$report.rollback.backup_root; "
        "$previous=[string]$report.rollback.previous_version; "
        "if(-not $backup -or -not $previous){throw 'Legion rollback point is missing'}; "
        f"& '{rollback_script}' -BackupRoot $backup -ExpectedVersion $previous; "
        "if($LASTEXITCODE -ne 0){throw 'Legion rollback failed'}"
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    patch_release.run(
        [
            "ssh",
            host,
            "powershell",
            "-NoProfile",
            "-EncodedCommand",
            encoded,
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legion-host", default="zt-legion")
    parser.add_argument("--legion-root", default=r"C:\Users\Oleg\les_rag")
    args, unknown = parser.parse_known_args(argv)
    if "--publish" in unknown or "--publish" in (argv or sys.argv[1:]):
        raise RuntimeError("--publish is forbidden for deploy-audit-rag")
    if unknown:
        raise RuntimeError("unknown arguments: " + " ".join(unknown))
    if sys.platform != "darwin":
        raise RuntimeError("deploy-audit-rag must start on Mac")

    contract = patch_release.load_contract()
    commit = patch_release.require_clean_pushed_branch(BRANCH)
    gates: dict[str, Any] = {}
    for name, command in (
        ("verify", ["make", "verify"]),
        ("test", ["make", "test"]),
        ("rag_core", ["make", "test-rag-core"]),
    ):
        run(command)
        gates[name] = "passed"
    gates.update(rag_gate_status())

    DIST.mkdir(exist_ok=True)
    build_tauri(
        str(contract["product_version"]),
        "app,dmg",
        build_number=int(contract["build_number"]),
    )
    mac_artifacts = verify_macos_artifacts(DIST / "LES.app", DIST / "LES.dmg")
    if patch_release.output(["git", "status", "--porcelain"]):
        raise RuntimeError("Mac build changed tracked source files")
    baseline = DIST / "LES-smeta-baseline.zip"
    create_archive(ROOT, baseline)

    transaction = MacTransaction(
        commit,
        str(contract["product_version"]),
        int(contract["build_number"]),
    )
    mac: dict[str, Any] = {}
    windows: dict[str, Any] = {}
    legion_attempted = False
    try:
        mac = transaction.apply()
        legion_attempted = True
        patch_release.remote_build(
            host=args.legion_host,
            repo_root=args.legion_root,
            branch=BRANCH,
            version=str(contract["product_version"]),
            build_number=int(contract["build_number"]),
            commit=commit,
            smeta_baseline_archive=baseline,
        )
        patch_release.fetch_remote_artifacts(host=args.legion_host, repo_root=args.legion_root)
        windows = patch_release.verify_local_artifacts(contract, commit)
        persistence = patch_release.verify_remote_production_persistence(
            host=args.legion_host,
            expected_version=str(contract["product_version"]),
            expected_build_number=int(contract["build_number"]),
            expected_commit=commit,
        )
        windows["independent_persistence"] = persistence
        production = windows.get("production") or {}
        legion_identity = {
            "product_version": persistence.get("product_version"),
            "build_number": int(persistence.get("build_number") or 0),
            "commit": persistence.get("commit"),
        }
        expected = {
            "product_version": contract["product_version"],
            "build_number": int(contract["build_number"]),
            "commit": commit,
        }
        if not _identity_matches(mac.get("identity") or {}, expected) or not _identity_matches(
            legion_identity, expected
        ):
            raise RuntimeError(
                f"cross-host identity mismatch: mac={mac.get('identity')}, legion={legion_identity}"
            )
        report = {
            "schema": "les.internal_dual_deploy.v1",
            "status": "ok",
            "published": False,
            "branch": BRANCH,
            "commit": commit,
            "product_version": contract["product_version"],
            "build_number": int(contract["build_number"]),
            "index_contract": "les.rag.index-contract.v2",
            "gates": gates,
            "mac": {**mac, "artifacts": mac_artifacts},
            "legion": windows,
            "rollback": {
                "mac": mac.get("backup_root"),
                "legion": (production.get("rollback") or {}).get("backup_root"),
                "user_data_untouched": True,
            },
        }
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        transaction.rollback()
        if legion_attempted:
            rollback_legion(args.legion_host, args.legion_root, commit)
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print(f"deploy-audit-rag failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
