"""Retrieval-подфаза doc-review (СПДС-нормоконтроль Phase 3+): для целей ``kind: retrieval`` ищет в
корпусе проекта (1) ФАКТЫ (устаревший ГОСТ-2020, стадия ПД/РД) и (2) ТЕКСТ требования ГОСТ (цитата).

Оба вкуса — через ``source_adapters`` (lexical реально доступен; vector в sync-пути отложен и честно
UNAVAILABLE). Поиск UNAVAILABLE → факт ``None`` (НЕ утверждаем «не найдено» — анти-галлюцинация), цель
останется ``review_needed``. Факты — детерминированный лексический поиск с source_ref+snippet, 0 LLM.

Результат — словарь ``{rule_id: {"check", "fact", "requirement"}}``, который ``run_review`` маппит в
статус/evidence. Сама ``run_review`` остаётся чистой: подфаза (живой поиск по корпусу) — в оркестраторе.
"""

from __future__ import annotations

import os
import re
import sqlite3
from typing import Any

from proxy.services import source_adapters as sa

# Маркеры (адаптер нормализует — убирает пробелы/точки/дефисы, lower). Эвристика: неоднозначно → unknown.
_OUTDATED_2020 = ("21.101-2020", "21.101–2020")
_STAGE_PD = ("проектная документация", "стадия П")
_STAGE_RD = ("рабочая документация", "рабочие чертежи", "стадия Р")
_CURRENT_STANDARD = "ГОСТ Р 21.101-2026"
_CURRENT_STANDARD_TERMS = ("21.101-2026", "21.101 2026", "21.101_2026")
_SPDS_DATASET_NAME = "NTD_SPDS_Index"
_SPDS_DOMAINS = {"NTD_SPDS", "NTD_GENERAL"}


def _search(dataset_id: str, terms: list[str], *, top_k: int = 8) -> sa.SourceAdapterResult:
    return sa.search_lexical_chunks(terms, dataset_ids=[dataset_id] if dataset_id else None, top_k=top_k)


def _hits(res: sa.SourceAdapterResult, *, limit: int = 5) -> list[dict[str, Any]]:
    return [{"kind": "document", "source_ref": m.source_ref, "snippet": (m.snippet or "")[:200]}
            for m in res.matches[:limit]]


def _norm(value: object) -> str:
    return re.sub(r"[\s._–—-]+", "", str(value or "").casefold().replace("ё", "е"))


def _has_current_standard(value: object) -> bool:
    text = str(value or "").casefold().replace("ё", "е")
    compact = _norm(text)
    return ("211012026" in compact) or any(_norm(term) in compact for term in _CURRENT_STANDARD_TERMS)


def _configured_normative_dataset_ids() -> list[str]:
    raw = os.getenv("LES_NORMCONTROL_SPDS_DATASET_IDS", "")
    out: list[str] = []
    for item in raw.split(","):
        ds = item.strip()
        if ds and ds not in out:
            out.append(ds)
    return out


def _normative_standard_dataset_ids() -> list[str]:
    """Find datasets that explicitly contain the current ГОСТ Р 21.101-2026 source.

    Project facts still search the project dataset. Requirement text searches these normative datasets,
    so an indexed ГОСТ in ``NTD_SPDS_Index`` becomes a real source instead of an accidental project hit.
    """
    configured = _configured_normative_dataset_ids()
    if configured:
        return configured
    try:
        from backend.rag_config import rag_meta_db_path

        with sqlite3.connect(rag_meta_db_path()) as conn:
            rows = conn.execute(
                """
                SELECT d.dataset_id, COALESCE(ds.name,''), COALESCE(d.file_name,''), COALESCE(d.domain,'')
                FROM documents d
                LEFT JOIN datasets ds ON ds.id = d.dataset_id
                """
            ).fetchall()
    except Exception:
        return []

    ranked: dict[str, tuple[int, str]] = {}
    for ds_id, ds_name, file_name, domain in rows:
        ds = str(ds_id or "").strip()
        if not ds:
            continue
        hay = f"{ds_name} {file_name} {domain}"
        has_current = _has_current_standard(hay)
        in_spds_dataset = str(ds_name or "").strip() == _SPDS_DATASET_NAME
        in_spds_domain = str(domain or "").strip() in _SPDS_DOMAINS
        if not has_current:
            continue
        score = 100
        if in_spds_dataset:
            score += 40
        if in_spds_domain:
            score += 20
        if "2020" in str(file_name or "") and "2026" not in str(file_name or ""):
            score -= 50
        prev = ranked.get(ds)
        if prev is None or score > prev[0]:
            ranked[ds] = (score, str(ds_name or ds))
    return [ds for ds, _ in sorted(ranked.items(), key=lambda item: (-item[1][0], item[1][1], item[0]))]


def _fact_outdated_standard(dataset_id: str) -> dict[str, Any] | None:
    """D0-002: устаревший ГОСТ Р 21.101-2020 в корпусе. UNAVAILABLE → None (искать не смогли)."""
    res = _search(dataset_id, list(_OUTDATED_2020))
    if res.status == sa.UNAVAILABLE:
        return None
    if res.status == sa.FOUND:
        return {"found": True, "hits": _hits(res)}
    return {"found": False, "hits": []}


def _fact_stage(dataset_id: str) -> dict[str, Any] | None:
    """D1-010: стадия ПД/РД по маркерам корпуса. И ПД, и РД (или ничего) → unknown → ручное."""
    pd = _search(dataset_id, list(_STAGE_PD))
    rd = _search(dataset_id, list(_STAGE_RD))
    if pd.status == sa.UNAVAILABLE and rd.status == sa.UNAVAILABLE:
        return None
    pd_found, rd_found = pd.status == sa.FOUND, rd.status == sa.FOUND
    if pd_found and not rd_found:
        return {"stage": "ПД", "hits": _hits(pd)}
    if rd_found and not pd_found:
        return {"stage": "РД", "hits": _hits(rd)}
    if pd_found and rd_found:
        return {"stage": "unknown", "hits": _hits(pd) + _hits(rd), "note": "признаки и ПД, и РД"}
    return {"stage": "unknown", "hits": []}


def _requirement_text(dataset_id: str, clause: str, title: str,
                      normative_dataset_ids: list[str] | None = None) -> dict[str, Any] | None:
    """Flavor B: текст пункта ГОСТ из нормативного RAG → requirement.snippet.

    Основной путь ищет актуальный ГОСТ Р 21.101-2026 в ``NTD_SPDS_Index``/SPDS-домене. Проектный dataset
    используется только как legacy fallback, чтобы старые офлайн-тесты/локальные стенды без NTD не ломались.
    """
    words = [w for w in title.replace("/", " ").split() if len(w) > 4][:3]
    terms = [_CURRENT_STANDARD, "21.101-2026", "21.101"] + ([clause] if clause else []) + words
    search_datasets = (
        list(_normative_standard_dataset_ids())
        if normative_dataset_ids is None
        else list(normative_dataset_ids)
    )
    tried_normative = False
    for ds in search_datasets:
        tried_normative = True
        res = _search(ds, terms, top_k=4)
        if res.status == sa.FOUND and res.matches:
            m = res.matches[0]
            return {
                "source_ref": m.source_ref,
                "snippet": (m.snippet or "")[:300],
                "standard": _CURRENT_STANDARD,
                "source_dataset_id": ds,
                "source_role": "normative_spds_rag",
            }
    if tried_normative:
        return None
    res = _search(dataset_id, ["21.101"] + words, top_k=4)
    if res.status != sa.FOUND or not res.matches:
        return None
    m = res.matches[0]
    return {"source_ref": m.source_ref, "snippet": (m.snippet or "")[:300], "source_role": "legacy_project_dataset"}


def build_retrieval_evidence(dataset_id: str, review_map,
                             normative_dataset_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Для каждой цели ``kind: retrieval`` — факт в корпусе (по check) + текст требования (flavor B).
    Ключ результата — ``rule_id``. Пустой/UNAVAILABLE поиск → ``fact=None`` → цель останется
    ``review_needed`` в ``run_review`` (фолбэк сохранён, регрессии нет)."""
    out: dict[str, dict[str, Any]] = {}
    if not dataset_id:
        return out
    for t in getattr(review_map, "targets", []):
        if getattr(t, "kind", "") != "retrieval":
            continue
        check = getattr(t, "check", "")
        fact: dict[str, Any] | None = None
        req: dict[str, Any] | None = None
        try:
            if check == "outdated_standard_in_corpus":
                fact = _fact_outdated_standard(dataset_id)
            elif check == "project_stage_detect":
                fact = _fact_stage(dataset_id)
            # spds_applicability и прочие retrieval-цели пока без факта (review_needed)
            req = _requirement_text(
                dataset_id,
                getattr(t, "clause", ""),
                getattr(t, "title", ""),
                normative_dataset_ids=normative_dataset_ids,
            )
        except Exception:  # noqa: BLE001
            fact, req = None, None
        out[t.id] = {"check": check, "fact": fact, "requirement": req}
    return out
