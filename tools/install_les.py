"""Installation and preflight helper for the LES host runtime."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = (
    "data",
    "storage",
    "logs",
    "RAG_Content",
    "artifacts",
    "artifacts/backups",
    "data/mail_imap_checkpoints",
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _command_version(command: str, *args: str) -> str | None:
    executable = shutil.which(command)
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return executable
    text = (result.stdout or result.stderr).strip().splitlines()
    return text[0] if text else executable


def build_checks() -> list[Check]:
    checks = [
        Check(
            "platform",
            platform.system() == "Darwin",
            f"{platform.system()} {platform.machine()}",
            required=False,
        ),
        Check(
            "python",
            sys.version_info >= (3, 12),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
    ]

    uv_version = _command_version("uv", "--version")
    checks.append(Check("uv", uv_version is not None, uv_version or "not found"))

    qdrant = Path.home() / ".local" / "bin" / "qdrant"
    qdrant_version = str(qdrant) if qdrant.exists() else _command_version("qdrant", "--version")
    checks.append(
        Check(
            "qdrant",
            qdrant_version is not None,
            qdrant_version or "not found; LES_QDRANT_RUNTIME=docker can be used as fallback",
            required=False,
        )
    )

    node_version = _command_version("node", "--version")
    checks.append(
        Check(
            "node",
            node_version is not None,
            node_version or "not found; needed only for rebuilding frontend/cad_bim_viewer",
            required=False,
        )
    )
    return checks


def ensure_dirs() -> list[str]:
    created: list[str] = []
    for relative in REQUIRED_DIRS:
        path = ROOT / relative
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created.append(relative)
    return created


def init_env(force: bool = False) -> str:
    source = ROOT / "env.example"
    target = ROOT / ".env"
    if target.exists() and not force:
        return ".env exists"
    if not source.exists():
        raise FileNotFoundError("env.example not found")
    shutil.copyfile(source, target)
    return ".env created from env.example" if not force else ".env overwritten from env.example"


def run_uv_sync() -> int:
    result = subprocess.run(["uv", "sync"], cwd=ROOT, check=False)
    return result.returncode


def _print_human(checks: list[Check], actions: dict[str, object]) -> None:
    for check in checks:
        status = "OK" if check.ok else ("WARN" if not check.required else "FAIL")
        print(f"[{status}] {check.name}: {check.detail}")
    for name, value in actions.items():
        print(f"[ACTION] {name}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and check a local LES installation.")
    parser.add_argument("--check", action="store_true", help="run dependency and platform checks")
    parser.add_argument("--init-env", action="store_true", help="create .env from env.example if missing")
    parser.add_argument("--force-env", action="store_true", help="overwrite .env from env.example")
    parser.add_argument("--create-dirs", action="store_true", help="create local runtime directories")
    parser.add_argument("--sync", action="store_true", help="run uv sync")
    parser.add_argument("--all", action="store_true", help="create dirs, init env, run checks and uv sync")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    if args.all:
        args.check = args.init_env = args.create_dirs = args.sync = True

    if not any((args.check, args.init_env, args.force_env, args.create_dirs, args.sync)):
        args.check = True

    checks = build_checks() if args.check else []
    actions: dict[str, object] = {}

    if args.create_dirs:
        actions["created_dirs"] = ensure_dirs()
    if args.init_env or args.force_env:
        actions["env"] = init_env(force=args.force_env)
    if args.sync:
        actions["uv_sync_exit_code"] = run_uv_sync()

    if args.json:
        print(json.dumps({"checks": [asdict(item) for item in checks], "actions": actions}, ensure_ascii=False, indent=2))
    else:
        _print_human(checks, actions)

    failed = [check for check in checks if check.required and not check.ok]
    if failed:
        return 1
    if actions.get("uv_sync_exit_code", 0) != 0:
        return int(actions["uv_sync_exit_code"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
