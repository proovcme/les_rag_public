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
    """Агрегат «Затраты труда машинистов» расходится на конкретные шифры ОТм.

    Книга — детерминированный двойник из ``tests/test_rim_lsr_trace_service.py``, а не то,
    что резолвит рантайм: без выбранной книги ФСЭМ не применяет разбор вовсе
    (``not_applied_without_pricebook``), поэтому и статус, и деньги разборки на книге
    оператора зависели бы от содержимого ``data/price_base``.
    """
    from proxy.services import rim_lsr_trace_service as rim
    from tests import test_rim_lsr_trace_service as gold

    trace = rim.build_position_trace(
        {"code": gold.CODE, "qty": gold.GOLD_QTY}, pricebook=gold._Book(), k_ozp=1.0, k_em=1.0
    )
    summary = trace["summary"]

    assert summary["fsem_trace"]["status"] == "reconciled"
    assert summary["fsem_trace"]["machine_count"] == 3
    assert summary["fsem_trace"]["detailed_machinist_rows"] == 3
    assert summary["fsem_trace"]["hours"] == 1.01  # the card's aggregate ОТм, fully split
    # детализация обязательна: без неё ЗПМ — одна агрегатная строка без шифра и без цены,
    # а с ней ЗПМ считается по ставкам книги, которые названы в строках 4-100-*
    assert summary["zpm"] == gold.GOLD_ZPM
    machinist_rows = [row for row in trace["rows"] if row["type"] == "resource_machinist"]
    assert sorted(str(row["columns"]["2"]) for row in machinist_rows) == [
        "4-100-040",
        "4-100-060",
        "4-100-060",
    ]
