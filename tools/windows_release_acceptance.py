#!/usr/bin/env python3
"""Installed Windows candidate acceptance: install, smoke, rollback, reinstall."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from tools import vps_patch, vps_patch_apply, windows_update_engine


PROXY = "http://127.0.0.1:8050"
UI = "http://127.0.0.1:8051"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    body: bytes | None = None,
    content_type: str = "application/json; charset=utf-8",
    timeout: float = 30,
) -> dict[str, Any]:
    data = body
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": content_type} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        decoded = json.loads(response.read().decode("utf-8-sig"))
    if not isinstance(decoded, dict):
        raise RuntimeError(f"acceptance endpoint returned non-object JSON: {url}")
    return decoded


def _ui_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{UI}/healthz", timeout=10) as response:  # noqa: S310
            return response.status == 200
    except OSError:
        return False


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return payload


def resolve_exact_installed_commit(
    value: Any,
    *,
    repo_root: Path | None = None,
) -> str:
    """Expand a legacy short deploy hash through the trusted source checkout."""

    commit = str(value or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{40}", commit):
        return commit
    if re.fullmatch(r"[0-9a-f]{7,39}", commit) is None:
        raise RuntimeError("installed deploy stamp has no exact commit")
    root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
    resolved = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{commit}^{{commit}}"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    exact = str(resolved.stdout or "").strip().lower()
    if (
        resolved.returncode != 0
        or re.fullmatch(r"[0-9a-f]{40}", exact) is None
        or not exact.startswith(commit)
    ):
        raise RuntimeError("installed deploy stamp has no exact commit")
    return exact


def snapshot_installed(runtime: Path, state: Path) -> dict[str, Any]:
    runtime = Path(runtime).resolve()
    state = Path(state).resolve()
    if not runtime.is_dir() or runtime == state or runtime in state.parents or state in runtime.parents:
        raise RuntimeError("installed runtime and persistent state boundary is invalid")
    contract = _read_json(runtime / "config" / "version.json", "installed version")
    stamp = _read_json(runtime / ".les_deploy_stamp.json", "installed deploy stamp")
    commit = resolve_exact_installed_commit(stamp.get("deployed_commit"))
    try:
        live_version = _request_json(f"{PROXY}/api/version", timeout=10)
        health = _request_json(f"{PROXY}/api/health", timeout=10)
        try:
            runtime_status = _request_json(f"{PROXY}/api/runtime/status", timeout=10)
        except (OSError, ValueError, RuntimeError, urllib.error.URLError):
            runtime_status = {}
        # Core liveness is the installed proxy identity plus the UI.  The aggregate
        # health status may be ``error`` solely because user-owned external Qdrant
        # is unavailable; that is tracked independently below.
        core = bool(live_version) and _ui_ready()
    except (OSError, ValueError, RuntimeError, urllib.error.URLError):
        live_version = {}
        health = {}
        runtime_status = {}
        core = False
    if live_version:
        live_commit = str(
            live_version.get("deployed_commit")
            or live_version.get("git_commit")
            or ""
        )
        if live_commit and not (
            commit.startswith(live_commit) or live_commit.startswith(commit)
        ):
            raise RuntimeError("live API identity differs from installed deploy stamp")
    rag = health.get("rag") if isinstance(health.get("rag"), dict) else {}
    provider = (
        runtime_status.get("proxy", {}).get("llm_provider", {})
        if isinstance(runtime_status.get("proxy"), dict)
        else {}
    )
    embedding = health.get("embedding") if isinstance(health.get("embedding"), dict) else {}
    return {
        "product_version": str(contract.get("product_version") or ""),
        "build_number": int(contract.get("build_number") or 0),
        "target_commit": commit,
        "capabilities": {
            "core": core,
            "qdrant": bool(core and health.get("backend") == "qdrant_llama" and rag.get("status") != "unavailable"),
            "answer": bool(core and provider.get("model")),
            "embedding": bool(
                core
                and (embedding.get("model") or embedding.get("embedding_model"))
            ),
        },
        "runtime_role": "installed_application",
        "state_role": "persistent_user_state",
    }


def require_capability_continuity(
    starting: dict[str, Any], current: dict[str, Any]
) -> None:
    before = starting.get("capabilities") or {}
    after = current.get("capabilities") or {}
    for role, available in sorted(before.items()):
        if available is True and after.get(role) is not True:
            raise RuntimeError(f"capability disappeared: {role}")


def _multipart_file(field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"les-acceptance-{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("ascii") + data + f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, f"multipart/form-data; boundary={boundary}"


def _native_rrf_fixture(marker: str) -> bytes:
    """Return one substantive paragraph that cannot be filtered as a tiny chunk."""
    text = (
        f"{marker}. Это контрольный документ установленного ЛЕС для проверки поиска. "
        "Он намеренно содержит достаточно связного текста, чтобы штатный индексатор создал "
        "evidence-чанк, а не отбросил короткую диагностическую строку как шум. Проверка обязана "
        "найти именно этот уникальный маркер через плотный и разреженный каналы Qdrant, объединить "
        "результаты native RRF и вернуть источник из временного датасета."
    )
    return text.encode("utf-8")


def _native_rrf_cleanup_url(dataset_id: str) -> str:
    encoded = urllib.parse.quote(str(dataset_id), safe="")
    return (
        f"{PROXY}/api/rag/datasets/{encoded}"
        "?recovery_policy=release_acceptance_ephemeral"
    )


def native_rrf_smoke(*, timeout: float = 180) -> dict[str, Any]:
    marker = f"les acceptance native rrf {uuid.uuid4().hex}"
    name = f"LES acceptance {uuid.uuid4().hex}"
    created = _request_json(
        f"{PROXY}/api/rag/datasets?name={urllib.parse.quote(name)}",
        method="POST",
    )
    dataset_id = str(created.get("id") or "")
    if not dataset_id:
        raise RuntimeError("acceptance dataset was not created")
    cleanup_error = ""
    try:
        body, content_type = _multipart_file(
            "file",
            "release-acceptance.txt",
            _native_rrf_fixture(marker),
        )
        uploaded = _request_json(
            f"{PROXY}/api/rag/upload/{dataset_id}",
            method="POST",
            body=body,
            content_type=content_type,
            timeout=60,
        )
        if not uploaded.get("doc_id"):
            raise RuntimeError("acceptance upload returned no document identity")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            documents = _request_json(
                f"{PROXY}/api/rag/documents?dataset_id={dataset_id}&limit=10",
                timeout=30,
            ).get("documents") or []
            if any(item.get("status") == "ERROR" for item in documents):
                raise RuntimeError("acceptance document indexing failed")
            if any(item.get("status") == "INDEXED" for item in documents):
                break
            time.sleep(0.75)
        else:
            raise RuntimeError("acceptance document was not indexed before timeout")
        result = _request_json(
            f"{PROXY}/api/rag/retrieve-debug",
            method="POST",
            payload={"question": marker, "dataset_ids": [dataset_id], "top_k": 3},
            timeout=timeout,
        )
        trace = result.get("retrieval_trace") or {}
        channels = trace.get("retrieval_channels") or []
        if (
            not result.get("chunks")
            or "rrf" not in str(trace.get("fusion") or "").lower()
            or "dense" not in channels
            or "qdrant_sparse" not in channels
        ):
            raise RuntimeError("installed native RRF acceptance failed")
        return {
            "ok": True,
            "fusion": trace.get("fusion"),
            "channels": channels,
            "chunks": len(result["chunks"]),
        }
    finally:
        try:
            _request_json(
                _native_rrf_cleanup_url(dataset_id), method="DELETE", timeout=30
            )
        except Exception as exc:  # noqa: BLE001
            cleanup_error = str(exc)
        if cleanup_error:
            raise RuntimeError(f"acceptance dataset cleanup failed: {cleanup_error}")


def installed_smoke(
    *,
    runtime: Path,
    state: Path,
    expected: dict[str, Any],
    starting: dict[str, Any],
) -> dict[str, Any]:
    current = snapshot_installed(runtime, state)
    for key in ("product_version", "build_number", "target_commit"):
        if current.get(key) != expected.get(key):
            raise RuntimeError(f"installed acceptance identity mismatch: {key}")
    if current.get("capabilities", {}).get("core") is not True:
        raise RuntimeError("installed LES core is not healthy")
    require_capability_continuity(starting, current)
    rrf = (
        native_rrf_smoke()
        if starting.get("capabilities", {}).get("qdrant") is True
        else {"status": "N/A: Qdrant unavailable before update"}
    )
    return {"ok": True, "identity": current, "capabilities": current["capabilities"], "rrf": rrf}


def install_patch(*, package_dir: Path, runtime: Path, state: Path) -> dict[str, Any]:
    launched = vps_patch.apply_local(output=package_dir, runtime=runtime, state=state)
    status = vps_patch.wait_local_update(Path(launched["status"]))
    if status.get("state") != "ready":
        raise RuntimeError(f"installed patch failed: {status.get('error') or status.get('stage')}")
    return status


def rollback_patch(
    *, runtime: Path, state: Path, installed: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return vps_patch_apply.rollback_accepted_patch(
        runtime=runtime,
        state=state,
        backup_root=Path(str(installed["backup_root"])),
        expected_target_commit=str(expected["target_commit"]),
    )


def install_full(*, job_path: Path) -> dict[str, Any]:
    job = _read_json(job_path, "hard-update job")
    if windows_update_engine.apply_hard_job(job_path) != 0:
        raise RuntimeError("installed full candidate failed")
    status = _read_json(Path(str(job["status_path"])), "hard-update status")
    if status.get("state") != "ready":
        raise RuntimeError("installed full candidate is not ready")
    return status


def rollback_full(
    *, install: Path, state: Path, installed: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return windows_update_engine.rollback_accepted_hard_update(
        install=install,
        state=state,
        recovery_root=Path(str(installed["recovery_root"])),
        expected_target_commit=str(expected["target_commit"]),
    )


def accept_patch(
    *, package_dir: Path, runtime: Path, state: Path, expected: dict[str, Any]
) -> dict[str, Any]:
    starting = snapshot_installed(runtime, state)
    first = install_patch(package_dir=package_dir, runtime=runtime, state=state)
    try:
        first_smoke = installed_smoke(
            runtime=runtime, state=state, expected=expected, starting=starting
        )
    except Exception:
        rollback_patch(runtime=runtime, state=state, installed=first, expected=expected)
        raise
    rollback = rollback_patch(
        runtime=runtime, state=state, installed=first, expected=expected
    )
    restored_smoke = installed_smoke(
        runtime=runtime, state=state, expected=starting, starting=starting
    )
    second = install_patch(package_dir=package_dir, runtime=runtime, state=state)
    final_smoke = installed_smoke(
        runtime=runtime, state=state, expected=expected, starting=starting
    )
    return {
        "accepted": True,
        "release_class": "patch",
        "starting_identity": starting,
        "first_install": first,
        "first_smoke": first_smoke,
        "rollback": rollback,
        "restored_smoke": restored_smoke,
        "second_install": second,
        "final_smoke": final_smoke,
        "final_identity": dict(expected),
    }


def accept_full(
    *, job_path: Path, install: Path, state: Path, expected: dict[str, Any]
) -> dict[str, Any]:
    runtime = windows_update_engine.runtime_root(install)
    starting = snapshot_installed(runtime, state)
    first = install_full(job_path=job_path)
    candidate_runtime = windows_update_engine.runtime_root(install)
    try:
        first_smoke = installed_smoke(
            runtime=candidate_runtime, state=state, expected=expected, starting=starting
        )
    except Exception:
        rollback_full(install=install, state=state, installed=first, expected=expected)
        raise
    rollback = rollback_full(
        install=install, state=state, installed=first, expected=expected
    )
    restored_smoke = installed_smoke(
        runtime=windows_update_engine.runtime_root(install),
        state=state,
        expected=starting,
        starting=starting,
    )
    second = install_full(job_path=job_path)
    final_smoke = installed_smoke(
        runtime=windows_update_engine.runtime_root(install),
        state=state,
        expected=expected,
        starting=starting,
    )
    return {
        "accepted": True,
        "release_class": "full",
        "starting_identity": starting,
        "first_install": first,
        "first_smoke": first_smoke,
        "rollback": rollback,
        "restored_smoke": restored_smoke,
        "second_install": second,
        "final_smoke": final_smoke,
        "final_identity": dict(expected),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--runtime", type=Path, required=True)
    snapshot.add_argument("--state", type=Path, required=True)
    for name in ("patch", "full"):
        command = sub.add_parser(name)
        command.add_argument("--state", type=Path, required=True)
        command.add_argument("--expected", type=Path, required=True)
        if name == "patch":
            command.add_argument("--package-dir", type=Path, required=True)
            command.add_argument("--runtime", type=Path, required=True)
        else:
            command.add_argument("--job", type=Path, required=True)
            command.add_argument("--install", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        result = snapshot_installed(args.runtime, args.state)
    else:
        expected = _read_json(args.expected, "expected release identity")
        result = (
            accept_patch(
                package_dir=args.package_dir,
                runtime=args.runtime,
                state=args.state,
                expected=expected,
            )
            if args.command == "patch"
            else accept_full(
                job_path=args.job,
                install=args.install,
                state=args.state,
                expected=expected,
            )
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Windows release acceptance failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
