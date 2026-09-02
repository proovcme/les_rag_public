"""Bounded Crawl4AI reader for exactly one model-selected public URL."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import ipaddress
import json
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.http_client_policy import trust_env_for_url
from proxy.services.web_research_config_service import WebResearchConfig


_MAX_RESULT_CHARS = 4_000
_MAX_RESPONSE_BYTES = 1_000_000


class UnsafeWebUrl(ValueError):
    pass


def validate_public_web_url(
    raw_url: str,
    *,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
) -> str:
    value = str(raw_url or "").strip()
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise UnsafeWebUrl("WEB_URL_NOT_PUBLIC")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeWebUrl("WEB_URL_NOT_PUBLIC") from exc
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise UnsafeWebUrl("WEB_URL_NOT_PUBLIC")
    try:
        addresses = resolver(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeWebUrl("WEB_URL_RESOLUTION_FAILED") from exc
    if not addresses:
        raise UnsafeWebUrl("WEB_URL_RESOLUTION_FAILED")
    for address in addresses:
        sockaddr = address[4]
        if not sockaddr:
            raise UnsafeWebUrl("WEB_URL_RESOLUTION_FAILED")
        try:
            resolved = ipaddress.ip_address(str(sockaddr[0]))
        except ValueError as exc:
            raise UnsafeWebUrl("WEB_URL_RESOLUTION_FAILED") from exc
        if not resolved.is_global:
            raise UnsafeWebUrl("WEB_URL_NOT_PUBLIC")
    return value


def _empty_result(
    status: str,
    requested_url: str,
    *,
    missing: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "requested_url": requested_url,
        "final_url": "",
        "title": "",
        "text": "",
        "text_truncated": False,
        "retrieved_at": "",
        "sources": [],
        "missing": list(missing or []),
        "warnings": list(warnings or []),
    }


def _read_response_bytes(response: Any) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > _MAX_RESPONSE_BYTES:
            raise ValueError("CRAWL4AI_RESPONSE_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def _page_text(item: Mapping[str, Any]) -> str:
    markdown = item.get("markdown")
    if isinstance(markdown, Mapping):
        return str(markdown.get("raw_markdown") or markdown.get("fit_markdown") or "")
    if isinstance(markdown, str):
        return markdown
    return str(item.get("text") or item.get("cleaned_html") or "")


def read_web_page(
    url: str,
    *,
    max_chars: int = _MAX_RESULT_CHARS,
    config: WebResearchConfig,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    requested_url = str(url or "").strip()
    if config.mode != "extended":
        return _empty_result(
            "missing",
            requested_url,
            missing=["Чтение веб-страниц доступно только в расширенном режиме"],
        )
    if not config.crawl4ai_url:
        return _empty_result(
            "missing",
            requested_url,
            missing=["Crawl4AI не настроен"],
        )
    try:
        selected_url = validate_public_web_url(requested_url, resolver=resolver)
    except UnsafeWebUrl:
        return _empty_result(
            "error",
            requested_url,
            warnings=["Адрес не является безопасным публичным URL"],
        )
    result_limit = max(1, min(_MAX_RESULT_CHARS, int(max_chars)))
    endpoint = f"{config.crawl4ai_url}/crawl"
    payload = {
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
    headers = (
        {"Authorization": f"Bearer {config.crawl4ai_token}"}
        if config.crawl4ai_token
        else {}
    )
    make_client = client_factory or httpx.Client
    try:
        with make_client(
            trust_env=trust_env_for_url(endpoint),
            follow_redirects=False,
            timeout=35.0,
            headers={"User-Agent": "LES-Agent/1.0"},
        ) as client:
            with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                response.raise_for_status()
                raw = _read_response_bytes(response)
        response_payload = json.loads(raw)
        if not isinstance(response_payload, Mapping) or response_payload.get("success") is not True:
            raise ValueError("CRAWL4AI_RESPONSE_INVALID")
        results = response_payload.get("results")
        if not isinstance(results, list) or not results or not isinstance(results[0], Mapping):
            raise ValueError("CRAWL4AI_RESPONSE_INVALID")
        item = results[0]
        final_url = validate_public_web_url(
            str(item.get("url") or selected_url),
            resolver=resolver,
        )
        full_text = _page_text(item)
        if not full_text:
            return _empty_result(
                "missing",
                requested_url,
                missing=["Страница не вернула читаемый текст"],
            )
        metadata = item.get("metadata")
        title = str(item.get("title") or "")
        if not title and isinstance(metadata, Mapping):
            title = str(metadata.get("title") or "")
        text = full_text[:result_limit]
        retrieved_at = datetime.now(timezone.utc).isoformat()
        return {
            "status": "ok",
            "requested_url": requested_url,
            "final_url": final_url,
            "title": title,
            "text": text,
            "text_truncated": len(full_text) > result_limit,
            "retrieved_at": retrieved_at,
            "sources": [{"kind": "web_page", "url": final_url, "title": title}],
            "missing": [],
            "warnings": [],
        }
    except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError, ValueError, UnsafeWebUrl):
        return _empty_result(
            "error",
            requested_url,
            warnings=["Crawl4AI не смог безопасно прочитать страницу"],
        )
