#!/usr/bin/env python3
"""Build read-only source-quality cards for the evidence-core priority corpus.

The tool deliberately reads the same local HTTP surfaces available to an
operator: ``/api/health``, Document Explorer and Dataset Notebook. It never
opens SQLite/Qdrant files directly and never runs parse, OCR or reindex.

    uv run python -m tools.priority_corpus_inventory
    uv run python -m tools.priority_corpus_inventory --output docs/EVIDENCE_CORE_PRIORITY_INVENTORY.md
    uv run python -m tools.priority_corpus_inventory --dataset <uuid>
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen


PRIORITY_CONTOURS = (
    {
        "label": "ПД ИЦ",
        "dataset_id": "1728e431-56d1-410f-8bf9-fdbf2543dce0",
        "purpose": "главный проектный корпус",
    },
    {
        "label": "BAI",
        "dataset_id": "449190eb-050e-422f-91a6-54852469201a",
        "purpose": "компактный project regression",
    },
    {
        "label": "Fire",
        "dataset_id": "5a17e366-4c9a-489e-bfda-518f8fe1223f",
        "purpose": "нормативный retrieval golden",
    },
    {
        "label": "Сметы: проектные таблицы",
        "dataset_id": "a1cc873f-2173-4fc9-bdc5-12e6707ef99b",
        "purpose": "ВОР, ЛСР и проектные таблицы",
    },
    {
        "label": "Сметы: нормативная опора",
        "dataset_id": "9bc6cd77-37f8-4be2-a95a-64d20891ca49",
        "purpose": "нормы и расценки; отдельный source layer",
    },
)
_SERVICE_FILE_NAMES = frozenset({
    "les.md",
    "00_dataset_map.md",
    ".pdf_preprocess_state.json",
    "dataset_card.json",
    "preprocess_state.json",
})

FetchJson = Callable[[str], dict[str, Any]]


def _api_url(proxy_url: str, path: str, **query: Any) -> str:
    base = proxy_url.rstrip("/")
    suffix = urlencode({key: value for key, value in query.items() if value is not None})
    return f"{base}{path}" + (f"?{suffix}" if suffix else "")


def fetch_json(url: str) -> dict[str, Any]:
    """Fetch one local LES read-only response without adding a dependency."""
    with urlopen(url, timeout=90) as response:  # noqa: S310 - caller supplies local proxy URL
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return payload


def fetch_documents(
    fetch: FetchJson,
    *,
    proxy_url: str,
    dataset_id: str,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    """Read all Document Explorer rows using its bounded pagination contract."""
    offset = 0
    documents: list[dict[str, Any]] = []
    while True:
        payload = fetch(
            _api_url(
                proxy_url,
                f"/api/documents/datasets/{dataset_id}/documents",
                limit=page_size,
                offset=offset,
            )
        )
        page = [dict(item) for item in payload.get("documents") or [] if isinstance(item, dict)]
        documents.extend(page)
        total = int(payload.get("total") or 0)
        if not page or len(documents) >= total:
            break
        offset += len(page)
    return documents


def _counts(rows: list[dict[str, Any]], key: str, *, default: str = "UNKNOWN") -> dict[str, int]:
    counter = Counter(str(row.get(key) or default) for row in rows)
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _extension(file_name: str) -> str:
    suffix = PurePosixPath(file_name).suffix.casefold()
    return suffix or "[без расширения]"


def is_service_record(file_name: str) -> bool:
    """Service maps/state are navigation records, not missing evidence chunks."""
    return PurePosixPath(file_name).name.casefold() in _SERVICE_FILE_NAMES


def _sample(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return [
        {
            "file_name": str(row.get("file_name") or ""),
            "doc_type": str(row.get("doc_type") or ""),
            "domain": str(row.get("domain") or ""),
            "chunk_count": int(row.get("chunk_count") or 0),
        }
        for row in rows[:limit]
    ]


def _basename_duplicates(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(PurePosixPath(str(row.get("file_name") or "")).name for row in rows)
    return dict(sorted(((name, count) for name, count in counts.items() if name and count > 1), key=lambda item: (-item[1], item[0])))


def build_quality_card(
    contour: dict[str, str],
    *,
    health_dataset: dict[str, Any] | None,
    documents: list[dict[str, Any]],
    notebook: dict[str, Any] | None,
    sample_limit: int = 8,
) -> dict[str, Any]:
    """Aggregate only API payloads into an operator-facing source-quality card."""
    typed_memory = (notebook or {}).get("typed_memory")
    typed_memory = typed_memory if isinstance(typed_memory, dict) else {}
    profile = (notebook or {}).get("profile")
    profile = profile if isinstance(profile, dict) else {}
    quality = profile.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    status_counts = _counts(documents, "status")
    pending = [row for row in documents if str(row.get("status") or "") == "PENDING"]
    errors = [row for row in documents if str(row.get("status") or "") == "ERROR"]
    indexed_zero_chunks = [
        row
        for row in documents
        if (
            str(row.get("status") or "") == "INDEXED"
            and int(row.get("chunk_count") or 0) <= 0
            and not is_service_record(str(row.get("file_name") or ""))
        )
    ]
    service_records = [row for row in documents if is_service_record(str(row.get("file_name") or ""))]
    missing_source_path = [row for row in documents if not str(row.get("source_path") or "").strip()]

    if errors:
        disposition = "review_errors"
    elif pending:
        disposition = "triage_pending"
    elif indexed_zero_chunks:
        disposition = "review_indexed_without_chunks"
    else:
        disposition = "baseline_candidate"

    revision_id = str(typed_memory.get("revision_id") or "")
    if not revision_id:
        for card in typed_memory.get("file_cards") or []:
            if isinstance(card, dict) and card.get("revision_id"):
                revision_id = str(card["revision_id"])
                break
    runtime_status = str((health_dataset or {}).get("status") or "UNKNOWN")
    runtime_status_drift = runtime_status == "ERROR" and not errors
    notebook_signals = quality.get("signals") if isinstance(quality.get("signals"), dict) else {}

    return {
        "schema": "priority_corpus_quality_card_v1",
        "context_role": "navigation",
        "is_evidence": False,
        "label": contour["label"],
        "purpose": contour["purpose"],
        "dataset": {
            "id": contour["dataset_id"],
            "name": str((health_dataset or {}).get("name") or (notebook or {}).get("name") or ""),
            "runtime_status": runtime_status,
            "owner": "UNSET",
            "source_revision_id": revision_id,
            "reader_status": str(typed_memory.get("reader_status") or "unknown"),
            "topic_map": bool(typed_memory.get("topic_map")),
            "section_map": bool(typed_memory.get("section_map")),
            "notebook_quality": str(quality.get("status") or "unknown"),
            "notebook_signals": {
                "lexical_chunks": int(notebook_signals.get("lexical_chunks") or 0),
                "table_signal_chunks": int(notebook_signals.get("table_signal_chunks") or 0),
            },
        },
        "documents": {
            "total": len(documents),
            "status_counts": status_counts,
            "doc_type_counts": _counts(documents, "doc_type"),
            "content_type_counts": _counts(documents, "content_type"),
            "domain_counts": _counts(documents, "domain"),
            "extension_counts": dict(
                sorted(Counter(_extension(str(row.get("file_name") or "")) for row in documents).items(), key=lambda item: (-item[1], item[0]))
            ),
            "declared_chunks": sum(int(row.get("chunk_count") or 0) for row in documents),
        },
        "observations": {
            "pending": _sample(pending, sample_limit),
            "pending_doc_type_counts": _counts(pending, "doc_type"),
            "pending_extension_counts": dict(
                sorted(Counter(_extension(str(row.get("file_name") or "")) for row in pending).items(), key=lambda item: (-item[1], item[0]))
            ),
            "pending_duplicate_basenames": _basename_duplicates(pending),
            "errors": _sample(errors, sample_limit),
            "indexed_zero_chunks": _sample(indexed_zero_chunks, sample_limit),
            "service_records": _sample(service_records, sample_limit),
            "missing_source_path_count": len(missing_source_path),
            "skipped_count": status_counts.get("SKIPPED", 0),
            "runtime_status_drift": runtime_status_drift,
        },
        "disposition": {
            "status": disposition,
            "automatic_quarantine": False,
            "reason": "Статусы и метаданные требуют операторского решения; отчёт ничего не меняет.",
        },
    }


def build_priority_inventory(
    *,
    proxy_url: str,
    contours: list[dict[str, str]],
    fetch: FetchJson = fetch_json,
    sample_limit: int = 8,
) -> dict[str, Any]:
    health = fetch(_api_url(proxy_url, "/api/health"))
    rag = health.get("rag") if isinstance(health.get("rag"), dict) else {}
    health_datasets = {
        str(row.get("id") or ""): row
        for row in rag.get("datasets") or []
        if isinstance(row, dict)
    }
    cards = []
    for contour in contours:
        dataset_id = contour["dataset_id"]
        documents = fetch_documents(fetch, proxy_url=proxy_url, dataset_id=dataset_id)
        notebook = fetch(_api_url(proxy_url, f"/api/notebooks/{dataset_id}", depth="deep"))
        cards.append(
            build_quality_card(
                contour,
                health_dataset=health_datasets.get(dataset_id),
                documents=documents,
                notebook=notebook,
                sample_limit=sample_limit,
            )
        )
    return {
        "schema": "priority_corpus_inventory_v1",
        "context_role": "navigation",
        "is_evidence": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "proxy_url": proxy_url.rstrip("/"),
        "runtime": {
            "status": health.get("status"),
            "collection": ((rag.get("qdrant") or {}).get("collection") if isinstance(rag.get("qdrant"), dict) else ""),
            "points_match_sqlite_chunks": ((rag.get("qdrant") or {}).get("points_match_sqlite_chunks") if isinstance(rag.get("qdrant"), dict) else None),
        },
        "cards": cards,
    }


def render_markdown(inventory: dict[str, Any]) -> str:
    """Render a compact, generated navigation report; never source evidence."""
    runtime = inventory.get("runtime") if isinstance(inventory.get("runtime"), dict) else {}
    lines = [
        "# Priority corpus inventory",
        "",
        "Статус: generated read-only snapshot. Не evidence; не запускает parse/OCR/reindex и не меняет источники.",
        f"Сгенерирован: `{inventory.get('generated_at')}`.",
        f"Runtime: `{runtime.get('status')}` · collection `{runtime.get('collection')}` · points/sqlite `{runtime.get('points_match_sqlite_chunks')}`.",
    ]
    for card in inventory.get("cards") or []:
        if not isinstance(card, dict):
            continue
        dataset = card.get("dataset") if isinstance(card.get("dataset"), dict) else {}
        documents = card.get("documents") if isinstance(card.get("documents"), dict) else {}
        observations = card.get("observations") if isinstance(card.get("observations"), dict) else {}
        disposition = card.get("disposition") if isinstance(card.get("disposition"), dict) else {}
        lines += [
            "",
            f"## {card.get('label')}",
            "",
            f"- Dataset: `{dataset.get('name')}` · `{dataset.get('id')}`.",
            f"- Назначение: {card.get('purpose')}. Owner: **{dataset.get('owner')}**.",
            f"- Runtime: `{dataset.get('runtime_status')}`; notebook `{dataset.get('notebook_quality')}`; reader `{dataset.get('reader_status')}`; revision `{dataset.get('source_revision_id') or 'MISSING'}`.",
            f"- Документы: {documents.get('total', 0)}; declared chunks: {documents.get('declared_chunks', 0)}; statuses: {_render_counts(documents.get('status_counts'))}.",
            f"- Типы: {_render_counts(documents.get('doc_type_counts'))}.",
            f"- Решение: **{disposition.get('status')}**. Автоматический quarantine: нет.",
        ]
        for key, label in (("pending", "Pending"), ("errors", "Errors"), ("indexed_zero_chunks", "Indexed без declared chunks")):
            samples = observations.get(key) if isinstance(observations.get(key), list) else []
            if not samples:
                continue
            lines += ["", f"### {label}", ""]
            for item in samples:
                if isinstance(item, dict):
                    lines.append(
                        f"- `{item.get('file_name')}` · {item.get('doc_type') or 'unknown'} · "
                        f"{item.get('domain') or 'unknown'} · chunks {item.get('chunk_count', 0)}"
                    )
        pending_type_counts = observations.get("pending_doc_type_counts")
        pending_extension_counts = observations.get("pending_extension_counts")
        if pending_type_counts:
            lines.append(f"- Pending по типу: {_render_counts(pending_type_counts)}.")
        if pending_extension_counts:
            lines.append(f"- Pending по расширению: {_render_counts(pending_extension_counts)}.")
        duplicate_pending = observations.get("pending_duplicate_basenames")
        if duplicate_pending:
            lines.append(f"- Повторяющиеся имена pending: {_render_counts(duplicate_pending)}.")
        if observations.get("runtime_status_drift"):
            lines.append("- **Drift:** runtime dataset status `ERROR`, но Document Explorer не видит строк `ERROR`; требуется сверка статуса, не parse.")
        service_records = observations.get("service_records") if isinstance(observations.get("service_records"), list) else []
        if service_records:
            lines.append(f"- Служебные записи исключены из zero-chunk defect: {len(service_records)}.")
    lines += [
        "",
        "## Следующий ход",
        "",
        "Назначить owner и операторское решение для каждого pending/error/zero-chunk файла. "
        "Только затем выбирать первый dataset для index-quality; этот отчёт сам не является основанием "
        "для ответа модели или массового изменения корпуса.",
    ]
    return "\n".join(lines) + "\n"


def _render_counts(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "—"
    return ", ".join(f"{key}: {count}" for key, count in value.items())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--dataset", action="append", default=[], help="dataset UUID; repeat to override default priority set")
    parser.add_argument("--sample-limit", type=int, default=8)
    parser.add_argument("--output", default="", help="generated Markdown report path")
    parser.add_argument("--json", dest="json_path", default="", help="optional machine-readable report path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contours = list(PRIORITY_CONTOURS)
    if args.dataset:
        known = {item["dataset_id"]: item for item in PRIORITY_CONTOURS}
        contours = [known.get(dataset_id, {"label": dataset_id, "dataset_id": dataset_id, "purpose": "operator-selected dataset"}) for dataset_id in args.dataset]
    inventory = build_priority_inventory(
        proxy_url=args.proxy_url,
        contours=contours,
        sample_limit=max(1, args.sample_limit),
    )
    markdown = render_markdown(inventory)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(markdown, encoding="utf-8")
    if args.json_path:
        from pathlib import Path

        Path(args.json_path).write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
