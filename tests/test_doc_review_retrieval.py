"""Retrieval-подфаза doc-review: факты корпуса (устаревший ГОСТ-2020 / стадия) + текст требования.

run_review остаётся чистой (evidence инъектируется); build_retrieval_evidence — маппинг лексического
адаптера (монипатч, офлайн, без живого индекса). Анти-галлюцинация: поиск недоступен → review_needed.
"""

from proxy.services import doc_review_retrieval_service as drr
from proxy.services import doc_review_service as dr
from proxy.services import source_adapters as sa
from proxy.services.document_set_model import build_document_set
from proxy.services.normcontrol_review_map_service import load_review_map

RMAP = load_review_map("gost_r_21_101_2026")
DS = build_document_set(["12-АР-1.pdf", "12-КР-2.pdf"])
D0 = "G21.101-2026-D0-002"   # outdated_standard_in_corpus
D1 = "G21.101-2026-D1-010"   # project_stage_detect


def _item(rule_id, retrieval_evidence=None):
    items = dr.run_review(DS, RMAP, retrieval_evidence=retrieval_evidence)
    return next(i for i in items if i.rule_id == rule_id)


# ── run_review: маппинг evidence → статус ─────────────────────────────────────

def test_retrieval_none_keeps_review_needed():
    # без подфазы retrieval-цели остаются review_needed (фолбэк, back-compat)
    assert _item(D0).status == dr.S_REVIEW_NEEDED
    assert _item(D1).status == dr.S_REVIEW_NEEDED


def test_outdated_standard_found_is_computed_issue():
    ev = {D0: {"check": "outdated_standard_in_corpus",
               "fact": {"found": True, "hits": [{"kind": "document",
                        "source_ref": "ds/old.pdf#chunk3", "snippet": "ГОСТ Р 21.101-2020"}]},
               "requirement": None}}
    it = _item(D0, ev)
    assert it.status == dr.S_COMPUTED_ISSUE
    assert it.document_evidence[0]["source_ref"] == "ds/old.pdf#chunk3"
    assert it.computed_check["status"] == "ok"


def test_outdated_standard_not_found_is_supported():
    ev = {D0: {"check": "outdated_standard_in_corpus", "fact": {"found": False, "hits": []},
               "requirement": None}}
    assert _item(D0, ev).status == dr.S_SUPPORTED


def test_outdated_standard_unavailable_is_review_needed():
    # поиск недоступен (fact None) → НЕ утверждаем «не найдено», остаёмся review_needed
    ev = {D0: {"check": "outdated_standard_in_corpus", "fact": None, "requirement": None}}
    assert _item(D0, ev).status == dr.S_REVIEW_NEEDED


def test_stage_detected_is_supported():
    ev = {D1: {"check": "project_stage_detect",
               "fact": {"stage": "ПД", "hits": [{"kind": "document",
                        "source_ref": "ds/a.pdf#chunk1", "snippet": "проектная документация"}]},
               "requirement": None}}
    it = _item(D1, ev)
    assert it.status == dr.S_SUPPORTED and "ПД" in it.model_note


def test_stage_unknown_is_manual():
    ev = {D1: {"check": "project_stage_detect", "fact": {"stage": "unknown", "hits": []},
               "requirement": None}}
    assert _item(D1, ev).status == dr.S_MANUAL


def test_requirement_text_fills_snippet():
    # flavor B: текст требования из корпуса → requirement.snippet заполнен (вместо пустого)
    ev = {D1: {"check": "project_stage_detect", "fact": {"stage": "ПД", "hits": []},
               "requirement": {"source_ref": "ds/gost.pdf#chunk7", "snippet": "4 Стадия документации …"}}}
    it = _item(D1, ev)
    assert it.requirement["source_ref"] == "ds/gost.pdf#chunk7"
    assert "Стадия" in it.requirement["snippet"]


# ── build_retrieval_evidence: маппинг лексического адаптера ────────────────────

def _fake(status, refs=()):
    return sa.SourceAdapterResult(
        status, sa.KIND_LEXICAL,
        matches=[sa.AdapterMatch(sa.KIND_LEXICAL, r, snippet="snip " + r) for r in refs])


def test_build_evidence_outdated_found(monkeypatch):
    monkeypatch.setattr(sa, "search_lexical_chunks",
                        lambda terms, **k: _fake(sa.FOUND, ["ds/x.pdf#chunk1"]))
    ev = drr.build_retrieval_evidence("ds", RMAP)
    assert ev[D0]["fact"]["found"] is True
    assert ev[D0]["fact"]["hits"][0]["source_ref"] == "ds/x.pdf#chunk1"


def test_build_evidence_outdated_not_found(monkeypatch):
    monkeypatch.setattr(sa, "search_lexical_chunks", lambda terms, **k: _fake(sa.NOT_FOUND))
    ev = drr.build_retrieval_evidence("ds", RMAP)
    assert ev[D0]["fact"]["found"] is False


def test_build_evidence_unavailable_is_none(monkeypatch):
    # индекс выключен/недоступен → fact None (не врём «не найдено»)
    monkeypatch.setattr(sa, "search_lexical_chunks", lambda terms, **k: _fake(sa.UNAVAILABLE))
    ev = drr.build_retrieval_evidence("ds", RMAP)
    assert ev[D0]["fact"] is None


def test_build_evidence_empty_dataset_is_empty():
    assert drr.build_retrieval_evidence("", RMAP) == {}
