from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools.windows_prebundle_smoke import (
    PrebundleSmokeError,
    _windows_powershell_environment,
    run_prebundle_smoke,
)


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows release boundary")


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/api/health":
            body = json.dumps({"status": "ready"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args):
        return


@pytest.fixture
def health_servers():
    servers = [ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler) for _ in range(2)]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        yield [server.server_port for server in servers]
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)


def _fake_runtime(root: Path, *, failed: bool = False) -> Path:
    app = root / "installers/windows/app"
    app.mkdir(parents=True)
    if failed:
        bootstrap = r"""
$logDir = Join-Path $env:LES_WINDOWS_STATE_ROOT "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$proxyLog = Join-Path $logDir "windows-light-proxy.err.log"
"real proxy startup error" | Set-Content -LiteralPath $proxyLog -Encoding utf8
@{proxy_log=$proxyLog; ui_log=$null} |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir "windows-light-state.json") -Encoding utf8
@{state="failed"; phase="services"; code="services_api_not_ready"; message="API failed"} |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir "bootstrap-status.json") -Encoding utf8
exit 1
"""
    else:
        bootstrap = r"""
Get-FileHash -LiteralPath $MyInvocation.MyCommand.Definition | Out-Null
$logDir = Join-Path $env:LES_WINDOWS_STATE_ROOT "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
@{
  proxy_port=[int]$env:LES_PREBUNDLE_TEST_PROXY_PORT
  ui_port=[int]$env:LES_PREBUNDLE_TEST_UI_PORT
  proxy_pid=[int]$env:LES_PREBUNDLE_TEST_PYTHON_PID
  ui_pid=[int]$env:LES_PREBUNDLE_TEST_PYTHON_PID
  process_contract="direct_python_no_console_v1"
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir "windows-light-state.json") -Encoding utf8
@{state="ready"; phase="ready"; code="bootstrap_degraded"; message="ready"} |
  ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDir "bootstrap-status.json") -Encoding utf8
exit 0
"""
    (app / "bootstrap.ps1").write_text(bootstrap, encoding="utf-8")
    (root / "installers/windows/stop-light.ps1").write_text(
        "param([int]$ProxyPort, [int]$UiPort)\nexit 0\n", encoding="utf-8"
    )
    return root


def test_prebundle_smoke_uses_programs_shaped_runtime_and_isolated_state(
    tmp_path, monkeypatch, health_servers
):
    runtime = _fake_runtime(tmp_path / "runtime")
    monkeypatch.setenv("LES_PREBUNDLE_TEST_PROXY_PORT", str(health_servers[0]))
    monkeypatch.setenv("LES_PREBUNDLE_TEST_UI_PORT", str(health_servers[1]))
    monkeypatch.setenv("LES_PREBUNDLE_TEST_PYTHON_PID", str(os.getpid()))
    monkeypatch.setenv("PSModulePath", str(tmp_path / "incompatible-powershell-modules"))

    result = run_prebundle_smoke(runtime, timeout_seconds=20)

    assert result["ok"] is True
    assert "Programs" in str(result["runtime_root"])
    assert Path(result["state_root"]) != Path(os.environ["LOCALAPPDATA"]) / "LES"
    assert result["proxy_port"] == health_servers[0]
    assert result["ui_port"] == health_servers[1]
    assert not Path(result["test_root"]).exists()


def test_prebundle_smoke_surfaces_bootstrap_failure(tmp_path):
    runtime = _fake_runtime(tmp_path / "runtime", failed=True)

    with pytest.raises(PrebundleSmokeError, match="real proxy startup error"):
        run_prebundle_smoke(runtime, timeout_seconds=20)


def test_windows_powershell_environment_discards_incompatible_module_path(monkeypatch):
    monkeypatch.setenv("PSModulePath", r"C:\fake\PowerShell7\Modules")
    monkeypatch.setenv("VIRTUAL_ENV", r"C:\worktree\.venv")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", r"C:\worktree\.venv")
    monkeypatch.setenv("UV_CACHE_DIR", r"C:\worktree\uv-cache")

    environment = _windows_powershell_environment(dict(os.environ))

    assert r"C:\fake\PowerShell7\Modules" not in environment["PSModulePath"]
    assert r"WindowsPowerShell\v1.0\Modules" in environment["PSModulePath"]
    assert "VIRTUAL_ENV" not in environment
    assert "UV_PROJECT_ENVIRONMENT" not in environment
    assert "UV_CACHE_DIR" not in environment
