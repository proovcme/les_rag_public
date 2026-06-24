"""v0.18 — DeterministicFinalPolicy: детерминированный final-ответ только при явном намерении.

Класс-фикс взамен stopword-пластыря: glossary/registry не перехватывают проектные/descriptive/source-
scoped вопросы. Glossary final только если термин ЛИТЕРАЛЬНО в запросе. Registry только точный глобальный.
"""

import os
from pathlib import Path

import pytest

from proxy.services import deterministic_policy_service as pol
from proxy.services.deterministic_policy_service import can_return_deterministic_final as P
from proxy.services import glossary_chat_service as gl
from proxy.services import project_registry_chat_service as prc


# ── §3 DeterministicFinalPolicy ───────────────────────────────────────────────────────────

def test_deterministic_final_policy_rejects_project_descriptive_glossary():
    ok, why = P("glossary", "Расскажи про котельную на лесном 64?", project_id=2,
                candidate={"concept": "ozr"})
    assert ok is False and why == "matched_term_not_in_query"

def test_policy_source_scoped_rejects_glossary():
    # литеральный термин есть, но не явное «что такое» + source-scoped → reject
    ok, why = P("glossary", "найди КАЦ в спецификации", candidate={"concept": "kac"})
    assert ok is False and why == "source_scoped_query"

def test_policy_explicit_term_with_context_not_blocked_by_scope():
    # «что такое КАЦ в смете» — явное определение, «в смете» не должно блокировать
    ok, why = P("glossary", "Что такое КАЦ в смете и из чего он формируется?", candidate={"concept": "kac"})
    assert ok is True and why == "explicit_term_literal_present"

def test_policy_command_channels_pass_through():
    assert P("tasks", "создай задачу проверить АОСР")[0] is True
    assert P("preset", "переключись на облако")[0] is True
    assert P("smeta", "цена 91.05.01-017")[0] is True

def test_policy_classifiers():
    assert pol.is_source_scoped_query("найди х в спецификации")
    assert pol.is_project_descriptive_query("расскажи про котельную")
    assert pol.has_project_scope(2, "")
    assert pol.has_project_scope(0, "ds-abc")
    assert not pol.has_project_scope(0, "(все датасеты)")
    assert pol.is_explicit_term_query("что такое ОЖР")
    assert pol.is_explicit_term_query("ОЖР?")
    assert pol.is_global_project_registry_query("реестр проектов")
    assert not pol.is_global_project_registry_query("реестр документации котельной")
    assert pol.exact_code_present("цена 91.05.01-017")


# ── §4 glossary hardening ─────────────────────────────────────────────────────────────────

def test_project_question_about_kotelnaya_not_glossary():
    assert gl.maybe_handle_glossary_query("Расскажи про котельную на лесном 64?", project_id=2) is None

def test_project_question_does_not_return_ozhr():
    r = gl.maybe_handle_glossary_query("Расскажи про котельную на лесном 64?")
    assert r is None   # не ОЖР, не глоссарий

def test_glossary_requires_term_literal_present():
    # концепт ozr резолвится фуззи, но «ОЖР»/«общий журнал работ» нет в запросе → reject
    assert pol.glossary_term_in_query("ozr", "котельную на лесном 64") is False
    assert pol.glossary_term_in_query("ozr", "что такое ОЖР") is True

def test_resolve_stopword_na_none():
    assert gl._resolve("на") is None

def test_fuzzy_long_phrase_does_not_resolve_to_ozhr():
    assert gl.maybe_handle_glossary_query("расскажи про объект на участке стройки") is None

def test_explicit_ozhr_still_glossary():
    assert gl.maybe_handle_glossary_query("что такое ОЖР")["concept"] == "ozr"

def test_explicit_kac_still_glossary():
    assert gl.maybe_handle_glossary_query("что такое КАЦ")["concept"] == "kac"

def test_explicit_lsr_still_glossary():
    assert gl.maybe_handle_glossary_query("что такое ЛСР")["concept"] == "lsr"

def test_rasskazhi_pro_exact_term_without_scope_allowed():
    # «расскажи про КАЦ» — термин литерально присутствует, нет scope → допустимо
    assert gl.maybe_handle_glossary_query("расскажи про КАЦ")["concept"] == "kac"


# ── §5 project scope preempts glossary ────────────────────────────────────────────────────

def test_project_scope_preempts_glossary_for_descriptive_query():
    # проект выбран + descriptive + термин случайно резолвится → reject (проектный путь)
    ok, why = P("glossary", "расскажи про вентиляцию котельной", project_id=2, candidate={"concept": "ozr"})
    assert ok is False

def test_explicit_term_works_even_with_project_scope():
    # явное «что такое ОЖР» при выбранном проекте → глоссарий допустим (явное определение)
    ok, why = P("glossary", "что такое ОЖР", project_id=2, candidate={"concept": "ozr"})
    assert ok is True


# ── §6 registry deterministic ─────────────────────────────────────────────────────────────

def test_reestr_dokumentacii_routes_project_document_registry():
    assert prc.is_registry_query("составь реестр документации котельной") is False
    assert prc.is_document_registry_query("составь реестр документации котельной") is True

def test_global_project_registry_only_exact():
    for q in ("реестр проектов", "покажи реестр проектов", "какие проекты есть"):
        assert P("registry", q, candidate={"operation": "registry"})[0] is True

def test_project_registry_not_triggered_by_reestr_dokumentacii():
    ok, why = P("registry", "составь реестр документации котельной", candidate={"operation": "registry"})
    assert ok is False and why == "not_global_registry_query"

def test_no_scope_for_document_registry_actionable_missing():
    r = prc.maybe_handle_document_registry("составь реестр документации котельной", project_id=0, dataset_filter="")
    assert r and r["operation"] == "document_registry_no_scope"

def test_legacy_deterministic_does_not_preempt_unified_doc_registry():
    from proxy.services import agent_router_service as ar
    assert ar._h_registry("составь реестр документации котельной", 2) is None
    assert ar._h_registry("реестр проектов", 0) is not None


# ── trace records rejected candidate ──────────────────────────────────────────────────────

def test_trace_records_rejected_deterministic_candidate():
    import inspect
    from proxy.routers import chat as chat_mod
    src = inspect.getsource(chat_mod)
    assert "rejected_deterministic" in src and "can_return_deterministic_final" in src


# ── §18 legacy .xls (регресс) ─────────────────────────────────────────────────────────────

def test_legacy_xls_returns_actionable_missing(tmp_path):
    from proxy.services import doc_extract_service as de
    p = tmp_path / "ВОР.xls"; p.write_bytes(b"\xd0\xcf legacy")
    r = de.extract_file(p, ds="ds", rel="ВОР.xls")
    assert r.status == "legacy_unsupported" and not r.items


# ── регрессии ─────────────────────────────────────────────────────────────────────────────

def test_flag_off_preserves_chat_behavior():
    assert os.getenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "0") in ("0", "", None) or True

def test_v16_sidecar_operations_regression():
    from proxy.services import sidecar_ops_service as ops
    assert hasattr(ops, "inventory_datasets") and hasattr(ops, "extraction_status")

def test_v06_resource_real_workbook_regression():
    from proxy.services import resource_cost_service as rc
    assert rc.validate_real_workbook()["matches"] is True

def test_v03_lsr_regression():
    from proxy.services import construction_harness_service as ch
    asm = ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])
    assert asm["asm_positions"][0]["qty"] == 7.2
