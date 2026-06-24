"""Unified Construction Harness v0.9 — real source adapters + searched_tiers + actionable MISSING.

Адаптеры (lexical/vector/mail) unavailable-safe: реальный сервис где есть, явный `unavailable`/
`not_configured` где нет — БЕЗ фейков. source_scoped и norm_qa отчитываются searched_tiers; MISSING
говорит, по каким tier'ам искал и что недоступно. Числа/нормы/письма не из модели.
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


def _fixture(tmp_path, ds="k", *, with_term=True):
    import pandas as pd
    d = tmp_path / ds
    d.mkdir(parents=True)
    name = "Клапан ОЗК-1" if with_term else "Насос К-100"
    pd.DataFrame([{"наименование": name, "марка": "ОЗК-1" if with_term else "К-100", "кол": 4, "ед": "шт"}]
                 ).to_parquet(d / "Акт_смонтированного_оборудования.parquet")
    return ds


# ── adapters: unavailable-safe, без фейков ───────────────────────────────────────────────

def test_lexical_adapter_status_no_fake():
    r = sa.search_lexical_chunks(["ОЗК"], dataset_ids=["nope"])
    assert r.status in (sa.FOUND, sa.NOT_FOUND, sa.UNAVAILABLE)
    assert all(m.source_ref for m in r.matches)        # нет матча без source_ref

def test_lexical_adapter_no_term():
    r = sa.search_lexical_chunks([])
    assert r.status == sa.NOT_FOUND and not r.matches

def test_vector_adapter_unavailable_not_fake():
    r = sa.search_vector_chunks("нормы по ОЗК")
    assert r.status == sa.UNAVAILABLE and r.matches == []
    assert any("vector_unavailable" in w for w in r.warnings)

def test_mail_adapter_unavailable_not_fake():
    r = sa.retrieve_mail_evidence(["ОЗК"])
    assert r.status == sa.UNAVAILABLE and r.matches == []
    assert any("mail_backend_not_configured" in w for w in r.warnings)

def test_mail_adapter_read_only_no_send():
    import inspect
    # код (без docstring) не ВЫЗЫВАЕТ send/push/delete/mutate
    src = inspect.getsource(sa.retrieve_mail_evidence)
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(("#", '"', "'")))
    for bad in (".send(", ".push(", ".delete(", "send_email", "push_mail", "create_draft"):
        assert bad not in code

def test_source_kind_constants():
    for k in (sa.KIND_PARQUET, sa.KIND_LEXICAL, sa.KIND_VECTOR, sa.KIND_MAIL, sa.KIND_WORKBOOK):
        assert isinstance(k, str)


# ── source_scoped: tier chain + searched_tiers ───────────────────────────────────────────

def test_source_scoped_found_tier1_parquet(tmp_path):
    ds = _fixture(tmp_path, with_term=True)
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete"
    assert r.answer_data["searched_tiers"] == ["parquet_row", "filename_metadata"]

def test_source_scoped_not_found_escalates_tiers(tmp_path):
    ds = _fixture(tmp_path, with_term=False)        # ОЗК нет в актах
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "no_data"
    tiers = r.answer_data["searched_tiers"]
    assert "parquet_row" in tiers and "lexical_chunk" in tiers and "vector_chunk" in tiers
    # vector_unavailable в warnings — явный статус, не молчание
    assert any("vector_unavailable" in w for w in r.warnings)

def test_source_scoped_missing_mentions_tiers(tmp_path):
    ds = _fixture(tmp_path, with_term=False)
    r = u.run_unified_construction_harness("найди КДУ-9 в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    miss = [it for b in r.evidence_blocks if b.type is EvidenceType.MISSING for it in b.items]
    assert any("tier" in b.lower() for it in miss for b in it.blockers)

def test_source_scope_priority_still_holds():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"


# ── norm_qa: layered lexical→vector ──────────────────────────────────────────────────────

def test_norm_qa_layered_tiers():
    # v0.12: file_body добавлен первым tier'ом (real .md без lexical-индекса)
    r = u.run_unified_construction_harness("правила расстановки ОЗК", dataset_ids=["k"], storage_root=None)
    assert r.answer_data["searched_tiers"] == ["file_body", "lexical_chunk", "vector_chunk"]

def test_norm_qa_no_source_missing_with_tiers():
    r = u.run_unified_construction_harness("правила расстановки ОЗК")
    assert r.total_status == "no_data"
    miss = [it for b in r.evidence_blocks if b.type is EvidenceType.MISSING for it in b.items]
    assert any("tier" in b.lower() for it in miss for b in it.blockers)

def test_norm_qa_no_invented_clause():
    r = u.run_unified_construction_harness("требования к котельной по пожарке")
    # без источника → нет RETRIEVED-утверждения (нет выдуманного пункта СП)
    if r.total_status == "no_data":
        assert not any(b.type is EvidenceType.RETRIEVED for b in r.evidence_blocks)


# ── mail: actionable not_configured ──────────────────────────────────────────────────────

def test_mail_no_source_actionable(tmp_path):
    ds = _fixture(tmp_path)         # нет mail-доков
    r = u.run_unified_construction_harness("найди ОЗК в почте", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "no_data"
    assert r.answer_data.get("mail_adapter_status") == "unavailable"
    assert any("mail_backend_not_configured" in w for w in r.warnings)


# ── v0_9 trace через живой _run_chat ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_trace_v09_has_tiers(live_chat):
    r = await chat_router._run_chat(
        chat_router.ChatRequest(question="правила расстановки ОЗК"))
    assert r["query_route"]["version"] == "unified_construction_harness_v0_10"
    ut = r["unified_trace"]
    assert ut["version"] == "unified_construction_harness_v0_10"
    assert "searched_tiers" in ut and "adapter_warnings" in ut

@pytest.mark.asyncio
async def test_live_trace_v09_no_mail_body(live_chat):
    # со scope: mail no_source → mail_backend_not_configured в warnings
    import tempfile, pandas as pd
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp()); (tmp / "k").mkdir()
    pd.DataFrame([{"наименование": "акт"}]).to_parquet(tmp / "k" / "Акт_смонтированного_оборудования.parquet")
    res = u.run_unified_construction_harness("найди ОЗК в почте", dataset_ids=["k"], storage_root=tmp)
    assert res.total_status == "no_data" and res.answer_data.get("intent") == "mail_entity_search"
    # trace/warnings несут статус, но НЕ тело письма
    blob = json_str(res.answer_data).lower()
    assert "body" not in blob and "subject" not in blob
    assert any("mail_backend_not_configured" in w for w in res.warnings)
    # и через живой роутер (без scope) — честный no_data, intent mail
    r = await chat_router._run_chat(chat_router.ChatRequest(question="что писали по котельной в почте"))
    assert r["unified_trace"]["intent"] == "mail_entity_search" and r["total_status"] == "no_data"


def json_str(o):
    import json
    return json.dumps(o, ensure_ascii=False)


# ── регрессии v0.3-v0.8 ──────────────────────────────────────────────────────────────────

def test_resource_real_workbook_still_validates():
    assert rc.validate_real_workbook()["matches"] is True

def test_resource_grand_via_chat():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < MONEY

def test_unit_gate_regression():
    assert ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])["asm_positions"][0]["qty"] == 7.2

def test_unknown_family_regression():
    assert ch.gesn_expand({"work": "некие работы общего вида", "unit": "м3"})["status"] == "needs_classification"

def test_generic_term_no_dictionary():
    for t in ("КДУ", "ШУ-1", "ВРС-12"):
        eq = u.extract_source_scoped_query(f"найди {t} в актах смонтированного оборудования")
        assert t in eq.exact_terms
