"""Тест полного typed ФСЭМ «машина→машинист» и reconciliation ОТм."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from proxy.services import fsem_machinist_service as fsem


def test_full_catalog_loads_entries():
    m = fsem.machine_to_machinist()
    if not m:
        pytest.skip("FSEM runtime catalog is not installed on this clean clone")
    assert m["91.05.05-015"][0] == "4-100-060"
    assert m["91.05.05-015"][1] == "Машинисты, средний разряд 6"
    assert "91.14.02-002" in m  # 3-я запись
    if os.getenv("LES_SMETA_PUBLIC_FIXTURE"):
        assert len(m) >= 3
    else:
        assert len(m) >= 900


def test_lookup_and_list():
    if fsem.lookup("91.14.02-001") is None:
        pytest.skip("FSEM runtime catalog is not installed on this clean clone")
    assert fsem.lookup("91.14.02-001")["driver_code"] == "4-100-040"
    assert fsem.lookup("нет-такой-машины") is None
    entries = fsem.list_entries()
    assert any(e["machine_code"] == "91.05.05-015" for e in entries)


def test_missing_catalog_fails_closed_without_seed(tmp_path):
    m = fsem.machine_to_machinist(str(tmp_path / "absent.yaml"))
    assert m == {}
    assert fsem.list_entries(str(tmp_path / "absent.sqlite")) == []


def test_rim_trace_uses_seed_ot_without_runtime_fsem_pricebook():
    """Clean public clone: без ФСЭМ sqlite + без pricebook сохраняются явные ОТм семени."""
    from proxy.services import lsr_assembly_service as la
    from proxy.services import rim_lsr_trace_service as rim

    book = la._resolve_book(None)
    trace = rim.build_position_trace(
        {"code": "ГЭСН12-01-034-02", "qty": 0.61}, pricebook=book, k_ozp=1.0, k_em=1.0
    )
    assert trace["summary"]["total"] == 11813.04
    if book is None:
        assert trace["summary"]["fsem_trace"]["status"] == "not_applied_without_pricebook"
    else:
        assert trace["summary"]["fsem_trace"]["status"] in {"reconciled", "unresolved", "not_applicable"}


def test_enrich_machinists_splits_aggregate_with_local_catalog(tmp_path: Path):
    db = tmp_path / "fsem.sqlite"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE machines(
            machine_code TEXT PRIMARY KEY,
            machine_name TEXT NOT NULL,
            machine_price_base REAL,
            driver_wage_base REAL,
            driver_grade REAL,
            driver_code TEXT NOT NULL,
            crew_hours REAL NOT NULL,
            source_page INTEGER NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO machines VALUES(?,?,?,?,?,?,?,?)",
        [
            ("91.05.05-015", "Кран 16 т", None, None, 6.0, "4-100-060", 1.0, 1),
            ("91.14.02-002", "Авто до 8 т", None, None, 4.0, "4-100-040", 1.0, 1),
        ],
    )
    conn.commit()
    conn.close()
    fsem.lookup.cache_clear()

    resources = [
        {"kind": "machine", "name": "Кран 16 т", "code": "91.05.05-015", "qty": 9, "price": 100},
        {"kind": "machine", "name": "Авто до 8 т", "code": "91.14.02-002", "qty": 0.5, "price": 50},
        {"kind": "machinist", "name": "Затраты труда машинистов", "qty": 9.5},
    ]
    priced, trace = fsem.enrich_machinists(resources, quantity_field="qty", db_path=db)

    assert trace["status"] == "reconciled"
    assert {item.get("code") for item in priced if item["kind"] == "machinist"} == {
        "4-100-060",
        "4-100-040",
    }
