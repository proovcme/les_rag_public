"""§ 3 / § 10: the ОЗП tariff шифр is an import fact with a stated origin, never a calc trick.

The first attempt at this rule derived ``1-100-NM`` from the card's «Средний разряд работы N,M»
*while pricing*, in both LSR engines.  That was a compensation for the demo seed (whose cards
named a разряд and no шифр) and it is what the release must not ship: the numbers of a
document then came partly from a code the source document never wrote, and the two engines
could disagree about which tariff row a разряд designated.  With the seed out of production
(`tests/test_gesn_seed_is_test_only_830.py`) the general rule has no reason to exist, and the
measured need for it is zero on the installed canonical base — 0 of its 5 307 codeless labour
rows name a разряд at all; they are aggregates («ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО: В ТОМ ЧИСЛЕ:»)
and stay the concrete hole they are (`stage_b/live_830/seed_vs_base_reconcile_830.json`).

What is allowed, and what this file pins:

1. a genuinely codeless row of an OFFICIAL IMPORT gets its tariff шифр where the import is
   read — the parquet/SQLite readers and the ФГИС ingest — and the row carries
   ``code_derivation`` naming that inference as the reader's, not the card's;
2. the calculators only REPORT that provenance (`labor_code_provenance`), they never invent a
   шифр while pricing, and they say the same thing on both routes (§ 10);
3. the шифр is only a question asked of the chosen ценовая книга: no book, no money;
4. a row whose name states no fractional разряд keeps «нужна ставка ОЗП» — a data question for
   the operator, not something the code answers;
5. the delivered file names the origin of such a шифр next to the price it explains.
"""

from __future__ import annotations

import copy
import inspect

import pandas as pd

from proxy.services import gesn_fgis_service as gfgis
from proxy.services import gesn_service as gs
from proxy.services import lsr_assembly_service, rim_lsr_trace_service
from proxy.services.fgis_price_service import PriceBook
from proxy.services.lsr_assembly_service import compute_position
from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace_from_visible_rows,
    build_position_trace,
)
from proxy.services.rim_trace_xlsx_service import render_lsr_xlsx
from tools.gesn_import import RESOURCE_FIELDS

IMPORT_CODE = "ГЭСН09-01-001-01"      # imported card, labour named by разряд only
AGGREGATE_CODE = "ГЭСН09-01-002-01"   # imported card, aggregate labour with no разряд
OWN_CODE = "ГЭСН09-01-003-01"         # imported card that states its own шифр
ETALON = "ГЭСН12-01-034-02"
TARIFF_40 = "1-100-40"
TARIFF_25 = "1-100-25"
BOOK_RATE_40 = 620.0                  # this test's own book row
DERIVATION = gfgis.LABOR_CODE_DERIVATION
AGGREGATE_NAME = "ЗАТРАТЫ ТРУДА РАБОЧИХ, ВСЕГО: В ТОМ ЧИСЛЕ:"
DERIVED_NOTE = "тарифный шифр выведен из среднего разряда карточки нормы"

_read_base = gs.load_base_norms       # the reader before any monkeypatching


def _card(code: str, labor_name: str, *, resource_code: str = "", per_unit: float = 10.0) -> dict:
    return {
        "norm_code": code,
        "norm_name": f"Импортированная карточка {code}",
        "norm_unit": "100 м2",
        "work_steps": "",
        "kind": "labor",
        "per_unit": per_unit,
        "resource_code": resource_code,
        "resource_name": labor_name,
        "resource_unit": "чел.-ч",
        "price": None,
        "base_type": "ГЭСН",
        "norm_key": code.replace("ГЭСН", "ГЭСН:"),
        "source_doc": "test",
        "source_guid": "",
    }


def _imported_base(tmp_path) -> str:
    """Three official-import cards, on the reader's own parquet contract."""

    path = tmp_path / "imported_base.parquet"
    pd.DataFrame(
        [
            _card(IMPORT_CODE, "Средний разряд работы 4,0"),
            _card(AGGREGATE_CODE, AGGREGATE_NAME, per_unit=13.7),
            _card(OWN_CODE, "Средний разряд работы 2.5", resource_code=TARIFF_25),
        ],
        columns=list(RESOURCE_FIELDS),
    ).to_parquet(path, index=False)
    return str(path)


def _book(rows: list[dict] | None = None) -> PriceBook:
    return PriceBook(
        rows if rows is not None else [
            {"code": TARIFF_40, "name": "Средний разряд работы 4,0", "unit": "чел.-ч",
             "price_base": BOOK_RATE_40 - 20.0, "price_current": None,
             "price_current_eff": BOOK_RATE_40},
            {"code": TARIFF_25, "name": "Средний разряд работы 2,5", "unit": "чел.-ч",
             "price_base": 507.56, "price_current": 507.56, "price_current_eff": 507.56},
        ],
        region="Санкт-Петербург",
        quarter="3 квартал 2026 г.",
    )


def _derived_labor_line(**overrides) -> dict:
    """An ОЗП line as an import reader hands it to a calculator: шифр plus its origin."""

    line = {
        "kind": "labor",
        "code": TARIFF_40,
        "name": "Средний разряд работы 4,0",
        "unit": "чел.-ч",
        "per_unit": 10.0,
        "qty": 10.0,
        "code_derivation": DERIVATION,
    }
    line.update(overrides)
    return line


def _labor_entry(trace, kind="labor"):
    entries = [
        item for item in trace["summary"]["resource_decisions"] if item.get("kind") == kind
    ]
    assert len(entries) == 1, trace["summary"]["resource_decisions"]
    return entries[0]


def _flat_cells(path) -> str:
    import openpyxl

    workbook = openpyxl.load_workbook(path)
    return "\n".join(
        str(cell.value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if cell.value not in (None, "")
    )


def _imported_world(monkeypatch, base_path: str) -> None:
    """The three imported cards are the whole norm view, so the engines read what we wrote."""

    monkeypatch.setattr(gs, "load_base_norms", lambda *_a, **_k: _read_base(base_path))
    monkeypatch.setattr(gs, "load_overlay_norms", lambda *_a, **_k: {})
    monkeypatch.delenv(gs.SEED_ENV_VAR, raising=False)


# ── 1. the rule, at the layer that owns it ────────────────────────────────────

def test_the_import_reader_derives_the_cipher_and_marks_its_origin(tmp_path):
    """A codeless ОЗП row of an official import gets the tariff row its разряд names.

    The шифр is written where the import is read, and the row states that the reader —
    not the card — worked it out.  No money is touched here.
    """

    base_path = _imported_base(tmp_path)
    norm = gs.get_norm(IMPORT_CODE, base_path=base_path)
    labor = next(res for res in norm["resources"] if res.get("kind") == "labor")

    assert labor["code"] == TARIFF_40
    assert labor["code_derivation"] == DERIVATION
    assert "price" not in labor          # the reader supplies a question, not an amount

    line = next(item for item in gs.expand_position(IMPORT_CODE, 2.0, base_path=base_path)
                if item["kind"] == "labor")
    assert line["code"] == TARIFF_40
    assert line["code_derivation"] == DERIVATION   # the origin survives the expansion
    assert line["qty"] == 20.0


def test_a_row_that_states_no_fractional_razryad_gets_no_cipher(tmp_path):
    """The other half of § 3: no разряд, nothing to derive — the aggregate stays a hole.

    Measured: every one of the 5 307 codeless labour rows of the installed canonical base is
    of this form, so this is the ordinary case, not an edge case.
    """

    labor = next(res for res in gs.get_norm(AGGREGATE_CODE, base_path=_imported_base(tmp_path))
                 ["resources"] if res.get("kind") == "labor")

    assert labor.get("code") in (None, "")
    assert "code_derivation" not in labor


def test_a_row_that_already_states_its_cipher_is_left_alone(tmp_path):
    norm = gs.get_norm(OWN_CODE, base_path=_imported_base(tmp_path))
    labor = next(res for res in norm["resources"] if res.get("kind") == "labor")

    assert labor["code"] == TARIFF_25
    assert "code_derivation" not in labor             # nothing was inferred over the card


def test_the_razryad_rule_lives_in_exactly_one_module():
    """§ 10: one meaning, one implementation — a second regular expression would drift."""

    sources = {
        module.__name__: inspect.getsource(module)
        for module in (gfgis, gs, lsr_assembly_service, rim_lsr_trace_service)
    }

    assert [name for name, src in sources.items() if r"разряд\D*" in src] == [gfgis.__name__]
    assert gfgis.labor_tariff_code("ОТ(ЗТ) средний разряд 2,5") == TARIFF_25   # the demo form
    assert gfgis.labor_tariff_code("Средний разряд работы 4,0") == TARIFF_40
    assert gfgis.labor_tariff_code("Средний разряд работы 2.5") == TARIFF_25   # base uses a dot
    assert gfgis.labor_tariff_code("ОТ(ЗТ) средний разряд работы") == ""       # no fraction
    assert gfgis.labor_tariff_code(AGGREGATE_NAME) == ""
    assert gfgis.labor_tariff_code(None) == ""
    # the readers delegate to that one implementation instead of restating it
    assert gs._labor_tariff_code("Средний разряд работы 4,0") == TARIFF_40


# ── 2. the calculators report; they do not repair ─────────────────────────────

def test_no_calculator_derives_a_cipher_while_it_prices():
    """The rejected half of the earlier fix, pinned so it cannot come back."""

    assert not hasattr(gfgis, "enrich_labor_tariff_codes")
    for name in ("proxy.services.lsr_assembly_service", "proxy.services.rim_lsr_trace_service"):
        src = inspect.getsource(__import__(name, fromlist=["*"]))
        assert "labor_tariff_code(" not in src, name        # no шифр invented at price time
        assert "_derive_labor_code(" not in src, name
        assert "labor_code_provenance(" in src, name        # only the origin is reported


def test_the_provenance_report_is_read_only():
    resources = [_derived_labor_line(), {"kind": "material", "code": "01.7.15.06-0111",
                                         "name": "Гвозди строительные", "unit": "т",
                                         "per_unit": 0.0015}]
    before = copy.deepcopy(resources)

    trace = gfgis.labor_code_provenance(resources)

    assert resources == before                       # nothing was written into the row
    assert trace == {"schema": "labor_code_provenance_v1", "status": "derived_from_import",
                     "derived": 1, "codes": [TARIFF_40], "note": DERIVATION}
    assert gfgis.labor_code_provenance([{"kind": "labor", "code": TARIFF_25,
                                         "name": "Средний разряд работы 2,5"}])["status"] == "not_needed"
    assert gfgis.labor_code_provenance([])["status"] == "not_needed"
    # a шифр without a stated origin is the card's own, and needs no note
    assert gfgis.labor_code_provenance([_derived_labor_line(code_derivation="")])["codes"] == []


def test_both_engines_report_the_same_origin_for_the_same_card(monkeypatch, tmp_path):
    """§ 10: one document, one statement about where a шифр came from."""

    _imported_world(monkeypatch, _imported_base(tmp_path))
    book = _book()
    rim = build_position_trace({"code": IMPORT_CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0},
                               pricebook=book)
    assembly = compute_position({"code": IMPORT_CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0},
                                pricebook=book)

    expected = {"schema": "labor_code_provenance_v1", "status": "derived_from_import",
                "derived": 1, "codes": [TARIFF_40], "note": DERIVATION}
    assert rim["summary"]["labor_code_trace"] == expected
    assert assembly["labor_code_trace"] == expected
    assert _labor_entry(rim)["code_derivation"] == DERIVATION
    priced = next(row for row in assembly["resources"] if row["kind"] == "labor")
    assert priced["code_derivation"] == DERIVATION


# ── 3. the шифр is a question, the book is the answer ─────────────────────────

def test_a_derived_cipher_is_priced_by_the_chosen_book_and_by_nothing_else(monkeypatch, tmp_path):
    _imported_world(monkeypatch, _imported_base(tmp_path))
    rim = build_position_trace({"code": IMPORT_CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0},
                               pricebook=_book())
    summary = rim["summary"]
    decision = _labor_entry(rim)

    assert decision["code"] == TARIFF_40
    assert decision["price"] == BOOK_RATE_40
    assert decision["cost"] == round(10.0 * BOOK_RATE_40, 2)
    assert decision["price_gap_kind"] == ""
    assert decision["code_derivation"] == DERIVATION    # the origin travels with the price
    assert summary["ozp"] == round(10.0 * BOOK_RATE_40, 2)
    assert summary["card_priced_resources"] == []       # no unowned money anywhere
    assert summary["amount_status"] == "complete"
    assert summary["full_amount"] == summary["total"]
    assert not any("карточк" in str(flag) for flag in summary["flags"]), summary["flags"]


def test_without_the_chosen_book_a_derived_cipher_prices_nothing(monkeypatch, tmp_path):
    """No base, no question asked: the amount is not the code's business (§ 7)."""

    _imported_world(monkeypatch, _imported_base(tmp_path))
    empty = PriceBook([], region="Санкт-Петербург", quarter="3 квартал 2026 г.")
    rim = build_position_trace({"code": IMPORT_CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0},
                               pricebook=empty)
    assembly = compute_position({"code": IMPORT_CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0},
                                pricebook=empty)

    assert _labor_entry(rim)["price"] in (None, 0)
    assert f"price_missing:{TARIFF_40}" in rim["summary"]["completeness_reasons"]
    assert rim["summary"]["ozp"] == 0.0 and rim["summary"]["total"] == 0.0
    assert rim["summary"]["amount_status"] == "partial"
    assert rim["summary"]["full_amount"] is None
    assert assembly["base"]["ozp"] == 0.0 and assembly["total"] == 0.0
    # the book being asked is recorded; nothing about the row was rewritten
    assert rim["summary"]["labor_code_trace"]["status"] == "derived_from_import"


def test_an_aggregate_labour_line_stays_an_operator_question(monkeypatch, tmp_path):
    """The negative case of the whole rule: the code does not raise a verdict by itself."""

    _imported_world(monkeypatch, _imported_base(tmp_path))
    book = _book()
    rim = build_position_trace({"code": AGGREGATE_CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0},
                               pricebook=book)
    assembly = compute_position({"code": AGGREGATE_CODE, "qty": 1.0, "nr_pct": 0, "sp_pct": 0},
                                pricebook=book)
    summary = rim["summary"]

    assert summary["labor_code_trace"]["status"] == "not_needed"
    assert summary["labor_code_trace"]["codes"] == []
    assert _labor_entry(rim)["code"] in (None, "")
    assert f"price_missing:{AGGREGATE_NAME}" in summary["completeness_reasons"]
    assert any("нужна ставка ОЗП" in str(flag) for flag in summary["flags"]), summary["flags"]
    assert summary["amount_status"] == "partial" and summary["full_amount"] is None
    assert any("нужна ставка ОЗП" in str(flag) for flag in assembly["flags"]), assembly["flags"]


# ── 4. the shipped base needs no inference, and the file says what it prints ──

def test_the_shipped_base_card_needs_no_derivation_at_all():
    """The production reality: the verified base states its own tariff шифр.

    If this ever starts reporting ``derived_from_import`` for the etalon, the base was
    rebuilt from a source that lost the шифр — worth knowing before anyone prices with it.
    """

    labor = next(res for res in gs.get_norm(ETALON)["resources"] if res.get("kind") == "labor")
    rim = build_position_trace({"code": ETALON, "qty": 0.61, "nr_pct": 0, "sp_pct": 0},
                               pricebook=_book())

    assert labor["code"] == TARIFF_25
    assert "code_derivation" not in labor
    assert rim["summary"]["labor_code_trace"] == {
        "schema": "labor_code_provenance_v1", "status": "not_needed",
        "derived": 0, "codes": [], "note": ""}
    assert _labor_entry(rim)["code_derivation"] == ""


def test_the_delivered_file_prints_where_a_derived_cipher_came_from(monkeypatch, tmp_path):
    """§ 3: the sheet must not present an inferred шифр as the card's own.

    The route is the real one — a ВОР row bound to an imported card whose ОЗП line named
    only a разряд — so the note in the file is the note a customer would read.
    """

    _imported_world(monkeypatch, _imported_base(tmp_path))
    lsr = build_lsr_trace_from_visible_rows(
        [{
            "source_row": "ВОР!R3",
            "row_role": "work",
            "basis": "ГЭСН 09-01-001-01",
            "title": "Сварная конструкция",
            "quantity": "1",
            "unit": "100 м2",
            "norm_status": "EXACT",
        }],
        pricebook=_book(),
    )
    path = tmp_path / "lsr_labor.xlsx"
    render_lsr_xlsx(lsr, path)
    flat = _flat_cells(path)

    assert TARIFF_40 in flat
    assert DERIVED_NOTE in flat
    assert str(BOOK_RATE_40) in flat or "620" in flat   # the book's amount is what priced it


