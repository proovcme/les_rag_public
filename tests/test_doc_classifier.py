"""Классификатор типа строительной таблицы (сигнатура шапки + название)."""

from __future__ import annotations

from proxy.services.doc_classifier import classify_table


def test_vedomost_materialov_by_headers():
    cols = ["№ п/п", "Наименование и техническая характеристика", "Наименование",
            "Код продукции", "Поставщик", "Ед.изм.", "Кол-во"]
    r = classify_table(cols)
    assert r["type"] == "ведомость_материалов"
    assert r["route"] == "объёмы_закупки" and r["confidence"] >= 0.5


def test_checklist_priemki_by_headers():
    cols = ["Этап", "Наименование оборудования", "АОРПИ", "Монтаж и расключение",
            "ЛК, КОРПУС", "Замечание/Примечание"]
    assert classify_table(cols)["type"] == "чек-лист_приемки"


def test_specifikaciya_by_headers():
    cols = ["Поз.", "Обозначение", "Наименование", "Кол.", "Масса ед.", "Примечание"]
    assert classify_table(cols)["type"] == "спецификация"


def test_explication_needs_title():
    cols = ["номер", "Имя"]  # шапки мало → неизвестно
    assert classify_table(cols)["type"] == "неизвестно"
    # название таблицы — решающий сигнал
    r = classify_table(cols, title="Экспликация помещений, этаж 5")
    assert r["type"] == "экспликация_помещений" and r["route"] == "реестр_помещений"


def test_unknown_on_empty():
    assert classify_table([])["type"] == "неизвестно"
    assert classify_table(["a", "b", "c"])["type"] == "неизвестно"


def test_specific_title_beats_generic():
    # «кабельный журнал» содержит «журнал» → специфичный тип должен бить generic
    r = classify_table(["марка", "сечение"], title="Кабельный журнал")
    assert r["type"] == "кабельный_журнал" and r["route"] == "кабели"


def test_title_disambiguates_materials_vs_vor():
    # одинаково «наименование/ед.изм/количество», но название разводит
    cols = ["№", "Наименование работ", "Ед.изм", "Количество", "Обоснование"]
    assert classify_table(cols, title="Ведомость объёмов работ")["type"] == "ведомость_объемов_работ"
