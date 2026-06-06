"""Seed Revit shared-parameter/FOP profiles into LES ARTEL_Index."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_PROXY_URL = "http://127.0.0.1:8050"


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1251", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_shared_parameters(text: str) -> dict[str, Any]:
    groups: dict[str, str] = {}
    params: list[dict[str, str]] = []
    section = ""
    headers: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("*"):
            parts = line.split()
            section = parts[0].lstrip("*").upper()
            headers = parts[1:]
            continue
        parts = line.split("\t")
        if not parts:
            continue
        if section == "GROUP" and len(parts) >= 3 and parts[0] == "GROUP":
            groups[parts[1]] = parts[2]
        elif section == "PARAM" and parts[0] == "PARAM":
            row = {headers[index]: parts[index + 1] for index in range(min(len(headers), len(parts) - 1))}
            row["GROUP_NAME"] = groups.get(row.get("GROUP", ""), row.get("GROUP", ""))
            params.append(row)
    return {"groups": groups, "params": params}


def _safe_profile_id(value: str) -> str:
    result = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return result.strip("._-") or "fop_profile"


def render_markdown(path: Path, profile_id: str, parsed: dict[str, Any]) -> str:
    groups: dict[str, str] = parsed["groups"]
    params: list[dict[str, str]] = parsed["params"]
    by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for param in params:
        by_group[param.get("GROUP_NAME", "")].append(param)

    lines = [
        "# ARTEL FOP Shared Parameter Profile",
        "",
        f"Profile ID: {profile_id}",
        f"Source file: {path.name}",
        "Product: ARTEL",
        "Document type: FOP_PROFILE",
        f"Group count: {len(groups)}",
        f"Parameter count: {len(params)}",
        "",
        "## Retrieval Hints",
        "ФОП shared parameters Revit GUID ADSK_Наименование ADSK_Код изделия ADSK_Марка ADSK_Примечание ARTEL RFA",
        "",
        "## Groups",
    ]
    for group_id, group_name in sorted(groups.items(), key=lambda item: (item[1], item[0])):
        lines.append(f"- {group_id}: {group_name}")

    lines.extend(["", "## Parameters By Group"])
    for group_name in sorted(by_group):
        lines.extend(["", f"### {group_name or 'Без группы'}"])
        for param in sorted(by_group[group_name], key=lambda item: item.get("NAME", "")):
            name = param.get("NAME", "")
            guid = param.get("GUID", "")
            datatype = param.get("DATATYPE", "")
            datacategory = param.get("DATACATEGORY", "")
            visible = param.get("VISIBLE", "")
            usermod = param.get("USERMODIFIABLE", "")
            description = param.get("DESCRIPTION", "")
            details = [
                f"GUID={guid}" if guid else "",
                f"type={datatype}" if datatype else "",
                f"category={datacategory}" if datacategory else "",
                f"visible={visible}" if visible else "",
                f"user_modifiable={usermod}" if usermod else "",
            ]
            suffix = "; ".join(item for item in details if item)
            line = f"- {name}"
            if suffix:
                line += f" ({suffix})"
            if description:
                line += f" - {description}"
            lines.append(line)
    lines.append("")
    return "\n".join(lines)


def write_projection(fop_path: Path, runtime_root: Path, profile_id: str | None = None) -> Path:
    profile = _safe_profile_id(profile_id or fop_path.stem)
    parsed = parse_shared_parameters(read_text(fop_path))
    target = runtime_root / "RAG_Content" / "ARTEL" / "fop_profiles" / f"{profile}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(fop_path, profile, parsed), encoding="utf-8")
    return target


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
        {"query": query, "dataset_filter": "ARTEL", "top_k": 5, "include_trace": True},
        api_key=api_key,
    )


def wait_for_search(proxy_url: str, query: str, timeout_sec: float, poll_sec: float, api_key: str = "") -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        last = search_artel(proxy_url, query, api_key=api_key)
        chunks = last.get("chunks") or []
        if any("fop_profiles/" in str(chunk.get("doc_name", "")) for chunk in chunks):
            return last
        time.sleep(poll_sec)
    raise RuntimeError(f"ARTEL FOP search did not return fop_profiles after {timeout_sec:.0f}s: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Revit FOP/shared-parameter profile into LES ARTEL_Index.")
    parser.add_argument("--fop", type=Path, action="append", required=True, help="Path to Revit shared parameters TXT.")
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd(), help="LES runtime root that owns RAG_Content.")
    parser.add_argument("--proxy-url", default=DEFAULT_PROXY_URL, help="LES proxy URL.")
    parser.add_argument("--api-key", default=os.getenv("LES_ADMIN_KEY", ""), help="LES admin API key; localhost trusted access can omit it.")
    parser.add_argument("--no-sync", action="store_true", help="Only write projections; do not call LES sync.")
    parser.add_argument("--verify-search", action="store_true", help="Poll /api/search until a FOP profile chunk is returned.")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    args = parser.parse_args()

    written = []
    for fop_path in args.fop:
        target = write_projection(fop_path, args.runtime_root)
        written.append(target)
        print(f"projection={target}")

    if not args.no_sync:
        sync_result = sync_artel(args.proxy_url, api_key=args.api_key)
        print("sync=" + json.dumps(sync_result, ensure_ascii=False, sort_keys=True))

    if args.verify_search:
        query = "ФОП shared parameters ADSK_Наименование ADSK_Код изделия GUID Revit ARTEL"
        search_result = wait_for_search(
            args.proxy_url,
            query,
            timeout_sec=args.timeout_sec,
            poll_sec=args.poll_sec,
            api_key=args.api_key,
        )
        print("search_count=" + str(search_result.get("count", 0)))
        first = (search_result.get("chunks") or [{}])[0]
        print("first_doc=" + str(first.get("doc_name", "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
