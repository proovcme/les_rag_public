#!/usr/bin/env python3
"""Console-free LES Windows runtime lifecycle implemented with Python stdlib."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import subprocess
import time
import tracemalloc
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
PROCESS_CONTRACT = "direct_python_no_console_v2"
MAX_ENV_BYTES = 1024 * 1024
_DIAGNOSTICS_PATH = os.getenv("LES_RUNTIME_DIAGNOSTICS_PATH", "").strip()
if _DIAGNOSTICS_PATH:
    tracemalloc.start(10)


def _self_working_set() -> int:
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.windll.kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    )
    return int(counters.WorkingSetSize) if ok else 0


def _diagnostic(stage: str, **values: Any) -> None:
    if not _DIAGNOSTICS_PATH:
        return
    current, peak = tracemalloc.get_traced_memory()
    payload = {
        "at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "pid": os.getpid(),
        "working_set": _self_working_set(),
        "python_allocated": current,
        "python_peak": peak,
        **values,
    }
    path = Path(_DIAGNOSTICS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _flags() -> int:
    return (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0


def _dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    size = path.stat().st_size
    if size > MAX_ENV_BYTES:
        raise RuntimeError(
            f"LES_ENV_OVERSIZED: {path} is {size} bytes; "
            "run tools/windows_env_doctor.py before starting LES"
        )
    for raw in path.read_text(encoding="utf-8-sig", errors="strict").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key.replace("_", "").isalnum():
            values[key] = value.strip().strip('"').strip("'")
    return values


def runtime_environment(
    runtime: Path,
    state: Path,
    *,
    proxy_port: int = 8050,
    ui_port: int = 8051,
) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(_dotenv(state / ".env"))
    provider = environment.get("LES_LLM_PROVIDER", "").strip() or "ollama"
    model_key = {
        "ollama": "OLLAMA_MODEL",
        "openrouter": "OPENROUTER_MODEL",
        "openai": "OPENAI_MODEL",
        "openai-compatible": "OPENAI_MODEL",
        "lemonade": "LEMONADE_MODEL",
    }.get(provider, "MLX_MODEL")
    model = environment.get(model_key, "").strip()
    if not model and provider == "ollama":
        model = "qwen3.5:9b"
    environment.update(
        {
            "LES_WINDOWS_STATE_ROOT": str(state),
            "LES_ENV_PATH": str(state / ".env"),
            "UV_PROJECT_ENVIRONMENT": str(state / ".venv"),
            # env.example contains Mac developer defaults. Installed Windows
            # identity must always resolve from the actual immutable runtime,
            # never from persisted cross-platform path hints.
            "LES_REPO_ROOT": str(runtime),
            "LES_RUNTIME_HOME": str(runtime),
            "LES_LLM_PROVIDER": provider,
            "LLM_MODEL": model,
            "QDRANT_URL": "http://127.0.0.1:6333",
            "PROXY_URL": f"http://127.0.0.1:{proxy_port}",
            "SOVUSHKA_UI_PORT": str(ui_port),
            "CHAT_VALIDATION_ENABLED": "false",
            "RAG_OCR_ENABLED": "false",
            "SPECKLE_ENABLED": "false",
            "CORS_ALLOWED_ORIGINS": (
                f"http://127.0.0.1:{proxy_port},http://127.0.0.1:{ui_port},"
                f"http://localhost:{proxy_port},http://localhost:{ui_port}"
            ),
        }
    )
    if provider == "ollama":
        ollama = environment.get("OLLAMA_BASE_URL", "").strip() or "http://127.0.0.1:11434"
        environment.update(
            {
                "OLLAMA_BASE_URL": ollama,
                "OLLAMA_MODEL": model,
                "MLX_URL": ollama,
                "EMBED_URL_PARSE": ollama,
                "EMBED_MODEL": environment.get("EMBED_MODEL", "").strip()
                or "bge-m3:latest",
                "EMBEDDING_MODEL": environment.get("EMBEDDING_MODEL", "").strip()
                or "bge-m3",
                "EMBED_BACKEND": "ollama",
                "RAG_VECTOR_SIZE": "1024",
                "RERANKER_ENABLED": "true",
                "RERANKER_BACKEND": "sentence_transformers",
                "RERANK_MODEL": environment.get("RERANK_MODEL", "").strip()
                or "BAAI/bge-reranker-v2-m3",
                # Windows runs the cross-encoder locally on CPU. Keep the
                # native RRF pool broad, but bound the expensive second stage.
                "RAG_CHAT_RERANK_CANDIDATE_K": environment.get(
                    "RAG_CHAT_RERANK_CANDIDATE_K", ""
                ).strip()
                or "16",
                "RERANK_MAX_TEXT_CHARS": environment.get(
                    "RERANK_MAX_TEXT_CHARS", ""
                ).strip()
                or "1200",
            }
        )
    elif provider == "openrouter":
        environment["OPENROUTER_BASE_URL"] = (
            environment.get("OPENROUTER_BASE_URL", "").strip()
            or "https://openrouter.ai/api/v1"
        )
        environment["OPENROUTER_MODEL"] = model
    elif provider in {"openai", "openai-compatible"}:
        environment["OPENAI_BASE_URL"] = (
            environment.get("OPENAI_BASE_URL", "").strip()
            or (
                "https://api.openai.com/v1"
                if provider == "openai"
                else "http://127.0.0.1:8000/v1"
            )
        )
        environment["OPENAI_MODEL"] = model
    return environment


def _python(state: Path) -> Path:
    for name in ("pythonw.exe", "python.exe"):
        candidate = state / ".venv" / "Scripts" / name
        if candidate.is_file():
            return candidate
    raise RuntimeError("persistent LES Python environment is missing")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def _process_name(pid: int) -> str:
    completed = subprocess.run(
        ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    text = completed.stdout.decode("utf-8", errors="replace").strip()
    if not text or text.startswith("INFO:"):
        return ""
    try:
        return next(csv.reader([text]))[0].casefold()
    except (csv.Error, IndexError):
        return ""


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    name = _process_name(pid)
    if name not in {"python.exe", "pythonw.exe"}:
        return
    for command in (
        ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
        ["tskill.exe", str(pid)],
    ):
        subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if not _process_name(pid):
                return
            time.sleep(0.1)
    raise RuntimeError(f"confirmed LES process {pid} could not be terminated")


def _listening_pids(ports: set[int]) -> dict[int, int]:
    completed = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    result: dict[int, int] = {}
    for raw in completed.stdout.decode("ascii", errors="ignore").splitlines():
        fields = raw.split()
        if len(fields) < 5 or fields[0].casefold() != "tcp" or fields[-2].upper() != "LISTENING":
            continue
        try:
            port = int(fields[1].rsplit(":", 1)[-1])
            pid = int(fields[-1])
        except ValueError:
            continue
        if port in ports and pid > 0:
            result[port] = pid
    return result


def _live_runtime_matches(runtime: Path) -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8050/api/version", timeout=5) as response:  # noqa: S310
            version = json.load(response)
        with urllib.request.urlopen("http://127.0.0.1:8051/healthz", timeout=5) as response:  # noqa: S310
            ui = json.load(response)
        reported = Path(str(version.get("runtime_path") or "")).resolve()
    except (OSError, ValueError, TypeError):
        return False
    return (
        str(reported).casefold() == str(Path(runtime).resolve()).casefold()
        and ui.get("status") == "ok"
        and ui.get("service") == "sovushka"
    )


def _stop_confirmed_live_runtime(runtime: Path, ports: set[int]) -> list[int]:
    listeners = _listening_pids(ports)
    if not listeners or not _live_runtime_matches(runtime):
        return []
    if set(listeners) != ports:
        raise RuntimeError("LES runtime identity is confirmed but not every runtime port has an owner")
    pids = sorted(set(listeners.values()))
    if any(_process_name(pid) not in {"python.exe", "pythonw.exe"} for pid in pids):
        raise RuntimeError("LES runtime ports are not owned exclusively by Python processes")
    for pid in pids:
        _terminate_pid(pid)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if all(_port_free(port) for port in ports):
            return pids
        time.sleep(0.25)
    raise RuntimeError("confirmed LES runtime processes did not release their ports")


def stop(
    state: Path,
    *,
    runtime: Path | None = None,
    proxy_port: int = 8050,
    ui_port: int = 8051,
) -> dict[str, Any]:
    state_path = state / "logs" / "windows-light-state.json"
    ports = {proxy_port, ui_port}
    stopped: list[int] = (
        _stop_confirmed_live_runtime(runtime, ports) if runtime is not None else []
    )
    if state_path.is_file():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            payload = {}
        for key in ("proxy_pid", "ui_pid", "lemonade_host_pid"):
            pid = int(payload.get(key) or 0)
            if pid > 0:
                _terminate_pid(pid)
                if pid not in stopped:
                    stopped.append(pid)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not all(_port_free(port) for port in ports):
        time.sleep(0.25)
    if not all(_port_free(port) for port in ports):
        raise RuntimeError("LES runtime stop completed but runtime ports remain occupied")
    return {"status": "stopped", "pids": stopped}


def _spawn(
    python: Path,
    arguments: list[str],
    *,
    runtime: Path,
    environment: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> subprocess.Popen[bytes]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout = stdout_path.open("ab", buffering=0)
    stderr = stderr_path.open("ab", buffering=0)
    try:
        return subprocess.Popen(
            [str(python), *arguments],
            cwd=str(runtime),
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            creationflags=_flags(),
        )
    finally:
        stdout.close()
        stderr.close()


def _redacted_tail(path: Path, *, limit: int = 2000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""
    return re.sub(
        r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)[^\s,;]+",
        r"\1\2<redacted>",
        text,
    ).strip()


def _wait_process_url(
    process: subprocess.Popen[bytes],
    url: str,
    timeout: int,
    *,
    label: str,
    stderr_path: Path,
) -> None:
    deadline = time.monotonic() + timeout
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        code = process.poll()
        if code is not None:
            detail = _redacted_tail(stderr_path)
            raise RuntimeError(
                f"{label} exited before readiness (code={code}): "
                f"{detail or 'no stderr output'}"
            )
        try:
            with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310
                if response.status == 200:
                    return
        except Exception:
            pass
        if attempts == 1 or attempts % 10 == 0:
            _diagnostic("wait_url", url=url, attempts=attempts)
        time.sleep(0.5)
    detail = _redacted_tail(stderr_path)
    raise RuntimeError(
        f"{label} remained alive but did not answer {url} within {timeout}s: "
        f"{detail or 'no stderr output'}"
    )


def start(
    runtime: Path,
    state: Path,
    *,
    proxy_port: int = 8050,
    ui_port: int = 8051,
) -> dict[str, Any]:
    _diagnostic("start_enter")
    stop(state, runtime=runtime, proxy_port=proxy_port, ui_port=ui_port)
    _diagnostic("after_stop")
    if not _port_free(proxy_port) or not _port_free(ui_port):
        raise RuntimeError("LES runtime ports are occupied by an unowned process")
    python = _python(state)
    environment = runtime_environment(
        runtime,
        state,
        proxy_port=proxy_port,
        ui_port=ui_port,
    )
    _diagnostic("after_environment", environment_keys=len(environment))
    logs = state / "logs"
    processes: list[subprocess.Popen[bytes]] = []
    proxy_stderr = logs / "windows-light-proxy.err.log"
    ui_stderr = logs / "windows-light-ui.err.log"
    try:
        proxy = _spawn(
            python,
            ["-m", "uvicorn", "proxy_server:app", "--host", "127.0.0.1", "--port", str(proxy_port)],
            runtime=runtime,
            environment=environment,
            stdout_path=logs / "windows-light-proxy.out.log",
            stderr_path=proxy_stderr,
        )
        processes.append(proxy)
        _diagnostic("after_proxy_spawn", proxy_pid=proxy.pid)
        ui = _spawn(
            python,
            ["sovushka_ng.py"],
            runtime=runtime,
            environment=environment,
            stdout_path=logs / "windows-light-ui.out.log",
            stderr_path=ui_stderr,
        )
        processes.append(ui)
        _diagnostic("after_ui_spawn", ui_pid=ui.pid)
        # /api/health performs Qdrant/Ollama/index probes and is intentionally
        # not a process-readiness endpoint. It can exceed a short socket
        # timeout on a cold Windows start. Exact health is checked by the
        # transaction smoke after the server is reachable.
        _wait_process_url(
            proxy,
            f"http://127.0.0.1:{proxy_port}/api/version",
            60,
            label="proxy",
            stderr_path=proxy_stderr,
        )
        _wait_process_url(
            ui,
            f"http://127.0.0.1:{ui_port}/healthz",
            30,
            label="UI",
            stderr_path=ui_stderr,
        )
        payload = {
            "status": "started",
            "provider": environment["LES_LLM_PROVIDER"],
            "proxy_port": proxy_port,
            "ui_port": ui_port,
            "proxy_pid": proxy.pid,
            "ui_pid": ui.pid,
            "lemonade_host_pid": None,
            "proxy_alive": proxy.poll() is None,
            "ui_alive": ui.poll() is None,
            "state_root": str(state),
            "process_contract": PROCESS_CONTRACT,
            "python_executable": str(python),
        }
        path = logs / "windows-light-state.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return payload
    except Exception:
        for process in processes:
            _terminate_pid(process.pid)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "stop"):
        command = sub.add_parser(name)
        command.add_argument("--runtime", type=Path, required=True)
        command.add_argument("--state", type=Path, required=True)
        command.add_argument("--proxy-port", type=int, default=8050)
        command.add_argument("--ui-port", type=int, default=8051)
    args = parser.parse_args(argv)
    payload = (
        start(
            args.runtime,
            args.state,
            proxy_port=args.proxy_port,
            ui_port=args.ui_port,
        )
        if args.command == "start"
        else stop(
            args.state,
            runtime=args.runtime,
            proxy_port=args.proxy_port,
            ui_port=args.ui_port,
        )
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
