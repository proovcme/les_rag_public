"""Immutable request-scoped configuration for selectable public web research."""

from __future__ import annotations

from dataclasses import dataclass
import os
from collections.abc import Callable
from typing import Any, Literal, Mapping, cast
from urllib.parse import urlparse

import httpx

from backend.http_client_policy import trust_env_for_url


@dataclass(frozen=True)
class WebResearchConfig:
    mode: Literal["simple", "extended"]
    searxng_url: str
    crawl4ai_url: str
    crawl4ai_token: str


def _normalized_service_url(raw: object) -> str:
    value = str(raw or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def capture_web_research_config(
    environ: Mapping[str, str] | None = None,
) -> WebResearchConfig:
    source = os.environ if environ is None else environ
    mode = str(source.get("LES_WEB_SEARCH_MODE", "simple")).strip().casefold()
    if mode not in {"simple", "extended"}:
        mode = "simple"
    return WebResearchConfig(
        mode=cast(Literal["simple", "extended"], mode),
        searxng_url=_normalized_service_url(source.get("LES_SEARXNG_URL", "")),
        crawl4ai_url=_normalized_service_url(source.get("LES_CRAWL4AI_URL", "")),
        crawl4ai_token=str(source.get("LES_CRAWL4AI_TOKEN", "")).strip(),
    )


def public_web_research_config(config: WebResearchConfig) -> dict[str, object]:
    return {
        "mode": config.mode,
        "searxng_url": config.searxng_url,
        "crawl4ai_url": config.crawl4ai_url,
        "crawl4ai_token_set": bool(config.crawl4ai_token),
        "restart_required": False,
    }


def web_research_status(config: WebResearchConfig) -> dict[str, Any]:
    """Describe configured providers without contacting either service."""
    return {
        "config": public_web_research_config(config),
        "services": {
            "simple": {"status": "available", "provider": "duckduckgo"},
            "searxng": {
                "status": "configured" if config.searxng_url else "missing",
                "url": config.searxng_url,
            },
            "crawl4ai": {
                "status": "configured" if config.crawl4ai_url else "missing",
                "url": config.crawl4ai_url,
            },
        },
    }


def _probe_get(
    url: str,
    *,
    request_kwargs: Mapping[str, Any],
    client_factory: Callable[..., Any],
) -> dict[str, str]:
    if not url:
        return {"status": "missing"}
    try:
        with client_factory(
            trust_env=trust_env_for_url(url),
            follow_redirects=False,
            timeout=3.0,
            headers={"User-Agent": "LES-Agent/1.0"},
        ) as client:
            response = client.get(url, **dict(request_kwargs))
            response.raise_for_status()
        return {"status": "ok"}
    except (httpx.HTTPError, OSError, ValueError, TypeError) as exc:
        return {"status": "error", "reason": type(exc).__name__}


def probe_web_research_services(
    config: WebResearchConfig,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Probe provider health only; never submit a URL to Crawl4AI."""
    make_client = client_factory or httpx.Client
    payload = web_research_status(config)
    payload["services"]["searxng"] = _probe_get(
        f"{config.searxng_url}/search" if config.searxng_url else "",
        request_kwargs={
            "params": {"q": "LES health", "format": "json", "language": "ru"}
        },
        client_factory=make_client,
    )
    crawl_headers = (
        {"Authorization": f"Bearer {config.crawl4ai_token}"}
        if config.crawl4ai_token
        else {}
    )
    payload["services"]["crawl4ai"] = _probe_get(
        f"{config.crawl4ai_url}/health" if config.crawl4ai_url else "",
        request_kwargs={"headers": crawl_headers},
        client_factory=make_client,
    )
    return payload
