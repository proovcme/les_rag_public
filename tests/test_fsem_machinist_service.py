"""Тест справочника ФСЭМ «машина→машинист» (handoff #3): yaml поверх seed, fail-safe, RIM-эталон цел."""

from proxy.services import fsem_machinist_service as fsem


def test_yaml_loads_entries():
    m = fsem.machine_to_machinist()
    assert m["91.05.05-015"] == ("4-100-060", "ОТм: кран на автомобильном ходу 16 т, машинист 6,0")
    assert "91.14.02-002" in m  # 3-я запись
    assert len(m) >= 3


def test_lookup_and_list():
    assert fsem.lookup("91.14.02-001")[0] == "4-100-040"
    assert fsem.lookup("нет-такой-машины") is None
    entries = fsem.list_entries()
    assert any(e["machine_code"] == "91.05.05-015" for e in entries)


def test_missing_yaml_falls_back_to_seed(tmp_path):
    m = fsem.machine_to_machinist(str(tmp_path / "absent.yaml"))
    assert m == fsem._SEED  # отсутствующий/битый yaml → встроенный seed, не пусто


def test_rim_trace_baseline_unchanged():
    # вынос в yaml НЕ меняет поведение: эталон ГЭСН12-01-034-02 @0.61 = 11813.04
    from proxy.services import lsr_assembly_service as la
    from proxy.services import rim_lsr_trace_service as rim

    book = la._resolve_book(None)
    trace = rim.build_position_trace(
        {"code": "ГЭСН12-01-034-02", "qty": 0.61}, pricebook=book, k_ozp=1.0, k_em=1.0
    )
    assert trace["summary"]["total"] == 11813.04
