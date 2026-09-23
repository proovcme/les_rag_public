# -*- coding: utf-8
"""Route-1 (spec -> VOR): an item that only matched a dictionary rule must not be
presented as a confirmed installation work; the item, its quantity and provenance
are preserved and the conversion is flagged as requiring a decision."""
from __future__ import annotations

from proxy.services.spec_to_bor_service import (
    _name_is_explicit_work,
    spec_rows_to_work_lines_v2,
)


def _spec(name, unit, qty, **kw):
    row = {"doc_type": "SPEC", "name": name, "unit": unit, "qty": qty,
           "source_file": "spec.xlsx", "pos": "1"}
    row.update(kw)
    return row


def test_item_name_is_not_an_explicit_work():
    assert _name_is_explicit_work("Светильник LED") is False
    assert _name_is_explicit_work("Кабель ВВГнг") is False
    assert _name_is_explicit_work("Монтаж шкафа") is True
    assert _name_is_explicit_work("Прокладка кабеля") is True
    # an adjective that merely resembles a verb stays a proposal, not confirmed
    assert _name_is_explicit_work("Монтажный блок") is False


def test_item_conversion_requires_decision_and_keeps_item():
    lines = spec_rows_to_work_lines_v2([_spec("Светильник LED", "шт", 24.0)])
    assert lines
    for line in lines:
        assert line.requires_decision is True
        assert line.original_item == "Светильник LED"
        assert "ТРЕБУЕТ РЕШЕНИЯ" in line.note
    # the item quantity is carried, not invented
    assert any(abs(line.qty - 24.0) < 1e-9 for line in lines)


def test_explicit_work_is_not_flagged():
    lines = spec_rows_to_work_lines_v2([_spec("Монтаж шкафа", "шт", 4.0)])
    assert lines
    assert all(line.requires_decision is False for line in lines)


def test_harness_marks_vor_incomplete_until_resolved():
    from proxy.services.construction_harness_service import spec_to_bor

    item_only = spec_to_bor([_spec("Кабель ВВГнг", "м", 100.0)])
    assert item_only["status"] == "ok"
    assert item_only["requires_decision_count"] >= 1
    assert item_only["complete"] is False
    assert any(p.get("requires_decision") for p in item_only["positions"])

    resolved = spec_to_bor([_spec("Установка розетки", "шт", 10.0)])
    assert resolved["complete"] is True
    assert resolved["requires_decision_count"] == 0
