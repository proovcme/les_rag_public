"""Actual reader/row/trace regressions; every normative source is synthetic."""

import copy
import hashlib
import os
import sqlite3

import pytest

from proxy.services import gesn_service as norms
from proxy.services import rim_lsr_trace_service as trace
from proxy.services.lsr_norm_quality_gate_service import ciphers_compatible
from proxy.services.lsr_result_readiness_service import build_lsr_result_readiness, format_lsr_readiness_notice


CODE = "ГЭСН01-01-001-01"
OTHER_FAMILY = "ГЭСНм01-01-001-01"


@pytest.fixture
def normative_base(tmp_path, monkeypatch):
    path = tmp_path / "norms.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE norms (norm_key TEXT PRIMARY KEY, display_code TEXT,
                base_type TEXT, norm_name TEXT, norm_unit TEXT, work_steps TEXT);
            CREATE TABLE resources (id INTEGER PRIMARY KEY, norm_key TEXT,
                kind TEXT, resource_code TEXT, resource_name TEXT,
                resource_unit TEXT, per_unit REAL, price REAL);
        """)
        for number, (family, code, per_unit) in enumerate(
            [("ГЭСН", CODE, 2.0), ("ГЭСНм", OTHER_FAMILY, 7.0)], start=1
        ):
            key = f"{family}:01-01-001-01"
            conn.execute("INSERT INTO norms VALUES (?, ?, ?, ?, ?, ?)",
                         (key, code, family, "Монтаж элемента", "шт.", '["Монтаж элемента"]'))
            conn.execute("INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (number, key, "labor", "1-100-25", "Рабочие", "чел.-ч", per_unit, 100.0))
    monkeypatch.setattr(norms, "_structured_base_path", lambda: path)
    monkeypatch.setattr(norms, "load_overlay_norms", lambda: {})
    monkeypatch.delenv(norms.SEED_ENV_VAR, raising=False)
    norms.load_base_norms.cache_clear()
    norms.load_structured_base_norms.cache_clear()
    yield path
    norms.load_base_norms.cache_clear()
    norms.load_structured_base_norms.cache_clear()


def selected_row(code=CODE, *, sha=None):
    row = {"source_row": "Source!R2", "row_role": "work", "name": "Монтаж элемента",
           "norm_code": code, "norm_status": "ANALOGUE_CANDIDATE", "quantity": 1,
           "unit": "шт.", "norm_quantity": 1,
           "_evidence_check": {"card_body_shown": True}}
    if sha is not None:
        row["_evidence_check"].update(normative_base_sha256=sha,
                                      norm_key="ГЭСН:01-01-001-01")
    return row


def replace_resource_quantity(path, value):
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE resources SET per_unit=? WHERE norm_key=?",
                     (value, "ГЭСН:01-01-001-01"))


@pytest.mark.parametrize("left,right", [
    ("01-01-001-01", CODE),
    ("ГЭСН01-01-001", CODE),
    (CODE, OTHER_FAMILY),
])
def test_cited_item_identity_requires_complete_same_family(left, right):
    assert ciphers_compatible(left, right) is False


def test_presentation_only_code_variants_still_match():
    assert ciphers_compatible("**ГЭСНм: 01–01–001–01**", OTHER_FAMILY)


def test_bare_authored_code_is_preserved_as_identity_conflict(normative_base):
    row = selected_row("01-01-001-01")
    before = copy.deepcopy(row)
    result = trace.positions_from_visible_lsr_rows([row])
    positions, bindings = result["positions"], result["row_bindings"]
    assert positions == []
    assert bindings[0]["status"] == "norm_identity_conflict"
    assert bindings[0]["code"] == "01-01-001-01"
    assert row == before
    assert bindings[0]["source_row"] == before


def test_two_qualified_families_resolve_their_own_resources(normative_base):
    sha = hashlib.sha256(normative_base.read_bytes()).hexdigest()
    other = {**selected_row(OTHER_FAMILY, sha=sha), "source_row": "Source!R3"}
    other["_evidence_check"]["norm_key"] = "ГЭСНм:01-01-001-01"
    result = trace.positions_from_visible_lsr_rows(
        [selected_row(CODE, sha=sha), other])
    positions, bindings = result["positions"], result["row_bindings"]
    assert [binding["status"] for binding in bindings] == ["bound", "bound"]
    assert [trace._position_resources(position)[1][0]["per_unit"] for position in positions] == [2, 7]


@pytest.mark.parametrize("missing_field", ["normative_base_sha256", "norm_key"])
def test_application_bound_row_without_full_generation_stamp_cannot_silently_use_current_base(
    normative_base, missing_field
):
    row = selected_row(sha=hashlib.sha256(normative_base.read_bytes()).hexdigest())
    row["_evidence_check"].pop(missing_field)
    before = copy.deepcopy(row)
    result = trace.build_lsr_trace_from_visible_rows([row])
    assert result["summary"]["positions_built"] == 0
    assert result["summary"]["selected_norms"] == 1
    assert result["summary"]["normative_generation_unconfirmed_rows"] == 1
    assert result["row_projection"][0]["status"] == "normative_generation_conflict"
    assert result["row_projection"][0]["normative_generation_reason"] == "cited_normative_generation_unconfirmed"
    assert result["row_projection"][0]["norm_status"] == "ANALOGUE_CANDIDATE"
    assert row == before


def test_legacy_manual_row_without_evidence_record_retains_its_authored_choice(normative_base):
    row = selected_row()
    row.pop("_evidence_check")
    result = trace.positions_from_visible_lsr_rows([row])
    assert result["row_bindings"][0]["status"] == "bound"
    assert result["row_bindings"][0]["norm_status"] == "ANALOGUE_CANDIDATE"


def test_same_path_changed_bytes_refresh_reader_without_cache_clear(normative_base):
    first = norms.get_norm(CODE)
    old_stat = normative_base.stat()
    old_sha = hashlib.sha256(normative_base.read_bytes()).hexdigest()
    replace_resource_quantity(normative_base, 9.0)
    assert normative_base.stat().st_size == old_stat.st_size
    os.utime(normative_base, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    assert hashlib.sha256(normative_base.read_bytes()).hexdigest() != old_sha
    second = norms.get_norm(CODE)
    assert first["resources"][0]["per_unit"] == 2
    assert second["resources"][0]["per_unit"] == 9
    assert second["_source_sha256"] != first["_source_sha256"]


def test_callers_cannot_edit_resources_inside_the_cached_source_generation(normative_base):
    selected = norms.get_norm(CODE)
    selected["resources"][0]["per_unit"] = 999
    fresh = norms.get_norm(CODE)
    assert fresh["resources"][0]["per_unit"] == 2
    assert fresh["_source_sha256"] == selected["_source_sha256"]


def test_explicit_demo_seed_also_refreshes_when_bytes_change_at_one_path(tmp_path):
    seed = tmp_path / "seed.yaml"
    template = ('norms:\n  - code: "' + CODE + '"\n    unit: "шт."\n'
                '    resources:\n      - kind: labor\n        name: "Рабочие"\n        per_unit: {}\n')
    seed.write_text(template.format(2), encoding="utf-8")
    absent_base = str(tmp_path / "absent.sqlite")
    first = norms.get_norm(CODE, path=str(seed), base_path=absent_base)
    seed.write_text(template.format(9), encoding="utf-8")
    second = norms.get_norm(CODE, path=str(seed), base_path=absent_base)
    assert first["resources"][0]["per_unit"] == 2
    assert second["resources"][0]["per_unit"] == 9
    assert second["_source_kind"] == norms.SEED_SOURCE_KIND
    assert second["_source_sha256"] != first["_source_sha256"]


def test_change_during_typed_read_fails_without_poisoning_snapshot_cache(normative_base, monkeypatch):
    connect = norms._connect_structured_base_readonly

    class ChangingConnection:
        def __init__(self, path):
            self.connection = connect(path)

        @property
        def row_factory(self):
            return self.connection.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self.connection.row_factory = value

        def execute(self, *args):
            return self.connection.execute(*args)

        def close(self):
            self.connection.close()
            replace_resource_quantity(normative_base, 9.0)

    monkeypatch.setattr(norms, "_connect_structured_base_readonly", ChangingConnection)
    with pytest.raises(norms.NormativeSnapshotConflict, match="changed during reading"):
        norms.get_norm(CODE)
    monkeypatch.setattr(norms, "_connect_structured_base_readonly", connect)
    assert norms.get_norm(CODE)["resources"][0]["per_unit"] == 9


def test_evidence_generation_mismatch_preserves_authored_row_without_calculation(normative_base):
    sha = hashlib.sha256(normative_base.read_bytes()).hexdigest()
    norms.get_norm(CODE)  # warm the same cache the old calculation path used
    row = selected_row(sha=sha)
    before = copy.deepcopy(row)
    replace_resource_quantity(normative_base, 9.0)
    result = trace.positions_from_visible_lsr_rows([row])
    positions, bindings = result["positions"], result["row_bindings"]
    assert positions == []
    assert bindings[0]["status"] == "normative_generation_conflict"
    assert bindings[0]["code"] == CODE
    assert row == before


def test_unreadable_replacement_is_a_generation_conflict_and_keeps_the_model_row(normative_base):
    row = selected_row(sha=hashlib.sha256(normative_base.read_bytes()).hexdigest())
    before = copy.deepcopy(row)
    normative_base.write_bytes(b"not a SQLite database")
    result = trace.positions_from_visible_lsr_rows([row])
    assert result["positions"] == []
    assert result["row_bindings"][0]["status"] == "normative_generation_conflict"
    assert result["row_bindings"][0]["source_row"] == before
    assert row == before


def test_calculation_pins_the_resources_read_with_the_quantity_unit(normative_base):
    sha = hashlib.sha256(normative_base.read_bytes()).hexdigest()
    result = trace.positions_from_visible_lsr_rows([selected_row(sha=sha)])
    positions, bindings = result["positions"], result["row_bindings"]
    assert bindings[0]["status"] == "bound"
    replace_resource_quantity(normative_base, 9.0)
    norms.load_base_norms.cache_clear()
    norms.load_structured_base_norms.cache_clear()
    norm, resources = trace._position_resources(positions[0])
    assert norm["_source_sha256"] == sha
    assert resources[0]["per_unit"] == 2
    summary = trace.build_position_trace(positions[0])["summary"]
    assert summary["labor_qty"] == 2
    assert summary["normative_source_snapshot"]["sha256"] == sha


@pytest.mark.parametrize("check", [
    {"normative_snapshot_conflict": True},
    {"normative_base_sha256": "not-a-sha256"},
])
def test_uncertain_or_invalid_cited_generation_does_not_choose_another_source(normative_base, check):
    row = selected_row()
    row["_evidence_check"].update(check)
    before = copy.deepcopy(row)
    result = trace.build_lsr_trace_from_visible_rows([row])
    assert result["summary"]["positions_built"] == 0
    assert result["summary"]["selected_norms"] == 1
    assert result["row_projection"][0]["status"] == "normative_generation_conflict"
    assert result["row_projection"][0]["norm_status"] == "ANALOGUE_CANDIDATE"
    assert row == before


def test_generation_conflict_is_a_technical_issue_separate_from_the_professional_choice():
    row = {**selected_row(), "norm_status": "EXACT"}
    row["_evidence_check"].update(cited_ciphers=[CODE], citation_checkable=True)
    result = build_lsr_result_readiness(packaged=True, rows=[row],
        pricing_status="priced_final",
        missing=["row:Source!R2:normative_generation_conflict"],
        row_projection=[{"locator": "Source!R2", "status": "normative_generation_conflict",
                         "binding_message": "generation differs"}],
        confirmed_amount=0, preliminary_amount=0)
    assert result["counts"]["norms_selected"] == 1
    assert result["counts"]["norms_applicability_substantiated"] == 1
    assert result["dimensions"]["norms"]["complete"] is True
    assert result["dimensions"]["document_integrity"]["complete"] is False
    assert result["document_issues"] == [{"code": "normative_generation_conflict",
        "locator": "Source!R2", "message": "generation differs"}]
    assert row["norm_status"] == "EXACT"
    notice = format_lsr_readiness_notice(result)
    assert "generation differs" in notice
    assert "Техническая проверка расчёта" in notice
    assert result["counts"]["normative_generation_conflicts"] == 1


def test_selected_counts_are_independent_of_model_applicability_and_money():
    rows = [selected_row(CODE), {**selected_row(OTHER_FAMILY), "source_row": "Source!R3"}]
    for row in rows:
        row.update(action_match="unknown", object_match="unknown", condition_match="unknown",
                   unit_compatible="unknown", composition_covers="unknown")
    before = copy.deepcopy(rows)
    result = build_lsr_result_readiness(packaged=True, rows=rows,
        confirmed_amount=0, preliminary_amount=123.45)
    assert result["counts"]["norms_selected"] == 2
    assert result["counts"]["norms_unique_ciphers"] == 2
    assert result["counts"]["norms_applicability_substantiated"] == 0
    assert result["counts"]["confirmed_amount"] == 0
    assert result["counts"]["preliminary_amount"] == 123.45
    assert rows == before


def test_unique_selection_metric_folds_only_presentation_not_norm_family():
    rows = [selected_row(CODE),
            {**selected_row("ГЭСН: 01–01–001–01"), "source_row": "Source!R3"},
            {**selected_row(OTHER_FAMILY), "source_row": "Source!R4"}]
    result = build_lsr_result_readiness(packaged=True, rows=rows)
    assert result["counts"]["norms_selected"] == 3
    assert result["counts"]["norms_unique_ciphers"] == 2
