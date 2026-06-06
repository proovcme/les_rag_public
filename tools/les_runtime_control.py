"""Local launchd control helpers for the LES host runtime.

This module is intentionally proxy-independent: Sovushka can use it even when
les-proxy is down and needs to be started.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, TextIO


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
GUI_DOMAIN = f"gui/{os.getuid()}" if hasattr(os, "getuid") else "gui/0"
LEGACY_ROOT_PLACEHOLDER = "/Users/ovc/Projects/LES_v2"
ROOT_PLACEHOLDER = "__LES_ROOT__"


@dataclass(frozen=True)
class ServiceDef:
    key: str
    title: str
    label: str
    repo_plist: str
    agent_plist: str
    port: int | None = None
    health_url: str | None = None
    process_tokens: tuple[str, ...] = ()


@dataclass
class ServiceStatus:
    key: str
    title: str
    label: str
    loaded: bool
    running: bool
    pid: int | None
    port: int | None
    port_pid: int | None
    health: str
    detail: str


@dataclass
class ActionResult:
    action: str
    service: str
    ok: bool
    message: str
    status: ServiceStatus | None = None
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class MemoryProcess:
    pid: int
    user: str
    rss_mb: float
    command: str
    les_owned: bool
    protected: bool


@dataclass(frozen=True)
class MemoryPreflight:
    ram_free_gb: float | None
    ram_total_gb: float | None
    swap_pct: float | None
    top_processes: list[MemoryProcess]
    kill_candidates: list[MemoryProcess]
    min_free_gb: float
    min_rss_mb: float


SERVICES: dict[str, ServiceDef] = {
    "qdrant": ServiceDef(
        key="qdrant",
        title="Qdrant",
        label="me.ovc.les.qdrant",
        repo_plist="qdrant_launchd.plist",
        agent_plist="me.ovc.les.qdrant.plist",
        port=6333,
        health_url="http://127.0.0.1:6333/collections",
        process_tokens=("qdrant",),
    ),
    "mlx": ServiceDef(
        key="mlx",
        title="MLX Host",
        label="me.ovc.les.mlx",
        repo_plist="mlx_launchd.plist",
        agent_plist="me.ovc.les.mlx.plist",
        port=8080,
        health_url="http://127.0.0.1:8080/api/health",
        process_tokens=("mlx_host.py",),
    ),
    "proxy": ServiceDef(
        key="proxy",
        title="les-proxy",
        label="me.ovc.les.proxy",
        repo_plist="proxy_launchd.plist",
        agent_plist="me.ovc.les.proxy.plist",
        port=8050,
        health_url="http://127.0.0.1:8050/api/health",
        process_tokens=("uvicorn", "proxy_server:app"),
    ),
    "indexer": ServiceDef(
        key="indexer",
        title="Qwen indexer",
        label="me.ovc.les.qwen-index-until-done",
        repo_plist="qwen_index_launchd.plist",
        agent_plist="me.ovc.les.qwen-index-until-done.plist",
        process_tokens=("qwen_index_until_done.py",),
    ),
    "ui": ServiceDef(
        key="ui",
        title="Sovushka UI",
        label="com.les.sovushka",
        repo_plist="sovushka_launchd.plist",
        agent_plist="com.les.sovushka.plist",
        port=8051,
        health_url="http://127.0.0.1:8051/healthz",
        process_tokens=("sovushka_ng.py",),
    ),
}

START_ORDER = ("qdrant", "mlx", "proxy", "indexer")
STOP_ORDER = ("indexer", "proxy", "mlx", "qdrant")
PROTECTED_PROCESS_NAMES = {
    "kernel_task",
    "launchd",
    "WindowServer",
    "loginwindow",
    "sysmond",
    "powerd",
    "mDNSResponder",
    "securityd",
    "opendirectoryd",
    "trustd",
    "cfprefsd",
}


def _run(args: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _host_memory() -> tuple[float | None, float | None, float | None]:
    try:
        import psutil

        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return round(vm.available / 1e9, 1), round(vm.total / 1e9, 1), round(sw.percent, 1)
    except Exception:
        return None, None, None


def _process_name(command: str) -> str:
    first = command.strip().split(maxsplit=1)[0] if command.strip() else ""
    return Path(first).name or first


def _is_les_owned_process(command: str) -> bool:
    tokens = [token for service in SERVICES.values() for token in service.process_tokens]
    tokens.extend(service.label for service in SERVICES.values())
    tokens.append(str(ROOT))
    return any(token and token in command for token in tokens)


def _is_protected_process(command: str) -> bool:
    name = _process_name(command)
    if name in PROTECTED_PROCESS_NAMES:
        return True
    return any(f"/{protected}" in command for protected in PROTECTED_PROCESS_NAMES)


def _parse_ps_memory_processes(output: str) -> list[MemoryProcess]:
    processes: list[MemoryProcess] = []
    for line in output.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid_raw, rss_raw, user, command = parts
        if not pid_raw.isdigit():
            continue
        try:
            rss_mb = int(rss_raw) / 1024
        except ValueError:
            continue
        pid = int(pid_raw)
        processes.append(
            MemoryProcess(
                pid=pid,
                user=user,
                rss_mb=round(rss_mb, 1),
                command=command,
                les_owned=_is_les_owned_process(command),
                protected=_is_protected_process(command) or pid == os.getpid(),
            )
        )
    return sorted(processes, key=lambda item: item.rss_mb, reverse=True)


def memory_processes(limit: int = 10) -> list[MemoryProcess]:
    result = _run(["ps", "-axo", "pid=,rss=,user=,command="], timeout=8)
    if result.returncode != 0:
        return []
    return _parse_ps_memory_processes(result.stdout)[:limit]


def build_memory_preflight(
    *,
    limit: int = 10,
    min_rss_mb: float = 700.0,
    min_free_gb: float = 12.0,
) -> MemoryPreflight:
    ram_free_gb, ram_total_gb, swap_pct = _host_memory()
    top_processes = memory_processes(limit=limit)
    candidates = [
        process
        for process in top_processes
        if process.rss_mb >= min_rss_mb and not process.les_owned and not process.protected
    ]
    return MemoryPreflight(
        ram_free_gb=ram_free_gb,
        ram_total_gb=ram_total_gb,
        swap_pct=swap_pct,
        top_processes=top_processes,
        kill_candidates=candidates,
        min_free_gb=min_free_gb,
        min_rss_mb=min_rss_mb,
    )


def _short_command(command: str, max_len: int = 90) -> str:
    command = " ".join(command.split())
    return command if len(command) <= max_len else command[: max_len - 1] + "…"


def print_memory_preflight(preflight: MemoryPreflight, *, stream: TextIO | None = None) -> None:
    stream = stream or sys.stderr
    free = "?" if preflight.ram_free_gb is None else f"{preflight.ram_free_gb:.1f} GB"
    total = "?" if preflight.ram_total_gb is None else f"{preflight.ram_total_gb:.1f} GB"
    swap = "?" if preflight.swap_pct is None else f"{preflight.swap_pct:.1f}%"
    print(f"[MEM] RAM free {free} / {total}, swap {swap}", file=stream)
    if preflight.ram_free_gb is not None and preflight.ram_free_gb >= preflight.min_free_gb:
        print(f"[MEM] Free memory is OK for startup threshold {preflight.min_free_gb:.1f} GB.", file=stream)
    elif preflight.ram_free_gb is not None:
        print(f"[MEM] Free memory is below startup comfort threshold {preflight.min_free_gb:.1f} GB.", file=stream)

    if not preflight.top_processes:
        print("[MEM] Process list unavailable.", file=stream)
        return

    print("[MEM] Top resident memory processes:", file=stream)
    for index, process in enumerate(preflight.top_processes, 1):
        flags = []
        if process.les_owned:
            flags.append("LES")
        if process.protected:
            flags.append("protected")
        suffix = f" [{' '.join(flags)}]" if flags else ""
        print(
            f"  {index:>2}. pid={process.pid:<6} rss={process.rss_mb:>7.1f} MB "
            f"user={process.user:<10} {_short_command(process.command)}{suffix}",
            file=stream,
        )


def select_memory_processes(answer: str, candidates: list[MemoryProcess]) -> list[MemoryProcess]:
    selected: list[MemoryProcess] = []
    by_number = {str(index): process for index, process in enumerate(candidates, 1)}
    by_pid = {str(process.pid): process for process in candidates}
    for token in answer.replace(",", " ").split():
        process = by_number.get(token) or by_pid.get(token)
        if process and process not in selected:
            selected.append(process)
    return selected


def terminate_memory_processes(processes: list[MemoryProcess]) -> list[dict[str, str | int | bool]]:
    results: list[dict[str, str | int | bool]] = []
    for process in processes:
        current = _process_command(process.pid)
        if current != process.command:
            results.append({"pid": process.pid, "ok": False, "message": "process changed; skipped"})
            continue
        try:
            os.kill(process.pid, signal.SIGTERM)
            results.append({"pid": process.pid, "ok": True, "message": "SIGTERM sent"})
        except ProcessLookupError:
            results.append({"pid": process.pid, "ok": True, "message": "already exited"})
        except PermissionError:
            results.append({"pid": process.pid, "ok": False, "message": "permission denied"})
    return results


def offer_memory_kill(preflight: MemoryPreflight, *, stream: TextIO | None = None) -> list[dict[str, str | int | bool]]:
    stream = stream or sys.stderr
    candidates = preflight.kill_candidates
    if not candidates:
        print("[MEM] No safe kill candidates above threshold.", file=stream)
        return []
    if not sys.stdin.isatty():
        print("[MEM] Non-interactive session: skip kill prompt.", file=stream)
        return []

    print("[MEM] Kill candidates (SIGTERM only, explicit selection required):", file=stream)
    for index, process in enumerate(candidates, 1):
        print(
            f"  {index:>2}. pid={process.pid:<6} rss={process.rss_mb:>7.1f} MB "
            f"{_short_command(process.command)}",
            file=stream,
        )
    answer = input("[MEM] Enter numbers or PIDs to terminate, or Enter to skip: ").strip()
    selected = select_memory_processes(answer, candidates)
    if not selected:
        print("[MEM] Nothing selected.", file=stream)
        return []
    results = terminate_memory_processes(selected)
    for result in results:
        mark = "ok" if result["ok"] else "skip"
        print(f"[MEM] {mark}: pid={result['pid']} {result['message']}", file=stream)
    time.sleep(1)
    return results


def _agent_path(service: ServiceDef) -> Path:
    return LAUNCH_AGENTS / service.agent_plist


def _repo_plist_path(service: ServiceDef) -> Path:
    return ROOT / service.repo_plist


def _render_plist_template(src: Path) -> str:
    text = src.read_text(encoding="utf-8")
    root = str(ROOT)
    return text.replace(ROOT_PLACEHOLDER, root).replace(LEGACY_ROOT_PLACEHOLDER, root)


def _install(service: ServiceDef) -> None:
    src = _repo_plist_path(service)
    if not src.exists():
        raise FileNotFoundError(f"missing plist template: {src}")
    LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
    dst = _agent_path(service)
    rendered = _render_plist_template(src).encode("utf-8")
    if not dst.exists() or rendered != dst.read_bytes():
        dst.write_bytes(rendered)


def _launchctl_print(service: ServiceDef) -> subprocess.CompletedProcess[str]:
    return _run(["launchctl", "print", f"{GUI_DOMAIN}/{service.label}"], timeout=8)


def _enable(service: ServiceDef) -> subprocess.CompletedProcess[str]:
    return _run(["launchctl", "enable", f"{GUI_DOMAIN}/{service.label}"], timeout=8)


def _loaded(service: ServiceDef) -> bool:
    return _launchctl_print(service).returncode == 0


def _pid_from_print(text: str) -> int | None:
    match = re.search(r"\bpid = (\d+)", text)
    return int(match.group(1)) if match else None


def _port_pid(port: int | None) -> int | None:
    if not port:
        return None
    result = _run(["lsof", "-tiTCP:%s" % port, "-sTCP:LISTEN"], timeout=5)
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def _health(url: str | None, timeout: float = 6.0) -> tuple[str, str]:
    if not url:
        return "n/a", ""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "les-runtime-control"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = getattr(response, "status", 0)
            return ("ok" if code < 500 else "err"), f"HTTP {code}"
    except urllib.error.HTTPError as error:
        return ("ok" if error.code < 500 else "err"), f"HTTP {error.code}"
    except Exception as error:
        return "err", str(error)[:140]


def _process_command(pid: int) -> str:
    result = _run(["ps", "-o", "command=", "-p", str(pid)], timeout=5)
    return result.stdout.strip()


def _safe_terminate_port_listener(service: ServiceDef) -> None:
    pid = _port_pid(service.port)
    if not pid:
        return
    command = _process_command(pid)
    if service.process_tokens and not any(token in command for token in service.process_tokens):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def status(service_key: str) -> ServiceStatus:
    service = SERVICES[service_key]
    printed = _launchctl_print(service)
    loaded = printed.returncode == 0
    pid = _pid_from_print(printed.stdout) if loaded else None
    port_pid = _port_pid(service.port)
    health, detail = _health(service.health_url)
    if health == "err" and (pid or port_pid):
        health = "slow"
    running = bool(pid or port_pid or health == "ok")
    return ServiceStatus(
        key=service.key,
        title=service.title,
        label=service.label,
        loaded=loaded,
        running=running,
        pid=pid,
        port=service.port,
        port_pid=port_pid,
        health=health,
        detail=detail,
    )


def all_statuses(keys: Iterable[str] | None = None) -> list[ServiceStatus]:
    return [status(key) for key in (keys or SERVICES.keys())]


def _service_ready(service: ServiceDef, current: ServiceStatus) -> bool:
    if _port_owner_conflict(service, current):
        return False
    if service.health_url:
        return current.health == "ok"
    return current.running


def _port_owner_conflict(service: ServiceDef, current: ServiceStatus) -> bool:
    if not service.port or not current.port_pid:
        return False
    if current.pid and current.port_pid != current.pid:
        return True
    return current.loaded and current.pid is None


def start_service(service_key: str, wait: bool = True) -> ActionResult:
    service = SERVICES[service_key]
    before = status(service_key)
    if before.running and _service_ready(service, before):
        return ActionResult("start", service.key, True, "already running", before)
    if before.running and _port_owner_conflict(service, before):
        stop_service(service_key, wait=True, terminate_listener=True)
        before = status(service_key)
    if before.running:
        after = wait_for(service_key) if wait else before
        ready = _service_ready(service, after)
        return ActionResult("start", service.key, ready, "already running" if ready else "running but not ready", after)

    try:
        _install(service)
    except Exception as error:
        return ActionResult("start", service.key, False, str(error), before)

    enable = _enable(service)
    if enable.returncode != 0:
        after_enable = status(service_key)
        return ActionResult("start", service.key, False, "launchctl enable failed", after_enable, enable.stdout, enable.stderr)

    agent = str(_agent_path(service))
    if before.loaded:
        result = _run(["launchctl", "kickstart", f"{GUI_DOMAIN}/{service.label}"], timeout=15)
    else:
        result = _run(["launchctl", "bootstrap", GUI_DOMAIN, agent], timeout=15)
        if result.returncode != 0 and "already bootstrapped" in result.stderr:
            result = _run(["launchctl", "kickstart", f"{GUI_DOMAIN}/{service.label}"], timeout=15)

    if result.returncode != 0:
        after_error = status(service_key)
        return ActionResult("start", service.key, False, "launchctl failed", after_error, result.stdout, result.stderr)

    after = wait_for(service_key) if wait else status(service_key)
    ready = _service_ready(service, after)
    return ActionResult("start", service.key, ready, "started" if ready else "start requested", after)


def restart_service(service_key: str, wait: bool = True) -> ActionResult:
    service = SERVICES[service_key]
    try:
        _install(service)
    except Exception as error:
        return ActionResult("restart", service.key, False, str(error), status(service_key))

    before = status(service_key)
    if _port_owner_conflict(service, before):
        stop_service(service_key, wait=True, terminate_listener=True)
        return start_service(service_key, wait=wait)

    if not _loaded(service):
        return start_service(service_key, wait=wait)

    result = _run(["launchctl", "kickstart", "-k", f"{GUI_DOMAIN}/{service.label}"], timeout=15)
    after = wait_for(service_key) if wait else status(service_key)
    ok = result.returncode == 0 and _service_ready(service, after)
    return ActionResult("restart", service.key, ok, "restarted" if ok else "restart requested", after, result.stdout, result.stderr)


def stop_service(service_key: str, wait: bool = True, terminate_listener: bool = True) -> ActionResult:
    service = SERVICES[service_key]
    before = status(service_key)
    agent = _agent_path(service)
    if before.loaded:
        result = _run(["launchctl", "bootout", GUI_DOMAIN, str(agent)], timeout=15)
    else:
        result = subprocess.CompletedProcess([], 0, "", "")

    if terminate_listener:
        _safe_terminate_port_listener(service)

    if wait:
        deadline = time.time() + 12
        after = status(service_key)
        while after.running and time.time() < deadline:
            time.sleep(0.5)
            after = status(service_key)
    else:
        after = status(service_key)

    ok = not after.running
    return ActionResult("stop", service.key, ok, "stopped" if ok else "stop requested", after, result.stdout, result.stderr)


def wait_for(service_key: str, timeout: int = 45) -> ServiceStatus:
    service = SERVICES[service_key]
    deadline = time.time() + timeout
    current = status(service_key)
    while not _service_ready(service, current) and time.time() < deadline:
        time.sleep(1)
        current = status(service_key)
    return current


def start_core(include_ui: bool = False, include_indexer: bool = True) -> list[ActionResult]:
    order = list(START_ORDER if include_indexer else ("qdrant", "mlx", "proxy"))
    if include_ui:
        order.append("ui")
    return [start_service(key) for key in order]


def stop_core(include_ui: bool = False) -> list[ActionResult]:
    order = list(STOP_ORDER)
    if include_ui:
        order.insert(0, "ui")
    return [stop_service(key) for key in order]


def restart_core(include_ui: bool = False, include_indexer: bool = True) -> list[ActionResult]:
    return stop_core(include_ui=include_ui) + start_core(include_ui=include_ui, include_indexer=include_indexer)


def _json_default(value):
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(type(value).__name__)


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control LES launchd runtime services.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    mem = sub.add_parser("memory-preflight")
    mem.add_argument("--limit", type=int, default=10)
    mem.add_argument("--min-rss-mb", type=float, default=700.0)
    mem.add_argument("--min-free-gb", type=float, default=12.0)
    mem.add_argument("--offer-kill", action="store_true")

    start = sub.add_parser("start-core")
    start.add_argument("--include-ui", action="store_true")
    start.add_argument("--no-indexer", action="store_true")
    start.add_argument("--open-ui", action="store_true")
    start.add_argument("--memory-preflight", action="store_true")
    start.add_argument("--offer-kill", action="store_true")
    start.add_argument("--memory-limit", type=int, default=10)
    start.add_argument("--memory-min-rss-mb", type=float, default=700.0)
    start.add_argument("--memory-min-free-gb", type=float, default=12.0)

    stop = sub.add_parser("stop-core")
    stop.add_argument("--include-ui", action="store_true")

    restart = sub.add_parser("restart-core")
    restart.add_argument("--include-ui", action="store_true")
    restart.add_argument("--no-indexer", action="store_true")

    for name in ("start", "stop", "restart"):
        p = sub.add_parser(name)
        p.add_argument("service", choices=sorted(SERVICES))

    args = parser.parse_args(argv)
    if args.command == "status":
        _print_json(all_statuses())
        return 0
    if args.command == "memory-preflight":
        preflight = build_memory_preflight(
            limit=args.limit,
            min_rss_mb=args.min_rss_mb,
            min_free_gb=args.min_free_gb,
        )
        print_memory_preflight(preflight)
        if args.offer_kill:
            offer_memory_kill(preflight)
        _print_json(preflight)
        return 0
    if args.command == "start-core":
        if args.memory_preflight:
            preflight = build_memory_preflight(
                limit=args.memory_limit,
                min_rss_mb=args.memory_min_rss_mb,
                min_free_gb=args.memory_min_free_gb,
            )
            print_memory_preflight(preflight)
            if args.offer_kill:
                offer_memory_kill(preflight)
        result = start_core(include_ui=args.include_ui, include_indexer=not args.no_indexer)
        _print_json(result)
        if args.open_ui:
            subprocess.run(["open", "http://127.0.0.1:8051/les"], check=False)
        return 0 if all(item.ok for item in result) else 1
    if args.command == "stop-core":
        result = stop_core(include_ui=args.include_ui)
        _print_json(result)
        return 0 if all(item.ok for item in result) else 1
    if args.command == "restart-core":
        result = restart_core(include_ui=args.include_ui, include_indexer=not args.no_indexer)
        _print_json(result)
        return 0 if all(item.ok for item in result) else 1
    if args.command == "start":
        _print_json(start_service(args.service))
        return 0
    if args.command == "stop":
        _print_json(stop_service(args.service))
        return 0
    if args.command == "restart":
        _print_json(restart_service(args.service))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
