"""Тест полного typed ФСЭМ «машина→машинист» и reconciliation ОТм."""

from proxy.services import fsem_machinist_service as fsem


def test_full_catalog_loads_entries():
    m = fsem.machine_to_machinist()
    assert m["91.05.05-015"][0] == "4-100-060"
    assert m["91.05.05-015"][1] == "Машинисты, средний разряд 6"
    assert "91.14.02-002" in m  # 3-я запись
    assert len(m) >= 900


def test_lookup_and_list():
    assert fsem.lookup("91.14.02-001")["driver_code"] == "4-100-040"
    assert fsem.lookup("нет-такой-машины") is None
    entries = fsem.list_entries()
    assert any(e["machine_code"] == "91.05.05-015" for e in entries)


def test_missing_catalog_fails_closed_without_seed(tmp_path):
    m = fsem.machine_to_machinist(str(tmp_path / "absent.yaml"))
    assert m == {}
    assert fsem.list_entries(str(tmp_path / "absent.sqlite")) == []


def test_rim_trace_uses_reconciled_full_fsem():
    from proxy.services import lsr_assembly_service as la
    from proxy.services import rim_lsr_trace_service as rim

    book = la._resolve_book(None)
    trace = rim.build_position_trace(
        {"code": "ГЭСН12-01-034-02", "qty": 0.61}, pricebook=book, k_ozp=1.0, k_em=1.0
    )
    assert trace["summary"]["total"] == 11896.35
    assert trace["summary"]["fsem_trace"]["status"] == "reconciled"
