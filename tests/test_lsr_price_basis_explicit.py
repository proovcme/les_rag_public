"""ADR-16 § 7 — the estimate path binds a price book only from an explicit basis.

These tests are the mechanical proof for regression «III квартал не сползает на
II»: the configured default must not price an estimate whose subject and period
nobody chose, a requested period that is not installed must be reported with the
books that *are* installed, and city and price zone must stay distinct.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from proxy.services import fgis_price_service
from proxy.services.lsr_workbook_adapter_service import (
    build_lsr_workbook_from_decisions,
    explicit_estimate_pricebook,
    summarize_lsr_price_basis,
)

CATALOG = [
    "sankt-peterburg_2kv2026",
    "sankt-peterburg_3kv2026",
    "leningradskaya_oblast_3kv2026",
    "moskva_3kv2026",
]


def _choice(**overrides):
    kwargs = {
        "requested_book": "",
        "operator_book": "",
        "region_text": "",
        "question_text": "Собери ЛСР по ведомости",
        "source_text": "Ведомость объёмов работ\nЗаказчик: тест",
        "source_name": "vor.xlsx",
        "pricebooks": CATALOG,
    }
    kwargs.update(overrides)
    return explicit_estimate_pricebook(**kwargs)


def test_no_explicit_basis_binds_no_book_and_lists_the_catalog():
    result = _choice()
    assert result["pricebook"] == ""
    assert result["available_books"] == CATALOG
    assert "не подставляется" in result["reason"]
    assert result["basis_binding"] == ""


def test_explicit_parameter_is_bound_without_derivation():
    result = _choice(requested_book="sankt-peterburg_3kv2026", pricebooks=["other_1kv2025"])
    assert result["pricebook"] == "sankt-peterburg_3kv2026"
    assert result["basis_binding"] == "sankt-peterburg_3kv2026"
    assert result["origin"] == "параметр расчёта"


def test_operator_confirmation_of_a_revision_is_explicit():
    result = _choice(operator_book="moskva_3kv2026")
    assert result["pricebook"] == "moskva_3kv2026"
    assert result["origin"] == "подтверждение оператора"


def test_subject_and_quarter_named_in_task_and_source_match_one_book():
    result = _choice(
        question_text="Собери ЛСР по Санкт-Петербургу, цены III квартала 2026 года",
        region_text="",
    )
    assert result["pricebook"] == "sankt-peterburg_3kv2026"
    assert result["origin"].startswith("выведено из:")
    assert result["requested_region"] == "Санкт-Петербург"
    assert result["requested_quarter"] == "3:2026"


def test_period_written_only_in_the_source_file_counts_as_explicit():
    result = _choice(source_text="Локальный сметный расчёт, 3kv2026, СПб")
    assert result["pricebook"] == "sankt-peterburg_3kv2026"


def test_requested_period_absent_is_reported_without_substitution():
    result = _choice(
        question_text="Собери ЛСР по Москве, цены IV квартала 2026 года",
    )
    assert result["pricebook"] == ""
    assert result["basis_binding"].startswith("Москва")
    assert "2026" in result["basis_binding"]
    assert "нет книги для названных" in result["reason"]
    # the rest of the base is never announced as missing
    assert result["available_books"] == CATALOG


def test_subject_outside_the_catalog_binds_no_book():
    result = _choice(question_text="Собери ЛСР по Омску, цены IV квартала 2026 года")
    assert result["pricebook"] == ""
    assert "субъект" in result["reason"]
    assert result["available_books"] == CATALOG


def test_conflicting_subject_between_task_and_source_is_not_resolved():
    result = _choice(
        question_text="Собери ЛСР по Москве, цены III квартала 2026",
        source_text="Ведомость объёмов работ по Санкт-Петербургу, III квартал 2026",
    )
    assert result["pricebook"] == ""
    assert "регион назван по-разному" in result["reason"]


def test_conflicting_periods_are_not_resolved():
    result = _choice(
        question_text="Собери ЛСР по Санкт-Петербургу, цены III квартала 2026",
        source_text="Уровень цен: 2 квартал 2026 года",
    )
    assert result["pricebook"] == ""
    assert "период цен назван по-разному" in result["reason"]


def test_city_and_price_zone_are_not_identified():
    result = _choice(
        question_text="Собери ЛСР по Ленинградской области, цены III квартала 2026"
    )
    assert result["pricebook"] == "leningradskaya_oblast_3kv2026"
    ambiguity = _choice(
        question_text="Собери ЛСР по Ленинградской области, цены III квартала 2026",
        pricebooks=["sankt-peterburg_3kv2026", "leningradskaya_oblast_3kv2026"],
    )
    assert ambiguity["pricebook"] == "leningradskaya_oblast_3kv2026"
    city = _choice(question_text="Собери ЛСР по СПб, цены III квартала 2026")
    assert city["pricebook"] == "sankt-peterburg_3kv2026"


def test_ambiguous_catalog_for_the_same_basis_asks_instead_of_choosing():
    result = _choice(
        question_text="Собери ЛСР по Санкт-Петербургу, цены III квартала 2026",
        pricebooks=["sankt-peterburg_3kv2026", "spb_3kv2026"],
    )
    assert result["pricebook"] == ""
    assert "несколько книг" in result["reason"]


def test_explicit_only_resolution_never_falls_back_to_the_default(tmp_path):
    for stem in ("sankt-peterburg_2kv2026", "moskva_3kv2026"):
        (tmp_path / f"{stem}.parquet").write_bytes(b"parquet")
    assert (
        fgis_price_service.resolve_pricebook_path(None, root=tmp_path, explicit_only=True)
        is None
    )
    default = fgis_price_service.resolve_pricebook_path(None, root=tmp_path)
    assert default and Path(default).name == "sankt-peterburg_2kv2026.parquet"
    bound = fgis_price_service.resolve_pricebook_path(
        "moskva_3kv2026", root=tmp_path, explicit_only=True
    )
    assert bound and Path(bound).name == "moskva_3kv2026.parquet"


class _Book:
    region = "Город Санкт-Петербург"

    def __init__(self, quarter: str) -> None:
        self.quarter = quarter


def _book_for_path(path: str) -> _Book:
    stamp = re.search(r"([1-4])kv(20\d\d)", Path(str(path)).stem)
    quarter = f"{stamp.group(1)} квартал {stamp.group(2)} г." if stamp else ""
    return _Book(quarter)


@pytest.mark.asyncio
async def test_adapter_keeps_draft_and_binds_only_after_confirmation(tmp_path, monkeypatch):
    captured: dict = {}

    def calculate(_rows, **kwargs):
        captured["pricebook"] = kwargs.get("pricebook")
        return {
            "schema": "rim_lsr_v1",
            "sections": [],
            "summary": {"input_rows": 1, "bound_rows": 1, "result_status": "priced_partial"},
            "row_bindings": [{"row": 1, "status": "bound"}],
        }

    def render(_trace, output_path, **kwargs):
        captured["meta"] = dict(kwargs.get("meta") or {})
        output_path.write_bytes(b"xlsx")
        return output_path

    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.build_lsr_trace_from_visible_rows",
        calculate,
    )
    monkeypatch.setattr(
        "proxy.services.lsr_workbook_adapter_service.render_lsr_xlsx", render
    )
    monkeypatch.setattr(
        fgis_price_service,
        "available_pricebooks",
        lambda *a, **k: [str(tmp_path / f"{stem}.parquet") for stem in CATALOG],
    )
    monkeypatch.setattr(fgis_price_service, "get_pricebook", _book_for_path)

    decisions = [
        {
            "source_row": "ВОР!R4",
            "title": "Прокладка кабеля NYM 3x2.5 в траншее",
            "unit": "м",
            "quantity": 120,
            "norm_code": "ТЕРр08-02-118-01",
        }
    ]
    base_args = {
        "decisions": decisions,
        "question": "Собери ЛСР по Санкт-Петербургу, цены III квартала 2026",
        "_source_text": "Ведомость объёмов работ",
    }
    first = await build_lsr_workbook_from_decisions(
        tmp_path / "vor.xlsx", dict(base_args), tmp_path / "lsr-1.xlsx", lambda *_a: None
    )
    # nothing is priced while the operator has not chosen, and the III-quarter
    # request is never answered with the installed II-quarter book
    assert first["pricebook"] == "sankt-peterburg_3kv2026"
    assert first["price_basis"]["match"] == "exact"
    assert first["price_basis"]["origin"].startswith("выведено из:")
    # the object handed to the calculator is the III-quarter book, not a default
    assert str(captured["pricebook"].quarter) == "3 квартал 2026 г."

    second = await build_lsr_workbook_from_decisions(
        tmp_path / "vor.xlsx",
        {**base_args, "pricebook": "sankt-peterburg_2kv2026"},
        tmp_path / "lsr-2.xlsx",
        lambda *_a: None,
    )
    assert second["pricebook"] == "sankt-peterburg_2kv2026"
    assert second["price_basis"]["match"] == "mismatch"
    assert "2 квартал 2026 г." in second["price_basis"]["note"]
    assert second["price_basis"]["origin"] == "параметр расчёта"

    third = await build_lsr_workbook_from_decisions(
        tmp_path / "vor.xlsx",
        {"decisions": decisions, "question": "Собери ЛСР", "_source_text": "Ведомость"},
        tmp_path / "lsr-3.xlsx",
        lambda *_a: None,
    )
    assert third["pricebook"] == ""
    assert third["price_basis"]["match"] == "no_book"
    assert third["price_basis_choice"]["pricebook"] == ""
    assert "sankt-peterburg_3kv2026" in third["price_basis"]["available_books"]
    assert captured["pricebook"] is None
    assert captured["meta"]["pricebook"] == ""


def test_no_book_note_names_the_requested_basis_and_the_available_books():
    summary = summarize_lsr_price_basis(
        question_text="Собери ЛСР по Санкт-Петербургу, цены IV квартала 2026",
        basis_binding="Санкт-Петербург IV квартала 2026",
        pricebook=None,
        pricebook_name="",
        available_books=CATALOG,
    )
    assert summary["match"] == "no_book"
    assert summary["requested_basis_present"] is True
    assert "Доступные книги" in summary["note"]
    assert "sankt-peterburg_2kv2026" in summary["note"]
    assert "не подменена другой книгой" in summary["note"]


def test_unnamed_basis_note_refuses_the_silent_default():
    summary = summarize_lsr_price_basis(pricebook=None, available_books=CATALOG)
    assert summary["match"] == "no_book"
    assert summary["requested_basis_present"] is False
    assert "книга не выбрана" in summary["note"]
