"""Service source registry: visible required data for smeta and normcontrol workflows.

ЛЕС не должен выглядеть как чёрный ящик: этот модуль превращает локальные файлы/датасеты
(`data/gesn_base`, `data/price_base`, `config/normcontrol`, нормативный RAG) в проверяемый
контракт для UI/API/docs.
"""

from __future__ import annotations

import glob
import json
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


def _folder_info(path: str) -> dict[str, Any]:
    p = Path(path)
    return {
        "path": str(p),
        "exists": p.exists() and p.is_dir(),
    }


def _folders_for_source(src: dict[str, Any], files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    configured = [str(x) for x in src.get("folders") or [] if str(x).strip()]
    folders = configured[:]
    if not folders:
        for f in files:
            raw = str(f.get("path") or "").strip()
            if not raw:
                continue
            if any(ch in raw for ch in "*?["):
                folders.append(str(Path(raw).parent))
            else:
                folders.append(str(Path(raw).parent if Path(raw).suffix else Path(raw)))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for folder in folders:
        if folder in seen:
            continue
        seen.add(folder)
        out.append(_folder_info(folder))
    return out


def _glob_matches(pattern: str) -> list[str]:
    return sorted(glob.glob(pattern, recursive="**" in pattern))


def _glob_infos(pattern: str) -> list[dict[str, Any]]:
    matches = _glob_matches(pattern)
    if not matches:
        return [{**_file_info(pattern), "matches": 0}]
    return [{**_file_info(m), "matches": len(matches)} for m in matches]


def _load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("sources", [])
    return data


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def _required_document_manifest(src: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summary = {"ready": 0, "partial": 0, "missing_blocking": 0, "missing_degraded": 0}
    for req in src.get("required_documents") or []:
        preferred_paths = [str(x) for x in req.get("preferred_paths") or [] if str(x).strip()]
        raw_paths = [str(x) for x in req.get("raw_paths") or [] if str(x).strip()]
        preferred_hits = [m for pattern in preferred_paths for m in _glob_matches(pattern)]
        raw_hits = [m for pattern in raw_paths for m in _glob_matches(pattern)]
        requiredness = str(req.get("requiredness") or "degraded")
        if preferred_hits:
            status = "ready"
        elif raw_hits:
            status = "partial"
        else:
            status = "missing_blocking" if requiredness == "blocking" else "missing_degraded"
        summary[status] = summary.get(status, 0) + 1
        rows.append(
            {
                "id": req.get("id"),
                "label": req.get("label") or req.get("id"),
                "status": status,
                "requiredness": requiredness,
                "preferred_files": req.get("preferred_files") or [],
                "accepted_files": req.get("accepted_files") or [],
                "preferred_paths": preferred_paths,
                "raw_paths": raw_paths,
                "found_preferred": preferred_hits[:50],
                "found_raw": raw_hits[:50],
                "found_preferred_count": len(preferred_hits),
                "found_raw_count": len(raw_hits),
                "needed_for": req.get("needed_for") or [],
            }
        )
    return {
        "schema": "service_source_required_documents_v1",
        "summary": {"total": len(rows), **summary},
        "items": rows,
    }


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
            elif Path(f["path"]).name.startswith("les_smeta_base") and f["path"].endswith("_manifest.json"):
                manifest = _read_json(Path(f["path"]))
                output = manifest.get("output") or {}
                excluded = manifest.get("excluded") or {}
                if output:
                    facts["structured_norms"] = output.get("norms")
                    facts["structured_resources"] = output.get("resources")
                if excluded:
                    facts["excluded_norms_missing_name_or_unit"] = excluded.get("norms_missing_name_or_unit")
        try:
            from proxy.services.gesn_service import load_base_norms, load_norms

            facts["base_norms"] = len(load_base_norms())
            facts["seed_norms"] = len(load_norms())
        except Exception:
            pass
    elif source_id == "fgis_price_base":
        pricebooks = [f for f in existing if str(f.get("path") or "").endswith(".parquet")]
        facts["pricebooks"] = len(pricebooks)
        total = 0
        for f in pricebooks:
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
    totals = {"ok": 0, "missing_blocking": 0, "missing_degraded": 0, "quarantined_blocking": 0}
    for src in cfg.get("sources", []):
        files: list[dict[str, Any]] = []
        for p in src.get("paths") or []:
            files.extend(_glob_infos(str(p)))
        dataset = _dataset_hits(src.get("dataset_query"))
        required_documents = _required_document_manifest(src)
        req_summary = required_documents.get("summary") or {}
        has_files = any(f.get("exists") for f in files) if files else False
        has_dataset = bool(dataset.get("documents"))
        present = has_files or has_dataset
        if req_summary.get("total"):
            if int(req_summary.get("missing_blocking") or 0):
                status = "missing_blocking"
            elif int(req_summary.get("missing_degraded") or 0) or int(req_summary.get("partial") or 0):
                status = "missing_degraded"
            else:
                status = "ok"
        else:
            status = _status(str(src.get("status_if_missing") or "degraded"), present)
        integrity: dict[str, Any] = {}
        if src.get("integrity_required"):
            from proxy.smeta_core.integrity import normative_base_integrity

            configured_paths = [str(value) for value in (src.get("paths") or [])]
            base_path = str(src.get("structured_base_path") or (configured_paths[0] if configured_paths else ""))
            manifest_path = str(
                src.get("base_manifest_path")
                or (configured_paths[1] if len(configured_paths) > 1 else "")
            )
            integrity = normative_base_integrity(
                base_path=base_path,
                manifest_path=manifest_path,
                report_path=str(src.get("integrity_report") or "data/smeta_base/les_smeta_base_integrity.json"),
            )
            if present and not integrity.get("trusted_for_pricing"):
                status = "quarantined_blocking"
        totals[status] = totals.get(status, 0) + 1
        item = {
            "id": src.get("id"),
            "domain": src.get("domain"),
            "label": src.get("label"),
            "status": status,
            "requiredness": src.get("status_if_missing", "degraded"),
            "files": files,
            "folders": _folders_for_source(src, files),
            "dataset": dataset,
            "accepted_files": src.get("accepted_files") or [],
            "needed_for": src.get("needed_for") or [],
            "operator_hint": src.get("operator_hint") or "",
            "operator_action": src.get("operator_action") or "",
            "process_label": src.get("process_label") or "Проверить источник",
            "required_documents": required_documents,
            "integrity": integrity,
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


def process_service_source(source_id: str, path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    """Operator-facing "play" action for a service source.

    v0.24.0.2 intentionally keeps this action non-destructive: it refreshes the registry contract and
    tells the operator what is ready/missing. Real importers/reindexers stay behind explicit workflow
    screens because a service-source button must never silently mutate a live knowledge base.
    """
    item = service_source(source_id, path)
    if item is None:
        return {"ok": False, "source_id": source_id, "status": "not_found", "message": "Источник данных не найден."}
    status = str(item.get("status") or "")
    folders = [f["path"] for f in item.get("folders") or [] if f.get("path")]
    missing_files = [f["path"] for f in item.get("files") or [] if not f.get("exists")]
    found_files = [f["path"] for f in item.get("files") or [] if f.get("exists")]
    required_documents = item.get("required_documents") or {}
    req_summary = required_documents.get("summary") or {}
    label = item.get("label") or source_id
    if req_summary.get("total"):
        ready = int(req_summary.get("ready") or 0)
        partial = int(req_summary.get("partial") or 0)
        missing = int(req_summary.get("missing_blocking") or 0) + int(req_summary.get("missing_degraded") or 0)
        if missing:
            msg = f"{label}: Play проверил состав. Готово {ready}, частично {partial}, не хватает {missing}."
        else:
            msg = f"{label}: Play проверил состав. Готово {ready}, частично {partial}, критичных пропусков нет."
    elif status == "ok":
        msg = f"{label}: источник найден. ЛЕС может использовать эти данные."
    elif status == "quarantined_blocking":
        reasons = "; ".join(str(x) for x in ((item.get("integrity") or {}).get("reasons") or [])[:4])
        msg = (
            f"{label}: файлы найдены, но база помещена в карантин и не может подтверждать "
            f"финальную стоимость. {reasons or 'Нет пройденного semantic integrity report.'}"
        )
    elif status == "missing_blocking":
        where = ", ".join(folders[:3]) or ", ".join(missing_files[:3]) or "служебную папку источника"
        msg = f"{label}: данных нет. Положи нужные файлы в {where} и запусти проверку ещё раз."
    else:
        where = ", ".join(folders[:3]) or ", ".join(missing_files[:3]) or "служебную папку источника"
        msg = f"{label}: источник неполный. ЛЕС продолжит работу с ограничениями; для полной проверки добавь файлы в {where}."
    return {
        "ok": status == "ok",
        "source_id": source_id,
        "status": status,
        "message": msg,
        "folders": folders,
        "missing_files": missing_files,
        "found_files": found_files,
        "facts": item.get("facts") or {},
        "required_documents": required_documents,
        "integrity": item.get("integrity") or {},
    }
