"""Unified Construction Harness v0.11 — real-data acceptance + failure-driven hardening.

index-health превращает lexical_miss → конкретный no_lexical_index/no_parquet; norm_qa MISSING называет
причину. Прогон на реальных датасетах (read-only) даёт честный ledger. doc_classifier на реальных
именах ГОСТ/СП. Числа/нормы/письма не из модели; нет фейков. runtime .env НЕ менялся.
"""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from proxy.services import source_adapters as sa
from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services import resource_cost_service as rc
from proxy.services.evidence_contract import EvidenceType

MONEY = 1.0

# импорт smoke-скрипта (для теста _failure классификации)
_spec = importlib.util.spec_from_file_location("smoke_v11", "scripts/smoke_unified_v11.py")
_smoke = importlib.util.module_from_spec(_spec)


def _load_smoke():
    import os
    os.environ.setdefault("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    _spec.loader.exec_module(_smoke)
    return _smoke


# ── index health ─────────────────────────────────────────────────────────────────────────

def test_index_health_counts(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    pd.DataFrame([{"x": 1}]).to_parquet(d / "Акт_смонтированного_оборудования.parquet")
    (d / "ГОСТ 30244-94.docx").write_bytes(b"x" * 2000)
    (d / "olm_001.eml").write_bytes(b"x" * 500)
    h = sa.inspect_dataset_index_health(["ds"], storage_root=tmp_path)
    rec = h["datasets"][0]
    assert rec["parquet_count"] == 1 and rec["file_count"] == 2 and rec["mail_count"] == 1
    assert "norm" in rec["doc_types"]

def test_index_health_no_parquet_warning(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "СП 17.13330.2017.docx").write_bytes(b"x" * 2000)
    rec = sa.inspect_dataset_index_health(["ds"], storage_root=tmp_path)["datasets"][0]
    assert "no_parquet" in rec["warnings"]

def test_index_health_empty_dataset(tmp_path):
    (tmp_path / "ds").mkdir()
    rec = sa.inspect_dataset_index_health(["ds"], storage_root=tmp_path)["datasets"][0]
    assert "empty_dataset" in rec["warnings"]


# ── norm_qa actionable: no_lexical_index ─────────────────────────────────────────────────

def test_norm_qa_no_lexical_index_actionable(tmp_path):
    # датасет без lexical-индекса → MISSING называет причину (no_lexical_index), не общее «не найдено»
    d = tmp_path / "ds"
    d.mkdir()
    (d / "СП 17.13330.2017.docx").write_bytes(b"x" * 2000)
    r = u.run_unified_construction_harness("правила расстановки ОЗК", dataset_ids=["ds"], storage_root=tmp_path)
    assert r.total_status == "no_data"
    # index_health приложен; если lexical пуст — причина названа
    assert "index_health" in r.answer_data
    blk = " ".join(it.blockers[0] for b in r.evidence_blocks if b.type is EvidenceType.MISSING
                   for it in b.items if it.blockers).lower()
    if r.answer_data["index_health"]["total_lexical_chunks"] == 0:
        assert "проиндекс" in blk or "no_lexical_index" in blk or "lexical" in blk

def test_norm_qa_no_invented_clause(tmp_path):
    (tmp_path / "ds").mkdir()
    r = u.run_unified_construction_harness("требования к котельной по пожарке", dataset_ids=["ds"], storage_root=tmp_path)
    if r.total_status == "no_data":
        assert not any(b.type is EvidenceType.RETRIEVED for b in r.evidence_blocks)


# ── doc_classifier на реальных именах ────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("ГОСТ 30244-94. Материалы строительные.docx", "norm"),
    ("СП 17.13330.2017. Свод правил. Кровли.docx", "norm"),
    ("Акт_смонтированного_оборудования_ТМ.parquet", "installed_equipment_act"),
    ("Ф9_ВОР_котельная.parquet", "f9_bor"),
    ("olm_00001.eml", "mail"),
    ("Котельная_спецификация_оборудования.pdf", "specification"),
])
def test_doc_classifier_real_names(name, expected):
    assert u.classify_doc_type(name) == expected


# ── smoke failure классификация (intent-first, без mail-мисклассификации) ─────────────────

def test_smoke_failure_classification_intent_first():
    s = _load_smoke()
    hw = {"datasets": [{"warnings": ["no_parquet", "no_lexical_index", "no_mail_source"]}]}
    # asbuilt без актов в норм-датасете → no_source_in_scope (НЕ mail)
    assert s._failure("no_data", "asbuilt_extract", {}, hw) == "no_source_in_scope"
    assert s._failure("no_data", "norm_qa", {}, hw) == "no_lexical_index"
    assert s._failure("no_data", "estimate_from_bor", {}, hw) == "f9_not_found_no_parquet"
    assert s._failure("no_data", "mail_entity_search", {}, hw) == "mail_backend_not_configured"
    assert s._failure("complete", "resource_cost_calc", {}, hw) is None
    assert s._failure("error", "norm_qa", {}, hw) == "unexpected_exception"


# ── registry на реальном датасете рантайма (read-only, если доступен) ─────────────────────

_RUNTIME = Path("/Users/ovc/LES/storage/datasets")
_GOST_DS = "844a2b53-9658-4e5a-92e4-f649de8af043"


@pytest.mark.skipif(not (_RUNTIME / _GOST_DS).exists(), reason="реальный датасет рантайма недоступен")
def test_real_registry_groups_gost_sp():
    r = u.run_unified_construction_harness("дай реестр документов проекта",
                                           dataset_ids=[_GOST_DS], storage_root=_RUNTIME)
    assert r.total_status == "complete" and len(r.sources) > 10
    assert "norm" in r.answer_data.get("groups", {})        # ГОСТ/СП → norm

@pytest.mark.skipif(not (_RUNTIME / _GOST_DS).exists(), reason="реальный датасет рантайма недоступен")
def test_real_norm_lexical_still_zero():
    # v0.15: после approved sidecar-write norm может находить термин в extracted_body → complete;
    # lexical-индекс при этом ВСЁ РАВНО пуст (sidecar ≠ lexical FTS). Если no_data — не blind.
    r = u.run_unified_construction_harness("правила расстановки ОЗК", dataset_ids=[_GOST_DS], storage_root=_RUNTIME)
    if r.total_status == "complete":                   # нашли в extracted_body (sidecar записан)
        assert r.sources and "extracted_body" in r.answer_data.get("searched_tiers", [])
    else:                                              # no_data → не blind: sidecar просмотрен, lexical пуст
        h = r.answer_data.get("index_health", {})
        assert h.get("total_lexical_chunks") == 0
        assert "extracted_body" in r.answer_data.get("searched_tiers", [])


# ── регрессии v0.3-v0.10 ─────────────────────────────────────────────────────────────────

def test_v10_async_regression():
    assert sa.search_vector_chunks("x").status == sa.UNAVAILABLE

def test_v06_resource_real_workbook_regression():
    assert rc.validate_real_workbook()["matches"] is True

def test_resource_grand_complete():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < MONEY

def test_v04_source_scope_regression():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_v03_lsr_regression(tmp_path):
    ds = ch.write_demo_project_doc(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete" and r.final_total is not None

def test_unit_gate_regression():
    assert ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])["asm_positions"][0]["qty"] == 7.2
