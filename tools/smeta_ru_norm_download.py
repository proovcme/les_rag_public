"""Download norm archives from https://smeta.ru/download/norm.

The Smeta.RU page exposes direct ``obs.smeta.ru`` ZIP links, so no browser,
token, or session cookie is required for the public archive list.

Typical runs:

    # inspect available archives
    uv run python -m tools.smeta_ru_norm_download --list

    # download latest FSNB-2022 archive into runtime storage
    uv run python -m tools.smeta_ru_norm_download \\
        --runtime-root /Users/ovc/LES --latest fsnb2022 --download

    # download by filename pattern
    uv run python -m tools.smeta_ru_norm_download \\
        --runtime-root /Users/ovc/LES --pattern 'red-2020/gesn_i9' --download

This downloader only fetches archives and writes a manifest/checksum. Parsing
or indexing their contents is a separate, explicit step.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PAGE_URL = "https://smeta.ru/download/norm"
DEFAULT_OUT_REL = Path("storage/downloads/smeta_ru_norm")
DEFAULT_EXTRACT_REL = Path("storage/extracted/smeta_ru_norm")
USER_AGENT = "Mozilla/5.0 LES smeta.ru norm downloader"


@dataclass(frozen=True)
class NormArchive:
    url: str
    filename: str
    category: str
    issue: int | None
    date: str
    size: int | None = None
    content_type: str = ""


def _request(url: str, *, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})


def fetch_page(url: str = PAGE_URL, *, timeout: int = 30) -> str:
    with urllib.request.urlopen(_request(url), timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def extract_zip_links(page_html: str, *, base_url: str = PAGE_URL) -> list[str]:
    links: list[str] = []
    for raw in re.findall(r"""href=["']([^"']+\.zip(?:\?[^"']*)?)["']""", page_html, flags=re.IGNORECASE):
        url = urllib.parse.urljoin(base_url, html.unescape(raw))
        if "obs.smeta.ru" not in urllib.parse.urlparse(url).netloc:
            continue
        if url not in links:
            links.append(url)
    return links


def _archive_category(filename: str, url: str) -> str:
    low = f"{url}/{filename}".lower()
    if "fsnb-2022" in low:
        return "fsnb2022"
    if "/red-2020/" in low:
        return "red2020"
    if "/red-2017/" in low:
        return "red2017"
    if "/red-2014/" in low:
        return "red2014"
    return "other"


def _issue(filename: str) -> int | None:
    m = re.search(r"(?:^|[_-])i(\d{1,3})(?:[_-]|$)", filename, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def _date(filename: str) -> str:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", filename)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else ""


def archive_from_url(url: str) -> NormArchive:
    filename = Path(urllib.parse.urlparse(url).path).name
    return NormArchive(
        url=url,
        filename=filename,
        category=_archive_category(filename, url),
        issue=_issue(filename),
        date=_date(filename),
    )


def discover_archives(*, page_url: str = PAGE_URL, timeout: int = 30) -> list[NormArchive]:
    return [archive_from_url(url) for url in extract_zip_links(fetch_page(page_url, timeout=timeout), base_url=page_url)]


def sort_archives(archives: Iterable[NormArchive]) -> list[NormArchive]:
    return sorted(
        archives,
        key=lambda item: (
            item.category,
            item.issue if item.issue is not None else -1,
            item.date,
            item.filename,
        ),
        reverse=True,
    )


def select_latest(archives: Iterable[NormArchive], category: str) -> NormArchive | None:
    candidates = [item for item in archives if item.category == category]
    return sort_archives(candidates)[0] if candidates else None


def filter_archives(archives: Iterable[NormArchive], pattern: str) -> list[NormArchive]:
    rx = re.compile(pattern, flags=re.IGNORECASE)
    return [item for item in archives if rx.search(item.url) or rx.search(item.filename)]


def head_archive(archive: NormArchive, *, timeout: int = 30) -> NormArchive:
    try:
        with urllib.request.urlopen(_request(archive.url, method="HEAD"), timeout=timeout) as response:
            return NormArchive(
                url=archive.url,
                filename=archive.filename,
                category=archive.category,
                issue=archive.issue,
                date=archive.date,
                size=int(response.headers["content-length"]) if response.headers.get("content-length") else None,
                content_type=response.headers.get("content-type") or "",
            )
    except Exception:
        return archive


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_archive(archive: NormArchive, out_dir: Path, *, timeout: int = 120, overwrite: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / archive.filename
    if target.exists() and not overwrite:
        return {
            "status": "exists",
            "path": target.as_posix(),
            "bytes": target.stat().st_size,
            "sha256": _sha256(target),
            "url": archive.url,
        }
    tmp = target.with_suffix(target.suffix + ".part")
    written = 0
    with urllib.request.urlopen(_request(archive.url), timeout=timeout) as response, tmp.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            written += len(chunk)
    tmp.replace(target)
    return {
        "status": "downloaded",
        "path": target.as_posix(),
        "bytes": written,
        "sha256": _sha256(target),
        "url": archive.url,
    }


def extract_archive(path: Path, extract_root: Path, *, overwrite: bool = False) -> dict:
    target_dir = extract_root / path.stem
    target_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts:
                continue
            target = target_dir / name
            if target.exists() and not overwrite:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
            extracted += 1
    return {"archive": path.as_posix(), "extract_dir": target_dir.as_posix(), "files": extracted}


def write_manifest(out_dir: Path, payload: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "smeta_ru_norm_download_manifest.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> dict:
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    out_dir = runtime_root / args.out
    extract_root = runtime_root / args.extract_to
    archives = discover_archives(page_url=args.page_url, timeout=args.timeout)
    selected: list[NormArchive] = []
    if args.latest:
        item = select_latest(archives, args.latest)
        if not item:
            raise SystemExit(f"нет архива категории {args.latest!r}")
        selected.append(item)
    if args.pattern:
        selected.extend(filter_archives(archives, args.pattern))
    if args.url:
        selected.extend(archive_from_url(url) for url in args.url)
    if not selected:
        selected = sort_archives(archives)
    selected = list({item.url: item for item in selected}.values())
    if args.with_head:
        selected = [head_archive(item, timeout=args.timeout) for item in selected]

    result: dict = {
        "schema": "les.smeta_ru_norm_download.v1",
        "page_url": args.page_url,
        "discovered": len(archives),
        "selected": [asdict(item) for item in selected],
        "downloaded": [],
        "extracted": [],
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if args.download:
        for item in selected:
            result["downloaded"].append(download_archive(item, out_dir, timeout=args.download_timeout, overwrite=args.overwrite))
    if args.extract:
        for item in result["downloaded"]:
            result["extracted"].append(extract_archive(Path(item["path"]), extract_root, overwrite=args.overwrite))
    result["manifest"] = write_manifest(out_dir, result).as_posix()
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smeta.RU norm archive downloader")
    parser.add_argument("--page-url", default=PAGE_URL)
    parser.add_argument("--runtime-root", default=".")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_REL)
    parser.add_argument("--extract-to", type=Path, default=DEFAULT_EXTRACT_REL)
    parser.add_argument("--list", action="store_true", help="print selected archives as a table")
    parser.add_argument("--with-head", action="store_true", help="fetch content-length/content-type for selected archives")
    parser.add_argument("--latest", choices=["fsnb2022", "red2020", "red2017", "red2014", "other"])
    parser.add_argument("--pattern", help="regex over URL/filename")
    parser.add_argument("--url", action="append", default=[], help="direct ZIP URL; repeatable")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--extract", action="store_true", help="extract downloaded ZIPs to --extract-to")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--download-timeout", type=int, default=180)
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run(args)
    if args.list or not args.download:
        for item in result["selected"]:
            size = item.get("size")
            mb = f"{size / 1024 / 1024:.1f} MB" if isinstance(size, int) else "?"
            print(f"{item['category']:8} {str(item.get('issue') or '-'):>3} {item.get('date') or '—'} {mb:>9}  {item['url']}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
