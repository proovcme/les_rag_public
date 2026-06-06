"""Seed Revit model/API sources for the ARTEL family factory."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


DEFAULT_PROXY_URL = "http://127.0.0.1:8050"
DEFAULT_RHINO_MODEL_GUIDE_URL = (
    "https://raw.githubusercontent.com/mcneel/rhino.inside-revit/1.x/"
    "docs/pages/_en/1.0/guides/revit-revit.md"
)
DEFAULT_REVIT_API_SYMBOL_MAP_URL = (
    "https://raw.githubusercontent.com/chuongmep/RevitAPIDocGen/master/RevitAPI2023.json"
)
DEFAULT_URL_TIMEOUT_SEC = 30.0


class _HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._title_depth += 1
        if self._skip_depth:
            return
        if tag in {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5"}:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if self._skip_depth:
            return
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4", "h5"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._title_depth:
            self.title_parts.append(text)
        self.parts.append(text + " ")


def is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def read_source_text(source: str, timeout_sec: float = DEFAULT_URL_TIMEOUT_SEC) -> str:
    if is_url(source):
        req = urllib.request.Request(source, headers={"User-Agent": "LES ARTEL seed tool"})
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=timeout_sec) as response:
                    raw = response.read()
                break
            except (TimeoutError, OSError, urllib.error.URLError) as exc:
                last_error = exc
                if attempt == 3:
                    raise
                time.sleep(attempt * 2)
        else:
            raise RuntimeError(f"Failed to read {source}") from last_error
    else:
        raw = Path(source).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def source_basename(source: str) -> str:
    if is_url(source):
        path = urllib.parse.urlparse(source).path
        return Path(path).name or "source"
    return Path(source).name


def safe_name(value: str, fallback: str = "source") -> str:
    value = re.sub(r"\.[a-zA-Z0-9]+$", "", value)
    value = re.sub(r"[^0-9A-Za-z._-]+", "_", value)
    value = value.strip("._-").lower()
    return value or fallback


def target_dir(runtime_root: Path, name: str) -> Path:
    return runtime_root / "RAG_Content" / "ARTEL" / name


def render_model_guide(source: str, raw_markdown: str) -> str:
    return (
        "# ARTEL Revit Model Guide\n\n"
        "Product: ARTEL\n"
        "Document type: REVIT_MODEL_GUIDE\n"
        "Purpose: Revit data model basis for ARTEL family factory specs, JSON catalogs and validation.\n"
        f"Source: {source}\n\n"
        "## Retrieval Hints\n\n"
        "Revit data model Element Parameter Category Family Type FamilySymbol FamilyInstance "
        "Document Subcategory UniqueId BuiltInCategory shared parameters ARTEL RFA catalog JSON.\n\n"
        "## LES Usage Contract\n\n"
        "Use this source when ARTEL needs to explain or normalize Revit concepts before creating "
        "family specs, catalog JSON, validation reports or extractor mappings. Pair it with "
        "`REVIT_API_REFERENCE`, `REVIT_API_SYMBOL_MAP`, `REVIT_API_SDK_DOC`, `FAMILY_GUIDE` "
        "and `FOP_PROFILE`.\n\n"
        "## Source Notes\n\n"
        + raw_markdown.strip()
        + "\n"
    )


def write_model_guide(source: str, runtime_root: Path) -> Path:
    raw = read_source_text(source)
    name = safe_name(source_basename(source), "revit_model_guide")
    if "rhino" in source.casefold() and "revit-revit" in source.casefold():
        name = "rhino_inside_revit_data_model"
    target = target_dir(runtime_root, "revit_model_guides") / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_model_guide(source, raw), encoding="utf-8")
    return target


def normalize_symbol_rows(source: str) -> list[dict[str, str]]:
    text = read_source_text(source)
    stripped = text.lstrip()
    rows: list[dict[str, Any]]
    if stripped.startswith("[") or stripped.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                rows = data["items"]
            elif isinstance(data.get("symbols"), list):
                rows = data["symbols"]
            else:
                rows = [data]
        else:
            rows = data
    else:
        reader = csv.DictReader(text.splitlines())
        rows = list(reader)

    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        namespace = str(row.get("Namespace") or row.get("NameSpace") or row.get("namespace") or "").strip()
        item = {
            "title": str(row.get("Title") or row.get("title") or "").strip(),
            "keywords": str(row.get("Keywords") or row.get("keywords") or "").strip(),
            "api_name": str(row.get("APIName") or row.get("ApiName") or row.get("api_name") or "").strip(),
            "description": str(row.get("Description") or row.get("description") or "").strip(),
            "namespace": namespace,
            "guid": str(row.get("Guid") or row.get("GUID") or row.get("guid") or "").strip(),
            "symbol_type": str(row.get("Type") or row.get("type") or "").strip(),
        }
        if any(item.values()):
            normalized.append(item)
    return normalized


def render_symbol_map(source: str, rows: list[dict[str, str]], max_symbols: int = 0) -> str:
    selected = rows if max_symbols <= 0 else rows[:max_symbols]
    namespaces = sorted({row["namespace"] for row in selected if row.get("namespace")})
    lines = [
        "# ARTEL Revit API Symbol Map",
        "",
        "Product: ARTEL",
        "Document type: REVIT_API_SYMBOL_MAP",
        "Schema: artel.revit_api_symbol_map.v1",
        "Purpose: local lookup map for Revit API classes, methods, properties, namespaces and documentation links.",
        f"Source: {source}",
        f"Symbol count: {len(rows)}",
        f"Indexed symbol count: {len(selected)}",
        "",
        "## Retrieval Hints",
        "",
        "Revit API symbol map namespace class method property event enum GUID link RevitAPIDocs",
        "Autodesk.Revit.DB Autodesk.Revit.UI FamilyManager FamilyParameter FamilyType",
        "FilteredElementCollector Transaction Element Parameter BuiltInCategory BuiltInParameter.",
        "",
        "## LES Usage Contract",
        "",
        "Use this source when ARTEL needs to find the exact Revit API symbol name, namespace,",
        "member type or online documentation id. Pair with `REVIT_API_SDK_DOC` for detailed",
        "member descriptions and with `REVIT_API_REFERENCE` for implementation patterns.",
        "",
        "## Namespaces",
    ]
    for namespace in namespaces[:400]:
        lines.append(f"- {namespace}")
    if len(namespaces) > 400:
        lines.append(f"- ... {len(namespaces) - 400} more namespaces")

    lines.extend(["", "## Symbols"])
    for row in selected:
        title = row.get("title") or row.get("api_name") or "Unnamed"
        details = []
        if row.get("api_name"):
            details.append(f"api={row['api_name']}")
        if row.get("namespace"):
            details.append(f"namespace={row['namespace']}")
        if row.get("symbol_type"):
            details.append(f"type={row['symbol_type']}")
        if row.get("guid"):
            details.append(f"guid={row['guid']}")
        line = f"- {title}"
        if details:
            line += " (" + "; ".join(details) + ")"
        description = " ".join((row.get("keywords") or "", row.get("description") or "")).strip()
        if description:
            line += f" - {description}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def write_symbol_map(source: str, runtime_root: Path, max_symbols: int = 0) -> Path:
    rows = normalize_symbol_rows(source)
    name = safe_name(source_basename(source), "revit_api_symbol_map")
    target = target_dir(runtime_root, "revit_api_symbol_map") / f"{name}_symbol_map.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_symbol_map(source, rows, max_symbols=max_symbols), encoding="utf-8")
    return target


def html_to_markdown(source_name: str, html: str) -> tuple[str, str]:
    parser = _HTMLToText()
    parser.feed(html)
    title = " ".join(parser.title_parts).strip() or source_name
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return title, text.strip()


def render_sdk_doc(source: str, title: str, body: str) -> str:
    return (
        "# ARTEL Revit API SDK Doc\n\n"
        "Product: ARTEL\n"
        "Document type: REVIT_API_SDK_DOC\n"
        "Source kind: Revit SDK CHM/HTML\n"
        f"Source: {source}\n"
        f"Title: {title}\n\n"
        "## Retrieval Hints\n\n"
        f"Revit API SDK documentation {title} Autodesk.Revit.DB Autodesk.Revit.UI ARTEL RFA family factory.\n\n"
        "## SDK Content\n\n"
        f"## {title}\n\n{body.strip()}\n"
    )


def write_sdk_html_file(path: Path, runtime_root: Path, source_root: Path | None = None) -> Path:
    html = path.read_text(encoding="utf-8", errors="ignore")
    rel = path.relative_to(source_root) if source_root else Path(path.name)
    title, body = html_to_markdown(path.name, html)
    safe = safe_name("_".join(rel.with_suffix("").parts), safe_name(path.name, "sdk_doc"))
    target = target_dir(runtime_root, "revit_api_sdk_docs") / f"{safe}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_sdk_doc(str(path), title, body), encoding="utf-8")
    return target


def write_sdk_html_url(source: str, runtime_root: Path, timeout_sec: float = DEFAULT_URL_TIMEOUT_SEC) -> Path:
    html = read_source_text(source, timeout_sec=timeout_sec)
    title, body = html_to_markdown(source_basename(source), html)
    safe = safe_name(source_basename(source), "sdk_url")
    target = target_dir(runtime_root, "revit_api_sdk_docs") / f"{safe}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_sdk_doc(source, title, body), encoding="utf-8")
    return target


def write_sdk_html_dir(html_dir: Path, runtime_root: Path, max_pages: int = 0) -> list[Path]:
    if not html_dir.is_dir():
        raise FileNotFoundError(f"SDK HTML directory not found: {html_dir}")
    html_files = sorted(
        path
        for path in html_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".htm", ".html"}
    )
    if max_pages > 0:
        html_files = html_files[:max_pages]
    return [write_sdk_html_file(path, runtime_root, source_root=html_dir) for path in html_files]


def extract_chm(chm_path: Path) -> Path:
    if not chm_path.is_file():
        raise FileNotFoundError(f"CHM file not found: {chm_path}")
    out_dir = Path(tempfile.mkdtemp(prefix="artel-revit-chm-"))
    extractors = [
        ("7zz", ["7zz", "x", str(chm_path), f"-o{out_dir}", "-y"]),
        ("7z", ["7z", "x", str(chm_path), f"-o{out_dir}", "-y"]),
        ("unar", ["unar", "-o", str(out_dir), str(chm_path)]),
        ("extract_chmLib", ["extract_chmLib", str(chm_path), str(out_dir)]),
    ]
    for binary, command in extractors:
        if not shutil.which(binary):
            continue
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return out_dir
    raise RuntimeError(
        "No CHM extractor found. Install 7zip/unar/chmlib or pass --sdk-html-dir with extracted RevitAPI.chm HTML."
    )


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None, api_key: str = "") -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {exc.code}: {body}") from exc


def sync_artel(proxy_url: str, api_key: str = "") -> dict[str, Any]:
    return _request_json("POST", f"{proxy_url.rstrip('/')}/api/rag/sync/ARTEL", api_key=api_key)


def search_artel(proxy_url: str, query: str, api_key: str = "") -> dict[str, Any]:
    return _request_json(
        "POST",
        f"{proxy_url.rstrip('/')}/api/search",
        {"query": query, "dataset_filter": "ARTEL", "top_k": 12, "include_trace": True},
        api_key=api_key,
    )


def wait_for_search(proxy_url: str, timeout_sec: float, poll_sec: float, api_key: str = "") -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    query = "ARTEL Revit family factory REVIT_API_SYMBOL_MAP REVIT_MODEL_GUIDE FamilyManager Element Category"
    expected = ("revit_model_guides/", "revit_api_symbol_map/", "revit_api_sdk_docs/")
    while time.monotonic() <= deadline:
        last = search_artel(proxy_url, query, api_key=api_key)
        chunks = last.get("chunks") or []
        if any(any(prefix in str(chunk.get("doc_name", "")) for prefix in expected) for chunk in chunks):
            return last
        time.sleep(poll_sec)
    raise RuntimeError(f"ARTEL factory search did not return factory sources after {timeout_sec:.0f}s: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ARTEL Revit family factory knowledge sources into LES.")
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd(), help="LES runtime root that owns RAG_Content.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="LES proxy URL.")
    parser.add_argument("--api-key", default=os.getenv("LES_ADMIN_KEY", ""), help="LES admin API key; localhost trusted access can omit it.")
    parser.add_argument("--model-guide", action="append", default=[], help="Markdown URL/path with Revit data model guide.")
    parser.add_argument("--symbol-map", action="append", default=[], help="JSON/CSV URL/path with Revit API symbol map.")
    parser.add_argument("--sdk-html-dir", type=Path, action="append", default=[], help="Directory with extracted Revit API SDK HTML files.")
    parser.add_argument("--sdk-url", action="append", default=[], help="Revit API SDK/RevitAPIDocs/RVTDocs HTML URL to index as REVIT_API_SDK_DOC.")
    parser.add_argument("--url-timeout-sec", type=float, default=DEFAULT_URL_TIMEOUT_SEC, help="Per-attempt timeout for URL reads.")
    parser.add_argument("--allow-fetch-errors", action="store_true", help="Continue when an --sdk-url cannot be fetched.")
    parser.add_argument("--chm", type=Path, action="append", default=[], help="RevitAPI.chm path; requires 7z/7zz/unar/chmlib.")
    parser.add_argument("--seed-defaults", action="store_true", help="Seed public Rhino model guide and RevitAPIDocGen 2023 symbol map.")
    parser.add_argument("--max-symbols", type=int, default=0, help="Limit symbol entries; 0 means all.")
    parser.add_argument("--max-sdk-pages", type=int, default=0, help="Limit SDK HTML pages; 0 means all.")
    parser.add_argument("--no-sync", action="store_true", help="Only write files; do not call LES sync.")
    parser.add_argument("--verify-search", action="store_true", help="Poll /api/search until factory chunks are returned.")
    parser.add_argument("--timeout-sec", type=float, default=180.0)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    args = parser.parse_args()

    model_guides = list(args.model_guide)
    symbol_maps = list(args.symbol_map)
    if args.seed_defaults or not (model_guides or symbol_maps or args.sdk_html_dir or args.sdk_url or args.chm):
        model_guides.append(DEFAULT_RHINO_MODEL_GUIDE_URL)
        symbol_maps.append(DEFAULT_REVIT_API_SYMBOL_MAP_URL)

    written: list[Path] = []
    for source in model_guides:
        target = write_model_guide(source, args.runtime_root)
        written.append(target)
        print(f"written={target}")
    for source in symbol_maps:
        target = write_symbol_map(source, args.runtime_root, max_symbols=args.max_symbols)
        written.append(target)
        print(f"written={target}")
    for html_dir in args.sdk_html_dir:
        for target in write_sdk_html_dir(html_dir, args.runtime_root, max_pages=args.max_sdk_pages):
            written.append(target)
        print(f"sdk_html_dir={html_dir} written_count={len(written)}")
    for source in args.sdk_url:
        try:
            target = write_sdk_html_url(source, args.runtime_root, timeout_sec=args.url_timeout_sec)
        except Exception as exc:
            if not args.allow_fetch_errors:
                raise
            print(f"fetch_error={source} error={exc}", flush=True)
            continue
        written.append(target)
        print(f"written={target}", flush=True)
    for chm_path in args.chm:
        extracted = extract_chm(chm_path)
        try:
            targets = write_sdk_html_dir(extracted, args.runtime_root, max_pages=args.max_sdk_pages)
            written.extend(targets)
            print(f"chm={chm_path} extracted={extracted} written_count={len(targets)}")
        finally:
            shutil.rmtree(extracted, ignore_errors=True)

    if not args.no_sync:
        sync_result = sync_artel(args.proxy_url, api_key=args.api_key)
        print("sync=" + json.dumps(sync_result, ensure_ascii=False, sort_keys=True))

    if args.verify_search:
        search_result = wait_for_search(
            args.proxy_url,
            timeout_sec=args.timeout_sec,
            poll_sec=args.poll_sec,
            api_key=args.api_key,
        )
        print("search_count=" + str(search_result.get("count", 0)))
        first = (search_result.get("chunks") or [{}])[0]
        print("first_doc=" + str(first.get("doc_name", "")))
        print("first_doc_type=" + str(first.get("doc_type", "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
