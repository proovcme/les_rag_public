"""Retrieval-подфаза doc-review (СПДС-нормоконтроль Phase 3+): для целей ``kind: retrieval`` ищет в
корпусе проекта (1) ФАКТЫ (устаревший ГОСТ-2020, стадия ПД/РД) и (2) ТЕКСТ требования ГОСТ (цитата).

Оба вкуса — через ``source_adapters`` (lexical реально доступен; vector в sync-пути отложен и честно
UNAVAILABLE). Поиск UNAVAILABLE → факт ``None`` (НЕ утверждаем «не найдено» — анти-галлюцинация), цель
останется ``review_needed``. Факты — детерминированный лексический поиск с source_ref+snippet, 0 LLM.

Результат — словарь ``{rule_id: {"check", "fact", "requirement"}}``, который ``run_review`` маппит в
статус/evidence. Сама ``run_review`` остаётся чистой: подфаза (живой поиск по корпусу) — в оркестраторе.
"""

from __future__ import annotations

from typing import Any

from proxy.services import source_adapters as sa

# Маркеры (адаптер нормализует — убирает пробелы/точки/дефисы, lower). Эвристика: неоднозначно → unknown.
_OUTDATED_2020 = ("21.101-2020", "21.101–2020")
_STAGE_PD = ("проектная документация", "стадия П")
_STAGE_RD = ("рабочая документация", "рабочие чертежи", "стадия Р")


def _search(dataset_id: str, terms: list[str], *, top_k: int = 8) -> sa.SourceAdapterResult:
    return sa.search_lexical_chunks(terms, dataset_ids=[dataset_id] if dataset_id else None, top_k=top_k)


def _hits(res: sa.SourceAdapterResult, *, limit: int = 5) -> list[dict[str, Any]]:
    return [{"kind": "document", "source_ref": m.source_ref, "snippet": (m.snippet or "")[:200]}
            for m in res.matches[:limit]]


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


def _requirement_text(dataset_id: str, clause: str, title: str) -> dict[str, Any] | None:
    """Flavor B: текст пункта ГОСТ из корпуса (если стандарт проиндексирован) → requirement.snippet.
    Лексика по номеру стандарта + значимым словам заголовка цели. Не найдено/UNAVAILABLE → None."""
    words = [w for w in title.replace("/", " ").split() if len(w) > 4][:3]
    res = _search(dataset_id, ["21.101"] + words, top_k=4)
    if res.status != sa.FOUND or not res.matches:
        return None
    m = res.matches[0]
    return {"source_ref": m.source_ref, "snippet": (m.snippet or "")[:300]}


def build_retrieval_evidence(dataset_id: str, review_map) -> dict[str, dict[str, Any]]:
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
            req = _requirement_text(dataset_id, getattr(t, "clause", ""), getattr(t, "title", ""))
        except Exception:  # noqa: BLE001
            fact, req = None, None
        out[t.id] = {"check": check, "fact": fact, "requirement": req}
    return out
