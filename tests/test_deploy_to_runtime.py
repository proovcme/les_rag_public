from tools import deploy_to_runtime


def test_mlx_host_change_restarts_the_mlx_service():
    assert deploy_to_runtime._service_for_path("mlx_host.py") == "me.ovc.les.mlx"


def test_backend_change_restarts_the_proxy_service():
    assert deploy_to_runtime._service_for_path("backend/qdrant_adapter.py") == "me.ovc.les.proxy"
