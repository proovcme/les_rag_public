import json
import socket

import pytest

from proxy.services.web_page_reader_service import (
    UnsafeWebUrl,
    read_web_page,
    validate_public_web_url,
)
from proxy.services.web_research_config_service import WebResearchConfig


def _public_resolver(host, port, **_kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port),
        )
    ]


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield self._body


class _RecordingClient:
    def __init__(self, payload):
        self.response_payload = payload
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def stream(self, method, url, *, json, headers):
        self.calls.append(
            {"method": method, "url": url, "json": json, "headers": headers}
        )
        return _Response(self.response_payload)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/private",
        "http://[::1]/",
        "https://user:pass@example.com/",
    ],
)
def test_reader_rejects_non_public_destinations_before_http(url):
    client = _RecordingClient({"success": True, "results": []})

    with pytest.raises(UnsafeWebUrl):
        validate_public_web_url(url, resolver=_public_resolver)

    assert client.calls == []


def test_reader_sends_only_model_selected_url_and_fixed_typed_options():
    selected_url = "https://public.example/material"
    client = _RecordingClient(
        {
            "success": True,
            "results": [
                {
                    "url": selected_url,
                    "title": "Материал",
                    "markdown": {"raw_markdown": "Материал " * 1000},
                }
            ],
        }
    )
    config = WebResearchConfig(
        "extended",
        "http://127.0.0.1:8888",
        "http://127.0.0.1:11235",
        "",
    )

    result = read_web_page(
        selected_url,
        max_chars=4000,
        config=config,
        resolver=_public_resolver,
        client_factory=lambda **_kwargs: client,
    )

    assert len(client.calls) == 1
    request = client.calls[0]
    assert request["method"] == "POST"
    assert request["url"] == "http://127.0.0.1:11235/crawl"
    assert request["json"] == {
        "urls": [selected_url],
        "browser_config": {
            "type": "BrowserConfig",
            "params": {"headless": True, "text_mode": True},
        },
        "crawler_config": {
            "type": "CrawlerRunConfig",
            "params": {
                "stream": False,
                "cache_mode": "bypass",
                "page_timeout": 30000,
            },
        },
    }
    assert "hooks" not in request["json"]
    assert "javascript" not in repr(request["json"]).casefold()
    assert result["text"] == ("Материал " * 1000)[:4000]
    assert result["text_truncated"] is True
    assert result["sources"] == [
        {"kind": "web_page", "url": selected_url, "title": "Материал"}
    ]


def test_reader_reports_missing_when_extended_reader_is_not_configured():
    config = WebResearchConfig("extended", "http://127.0.0.1:8888", "", "")

    result = read_web_page(
        "https://public.example/material",
        max_chars=4000,
        config=config,
        resolver=_public_resolver,
        client_factory=lambda **_kwargs: pytest.fail("HTTP must not run"),
    )

    assert result["status"] == "missing"
    assert result["missing"] == ["Crawl4AI не настроен"]


def test_reader_rejects_private_final_url_without_exposing_page_text():
    client = _RecordingClient(
        {
            "success": True,
            "results": [
                {
                    "url": "http://127.0.0.1/private",
                    "title": "Private",
                    "markdown": {"raw_markdown": "secret"},
                }
            ],
        }
    )
    config = WebResearchConfig(
        "extended",
        "",
        "http://127.0.0.1:11235",
        "secret-token",
    )

    result = read_web_page(
        "https://public.example/material",
        max_chars=4000,
        config=config,
        resolver=_public_resolver,
        client_factory=lambda **_kwargs: client,
    )

    assert result["status"] == "error"
    assert result["text"] == ""
    assert result["sources"] == []
    assert client.calls[0]["headers"] == {"Authorization": "Bearer secret-token"}
