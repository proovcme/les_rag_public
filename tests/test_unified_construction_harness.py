"""LES Unified Construction Harness v0.3 — единый evidence-слой по строительным intent'ам.

Keyword-роутинг → per-intent facade → RETRIEVED/COMPUTED/ASSUMED/MISSING/BLOCKED. Feature-flag
OFF дефолт. Котельная golden: реестр НЕ мусорных документов + описание из источников + ЛСР по Ф9.
Нормативный/проектный ответ без источника → MISSING, не фантазия. Числа только из tool-результата.
"""

from pathlib import Path

from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services.evidence_contract import EvidenceType


# ── котельная fixture (через storage/dataset facade, не напрямую в orchestrator) ──────────

def _kotelnaya(tmp_path: Path, ds: str = "kotelnaya") -> str:
    ddir = tmp_path / ds
    ddir.mkdir(parents=True, exist_ok=True)
    for n, sz in [("Котельная_тепломеханика_ТМ.pdf", 5000), ("Котельная_газоснабжение_ГСВ.pdf", 4000),
                  ("Котельная_автоматика_АУПТ.docx", 3000),
                  ("~$врем.docx", 100), ("копия_old.pdf", 2000), ("пустой.pdf", 0)]:
        (ddir / n).write_bytes(b"x" * sz)
    ch.write_demo_project_doc(tmp_path, dataset_id=ds)      # Ф9/ВОР parquet
    return ds


# ── routing ──────────────────────────────────────────────────────────────────────────────

def test_route_norm_qa():
    assert u.route_construction_intent("что по нормам про АУПТ серверной").intent == "norm_qa"

def test_route_project_summary():
    assert u.route_construction_intent("опиши проект котельная").intent == "project_summary"

def test_route_project_document_registry():
    assert u.route_construction_intent("дай реестр документов проекта").intent == "project_document_registry"

def test_route_mail_qa():
    # v0.4: «в почте» = source-фраза → mail_entity_search (источник доминирует); «из писем» → mail_qa
    assert u.route_construction_intent("что в почте по котельной").intent == "mail_entity_search"
    assert u.route_construction_intent("из писем по согласованию").intent == "mail_qa"

def test_route_estimate_from_bor():
    assert u.route_construction_intent("собери предварительную ЛСР по Ф9").intent == "estimate_from_bor"

def test_route_bor_extract():
    assert u.route_construction_intent("извлеки ВОР из спецификации").intent == "bor_extract"

def test_route_table_agg():
    assert u.route_construction_intent("посчитай сумму по ведомости").intent == "table_agg"

def test_low_confidence_routes_none():
    assert u.route_construction_intent("привет как дела").intent == "none"
    assert u.run_unified_construction_harness("привет как дела") is None   # none → старый путь


# ── project registry: не мусорные документы ──────────────────────────────────────────────

def test_project_registry_lists_non_noise_docs(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("реестр документов проекта", dataset_ids=[ds], storage_root=tmp_path)
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    names = [it.title for it in retr.items]
    assert any("тепломеханика" in n for n in names) and not any("~$" in n for n in names)

def test_project_registry_excludes_noise_docs(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("реестр документов проекта", dataset_ids=[ds], storage_root=tmp_path)
    blocked = next(b for b in r.evidence_blocks if b.type is EvidenceType.BLOCKED)
    titles = [it.title for it in blocked.items]
    assert any("~$" in t for t in titles) and any("old" in t for t in titles) and any("пустой" in t for t in titles)
    # мусор помечен, но НЕ удалён физически
    assert (tmp_path / ds / "~$врем.docx").exists()

def test_project_registry_source_refs(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("реестр документов", dataset_ids=[ds], storage_root=tmp_path)
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert all(it.source_refs for it in retr.items)

def test_project_summary_uses_retrieved_sources(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("опиши проект котельная", dataset_ids=[ds], storage_root=tmp_path)
    assert "котельн" in r.answer_data.get("summary", "").lower()
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert all(it.source_refs for it in retr.items)
    # паспорт без источника → MISSING (не выдумка назначения/мощности/адреса)
    assert any(b.type is EvidenceType.MISSING for b in r.evidence_blocks)

def test_project_summary_missing_without_scope():
    r = u.run_unified_construction_harness("опиши проект котельная")
    assert r.total_status == "no_data" and r.evidence_blocks[0].type is EvidenceType.MISSING


# ── mail: honest MISSING, без отправки/мутации ───────────────────────────────────────────

def test_mail_qa_no_source_returns_missing(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("что в почте по котельной", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "no_data" and r.evidence_blocks[0].type is EvidenceType.MISSING

def test_mail_does_not_send_or_mutate():
    # mail handler — чисто read; никаких send/push (контур не импортирует mail_push в путь ответа)
    import inspect
    src = inspect.getsource(u._handle_mail)
    assert "push" not in src.lower() and "send" not in src.lower()


# ── нормы/документы: без источника нет нормативного утверждения ───────────────────────────

def test_norm_qa_no_source_no_hallucination(tmp_path):
    # lexical в тест-окружении пуст → честный MISSING, а не выдуманный пункт нормы
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("что по нормам про предел огнестойкости", dataset_ids=[ds],
                                           storage_root=tmp_path)
    assert r.total_status in ("no_data", "complete")
    if r.total_status == "no_data":
        assert r.evidence_blocks[0].type is EvidenceType.MISSING
    else:   # если что-то нашлось — обязан быть source_ref
        assert all(it.source_refs for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED for it in b.items)


# ── BOR / estimate (переиспользуют v0.2, gates целы) ─────────────────────────────────────

def test_bor_extract_from_retrieved_project_doc(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("извлеки ВОР", dataset_ids=[ds], storage_root=tmp_path)
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert retr.items and all(it.source_refs for it in retr.items)

def test_estimate_from_bor_retrieval_backed(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    types = {b.type for b in r.evidence_blocks}
    assert EvidenceType.RETRIEVED in types and EvidenceType.COMPUTED in types
    assert r.total_status == "complete" and r.final_total is not None

def test_estimate_missing_without_source(tmp_path):
    # нет Ф9/ВОР в scope → MISSING, не LLM-декомпозиция
    (tmp_path / "empty_ds").mkdir()
    r = u.run_unified_construction_harness("собери ЛСР по Ф9", dataset_ids=["empty_ds"], storage_root=tmp_path)
    assert r.total_status == "no_data" and r.final_total is None


# ── table_agg: COMPUTED с provenance ─────────────────────────────────────────────────────

def test_table_agg_computed_with_source_refs(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("посчитай сумму по ведомости", dataset_ids=[ds], storage_root=tmp_path)
    comp = next(b for b in r.evidence_blocks if b.type is EvidenceType.COMPUTED)
    it = comp.items[0]
    assert it.value is not None and (it.formula or it.source_refs)


# ── feature flag ─────────────────────────────────────────────────────────────────────────

def test_unified_harness_flag_off_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", raising=False)
    ds = _kotelnaya(tmp_path)
    assert u.maybe_unified_construction_harness("реестр документов", dataset_ids=[ds], storage_root=tmp_path) is None

def test_unified_harness_flag_on_routes_supported_intent(monkeypatch, tmp_path):
    monkeypatch.setenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    ds = _kotelnaya(tmp_path)
    res = u.maybe_unified_construction_harness("реестр документов проекта", dataset_ids=[ds], storage_root=tmp_path)
    assert res is not None and res.evidence_blocks
    assert u.maybe_unified_construction_harness("привет") is None   # none → None даже при ON

def test_unified_harness_flag_on_no_data_for_missing_scope(monkeypatch):
    monkeypatch.setenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    res = u.maybe_unified_construction_harness("реестр документов проекта")
    assert res is not None and res.total_status == "no_data"


# ── composer: факты/числа только из evidence ─────────────────────────────────────────────

def test_composer_only_uses_evidence(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("собери ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    txt = u.compose_unified_answer(r)
    assert "ИТОГО" in txt and "₽" in txt
    # все числа в COMPUTED имеют формулу/источник
    for b in r.evidence_blocks:
        for it in b.items:
            if it.value is not None:
                assert it.source_refs or it.formula


# ── golden E2E: котельная (реестр не мусора + описание + ЛСР) ─────────────────────────────

def test_golden_kotelnaya_registry_and_summary(tmp_path):
    ds = _kotelnaya(tmp_path)
    reg = u.run_unified_construction_harness("опиши проект котельная и дай реестр документов",
                                             dataset_ids=[ds], storage_root=tmp_path)
    # комбо-запрос → registry (приоритет): источники включённых + мусор отдельно (BLOCKED)
    assert reg.sources and any(b.type is EvidenceType.BLOCKED for b in reg.evidence_blocks)
    # отдельно описание проекта — с честным MISSING паспорта
    ps = u.run_unified_construction_harness("опиши проект котельная", dataset_ids=[ds], storage_root=tmp_path)
    assert ps.sources and any(b.type is EvidenceType.MISSING for b in ps.evidence_blocks)
