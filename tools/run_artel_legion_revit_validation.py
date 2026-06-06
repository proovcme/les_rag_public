"""Run ARTEL Revit validation on Legion and ingest the produced report."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMOTE_ROOT = r"C:\Users\Oleg\AppData\Local\Temp\artel-current-autorun"
DEFAULT_FAMILY_PATH = r"C:\Program Files\Autodesk\Revit 2025\Samples\rac_basic_sample_family.rfa"
DEFAULT_LOCAL_REPORT_DIR = ROOT / "local_private_archive" / "artel_validation_reports"
DEFAULT_PROXY_URL = "http://127.0.0.1:8050"
DEFAULT_ARTEL_URL = "http://127.0.0.1:5057"
DEFAULT_TASK_ID = "task_0241"
DEFAULT_LEGION_BACKEND_DLL = (
    r"C:\Users\Oleg\AppData\Local\Temp\artel-backend-persist"
    r"\backend\Agnostis.Api\bin\Release\net8.0\Agnostis.Api.dll"
)
DEFAULT_LEGION_BACKEND_DATA_DIR = r"C:\Users\Oleg\AppData\Local\Temp\artel-backend-persist\runtime-data"


class CommandError(RuntimeError):
    def __init__(self, command: list[str], result: subprocess.CompletedProcess[str]) -> None:
        self.command = command
        self.result = result
        super().__init__(f"Command failed with exit code {result.returncode}: {shlex.join(command)}")


def run_command(command: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise CommandError(command, result)
    return result


def parse_json_object(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("No JSON object found in command output.")


def ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def remote_script(root: str, script_name: str) -> str:
    return root.rstrip("\\/") + "\\" + script_name


def windows_path_for_scp(path: str) -> str:
    return path.replace("\\", "/")


def ssh_powershell(host: str, script: str) -> list[str]:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return ["ssh", host, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def ssh_powershell_foreground(host: str, script: str) -> list[str]:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return ["ssh", host, "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def diagnose_legion(host: str, remote_root: str, timeout: float) -> dict[str, Any]:
    script = f"& {ps_single_quote(remote_script(remote_root, 'diagnose-family-factory-revit-session.ps1'))}"
    result = run_command(ssh_powershell(host, script), timeout=timeout)
    return parse_json_object(result.stdout)


def revit_artel_url(args: argparse.Namespace) -> str:
    if args.use_legion_artel_backend:
        return args.legion_artel_backend_url
    return args.artel_url


def run_autorun(args: argparse.Namespace) -> dict[str, Any]:
    script_path = remote_script(args.remote_root, "run-family-factory-revit-autorun.ps1")
    parts = [
        "&",
        ps_single_quote(script_path),
        "-FamilyPath",
        ps_single_quote(args.family_path),
        "-RevitInstallDir",
        ps_single_quote(args.revit_install_dir),
        "-ArtelBaseUrl",
        ps_single_quote(revit_artel_url(args) if args.submit_to_artel else ""),
        "-TaskId",
        ps_single_quote(args.task_id if args.submit_to_artel else ""),
        "-ApiKey",
        ps_single_quote(args.artel_api_key),
        "-RequiredSharedParameters",
        ps_single_quote(args.required_shared_parameters),
        "-TimeoutSec",
        str(args.revit_timeout_sec),
    ]
    if args.skip_lock_screen_check:
        parts.append("-SkipLockScreenCheck")
    if args.keep_existing_reports:
        parts.append("-KeepExistingReports")
    script = " ".join(parts)
    result = run_command(ssh_powershell(args.ssh_host, script), timeout=args.revit_timeout_sec + 60)
    return parse_json_object(result.stdout)


def terminate_process(process: subprocess.Popen[str], *, timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


@contextmanager
def managed_process(command: list[str]) -> Iterator[subprocess.Popen[str]]:
    process = subprocess.Popen(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        yield process
    finally:
        terminate_process(process)


def start_legion_backend_command(args: argparse.Namespace) -> list[str]:
    app_dir = str(Path(args.legion_artel_backend_dll.replace("\\", "/")).parent).replace("/", "\\")
    script = "; ".join(
        [
            f"$env:ARTEL_DATA_DIR={ps_single_quote(args.legion_artel_backend_data_dir)}",
            f"$env:ASPNETCORE_URLS={ps_single_quote(args.legion_artel_backend_url)}",
            f"Set-Location {ps_single_quote(app_dir)}",
            f"dotnet {ps_single_quote(args.legion_artel_backend_dll)}",
        ]
    )
    return ssh_powershell_foreground(args.ssh_host, script)


def start_tunnel_command(args: argparse.Namespace) -> list[str]:
    return [
        "ssh",
        "-N",
        "-L",
        f"{args.legion_artel_local_port}:127.0.0.1:{args.legion_artel_remote_port}",
        args.ssh_host,
    ]


def legion_backend_pids(args: argparse.Namespace) -> set[int]:
    script = "; ".join(
        [
            "$ProgressPreference='SilentlyContinue'",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -eq 'dotnet.exe' -and "
                f"$_.CommandLine -like {ps_single_quote('*' + args.legion_artel_backend_dll + '*')} }} | "
                "ForEach-Object { $_.ProcessId }"
            ),
        ]
    )
    result = run_command(ssh_powershell(args.ssh_host, script), timeout=15)
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        text = line.strip()
        if text.isdigit():
            pids.add(int(text))
    return pids


def stop_legion_backend_pids(args: argparse.Namespace, pids: set[int]) -> None:
    if not pids:
        return
    pid_list = ",".join(str(pid) for pid in sorted(pids))
    script = "; ".join(
        [
            "$ProgressPreference='SilentlyContinue'",
            f"foreach ($processId in @({pid_list})) {{ "
            "Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }",
        ]
    )
    run_command(ssh_powershell(args.ssh_host, script), timeout=15)


def wait_for_artel_backend(artel_url: str, *, timeout: float, poll_sec: float = 0.5) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest = {"ok": False, "url": f"{artel_url.rstrip('/')}/health", "error": "timeout"}
    while time.monotonic() < deadline:
        latest = check_artel_backend(artel_url, timeout=min(2.0, poll_sec + 0.5))
        if latest["ok"]:
            return latest
        time.sleep(poll_sec)
    return latest


@contextmanager
def legion_artel_backend(args: argparse.Namespace, summary: dict[str, Any]) -> Iterator[None]:
    if not args.use_legion_artel_backend:
        yield
        return

    args.artel_url = f"http://127.0.0.1:{args.legion_artel_local_port}"
    summary["legion_artel_backend"] = {
        "remote_url": args.legion_artel_backend_url,
        "local_url": args.artel_url,
        "dll": args.legion_artel_backend_dll,
        "data_dir": args.legion_artel_backend_data_dir,
    }
    before_pids = legion_backend_pids(args)
    try:
        with managed_process(start_legion_backend_command(args)) as backend_process:
            time.sleep(0.5)
            if backend_process.poll() is not None:
                stdout, stderr = backend_process.communicate()
                raise RuntimeError(f"Legion ARTEL backend exited early: stdout={stdout}; stderr={stderr}")
            with managed_process(start_tunnel_command(args)) as tunnel_process:
                time.sleep(0.5)
                if tunnel_process.poll() is not None:
                    stdout, stderr = tunnel_process.communicate()
                    raise RuntimeError(f"ARTEL backend SSH tunnel exited early: stdout={stdout}; stderr={stderr}")
                health = wait_for_artel_backend(args.artel_url, timeout=args.artel_health_timeout_sec)
                summary["legion_artel_backend"]["health"] = health
                if not health["ok"]:
                    raise RuntimeError("Legion ARTEL backend did not become healthy: " + json.dumps(health))
                yield
    finally:
        after_pids = legion_backend_pids(args)
        stop_legion_backend_pids(args, after_pids - before_pids)


def check_artel_backend(artel_url: str, *, timeout: float) -> dict[str, Any]:
    url = f"{artel_url.rstrip('/')}/health"
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return {"ok": False, "url": url, "error": str(exc)}
    payload: dict[str, Any] = {}
    if body.strip():
        try:
            decoded = json.loads(body)
            if isinstance(decoded, dict):
                payload = decoded
        except json.JSONDecodeError:
            payload = {"raw": body[:500]}
    return {
        "ok": payload.get("status") == "ok",
        "url": url,
        "response": payload,
    }


def copy_report(host: str, remote_report: str, local_dir: Path) -> Path:
    local_dir.mkdir(parents=True, exist_ok=True)
    source = f"{host}:{windows_path_for_scp(remote_report)}"
    destination = local_dir / Path(remote_report.replace("\\", "/")).name
    run_command(["scp", source, str(destination)])
    return destination


def ingest_report(args: argparse.Namespace, report_path: Path) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(ROOT / "tools" / "ingest_artel_validation_report.py"),
        "--report",
        str(report_path),
        "--artel-url",
        args.artel_url,
        "--task-id",
        args.task_id,
        "--runtime-root",
        str(args.runtime_root),
        "--proxy-url",
        args.proxy_url,
        "--timeout-sec",
        str(args.search_timeout_sec),
        "--poll-sec",
        str(args.poll_sec),
        "--top-k",
        str(args.top_k),
    ]
    if args.artel_api_key:
        command.extend(["--artel-api-key", args.artel_api_key])
    if args.les_api_key:
        command.extend(["--api-key", args.les_api_key])
    if args.no_sync:
        command.append("--no-sync")
    if args.verify_search:
        command.append("--verify-search")
    return run_command(command, timeout=args.search_timeout_sec + 120)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose Legion, run ARTEL.Revit.FamilyFactory autorun validation "
            "from an interactive Revit desktop, copy the JSON report, and ingest it into LES."
        )
    )
    parser.add_argument("--ssh-host", default=os.getenv("ARTEL_LEGION_SSH_HOST", "legion"))
    parser.add_argument("--remote-root", default=os.getenv("ARTEL_LEGION_REMOTE_ROOT", DEFAULT_REMOTE_ROOT))
    parser.add_argument("--family-path", default=os.getenv("ARTEL_FAMILY_PATH", DEFAULT_FAMILY_PATH))
    parser.add_argument("--revit-install-dir", default=r"C:\Program Files\Autodesk\Revit 2025")
    parser.add_argument("--local-report-dir", type=Path, default=DEFAULT_LOCAL_REPORT_DIR)
    parser.add_argument("--artel-url", default=os.getenv("ARTEL_BASE_URL", DEFAULT_ARTEL_URL))
    parser.add_argument("--task-id", default=os.getenv("ARTEL_TASK_ID", DEFAULT_TASK_ID))
    parser.add_argument("--artel-api-key", default=os.getenv("ARTEL_API_KEY", ""))
    parser.add_argument("--runtime-root", type=Path, default=ROOT)
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL)
    parser.add_argument("--les-api-key", default=os.getenv("LES_ADMIN_KEY", ""))
    parser.add_argument("--required-shared-parameters", default="ADSK_Наименование")
    parser.add_argument("--diagnose-timeout-sec", type=float, default=30.0)
    parser.add_argument("--artel-health-timeout-sec", type=float, default=5.0)
    parser.add_argument("--revit-timeout-sec", type=int, default=420)
    parser.add_argument("--search-timeout-sec", type=float, default=120.0)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--submit-to-artel", action="store_true", help="Let the Revit add-in POST directly to ARTEL backend.")
    parser.add_argument("--use-legion-artel-backend", action="store_true", help="Start ARTEL backend on Legion and open a local SSH tunnel for ingest.")
    parser.add_argument("--legion-artel-backend-dll", default=DEFAULT_LEGION_BACKEND_DLL)
    parser.add_argument("--legion-artel-backend-data-dir", default=DEFAULT_LEGION_BACKEND_DATA_DIR)
    parser.add_argument("--legion-artel-remote-port", type=int, default=5057)
    parser.add_argument("--legion-artel-local-port", type=int, default=15057)
    parser.add_argument("--legion-artel-backend-url", default="http://127.0.0.1:5057")
    parser.add_argument("--skip-lock-screen-check", action="store_true", help="Pass through to the Revit autorun script.")
    parser.add_argument("--keep-existing-reports", action="store_true")
    parser.add_argument("--no-ingest", action="store_true", help="Copy the report only; do not POST it to ARTEL/LES.")
    parser.add_argument("--skip-artel-health-check", action="store_true")
    parser.add_argument("--backend-only-smoke", action="store_true", help="Check ARTEL backend startup/health without touching Revit.")
    parser.add_argument("--no-sync", action="store_true", help="Pass through to ingest script.")
    parser.add_argument("--verify-search", action="store_true", help="Verify report projection through LES search after sync.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary: dict[str, Any] = {
        "ssh_host": args.ssh_host,
        "remote_root": args.remote_root,
        "family_path": args.family_path,
    }
    try:
        if args.backend_only_smoke:
            with legion_artel_backend(args, summary):
                artel_health = check_artel_backend(args.artel_url, timeout=args.artel_health_timeout_sec)
                summary["artel_backend"] = artel_health
                summary["status"] = "ok" if artel_health["ok"] else "artel_backend_unavailable"
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 0 if artel_health["ok"] else 3

        diagnosis = diagnose_legion(args.ssh_host, args.remote_root, args.diagnose_timeout_sec)
        summary["diagnosis"] = {
            "status": diagnosis.get("status"),
            "lockScreen": diagnosis.get("lockScreen"),
            "revitExe": diagnosis.get("revitExe"),
            "artelAddin": diagnosis.get("artelAddin"),
            "reportDir": diagnosis.get("reportDir"),
        }
        if diagnosis.get("status") != "interactive" and not args.skip_lock_screen_check:
            summary["status"] = "locked"
            summary["message"] = "Legion desktop is not interactive; unlock Windows before Revit autorun."
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 2

        with legion_artel_backend(args, summary):
            if (args.submit_to_artel or not args.no_ingest) and not args.skip_artel_health_check:
                artel_health = check_artel_backend(args.artel_url, timeout=args.artel_health_timeout_sec)
                summary["artel_backend"] = artel_health
                if not artel_health["ok"]:
                    summary["status"] = "artel_backend_unavailable"
                    summary["message"] = "ARTEL backend is not healthy; start backend before Revit autorun/ingest."
                    print(json.dumps(summary, ensure_ascii=False, indent=2))
                    return 3

            autorun = run_autorun(args)
            summary["autorun"] = autorun
            report_path = str(autorun.get("validationReport") or "")
            if not report_path:
                summary["status"] = "no_report"
                summary["message"] = "Revit autorun finished without validationReport."
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 1

            local_report = copy_report(args.ssh_host, report_path, args.local_report_dir)
            summary["copied_report"] = str(local_report)

            if not args.no_ingest:
                ingest = ingest_report(args, local_report)
                summary["ingest_stdout"] = ingest.stdout
                summary["ingest_stderr"] = ingest.stderr

        summary["status"] = "ok"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except CommandError as exc:
        summary["status"] = "command_error"
        summary["command"] = exc.command
        summary["returncode"] = exc.result.returncode
        summary["stdout"] = exc.result.stdout
        summary["stderr"] = exc.result.stderr
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return exc.result.returncode or 1
    except Exception as exc:
        summary["status"] = "error"
        summary["message"] = str(exc)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
