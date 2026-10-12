"""Canonical SQLite identity must survive calculation and the actual XLSX adapter."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import openpyxl
import pandas as pd
import pytest

from proxy.services import gesn_service as gs, fgis_price_service
from proxy.services.lsr_workbook_adapter_service import build_lsr_workbook_from_decisions
from proxy.services.rim_lsr_trace_service import build_lsr_trace_from_visible_rows
from proxy.smeta_core.norm_browser import _cards_by_norm_keys
from tools.build_smeta_structured_base import build_structured_base
from tools.gesn_import import RESOURCE_FIELDS


@pytest.fixture(params=["fixture-edition-A", "fixture-edition-B"])
def canonical(tmp_path, monkeypatch, request):
    records = []
    for family, quantity in [("ГЭСНм", 0.22), ("ГЭСН", 7)]:
        for kind, code, name, unit, amount in [
            ("labor", "1-100-38", "Средний разряд работы 3,8", "чел.-ч", quantity),
            ("material", "5-1", "Масса", "т", 0.24),
        ]:
            row = dict.fromkeys(RESOURCE_FIELDS)
            row.update(norm_code=f"{family}11-04-028-01", base_type=family,
                       norm_key=f"{family}:11-04-028-01", norm_name=f"{family}: нормативная операция",
                       norm_unit="шт", work_steps=json.dumps(["Нормативный состав"], ensure_ascii=False),
                       kind=kind, resource_code=code, resource_name=name, resource_unit=unit,
                       per_unit=amount, source_doc="synthetic normative fixture", source_guid="fixture-guid")
            records.append(row)
    source = tmp_path / "source.parquet"
    pd.DataFrame(records, columns=list(RESOURCE_FIELDS)).to_parquet(source, index=False)
    base = tmp_path / "canonical.sqlite"
    build_structured_base(source=source, out=base, manifest_out=tmp_path / "manifest.json", edition=request.param)
    monkeypatch.setenv("LES_SMETA_STRUCTURED_BASE", str(base))
    for loader in (gs.load_base_norms, gs.load_structured_base_norms, gs.load_norms):
        loader.cache_clear()
    yield base, request.param
    for loader in (gs.load_base_norms, gs.load_structured_base_norms, gs.load_norms):
        loader.cache_clear()


def test_seed_cannot_replace_canonical_name_unit_or_resources(canonical):
    base, edition = canonical
    code = "ГЭСНм11-04-028-01"
    card = _cards_by_norm_keys(["ГЭСНм:11-04-028-01"], base_path=base)[0]
    norm = gs.get_norm(code)
    assert norm["name"] == card["title"]
    assert norm["unit"] == card["measure_unit"]
    assert norm["norm_id"] == card["norm_id"] == f"{edition}|ГЭСНм|11-04-028-01"
    assert norm["edition"] == edition
    assert {r["code"] for r in norm["resources"]} == {"1-100-38", "5-1"}
    assert next(r for r in norm["resources"] if r["kind"] == "labor")["per_unit"] == 0.22
    assert "nr_pct" not in norm  # A demo percentage cannot override the canonical rule lookup either.
    assert gs.get_norm("11-04-028-01", strict_family=True) is None
    assert gs.get_norm("ГЭСН11-04-028-01")["name"] != norm["name"]
    assert gs.get_norm("ГЭСНм11-04-027-01") is None  # Missing in this edition, present only in demo seed.


def test_canonical_identity_and_unknown_price_survive_adapter_xlsx(canonical, tmp_path, monkeypatch):
    base, edition = canonical
    book = fgis_price_service.PriceBook([
        {"code": "1-100-38", "name": "Произвольное поясняющее имя цены", "unit": "чел.-ч", "price_current": 123},
    ], region="fixture region", quarter="fixture period")
    monkeypatch.setattr(fgis_price_service, "resolve_pricebook_path", lambda *_: "fixture.parquet")
    monkeypatch.setattr(fgis_price_service, "get_pricebook", lambda *_: book)
    decision = {"source_row": "Лист!17", "norm_code": "ГЭСНм11-04-028-01",
                "title": "Выбранная моделью операция", "quantity": 2, "unit": "шт"}
    trace = build_lsr_trace_from_visible_rows([decision], pricebook=book)
    work = next(row for row in trace["sections"][0]["positions"][0]["rows"] if row["type"] == "work")
    assert work["meta"]["normative_source"]["norm_id"] == f"{edition}|ГЭСНм|11-04-028-01"
    target = tmp_path / "identity.xlsx"
    result = asyncio.run(build_lsr_workbook_from_decisions(Path("."), {"decisions": [decision]}, target, lambda *_: None))
    assert result["bound_rows"] == 1
    sheet = openpyxl.load_workbook(target, data_only=False).worksheets[0]
    row = next(r for r in sheet if r[1].value == decision["norm_code"])
    assert "ГЭСНм: нормативная операция" in row[2].value
    assert "Выбранная моделью операция" in row[2].value
    assert row[3].value == "шт" and row[4].value == 2
    assert f"{edition}|ГЭСНм|11-04-028-01" in row[1].comment.text
    assert "Лист!17" in row[1].comment.text
    labor = next(r for r in sheet if r[1].value == "1-100-38")
    assert labor[2].value == "Средний разряд работы 3,8"
    assert labor[4].value == 0.22
    assert labor[9].value == 123
    mass = next(r for r in sheet if r[1].value == "5-1")
    assert mass[2].value == "Масса" and mass[3].value == "т"
    assert mass[9].value is None and mass[11].value is None
