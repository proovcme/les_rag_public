"""Service source registry: visible required data for smeta and normcontrol workflows.

ЛЕС не должен выглядеть как чёрный ящик: этот модуль превращает локальные файлы/датасеты
(`data/gesn_base`, `data/price_base`, `config/normcontrol`, нормативный RAG) в проверяемый
контракт для UI/API/docs.
"""

from __future__ import annotations

import glob
import sqlite3
from pathlib import Path
from typing import Any

import yaml

from backend.rag_config import rag_meta_db_path

DEFAULT_CONFIG = Path("config/service_sources.yaml")


def _file_info(path: str) -> dict[str, Any]:
    p = Path(path)
    return {
        "path": str(p),
        "exists": p.exists(),
        "is_glob": any(ch in str(path) for ch in "*?["),
        "size_bytes": p.stat().st_size if p.exists() and p.is_file() else 0,
    }


def _glob_infos(pattern: str) -> list[dict[str, Any]]:
    matches = sorted(glob.glob(pattern))
    if not matches:
        return [{**_file_info(pattern), "matches": 0}]
    return [{**_file_info(m), "matches": len(matches)} for m in matches]


def _load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("sources", [])
    return data


def _status(required_mode: str, present: bool) -> str:
    if present:
        return "ok"
    return "missing_blocking" if required_mode == "blocking" else "missing_degraded"


def _parquet_rows(path: str) -> int | None:
    try:
        import pandas as pd

        return int(len(pd.read_parquet(path)))
    except Exception:
        return None


def _dataset_hits(query: dict[str, Any] | None) -> dict[str, Any]:
    if not query:
        return {"datasets": [], "documents": 0}
    domains = [str(x) for x in query.get("domains") or []]
    needles = [str(x).casefold() for x in query.get("name_contains") or [] if str(x).strip()]
    try:
        with sqlite3.connect(rag_meta_db_path()) as conn:
            rows = conn.execute(
                """
                SELECT d.dataset_id, COALESCE(ds.name,''), COALESCE(d.file_name,''), COALESCE(d.domain,'')
                FROM documents d
                LEFT JOIN datasets ds ON ds.id = d.dataset_id
                """
            ).fetchall()
    except Exception:
        return {"datasets": [], "documents": 0, "error": "meta_db_unavailable"}
    by_ds: dict[str, dict[str, Any]] = {}
    docs = 0
    for ds_id, ds_name, file_name, domain in rows:
        hay = f"{ds_name} {file_name} {domain}".casefold()
        domain_ok = not domains or domain in domains
        needle_ok = not needles or any(n in hay for n in needles)
        if not (domain_ok or needle_ok):
            continue
        docs += 1
        rec = by_ds.setdefault(str(ds_id), {"id": str(ds_id), "name": ds_name or str(ds_id), "documents": 0})
        rec["documents"] += 1
    return {"datasets": sorted(by_ds.values(), key=lambda x: x["name"]), "documents": docs}


def _facts_for_source(source_id: str, files: list[dict[str, Any]], dataset: dict[str, Any]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    existing = [f for f in files if f.get("exists")]
    if source_id == "gesn_base":
        for f in existing:
            if f["path"].endswith(".parquet"):
                rows = _parquet_rows(f["path"])
                if rows is not None:
                    facts.setdefault("parquet_rows", 0)
                    facts["parquet_rows"] += rows
        try:
            from proxy.services.gesn_service import load_base_norms, load_norms

            facts["base_norms"] = len(load_base_norms())
            facts["seed_norms"] = len(load_norms())
        except Exception:
            pass
    elif source_id == "fgis_price_base":
        facts["pricebooks"] = len(existing)
        total = 0
        for f in existing:
            rows = _parquet_rows(f["path"])
            if rows:
                total += rows
        if total:
            facts["price_rows"] = total
    elif source_id == "normcontrol_spds_rulepack":
        try:
            from proxy.services.normcontrol_review_map_service import load_review_map

            m = load_review_map("gost_r_21_101_2026")
            facts["standard"] = m.standard
            facts["targets"] = len(m.targets)
        except Exception:
            pass
    elif source_id == "normcontrol_spds_rag":
        facts["datasets"] = len(dataset.get("datasets") or [])
        facts["documents"] = dataset.get("documents", 0)
    return facts


def service_sources(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    cfg = _load_config(path)
    out: list[dict[str, Any]] = []
    totals = {"ok": 0, "missing_blocking": 0, "missing_degraded": 0}
    for src in cfg.get("sources", []):
        files: list[dict[str, Any]] = []
        for p in src.get("paths") or []:
            files.extend(_glob_infos(str(p)))
        dataset = _dataset_hits(src.get("dataset_query"))
        has_files = any(f.get("exists") for f in files) if files else False
        has_dataset = bool(dataset.get("documents"))
        present = has_files or has_dataset
        status = _status(str(src.get("status_if_missing") or "degraded"), present)
        totals[status] = totals.get(status, 0) + 1
        item = {
            "id": src.get("id"),
            "domain": src.get("domain"),
            "label": src.get("label"),
            "status": status,
            "requiredness": src.get("status_if_missing", "degraded"),
            "files": files,
            "dataset": dataset,
            "accepted_files": src.get("accepted_files") or [],
            "needed_for": src.get("needed_for") or [],
            "operator_hint": src.get("operator_hint") or "",
        }
        item["facts"] = _facts_for_source(str(item["id"]), files, dataset)
        out.append(item)
    return {
        "schema": "service_sources_v1",
        "title": (cfg.get("meta") or {}).get("title", "Служебные источники Л.Е.С."),
        "version": (cfg.get("meta") or {}).get("version", 1),
        "summary": {"total": len(out), **totals},
        "sources": out,
    }


def service_source(source_id: str, path: Path | str = DEFAULT_CONFIG) -> dict[str, Any] | None:
    for src in service_sources(path).get("sources", []):
        if src.get("id") == source_id:
            return src
    return None
