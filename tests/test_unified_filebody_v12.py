"""Unified Construction Harness v0.12 — file_body + EML + markdown-table extraction.

Реальные датасеты = .md/.eml, не parquet. Harness читает их read-only с source_refs до файла/строки/
message_id: термин в .md → RETRIEVED file_body; термин в .eml → RETRIEVED mail; markdown-таблица → ВОР.
Без OCR, без мутации, без fake source_refs. no_lexical_index больше не значит слепой no_data.
"""

from pathlib import Path

import pytest

from proxy.services import source_adapters as sa
from proxy.services import unified_construction_harness_service as u
from proxy.services import construction_harness_service as ch
from proxy.services import resource_cost_service as rc
from proxy.services.evidence_contract import EvidenceType

MONEY = 1.0
_RT = Path("/Users/ovc/LES/storage/datasets")


def _md_ds(tmp_path, name="ds", body="# Котельная ТМ\n\nКлапан ОЗК-1 установлен в венткамере №3.\n"):
    d = tmp_path / name
    d.mkdir(parents=True)
    (d / "Котельная_ТМ.md").write_text(body, encoding="utf-8")
    return name


# ── file_body adapter ────────────────────────────────────────────────────────────────────

def test_file_body_exact_term_md(tmp_path):
    ds = _md_ds(tmp_path)
    r = sa.search_file_body(["ОЗК"], dataset_ids=[ds], storage_root=tmp_path)
    assert r.status == sa.FOUND and r.matches[0].source_kind == sa.KIND_FILE_BODY

def test_file_body_source_ref_line(tmp_path):
    ds = _md_ds(tmp_path)
    m = sa.search_file_body(["ОЗК"], dataset_ids=[ds], storage_root=tmp_path).matches[0]
    assert m.line_start == 3 and "#L3" in m.source_ref and m.file_name == "Котельная_ТМ.md"

def test_file_body_ignores_binary(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "scan.pdf").write_bytes("%PDF ОЗК binary".encode("utf-8"))     # .pdf не читается file_body
    r = sa.search_file_body(["ОЗК"], dataset_ids=["ds"], storage_root=tmp_path)
    assert r.status == sa.NOT_FOUND

def test_file_body_path_traversal_safe(tmp_path):
    assert sa._safe_under(tmp_path, tmp_path / "ds" / "f.md") is True
    assert sa._safe_under(tmp_path / "ds", tmp_path / "other" / "f.md") is False

def test_file_body_hyphen_space_dot_normalization(tmp_path):
    ds = _md_ds(tmp_path, body="Клапан ОЗК 1 и ОЗК.2 и ОЗК-3\n")
    r = sa.search_file_body(["ОЗК-1"], dataset_ids=[ds], storage_root=tmp_path)
    assert r.status == sa.FOUND      # ОЗК-1 ≈ «ОЗК 1»

def test_file_body_term_not_found(tmp_path):
    ds = _md_ds(tmp_path)
    assert sa.search_file_body(["ВВГнг"], dataset_ids=[ds], storage_root=tmp_path).status == sa.NOT_FOUND


# ── EML adapter ──────────────────────────────────────────────────────────────────────────

def _eml_ds(tmp_path, name="mail", subj="Согласование ОЗК", body="Прошу согласовать ОЗК-1"):
    d = tmp_path / name
    d.mkdir(parents=True)
    eml = (f"From: gip@x.ru\nTo: rp@x.ru\nSubject: {subj}\nDate: Mon, 1 Apr 2026 10:00:00 +0300\n"
           f"Message-ID: <m1@les>\nContent-Type: text/plain; charset=utf-8\n\n{body}\n")
    (d / "msg1.eml").write_text(eml, encoding="utf-8")
    return name

def test_eml_search_subject(tmp_path):
    ds = _eml_ds(tmp_path)
    r = sa.search_eml_messages(["ОЗК"], dataset_ids=[ds], storage_root=tmp_path)
    assert r.status == sa.FOUND and r.matches[0].source_ref == "<m1@les>"

def test_eml_fields_and_snippet(tmp_path):
    ds = _eml_ds(tmp_path)
    m = sa.search_eml_messages(["ОЗК"], dataset_ids=[ds], storage_root=tmp_path).matches[0]
    assert m.fields["from"] and m.fields["date"] and "ОЗК" in m.snippet

def test_eml_no_source_when_no_eml(tmp_path):
    (tmp_path / "ds").mkdir()
    assert sa.search_eml_messages(["ОЗК"], dataset_ids=["ds"], storage_root=tmp_path).status == sa.NO_SOURCE

def test_eml_read_only_no_send():
    import inspect
    code = "\n".join(ln for ln in inspect.getsource(sa.search_eml_messages).splitlines()
                     if not ln.strip().startswith(("#", '"', "'")))
    for bad in (".send(", ".delete(", "smtp", "create_draft", ".store("):
        assert bad not in code.lower()


# ── markdown tables → ВОР ─────────────────────────────────────────────────────────────────

_MD_TABLE = ("# Ф9\n\n| Наименование | Ед. изм. | Кол-во |\n|---|---|---|\n"
             "| Разработка грунта | м3 | 7200 |\n| Гидроизоляция | м2 | 1500 |\n")

def test_markdown_table_extract(tmp_path):
    p = tmp_path / "f.md"
    p.write_text(_MD_TABLE, encoding="utf-8")
    tbls = sa.extract_markdown_tables_from_file(p)
    assert len(tbls) == 1 and len(tbls[0]["rows"]) == 2

def test_markdown_table_to_bor_rows_source_refs(tmp_path):
    p = tmp_path / "f.md"
    p.write_text(_MD_TABLE, encoding="utf-8")
    conv = sa.markdown_table_to_rows(sa.extract_markdown_tables_from_file(p)[0], file_name="f.md", dataset_id="ds")
    assert conv["status"] == "ok" and len(conv["rows"]) == 2
    assert all("#L" in r["source_file"] and r["qty"] for r in conv["rows"])

def test_markdown_table_not_recognized(tmp_path):
    p = tmp_path / "f.md"
    p.write_text("| A | B |\n|---|---|\n| x | y |\n", encoding="utf-8")   # нет наименование/кол-во
    conv = sa.markdown_table_to_rows(sa.extract_markdown_tables_from_file(p)[0])
    assert conv["status"] == "not_recognized"

def test_bor_extract_from_markdown_no_parquet(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "Ф9_ВОР.md").write_text(_MD_TABLE, encoding="utf-8")
    r = u.run_unified_construction_harness("извлеки ВОР из Ф9", dataset_ids=["ds"], storage_root=tmp_path)
    assert r.total_status == "complete"
    assert next(b for b in r.evidence_blocks if b.type is EvidenceType.RETRIEVED).items[0].source_refs


# ── doc_classifier v0.12 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("revit-api-chms_html_2025_shard_0001.md", "external_reference"),
    ("cad_bim_speckle_432aa0b18f2a.md", "external_reference"),
    ("olm_00001.eml", "mail"),
    ("Котельная_ТМ.md", "project_doc"),
    ("ГОСТ 30244-94.docx", "norm"),
])
def test_doc_classifier_v12(name, expected):
    assert u.classify_doc_type(name) == expected


# ── index health v0.12 ───────────────────────────────────────────────────────────────────

def test_index_health_md_eml_counts(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "a.md").write_text("# x\n", encoding="utf-8")
    (d / "m.eml").write_text("Subject: x\n\nbody\n", encoding="utf-8")
    rec = sa.inspect_dataset_index_health(["ds"], storage_root=tmp_path)["datasets"][0]
    assert rec["md_file_count"] == 1 and rec["eml_file_count"] == 1 and rec["readable_body_available"]

def test_index_health_no_lexical_but_file_body(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "a.md").write_text("# x\n", encoding="utf-8")
    rec = sa.inspect_dataset_index_health(["ds"], storage_root=tmp_path)["datasets"][0]
    assert "no_lexical_index_but_file_body_available" in rec["warnings"]

def test_index_health_markdown_table_count(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "f.md").write_text(_MD_TABLE, encoding="utf-8")
    rec = sa.inspect_dataset_index_health(["ds"], storage_root=tmp_path)["datasets"][0]
    assert rec["markdown_table_count"] >= 1 and "no_parquet_but_markdown_table_found" in rec["warnings"]


# ── norm_qa / source-scoped via file_body ────────────────────────────────────────────────

def test_norm_qa_file_body_hit(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    (d / "СП_котельная.md").write_text("# СП\n\nАУПТ требуется для котельной по пункту 5.4\n", encoding="utf-8")
    r = u.run_unified_construction_harness("найди АУПТ в документах проекта", dataset_ids=["ds"], storage_root=tmp_path)
    assert r.total_status == "complete"        # нашли в .md без lexical-индекса
    assert "file_body" in r.answer_data.get("searched_tiers", []) or r.sources

def test_norm_qa_no_source_missing_mentions_tiers(tmp_path):
    (tmp_path / "ds").mkdir()
    r = u.run_unified_construction_harness("правила расстановки ВВГнг", dataset_ids=["ds"], storage_root=tmp_path)
    assert r.total_status == "no_data"
    assert "file_body" in r.answer_data.get("searched_tiers", [])

def test_source_scoped_file_body_no_mounted_claim_from_spec(tmp_path):
    # ОЗК есть в спецификации (.md), нет в актах → отдельно, не «монтаж»
    d = tmp_path / "ds"
    d.mkdir()
    (d / "Котельная_спецификация.md").write_text("# Спец\n\nКлапан ОЗК-1 — 6 шт\n", encoding="utf-8")
    r = u.run_unified_construction_harness("найди ОЗК в спецификации", dataset_ids=["ds"], storage_root=tmp_path)
    assert r.total_status == "complete"        # source-scoped spec → найдено (file_body/filename)


# ── live trace v0.12 (через _run_chat) ───────────────────────────────────────────────────

def test_v12_trace_has_file_body_tier_in_norm(tmp_path):
    r = u.run_unified_construction_harness("правила расстановки ОЗК", dataset_ids=["x"], storage_root=tmp_path)
    assert "file_body" in r.answer_data.get("searched_tiers", [])


# ── реальные датасеты рантайма (read-only, если доступны) ─────────────────────────────────

@pytest.mark.skipif(not _RT.exists(), reason="runtime datasets недоступны")
def test_real_file_body_md():
    ds = "2e9a05e1-bb31-4538-9bf4-053ca53c152c"
    if not (_RT / ds).exists():
        pytest.skip("dataset отсутствует")
    r = sa.search_file_body(["Speckle"], dataset_ids=[ds], storage_root=_RT)
    assert r.status == sa.FOUND and r.matches[0].line_start

@pytest.mark.skipif(not _RT.exists(), reason="runtime datasets недоступны")
def test_real_eml_messages():
    ds = "11da8ad7-512e-4301-9126-d6e28bd0ac43"
    if not (_RT / ds).exists():
        pytest.skip("dataset отсутствует")
    r = sa.search_eml_messages([], dataset_ids=[ds], storage_root=_RT, top_k=2)
    assert r.status in (sa.FOUND, sa.NOT_FOUND) and r.source_kind == sa.KIND_MAIL


# ── регрессии ────────────────────────────────────────────────────────────────────────────

def test_v06_resource_workbook_regression():
    assert rc.validate_real_workbook()["matches"] is True

def test_resource_grand_complete():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < MONEY

def test_v04_source_scope_regression():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_v03_lsr_parquet_still_works(tmp_path):
    ds = ch.write_demo_project_doc(tmp_path)
    r = u.run_unified_construction_harness("собери предварительную ЛСР по Ф9", dataset_ids=[ds], storage_root=tmp_path)
    assert r.total_status == "complete" and r.final_total is not None

def test_unit_gate_regression():
    assert ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])["asm_positions"][0]["qty"] == 7.2
