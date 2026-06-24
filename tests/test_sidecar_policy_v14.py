"""Unified Construction Harness v0.14 — runtime sidecar acceptance + write-policy + staleness.

Запись в runtime storage требует явного разрешения оператора (env + флаг); dry-run по умолчанию;
manifest фиксирует mtime/size → staleness; оригиналы read-only. Test-стабильность: agent_router
герметичен (без сети). Числа/источники не выдумываются.
"""

import importlib.util
from pathlib import Path

import pytest

from proxy.services import doc_extract_service as de
from proxy.services import source_adapters as sa
from proxy.services import unified_construction_harness_service as u
from proxy.services import resource_cost_service as rc
from proxy.services import construction_harness_service as ch


def _xlsx(path, sheet="ВОР", rows=(("Наименование", "Ед", "Кол-во"), ("Грунт", "м3", 7200))):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(list(r))
    wb.save(str(path))


def _load_v14():
    spec = importlib.util.spec_from_file_location("ext_v14", "scripts/extract_dataset_bodies_v14.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── write policy ─────────────────────────────────────────────────────────────────────────

def test_dry_run_does_not_write(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    _xlsx(d / "f.xlsx")
    s = _load_v14()
    rep = s.run("ds", storage_root=tmp_path, exts={".xlsx"}, max_files=10, max_mb=40,
                do_write=False, confirm_runtime=False, force=False)
    assert rep["dry_run"] and rep["wrote_sidecars"] == 0 and rep["would_write"] == 1
    assert de.sidecar_count(tmp_path, "ds") == 0

def test_non_runtime_write_creates_sidecars(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    _xlsx(d / "f.xlsx")
    s = _load_v14()
    rep = s.run("ds", storage_root=tmp_path, exts={".xlsx"}, max_files=10, max_mb=40,
                do_write=True, confirm_runtime=False, force=False)
    # tmp_path не runtime → запись разрешена без подтверждения
    assert not rep["runtime_path"] and rep["wrote_sidecars"] == 1
    assert de.sidecar_count(tmp_path, "ds") == 1 and rep["manifest"]

def test_runtime_write_blocked_without_approval(tmp_path, monkeypatch):
    # эмулируем runtime storage через LES_RUNTIME_HOME
    monkeypatch.setenv("LES_RUNTIME_HOME", str(tmp_path))
    monkeypatch.delenv("LES_ALLOW_RUNTIME_SIDECAR_WRITE", raising=False)
    d = tmp_path / "storage" / "ds"
    d.mkdir(parents=True)
    _xlsx(d / "f.xlsx")
    s = _load_v14()
    rep = s.run("ds", storage_root=tmp_path / "storage", exts={".xlsx"}, max_files=10, max_mb=40,
                do_write=True, confirm_runtime=False, force=False)
    assert rep["runtime_path"] and rep["dry_run"] and "runtime_sidecar_write_not_approved" in rep["write_blocked"]
    assert de.sidecar_count(tmp_path / "storage", "ds") == 0

def test_runtime_write_allowed_with_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("LES_RUNTIME_HOME", str(tmp_path))
    monkeypatch.setenv("LES_ALLOW_RUNTIME_SIDECAR_WRITE", "1")
    d = tmp_path / "storage" / "ds"
    d.mkdir(parents=True)
    _xlsx(d / "f.xlsx")
    s = _load_v14()
    rep = s.run("ds", storage_root=tmp_path / "storage", exts={".xlsx"}, max_files=10, max_mb=40,
                do_write=True, confirm_runtime=True, force=False)
    assert rep["wrote_sidecars"] == 1 and not rep["write_blocked"]

def test_originals_not_mutated(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    _xlsx(d / "f.xlsx")
    before = (d / "f.xlsx").read_bytes()
    s = _load_v14()
    rep = s.run("ds", storage_root=tmp_path, exts={".xlsx"}, max_files=10, max_mb=40,
                do_write=True, confirm_runtime=False, force=False)
    assert rep["originals_mutated"] is False and (d / "f.xlsx").read_bytes() == before


# ── manifest + staleness ─────────────────────────────────────────────────────────────────

def test_manifest_created(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    _xlsx(d / "f.xlsx")
    s = _load_v14()
    s.run("ds", storage_root=tmp_path, exts={".xlsx"}, max_files=10, max_mb=40,
          do_write=True, confirm_runtime=False, force=False)
    man = de.read_manifest(tmp_path, "ds")
    assert man and man["files"] and man["summary"]["xlsx_count"] == 1

def test_sidecar_stale_detection(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    _xlsx(d / "f.xlsx")
    s = _load_v14()
    s.run("ds", storage_root=tmp_path, exts={".xlsx"}, do_write=True, confirm_runtime=False,
          force=False, max_files=10, max_mb=40)
    assert de.sidecar_stale_files(tmp_path, "ds") == []     # свежий
    _xlsx(d / "f.xlsx", rows=(("X", "Y"), ("a", "b"), ("c", "d")))   # изменили оригинал
    assert "f.xlsx" in de.sidecar_stale_files(tmp_path, "ds")        # → stale

def test_index_health_sidecar_stale(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    _xlsx(d / "f.xlsx")
    s = _load_v14()
    s.run("ds", storage_root=tmp_path, exts={".xlsx"}, do_write=True, confirm_runtime=False,
          force=False, max_files=10, max_mb=40)
    _xlsx(d / "f.xlsx", rows=(("X", "Y"), ("a", "b"), ("c", "d")))
    rec = sa.inspect_dataset_index_health(["ds"], storage_root=tmp_path)["datasets"][0]
    assert rec["manifest_present"] and rec["stale_count"] >= 1 and "sidecar_stale" in rec["warnings"]


# ── real dataset dry-run (read-only, если доступен) ──────────────────────────────────────

_RT = Path("/Users/ovc/LES/storage/datasets")
_GOST = "844a2b53-9658-4e5a-92e4-f649de8af043"


@pytest.mark.skipif(not (_RT / _GOST).exists(), reason="runtime dataset недоступен")
def test_real_dataset_dry_run_extracts_docx():
    s = _load_v14()
    rep = s.run(_GOST, storage_root=_RT, exts={".docx"}, max_files=2000, max_mb=40,
                do_write=False, confirm_runtime=False, force=False)
    assert rep["dry_run"] and rep["files_seen"] > 0 and rep["docx_paragraphs"] > 0
    assert rep["wrote_sidecars"] == 0 and rep["originals_mutated"] is False


# ── test stability: agent_router герметичен ──────────────────────────────────────────────

def test_agent_router_classify_hermetic(monkeypatch):
    import proxy.services.agent_router_service as ar
    monkeypatch.setattr(ar, "_route_llm_text", lambda *a, **k: "project_registry")
    assert ar._classify("какие объекты") == "project_registry"   # без сети, мок на реальном пути


# ── регрессии v0.3-v0.13 ─────────────────────────────────────────────────────────────────

def test_v13_extraction_regression(tmp_path):
    d = tmp_path / "ds"
    d.mkdir()
    _xlsx(d / "Ф9.xlsx")
    r = u.run_unified_construction_harness("извлеки ВОР из Ф9", dataset_ids=["ds"], storage_root=tmp_path)
    assert r.total_status == "complete"

def test_v06_resource_workbook_regression():
    assert rc.validate_real_workbook()["matches"] is True

def test_resource_grand_complete():
    r = u.run_unified_construction_harness("проверь пример обсчёта")
    assert r.total_status == "complete" and abs(r.final_total - 16827283.19) < 1.0

def test_v04_source_scope_regression():
    assert u.route_construction_intent("найди ОЗК в актах смонтированного оборудования").intent == "asbuilt_extract"
    assert u.route_construction_intent("правила расстановки ОЗК").intent == "norm_qa"

def test_unit_gate_regression():
    assert ch.lsr_assemble([{"code": "06-02-001-01", "work": "плита", "unit": "м3", "qty": 720}])["asm_positions"][0]["qty"] == 7.2
