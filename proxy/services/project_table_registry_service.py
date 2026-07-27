"""Read-only table registry and targeted reader for Л.И.С.Т.

The registry turns project PDF table manifests into searchable navigation
cards. Cards and sample rows are navigation only. ``read_project_table`` opens
the original PDF table and returns source-referenced rows suitable as evidence.
No vector index or MetaDB state is changed here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from proxy.services.lexical_index_service import stem_russian_word
from proxy.services.project_pdf_extract_service import project_pdf_extract_root
from proxy.services.project_pdf_table_service import (
    PROJECT_PDF_TABLE_ALGO_VERSION,
    merge_adjacent_project_table_fragments,
)

TABLE_REGISTRY_SCHEMA = "project_table_registry_v1"
TABLE_CARD_SCHEMA = "project_table_card_v1"
TABLE_READ_SCHEMA = "project_table_read_v1"
TABLE_REGISTRY_FILE = "table_registry.jsonl"
TABLE_REGISTRY_SUMMARY_FILE = "table_registry_summary.json"
_TABLE_REF_RE = re.compile(r"^(?P<path>.+)#page=(?P<page>\d+)#(?:table=(?P<table>\d+)|tables=(?P<start>\d+)-(?P<end>\d+))")


def build_project_table_registry(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    root = project_pdf_extract_root(dataset_id, storage_root=storage_root)
    manifests = sorted(root.glob("*/project_pdf_table_manifest.json"))
    cards: list[dict[str, Any]] = []
    types: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    files: set[str] = set()
    normalized_samples = 0
    identity_ready = 0
    identity_stale = 0
    non_addressable = 0
    fingerprints: dict[str, dict[str, Any]] = {}
    for manifest_path in manifests:
        manifest = _read_json(manifest_path)
        if not manifest:
            continue
        source_path = str(manifest.get("source_path") or "")
        file_name = str(manifest.get("file_name") or Path(source_path).name)
        fingerprint = fingerprints.setdefault(source_path, _source_fingerprint(Path(source_path)))
        for page in manifest.get("pages") or []:
            if not isinstance(page, dict):
                continue
            for candidate in page.get("table_type_candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                card = _candidate_card(
                    dataset_id,
                    candidate,
                    source_path=source_path,
                    file_name=file_name,
                    manifest_path=manifest_path,
                    page_no=int(page.get("page") or 0),
                    source_fingerprint=fingerprint,
                    table_algo_version=str(manifest.get("algo_version") or ""),
                    detector_version=str(manifest.get("detector_version") or ""),
                )
                cards.append(card)
                types[str(card["semantic_type"])] += 1
                categories[str(card["category"])] += 1
                files.add(source_path or file_name)
                if card.get("normalized_sample_rows"):
                    normalized_samples += 1
                if card.get("identity_status") == "ready":
                    identity_ready += 1
                elif card.get("identity_status") == "stale":
                    identity_stale += 1
                else:
                    non_addressable += 1

    registry_path = root / TABLE_REGISTRY_FILE
    _write_jsonl_atomic(registry_path, cards)
    summary = {
        "schema": TABLE_REGISTRY_SCHEMA,
        "dataset_id": dataset_id,
        "table_algo_version": PROJECT_PDF_TABLE_ALGO_VERSION,
        "status": ("ok" if identity_stale == 0 else "partial" if identity_ready else "stale") if cards else "empty",
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
        "table_count": len(cards),
        "file_count": len(files),
        "normalized_sample_tables": normalized_samples,
        "identity_ready_tables": identity_ready,
        "stale_identity_tables": identity_stale,
        "non_addressable_cards": non_addressable,
        "semantic_types": dict(types.most_common()),
        "categories": dict(categories.most_common()),
        "registry_path": registry_path.as_posix(),
    }
    _write_json_atomic(root / TABLE_REGISTRY_SUMMARY_FILE, summary)
    _load_cards_cached.cache_clear()
    return summary


def project_table_registry_summary(
    dataset_id: str,
    *,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    root = project_pdf_extract_root(dataset_id, storage_root=storage_root)
    payload = _read_json(root / TABLE_REGISTRY_SUMMARY_FILE)
    if payload:
        return payload
    return {
        "schema": TABLE_REGISTRY_SCHEMA,
        "dataset_id": dataset_id,
        "status": "missing",
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
        "table_count": 0,
        "warnings": ["table_registry_not_built"],
    }


def search_project_tables(
    dataset_id: str,
    query: str = "",
    *,
    semantic_type: str = "",
    file_filter: str = "",
    include_noise: bool = False,
    limit: int = 20,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    cards = _load_registry_cards(dataset_id, storage_root=storage_root)
    query_norm = _norm(query)
    terms = _tokens(query_norm)
    type_norm = _norm(semantic_type)
    file_norm = _norm(file_filter)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for card in cards:
        if not include_noise and str(card.get("category") or "") in {"noise", "service"}:
            continue
        if type_norm and type_norm not in _norm(str(card.get("semantic_type") or "")):
            continue
        if file_norm and file_norm not in _norm(str(card.get("source_path") or card.get("file_name") or "")):
            continue
        score = _card_score(card, query_norm=query_norm, terms=terms)
        if query_norm and score <= 0:
            continue
        ranked.append((score, card))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("source_ref") or "")))
    selected = [dict(card) | {"score": score} for score, card in ranked[: max(1, min(int(limit), 100))]]
    return {
        "schema": "project_table_search_v1",
        "dataset_id": dataset_id,
        "query": query,
        "filters": {
            "semantic_type": semantic_type,
            "file": file_filter,
            "include_noise": bool(include_noise),
        },
        "total_candidates": len(ranked),
        "returned": len(selected),
        "items": selected,
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
    }


def read_project_table(
    dataset_id: str,
    table_id: str,
    *,
    max_rows: int = 100,
    storage_root: Path = Path("storage/datasets"),
) -> dict[str, Any]:
    if not re.fullmatch(r"(?:[0-9a-f]{20}|[0-9a-f]{32})", str(table_id or "")):
        raise ValueError("table_id must be a 20 or 32 character lowercase hex id")
    cards = _load_registry_cards(dataset_id, storage_root=storage_root)
    card = next((item for item in cards if item.get("table_id") == table_id), None)
    if not card:
        raise KeyError(f"table not found: {table_id}")
    source_ref = str(card.get("source_ref") or "")
    parsed = _parse_table_ref(source_ref)
    manifest_path = Path(str(card.get("manifest_path") or ""))
    root = project_pdf_extract_root(dataset_id, storage_root=storage_root).resolve()
    if not manifest_path.resolve().is_relative_to(root):
        raise ValueError("table manifest escapes dataset source-map root")
    manifest = _read_json(manifest_path)
    if not manifest or str(manifest.get("source_path") or "") != parsed["path"]:
        raise ValueError("table registry source does not match its manifest")
    if len(str(table_id)) != 32 or not card.get("source_fingerprint") or not card.get("bbox"):
        return _stale_payload(dataset_id, card, reason="registry_identity_contract_outdated")
    if str(card.get("table_algo_version") or "") != PROJECT_PDF_TABLE_ALGO_VERSION:
        return _stale_payload(dataset_id, card, reason="table_algorithm_version_changed")
    if str(manifest.get("algo_version") or "") != str(card.get("table_algo_version") or ""):
        return _stale_payload(dataset_id, card, reason="manifest_algorithm_version_changed")
    try:
        import fitz
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("PyMuPDF is unavailable") from exc
    current_detector = f"pymupdf:{getattr(fitz, 'VersionBind', 'unknown')}"
    if str(card.get("detector_version") or "") != current_detector:
        return _stale_payload(dataset_id, card, reason="table_detector_version_changed")
    current_fingerprint = _source_fingerprint(Path(parsed["path"]))
    if current_fingerprint != card.get("source_fingerprint"):
        return _stale_payload(dataset_id, card, reason="source_document_changed", current_fingerprint=current_fingerprint)
    detected = _read_pdf_table(parsed)
    if detected.get("status") != "ok":
        return _stale_payload(dataset_id, card, reason=str(detected.get("reason") or "table_detection_changed"))
    if not _bbox_matches(card.get("bbox"), detected.get("bbox")):
        return _stale_payload(dataset_id, card, reason="table_geometry_changed", current_bbox=detected.get("bbox"))
    matrix = list(detected.get("matrix") or [])
    if _header_signature(matrix) != str(card.get("header_signature") or ""):
        return _stale_payload(dataset_id, card, reason="table_header_changed")
    row_limit = max(1, min(int(max_rows), 500))
    bounded = matrix[:row_limit]
    normalized = _normalized_rows(bounded)
    return {
        "schema": TABLE_READ_SCHEMA,
        "dataset_id": dataset_id,
        "table_id": table_id,
        "semantic_type": card.get("semantic_type"),
        "category": card.get("category"),
        "source_ref": source_ref,
        "source_path": parsed["path"],
        "page": parsed["page"],
        "table_indices": parsed["indices"],
        "headers": bounded[0] if bounded else [],
        "rows": bounded[1:] if len(bounded) > 1 else [],
        "matrix": bounded,
        "normalized_rows": normalized,
        "row_count": len(matrix),
        "returned_rows": len(bounded),
        "truncated": len(matrix) > len(bounded),
        "status": "ok",
        "context_role": "source_evidence",
        "is_evidence": True,
    }


def _candidate_card(
    dataset_id: str,
    candidate: dict[str, Any],
    *,
    source_path: str,
    file_name: str,
    manifest_path: Path,
    page_no: int,
    source_fingerprint: dict[str, Any],
    table_algo_version: str,
    detector_version: str,
) -> dict[str, Any]:
    source_ref = str(candidate.get("source_ref") or "")
    matrix = _sample_matrix(str(candidate.get("sample") or ""))
    bbox = _bbox_values(candidate.get("bbox"))
    header_signature = str(candidate.get("header_signature") or _header_signature(matrix))
    identity = json.dumps(
        {
            "document_sha256": source_fingerprint.get("sha256"),
            "page": page_no,
            "bbox": bbox,
            "header": header_signature,
            "detector": detector_version,
            "algorithm": table_algo_version,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    table_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    semantic_type = str(candidate.get("semantic_type") or "UNKNOWN: требует ручной/визуальной классификации")
    category = str(candidate.get("category") or "unknown")
    card = {
        "schema": TABLE_CARD_SCHEMA,
        "table_id": table_id,
        "dataset_id": dataset_id,
        "file_name": file_name,
        "source_path": source_path,
        "manifest_path": manifest_path.as_posix(),
        "page": page_no,
        "bbox": bbox,
        "header_signature": header_signature,
        "source_fingerprint": source_fingerprint,
        "table_algo_version": table_algo_version,
        "detector_version": detector_version,
        "identity_status": (
            "not_applicable"
            if category == "drawing_annotation" or _TABLE_REF_RE.match(source_ref) is None
            else "ready"
            if (
                bool(source_fingerprint.get("sha256"))
                and bool(bbox)
                and table_algo_version == PROJECT_PDF_TABLE_ALGO_VERSION
                and bool(detector_version)
            )
            else "stale"
        ),
        "source_ref": source_ref,
        "source_refs": list(candidate.get("source_refs") or [source_ref]),
        "semantic_type": semantic_type,
        "category": category,
        "confidence": float(candidate.get("confidence") or 0.0),
        "headers": matrix[0] if matrix else [],
        "sample_rows": matrix[1:] if len(matrix) > 1 else [],
        "normalized_sample_rows": _normalized_rows(matrix),
        "sample": str(candidate.get("sample") or "")[:1000],
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
    }
    card["projection_text"] = _projection_text(card)
    return card


def _read_pdf_table(parsed: dict[str, Any]) -> dict[str, Any]:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError("PyMuPDF is unavailable") from exc
    source_path = Path(parsed["path"])
    if not source_path.exists() or source_path.suffix.lower() != ".pdf":
        raise FileNotFoundError(source_path)
    with fitz.open(str(source_path)) as doc:
        page_no = int(parsed["page"])
        if page_no < 1 or page_no > int(doc.page_count):
            raise ValueError(f"page out of range: {page_no}")
        page = doc[page_no - 1]
        tables = list(page.find_tables().tables)
        fragments: list[dict[str, Any]] = []
        for index in parsed["indices"]:
            if index < 1 or index > len(tables):
                raise ValueError(f"table index out of range: {index}")
            table = tables[index - 1]
            fragments.append({
                "matrix": table.extract() or [],
                "table_indices": [index],
                "context": "",
                "bbox": _bbox_values(getattr(table, "bbox", None)),
            })
    merged = merge_adjacent_project_table_fragments(fragments)
    if not merged:
        return {"status": "stale", "reason": "table_not_detected"}
    if len(merged) != 1:
        return {"status": "stale", "reason": "table_fragments_no_longer_merge"}
    return {
        "status": "ok",
        "matrix": _clean_matrix(merged[0].get("matrix") or []),
        "bbox": _bbox_values(merged[0].get("bbox")),
    }


def _parse_table_ref(source_ref: str) -> dict[str, Any]:
    match = _TABLE_REF_RE.match(source_ref)
    if not match:
        raise ValueError(f"unsupported table source_ref: {source_ref}")
    if match.group("table"):
        indices = [int(match.group("table"))]
    else:
        start = int(match.group("start"))
        end = int(match.group("end"))
        if end < start or end - start > 100:
            raise ValueError("invalid table range")
        indices = list(range(start, end + 1))
    return {"path": match.group("path"), "page": int(match.group("page")), "indices": indices}


def _sample_matrix(sample: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_row in str(sample or "").split(" / "):
        cells = [" ".join(cell.split()) for cell in raw_row.split("|")]
        if any(cells):
            rows.append(cells)
    return rows


def _clean_matrix(matrix: list[list[Any]]) -> list[list[str]]:
    return [[" ".join(str(cell or "").split()) for cell in row] for row in matrix if any(str(cell or "").strip() for cell in row)]


def _header_signature(matrix: list[list[str]]) -> str:
    if not matrix:
        return ""
    header = [" ".join(str(value or "").casefold().replace("ё", "е").split()) for value in matrix[0]]
    return hashlib.sha256("|".join(header).encode("utf-8")).hexdigest()[:24]


def _bbox_values(value: Any) -> list[float]:
    try:
        values = [round(float(item), 3) for item in value]
    except (TypeError, ValueError):
        return []
    return values if len(values) == 4 else []


def _bbox_matches(expected: Any, current: Any, *, tolerance: float = 1.0) -> bool:
    left = _bbox_values(expected)
    right = _bbox_values(current)
    return bool(left and right and all(abs(a - b) <= tolerance for a, b in zip(left, right)))


def _source_fingerprint(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"size": None, "mtime_ns": None, "sha256": ""}
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": ""}
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": digest.hexdigest()}


def _stale_payload(dataset_id: str, card: dict[str, Any], *, reason: str, **details: Any) -> dict[str, Any]:
    return {
        "schema": TABLE_READ_SCHEMA,
        "dataset_id": dataset_id,
        "table_id": card.get("table_id"),
        "status": "stale",
        "reason": reason,
        "source_ref": card.get("source_ref"),
        "semantic_type": card.get("semantic_type"),
        "context_role": "navigation_not_evidence",
        "is_evidence": False,
        **details,
    }


def _normalized_rows(matrix: list[list[str]]) -> list[dict[str, str]]:
    if len(matrix) < 2:
        return []
    raw_headers = [" ".join(str(value or "").split()) for value in matrix[0]]
    if sum(bool(re.search(r"[A-Za-zА-Яа-яЁё]", header)) for header in raw_headers) < 2:
        return []
    headers: list[str] = []
    used: Counter[str] = Counter()
    for index, header in enumerate(raw_headers, 1):
        base = header or f"column_{index}"
        used[base] += 1
        headers.append(base if used[base] == 1 else f"{base}_{used[base]}")
    out: list[dict[str, str]] = []
    for row in matrix[1:]:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        if any(str(value or "").strip() for value in padded):
            out.append({headers[index]: str(padded[index] or "") for index in range(len(headers))})
    return out


def _projection_text(card: dict[str, Any]) -> str:
    headers = " | ".join(str(value) for value in card.get("headers") or [])
    sample_rows = [" | ".join(str(value) for value in row) for row in card.get("sample_rows") or []]
    return "\n".join(
        value
        for value in (
            f"Table type: {card.get('semantic_type')}",
            f"File: {card.get('source_path') or card.get('file_name')}",
            f"Source: {card.get('source_ref')}",
            f"Headers: {headers}" if headers else "",
            *sample_rows[:5],
        )
        if value
    )[:4000]


def _card_score(card: dict[str, Any], *, query_norm: str, terms: list[str]) -> int:
    if not query_norm:
        return 1
    semantic = _norm(str(card.get("semantic_type") or ""))
    headers = _norm(" ".join(str(value) for value in card.get("headers") or []))
    sample = _norm(str(card.get("sample") or ""))
    source = _norm(str(card.get("source_path") or card.get("file_name") or ""))
    combined = " ".join((semantic, headers, sample, source))
    score = 12 if query_norm in combined else 0
    for term in terms:
        if _field_matches(term, semantic):
            # A recognized table type is stronger navigation than the same
            # word appearing incidentally inside an UNKNOWN sample row.
            score += 20
        if _field_matches(term, headers):
            score += 4
        if _field_matches(term, sample):
            score += 2
        if _field_matches(term, source):
            score += 1
    return score


def _field_matches(term: str, field: str) -> bool:
    """Match exact tokens plus conservative Russian inflection variants."""
    if term in field:
        return True
    if not re.search(r"[а-яё]", term):
        return False
    wanted = stem_russian_word(term)
    if len(wanted) < 5:
        return False
    prefix = wanted[:5]
    return any(
        len(candidate) >= 5 and stem_russian_word(candidate).startswith(prefix)
        for candidate in re.findall(r"[а-яё]+", field)
    )


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[0-9a-zа-яё_.-]+", _norm(value)) if len(token) > 1]


def _norm(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def _load_registry_cards(dataset_id: str, *, storage_root: Path) -> list[dict[str, Any]]:
    path = project_pdf_extract_root(dataset_id, storage_root=storage_root) / TABLE_REGISTRY_FILE
    if not path.exists():
        return []
    return list(_load_cards_cached(path.as_posix(), int(path.stat().st_mtime_ns)))


@lru_cache(maxsize=12)
def _load_cards_cached(path: str, _mtime_ns: int) -> tuple[dict[str, Any], ...]:
    cards: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                cards.append(payload)
    return tuple(cards)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _write_jsonl_atomic(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)
