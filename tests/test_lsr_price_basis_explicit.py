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


def _stub_the_calculator(monkeypatch, tmp_path) -> dict:
    """Record what the adapter hands the calculation engine and the renderer.

    The installed catalogue must not decide these assertions, so the catalog is
    the module ``CATALOG`` and every book is built from its file name.
    """

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
    return captured


@pytest.mark.asyncio
async def test_adapter_keeps_draft_and_binds_only_after_confirmation(tmp_path, monkeypatch):
    captured = _stub_the_calculator(monkeypatch, tmp_path)

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


#: the shape that produced the live defect: a task that names one subject and a
#: source document whose own object address names another
CONTRADICTED_TASK = "Собери ЛСР по Москве, цены III квартала 2026"
CONTRADICTED_SOURCE = (
    "Ведомость объёмов работ\n"
    "Объект: г. Санкт-Петербург, Выборгский район, ул. Парадная, д. 1\n"
    "Заказчик: тест"
)


def _refused_choice(**overrides):
    kwargs = {
        "question_text": CONTRADICTED_TASK,
        "source_text": CONTRADICTED_SOURCE,
        "source_name": "bap.pdf",
        "pricebooks": CATALOG,
    }
    kwargs.update(overrides)
    return _choice(**kwargs)


def test_a_refused_basis_names_the_two_subjects_instead_of_a_missing_book():
    """ADR-16 § 7 with the live 823 evidence from matrix cell ``B3_bap_pdf``.

    Refusing to pick between Москва (the task) and Санкт-Петербург (the object
    address inside the PDF) is the correct mechanic, and it was already in place.
    What the operator actually read on build 822 was «Запрошенная ценовая база
    „3 квартал 2026" локально не найдена» — a false statement about the local
    catalogue, because ``moskva_3kv2026`` is installed and simply was not chosen.
    """

    result = _refused_choice()
    assert result["pricebook"] == ""
    assert result["refusal"] == "contradiction"
    assert result["contradicting_regions"] == ["Москва", "Санкт-Петербург"]
    assert result["contradicting_quarters"] == []
    assert "moskva_3kv2026" in result["available_books"]

    summary = summarize_lsr_price_basis(
        question_text=CONTRADICTED_TASK,
        pricebook=None,
        pricebook_name="",
        available_books=result["available_books"],
        basis_binding=result["basis_binding"],
        basis_refusal=result["refusal"],
        basis_candidates=result["matching_books"],
        basis_contradictions=(
            ["регион: " + ", ".join(result["contradicting_regions"])]
            if result["contradicting_regions"]
            else []
        ),
    )
    assert summary["match"] == "no_book"
    assert summary["refusal"] == "contradiction"
    assert summary["contradictions"] == ["регион: Москва, Санкт-Петербург"]
    assert "разную ценовую базу" in summary["note"]
    assert "регион: Москва, Санкт-Петербург" in summary["note"]
    assert "молча выбирать одно из двух" in summary["note"]
    # the installed catalogue is neither announced as missing nor hidden
    assert "не найдена" not in summary["note"]
    assert "не задана явно" not in summary["note"]
    assert "moskva_3kv2026" in summary["note"]
    assert summary["available_books"] == CATALOG


def test_a_half_named_basis_names_the_books_it_is_missing_a_period_for():
    """The other live 823 sentence, from cell ``B4_eom_pdf``.

    The task said «ценовую базу я не назвал», the document names Санкт-Петербург
    and no quarter. The adapter answered «Запрошенная ценовая база
    „Санкт-Петербург" локально не найдена» while two Saint-Petersburg books are
    installed — what is missing is the period, and the operator has to be told
    exactly that, with the books that already fit (ADR-16 § 7).
    """

    result = _choice(
        question_text="Собери ЛСР по прикреплённому документу, цены не подставляй молча",
        source_text="Ориентир стоимости работ\nОбъект: г. Санкт-Петербург, ул. Парковая",
        source_name="eom.pdf",
    )
    assert result["pricebook"] == ""
    assert result["refusal"] == "unnamed_period"
    assert result["requested_region"] == "Санкт-Петербург"
    assert result["requested_region_origin"] == "выведено из: исходник"
    assert result["matching_books"] == ["sankt-peterburg_2kv2026", "sankt-peterburg_3kv2026"]

    summary = summarize_lsr_price_basis(
        question_text="Собери ЛСР по прикреплённому документу, цены не подставляй молча",
        pricebook=None,
        requested_region=result["requested_region"],
        requested_region_origin=result["requested_region_origin"],
        available_books=result["available_books"],
        basis_binding=result["basis_binding"],
        basis_refusal=result["refusal"],
        basis_candidates=result["matching_books"],
    )
    note = summary["note"]
    assert summary["match"] == "no_book"
    assert summary["refusal"] == "unnamed_period"
    assert "период (квартал и год) — нет" in note
    assert "sankt-peterburg_2kv2026" in note and "sankt-peterburg_3kv2026" in note
    assert "не найдена" not in note
    # the source of the subject is stated, not implied (the task named no base)
    assert summary["requested_region_origin"] == "выведено из: исходник"


def test_a_period_that_really_is_absent_is_still_called_absent():
    """The negative control: the honest refusal must not swallow the real gap.

    A named subject and period that no installed book covers is a *missing*
    basis, and the note has to keep saying so — otherwise the fix would replace
    one blanket statement with another.
    """

    result = _choice(question_text="Собери ЛСР по Москве, цены IV квартала 2026")
    assert result["pricebook"] == ""
    assert result["contradicting_regions"] == []
    assert result["contradicting_quarters"] == []
    assert result["refusal"] == "no_matching_book"
    assert result["matching_books"] == []
    summary = summarize_lsr_price_basis(
        question_text="Собери ЛСР по Москве, цены IV квартала 2026",
        pricebook=None,
        available_books=result["available_books"],
        basis_binding=result["basis_binding"],
        basis_refusal=result["refusal"],
        basis_candidates=result["matching_books"],
        basis_contradictions=[],
    )
    assert summary["contradictions"] == []
    assert "локально не найдена" in summary["note"]
    assert "Доступные книги" in summary["note"]


@pytest.mark.asyncio
async def test_the_adapter_carries_its_own_refusal_into_the_operator_note(
    tmp_path, monkeypatch
):
    """The seam the 822 summary could not see.

    ``explicit_estimate_pricebook`` reads the whole source text, while
    ``summarize_lsr_price_basis`` receives only the fields the adapter passes on
    — so the derivation was right and the delivered answer was wrong in the same
    call. This proves the value crosses that seam rather than being recomputed.
    """

    captured = _stub_the_calculator(monkeypatch, tmp_path)
    built = await build_lsr_workbook_from_decisions(
        tmp_path / "bap.pdf",
        {
            "decisions": [
                {
                    "source_row": "ВОР!R4",
                    "title": "Прокладка кабеля NYM 3x2.5 в траншее",
                    "unit": "м",
                    "quantity": 120,
                    "norm_code": "ТЕРр08-02-118-01",
                }
            ],
            "question": CONTRADICTED_TASK,
            "_source_text": CONTRADICTED_SOURCE,
        },
        tmp_path / "lsr.xlsx",
        lambda *_a: None,
    )
    assert built["pricebook"] == ""
    assert captured["pricebook"] is None
    basis = built["price_basis"]
    assert basis["match"] == "no_book"
    assert basis["refusal"] == "contradiction"
    assert basis["contradictions"] == ["регион: Москва, Санкт-Петербург"]
    assert "разную ценовую базу" in basis["note"]
    assert "не найдена" not in basis["note"]
    # the same sentence is what the delivered file prints on its header (§ 10)
    assert captured["meta"]["price_basis_note"] == basis["note"]
    assert "не найдена" not in captured["meta"]["price_basis_note"]

    half_named = await build_lsr_workbook_from_decisions(
        tmp_path / "eom.pdf",
        {
            "decisions": [
                {
                    "source_row": "БОР!R7",
                    "title": "Устройство стяжки цементно-песчаной",
                    "unit": "м2",
                    "quantity": 240,
                    "norm_code": "ТЕРр11-01-013-02",
                }
            ],
            "question": "Собери ЛСР по прикреплённому документу, цены не подставляй молча",
            "_source_text": (
                "Ориентир стоимости работ\n"
                "Объект: г. Санкт-Петербург, ул. Парковая, д. 12"
            ),
        },
        tmp_path / "lsr-2.xlsx",
        lambda *_a: None,
    )
    second = half_named["price_basis"]
    assert second["match"] == "no_book"
    assert second["refusal"] == "unnamed_period"
    assert second["matching_books"] == ["sankt-peterburg_2kv2026", "sankt-peterburg_3kv2026"]
    assert "период (квартал и год) — нет" in second["note"]
    assert "не найдена" not in second["note"]
    assert second["requested_region_origin"] == "выведено из: исходник"
