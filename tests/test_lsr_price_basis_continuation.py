"""Task 2026-09-28 § 4 — a continuation of the same document keeps its price basis.

Live proof of the defect this file closes (build 820, installed app):
``stage_b/live_820/basis_continuation/basis_continuation.json`` — revision 1 of
«ВОР — Общая по Каменке» was priced in ``sankt-peterburg_3kv2026`` and said so in
the delivered file, while revisions 2..6, produced by ordinary «Продолжи это же
задание по тому же прикреплённому документу.» replies, printed «Ценовая база не
задана явно, поэтому книга не выбрана» and priced nothing.  The basis was derived
from the text of each turn again instead of being read back from the document.

These tests pin the fix at the four levels that each lost the basis on its own:

* the derivation — what may be inherited, and what may never be;
* the summary — how the inherited basis is stated to the operator;
* the adapter — the book the calculator receives and the header the file shows;
* the durable seam — the basis written when a revision is packaged and read back
  by the next turn, which is where the live continuation actually lost it.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from proxy.services import fgis_price_service
from proxy.services.chat_evidence_application_service import (
    document_price_basis_arguments,
    workbook_document_price_basis,
    workbook_packaging_args,
)
from proxy.services.lsr_workbook_adapter_service import (
    build_lsr_workbook_from_decisions,
    explicit_estimate_pricebook,
    summarize_lsr_price_basis,
)
from proxy.services.workbook_research_job_service import WorkbookResearchJobService

CATALOG = [
    "sankt-peterburg_2kv2026",
    "sankt-peterburg_3kv2026",
    "leningradskaya_oblast_3kv2026",
    "moskva_3kv2026",
]

#: what the durable packaging history stores for a revision priced in СПб III/2026
DOCUMENT_BASIS = {
    "pricebook": "sankt-peterburg_3kv2026",
    "region": "Город Санкт-Петербург",
    "quarter": "3 квартал 2026 г.",
    "binding": "Санкт-Петербург 3 квартал 2026 г.",
    "revision_id": "rev_1",
}


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


class _Book:
    region = "Город Санкт-Петербург"

    def __init__(self, quarter: str) -> None:
        self.quarter = quarter


def _book_for_path(path: str) -> _Book:
    stamp = re.search(r"([1-4])kv(20\d\d)", Path(str(path)).stem)
    quarter = f"{stamp.group(1)} квартал {stamp.group(2)} г." if stamp else ""
    return _Book(quarter)


def test_continuation_without_a_named_basis_keeps_the_documents_own_book():
    result = _choice(
        question_text="Добери нормы по остальным строкам",
        document_basis=DOCUMENT_BASIS,
    )
    assert result["pricebook"] == "sankt-peterburg_3kv2026"
    assert result["origin"] == "наследие документа (ревизия rev_1)"
    assert result["inherited_from_document"] == "rev_1"
    assert result["requested_region"] == "Санкт-Петербург"
    assert result["requested_quarter"] == "3:2026"


def test_a_basis_named_in_the_continuation_wins_over_the_document_record():
    moved = _choice(
        question_text="Пересчитай по Москве, цены III квартала 2026",
        document_basis=DOCUMENT_BASIS,
    )
    assert moved["pricebook"] == "moskva_3kv2026"
    assert moved["inherited_from_document"] == ""
    zone = _choice(
        question_text="Пересчитай по Ленинградской области, цены III квартала 2026",
        document_basis=DOCUMENT_BASIS,
    )
    assert zone["pricebook"] == "leningradskaya_oblast_3kv2026"
    assert zone["inherited_from_document"] == ""


def test_a_partially_named_continuation_inherits_only_what_it_leaves_unnamed():
    # The operator re-names the subject and says nothing about the period: the
    # period stays, the subject moves.
    period = _choice(
        question_text="Пересчитай по Санкт-Петербургу",
        document_basis=DOCUMENT_BASIS,
    )
    assert period["pricebook"] == "sankt-peterburg_3kv2026"
    assert period["origin"] == "наследие документа: период"
    # The reverse: only the period is re-named, so the subject is inherited and
    # the catalog is searched for that pair — here it lands on another book.
    subject = _choice(
        question_text="Возьми цены II квартала 2026",
        document_basis=DOCUMENT_BASIS,
    )
    assert subject["pricebook"] == "sankt-peterburg_2kv2026"
    assert subject["origin"] == "наследие документа: субъект"
    assert subject["inherited_from_document"] == "rev_1"


def test_a_document_book_that_is_no_longer_installed_is_never_substituted():
    stale = _choice(
        question_text="Добери нормы",
        document_basis={
            "pricebook": "sankt-peterburg_4kv2027",
            "region": "Город Санкт-Петербург",
            "quarter": "4 квартал 2027 г.",
            "binding": "Санкт-Петербург 4 квартал 2027 г.",
            "revision_id": "rev_old",
        },
    )
    assert stale["pricebook"] == ""
    assert stale["inherited_from_document"] == "rev_old"
    assert "не подменяют" in stale["document_basis_note"]
    assert "4 квартал 2027" in stale["document_basis_note"]


def test_an_unpriced_document_record_keeps_asking_the_same_question():
    # A revision that bound no book asked a question; the next pass must not read
    # that question back as though it had been answered (§ 7).
    result = _choice(
        question_text="Добери нормы",
        document_basis={"pricebook": "", "region": "", "quarter": "", "binding": ""},
    )
    assert result["pricebook"] == ""
    assert result["inherited_from_document"] == ""
    assert "не названы ни субъект, ни период" in result["reason"]


def test_no_document_record_behaves_exactly_as_before():
    untouched = _choice(question_text="Добери нормы по остальным строкам")
    assert untouched["pricebook"] == ""
    assert untouched["inherited_from_document"] == ""
    assert untouched["document_basis_note"] == ""


def test_inherited_basis_is_reported_as_continued_not_as_unasked():
    summary = summarize_lsr_price_basis(
        requested_book="sankt-peterburg_3kv2026",
        pricebook=_Book("3 квартал 2026 г."),
        pricebook_name="sankt-peterburg_3kv2026",
        requested_region="Санкт-Петербург",
        requested_region_origin="наследие документа",
        pricebook_origin="наследие документа (ревизия rev_1)",
        inherited_from_document="rev_1",
    )
    assert summary["match"] == "exact"
    assert summary["inherited_from_document"] == "rev_1"
    assert "не обнулена" in summary["note"]
    assert "наследие документа" in summary["note"]
    assert summary["requested_region_origin"] == "наследие документа"


def test_a_requested_basis_without_a_book_still_asks_and_lists_the_catalog():
    summary = summarize_lsr_price_basis(
        pricebook=None,
        available_books=CATALOG,
        document_basis_note=(
            "Унаследовано из уже посчитанного документа: субъект, период."
        ),
        inherited_from_document="rev_old",
    )
    assert summary["match"] == "no_book"
    assert summary["inherited_from_document"] == "rev_old"
    assert "Унаследовано из уже посчитанного документа" in summary["note"]
    assert "sankt-peterburg_2kv2026" in summary["note"]


@pytest.mark.asyncio
async def test_adapter_continuation_prices_the_same_book_and_says_so(tmp_path, monkeypatch):
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
    first = await build_lsr_workbook_from_decisions(
        tmp_path / "vor.xlsx",
        {
            "decisions": decisions,
            "question": "Собери ЛСР по Санкт-Петербургу, цены III квартала 2026",
            "_source_text": "Ведомость объёмов работ",
        },
        tmp_path / "lsr-1.xlsx",
        lambda *_a: None,
    )
    assert first["price_basis"]["match"] == "exact"
    carried = {
        "pricebook": first["price_basis"]["actual_book"],
        "region": first["price_basis"]["actual_region"],
        "quarter": first["price_basis"]["actual_quarter"],
        "binding": "Санкт-Петербург 3 квартал 2026 г.",
        "revision_id": "rev_1",
    }

    # the continuation turn of the same document carries no basis in its wording
    second = await build_lsr_workbook_from_decisions(
        tmp_path / "vor.xlsx",
        {
            "decisions": decisions,
            "question": "Продолжи это же задание по тому же прикреплённому документу.",
            "_source_text": "Ведомость объёмов работ",
            "document_price_basis": carried,
        },
        tmp_path / "lsr-2.xlsx",
        lambda *_a: None,
    )
    assert second["pricebook"] == "sankt-peterburg_3kv2026"
    assert second["price_basis"]["match"] == "exact"
    assert second["price_basis"]["inherited_from_document"] == "rev_1"
    # the calculator receives the III-quarter book, never None
    assert str(captured["pricebook"].quarter) == "3 квартал 2026 г."
    # and the header the operator opens still names that basis
    assert captured["meta"]["price_level"] == "3 квартал 2026 г."
    assert "не обнулена" in captured["meta"]["price_basis_note"]
    assert captured["meta"]["price_basis_match"] == "exact"


# --------------------------------------------------------------------------- #
# the durable seam: packaged revision -> stored basis -> next turn's args
# --------------------------------------------------------------------------- #
def _job_events(tmp_path):
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(
        service.identity(
            session_id="session-1",
            attachment_id="read_123456abcdef",
            source_sha256="a" * 64,
            dataset_ids=["smeta"],
            profile_revision_id="factory",
            model_identity="qwen-35b",
            question="Собери ЛСР по Санкт-Петербургу, цены III квартала 2026",
        )
    )
    service.record_packaging(
        job["job_id"],
        tool="build_lsr_workbook",
        revision_id="rev_1",
        draft=False,
        price_basis={
            "actual_book": "sankt-peterburg_3kv2026",
            "actual_region": "Город Санкт-Петербург",
            "actual_quarter": "3 квартал 2026 г.",
            "match": "exact",
        },
    )
    return service, job


def test_the_basis_written_at_packaging_is_the_basis_the_next_turn_reads(tmp_path):
    # The live defect lived between these two calls: the file was priced, and the
    # continuation turn still reported no basis.  One test across the real writer
    # and the real reader keeps the key names of both sides tied together.
    service, job = _job_events(tmp_path)
    carried = workbook_document_price_basis(
        service.list_events(job["job_id"]), tool="build_lsr_workbook"
    )
    assert carried == {
        "pricebook": "sankt-peterburg_3kv2026",
        "region": "Город Санкт-Петербург",
        "quarter": "3 квартал 2026 г.",
        # the label is rebuilt from the effective region+quarter, not copied from
        # an older turn's wording, so a stale label can never ride along
        "binding": "Город Санкт-Петербург 3 квартал 2026 г.",
        "revision_id": "rev_1",
    }

    args = workbook_packaging_args(
        packaging_tool="build_lsr_workbook",
        attachment_id="read_123456abcdef",
        question="Продолжи это же задание по тому же прикреплённому документу.",
        decisions=[{"source_row": "ВОР!R4", "title": "Монтаж", "unit": "м", "quantity": 1}],
        operator_overrides={},
        document_price_basis=carried,
    )
    assert args["document_price_basis"] == carried

    from proxy.services.structured_extract import validate as validate_json_schema
    from proxy.services.workbook_tool_service import (
        BUILD_LSR_WORKBOOK,
        BUILD_VOR_WORKBOOK,
    )

    assert validate_json_schema(args, BUILD_LSR_WORKBOOK.input_schema) == []
    # the ВОР packager has no such property: sending it fails its schema
    vor_args = workbook_packaging_args(
        packaging_tool="build_vor_workbook",
        attachment_id="read_123456abcdef",
        question="Продолжи это же задание по тому же прикреплённому документу.",
        decisions=[{"source_row": "ВОР!R4", "title": "Монтаж", "unit": "м", "quantity": 1}],
        operator_overrides={},
        document_price_basis=carried,
    )
    assert "document_price_basis" not in vor_args
    assert validate_json_schema(vor_args, BUILD_VOR_WORKBOOK.input_schema) == []


def test_a_revision_packaged_without_a_book_leaves_the_question_open(tmp_path):
    # An earlier draft that priced nothing asked the operator to choose; carrying
    # its empty record forward would answer that question by itself (§ 7).
    service = WorkbookResearchJobService(tmp_path / "meta.db")
    job = service.begin_or_resume(
        service.identity(
            session_id="session-1",
            attachment_id="read_123456abcdef",
            source_sha256="a" * 64,
            dataset_ids=["smeta"],
            profile_revision_id="factory",
            model_identity="qwen-35b",
            question="Собери ЛСР",
        )
    )
    service.record_packaging(
        job["job_id"],
        tool="build_lsr_workbook",
        revision_id="rev_draft",
        draft=True,
        price_basis={"actual_book": "", "match": "no_book"},
    )

    assert workbook_document_price_basis(service.list_events(job["job_id"])) == {}
    args = workbook_packaging_args(
        packaging_tool="build_lsr_workbook",
        attachment_id="read_123456abcdef",
        question="Добери нормы",
        decisions=[],
        operator_overrides={},
        document_price_basis={},
    )
    assert "document_price_basis" not in args


def test_events_written_before_the_basis_was_recorded_invent_nothing(tmp_path):
    # Backwards compatibility: existing jobs have packaging events with no basis
    # key at all.  They must read as "nothing recorded", never as a guessed book.
    legacy = [
        {
            "sequence": 1,
            "event_type": "workbook_packaged",
            "payload": {
                "tool": "build_lsr_workbook",
                "revision_id": "rev_old",
                "draft": False,
                "parent_revision_id": "",
            },
        }
    ]
    assert workbook_document_price_basis(legacy) == {}
    assert document_price_basis_arguments(None) == {}
    assert document_price_basis_arguments({"pricebook": "  "}) == {}
    assert document_price_basis_arguments({"actual_book": "moskva_3kv2026"}) == {
        "pricebook": "moskva_3kv2026",
        "region": "",
        "quarter": "",
        "binding": "",
        "revision_id": "",
    }
