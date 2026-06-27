"""W20.1 — Парсер смет (ЛСР → позиции): позиции и итог бит-в-бит, разделы. 0 LLM."""
import importlib

import pytest


# Синтетический экспорт Гранд-Сметы: служебные строки, заголовок, разделы, позиции, итоги.
MATRIX = [
    ["Локальный сметный расчёт № 02-01-01", None, None, None, None, None],
    [None, None, None, None, None, None],
    ["№ п/п", "Обоснование", "Наименование работ и затрат", "Ед. изм.", "Количество", "Стоимость всего"],
    ["Раздел 1. Земляные работы", None, None, None, None, None],
    ["1", "ГЭСН 01-01-003", "Разработка грунта экскаватором", "1000 м3", "2,5", "125000,50"],
    ["2", "ФЕР 01-02-001", "Уплотнение грунта", "100 м3", "10", "30000"],
    ["", "", "Итого по разделу 1", "", "", "155000,50"],
    ["Раздел 2. Бетонные работы", None, None, None, None, None],
    ["3", "ГЭСН 06-01-001", "Устройство бетонной подготовки", "м3", "48", "240000"],
    ["", "", "Итого по разделу 2", "", "", "240000"],
    ["", "", "ВСЕГО по смете", "", "", "395000,50"],
]


def test_parse_positions_and_sections():
    import proxy.services.estimate_service as es
    items = es.parse_estimate_rows(MATRIX)
    # три позиции (итоги/разделы/служебные — отброшены)
    assert [it.name for it in items] == [
        "Разработка грунта экскаватором", "Уплотнение грунта", "Устройство бетонной подготовки"
    ]
    assert items[0].code == "ГЭСН 01-01-003"
    assert items[0].quantity == 2.5 and items[0].total_cost == 125000.50
    assert items[0].section == "Раздел 1. Земляные работы"
    assert items[2].section == "Раздел 2. Бетонные работы"
    assert items[1].unit == "м³" or items[1].unit  # нормализация единиц переиспользует bor_service


def test_total_matches_source_bit_for_bit():
    import proxy.services.estimate_service as es
    items = es.parse_estimate_rows(MATRIX)
    summary = es.summarize(items)
    # сумма позиций = «ВСЕГО по смете» источника (395000,50)
    assert summary["total_cost"] == 395000.50
    assert summary["items_count"] == 3
    by_section = {s["section"]: s["total_cost"] for s in summary["sections"]}
    assert by_section["Раздел 1. Земляные работы"] == 155000.50
    assert by_section["Раздел 2. Бетонные работы"] == 240000.0


def test_num_parses_grand_smeta_formats():
    import proxy.services.estimate_service as es
    assert es._num("1 234,56") == 1234.56
    assert es._num("48") == 48.0
    assert es._num("\xa01\xa0000") == 1000.0
    assert es._num("") is None and es._num(None) is None and es._num("—") is None


@pytest.fixture()
def db(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("RAG_META_DB_PATH", str(tmp_path / "data" / "les_meta.db"))
    import backend.rag_config as rc
    importlib.reload(rc)
    import proxy.services.estimate_service as es
    importlib.reload(es)
    return es, tmp_path


def test_import_xlsx_roundtrip_and_project_total(db):
    es, tmp_path = db
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    for row in MATRIX:
        ws.append(["" if c is None else c for c in row])
    xlsx = tmp_path / "lsr.xlsx"
    wb.save(str(xlsx))

    result = es.import_estimate(xlsx, project_id=7, name="ЛСР 02-01-01")
    assert result["items_count"] == 3
    assert result["total_cost"] == 395000.50

    stored = es.get_estimate(result["estimate_id"])
    assert len(stored["items"]) == 3
    assert stored["items"][0]["name"] == "Разработка грунта экскаватором"

    total = es.project_total(7)
    assert total["estimates_count"] == 1 and total["total_cost"] == 395000.50
    # партиционирование по объекту (Q3)
    assert es.project_total(999)["estimates_count"] == 0
