"""Typed expansion and exact whole-preview fallback share the existing budget."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from proxy.services import model_research_tool_service as research
from proxy.services.chat_evidence_application_service import (
    _model_rag_full_groups, build_model_rag_evidence_groups,
    _model_rag_exact_card_key,
)
from proxy.services.model_rag_grouped_evidence_service import (
    _plan_single_body_page, _render, normative_card_identity,
)
from proxy.services.model_resource_reference_service import shown_resource_record


def _card(*, padding=0):
    return {"norm_key": "ГЭСНм:08-02-001-01", "norm_code": "ГЭСНм08-02-001-01",
            "title": "Исходная работа", "measure_unit": "100 м", "edition": "ФСНБ fixture",
            "base_type": "ГЭСНм", "work_steps": ["Шаг 1", "Условие из карточки"],
            "source_ref": "source.xml#guid=norm-guid", "resource_count": 19,
            "resource_preview": [{"kind": "material", "code": "0", "name": "Обзор", "unit": "кг"}],
            "resources": [{"kind": "material", "code": str(i), "name": "Ресурс" + "Х" * padding,
                           "unit": "кг", "per_unit": i/4, "source_ref": f"source.xml#guid=r{i}"}
                          for i in range(19)],
            "resources_returned": 19, "resources_complete": True, "resource_consumption_known": True,
            "hydration_status": "ok", "hydration_origin": "application_typed_exact",
            "normative_base_sha256": "a" * 64, "source_hash_basis": "normative_sqlite_base_bytes"}


def test_shared_factory_emits_full_retained_resources_without_claiming_model_read():
    card = _card()
    chunk = research._norm_search_chunk(card, score=6.0, matched_before_cap=24)
    assert chunk.content == research._full_norm_card_content(card)
    assert chunk.meta["resource_preview"] == card["resource_preview"]
    assert chunk.meta["resources"][0]["per_unit"] == 0
    assert len(chunk.meta["resources"]) == 19
    assert chunk.meta["exact_card_read"] is True
    assert chunk.meta["hydration_origin"] == "application_typed_exact"
    assert "model_requested_read" not in chunk.meta
    assert chunk.meta["hydration_preview_sha256"] == hashlib.sha256(research._norm_card_content(card).encode("utf-8")).hexdigest()


def test_physical_full_fit_delivers_full_card_and_resource_slots():
    card = _card()
    chunk = research._norm_search_chunk(card, score=1, matched_before_cap=1)
    groups, delivered, deferred = build_model_rag_evidence_groups(
        [("Модельный запрос без изменений", [chunk])], max_chars=200000, hits_per_query=6,
    )
    assert not deferred
    assert delivered[0].content == research._full_norm_card_content(card)
    assert delivered[0].meta["normative_card_complete"] is True
    assert delivered[0].meta["exact_card_read"] is True
    assert delivered[0].meta["model_query_text"] == "Модельный запрос без изменений"
    assert shown_resource_record(delivered[0].meta, delivered[0].content, 19) is not None


def test_no_full_first_group_capacity_retains_entire_original_preview_page():
    card = _card(padding=600)
    chunks = [research._norm_search_chunk(card, score=6-i, matched_before_cap=35) for i in range(6)]
    query_hits = [("Дословный запрос модели", chunks)]
    old_chunks = [SimpleNamespace(content=research._norm_card_content(card), doc_name=chunk.doc_name,
                                   score=chunk.score, meta=research.norm_preview_metadata(chunk.meta))
                  for chunk in chunks]
    old_groups, _ = _model_rag_full_groups([(query_hits[0][0], old_chunks)], hits_per_query=6)
    old_page = _render(old_groups, {f"Q1.H{i}" for i in range(1,7)}, 1)
    budget = old_page.rendered_chars
    hydrated_groups, _ = _model_rag_full_groups(query_hits, hits_per_query=6)
    assert not _plan_single_body_page(hydrated_groups, budget).included_count

    groups, delivered, deferred = build_model_rag_evidence_groups(query_hits, max_chars=budget, hits_per_query=6)

    assert groups == old_page.groups
    assert sum(len(part) for part in groups) <= budget
    assert not deferred
    assert [row.meta["model_evidence_ref"] for row in delivered] == [f"Q1.H{i}" for i in range(1,7)]
    for row in delivered:
        assert row.content == research._norm_card_content(card)
        assert row.meta["normative_card_complete"] is False
        assert row.meta["exact_card_read"] is False
        assert row.meta["full_card_deferred_reason"] == "capacity"
        assert row.meta["normative_base_sha256"] == card["normative_base_sha256"]
        assert "resources" not in row.meta
        assert shown_resource_record(row.meta, row.content, 1) is None
    assert '"available_read"' in "\n".join(groups)


def test_legacy_normative_identity_hash_remains_exact_without_new_generation():
    meta = {key: _card()[key] for key in ("norm_key", "norm_code", "edition", "base_type", "source_ref")}
    fields = {name: meta.get(name) for name in ("norm_key", "source_ref", "source_sha256", "edition", "base_type")}
    fields["norm_code"] = meta["norm_code"].upper()
    old_hash = "norm_card_" + hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    assert normative_card_identity(meta) == old_hash
    assert normative_card_identity({**meta, "normative_base_sha256": ""}) == old_hash
    assert normative_card_identity({**meta, "normative_base_sha256": "a" * 64}) != old_hash


def test_shared_model_retriever_enables_hydration_without_altering_native_query(monkeypatch):
    from proxy.smeta_core import norm_browser
    calls = []
    query = "Кириллица 'дословно' 100 м"
    def retrieve(queries, **kwargs):
        calls.append((queries, kwargs))
        return {query: {"cards": [], "retrieval_trace": {}}}
    monkeypatch.setattr(norm_browser, "browse_norms_many", retrieve)
    assert research.retrieve_smeta_norm_cards(query, limit=6) == {"cards": [], "retrieval_trace": {}}
    assert calls == [([query], {"limit": 6, "rerank": True, "expand_queries": False, "hydrate_resources": True})]


def test_equal_body_from_different_base_revision_cannot_share_exact_evidence():
    card = _card()
    a = research._norm_search_chunk(card, score=1, matched_before_cap=1)
    b = SimpleNamespace(content=a.content, doc_name=a.doc_name, score=a.score,
                        meta={**a.meta, "normative_base_sha256": "b" * 64})
    assert _model_rag_exact_card_key(a) != _model_rag_exact_card_key(b)
    legacy = SimpleNamespace(content=a.content, doc_name=a.doc_name, score=a.score,
                             meta={key: value for key, value in a.meta.items() if key != "normative_base_sha256"})
    empty = SimpleNamespace(content=a.content, doc_name=a.doc_name, score=a.score,
                            meta={**legacy.meta, "normative_base_sha256": ""})
    assert _model_rag_exact_card_key(legacy) == _model_rag_exact_card_key(empty)


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_generation", [None, "b" * 64, "a" * 64])
@pytest.mark.parametrize("pointer_basis", ["normative_base_sha256", "retained_normative_base_sha256"])
async def test_native_read_known_generation_is_verified_for_alias_and_exact_key(returned_generation, pointer_basis, monkeypatch):
    card = _card()
    monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **_kw: [])
    returned = {**card}
    if returned_generation is None:
        returned.pop("normative_base_sha256")
    else:
        returned["normative_base_sha256"] = returned_generation
    calls = []
    def reader(**args):
        calls.append(args)
        return {"status": "ok", "card": returned, "warnings": [], "missing": []}
    service = research.ModelResearchToolService(
        retrieve=lambda **_kw: pytest.fail("no new search"), frozen_dataset_ids=(), retrieval_kwargs={},
        fallback=lambda *_a: pytest.fail("no fallback"), norm_card_reader=reader,
    )
    chunk = research._norm_search_chunk(card, score=1, matched_before_cap=1)
    if pointer_basis == "retained_normative_base_sha256":
        chunk.meta["retained_normative_base_sha256"] = chunk.meta.pop("normative_base_sha256")
    _, shown, _ = build_model_rag_evidence_groups([("literal query", [chunk])], max_chars=200000, hits_per_query=6)
    shown[0].meta.update(model_evidence_ref="Q1.H1", model_inventory_delivery_status="delivered",
                         model_delivery_status="delivered")
    service.register_shown_norm_cards(shown)
    for args in ({"evidence_ref": "Q1.H1"}, {"norm_key": card["norm_key"], "norm_code": card["norm_code"]}):
        result = await service.execute({"tool": "read_norm_card", "args": args})
        if returned_generation == card["normative_base_sha256"]:
            assert result.payload["status"] == "ok"
            assert result.chunks[0].meta["normative_base_sha256"] == returned_generation
        else:
            assert result.payload["status"] == "conflict"
            assert result.chunks == ()
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_failed_expansion_warning_is_visible_without_false_missing_search(monkeypatch):
    card = _card()
    for key in ("resources", "resources_returned", "resources_complete", "resource_consumption_known", "normative_base_sha256"):
        card.pop(key)
    card.update(hydration_status="source_changed", hydration_warnings=["base changed during exact snapshot"],
                retained_normative_base_sha256="a" * 64)
    monkeypatch.setattr(research.nr_sp_service, "model_candidates", lambda **_kw: [])
    query = "literal model query"
    calls = []
    def retrieve(actual, *, limit):
        calls.append((actual, limit))
        return {"cards": [card], "retrieval_trace": {"rag": {"status": "ok"}}}
    service = research.ModelResearchToolService(
        retrieve=lambda **_kw: pytest.fail("no alternate search"), frozen_dataset_ids=(), retrieval_kwargs={},
        fallback=lambda *_a: pytest.fail("no fallback search"), smeta_norm_retrieve=retrieve,
    )
    result = await service.execute({"tool": "search_sources", "args": {"q": query}})
    assert calls == [(query, 6)]
    assert result.payload["status"] == "ok"
    assert result.payload["result"]["count"] == 1
    assert result.payload["warnings"] == ["base changed during exact snapshot"]
    assert result.chunks[0].content == research._norm_card_content(card)
    assert result.chunks[0].meta["retained_normative_base_sha256"] == "a" * 64
    assert "normative_base_sha256" not in result.chunks[0].meta
    assert "resources" not in result.chunks[0].meta
