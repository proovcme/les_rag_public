from tools import les_runtime_control as runtime_control


def test_service_ready_requires_health_ok_when_health_url_exists():
    service = runtime_control.ServiceDef(
        key="qdrant",
        title="Qdrant",
        label="me.ovc.les.qdrant",
        repo_plist="qdrant_launchd.plist",
        agent_plist="me.ovc.les.qdrant.plist",
        health_url="http://127.0.0.1:6333/collections",
    )
    status = runtime_control.ServiceStatus(
        key="qdrant",
        title="Qdrant",
        label="me.ovc.les.qdrant",
        loaded=True,
        running=True,
        pid=123,
        port=6333,
        port_pid=123,
        health="slow",
        detail="connection refused",
    )

    assert runtime_control._service_ready(service, status) is False


def test_service_ready_rejects_launchd_job_with_orphan_port_owner():
    service = runtime_control.ServiceDef(
        key="mlx",
        title="MLX Host",
        label="me.ovc.les.mlx",
        repo_plist="mlx_launchd.plist",
        agent_plist="me.ovc.les.mlx.plist",
        port=8080,
        health_url="http://127.0.0.1:8080/api/health",
    )
    status = runtime_control.ServiceStatus(
        key="mlx",
        title="MLX Host",
        label="me.ovc.les.mlx",
        loaded=True,
        running=True,
        pid=None,
        port=8080,
        port_pid=630,
        health="ok",
        detail="HTTP 200",
    )

    assert runtime_control._service_ready(service, status) is False


def test_service_ready_rejects_mismatched_launchd_and_port_pids():
    service = runtime_control.ServiceDef(
        key="mlx",
        title="MLX Host",
        label="me.ovc.les.mlx",
        repo_plist="mlx_launchd.plist",
        agent_plist="me.ovc.les.mlx.plist",
        port=8080,
        health_url="http://127.0.0.1:8080/api/health",
    )
    status = runtime_control.ServiceStatus(
        key="mlx",
        title="MLX Host",
        label="me.ovc.les.mlx",
        loaded=True,
        running=True,
        pid=32701,
        port=8080,
        port_pid=630,
        health="ok",
        detail="HTTP 200",
    )

    assert runtime_control._service_ready(service, status) is False


def test_service_ready_accepts_launchd_job_that_owns_port():
    service = runtime_control.ServiceDef(
        key="mlx",
        title="MLX Host",
        label="me.ovc.les.mlx",
        repo_plist="mlx_launchd.plist",
        agent_plist="me.ovc.les.mlx.plist",
        port=8080,
        health_url="http://127.0.0.1:8080/api/health",
    )
    status = runtime_control.ServiceStatus(
        key="mlx",
        title="MLX Host",
        label="me.ovc.les.mlx",
        loaded=True,
        running=True,
        pid=37140,
        port=8080,
        port_pid=37140,
        health="ok",
        detail="HTTP 200",
    )

    assert runtime_control._service_ready(service, status) is True


def test_service_ready_uses_running_for_services_without_health_url():
    service = runtime_control.ServiceDef(
        key="indexer",
        title="Indexer",
        label="me.ovc.les.qwen-index-until-done",
        repo_plist="qwen_index_launchd.plist",
        agent_plist="me.ovc.les.qwen-index-until-done.plist",
    )
    status = runtime_control.ServiceStatus(
        key="indexer",
        title="Indexer",
        label="me.ovc.les.qwen-index-until-done",
        loaded=True,
        running=True,
        pid=123,
        port=None,
        port_pid=None,
        health="n/a",
        detail="",
    )

    assert runtime_control._service_ready(service, status) is True


def test_parse_memory_processes_marks_les_and_protected_processes():
    output = """
      10  1048576 ovc  /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --type=renderer
       1   512000 root /sbin/launchd
      20   900000 ovc  /Users/ovc/Projects/LES_v2/.venv/bin/python mlx_host.py
    """

    processes = runtime_control._parse_ps_memory_processes(output)

    assert [process.pid for process in processes] == [10, 20, 1]
    assert processes[0].rss_mb == 1024.0
    assert processes[0].protected is False
    assert processes[1].les_owned is True
    assert processes[2].protected is True


def test_memory_preflight_candidates_exclude_les_and_protected(monkeypatch):
    processes = [
        runtime_control.MemoryProcess(10, "ovc", 1200.0, "Chrome", les_owned=False, protected=False),
        runtime_control.MemoryProcess(20, "ovc", 1100.0, "mlx_host.py", les_owned=True, protected=False),
        runtime_control.MemoryProcess(1, "root", 1000.0, "launchd", les_owned=False, protected=True),
        runtime_control.MemoryProcess(30, "ovc", 100.0, "small", les_owned=False, protected=False),
    ]
    monkeypatch.setattr(runtime_control, "_host_memory", lambda: (7.5, 24.0, 10.0))
    monkeypatch.setattr(runtime_control, "memory_processes", lambda limit=10: processes[:limit])

    preflight = runtime_control.build_memory_preflight(limit=4, min_rss_mb=700.0)

    assert preflight.ram_free_gb == 7.5
    assert [process.pid for process in preflight.kill_candidates] == [10]


def test_select_memory_processes_accepts_numbers_and_pids_without_duplicates():
    candidates = [
        runtime_control.MemoryProcess(10, "ovc", 1200.0, "Chrome", False, False),
        runtime_control.MemoryProcess(30, "ovc", 900.0, "Cursor", False, False),
    ]

    selected = runtime_control.select_memory_processes("1 30 30 nope", candidates)

    assert [process.pid for process in selected] == [10, 30]


def test_terminate_memory_processes_rechecks_pid_command(monkeypatch):
    candidates = [
        runtime_control.MemoryProcess(10, "ovc", 1200.0, "Chrome", False, False),
        runtime_control.MemoryProcess(30, "ovc", 900.0, "Cursor", False, False),
    ]
    killed = []
    monkeypatch.setattr(
        runtime_control,
        "_process_command",
        lambda pid: "Chrome" if pid == 10 else "Different",
    )
    monkeypatch.setattr(runtime_control.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    results = runtime_control.terminate_memory_processes(candidates)

    assert killed == [(10, runtime_control.signal.SIGTERM)]
    assert results == [
        {"pid": 10, "ok": True, "message": "SIGTERM sent"},
        {"pid": 30, "ok": False, "message": "process changed; skipped"},
    ]


def test_start_service_enables_disabled_launch_agent(monkeypatch):
    calls = []
    service = runtime_control.SERVICES["indexer"]
    before = runtime_control.ServiceStatus(
        key=service.key,
        title=service.title,
        label=service.label,
        loaded=False,
        running=False,
        pid=None,
        port=None,
        port_pid=None,
        health="n/a",
        detail="",
    )
    after = runtime_control.ServiceStatus(
        key=service.key,
        title=service.title,
        label=service.label,
        loaded=True,
        running=True,
        pid=123,
        port=None,
        port_pid=None,
        health="n/a",
        detail="",
    )
    statuses = iter([before, after])

    monkeypatch.setattr(runtime_control, "status", lambda key: next(statuses))
    monkeypatch.setattr(runtime_control, "_install", lambda svc: None)
    monkeypatch.setattr(runtime_control, "_enable", lambda svc: calls.append(["enable", svc.label]) or runtime_control.subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(runtime_control, "_run", lambda args, timeout=20: calls.append(args) or runtime_control.subprocess.CompletedProcess(args, 0, "", ""))
    monkeypatch.setattr(runtime_control, "wait_for", lambda key: after)

    result = runtime_control.start_service("indexer")

    assert result.ok is True
    assert calls[0] == ["enable", service.label]
    assert any(call[:2] == ["launchctl", "bootstrap"] for call in calls if isinstance(call, list) and len(call) >= 2)


def test_ui_service_uses_lightweight_health_endpoint():
    assert runtime_control.SERVICES["ui"].health_url == "http://127.0.0.1:8051/healthz"
