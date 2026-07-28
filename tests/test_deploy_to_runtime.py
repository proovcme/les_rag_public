from tools import deploy_to_runtime


def test_mlx_host_change_restarts_the_mlx_service():
    assert deploy_to_runtime._service_for_path("mlx_host.py") == "me.ovc.les.mlx"


def test_backend_change_restarts_the_proxy_service():
    assert deploy_to_runtime._service_for_path("backend/qdrant_adapter.py") == "me.ovc.les.proxy"


def test_clean_commit_deploy_uses_runtime_stamp_as_diff_baseline(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / ".les_deploy_stamp.json").write_text(
        '{"deployed_commit":"old123"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(deploy_to_runtime, "RT", runtime)
    monkeypatch.setattr(deploy_to_runtime, "_git", lambda _args: "")

    class Result:
        returncode = 0
        stdout = "backend/qdrant_adapter.py\nproxy/services/version_service.py\n"

    monkeypatch.setattr(deploy_to_runtime.subprocess, "run", lambda *_args, **_kwargs: Result())

    assert deploy_to_runtime._changed_files() == [
        "backend/qdrant_adapter.py",
        "proxy/services/version_service.py",
    ]


def test_runtime_file_matching_deployed_commit_is_safe(monkeypatch, tmp_path):
    dev = tmp_path / "dev"
    runtime = tmp_path / "runtime"
    (dev / "proxy").mkdir(parents=True)
    (runtime / "proxy").mkdir(parents=True)
    (dev / "proxy/app.py").write_text("new", encoding="utf-8")
    (runtime / "proxy/app.py").write_text("old", encoding="utf-8")
    monkeypatch.setattr(deploy_to_runtime, "DEV", dev)
    monkeypatch.setattr(deploy_to_runtime, "RT", runtime)
    monkeypatch.setattr(
        deploy_to_runtime,
        "_commit_bytes",
        lambda commit, _path: b"old" if commit == "old123" else b"new",
    )

    assert deploy_to_runtime.classify(
        "proxy/app.py",
        {},
        deployed_commit="old123",
    ) == ("clean@deployed", True)
