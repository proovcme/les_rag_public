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


def test_embed_client_keeps_loopback_embeddings_off_the_proxy_environment(monkeypatch):
    """Эмбеддер живёт на loopback: унаследованный ALL_PROXY не должен его ломать.

    Реальный отказ 08.09: задание ФГИС унаследовало от процесса прокси
    `ALL_PROXY=socks4://127.0.0.1:10808`, httpx такую схему не поддерживает, и сборка
    сметной базы упала с `ValueError: Unknown scheme for proxy URL`.
    """
    import asyncio

    from backend import qdrant_adapter

    captured: dict[str, object] = {}

    class _FakeResponse:
        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
                "embedding_model": "Qwen3-Embedding-0.6B-GGUF",
                "embedding_backend": "llama_cpp",
            }

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json):  # noqa: A002 - сигнатура httpx
            return _FakeResponse()

    monkeypatch.setenv("ALL_PROXY", "socks4://127.0.0.1:10808")
    monkeypatch.setattr(qdrant_adapter.httpx, "AsyncClient", _FakeClient)

    client = qdrant_adapter.EmbedClient(
        "http://127.0.0.1:18080",
        "Qwen3-Embedding-0.6B-GGUF",
        backend="llama_cpp",
    )
    asyncio.run(client.encode_async(["текст"]))

    assert captured.get("trust_env") is False


def test_unsupported_proxy_scheme_is_dropped_from_child_environment():
    """Задание не должно наследовать прокси-схему, которую httpx не понимает.

    08.09 обновление ФГИС унаследовало `ALL_PROXY=socks4://127.0.0.1:10808` и упало
    на сборке сметной базы: httpx поднимает ValueError уже при создании клиента.
    """
    from backend.http_client_policy import environment_without_unsupported_proxies

    source = {
        "PATH": "C:/bin",
        "ALL_PROXY": "socks4://127.0.0.1:10808",
        "HTTP_PROXY": "http://proxy.corp:3128",
        "https_proxy": "socks4a://127.0.0.1:10808",
        "NO_PROXY": "127.0.0.1",
    }
    cleaned = environment_without_unsupported_proxies(source)

    assert "ALL_PROXY" not in cleaned
    assert "https_proxy" not in cleaned
    # Поддерживаемые схемы и всё остальное окружение сохраняются.
    assert cleaned["HTTP_PROXY"] == "http://proxy.corp:3128"
    assert cleaned["NO_PROXY"] == "127.0.0.1"
    assert cleaned["PATH"] == "C:/bin"
    # Исходное окружение не мутируется.
    assert source["ALL_PROXY"] == "socks4://127.0.0.1:10808"


def test_fgis_job_starts_children_without_unsupported_proxy_scheme():
    """Порождение задания ФГИС обязано чистить окружение, а не наследовать его как есть."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "proxy/services/fgis_update_service.py").read_text(encoding="utf-8")
    assert "env=environment_without_unsupported_proxies()" in source


def test_qdrant_clients_bypass_the_proxy_environment():
    """Клиент Qdrant тоже строит httpx и падает на схеме, которую тот не знает.

    Живой отказ 09.09 при включённом VPN: `QdrantClient(url=...)` поднимает
    `ValueError: Unknown scheme for proxy URL URL('socks4://127.0.0.1:10808')` при
    создании — то есть сметный поиск норм не работает вовсе, а не «медленно».
    Проверено там же: с `trust_env=False` клиент создаётся и отвечает.
    """
    import re

    root = Path(__file__).resolve().parents[1]
    targets = (
        "proxy/smeta_core/norm_browser.py",
        "proxy/services/rag_readiness_service.py",
        "proxy/services/rag_catalog_recovery_service.py",
        "proxy/services/smeta_generation_reconciliation_service.py",
        "proxy/routers/runtime.py",
        "backend/qdrant_adapter.py",
    )
    for relative in targets:
        source = (root / relative).read_text(encoding="utf-8")
        for match in re.finditer(r"(?:Async)?QdrantClient\(", source):
            tail = source[match.end(): match.end() + 400]
            depth, ctor = 1, []
            for char in tail:
                depth += char == "("
                depth -= char == ")"
                if depth == 0:
                    break
                ctor.append(char)
            constructor = "".join(ctor)
            assert "trust_env" in constructor, f"{relative}: {constructor[:80]}"
