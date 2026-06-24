"""Unified Construction Harness v0.10 — async real adapters (vector/mail) через инжекцию.

backend есть → RETRIEVED с source_refs; backend нет → actionable unavailable; timeout/error → статус,
не краш. Семантический vector без точного термина → weak_related (НЕ «найдено»). Mail read-only,
snippet-only. Нет asyncio.run в running loop. Sync/offline контур не сломан.
"""

from types import SimpleNamespace

import pytest

import proxy.routers.chat as chat_router
from proxy.services import source_adapters as sa
from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services import resource_cost_service as rc
from proxy.services.evidence_contract import EvidenceType

MONEY = 1.0


def _chunk(text, doc="Док.pdf", ds="k", ordn=1):
    return SimpleNamespace(text=text, doc_name=doc, dataset_id=ds, chunk_ord=ordn, score=0.7)


async def _vfn_found(q, dsids):
    return [_chunk("...установлен клапан ОЗК-1...", doc="Акт_смонтированного.pdf")]


async def _vfn_semantic(q, dsids):
    return [_chunk("монтаж вентиляционного оборудования", doc="Акт_смонтированного.pdf")]


async def _vfn_noref(q, dsids):
    return [SimpleNamespace(text="ОЗК-1 есть", doc_name="", dataset_id="")]  # нет ref


async def _vfn_slow(q, dsids):
    import asyncio
    await asyncio.sleep(0.2)
    return [_chunk("ОЗК")]


async def _vfn_boom(q, dsids):
    raise RuntimeError("qdrant down")


async def _mfn(q):
    return SimpleNamespace(items=[{"message_id": "<m1@x>", "subject": "Согласование ОЗК",
                                   "snippet": "прошу согласовать ОЗК-1", "body": "СЕКРЕТ полное тело"}])


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


# ── async vector adapter ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_vector_async_unavailable_no_fn():
    r = await sa.search_vector_chunks_async("нормы ОЗК", vector_fn=None)
    assert r.status == sa.UNAVAILABLE and not r.matches
    assert any("vector_backend_unavailable" in w for w in r.warnings)

@pytest.mark.asyncio
async def test_vector_async_found():
    r = await sa.search_vector_chunks_async("ОЗК", vector_fn=_vfn_found)
    assert r.status == sa.FOUND and r.matches[0].source_ref and r.matches[0].source_kind == sa.KIND_VECTOR

@pytest.mark.asyncio
async def test_vector_async_requires_source_ref():
    r = await sa.search_vector_chunks_async("ОЗК", vector_fn=_vfn_noref)
    assert r.status != sa.FOUND               # чанк без ref → не RETRIEVED (не фейк)

@pytest.mark.asyncio
async def test_vector_async_semantic_is_weak_not_found():
    r = await sa.search_vector_chunks_async("ОЗК", exact_terms=["ОЗК"], require_exact=True, vector_fn=_vfn_semantic)
    assert r.status == sa.WEAK_RELATED and not r.matches    # семантика без термина ≠ найдено

@pytest.mark.asyncio
async def test_vector_async_exact_match():
    r = await sa.search_vector_chunks_async("ОЗК", exact_terms=["ОЗК-1"], require_exact=True, vector_fn=_vfn_found)
    assert r.status == sa.FOUND

@pytest.mark.asyncio
async def test_vector_async_timeout_safe():
    r = await sa.search_vector_chunks_async("ОЗК", vector_fn=_vfn_slow, timeout_s=0.01)
    assert r.status == sa.TIMEOUT and any("vector_timeout" in w for w in r.warnings)

@pytest.mark.asyncio
async def test_vector_async_error_safe():
    r = await sa.search_vector_chunks_async("ОЗК", vector_fn=_vfn_boom)
    assert r.status == sa.ERROR and any("vector_error" in w for w in r.warnings)


# ── async mail adapter (read-only) ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mail_async_unavailable_no_fn():
    r = await sa.retrieve_mail_evidence_async(["ОЗК"], mail_fn=None)
    assert r.status == sa.UNAVAILABLE and any("mail_backend_not_configured" in w for w in r.warnings)

@pytest.mark.asyncio
async def test_mail_async_found_message_id_ref():
    r = await sa.retrieve_mail_evidence_async(["ОЗК"], "ОЗК", mail_fn=_mfn)
    assert r.status == sa.FOUND and r.matches[0].source_ref == "<m1@x>"

@pytest.mark.asyncio
async def test_mail_async_snippet_only_no_full_body():
    r = await sa.retrieve_mail_evidence_async(["ОЗК"], "ОЗК", mail_fn=_mfn)
    # полное тело письма НЕ попадает в матч (только snippet)
    assert "СЕКРЕТ" not in r.matches[0].snippet and "согласовать" in r.matches[0].snippet

def test_mail_async_read_only_no_mutation():
    import inspect
    code = "\n".join(ln for ln in inspect.getsource(sa.retrieve_mail_evidence_async).splitlines()
                     if not ln.strip().startswith(("#", '"', "'")))
    for bad in (".send(", ".push(", ".delete(", ".draft(", "send_email", "create_draft"):
        assert bad not in code


# ── async orchestrator: sync-first + escalate ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_orchestrator_norm_vector_found(tmp_path):
    r = await u.run_unified_construction_harness_async("правила расстановки ОЗК", dataset_ids=["k"],
                                                       storage_root=tmp_path, vector_fn=_vfn_found)
    assert r.total_status == "complete" and r.answer_data["adapter_statuses"]["vector"] == "found"
    assert next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED).items[0].source_refs

@pytest.mark.asyncio
async def test_async_orchestrator_source_scoped_semantic_weak(tmp_path):
    (tmp_path / "k").mkdir()
    import pandas as pd
    pd.DataFrame([{"наименование": "Насос К-100"}]).to_parquet(tmp_path / "k" / "Акт_смонтированного_оборудования.parquet")
    r = await u.run_unified_construction_harness_async("найди ОЗК в актах смонтированного оборудования",
                                                       dataset_ids=["k"], storage_root=tmp_path, vector_fn=_vfn_semantic)
    assert r.total_status == "no_data"        # семантика без термина → НЕ найдено
    assert r.answer_data["adapter_statuses"]["vector"] == "weak_related"

@pytest.mark.asyncio
async def test_async_orchestrator_mail_found(tmp_path):
    (tmp_path / "k").mkdir()
    import pandas as pd
    pd.DataFrame([{"x": 1}]).to_parquet(tmp_path / "k" / "Акт_смонтированного_оборудования.parquet")
    r = await u.run_unified_construction_harness_async("найди ОЗК в почте", dataset_ids=["k"],
                                                       storage_root=tmp_path, mail_fn=_mfn)
    assert r.total_status == "complete" and r.answer_data["adapter_statuses"]["mail"] == "found"

@pytest.mark.asyncio
async def test_async_orchestrator_no_fn_unavailable(tmp_path):
    r = await u.run_unified_construction_harness_async("правила расстановки ОЗК", dataset_ids=["k"],
                                                       storage_root=tmp_path)
    assert r.total_status == "no_data" and "vector" not in r.answer_data["adapter_statuses"]

@pytest.mark.asyncio
async def test_async_orchestrator_sync_intent_untouched(tmp_path):
    # resource не трогается async-эскалацией
    r = await u.run_unified_construction_harness_async("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < MONEY


# ── live _run_chat v0.10 trace ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_trace_v10(live_chat):
    r = await chat_router._run_chat(chat_router.ChatRequest(question="правила расстановки ОЗК"))
    assert r["query_route"]["version"] == "unified_construction_harness_v0_10"
    ut = r["unified_trace"]
    assert ut["version"] == "unified_construction_harness_v0_10" and "adapter_statuses" in ut

@pytest.mark.asyncio
async def test_live_trace_v10_resource_complete(live_chat):
    r = await chat_router._run_chat(chat_router.ChatRequest(question="проверь пример обсчёта"))
    assert r["total_status"] == "complete" and r["query_route"]["intent"] == "resource_cost_calc"

@pytest.mark.asyncio
async def test_live_trace_no_mail_body_leak(live_chat):
    r = await chat_router._run_chat(chat_router.ChatRequest(question="что писали по котельной в почте"))
    import json
    assert "СЕКРЕТ" not in json.dumps(r["unified_trace"], ensure_ascii=False)


# ── регрессии ────────────────────────────────────────────────────────────────────────────

def test_sync_path_still_works():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete"

def test_v09_adapter_offline_unavailable():
    assert sa.search_vector_chunks("x").status == sa.UNAVAILABLE

def test_v04_source_scope_regression():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_v06_resource_real_workbook_regression():
    assert rc.validate_real_workbook()["matches"] is True

def test_unit_gate_regression():
    assert ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])["asm_positions"][0]["qty"] == 7.2
