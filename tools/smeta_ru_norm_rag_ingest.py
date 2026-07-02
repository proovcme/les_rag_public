"""Download Smeta.RU norm archives one by one and project them into LES RAG.

The worker is intentionally conservative:

* ZIPs stay in ``storage/downloads/smeta_ru_norm``.
* Extracted source artifacts stay in ``storage/extracted/smeta_ru_norm``.
* RAG receives markdown/text projections and supported source documents under
  ``RAG_Content/TABLE_SMETA/SMETA_RU_NORM``.
* After each new archive package is written, the worker can call
  ``/api/rag/sync-smart`` so LES registers/parses that batch before moving on.

This is a source-ingestion layer. It does not mark norm data as priced_final and
does not choose estimate work items or normative applicability.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from backend.smart_index import SUPPORTED_SUFFIXES
from tools import smeta_ru_norm_download as dl


DEFAULT_RAG_REL = Path("RAG_Content/TABLE_SMETA/SMETA_RU_NORM")
DEFAULT_STATE_REL = Path("storage/state/smeta_ru_norm_rag_ingest_state.json")
DEFAULT_DOWNLOAD_REL = dl.DEFAULT_OUT_REL
DEFAULT_EXTRACT_REL = dl.DEFAULT_EXTRACT_REL
GROUP_NAME = "TABLE_SMETA"

CATEGORY_LABELS = {
    "fsnb2022": "ФСНБ-2022: ГЭСН/ГЭСНм/ГЭСНп/ГЭСНр и федеральные базовые цены 2022",
    "red2020": "Редакция 2020: ГЭСН/ФЕР и ресурсные сборники 2020",
    "red2017": "Редакция 2017: архивная нормативная база",
    "red2014": "Редакция 2014: архивная нормативная база",
    "other": "Прочие архивы Smeta.RU norm",
}
TEXT_PROJECTION_SUFFIXES = {".txt", ".csv", ".xml", ".json", ".html", ".htm", ".ini", ".cfg"}
NESTED_ARCHIVE_SUFFIXES = {".vnbx"}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _slug(value: str, *, fallback: str = "item") -> str:
    out = re.sub(r"[^0-9A-Za-zА-Яа-я._-]+", "_", value.strip())
    out = re.sub(r"_+", "_", out).strip("._-")
    return (out or fallback)[:160]


def _category_dataset_name(category: str) -> str:
    return f"SMETA_RU_NORM_{_slug(category, fallback='other').upper()}_Index"


def _archive_key(archive: dl.NormArchive) -> str:
    return archive.url


def _select_archives(args: argparse.Namespace) -> list[dl.NormArchive]:
    archives = dl.discover_archives(page_url=args.page_url, timeout=args.timeout)
    selected: list[dl.NormArchive] = []
    categories = args.category or ["fsnb2022", "red2020", "red2017", "red2014"]
    if args.latest_per_category:
        for category in categories:
            item = dl.select_latest(archives, category)
            if item:
                selected.append(item)
    if args.latest:
        for category in args.latest:
            item = dl.select_latest(archives, category)
            if not item:
                raise SystemExit(f"нет архива категории {category!r}")
            selected.append(item)
    for pattern in args.pattern or []:
        selected.extend(dl.filter_archives(archives, pattern))
    selected.extend(dl.archive_from_url(url) for url in args.url or [])
    if args.all:
        selected.extend(dl.sort_archives(archives))
    if not selected:
        selected = [item for category in categories if (item := dl.select_latest(archives, category))]
    dedup = list({item.url: item for item in selected}.values())
    if args.with_head:
        dedup = [dl.head_archive(item, timeout=args.timeout) for item in dedup]
    dedup = dl.sort_archives(dedup)
    return dedup[: args.max_archives] if args.max_archives else dedup


def _iter_files(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*")) if path.is_file()]


def _copy_supported_sources(
    *,
    extract_dir: Path,
    rag_archive_dir: Path,
    max_files: int,
    max_file_mb: float,
) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    source_dir = rag_archive_dir / "source_files"
    max_bytes = int(max_file_mb * 1024 * 1024)
    for path in _iter_files(extract_dir):
        if len(copied) >= max_files:
            break
        suffix = path.suffix.lower()
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if suffix not in SUPPORTED_SUFFIXES or size <= 0 or size > max_bytes:
            continue
        rel = path.relative_to(extract_dir)
        target = source_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append({"source": rel.as_posix(), "rag_path": target.as_posix(), "bytes": size, "suffix": suffix})
    return copied


def _project_text_files(
    *,
    extract_dir: Path,
    rag_archive_dir: Path,
    max_files: int,
    max_file_mb: float,
    max_chars: int,
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    target_root = rag_archive_dir / "projected_text"
    max_bytes = int(max_file_mb * 1024 * 1024)
    for path in _iter_files(extract_dir):
        if len(projected) >= max_files:
            break
        suffix = path.suffix.lower()
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if suffix not in TEXT_PROJECTION_SUFFIXES or size <= 0 or size > max_bytes:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if not text.strip():
            continue
        rel = path.relative_to(extract_dir)
        target = target_root / rel.with_suffix(rel.suffix + ".md")
        body = [
            "---",
            "les_source: smeta_ru_norm_archive_text_projection",
            f"source_relative_path: {rel.as_posix()}",
            f"source_suffix: {suffix}",
            f"source_bytes: {size}",
            "---",
            "",
            f"# Smeta.RU norm text projection: {rel.as_posix()}",
            "",
            "Это текстовая проекция файла из ZIP-архива Smeta.RU norm для поиска по RAG.",
            "Она является evidence/navigation, а не финальным расчётным trace.",
            "",
            "```text",
            text[:max_chars],
            "```",
        ]
        _write(target, "\n".join(body))
        projected.append({"source": rel.as_posix(), "rag_path": target.as_posix(), "bytes": size, "suffix": suffix})
    return projected


def _project_nested_archives(
    *,
    extract_dir: Path,
    rag_archive_dir: Path,
    max_archives: int,
    max_files_per_archive: int,
    max_file_mb: float,
    max_chars: int,
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    target_root = rag_archive_dir / "projected_nested"
    max_bytes = int(max_file_mb * 1024 * 1024)
    nested_paths = [
        path for path in _iter_files(extract_dir)
        if path.suffix.lower() in NESTED_ARCHIVE_SUFFIXES and zipfile.is_zipfile(path)
    ]
    for archive_path in nested_paths[:max_archives]:
        rel_archive = archive_path.relative_to(extract_dir)
        archive_slug = _slug(rel_archive.as_posix(), fallback="nested_archive")
        with zipfile.ZipFile(archive_path) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            suffixes = Counter((Path(info.filename).suffix.lower() or "<no_suffix>") for info in infos)
            inventory = {
                "source_archive": rel_archive.as_posix(),
                "files": len(infos),
                "bytes": sum(info.file_size for info in infos),
                "suffixes": dict(sorted(suffixes.items())),
                "sample": [info.filename for info in infos[:80]],
            }
            inventory_target = target_root / archive_slug / "00_nested_archive_inventory.md"
            _write(
                inventory_target,
                "\n".join(
                    [
                        f"# Nested Smeta.RU archive inventory: {rel_archive.as_posix()}",
                        "",
                        "Это инвентарь вложенного архива из пакета Smeta.RU norm.",
                        "Карточка является RAG/evidence для модели; расчётный trace строится отдельно.",
                        "",
                        "```json",
                        _json(inventory),
                        "```",
                        "",
                    ]
                ),
            )
            projected.append(
                {
                    "source": rel_archive.as_posix(),
                    "inner": "__inventory__",
                    "rag_path": inventory_target.as_posix(),
                    "bytes": archive_path.stat().st_size,
                    "suffix": archive_path.suffix.lower(),
                }
            )
            written_inner = 0
            for info in infos:
                if written_inner >= max_files_per_archive:
                    break
                inner_suffix = Path(info.filename).suffix.lower()
                if inner_suffix not in TEXT_PROJECTION_SUFFIXES:
                    continue
                if info.file_size <= 0 or info.file_size > max_bytes:
                    continue
                try:
                    raw = zf.read(info)
                except Exception:
                    continue
                text = raw.decode("utf-8", "replace")
                if not text.strip():
                    continue
                inner_slug = _slug(info.filename, fallback="inner")
                target = target_root / archive_slug / f"{inner_slug}.md"
                body = [
                    "---",
                    "les_source: smeta_ru_norm_nested_archive_projection",
                    f"source_archive: {rel_archive.as_posix()}",
                    f"inner_path: {info.filename}",
                    f"inner_suffix: {inner_suffix}",
                    f"inner_bytes: {info.file_size}",
                    "---",
                    "",
                    f"# Smeta.RU nested projection: {info.filename}",
                    "",
                    f"Source archive: `{rel_archive.as_posix()}`.",
                    "Это текстовая проекция внутреннего файла из `.vnbx` для RAG.",
                    "",
                    "```json" if inner_suffix == ".json" else "```text",
                    text[:max_chars],
                    "```",
                ]
                _write(target, "\n".join(body))
                projected.append(
                    {
                        "source": rel_archive.as_posix(),
                        "inner": info.filename,
                        "rag_path": target.as_posix(),
                        "bytes": info.file_size,
                        "suffix": inner_suffix,
                    }
                )
                written_inner += 1
    return projected


def _file_inventory(extract_dir: Path, *, limit: int = 80) -> dict[str, Any]:
    files = _iter_files(extract_dir)
    by_suffix = Counter((path.suffix.lower() or "<no_suffix>") for path in files)
    return {
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files if path.exists()),
        "suffixes": dict(sorted(by_suffix.items())),
        "sample": [path.relative_to(extract_dir).as_posix() for path in files[:limit]],
    }


def _render_group_classifier(categories: Iterable[str]) -> str:
    unique = list(dict.fromkeys(categories))
    lines = [
        "# Smeta.RU norm corpus classifier",
        "",
        "LES dataset group: TABLE_SMETA.",
        "Source: https://smeta.ru/download/norm and direct obs.smeta.ru ZIP archives.",
        "",
        "Назначение для модели:",
        "- искать разделы ФСНБ, ГЭСН, ГЭСНм, ГЭСНп, ГЭСНр, ФЕР и ресурсные сборники;",
        "- отличать нормативную навигацию от финального calculation_trace;",
        "- использовать найденные нормы как evidence для РИМ-маршрута, а не как автоматический выбор работ.",
        "",
        "Правила:",
        "- архивная карточка не является priced_final;",
        "- missing price не превращается в 0;",
        "- для денег нужен trace, источник цены или явно помеченный scenario_assumption.",
        "",
        "Категории:",
    ]
    for category in unique:
        lines.append(f"- `{category}` → `{_category_dataset_name(category)}`: {CATEGORY_LABELS.get(category, category)}")
    return "\n".join(lines) + "\n"


def _render_category_card(category: str) -> str:
    return "\n".join(
        [
            f"# Smeta.RU norm dataset: {category}",
            "",
            f"Dataset group: {GROUP_NAME}.",
            f"Dataset name hint: {_category_dataset_name(category)}.",
            f"Description: {CATEGORY_LABELS.get(category, category)}.",
            "",
            "Machine description:",
            "- source_kind: smeta_ru_norm_zip_corpus",
            "- content_role: нормативная навигация, нормы, расценки, ресурсы",
            "- calculation_status: evidence_only_until_extracted_trace",
            "- preferred_use: найти сборник/раздел/таблицу/шифр для РИМ/ГЭСН маршрута",
            "",
            "Не использовать как самостоятельный финальный расчёт без раскрытия нормы, ресурсов, цен/индексов и arithmetic trace.",
            "",
        ]
    )


def _render_archive_manifest(
    *,
    archive: dl.NormArchive,
    download: dict[str, Any],
    extract: dict[str, Any],
    inventory: dict[str, Any],
    copied: list[dict[str, Any]],
    projected: list[dict[str, Any]],
    nested_projected: list[dict[str, Any]],
) -> str:
    payload = {
        "schema": "les.smeta_ru_norm_archive_card.v1",
        "archive": asdict(archive),
        "download": download,
        "extract": extract,
        "inventory": inventory,
        "copied_supported_sources": copied,
        "projected_text_files": projected,
        "projected_nested_files": nested_projected,
        "dataset_group": GROUP_NAME,
        "dataset_name_hint": _category_dataset_name(archive.category),
    }
    lines = [
        f"# Smeta.RU norm archive: {archive.filename}",
        "",
        f"Dataset group: {GROUP_NAME}.",
        f"Dataset name hint: {_category_dataset_name(archive.category)}.",
        f"Category: {archive.category}.",
        f"Issue: {archive.issue if archive.issue is not None else 'unknown'}.",
        f"Date: {archive.date or 'unknown'}.",
        f"URL: {archive.url}.",
        "",
        "This archive card is RAG/navigation evidence. It is not priced_final and not a calculation trace.",
        "",
        "## Extracted Inventory",
        "",
        f"- Files: {inventory['files']}",
        f"- Bytes: {inventory['bytes']}",
        f"- Supported files copied to RAG: {len(copied)}",
        f"- Text projections written: {len(projected)}",
        f"- Nested archive projections written: {len(nested_projected)}",
        "",
        "## Suffixes",
        "",
        *[f"- `{suffix}`: {count}" for suffix, count in inventory["suffixes"].items()],
        "",
        "## Sample Files",
        "",
        *[f"- `{item}`" for item in inventory["sample"]],
        "",
        "## Machine JSON",
        "",
        "```json",
        _json(payload),
        "```",
        "",
    ]
    return "\n".join(lines)


def _sync_rag(*, proxy_url: str, parse: bool, parse_limit: int, source_root: str = "RAG_Content") -> dict[str, Any]:
    body = json.dumps({"source_root": source_root, "parse": parse, "parse_limit_per_dataset": parse_limit}).encode("utf-8")
    request = urllib.request.Request(
        proxy_url.rstrip("/") + "/api/rag/sync-smart",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def _set_dataset_group(*, proxy_url: str, dataset_id: str, group: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"group": group})
    request = urllib.request.Request(
        f"{proxy_url.rstrip('/')}/api/rag/datasets/{urllib.parse.quote(dataset_id)}/group?{query}",
        method="PATCH",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _process_archive(args: argparse.Namespace, archive: dl.NormArchive, state: dict[str, Any]) -> dict[str, Any]:
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    out_dir = runtime_root / args.out
    extract_root = runtime_root / args.extract_to
    rag_root = runtime_root / args.rag_out
    category_dir = rag_root / archive.category
    archive_dir = category_dir / _slug(Path(archive.filename).stem)

    download = dl.download_archive(archive, out_dir, timeout=args.download_timeout, overwrite=args.overwrite)
    extract = dl.extract_archive(Path(download["path"]), extract_root, overwrite=args.overwrite)
    extract_dir = Path(extract["extract_dir"])
    inventory = _file_inventory(extract_dir, limit=args.inventory_sample)

    _write(rag_root / "00_group_classifier.md", _render_group_classifier([archive.category, *state.get("categories", [])]))
    _write(category_dir / "00_dataset_card.md", _render_category_card(archive.category))
    copied = _copy_supported_sources(
        extract_dir=extract_dir,
        rag_archive_dir=archive_dir,
        max_files=args.max_source_files,
        max_file_mb=args.max_source_file_mb,
    )
    projected = _project_text_files(
        extract_dir=extract_dir,
        rag_archive_dir=archive_dir,
        max_files=args.max_text_projections,
        max_file_mb=args.max_text_file_mb,
        max_chars=args.max_text_chars,
    )
    nested_projected = _project_nested_archives(
        extract_dir=extract_dir,
        rag_archive_dir=archive_dir,
        max_archives=args.max_nested_archives,
        max_files_per_archive=args.max_nested_files,
        max_file_mb=args.max_nested_file_mb,
        max_chars=args.max_nested_chars,
    )
    manifest_md = _write(
        archive_dir / "01_archive_manifest.md",
        _render_archive_manifest(
            archive=archive,
            download=download,
            extract=extract,
            inventory=inventory,
            copied=copied,
            projected=projected,
            nested_projected=nested_projected,
        ),
    )
    archive_state = {
        "archive": asdict(archive),
        "download": download,
        "extract": extract,
        "inventory": inventory,
        "copied_supported_sources": len(copied),
        "projected_text_files": len(projected),
        "projected_nested_files": len(nested_projected),
        "rag_archive_dir": archive_dir.as_posix(),
        "manifest_md": manifest_md.as_posix(),
        "status": "projected",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if args.sync_rag:
        archive_state["sync_rag"] = _sync_rag(
            proxy_url=args.proxy_url,
            source_root=args.sync_source_root,
            parse=args.parse,
            parse_limit=args.parse_limit,
        )
        for dataset in archive_state["sync_rag"].get("datasets") or []:
            dataset_id = str(dataset.get("dataset_id") or "")
            if dataset_id:
                try:
                    _set_dataset_group(proxy_url=args.proxy_url, dataset_id=dataset_id, group=GROUP_NAME)
                except Exception as error:  # noqa: BLE001
                    archive_state.setdefault("group_errors", []).append({"dataset_id": dataset_id, "error": str(error)})
        archive_state["status"] = "indexed" if args.parse else "registered"
    return archive_state


def run(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = Path(args.runtime_root).expanduser().resolve()
    state_path = runtime_root / args.state
    state = _read_json(state_path, {"schema": "les.smeta_ru_norm_rag_ingest_state.v1", "archives": {}, "categories": []})
    archives = _select_archives(args)
    processed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for archive in archives:
        key = _archive_key(archive)
        previous = (state.get("archives") or {}).get(key) or {}
        if previous.get("status") in {"indexed", "registered", "projected"} and not args.force:
            skipped.append({"url": archive.url, "filename": archive.filename, "reason": "already_processed"})
            continue
        try:
            item_state = _process_archive(args, archive, state)
            state.setdefault("archives", {})[key] = item_state
            categories = list(dict.fromkeys([archive.category, *state.get("categories", [])]))
            state["categories"] = categories
            state["last_archive"] = archive.filename
            state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _write(state_path, _json(state))
            processed.append(item_state)
        except Exception as error:  # noqa: BLE001
            failure = {"archive": asdict(archive), "status": "error", "error": str(error), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            state.setdefault("archives", {})[key] = failure
            state["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _write(state_path, _json(state))
            if args.stop_on_error:
                raise
            processed.append(failure)
    summary = {
        "schema": "les.smeta_ru_norm_rag_ingest.v1",
        "selected": [asdict(item) for item in archives],
        "processed": processed,
        "skipped": skipped,
        "state_path": state_path.as_posix(),
        "rag_out": (runtime_root / args.rag_out).as_posix(),
    }
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smeta.RU norm ZIP → LES RAG ingest worker")
    parser.add_argument("--runtime-root", default=".", help="LES root that owns RAG_Content/storage")
    parser.add_argument("--page-url", default=dl.PAGE_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_DOWNLOAD_REL)
    parser.add_argument("--extract-to", type=Path, default=DEFAULT_EXTRACT_REL)
    parser.add_argument("--rag-out", type=Path, default=DEFAULT_RAG_REL)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_REL)
    parser.add_argument("--latest-per-category", action="store_true", help="ingest latest archive for each category")
    parser.add_argument("--category", action="append", choices=["fsnb2022", "red2020", "red2017", "red2014", "other"])
    parser.add_argument("--latest", action="append", choices=["fsnb2022", "red2020", "red2017", "red2014", "other"])
    parser.add_argument("--pattern", action="append", help="regex over URL/filename; repeatable")
    parser.add_argument("--url", action="append", default=[], help="direct ZIP URL; repeatable")
    parser.add_argument("--all", action="store_true", help="ingest every discovered archive; potentially large")
    parser.add_argument("--max-archives", type=int, default=0, help="cap selected archives after sorting; 0 means no cap")
    parser.add_argument("--with-head", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-project archives already present in state")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--download-timeout", type=int, default=900)
    parser.add_argument("--max-source-files", type=int, default=0)
    parser.add_argument("--max-source-file-mb", type=float, default=80.0)
    parser.add_argument("--max-text-projections", type=int, default=200)
    parser.add_argument("--max-text-file-mb", type=float, default=8.0)
    parser.add_argument("--max-text-chars", type=int, default=12000)
    parser.add_argument("--max-nested-archives", type=int, default=5)
    parser.add_argument("--max-nested-files", type=int, default=200)
    parser.add_argument("--max-nested-file-mb", type=float, default=8.0)
    parser.add_argument("--max-nested-chars", type=int, default=20000)
    parser.add_argument("--inventory-sample", type=int, default=100)
    parser.add_argument("--sync-rag", action="store_true", help="call /api/rag/sync-smart after each archive")
    parser.add_argument("--parse", action="store_true", help="parse during --sync-rag")
    parser.add_argument("--parse-limit", type=int, default=25)
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--sync-source-root", default=DEFAULT_RAG_REL.as_posix())
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        summary = run(args)
    except Exception as error:  # noqa: BLE001
        print(str(error), file=sys.stderr)
        return 2
    print(_json(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
