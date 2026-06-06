"""Run a clean-room LES install smoke in a temporary copy of the repo."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORE_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".claude",
    "__pycache__",
    "node_modules",
    "data",
    "storage",
    "logs",
    "RAG_Content",
    "artifacts",
    "snapshots",
    "local_private_archive",
    "dist",
    ".env",
}


def ignore_copy(_dir: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in IGNORE_NAMES or name.endswith(".pyc") or name.endswith(".env") or name == ".DS_Store":
            ignored.add(name)
    return ignored


def run(command: list[str], cwd: Path, timeout: int) -> int:
    print("+", " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd, timeout=timeout, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean-room LES install smoke.")
    parser.add_argument("--profile", default="server-remote-model")
    parser.add_argument("--workdir", default=None, help="existing or new workdir for the smoke copy")
    parser.add_argument("--keep", action="store_true", help="keep temporary copy after the smoke")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--build-artifact", action="store_true")
    parser.add_argument("--artifact-profile", default="linux-docker")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    if args.workdir:
        base = Path(args.workdir).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        keep = True
    else:
        base = Path(tempfile.mkdtemp(prefix="les-clean-install-"))
        keep = args.keep
    target = base / "LES_v2_clean"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(ROOT, target, ignore=ignore_copy)

    try:
        if not args.skip_sync:
            code = run(["uv", "sync"], target, args.timeout)
            if code:
                return code
        code = run(["uv", "run", "lesctl", "doctor", "--profile", args.profile, "--json"], target, args.timeout)
        if code:
            return code
        code = run(
            ["uv", "run", "lesctl", "install", "--profile", args.profile, "--init-env", "--json"],
            target,
            args.timeout,
        )
        if code:
            return code
        if args.run_tests:
            code = run(
                [
                    "uv",
                    "run",
                    "pytest",
                    "-q",
                    "tests/test_install_les.py",
                    "tests/test_lesctl.py",
                    "tests/test_installers.py",
                ],
                target,
                args.timeout,
            )
            if code:
                return code
        if args.build_artifact:
            code = run(
                [
                    "uv",
                    "run",
                    "python",
                    "tools/build_release_artifacts.py",
                    "--profile",
                    args.artifact_profile,
                    "--name",
                    f"les-{args.artifact_profile}-clean-smoke",
                ],
                target,
                args.timeout,
            )
            if code:
                return code
        print(f"Clean install smoke OK: {target}")
        return 0
    finally:
        if not keep:
            shutil.rmtree(base, ignore_errors=True)
        else:
            print(f"Kept smoke workdir: {base}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
