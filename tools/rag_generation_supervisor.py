#!/usr/bin/env python3
"""Supervise one contract-clean RAG generation through build, gate and alias switch.

The launchd job restarts after transient failures.  The builder itself is
idempotent and checkpointed; the supervisor stops fail-closed after a bounded
number of failed launches instead of creating an infinite paid retry loop.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", required=True)
    parser.add_argument("--alias", default="les_rag")
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--contract-path", type=Path, required=True)
    parser.add_argument("--alias-contract-path", type=Path, required=True)
    parser.add_argument("--lexical-db", type=Path, required=True)
    parser.add_argument("--migration-report", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--progress-path", type=Path, required=True)
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--embed-url", default="http://127.0.0.1:8081")
    parser.add_argument("--embed-backend", default="")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--embedding-api-model", default="")
    parser.add_argument("--rag-chunk-unit", choices=("chars", "tokens"), default="")
    parser.add_argument("--archive-physical-alias-as", default="")
    parser.add_argument(
        "--create-destination",
        action="store_true",
        help="allow the reviewed generation job to create its missing sibling collection",
    )
    parser.add_argument("--max-failures", type=int, default=12)


def _worker_arguments(args: argparse.Namespace) -> list[str]:
    result = [
        "--src", args.src,
        "--dst", args.dst,
        "--alias", args.alias,
        "--source-db", str(args.source_db),
        "--contract-path", str(args.contract_path),
        "--alias-contract-path", str(args.alias_contract_path),
        "--lexical-db", str(args.lexical_db),
        "--migration-report", str(args.migration_report),
        "--readiness-report", str(args.readiness_report),
        "--progress-path", str(args.progress_path),
        "--state-path", str(args.state_path),
        "--qdrant-url", args.qdrant_url,
        "--embed-url", args.embed_url,
        "--max-failures", str(args.max_failures),
    ]
    for option, value in (
        ("--embed-backend", args.embed_backend),
        ("--embedding-model", args.embedding_model),
        ("--embedding-api-model", args.embedding_api_model),
        ("--rag-chunk-unit", args.rag_chunk_unit),
        ("--archive-physical-alias-as", args.archive_physical_alias_as),
    ):
        if value:
            result.extend((option, value))
    if args.create_destination:
        result.append("--create-destination")
    return result


def render_launchd_plist(
    *,
    label: str,
    python: Path,
    script: Path,
    worker_args: list[str],
    workdir: Path,
    log_path: Path,
) -> bytes:
    payload = {
        "Label": label,
        "ProgramArguments": [str(python), str(script), "run", *worker_args],
        "WorkingDirectory": str(workdir),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }
    return plistlib.dumps(payload, sort_keys=False)


def _run_stage(state: dict[str, Any], state_path: Path, stage: str, command: list[str]) -> None:
    state.update({"status": "running", "stage": stage, "updated_at": time.time()})
    _write_json_atomic(state_path, state)
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def run(args: argparse.Namespace) -> int:
    for name, value in (
        ("EMBED_BACKEND", args.embed_backend),
        ("EMBEDDING_MODEL", args.embedding_model),
        ("EMBED_MODEL", args.embedding_api_model),
        ("RAG_CHUNK_UNIT", args.rag_chunk_unit),
    ):
        if value:
            os.environ[name] = value
    state = _read_json(args.state_path)
    failures = int(state.get("failures") or 0)
    state.update(
        {
            "schema": "les.rag.generation-job.v1",
            "source_collection": args.src,
            "destination_collection": args.dst,
            "alias": args.alias,
            "pid": os.getpid(),
            "failures": failures,
        }
    )
    python = Path(sys.executable)
    try:
        build = [
                str(python),
                str(ROOT / "tools/build_rag_contract_sibling.py"),
                "--src", args.src,
                "--dst", args.dst,
                "--source-db", str(args.source_db),
                "--contract-path", str(args.contract_path),
                "--qdrant-url", args.qdrant_url,
                "--embed-url", args.embed_url,
                "--resume",
                "--report-path", str(args.migration_report),
                "--progress-path", str(args.progress_path),
            ]
        if args.create_destination:
            build.append("--create")
        _run_stage(
            state,
            args.state_path,
            "build",
            build,
        )
        _run_stage(
            state,
            args.state_path,
            "lexical_build",
            [
                str(python),
                str(ROOT / "tools/build_lexical_index.py"),
                "--qdrant-url", args.qdrant_url,
                "--collection", args.dst,
                "--db", str(args.lexical_db),
                "--rebuild",
            ],
        )
        _run_stage(
            state,
            args.state_path,
            "readiness",
            [
                str(python),
                str(ROOT / "tools/rag_rrf_readiness.py"),
                "--collection", args.dst,
                "--contract-path", str(args.contract_path),
                "--source-db", str(args.source_db),
                "--migration-report", str(args.migration_report),
                "--lexical-db", str(args.lexical_db),
                "--qdrant-url", args.qdrant_url,
                "--embed-url", args.embed_url,
                "--live-rrf",
                "--report-path", str(args.readiness_report),
            ],
        )
        activation = [
                str(python),
                str(ROOT / "tools/activate_qdrant_generation.py"),
                "--alias", args.alias,
                "--target", args.dst,
                "--readiness-report", str(args.readiness_report),
                "--qdrant-url", args.qdrant_url,
                "--contract-source", str(args.contract_path),
                "--contract-destination", str(args.alias_contract_path),
                "--lexical-db", str(args.lexical_db),
                "--lexical-source-collection", args.dst,
                "--job-state-path", str(args.state_path),
                "--drop-empty-alias-placeholder",
            ]
        if args.archive_physical_alias_as:
            activation.extend(
                ("--archive-physical-alias-as", args.archive_physical_alias_as)
            )
        _run_stage(
            state,
            args.state_path,
            "activation",
            activation,
        )
    except Exception as exc:  # noqa: BLE001 - subprocess preserves exact exit in the log
        failures += 1
        state.update(
            {
                "status": "blocked" if failures >= args.max_failures else "retrying",
                "failures": failures,
                "error": f"{type(exc).__name__}: {exc}",
                "updated_at": time.time(),
            }
        )
        _write_json_atomic(args.state_path, state)
        return 0 if failures >= args.max_failures else 1
    state.update(
        {
            "status": "activated",
            "stage": "complete",
            "failures": 0,
            "error": "",
            "updated_at": time.time(),
        }
    )
    _write_json_atomic(args.state_path, state)
    return 0


def install(args: argparse.Namespace) -> int:
    plist_path = Path.home() / "Library/LaunchAgents" / f"{args.label}.plist"
    args.log_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    if args.reset_failures:
        state = _read_json(args.state_path)
        state.update(
            {
                "schema": "les.rag.generation-job.v1",
                "status": "installed",
                "failures": 0,
                "error": "",
                "updated_at": time.time(),
            }
        )
        _write_json_atomic(args.state_path, state)
    project_python = ROOT / ".venv/bin/python"
    python = project_python if project_python.is_file() else Path(sys.executable).resolve()
    plist_path.write_bytes(
        render_launchd_plist(
            label=args.label,
            python=python,
            script=Path(__file__).resolve(),
            worker_args=_worker_arguments(args),
            workdir=ROOT,
            log_path=args.log_path,
        )
    )
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{args.label}"], check=False)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=True)
    print(
        json.dumps(
            {
                "status": "installed",
                "label": args.label,
                "plist": str(plist_path),
                "state": str(args.state_path),
                "progress": str(args.progress_path),
                "log": str(args.log_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    run_parser = sub.add_parser("run")
    _common_args(run_parser)
    install_parser = sub.add_parser("install-launchd")
    _common_args(install_parser)
    install_parser.add_argument("--label", default="me.ovc.les.rag-generation")
    install_parser.add_argument("--log-path", type=Path, required=True)
    install_parser.add_argument("--reset-failures", action="store_true")
    args = parser.parse_args()
    return run(args) if args.action == "run" else install(args)


if __name__ == "__main__":
    raise SystemExit(main())
