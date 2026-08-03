"""Bounded public web search for the explicit read-only Agent mode."""

from __future__ import annotations

import html
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from backend.http_client_policy import trust_env_for_url


_SEARCH_URL = "https://html.duckduckgo.com/html/"


class _DuckResults(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._field = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            if self._current is not None:
                self.results.append(self._current)
            self._current = {"title": "", "snippet": "", "url": values.get("href", "")}
            self._field = "title"
        elif self._current is not None and "result__snippet" in classes:
            self._field = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag in {"a", "div"}:
            self._field = ""

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._field:
            self._current[self._field] += data

    def close(self) -> None:
        super().close()
        if self._current is not None:
            self.results.append(self._current)
            self._current = None


def _direct_url(raw: str) -> str:
    value = html.unescape(str(raw or "").strip())
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.netloc.casefold().endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        value = unquote(target) if target else ""
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def parse_search_results(html_text: str, *, limit: int = 8) -> list[dict[str, str]]:
    parser = _DuckResults()
    parser.feed(str(html_text or ""))
    parser.close()
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in parser.results:
        url = _direct_url(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": " ".join((item.get("title") or "").split()),
                "snippet": " ".join((item.get("snippet") or "").split()),
                "url": url,
                "domain": urlparse(url).netloc.casefold().removeprefix("www."),
            }
        )
        if len(results) >= max(1, min(12, int(limit))):
            break
    return results


def search_web(query: str, *, limit: int = 8, timeout_sec: float = 12.0) -> dict[str, Any]:
    normalized = " ".join(str(query or "").split())
    if len(normalized) < 3:
        return {"status": "missing", "query": normalized, "results": [], "missing": ["query"]}
    normalized = normalized[:500]
    with httpx.Client(
        trust_env=trust_env_for_url(_SEARCH_URL),
        follow_redirects=True,
        timeout=max(2.0, min(20.0, float(timeout_sec))),
        headers={"User-Agent": "Mozilla/5.0 LES-Agent/1.0"},
    ) as client:
        response = client.get(_SEARCH_URL, params={"q": normalized, "kl": "ru-ru"})
        response.raise_for_status()
    results = parse_search_results(response.text, limit=limit)
    return {
        "status": "ok" if results else "missing",
        "query": normalized,
        "results": results,
        "missing": [] if results else ["web search returned no results"],
    }
