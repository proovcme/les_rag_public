"""Unit tests for Flexible Code Resolver in smeta document_workflow."""
import pytest
from proxy.smeta_core.document_workflow import resolve_extracted_norm_code_flexible


def test_flexible_resolver_preserves_existing_bind():
    item = {
        "work_id": "vor-0001",
        "decision": "bind",
        "norm_code": "ГЭСНм37-01-002-01",
        "reason": "Explicit norm chosen",
    }
    result = resolve_extracted_norm_code_flexible(dict(item))
    assert result["decision"] == "bind"
    assert result["norm_code"] == "ГЭСНм37-01-002-01"


def test_flexible_resolver_extracts_table_code_from_covered_by_reason():
    item = {
        "work_id": "vor-0010",
        "decision": "covered_by",
        "covered_by_work_id": "vor-0010",
        "reason": "Патч-корд Cat.6a; таблица 11-04-027 покрывает монтаж.",
    }
    by_id = {"vor-0010": {"unit": "шт."}}
    opened_cards = {}

    result = resolve_extracted_norm_code_flexible(dict(item), by_id=by_id, opened_cards=opened_cards)

    assert result["decision"] == "bind"
    assert "11-04-027" in result["norm_code"]
    assert result["selection_kind"] == "exact"
    assert "vor-0010" in opened_cards


def test_flexible_resolver_extracts_table_code_from_unbound_reason():
    item = {
        "work_id": "vor-0007",
        "decision": "unbound",
        "covered_by_work_id": "",
        "reason": "Монтаж патч-панели относится к таблице 11-04-027",
    }
    opened_cards = {}

    result = resolve_extracted_norm_code_flexible(dict(item), opened_cards=opened_cards)

    assert result["decision"] == "bind"
    assert "11-04-027" in result["norm_code"]
    assert "vor-0007" in opened_cards


def test_flexible_resolver_ignores_plain_text_without_codes():
    item = {
        "work_id": "vor-0002",
        "decision": "unbound",
        "covered_by_work_id": "",
        "reason": "Кабельный организатор без явной нормы в каталоге",
    }
    result = resolve_extracted_norm_code_flexible(dict(item))
    assert result["decision"] == "unbound"
    assert result.get("norm_code", "") == ""
