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
