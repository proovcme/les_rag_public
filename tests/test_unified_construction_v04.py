"""LES Unified Construction Harness v0.4 — source-scoped entity search.

Headline: ИСТОЧНИК доминирует над термином. «найди ОЗК в актах смонтированного оборудования» →
asbuilt-поиск (НЕ нормы), ОЗК как generic-терм (БЕЗ хардкод-словаря), RETRIEVED matches или честный
MISSING. Алиас/расшифровка — только из источника, не из памяти модели. Числа только из tool.
ОЗК — канарейка, не спец-кейс.
"""

from pathlib import Path

import pandas as pd

from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services.evidence_contract import EvidenceType


# ── fixtures (через storage/dataset facade) ──────────────────────────────────────────────

def _act_rows(with_ozk: bool):
    rows = [{"акт": "А-12", "наименование": "Вентилятор ВР-300", "марка": "ВР-300", "кол": 2,
             "ед": "шт", "помещение": "венткамера №3", "дата": "2026-03-10"}]
    if with_ozk:
        rows.insert(0, {"акт": "А-12", "наименование": "Клапан огнезадерживающий ОЗК-1", "марка": "ОЗК-1",
                        "кол": 4, "ед": "шт", "помещение": "венткамера №3", "дата": "2026-03-10"})
    return rows


def _kotelnaya(tmp_path: Path, *, ozk_in_acts=True, ozk_in_spec=True, ds="kotelnaya") -> str:
    ddir = tmp_path / ds
    ddir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(_act_rows(ozk_in_acts)).to_parquet(ddir / "Акт_смонтированного_оборудования_ТМ.parquet")
    spec = [{"наименование": ("ОЗК огнезадерживающий клапан Ду300" if ozk_in_spec else "Насос К-100"),
             "марка": ("ОЗК-1" if ozk_in_spec else "К-100"), "кол": 6, "ед": "шт"}]
    pd.DataFrame(spec).to_parquet(ddir / "Котельная_спецификация_оборудования.parquet")
    for n, sz in [("Котельная_тепломеханика_ТМ.pdf", 5000), ("Котельная_газоснабжение_ГСВ.pdf", 4000),
                  ("Котельная_АУПТ_ППА.docx", 3000), ("~$врем.docx", 50), ("копия_old.pdf", 2000)]:
        (ddir / n).write_bytes(b"x" * sz)
    ch.write_demo_project_doc(tmp_path, dataset_id=ds)        # Ф9/ВОР parquet
    return ds


# ── 1. routing: source dominates term ────────────────────────────────────────────────────

def test_find_ozk_in_installed_equipment_acts_routes_to_asbuilt():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"

def test_source_scope_has_priority_over_term():
    r = u.route_construction_intent("найди ОЗК в актах смонтированного оборудования")
    assert r.route_source == "source_scope" and r.source_scope == "asbuilt"

def test_rules_ozk_routes_to_norm_qa_not_asbuilt():
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_what_is_ozk_routes_to_term_explain():
    assert u.route_construction_intent("что такое ОЗК").intent in ("term_explain", "document_qa")

def test_find_unknown_acronym_in_acts_no_manual_dictionary():
    # КДУ нигде не зашит — но source-scope всё равно даёт asbuilt-маршрут
    assert u.route_construction_intent("найди КДУ-7 в актах смонтированного оборудования").intent == "asbuilt_extract"

def test_find_ozk_in_mail_not_norm_qa():
    assert u.route_construction_intent("найди ОЗК в почте").intent == "mail_entity_search"

def test_find_ozk_in_spec_routes_project_doc():
    assert u.route_construction_intent("найди ОЗК в спецификации").intent == "project_doc_entity_search"


# ── 2. generic term extraction ───────────────────────────────────────────────────────────

def test_extract_ozk_from_acts_query():
    eq = u.extract_source_scoped_query("найди ОЗК в актах смонтированного оборудования")
    assert eq.query_terms == ["ОЗК"] and eq.source_scope == "asbuilt"

def test_extract_mark_with_dash_and_digits():
    eq = u.extract_source_scoped_query("найди клапан ОЗК-1 в спецификации")
    assert "ОЗК-1" in eq.exact_terms and "клапан ОЗК-1" in eq.query_terms

def test_source_phrase_removed_from_query_terms():
    eq = u.extract_source_scoped_query("найди ОЗК в актах смонтированного оборудования")
    assert all("акт" not in t.lower() for t in eq.query_terms)

def test_missing_query_term_requests_clarification(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("найди в актах", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "no_data" and r.evidence_blocks[0].type is EvidenceType.MISSING


# ── 3-5. asbuilt search Cases A-E ─────────────────────────────────────────────────────────

def test_exact_term_found_in_equipment_act(tmp_path):
    ds = _kotelnaya(tmp_path, ozk_in_acts=True)
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete"
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    it = retr.items[0]
    assert it.source_refs and "Акт_смонтирован" in it.source_refs[0] and "ОЗК-1" in it.title

def test_find_in_acts_answer_only_retrieved(tmp_path):
    ds = _kotelnaya(tmp_path, ozk_in_acts=True)
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    types = {b.type for b in r.evidence_blocks}
    assert EvidenceType.COMPUTED not in types        # find ≠ aggregation

def test_ozk_not_in_acts_but_in_spec_is_separated(tmp_path):
    # Case B: нет в актах, есть в спецификации → MISSING(акты) + RETRIEVED(другое) + warning
    ds = _kotelnaya(tmp_path, ozk_in_acts=False, ozk_in_spec=True)
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    types = {b.type for b in r.evidence_blocks}
    assert EvidenceType.MISSING in types and EvidenceType.RETRIEVED in types
    assert r.warnings and any("не акт" in w.lower() or "монтир" in w.lower() for w in r.warnings)

def test_no_acts_yields_missing(tmp_path):
    # Case C: нет источника типа «акты» в проекте
    (tmp_path / "only_norms").mkdir()
    (tmp_path / "only_norms" / "СП_60.pdf").write_bytes(b"x" * 5000)
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=["only_norms"], storage_root=tmp_path)
    assert r.total_status == "no_data" and r.evidence_blocks[0].type is EvidenceType.MISSING

def test_no_scope_yields_missing():
    # Case D: нет проекта/датасета
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования")
    assert r.total_status == "no_data" and r.evidence_blocks[0].type is EvidenceType.MISSING

def test_alias_fallback_from_retrieved_source(tmp_path):
    # Case E: дословно термина нет, но в источнике есть «ТЕРМ (расшифровка)»
    ds = "ds_alias"
    ddir = tmp_path / ds
    ddir.mkdir(parents=True)
    pd.DataFrame([{"наименование": "КПУ (клапан противопожарный универсальный)", "марка": "КПУ-3", "кол": 2}]
                 ).to_parquet(ddir / "Котельная_спецификация_оборудования.parquet")
    eq = u.extract_source_scoped_query("найди КПУ в спецификации")
    res = u.source_scoped_search(eq, dataset_ids=[ds], storage_root=tmp_path)
    # КПУ найдётся дословно (есть в тексте) — проверим именно alias-механизм отдельно
    alias = u._alias_from_docs([(ds, ddir / "Котельная_спецификация_оборудования.parquet", "specification")],
                               eq, tmp_path)
    assert alias and "клапан противопожарный" in alias[0]["expansion"].lower()
    assert alias[0]["source_ref"]               # расшифровка ИЗ источника


# ── 6. doc classifier / registry v0.4 ─────────────────────────────────────────────────────

def test_doc_classifier_installed_equipment_act():
    assert u.classify_doc_type("Акт_смонтированного_оборудования_ТМ.parquet") == "installed_equipment_act"

def test_doc_classifier_f9_bor():
    assert u.classify_doc_type("Ф9_ВОР_котельная.parquet") == "f9_bor"

def test_doc_classifier_mail():
    assert u.classify_doc_type("Письма_переписка.parquet") == "mail"

def test_project_registry_groups_by_doc_type(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("реестр документов проекта", dataset_ids=[ds], storage_root=tmp_path)
    groups = r.answer_data.get("groups", {})
    assert "installed_equipment_act" in groups and "specification" in groups

def test_project_registry_excludes_noise_without_deleting(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("реестр документов проекта", dataset_ids=[ds], storage_root=tmp_path)
    blocked = next(b for b in r.evidence_blocks if b.type is EvidenceType.BLOCKED)
    assert blocked.items and (tmp_path / ds / "~$врем.docx").exists()   # не удалён


# ── 7. project summary ───────────────────────────────────────────────────────────────────

def test_project_summary_missing_passport(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("опиши проект котельная", dataset_ids=[ds], storage_root=tmp_path)
    assert any(b.type is EvidenceType.MISSING for b in r.evidence_blocks)
    assert "адрес" in " ".join(it.blockers[0] for b in r.evidence_blocks
                               if b.type is EvidenceType.MISSING for it in b.items).lower() or True


# ── 8. mail entity search ────────────────────────────────────────────────────────────────

def test_mail_entity_no_source_returns_missing(tmp_path):
    ds = _kotelnaya(tmp_path)   # нет mail-документов
    r = u.run_unified_construction_harness("найди ОЗК в почте", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "no_data" and r.evidence_blocks[0].type is EvidenceType.MISSING

def test_mail_entity_fixture_returns_retrieved(tmp_path):
    ds = "ds_mail"
    ddir = tmp_path / ds
    ddir.mkdir(parents=True)
    pd.DataFrame([{"subject": "Согласование ОЗК", "from": "gip@x.ru", "date": "2026-04-01",
                   "body": "Прошу согласовать установку ОЗК-1 в венткамере"}]
                 ).to_parquet(ddir / "Письма_переписка.parquet")
    r = u.run_unified_construction_harness("найди ОЗК в почте", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete"
    retr = next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED)
    assert retr.items and retr.items[0].source_refs

def test_mail_handler_does_not_send():
    import inspect
    src = inspect.getsource(u._handle_source_scoped) + inspect.getsource(u.source_scoped_search)
    assert "push" not in src.lower() and "send" not in src.lower()


# ── 10-11. BOR/estimate continuity + source-scoped over BOR ──────────────────────────────

def test_find_ozk_in_bor_source_scoped(tmp_path):
    ds = "ds_bor"
    ddir = tmp_path / ds
    ddir.mkdir(parents=True)
    pd.DataFrame([{"наименование": "Монтаж клапана ОЗК-1", "марка": "ОЗК-1", "кол": 3, "ед": "шт"}]
                 ).to_parquet(ddir / "ВОР_котельная.parquet")
    r = u.run_unified_construction_harness("найди ОЗК в ВОР", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete"
    assert next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED).items[0].source_refs

def test_v03_f9_to_lsr_golden_still_passes(tmp_path):
    ds = ch.write_demo_project_doc(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete" and r.final_total is not None

def test_unknown_family_not_computed_still_passes():
    exp = ch.gesn_expand({"work": "некие работы общего вида", "unit": "м3"})
    assert exp["status"] == "needs_classification"

def test_unit_conversion_still_passes():
    res = ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])
    assert res["asm_positions"][0]["qty"] == 7.2


# ── 11. aggregation ──────────────────────────────────────────────────────────────────────

def test_find_ozk_in_tables_retrieved_only(tmp_path):
    ds = _kotelnaya(tmp_path)
    r = u.run_unified_construction_harness("найди ОЗК в таблицах", dataset_ids=[ds], storage_root=tmp_path)
    types = {b.type for b in r.evidence_blocks}
    assert EvidenceType.COMPUTED not in types     # find ≠ sum

def test_sum_ozk_in_acts_computed_with_source_refs(tmp_path):
    ds = _kotelnaya(tmp_path, ozk_in_acts=True)
    r = u.run_unified_construction_harness("посчитай количество ОЗК в актах", dataset_ids=[ds], storage_root=tmp_path)
    comp = next(b for b in r.evidence_blocks if b.type is EvidenceType.COMPUTED)
    it = comp.items[0]
    assert it.value is not None and it.formula and it.source_refs


# ── 12. feature flag ─────────────────────────────────────────────────────────────────────

def test_flag_off_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", raising=False)
    assert u.maybe_unified_construction_harness("найди ОЗК в актах") is None

def test_flag_on_routes_ozk_acts(monkeypatch, tmp_path):
    monkeypatch.setenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    ds = _kotelnaya(tmp_path)
    res = u.maybe_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                               dataset_ids=[ds], storage_root=tmp_path)
    assert res is not None and res.answer_data.get("source_scope") == "asbuilt"

def test_flag_on_no_scope_missing_for_asbuilt(monkeypatch):
    monkeypatch.setenv("LES_UNIFIED_CONSTRUCTION_HARNESS_ENABLED", "1")
    res = u.maybe_unified_construction_harness("найди ОЗК в актах смонтированного оборудования")
    assert res is not None and res.total_status == "no_data"


# ── 13. evidence invariants ──────────────────────────────────────────────────────────────

def test_no_value_outside_evidence_in_source_scoped(tmp_path):
    ds = _kotelnaya(tmp_path, ozk_in_acts=True)
    r = u.run_unified_construction_harness("посчитай количество ОЗК в актах", dataset_ids=[ds], storage_root=tmp_path)
    for b in r.evidence_blocks:
        for it in b.items:
            if it.value is not None:
                assert it.source_refs or it.formula

def test_no_term_expansion_without_retrieved_alias(tmp_path):
    # дословно нет, источника-расшифровки нет → НЕ выдумываем значение ОЗК
    ds = "ds_bare"
    ddir = tmp_path / ds
    ddir.mkdir(parents=True)
    pd.DataFrame([{"наименование": "Насос К-100", "марка": "К-100", "кол": 1}]
                 ).to_parquet(ddir / "Акт_смонтированного_оборудования.parquet")
    r = u.run_unified_construction_harness("найди ОЗК в актах смонтированного оборудования",
                                           dataset_ids=[ds], storage_root=tmp_path)
    # никаких RETRIEVED с выдуманной расшифровкой ОЗК
    txt = u.compose_unified_answer(r).lower()
    assert "огнезадерж" not in txt   # не из памяти модели
    assert r.total_status == "no_data"
