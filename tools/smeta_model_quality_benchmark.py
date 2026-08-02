"""Reproducible Qwen/Gemma document-to-LSR benchmark on the canonical LES workflow.

The harness changes transport configuration only.  It never selects or repairs a
norm, route, resource, coefficient, coverage decision, or professional result.
Both profiles use the same prompt, tools, corpus, limits, seed and source file.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx

from proxy.services import smeta_chat_adapter_service as adapters
from proxy.services.smeta_chat_application_service import (
    _load_document_checkpoint,
    _source_fingerprint,
    _write_document_checkpoint,
)
from proxy.services.prompt_registry_service import smeta_native_skill_prompt
from proxy.smeta_core.document_workflow import batch_norm_tools, run_vor_document_workflow
from proxy.smeta_core.source_intake import intake_vor_document


SCHEMA = "les.smeta.model-quality-benchmark.v1"
EVENT_SCHEMA = "les.smeta.model-quality-tool-event.v1"
DEFAULT_REQUEST = "Составь проверяемый сметный расчёт по этой ведомости"
DEFAULT_PROFILES = ("qwen=qwen3.5:9b", "gemma=gemma4:12b")


class BenchmarkInterruption(RuntimeError):
    """Cooperative crash boundary used to prove durable checkpoint resume."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _parse_profiles(
    values: list[str],
    *,
    allow_single: bool = False,
) -> list[tuple[str, str]]:
    profiles: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in values:
        label, separator, model = str(value).partition("=")
        label = label.strip()
        model = model.strip()
        if not separator or not label or not model:
            raise ValueError(f"invalid profile {value!r}; expected label=model")
        if label in seen:
            raise ValueError(f"duplicate profile label: {label}")
        seen.add(label)
        profiles.append((label, model))
    if not profiles:
        raise ValueError("at least one model profile is required")
    if len(profiles) < 2 and not allow_single:
        raise ValueError("at least two model profiles are required")
    return profiles


def _ollama_models(base_url: str) -> dict[str, dict[str, Any]]:
    root = base_url.rstrip("/")
    if root.casefold().endswith("/v1"):
        root = root[:-3]
    with httpx.Client(timeout=20.0) as client:
        response = client.get(f"{root}/api/tags")
        response.raise_for_status()
        payload = response.json()
    return {
        str(item.get("name") or item.get("model") or ""): dict(item)
        for item in payload.get("models") or []
        if str(item.get("name") or item.get("model") or "")
    }


def _qdrant_evidence(base_url: str) -> dict[str, Any]:
    root = base_url.rstrip("/")
    with httpx.Client(timeout=20.0) as client:
        response = client.get(f"{root}/aliases")
        response.raise_for_status()
        aliases = {
            str(item.get("alias_name") or ""): str(item.get("collection_name") or "")
            for item in (response.json().get("result") or {}).get("aliases") or []
        }
        collections: dict[str, Any] = {}
        for alias in ("les_smeta_norm_cards", "les_smeta_norm_catalog"):
            target = aliases.get(alias)
            if not target:
                continue
            info = client.get(f"{root}/collections/{target}")
            info.raise_for_status()
            payload = info.json().get("result") or {}
            collections[alias] = {
                "target": target,
                "points_count": payload.get("points_count"),
                "indexed_vectors_count": payload.get("indexed_vectors_count"),
                "status": payload.get("status"),
            }
    return {"aliases": aliases, "smeta_collections": collections}


def _warm_model(base_url: str, model: str, *, seed: int, num_ctx: int) -> dict[str, Any]:
    root = base_url.rstrip("/")
    if root.casefold().endswith("/v1"):
        root = root[:-3]
    started = time.perf_counter()
    with httpx.Client(timeout=300.0) as client:
        response = client.post(
            f"{root}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Ответь одним словом: ГОТОВО"}],
                "stream": False,
                "keep_alive": "10m",
                "options": {
                    "temperature": 0.0,
                    "seed": seed,
                    "num_ctx": num_ctx,
                    "num_predict": 8,
                },
            },
        )
        response.raise_for_status()
        payload = response.json()
    return {
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "model": str(payload.get("model") or model),
        "done_reason": str(payload.get("done_reason") or ""),
        "load_duration_ns": int(payload.get("load_duration") or 0),
        "prompt_eval_count": int(payload.get("prompt_eval_count") or 0),
        "eval_count": int(payload.get("eval_count") or 0),
    }


def _unload_model(base_url: str, model: str) -> None:
    root = base_url.rstrip("/")
    if root.casefold().endswith("/v1"):
        root = root[:-3]
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{root}/api/generate",
            json={"model": model, "prompt": "", "stream": False, "keep_alive": 0},
        )
        response.raise_for_status()


def _assert_reranker_ready() -> dict[str, Any]:
    """Fail closed before a multi-hour A/B if the production reranker is dead."""
    import asyncio

    from backend.reranker import SentenceTransformerReranker, select_reranker_cls

    cls = select_reranker_cls()
    if cls is not SentenceTransformerReranker and os.name == "nt":
        raise RuntimeError(
            "Windows A/B requires RERANKER_BACKEND=sentence_transformers; "
            f"got {cls.__name__} (MLX cross_encoder is not a Legion production path)"
        )
    if cls is SentenceTransformerReranker:
        reranker = cls()
        ranked = asyncio.run(
            reranker.rerank(
                "монтаж шкафа",
                [
                    {"text": "Монтаж телекоммуникационного шкафа", "score": 0.2, "metadata": {"i": 0}},
                    {"text": "Устройство стяжки пола", "score": 0.1, "metadata": {"i": 1}},
                    {"text": "Прокладка кабеля витая пара", "score": 0.15, "metadata": {"i": 2}},
                    {"text": "Пусконаладка СКС", "score": 0.05, "metadata": {"i": 3}},
                ],
                top_k=2,
            )
        )
        if len(ranked) < 1:
            raise RuntimeError("sentence-transformers reranker returned no ranks")
        return {
            "backend": "sentence_transformers",
            "class": cls.__name__,
            "model": reranker.model,
            "smoke_ranks": len(ranked),
        }
    return {"backend": "configured", "class": cls.__name__}


@contextlib.contextmanager
def _model_environment(
    model: str,
    *,
    base_url: str,
    seed: int,
    num_ctx: int,
    tool_max_tokens: int,
    mapping_max_tokens: int,
) -> Iterator[None]:
    values = {
        "LES_LLM_PROVIDER": "ollama",
        "LES_SMETA_PROVIDER": "ollama",
        "LES_SMETA_DOCUMENT_PROVIDER": "ollama",
        "LES_SMETA_DOCUMENT_MODEL": model,
        "OLLAMA_BASE_URL": base_url,
        "OLLAMA_MODEL": model,
        "LLM_MODEL": model,
        "LES_SMETA_DOCUMENT_SEED": str(seed),
        "LES_SMETA_DOCUMENT_NUM_CTX": str(num_ctx),
        "LES_SMETA_DOCUMENT_TOOL_MAX_TOKENS": str(tool_max_tokens),
        "LES_SMETA_DOCUMENT_MAPPING_MAX_TOKENS": str(mapping_max_tokens),
        "LES_SMETA_DOCUMENT_THINK": "false",
    }
    if os.name == "nt":
        # Match start-light / windows_runtime: never hit Mac MLX :8080 from Legion A/B.
        values["RERANKER_BACKEND"] = "sentence_transformers"
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _all_positions(lsr: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(position.get("work_id") or ""): position
        for section in lsr.get("sections") or []
        for position in section.get("positions") or []
        if str(position.get("work_id") or "")
    }


def _coverage(lsr: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("work_id") or ""): item
        for item in lsr.get("coverage") or []
        if str(item.get("work_id") or "")
    }


def _same_number(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-9
    except (TypeError, ValueError):
        return str(left) == str(right)


def _work_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "work_id" and str(item or ""):
                found.add(str(item))
            elif key in {"work_ids", "remaining_work_ids"} and isinstance(item, list):
                found.update(str(entry) for entry in item if str(entry or ""))
            else:
                found.update(_work_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_work_ids(item))
    return found


def _assistant_calls(trace: dict[str, Any]) -> list[dict[str, Any]]:
    assistant = trace.get("assistant") or {}
    if not isinstance(assistant, dict):
        return []
    calls = assistant.get("tool_calls") or []
    parsed: list[dict[str, Any]] = []
    for call in calls if isinstance(calls, list) else []:
        function = (call or {}).get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        parsed.append({
            "tool": str(function.get("name") or (call or {}).get("name") or ""),
            "arguments": arguments if isinstance(arguments, dict) else {},
        })
    return parsed


def _tool_stats(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fingerprints: dict[str, list[str]] = defaultdict(list)
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for trace in result.get("model_trace") or []:
        if not isinstance(trace, dict):
            continue
        for call in _assistant_calls(trace):
            arguments = call["arguments"]
            ids = _work_ids(arguments)
            if not ids:
                continue
            fingerprint = json.dumps(call, ensure_ascii=False, sort_keys=True, default=str)
            for work_id in ids:
                fingerprints[work_id].append(fingerprint)
                names[work_id][call["tool"]] += 1
    output: dict[str, dict[str, Any]] = {}
    for work_id in set(fingerprints) | set(names):
        counts = Counter(fingerprints[work_id])
        output[work_id] = {
            "calls": sum(names[work_id].values()),
            "repeats": sum(max(0, count - 1) for count in counts.values()),
            "by_tool": dict(sorted(names[work_id].items())),
        }
    return output


def _qrel_for(qrels: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    rows = qrels.get("rows") or {}
    for key in (row.get("work_id"), row.get("source_no"), row.get("source_row")):
        if str(key or "") in rows:
            value = rows[str(key)]
            return dict(value) if isinstance(value, dict) else {}
    return {}


_STAGE_BY_TOOL = {
    "browse_norm_catalog": "catalog",
    "choose_norm_catalog": "catalog",
    "confirm_norm_catalog_scope": "catalog",
    "broaden_norm_catalog": "catalog",
    "reuse_norm_catalog_route": "catalog",
    "search_norms_batch": "search",
    "read_norms_batch": "read",
    "submit_lsr_mapping": "bind",
}


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return round(ordered[low] * (1.0 - weight) + ordered[high] * weight, 3)


def stage_latency_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Aggregate tool/model stage timings for A/B Gemma↔Qwen comparison."""
    buckets: dict[str, list[float]] = defaultdict(list)
    trajectory = ((result.get("agent_trace") or {}).get("tool_trajectory") or [])
    for item in trajectory if isinstance(trajectory, list) else []:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "")
        stage = _STAGE_BY_TOOL.get(tool, "other_tools")
        try:
            buckets[stage].append(float(item.get("elapsed_ms") or 0.0))
        except (TypeError, ValueError):
            continue
    model_turns = 0
    for trace in result.get("model_trace") or []:
        if not isinstance(trace, dict):
            continue
        model_turns += 1
        for key in ("elapsed_ms", "duration_ms", "provider_elapsed_ms"):
            if key in trace:
                try:
                    buckets["llm"].append(float(trace[key]))
                except (TypeError, ValueError):
                    pass
                break
    for trace in result.get("catalog_trace") or []:
        if isinstance(trace, dict) and trace.get("elapsed_ms") is not None:
            try:
                buckets["catalog"].append(float(trace["elapsed_ms"]))
            except (TypeError, ValueError):
                pass
    for trace in result.get("query_trace") or []:
        if isinstance(trace, dict) and trace.get("elapsed_ms") is not None:
            try:
                buckets["search"].append(float(trace["elapsed_ms"]))
            except (TypeError, ValueError):
                pass
    stages: dict[str, Any] = {}
    for name, values in sorted(buckets.items()):
        stages[name] = {
            "count": len(values),
            "total_ms": round(sum(values), 3),
            "p50_ms": _percentile(values, 50),
            "p95_ms": _percentile(values, 95),
        }
    tool_calls = sum(
        int(stage["count"]) for name, stage in stages.items() if name != "llm"
    )
    return {
        "schema": "les.smeta.stage-latency.v1",
        "model_turns": model_turns,
        "tool_calls": tool_calls,
        "stages": stages,
        "route_events": {
            "catalog_trace": len(result.get("catalog_trace") or []),
            "query_trace": len(result.get("query_trace") or []),
            "browse_trace_work_ids": len(result.get("browse_trace") or {}),
        },
    }


def analyze_result(
    result: dict[str, Any],
    *,
    row_timings: dict[str, dict[str, float]],
    qrels: dict[str, Any] | None = None,
) -> dict[str, Any]:
    qrels = qrels or {}
    intake_rows = list((result.get("intake") or {}).get("work_items") or [])
    selections = dict(result.get("selections") or {})
    lsr = dict(result.get("lsr") or {})
    positions = _all_positions(lsr)
    coverage = _coverage(lsr)
    blockers_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for blocker in lsr.get("blockers") or []:
        blockers_by_work[str((blocker or {}).get("work_id") or "")].append(blocker)
    tool_stats = _tool_stats(result)
    query_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in result.get("query_trace") or []:
        query_by_work[str((trace or {}).get("work_id") or "")].append(trace)
    catalog_by_work: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trace in result.get("catalog_trace") or []:
        catalog_by_work[str((trace or {}).get("work_id") or "")].append(trace)

    rows: list[dict[str, Any]] = []
    for source in intake_rows:
        work_id = str(source.get("work_id") or "")
        selection = dict(selections.get(work_id) or {})
        position = positions.get(work_id) or {}
        coverage_item = coverage.get(work_id) or {}
        blockers = blockers_by_work.get(work_id, [])
        norm_code = str(selection.get("norm_code") or position.get("code") or "")
        coverage_status = str(coverage_item.get("status") or "")
        if position and not blockers:
            status = "calculated"
        elif coverage_status == "covered_by" and not blockers:
            status = "calculated"
        elif position or (selection and norm_code):
            status = "partial"
        else:
            status = "missing"

        qrel = _qrel_for(qrels, source)
        acceptable = {str(code) for code in qrel.get("acceptable_norm_codes") or []}
        norm_correctness = (
            "correct" if acceptable and norm_code in acceptable
            else "incorrect" if acceptable and norm_code
            else "missing" if acceptable
            else "not_adjudicated"
        )
        source_qty = source.get("quantity")
        position_qty = position.get("source_quantity", position.get("physical_quantity"))
        volume_integrity = bool(position) and _same_number(source_qty, position_qty)
        source_unit = str(source.get("unit") or "")
        position_unit = str(position.get("source_unit") or position.get("physical_unit") or "")
        unit_integrity = bool(position) and source_unit.casefold() == position_unit.casefold()
        source_integrity = dict(position.get("norm_source_integrity") or {})
        provenance_integrity = bool(norm_code) and bool(source_integrity)
        catalog_levels = {
            str(trace.get("level") or trace.get("node_type") or "")
            for trace in catalog_by_work.get(work_id, [])
        }
        scoped_queries = [
            trace for trace in query_by_work.get(work_id, [])
            if any((trace.get("filters") or {}).get(key) for key in ("base_types", "collections", "table_codes"))
        ]
        route_structural = (
            "verified" if norm_code and scoped_queries and catalog_levels
            else "partial" if scoped_queries or catalog_levels
            else "missing"
        )
        expected_family = str(qrel.get("expected_family") or "")
        selected_family = str(selection.get("norm_family") or selection.get("base_type") or "")
        route_correctness = (
            "correct" if expected_family and selected_family == expected_family
            else "incorrect" if expected_family and selected_family
            else "missing" if expected_family
            else "not_adjudicated"
        )
        timing = row_timings.get(work_id) or {}
        calculated_total = (position.get("summary") or {}).get("total")
        rows.append({
            "work_id": work_id,
            "source_no": source.get("source_no"),
            "source_row": source.get("source_row"),
            "title": source.get("title"),
            "unit": source_unit,
            "quantity": source_qty,
            "status": status,
            "decision": (
                "bind" if norm_code else
                "covered_by" if selection.get("covered_by_work_id") else
                "unbound" if selection else "missing"
            ),
            "norm_code": norm_code,
            "norm_correctness": norm_correctness,
            "unit_integrity": unit_integrity,
            "volume_integrity": volume_integrity,
            "provenance_integrity": provenance_integrity,
            "route_structural": route_structural,
            "route_correctness": route_correctness,
            "tool_calls": int((tool_stats.get(work_id) or {}).get("calls") or 0),
            "tool_repeats": int((tool_stats.get(work_id) or {}).get("repeats") or 0),
            "tools_by_name": (tool_stats.get(work_id) or {}).get("by_tool") or {},
            "elapsed_sec": round(float(timing.get("elapsed_sec") or 0.0), 3),
            "timing_scope": "row_mapping_until_terminal_checkpoint",
            "calculated_total": calculated_total,
            "zero_calculation": bool(position) and _same_number(calculated_total, 0),
            "blockers": blockers,
        })
    statuses = Counter(row["status"] for row in rows)
    stage_latency = stage_latency_summary(result)
    return {
        "schema": SCHEMA,
        "rows": rows,
        "stage_latency": stage_latency,
        "summary": {
            "input_rows": len(rows),
            "calculated": statuses["calculated"],
            "partial": statuses["partial"],
            "missing": statuses["missing"],
            "empty_or_zero_rows": sum(
                1 for row in rows
                if not str(row.get("title") or "").strip()
                or row.get("quantity") in (None, "", 0, 0.0, "0", "0.0")
            ),
            "zero_calculation_rows": sum(bool(row["zero_calculation"]) for row in rows),
            "empty_result_rows": sum(row["status"] == "missing" for row in rows),
            "tool_calls": sum(row["tool_calls"] for row in rows),
            "tool_repeats": sum(row["tool_repeats"] for row in rows),
            "unit_integrity_pass": sum(bool(row["unit_integrity"]) for row in rows),
            "volume_integrity_pass": sum(bool(row["volume_integrity"]) for row in rows),
            "provenance_integrity_pass": sum(bool(row["provenance_integrity"]) for row in rows),
            "route_structural_verified": sum(row["route_structural"] == "verified" for row in rows),
            "professionally_adjudicated_rows": sum(row["norm_correctness"] != "not_adjudicated" for row in rows),
            "stage_latency": stage_latency,
        },
    }


def _trace_events(
    result: dict[str, Any],
    *,
    profile: str,
    model: str,
    event_path: Path,
    elapsed_sec: float,
) -> None:
    for kind, values in (
        ("query_trace", result.get("query_trace") or []),
        ("catalog_trace", result.get("catalog_trace") or []),
        ("model_trace", result.get("model_trace") or []),
    ):
        for index, value in enumerate(values, 1):
            _append_jsonl(event_path, {
                "schema": EVENT_SCHEMA,
                "timestamp": _utc_now(),
                "elapsed_sec": round(elapsed_sec, 3),
                "profile": profile,
                "model": model,
                "event": kind,
                "index": index,
                "payload": value,
            })
    for work_id, values in (result.get("browse_trace") or {}).items():
        for index, value in enumerate(values or [], 1):
            _append_jsonl(event_path, {
                "schema": EVENT_SCHEMA,
                "timestamp": _utc_now(),
                "elapsed_sec": round(elapsed_sec, 3),
                "profile": profile,
                "model": model,
                "event": "browse_trace",
                "work_id": work_id,
                "index": index,
                "payload": value,
            })
    for index, value in enumerate(
        ((result.get("agent_trace") or {}).get("tool_trajectory") or []),
        1,
    ):
        _append_jsonl(event_path, {
            "schema": EVENT_SCHEMA,
            "timestamp": _utc_now(),
            "elapsed_sec": round(elapsed_sec, 3),
            "profile": profile,
            "model": model,
            "event": "tool_trajectory",
            "index": index,
            "payload": value,
        })
    _append_jsonl(event_path, {
        "schema": EVENT_SCHEMA,
        "timestamp": _utc_now(),
        "elapsed_sec": round(elapsed_sec, 3),
        "profile": profile,
        "model": model,
        "event": "stage_latency",
        "payload": stage_latency_summary(result),
    })


def _run_profile(
    *,
    source: Path,
    profile: str,
    model: str,
    run_root: Path,
    args: argparse.Namespace,
    model_metadata: dict[str, Any],
    qrels: dict[str, Any],
    resume_existing: bool = False,
) -> dict[str, Any]:
    profile_root = run_root / profile
    if resume_existing:
        if not profile_root.is_dir():
            raise RuntimeError(f"resume profile directory is absent: {profile_root}")
    else:
        profile_root.mkdir(parents=True, exist_ok=False)
    event_path = profile_root / "tool-events.jsonl"
    checkpoint_path = profile_root / "checkpoint.json"
    source_fingerprint = _source_fingerprint(source)
    resume_result = (
        _load_document_checkpoint(
            checkpoint_path,
            source_fingerprint=source_fingerprint,
        )
        if resume_existing
        else None
    )
    if resume_existing and not resume_result:
        raise RuntimeError(f"resume checkpoint is absent or incompatible: {checkpoint_path}")
    rows = list(intake_vor_document(source).get("work_items") or [])
    ordered_work_ids = [str(row.get("work_id") or "") for row in rows]
    progress_work_ids = [
        work_id
        for work_id in ordered_work_ids
        if work_id not in ((resume_result or {}).get("selections") or {})
    ]
    row_timings: dict[str, dict[str, float]] = {}
    started = time.perf_counter()
    active_batch_started: dict[int, float] = {}
    interrupted = bool(
        resume_result
        and args.interrupt_after_rows > 0
        and len(resume_result.get("selections") or {}) >= args.interrupt_after_rows
    )
    interruption_elapsed = 0.0

    def emit(event: str, payload: dict[str, Any]) -> None:
        _append_jsonl(event_path, {
            "schema": EVENT_SCHEMA,
            "timestamp": _utc_now(),
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "profile": profile,
            "model": model,
            "event": event,
            "payload": payload,
        })

    def progress(event: dict[str, Any]) -> None:
        phase = str(event.get("phase") or "")
        batch = int(event.get("batch") or 0)
        if phase == "source_batch" and batch > 0:
            work_id = progress_work_ids[batch - 1] if batch <= len(progress_work_ids) else ""
            if event.get("status") == "started":
                active_batch_started[batch] = time.perf_counter()
            elif event.get("status") == "done" and work_id:
                batch_started = active_batch_started.get(batch, started)
                row_timings[work_id] = {
                    "elapsed_sec": time.perf_counter() - batch_started,
                    "completed_at_sec": time.perf_counter() - started,
                }
        emit("progress", event)

    def checkpoint(agent_result: dict[str, Any]) -> None:
        nonlocal interrupted, interruption_elapsed
        previous_checkpoint = _load_document_checkpoint(
            checkpoint_path,
            source_fingerprint=source_fingerprint,
        )
        if len((previous_checkpoint or {}).get("selections") or {}) > len(
            agent_result.get("selections") or {}
        ):
            emit("checkpoint_regression_ignored", {
                "incoming_completed_rows": len(agent_result.get("selections") or {}),
                "preserved_completed_rows": len(previous_checkpoint.get("selections") or {}),
            })
            return
        _write_document_checkpoint(
            checkpoint_path,
            source_fingerprint=source_fingerprint,
            agent_result=agent_result,
        )
        completed = len(agent_result.get("selections") or {})
        now = time.perf_counter()
        for work_id in (agent_result.get("selections") or {}):
            if work_id in row_timings:
                continue
            if work_id in progress_work_ids:
                batch = progress_work_ids.index(work_id) + 1
                batch_started = active_batch_started.get(batch, started)
                row_timings[work_id] = {
                    "elapsed_sec": now - batch_started,
                    "completed_at_sec": now - started,
                }
        emit("checkpoint", {
            "completed_rows": completed,
            "remaining_work_ids": agent_result.get("remaining_work_ids") or [],
            "incomplete_blocker": agent_result.get("incomplete_blocker") or {},
        })
        if (
            args.interrupt_after_rows > 0
            and not interrupted
            and completed >= args.interrupt_after_rows
        ):
            interrupted = True
            interruption_elapsed = time.perf_counter() - started
            emit("interruption_injected", {"completed_rows": completed})
            raise BenchmarkInterruption(
                f"cooperative interruption after {completed} checkpointed rows"
            )

    warmup = _warm_model(
        args.ollama_base_url,
        model,
        seed=args.seed,
        num_ctx=args.num_ctx,
    )
    emit("warmup", warmup)
    if resume_result:
        emit("resume_started", {
            "checkpointed_rows": len(resume_result.get("selections") or {}),
            "external_resume": True,
        })
    common = {
        "exchange": adapters._smeta_document_exchange,
        "mapping_exchange": adapters._smeta_document_mapping_exchange,
        "candidate_limit": args.candidate_limit,
        "out_xlsx": profile_root / "result.xlsx",
        "out_report": profile_root / "workflow.json",
        "revision_root": str(profile_root / "revisions"),
        "progress": progress,
        "source_name": source.name,
        "user_request": args.request,
        "batch_size": 1,
        "max_agent_turns": args.max_turns,
        "batch_checkpoint": checkpoint,
        "require_scoped_search": True,
        "require_global_review": True,
    }
    with _model_environment(
        model,
        base_url=args.ollama_base_url,
        seed=args.seed,
        num_ctx=args.num_ctx,
        tool_max_tokens=args.tool_max_tokens,
        mapping_max_tokens=args.mapping_max_tokens,
    ):
        try:
            result = run_vor_document_workflow(
                source,
                **common,
                **(
                    {"resume_agent_result": resume_result}
                    if resume_result
                    else {}
                ),
            )
        except BenchmarkInterruption:
            resume_result = _load_document_checkpoint(
                checkpoint_path,
                source_fingerprint=source_fingerprint,
            )
            if not resume_result:
                raise RuntimeError("injected interruption produced no resumable checkpoint")
            emit("resume_started", {
                "checkpointed_rows": len(resume_result.get("selections") or {}),
            })
            progress_work_ids[:] = [
                work_id
                for work_id in ordered_work_ids
                if work_id not in (resume_result.get("selections") or {})
            ]
            active_batch_started.clear()
            result = run_vor_document_workflow(
                source,
                **common,
                resume_agent_result=resume_result,
            )
    elapsed = time.perf_counter() - started
    checkpoint_path.unlink(missing_ok=True)
    (profile_root / "failure.json").unlink(missing_ok=True)
    analysis = analyze_result(result, row_timings=row_timings, qrels=qrels)
    analysis.update({
        "profile": profile,
        "model": model,
        "model_metadata": model_metadata,
        "elapsed_sec": round(elapsed, 3),
        "resume": {
            "interruption_requested_after_rows": args.interrupt_after_rows,
            "interruption_observed": interrupted,
            "interruption_elapsed_sec": round(interruption_elapsed, 3),
            "resumed_from_checkpoint": resume_result is not None,
            "completed_after_resume": bool(result.get("xlsx_path")),
        },
        "artifacts": {
            "xlsx": str(profile_root / "result.xlsx"),
            "workflow_json": str(profile_root / "workflow.json"),
            "tool_events_jsonl": str(event_path),
        },
    })
    _trace_events(
        result,
        profile=profile,
        model=model,
        event_path=event_path,
        elapsed_sec=elapsed,
    )
    _json_dump(profile_root / "analysis.json", analysis)
    return analysis


def _validate_resume_manifest(
    manifest: dict[str, Any],
    *,
    source_sha: str,
    profiles: list[tuple[str, str]],
    args: argparse.Namespace,
) -> None:
    """Reject resume attempts that would mix incompatible benchmark contracts."""
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"resume manifest must use schema {SCHEMA}")
    if str((manifest.get("source") or {}).get("sha256") or "") != source_sha:
        raise ValueError("resume manifest source_sha256 does not match the benchmark source")
    expected_profiles = [
        {"label": label, "model": model} for label, model in profiles
    ]
    if manifest.get("profiles") != expected_profiles:
        raise ValueError("resume manifest profiles do not match requested profiles")
    fixed = dict(manifest.get("fixed_contract") or {})
    expected_fixed = {
        "request": args.request,
        "candidate_limit": args.candidate_limit,
        "max_turns": args.max_turns,
        "batch_size": 1,
        "seed": args.seed,
        "num_ctx": args.num_ctx,
        "tool_max_tokens": args.tool_max_tokens,
        "mapping_max_tokens": args.mapping_max_tokens,
        "require_scoped_search": True,
        "require_global_review": True,
        "interrupt_after_rows": args.interrupt_after_rows,
    }
    mismatched = [
        key for key, value in expected_fixed.items() if fixed.get(key) != value
    ]
    if mismatched:
        raise ValueError(
            "resume manifest fixed contract differs for: " + ", ".join(mismatched)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument(
        "--allow-single-profile",
        action="store_true",
        help="Allow one profile for a timed smoke; full A/B still needs two.",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/model-quality"))
    parser.add_argument(
        "--resume-run",
        type=Path,
        help="Resume compatible profile checkpoints inside an existing run directory.",
    )
    parser.add_argument("--qrels", type=Path)
    parser.add_argument("--request", default=DEFAULT_REQUEST)
    parser.add_argument("--ollama-base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--candidate-limit", type=int, default=8)
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument(
        "--interrupt-after-rows",
        type=int,
        default=0,
        help="0 = no injected crash (default for measurement). >0 proves durable resume only.",
    )
    parser.add_argument("--seed", type=int, default=314159)
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--tool-max-tokens", type=int, default=1800)
    parser.add_argument("--mapping-max-tokens", type=int, default=8000)
    parser.add_argument("--state-root", type=Path)
    args = parser.parse_args(argv)

    if args.state_root:
        os.environ["LES_WINDOWS_STATE_ROOT"] = str(args.state_root.resolve())
    elif os.name == "nt" and not os.getenv("LES_WINDOWS_STATE_ROOT", "").strip():
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        if not local_app_data:
            parser.error("LOCALAPPDATA is unavailable; pass --state-root")
        os.environ["LES_WINDOWS_STATE_ROOT"] = str(Path(local_app_data) / "LES")

    source = args.source.resolve()
    if not source.is_file():
        parser.error(f"source file not found: {source}")
    if source.suffix.casefold() not in {".xlsx", ".xlsm", ".pdf"}:
        parser.error("source must be XLSX, XLSM or PDF")
    profiles = _parse_profiles(
        args.profile or list(DEFAULT_PROFILES),
        allow_single=bool(args.allow_single_profile),
    )
    qrels = {}
    if args.qrels:
        qrels = json.loads(args.qrels.read_text(encoding="utf-8"))
        if qrels.get("schema") != "les.smeta.qrels.v1":
            parser.error("qrels must use schema les.smeta.qrels.v1")

    available = _ollama_models(args.ollama_base_url)
    missing = [model for _, model in profiles if model not in available]
    if missing:
        parser.error("Ollama models are absent: " + ", ".join(missing))
    if os.name == "nt":
        os.environ.setdefault("RERANKER_BACKEND", "sentence_transformers")
    try:
        reranker_evidence = _assert_reranker_ready()
    except Exception as error:
        parser.error(f"reranker preflight failed: {type(error).__name__}: {error}")
    source_sha = _sha256(source)
    if qrels and str(qrels.get("source_sha256") or "") != source_sha:
        parser.error("qrels source_sha256 does not match the benchmark source")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + source_sha[:12]
    new_manifest = {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": _utc_now(),
        "source": {"path": str(source), "sha256": source_sha},
        "runtime_evidence": {
            "system_prompt_sha256": hashlib.sha256(
                smeta_native_skill_prompt().encode("utf-8")
            ).hexdigest(),
            "tool_contract_sha256": hashlib.sha256(
                json.dumps(
                    batch_norm_tools(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "qdrant": _qdrant_evidence(args.qdrant_url),
            "reranker": reranker_evidence,
            "ollama_models": {
                model: {
                    "digest": available[model].get("digest"),
                    "size": available[model].get("size"),
                }
                for _, model in profiles
            },
        },
        "profiles": [{"label": label, "model": model} for label, model in profiles],
        "fixed_contract": {
            "request": args.request,
            "candidate_limit": args.candidate_limit,
            "max_turns": args.max_turns,
            "batch_size": 1,
            "seed": args.seed,
            "num_ctx": args.num_ctx,
            "tool_max_tokens": args.tool_max_tokens,
            "mapping_max_tokens": args.mapping_max_tokens,
            "require_scoped_search": True,
            "require_global_review": True,
            "interrupt_after_rows": args.interrupt_after_rows,
        },
        "qrels": str(args.qrels.resolve()) if args.qrels else "",
        "status": "running",
        "results": [],
    }
    if args.resume_run:
        run_root = args.resume_run.resolve()
        manifest_path = run_root / "manifest.json"
        if not manifest_path.is_file():
            parser.error(f"resume manifest not found: {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            _validate_resume_manifest(
                manifest,
                source_sha=source_sha,
                profiles=profiles,
                args=args,
            )
        except (OSError, json.JSONDecodeError, ValueError) as error:
            parser.error(f"invalid resume run: {error}")
        manifest.setdefault("prior_results", []).extend(manifest.get("results") or [])
        manifest["results"] = []
        manifest["status"] = "running"
        manifest["resumed_at"] = _utc_now()
        manifest.pop("completed_at", None)
        run_id = str(manifest.get("run_id") or run_root.name)
    else:
        run_root = args.out_dir.resolve() / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        manifest = new_manifest
    _json_dump(run_root / "manifest.json", manifest)
    exit_code = 0
    for label, model in profiles:
        try:
            result = _run_profile(
                source=source,
                profile=label,
                model=model,
                run_root=run_root,
                args=args,
                model_metadata=available[model],
                qrels=qrels,
                resume_existing=bool(args.resume_run),
            )
            manifest["results"].append({
                "profile": label,
                "model": model,
                "status": "complete",
                "analysis": str(run_root / label / "analysis.json"),
                "summary": result["summary"],
                "elapsed_sec": result["elapsed_sec"],
                "resume": result["resume"],
            })
        except Exception as error:
            exit_code = 1
            failure = {
                "profile": label,
                "model": model,
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
            }
            manifest["results"].append(failure)
            _json_dump(run_root / label / "failure.json", failure)
        finally:
            try:
                _unload_model(args.ollama_base_url, model)
            except Exception as error:
                manifest.setdefault("runtime_cleanup_warnings", []).append(
                    f"{label}: {type(error).__name__}: {error}"
                )
        _json_dump(run_root / "manifest.json", manifest)
    manifest["status"] = "complete" if exit_code == 0 else "partial_failure"
    manifest["completed_at"] = _utc_now()
    _json_dump(run_root / "manifest.json", manifest)
    print(json.dumps({
        "status": manifest["status"],
        "run_root": str(run_root),
        "results": manifest["results"],
    }, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
