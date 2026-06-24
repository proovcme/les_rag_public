"""Unified Construction Harness v0.8 — operational hardening.

Actionable no-scope MISSING (говорит КАКОЙ источник нужен), v0_8 unified_trace через живой
`_run_chat`, smoke-набор. Flag OFF не покрывается (живой RAG нужен бэкенд) — за него 228 chat-тестов.
"""

from types import SimpleNamespace

import pytest

import proxy.routers.chat as chat_router
from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services import resource_cost_service as rc
from proxy.services.evidence_contract import EvidenceType

MONEY = 1.0


@pytest.fixture
def live_chat(monkeypatch):
    monkeypatch.setenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    chat_router.set_chat_state(chat_router.ChatRouterState(
        rag_backend=SimpleNamespace(), llm_semaphore=SimpleNamespace(_value=1),
        crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
        chat_metrics={"latency_search": [], "latency_gen": [], "tokens": [], "crag_pass": 0, "crag_fail": 0},
        reranker_available=False, reranker_cls=None, current_mode={"mode": "chat"},
        metrics_cache={"ram_free_gb": 12.0, "swap_pct": 0.0}))
    yield


# ── actionable no-scope MISSING ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,src_kw", [
    ("опиши проект котельная и дай реестр документов", "проектные документ"),
    ("собери предварительную ЛСР по Ф9", "ф9"),
    ("извлеки ВОР", "ф9"),
])
def test_no_scope_actionable_missing(q, src_kw):
    r = u.run_unified_construction_harness(q)        # без dataset_ids
    assert r.total_status == "no_data"
    ad = r.answer_data
    assert ad.get("needs_scope") and src_kw in ad.get("required_source", "").lower()
    # сообщение подсказывает действие
    miss = [it for b in r.evidence_blocks if b.type is EvidenceType.MISSING for it in b.items]
    joined = " ".join(b for it in miss for b in it.blockers).lower()
    assert "проект" in joined and ("dataset" in joined or "датасет" in joined)

def test_asbuilt_no_scope_actionable():
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования")
    assert r.total_status == "no_data"
    miss = [it for b in r.evidence_blocks if b.type is EvidenceType.MISSING for it in b.items]
    txt = " ".join([it.title for it in miss] + [b for it in miss for b in it.blockers]).lower()
    assert ("акт" in txt or "проект" in txt) and ("dataset" in txt or "датасет" in txt or "project_id" in txt)

def test_no_scope_does_not_hallucinate():
    r = u.run_unified_construction_harness("собери ЛСР по Ф9")
    assert r.final_total is None and r.total_status == "no_data"
    # никаких COMPUTED-чисел без источника
    assert not any(b.type is EvidenceType.COMPUTED for b in r.evidence_blocks)


# ── v0_8 trace через живой _run_chat ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_trace_v08_resource(live_chat):
    r = await chat_router._run_chat(chat_router.ChatRequest(question="проверь пример обсчёта"))
    assert r["query_route"]["version"] == "unified_construction_harness_v0_8"
    ut = r["unified_trace"]
    assert ut["version"] == "unified_construction_harness_v0_8"
    assert ut["intent"] == "resource_cost_calc" and ut["total_status"] == "complete"
    assert ut["tools"] and "evidence" in ut and ut["evidence"].get("COMPUTED", 0) > 0

@pytest.mark.asyncio
async def test_live_trace_needs_scope_flag(live_chat):
    r = await chat_router._run_chat(chat_router.ChatRequest(question="дай реестр документов проекта"))
    ut = r["unified_trace"]
    assert ut["intent"] == "project_document_registry"
    assert ut["needs_scope"] is True and ut["total_status"] == "no_data"

@pytest.mark.asyncio
async def test_live_trace_source_scope(live_chat):
    r = await chat_router._run_chat(
        chat_router.ChatRequest(question="найди ОЗК в актах смонтированного оборудования"))
    ut = r["unified_trace"]
    assert ut["intent"] == "asbuilt_extract" and ut["source_scope"] == "asbuilt"
    assert ut["query_terms"] == ["ОЗК"]

@pytest.mark.asyncio
async def test_live_trace_no_mail_body_leak(live_chat):
    # trace не должен содержать тела письма (в mail no_data — только статус)
    r = await chat_router._run_chat(chat_router.ChatRequest(question="что писали по котельной в почте"))
    ut = r["unified_trace"]
    assert ut["intent"] == "mail_entity_search" and ut["total_status"] == "no_data"


# ── smoke-набор (через run_unified + fixture) ────────────────────────────────────────────

def _fixture(tmp_path, ds="kotelnaya"):
    import pandas as pd
    d = tmp_path / ds
    d.mkdir(parents=True)
    for n, sz in [("Котельная_ТМ.pdf", 5000), ("~$tmp.docx", 40)]:
        (d / n).write_bytes(b"x" * sz)
    pd.DataFrame([{"наименование": "Клапан ОЗК-1", "марка": "ОЗК-1", "кол": 4, "ед": "шт", "акт": "А-1"}]
                 ).to_parquet(d / "Акт_смонтированного_оборудования.parquet")
    ch.write_demo_project_doc(tmp_path, dataset_id=ds)
    return ds

def test_smoke_registry_with_scope(tmp_path):
    ds = _fixture(tmp_path)
    r = u.run_unified_construction_harness("опиши проект котельная и дай реестр документов",
                                           dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status in ("complete", "partial") and r.sources

def test_smoke_asbuilt_found_with_scope(tmp_path):
    ds = _fixture(tmp_path)
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete"
    assert next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED).items[0].source_refs

def test_smoke_lsr_with_scope(tmp_path):
    ds = _fixture(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9",
                                           dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete" and r.final_total is not None


# ── регрессии ────────────────────────────────────────────────────────────────────────────

def test_v04_ozk_still_asbuilt_not_norm():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_generic_term_no_dictionary():
    eq = u.extract_source_scoped_query("найди КДУ-7 в актах смонтированного оборудования")
    assert "КДУ-7" in eq.exact_terms

def test_v06_resource_real_workbook_still_validates():
    assert rc.validate_real_workbook()["matches"] is True

def test_v03_unit_gate_still_passes():
    assert ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])["asm_positions"][0]["qty"] == 7.2

def test_resource_grand_complete_via_chat():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < MONEY
