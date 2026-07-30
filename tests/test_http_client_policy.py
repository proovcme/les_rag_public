import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from backend.http_client_policy import is_loopback_url, trust_env_for_url


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8050/api/health",
        "http://localhost.:8050",
        "http://worker.localhost:8080/v1",
        "http://127.0.0.1:6333",
        "http://127.42.0.8:8080",
        "http://[::1]:8080/api/health",
    ],
)
def test_loopback_urls_bypass_proxy_environment(url: str):
    assert is_loopback_url(url)
    assert trust_env_for_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://les.ovc.me",
        "https://example.com",
        "http://10.0.0.2:8050",
        "http://192.168.1.20:6333",
        "http://host.docker.internal:6333",
        "not-a-url",
    ],
)
def test_external_and_private_network_urls_keep_normal_httpx_policy(url: str):
    assert not is_loopback_url(url)
    assert trust_env_for_url(url) is True


def test_invalid_system_proxy_cannot_break_loopback_request(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(204)
            self.end_headers()

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ALL_PROXY", "socks4://127.0.0.1:9")
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(trust_env=trust_env_for_url(url), timeout=2.0) as client:
            assert client.get(url).status_code == 204
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_critical_loopback_callers_apply_shared_policy():
    root = Path(__file__).resolve().parents[1]
    targets = (
        "sovushka/state.py",
        "sovushka/lite_bridge.py",
        "proxy/app.py",
        "proxy/routers/diagnostics.py",
        "proxy/routers/runtime.py",
        "backend/metrics_collector.py",
        "backend/reranker.py",
    )
    for relative in targets:
        source = (root / relative).read_text(encoding="utf-8")
        assert "trust_env_for_url" in source, relative
        for occurrence in source.split("httpx.AsyncClient(")[1:]:
            constructor = occurrence.split(")", 1)[0]
            assert "trust_env=" in constructor, relative
