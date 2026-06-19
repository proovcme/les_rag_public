"""Unified LES control facade."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tools import install_les, les_doctor, les_runtime_control


ROOT = Path(__file__).resolve().parents[1]
DOCKER_PROFILES = {"linux-docker", "windows-docker"}


def _compose_file(profile: str) -> Path:
    platform_dir = "windows" if profile == "windows-docker" else "linux"
    return ROOT / "installers" / platform_dir / "docker-compose.yml"


def _run(args: list[str]) -> int:
    return subprocess.run(args, cwd=ROOT, check=False).returncode


def _docker_compose(profile: str, action: str) -> int:
    base = ["docker", "compose", "-f", str(_compose_file(profile)), "--project-directory", str(ROOT)]
    if action == "start":
        return _run([*base, "up", "-d", "qdrant", "proxy", "ui"])
    if action == "stop":
        return _run([*base, "stop"])
    if action == "restart":
        code = _run([*base, "restart"])
        return code if code == 0 else _run([*base, "up", "-d", "qdrant", "proxy", "ui"])
    if action == "status":
        return _run([*base, "ps"])
    return 2


def _systemd_user(action: str) -> int:
    if action == "start":
        return _run(["systemctl", "--user", "start", "les-proxy", "les-ui"])
    if action == "stop":
        return _run(["systemctl", "--user", "stop", "les-ui", "les-proxy"])
    if action == "restart":
        return _run(["systemctl", "--user", "restart", "les-proxy", "les-ui"])
    if action == "status":
        return _run(["systemctl", "--user", "status", "les-proxy", "les-ui", "--no-pager"])
    return 2


def _profile_action(profile: str | None, action: str) -> int | None:
    if not profile or profile in {"mac-native", "server-remote-model"}:
        return None
    if profile in DOCKER_PROFILES:
        return _docker_compose(profile, action)
    if profile == "linux-systemd":
        return _systemd_user(action)
    if profile == "windows-lite":
        print("windows-lite uses remote/local services; use install.ps1 and browser UI.", file=sys.stderr)
        return 1
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LES boxed runtime control.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser(
        "doctor",
        help="одношаговый отчёт о здоровье рантайма (порты/RAM/диск/GPU/провайдеры/коллекции)",
    )
    doctor.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument(
        "--profile-check",
        action="store_true",
        help="вместо health-отчёта прогнать платформенные/профильные проверки установки",
    )

    install = sub.add_parser("install", help="prepare local directories, .env and dependencies")
    install.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    install.add_argument("--sync", action="store_true")
    install.add_argument("--init-env", action="store_true")
    install.add_argument("--force-env", action="store_true")
    install.add_argument("--json", action="store_true")

    init = sub.add_parser("init", help="initialize local runtime directories and .env")
    init.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    init.add_argument("--force-env", action="store_true")
    init.add_argument("--json", action="store_true")

    status = sub.add_parser("status", help="show LES service status")
    status.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)

    start = sub.add_parser("start", help="start LES core services")
    start.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    start.add_argument("--include-ui", action="store_true")
    start.add_argument("--no-indexer", action="store_true")
    start.add_argument("--memory-preflight", action="store_true")

    stop = sub.add_parser("stop", help="stop LES core services")
    stop.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    stop.add_argument("--include-ui", action="store_true")

    restart = sub.add_parser("restart", help="restart LES core services")
    restart.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    restart.add_argument("--include-ui", action="store_true")
    restart.add_argument("--no-indexer", action="store_true")

    smoke = sub.add_parser("smoke", help="run lightweight local service status smoke")
    smoke.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    smoke.add_argument("--include-ui", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        if args.profile_check:
            command = ["--check"]
            if args.profile:
                command.extend(["--profile", args.profile])
            if args.json:
                command.append("--json")
            return install_les.main(command)
        doctor_args = ["--json"] if args.json else []
        return les_doctor.main(doctor_args)
    if args.command == "install":
        command = ["--check", "--create-dirs"]
        if args.profile:
            command.extend(["--profile", args.profile])
        if args.sync:
            command.append("--sync")
        if args.init_env:
            command.append("--init-env")
        if args.force_env:
            command.append("--force-env")
        if args.json:
            command.append("--json")
        return install_les.main(command)
    if args.command == "init":
        command = ["--check", "--create-dirs", "--init-env"]
        if args.profile:
            command.extend(["--profile", args.profile])
        if args.force_env:
            command.append("--force-env")
        if args.json:
            command.append("--json")
        return install_les.main(command)
    if args.command == "status":
        profile_code = _profile_action(args.profile, "status")
        if profile_code is not None:
            return profile_code
        return les_runtime_control.main(["status"])
    if args.command == "start":
        profile_code = _profile_action(args.profile, "start")
        if profile_code is not None:
            return profile_code
        command = ["start-core"]
        if args.include_ui:
            command.append("--include-ui")
        if args.no_indexer:
            command.append("--no-indexer")
        if args.memory_preflight:
            command.append("--memory-preflight")
        return les_runtime_control.main(command)
    if args.command == "stop":
        profile_code = _profile_action(args.profile, "stop")
        if profile_code is not None:
            return profile_code
        command = ["stop-core"]
        if args.include_ui:
            command.append("--include-ui")
        return les_runtime_control.main(command)
    if args.command == "restart":
        profile_code = _profile_action(args.profile, "restart")
        if profile_code is not None:
            return profile_code
        command = ["restart-core"]
        if args.include_ui:
            command.append("--include-ui")
        if args.no_indexer:
            command.append("--no-indexer")
        return les_runtime_control.main(command)
    if args.command == "smoke":
        profile_code = _profile_action(args.profile, "status")
        if profile_code is not None:
            return profile_code
        return les_runtime_control.main(["status"])
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
