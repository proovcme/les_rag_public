"""Fail-closed web quote collector for KAC.

Search is only a quote discovery adapter.  It never decides that a material is
applicable and never substitutes a product: the caller supplies the exact model-
selected product query.  Results without a strong article/mark identifier, a
visible price, or three distinct supplier domains stay incomplete.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from proxy.services.kac_service import analyze_kac


_PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[\s\u00a0]\d{3})*(?:[,.]\d{1,2})?|\d{2,7}(?:[,.]\d{1,2})?)"
    r"\s*(?:₽|руб(?:\.|лей|ля)?|rub)(?=$|[\s/<,;])",
    re.IGNORECASE,
)


def _key(value: Any) -> str:
    return re.sub(r"[^0-9a-zа-я]", "", str(value or "").casefold().replace("ё", "е"))


def strong_identifiers(query: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-zА-Яа-я][0-9A-Za-zА-Яа-я.\-/]{3,}", str(query or ""))
    out: list[str] = []
    for token in tokens:
        canonical = _key(token)
        if len(canonical) >= 4 and any(char.isdigit() for char in canonical):
            out.append(canonical)
    return sorted(set(out), key=len, reverse=True)


class _DuckResults(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._field = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        values = {key: value or "" for key, value in attrs}
        classes = set(values.get("class", "").split())
        if "result__a" in classes:
            self._current = {"title": "", "snippet": "", "url": values.get("href", "")}
            self._field = "title"
        elif "result__snippet" in classes and self._current is not None:
            self._field = "snippet"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._field == "snippet" and self._current is not None:
            self.results.append(self._current)
            self._current = None
        if tag == "a":
            self._field = ""

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._field:
            self._current[self._field] += data


def _direct_url(raw: str) -> str:
    value = html.unescape(str(raw or ""))
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(target) if target else value
    return value


def _price(text: str) -> float | None:
    match = _PRICE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if 0 < value < 100_000_000 else None


def _unit(value: str) -> str:
    key = re.sub(r"[.\s]", "", str(value or "").casefold())
    aliases = {"штука": "шт", "штук": "шт", "метр": "м", "метров": "м", "упаковка": "уп", "упак": "уп"}
    return aliases.get(key, key)


def _visible_unit(text: str) -> str:
    match = re.search(
        r"(?:/|за\s+|на\s+)(шт\.?|штук[аи]?|м(?:етр(?:а|ов)?)?\.?|уп\.?|упак(?:овк[ау])?)\b",
        str(text or ""),
        re.IGNORECASE,
    )
    return _unit(match.group(1)) if match else ""


def collect_quotes(
    query: str,
    *,
    material: str,
    unit: str,
    vat_pct: float = 22.0,
    min_suppliers: int = 3,
    timeout_sec: float = 12.0,
    html_text: str | None = None,
) -> dict[str, Any]:
    identifiers = strong_identifiers(query)
    if not identifiers:
        return {
            "status": "identifier_required",
            "query": query,
            "quotes": [],
            "kac": analyze_kac([], min_suppliers=min_suppliers),
        }
    if html_text is None:
        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{query} цена купить", "kl": "ru-ru"},
            headers={"User-Agent": "Mozilla/5.0 LES-KAC/1.0"},
            follow_redirects=True,
            timeout=timeout_sec,
        )
        response.raise_for_status()
        html_text = response.text
    parser = _DuckResults()
    parser.feed(html_text)
    by_domain: dict[str, dict[str, Any]] = {}
    strongest = identifiers[0]
    for item in parser.results:
        url = _direct_url(item.get("url") or "")
        domain = urlparse(url).netloc.casefold().removeprefix("www.")
        visible = " ".join((item.get("title") or "", item.get("snippet") or "", url))
        if not domain or strongest not in _key(visible):
            continue
        price = _price(visible)
        if price is None:
            continue
        visible_unit = _visible_unit(visible)
        if not visible_unit or visible_unit != _unit(unit):
            continue
        quote = {
            "material": material,
            "supplier": domain,
            "unit": visible_unit,
            "price": price,
            "price_includes_vat": True,
            "vat_pct": float(vat_pct),
            "vat_basis": "публичная розничная web-цена; НДС нормализован по сценарию",
            "source": url,
            "search_title": item.get("title") or "",
            "search_snippet": item.get("snippet") or "",
        }
        existing = by_domain.get(domain)
        if existing is None or float(quote["price"]) < float(existing["price"]):
            by_domain[domain] = quote
    quotes = list(by_domain.values())
    result = analyze_kac(quotes, min_suppliers=min_suppliers)
    material_result = (result.get("materials") or [{}])[0]
    sufficient = bool(material_result.get("sufficient")) and not bool(material_result.get("unit_mismatch"))
    return {
        "status": "sufficient" if sufficient else "insufficient",
        "query": query,
        "identifiers": identifiers,
        "quotes": quotes,
        "kac": result,
    }
