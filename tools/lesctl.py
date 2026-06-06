"""Unified LES control facade."""

from __future__ import annotations

import argparse
import sys

from tools import install_les, les_runtime_control


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LES boxed runtime control.")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="run platform/profile checks")
    doctor.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    doctor.add_argument("--json", action="store_true")

    install = sub.add_parser("install", help="prepare local directories, .env and dependencies")
    install.add_argument("--profile", choices=sorted(install_les.SUPPORTED_PROFILES), default=None)
    install.add_argument("--sync", action="store_true")
    install.add_argument("--init-env", action="store_true")
    install.add_argument("--force-env", action="store_true")
    install.add_argument("--json", action="store_true")

    sub.add_parser("status", help="show LES service status")

    start = sub.add_parser("start", help="start LES core services")
    start.add_argument("--include-ui", action="store_true")
    start.add_argument("--no-indexer", action="store_true")
    start.add_argument("--memory-preflight", action="store_true")

    stop = sub.add_parser("stop", help="stop LES core services")
    stop.add_argument("--include-ui", action="store_true")

    restart = sub.add_parser("restart", help="restart LES core services")
    restart.add_argument("--include-ui", action="store_true")
    restart.add_argument("--no-indexer", action="store_true")

    smoke = sub.add_parser("smoke", help="run lightweight local service status smoke")
    smoke.add_argument("--include-ui", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        command = ["--check"]
        if args.profile:
            command.extend(["--profile", args.profile])
        if args.json:
            command.append("--json")
        return install_les.main(command)
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
    if args.command == "status":
        return les_runtime_control.main(["status"])
    if args.command == "start":
        command = ["start-core"]
        if args.include_ui:
            command.append("--include-ui")
        if args.no_indexer:
            command.append("--no-indexer")
        if args.memory_preflight:
            command.append("--memory-preflight")
        return les_runtime_control.main(command)
    if args.command == "stop":
        command = ["stop-core"]
        if args.include_ui:
            command.append("--include-ui")
        return les_runtime_control.main(command)
    if args.command == "restart":
        command = ["restart-core"]
        if args.include_ui:
            command.append("--include-ui")
        if args.no_indexer:
            command.append("--no-indexer")
        return les_runtime_control.main(command)
    if args.command == "smoke":
        return les_runtime_control.main(["status"])
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
