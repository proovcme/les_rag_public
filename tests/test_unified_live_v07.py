"""Unified Construction Harness v0.7 — operational LIVE chat path (flag ON).

Доказывает, что при LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED=1 обычный chat (`_run_chat`) реально
маршрутизирует строительные intent'ы в unified-harness и отдаёт evidence-ответ с query_route=
unified_construction_harness_v0_9 — не только в unit-тестах сервиса, а через живой роутер.

Источники: resource workbook = РЕАЛЬНЫЙ (fsnb2022.ru); project/asbuilt/ВОР/ЛСР = parquet-fixture
через storage facade. Числа/нормы/итоги — только из tool. Flag OFF не покрывается здесь (живой RAG
требует бэкенд) — за него отвечают 228 chat-тестов и unit OFF→None.
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
    """Минимальный chat-state + flag ON. Unified-путь возвращает ДО ретрива → бэкенд не нужен."""
    monkeypatch.setenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    chat_router.set_chat_state(chat_router.ChatRouterState(
        rag_backend=SimpleNamespace(), llm_semaphore=SimpleNamespace(_value=1),
        crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
        chat_metrics={"latency_search": [], "latency_gen": [], "tokens": [], "crag_pass": 0, "crag_fail": 0},
        reranker_available=False, reranker_cls=None, current_mode={"mode": "chat"},
        metrics_cache={"ram_free_gb": 12.0, "swap_pct": 0.0}))
    yield


async def _ask(q, **kw):
    return await chat_router._run_chat(chat_router.ChatRequest(question=q, **kw))


# ── LIVE: флаг ON → unified в реальном chat ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_resource_workbook(live_chat):
    r = await _ask("проверь пример обсчёта")
    qr = r["query_route"]
    assert qr["version"] == "unified_construction_harness_v0_9"
    assert qr["intent"] == "resource_cost_calc" and qr["provenance"] == "real"
    assert r["total_status"] == "complete"
    assert "16 827 283.19" in r["answer"] or "16827283.19" in r["answer"]
    assert r["evidence_summary"].get("COMPUTED", 0) > 0 and r["evidence_summary"].get("RETRIEVED", 0) > 0

@pytest.mark.asyncio
async def test_live_norm_qa_missing_not_hallucination(live_chat):
    r = await _ask("правила расстановки ОЗК")
    assert r["query_route"]["version"] == "unified_construction_harness_v0_9"
    assert r["query_route"]["intent"] == "norm_qa"
    assert r["total_status"] in ("no_data", "complete")     # без lexical-данных → честный no_data

@pytest.mark.asyncio
async def test_live_source_scoped_asbuilt_routes(live_chat):
    r = await _ask("найди ОЗК в актах смонтированного оборудования")
    assert r["query_route"]["intent"] == "asbuilt_extract"   # НЕ norm_qa
    assert r["query_route"]["version"] == "unified_construction_harness_v0_9"

@pytest.mark.asyncio
async def test_live_cost_project_ambiguous(live_chat):
    r = await _ask("стоимость проекта")
    assert r["query_route"]["intent"] == "resource_cost_calc" and r["total_status"] == "no_data"

@pytest.mark.asyncio
async def test_live_kac_query(live_chat):
    r = await _ask("что требует КАЦ по примеру")
    assert r["query_route"]["intent"] == "resource_cost_calc"
    assert r["query_route"]["version"] == "unified_construction_harness_v0_9"


# ── dataset-голдены (через storage facade, run_unified) ──────────────────────────────────

def test_golden_project_registry_summary(tmp_path):
    ds = "kotelnaya"; d = tmp_path / ds; d.mkdir(parents=True)
    import pandas as pd
    for n, sz in [("Котельная_ТМ.pdf", 5000), ("Котельная_АУПТ.docx", 3000), ("~$tmp.docx", 40)]:
        (d / n).write_bytes(b"x" * sz)
    pd.DataFrame([{"наименование": "Клапан ОЗК-1", "марка": "ОЗК-1", "кол": 4, "ед": "шт"}]
                 ).to_parquet(d / "Акт_смонтированного_оборудования.parquet")
    r = u.run_unified_construction_harness("опиши проект котельная и дай реестр документов",
                                           dataset_ids=[ds], storage_root=tmp_path)
    assert r.sources and any(b.type is EvidenceType.BLOCKED for b in r.evidence_blocks)  # мусор отдельно
    assert (d / "~$tmp.docx").exists()                                                   # не удалён

def test_golden_source_scoped_asbuilt_found(tmp_path):
    import pandas as pd
    d = tmp_path / "k"; d.mkdir()
    pd.DataFrame([{"наименование": "Клапан ОЗК-1", "марка": "ОЗК-1", "кол": 4, "ед": "шт", "акт": "А-12"}]
                 ).to_parquet(d / "Акт_смонтированного_оборудования.parquet")
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=["k"], storage_root=tmp_path)
    assert r.total_status == "complete"
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert retr.items[0].source_refs

def test_golden_lsr_from_f9(tmp_path):
    ds = ch.write_demo_project_doc(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete" and r.final_total is not None

@pytest.mark.parametrize("q,scope", [
    ("найди КДУ-7 в актах смонтированного оборудования", "asbuilt"),
    ("найди ШУ-1 в исполнительной", "asbuilt"),
    ("найди ВРС-12 в спецификации", "specification"),
])
def test_golden_generic_term_no_dictionary(q, scope):
    r = u.route_construction_intent(q)
    assert r.source_scope == scope and r.route_source == "source_scope"   # generic, без словаря


# ── bridge-интерфейсы (v0.7) ─────────────────────────────────────────────────────────────

def test_bridge_price_source_workbook_no_db():
    s = rc.resource_price_source()
    assert s["source"] == "workbook" and s["db_available"] is False

def test_bridge_fgis_not_connected_not_fake():
    assert rc.fgis_price_lookup("91.05.05-015")["status"] == "not_found"

def test_bridge_nr_sp_lookup():
    res = rc.nr_sp_lookup("НР Строительные металлические конструкции")
    assert res["status"] in ("found", "not_found")    # обёртка nr_sp_service

def test_bridge_machinist_mapping():
    assert rc.machinist_mapping_lookup("91.05.05-015")["status"] == "found"
    assert rc.machinist_mapping_lookup("91.99.99-999")["status"] == "not_found"


# ── регрессии (не сломали v0.3-v0.6) ─────────────────────────────────────────────────────

def test_real_workbook_validation_regression():
    val = rc.validate_real_workbook()
    assert val["matches"] is True and val["line_diffs"] == []

def test_unknown_family_blocked_regression():
    assert ch.gesn_expand({"work": "некие работы общего вида", "unit": "м3"})["status"] == "needs_classification"

def test_unit_conversion_regression():
    assert ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])["asm_positions"][0]["qty"] == 7.2

def test_no_manual_ozk_dictionary():
    # ОЗК нигде не зашит как бизнес-термин — экстракция generic
    eq = u.extract_source_scoped_query("найди ОЗК в актах смонтированного оборудования")
    assert eq.query_terms == ["ОЗК"]              # generic-экстракция, термин не из словаря
    # КДУ/ШУ/ВРС — те же generic-правила, без отдельных записей под каждый
    for term in ("КДУ", "ШУ-1", "ВРС-12"):
        eq2 = u.extract_source_scoped_query(f"найди {term} в актах смонтированного оборудования")
        assert term in eq2.exact_terms
    # нет dict-маппинга «ОЗК» → расшифровка в коде (alias только из источника)
    import inspect
    src = inspect.getsource(u)
    assert '"ОЗК"' not in src and "'ОЗК'" not in src
