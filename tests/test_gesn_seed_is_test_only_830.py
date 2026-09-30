"""Release proof «в обоих production-путях нет демо-данных» (§ 3, сборка 830).

The measured root cause is in `stage_b/live_830/seed_vs_base_reconcile_830.md`: all ten
cards of `config/domain/gesn_seed.yaml` already exist in the verified base, and the seed
merged last, so it overrode them — the labour consumption of ГЭСНр62-01-001-01 differed by
a factor of five (2,8 against 13,7 чел.-ч), the tariff шифр the demo разряд implied matched
the base's own шифр for exactly one card out of ten, ГЭСНр67-01-001-01 said «шт.» where the
base says «100 м», and the НР/СП the demo cards wrote had no normative owner at all.  Every
«gold» amount the previous build pinned (11 813.04, 11 998.07) was a demo artifact.

The ruling this file enforces, in full: in production the norm-card source is the main
verified base; the seed takes part in neither search nor calculation, including for norms the
base does not carry; it stays reachable only for an explicitly enabled test scenario; a card
the base does not have is shown as a concrete gap and is never replaced by a demo card.
Four things are pinned, in that order:

1. what the calculator and the catalog read by default — the base, with no demo card
   anywhere in the merged view;
2. that neither production projection (the norm store feeding candidate search, and the ГЭСН
   notebook the model reads) admits a seed row until a scenario names one;
3. that a norm missing from the base produces a named gap and no money, not a substitute;
4. that when a scenario DOES opt in, both engines say out loud that the position rests on a
   demo card and is not base-backed money — the opt-in may read the seed, never disguise it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from proxy.services import gesn_service as gs
from proxy.services.fgis_price_service import PriceBook
from proxy.services.lsr_assembly_service import compute_position
from proxy.services.rim_lsr_trace_service import (
    build_lsr_trace,
    build_position_trace,
)
from proxy.services.smeta_norm_store import _build_rows
from tools.gesn_import import RESOURCE_FIELDS

CODE = "ГЭСН12-01-034-02"
CARD_KEY = "ГЭСН:12-01-034-02"
SEED_ENV = gs.SEED_ENV_VAR
MISSING = "ГЭСН99-99-999-01"
DEMO_LABOR_RATE = 475.11          # the number the demo card writes for ОЗП
DEMO_TITLE = "Устройство обрешётки с прозорами из брусков"   # with «ё»; the base has none
BASE_TITLE = "Устройство обрешетки из основной базы"          # this scenario's own base card

# The reader before monkeypatching, captured while the module attribute is still itself:
# ``lru_cache``'s C implementation exposes no ``__wrapped__``.
_read_base = gs.load_base_norms


def _resource(**overrides) -> dict[str, object]:
    row = {
        "norm_code": CODE,
        "norm_name": "Устройство обрешетки с прозорами из брусков",
        "norm_unit": "100 м2",
        "work_steps": "",
        "kind": "labor",
        "per_unit": 12.94,
        "resource_code": "1-100-25",
        "resource_name": "Средний разряд работы 2.5",
        "resource_unit": "чел.-ч",
        "price": None,
        "base_type": "ГЭСН",
        "norm_key": CARD_KEY,
        "source_doc": "test",
        "source_guid": "",
    }
    row.update(overrides)
    return row


def _write_base(tmp_path: Path, rows: list[dict[str, object]]) -> str:
    """A mini norm base on the reader's own contract, so the test owns its numbers."""

    path = tmp_path / "base.parquet"
    pd.DataFrame(rows, columns=list(RESOURCE_FIELDS)).to_parquet(path, index=False)
    return str(path)


def _write_seed(tmp_path: Path, norms: list[dict[str, object]]) -> str:
    import yaml

    path = tmp_path / "seed.yaml"
    path.write_text(yaml.safe_dump({"norms": norms}, allow_unicode=True), encoding="utf-8")
    return str(path)


def _world(monkeypatch, base_path: str) -> None:
    """The mini base is the whole norm world: no installed overlay, and no shipped seed."""

    monkeypatch.setattr(gs, "load_base_norms", lambda *_a, **_k: _read_base(base_path))
    monkeypatch.setattr(gs, "load_overlay_norms", lambda *_a, **_k: {})


def _demo_scenario_world(monkeypatch, tmp_path) -> str:
    """Base carries one card; a demo file that DOES carry the missing one sits next to it.

    Returns the seed path — reaching it takes an explicit opt-in, which is the point.
    """

    base_path = _write_base(tmp_path, [_resource()])
    _world(monkeypatch, base_path)
    return _write_seed(tmp_path, [{
        "code": MISSING,
        "name": "DEMO substitution candidate",
        "unit": "1 м2",
        "nr_pct": 100,
        "sp_pct": 50,
        "resources": [{"kind": "labor", "name": "ОТ(ЗТ) средний разряд 2,5",
                       "unit": "чел.-ч", "per_unit": 1.0, "price": DEMO_LABOR_RATE}],
    }])


def _labor_decision(trace, *, expect_price):
    entries = [
        item for item in trace["summary"]["resource_decisions"] if item.get("kind") == "labor"
    ]
    assert len(entries) == 1, entries
    if expect_price:
        return entries[0]
    assert entries[0].get("price") in (None, "", 0), entries[0]
    return entries[0]


@pytest.fixture(autouse=True)
def _production_view_by_default():
    """No scenario opt-in, and the readers' caches cleared around every test."""

    import os

    def _clean() -> None:
        os.environ.pop(SEED_ENV, None)
        gs.load_norms.cache_clear()
        gs.load_base_norms.cache_clear()
        gs.load_overlay_norms.cache_clear()
        gs.load_structured_base_norms.cache_clear()

    _clean()
    yield
    _clean()


# ── 1. what the calculator reads by default ──────────────────────────────────

def test_the_demo_card_is_still_on_disk_and_still_would_override():
    """The premise of the whole fix: the seed is not harmless, so it must not be merged.

    If this ever stops being true there is nothing left to guard, and the tests below
    would be asserting an empty claim — so the danger is pinned first.
    """

    demo = gs.load_norms()[CARD_KEY]

    assert demo["_source_kind"] == gs.SEED_SOURCE_KIND
    assert demo["name"] == DEMO_TITLE
    assert demo["nr_pct"] == 109 and demo["sp_pct"] == 57     # accrual with no normative owner
    demo_labor = next(res for res in demo["resources"] if res.get("kind") == "labor")
    assert demo_labor["price"] == DEMO_LABOR_RATE
    assert not demo_labor.get("code")                          # a разряд, not a шифр
    assert len(demo["resources"]) == 8                         # and no бруски row at all


def test_the_calculator_reads_the_verified_base_card_not_the_demo_one():
    norm = gs.get_norm(CODE)

    assert norm["_source_kind"] == "structured_sqlite"
    assert norm["key"] == CARD_KEY
    labor = next(res for res in norm["resources"] if res.get("kind") == "labor")
    assert labor["code"] == "1-100-25"                # the base states its own tariff шифр
    assert "price" not in labor                       # the base carries no money to inherit
    assert len(norm["resources"]) == 7
    assert gs.get_norm(CODE, include_seed=False)["_source_kind"] == "structured_sqlite"


def test_no_card_in_the_default_merged_view_is_a_demo_card():
    """The whole production view, not one lookup: zero seed rows while no scenario opted in."""

    merged = gs._merged_norms()

    assert merged                                              # the base really loaded
    assert [key for key, norm in merged.items()
            if str(norm.get("_source_kind") or "") == gs.SEED_SOURCE_KIND] == []
    assert merged[CARD_KEY]["_source_kind"] == "structured_sqlite"
    # the catalog the router lists is built from the same merge
    assert [item for item in gs.list_norms() if item["code"] == CODE][0]["resources"] == 7


def test_an_explicit_test_scenario_can_still_reach_the_demo_card_and_is_marked():
    """The opt-in exists, so the guard is a label rather than a ban — and it stays labelled."""

    assert gs._merged_norms(include_seed=True)[CARD_KEY]["_source_kind"] == gs.SEED_SOURCE_KIND
    assert gs.get_norm(CODE, include_seed=True)["name"] == DEMO_TITLE


def test_the_environment_switch_is_the_only_default_way_in(monkeypatch):
    assert gs.seed_enabled() is False
    monkeypatch.setenv(SEED_ENV, "1")
    assert gs.seed_enabled() is True
    monkeypatch.setenv(SEED_ENV, "0")
    assert gs.seed_enabled() is False
    monkeypatch.setenv(SEED_ENV, "yes")
    assert gs.seed_enabled() is True


# ── 2. both production projections, on a base the test owns ──────────────────

def test_the_norm_search_projection_has_no_demo_row_until_a_scenario_names_one(tmp_path, monkeypatch):
    """`smeta_norm_store` is the candidate search the model picks norms from (§ 3: a demo
    card must not be a candidate for a real work)."""

    monkeypatch.setattr(gs, "load_base_norms", lambda *_a, **_k: {
        CARD_KEY: {
            "code": CODE, "key": CARD_KEY, "name": BASE_TITLE, "unit": "100 м2",
            "resources": [{"kind": "labor", "name": "Средний разряд работы 2.5",
                           "unit": "чел.-ч", "per_unit": 12.94, "code": "1-100-25"}],
        }
    })
    monkeypatch.setattr(gs, "load_overlay_norms", lambda *_a, **_k: {})
    base_path = _write_base(tmp_path, [_resource()])

    rows = _build_rows(base_path)
    by_code = {row.code: row for row in rows}

    # the projection keys a card by its norm key, the way the base stores it
    assert by_code[CARD_KEY].title == BASE_TITLE.lower()
    assert by_code[CARD_KEY].source_kind == "base_parquet"
    assert [row.code for row in rows if row.source_kind == gs.SEED_SOURCE_KIND] == []
    assert not any("gesn_seed.yaml" in row.provenance for row in rows)

    monkeypatch.setenv(SEED_ENV, "1")
    opted_in = {row.code: row for row in _build_rows(base_path)}

    # an opted-in scenario may read the seed, but never pass it off as a base card
    assert opted_in[CARD_KEY].source_kind == gs.SEED_SOURCE_KIND
    assert opted_in[CARD_KEY].provenance == "config/domain/gesn_seed.yaml"


def test_the_model_notebook_is_built_from_base_cards_only(monkeypatch):
    from proxy.services import notebook_service

    monkeypatch.setattr(gs, "load_base_norms", lambda *_a, **_k: {
        CARD_KEY: {
            "code": CODE, "name": BASE_TITLE, "unit": "100 м2",
            "resources": [{"kind": "labor", "name": "Средний разряд работы 2.5",
                           "unit": "чел.-ч", "per_unit": 12.94, "code": "1-100-25"}],
        }
    })
    notebook_service.build_gesn_notebook.cache_clear()
    try:
        titles = [
            str(example["name"])
            for collection in notebook_service.build_gesn_notebook()["collections"]
            for example in collection["examples"]
        ]

        assert BASE_TITLE in titles
        assert DEMO_TITLE not in titles

        monkeypatch.setenv(SEED_ENV, "1")
        notebook_service.build_gesn_notebook.cache_clear()
        opted_in = [
            str(example["name"])
            for collection in notebook_service.build_gesn_notebook()["collections"]
            for example in collection["examples"]
        ]
        assert DEMO_TITLE in opted_in
    finally:
        notebook_service.build_gesn_notebook.cache_clear()


def test_the_registry_says_whether_this_process_admits_the_seed():
    from proxy.services import service_source_registry as reg

    facts = reg._facts_for_source("gesn_base", [], {})

    assert facts["seed_in_production_view"] is False
    assert facts["seed_norms"] == len(gs.load_norms())     # the file is there either way
    assert facts["base_norms"] == len(_read_base(None))


# ── 3. a card the base does not carry is a gap, never a demo substitute ───────

def test_a_norm_absent_from_the_base_is_not_found_even_though_the_seed_has_it(monkeypatch, tmp_path):
    seed_path = _demo_scenario_world(monkeypatch, tmp_path)

    assert gs.get_norm(MISSING) is None
    assert gs.expand_position(MISSING, 1.0) is None
    # the seed would have answered, which is exactly what must not happen silently
    assert gs.get_norm(MISSING, path=seed_path)["name"] == "DEMO substitution candidate"


def test_both_engines_report_the_missing_card_as_a_named_gap_and_price_nothing(monkeypatch, tmp_path):
    _demo_scenario_world(monkeypatch, tmp_path)
    empty_book = PriceBook([], region="Санкт-Петербург", quarter="3 квартал 2026 г.")
    rim = build_position_trace({"code": MISSING, "qty": 1.0}, pricebook=empty_book)
    assembly = compute_position({"code": MISSING, "qty": 1.0}, pricebook=empty_book)
    summary = rim["summary"]

    # «norm_missing» plus the accrual question the absent card also leaves open (§ 3: the
    # gap is named, it is not smoothed over by a demo НР/СП)
    assert summary["completeness_reasons"] == ["norm_missing", "nr_sp_unresolved"], \
        summary["completeness_reasons"]
    assert any("норма ГЭСН не найдена в базе" in str(flag) for flag in summary["flags"])
    assert any("не подменяем" in str(flag) for flag in summary["flags"])
    assert MISSING in " ".join(str(flag) for flag in summary["flags"])
    assert summary["total"] == 0.0 and summary["full_amount"] is None
    assert summary["known_amount"] == 0.0
    assert summary["ozp"] == 0.0
    assert summary["amount_status"] == "partial"
    # the document the operator would be handed cannot read as finished
    doc = build_lsr_trace([{"code": MISSING, "qty": 1.0}], pricebook=empty_book)["summary"]
    assert doc["result_status"] == "priced_partial", doc["result_status"]
    assert doc["total"] == 0.0 and doc["known_amount"] == 0.0
    assert any("не подменяем" in str(flag) for flag in doc["flags"]), doc["flags"]
    # the demo rate never reaches either projection of the money
    assert all(not item.get("price") for item in summary["resource_decisions"])
    assert assembly["total"] == 0.0 and assembly["base"]["ozp"] == 0.0
    assert any("не найдена" in str(flag) and "не подменяем" in str(flag)
               for flag in assembly["flags"]), assembly["flags"]


# ── 4. an opted-in demo card is read, and named, by both engines ──────────────

def test_both_engines_say_a_demo_card_is_not_base_backed_money(monkeypatch, tmp_path):
    seed_path = _demo_scenario_world(monkeypatch, tmp_path)
    monkeypatch.setattr(gs, "DEFAULT_PATH", Path(seed_path))
    gs.load_norms.cache_clear()          # the reader caches by path; the scenario swapped the file
    monkeypatch.setenv(SEED_ENV, "1")
    # a book the demo row cannot be asked of: the labour line names a разряд, not a шифр
    empty_book = PriceBook([], region="Санкт-Петербург", quarter="3 квартал 2026 г.")

    rim = build_position_trace({"code": MISSING, "qty": 1.0}, pricebook=empty_book)
    assembly = compute_position({"code": MISSING, "qty": 1.0}, pricebook=empty_book)
    summary = rim["summary"]

    assert any("демо-семени" in str(flag) for flag in summary["flags"]), summary["flags"]
    assert "normative_source_demo_seed" in summary["completeness_reasons"]
    assert summary["norm_source_integrity"]["trusted_for_pricing"] is False
    assert summary["norm_source_integrity"]["source_kind"] == gs.SEED_SOURCE_KIND
    assert summary["amount_status"] == "partial"
    assert summary["full_amount"] is None
    doc = build_lsr_trace([{"code": MISSING, "qty": 1.0}], pricebook=empty_book)["summary"]
    assert doc["result_status"] == "priced_partial", doc["result_status"]
    assert any("демо-семени" in str(flag) for flag in doc["flags"]), doc["flags"]
    # the demo's own 475,11 is still unowned money, even in a demo scenario
    decision = _labor_decision(rim, expect_price=True)
    assert decision["price"] == DEMO_LABOR_RATE
    assert decision["price_gap_kind"] == "цена из карточки нормы, основания нет"
    assert any("card_price_without_basis" in str(reason) for reason in summary["completeness_reasons"])

    assert any("демо-семени" in str(flag) for flag in assembly["flags"]), assembly["flags"]
    assert assembly["norm_source_integrity"]["trusted_for_pricing"] is False
    priced = next(row for row in assembly["resources"] if row["kind"] == "labor")
    assert priced["price_used"] == DEMO_LABOR_RATE
    assert priced["price_source"] == "card_price"
    assert priced["price_action"] == "card_price_without_basis"
    assert assembly["base"]["ozp"] == round(DEMO_LABOR_RATE, 2)


def test_the_rejected_premise_cannot_come_back_through_a_default_call():
    """No public entry point may merge the seed without naming the scenario.

    The bug was structural: `get_norm` always merged the seed last, so any caller — a
    calculator, a router, a search — silently got demo money.  The keyword default is the
    guard, and this pins it against a future `include_seed=True` slipping back in.
    """

    import inspect

    for func in (gs.get_norm, gs.list_norms, gs.expand_position, gs._merged_norms):
        default = inspect.signature(func).parameters["include_seed"].default
        assert default is None, (func.__name__, default)
    assert "merged.update(load_norms(path))" in inspect.getsource(gs._merged_norms)
    assert "include_seed = path is not None or seed_enabled()" in inspect.getsource(gs._merged_norms)


def test_the_seed_override_that_broke_the_etalon_is_now_the_bases_number():
    """The concrete regression: ОЗП of ГЭСН12-01-034-02 is 12,94 чел.-ч per 100 м2, from the base.

    This card is the one demo и base agreed on, so the release must not lose its figure
    either — and it must carry the base's own шифр with no invented provenance.
    """

    labor = next(line for line in gs.expand_position(CODE, 1.0) if line["kind"] == "labor")

    assert labor["qty"] == pytest.approx(12.94)
    assert labor["code"] == "1-100-25"
    assert "price" not in labor                  # nothing priced until the chosen book is asked
    assert labor.get("code_derivation") is None  # the base states this шифр itself
    assert DEMO_LABOR_RATE != labor["qty"]
