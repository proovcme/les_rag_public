"""Детерминированная структура документа (состав/перечень разделов). 0 LLM."""
from proxy.services import document_outline_service as svc


FIXTURE = """
II. Состав разделов проектной документации на объекты капитального строительства
10. Раздел 1 "Пояснительная записка" должен содержать: ...
13. Раздел 3 "Архитектурные решения" должен содержать: ...
12. Раздел 2 "Схема планировочной организации земельного участка" ...
III. Состав разделов проектной документации на линейные объекты
38. Раздел 5 "Проект организации строительства" (линейный) должен содержать: ...
39. Раздел 6 "Проект организации работ по сносу (демонтажу) линейного объекта" ...
"""


def test_parse_outline_capital_only_cuts_linear():
    items = svc.parse_outline(FIXTURE, capital_only=True)
    nums = [it.number for it in items]
    assert nums == ["1", "2", "3"]  # линейные (5,6 после границы) отрезаны
    assert items[0].title == "Пояснительная записка"
    assert items[1].title.startswith("Схема планировочной")


def test_parse_outline_orders_by_number():
    items = svc.parse_outline('Раздел 11 "Смета" Раздел 2 "Схема" Раздел 1 "Записка"', capital_only=False)
    assert [it.number for it in items] == ["1", "2", "11"]


def test_is_outline_query():
    assert svc.is_outline_query("Состав проектной документации по ПП-87")
    assert svc.is_outline_query("какие разделы в постановлении 87")
    assert not svc.is_outline_query("что должен содержать раздел 9")


def test_supports_subitem_number():
    items = svc.parse_outline('Раздел 10 "Доступ инвалидов" Раздел 10(1) "Энергоэффективность"', capital_only=False)
    assert [it.number for it in items] == ["10", "10(1)"]


def test_format_outline():
    items = svc.parse_outline('Раздел 1 "Пояснительная записка"', capital_only=False)
    out = svc.format_outline(items, "ПП-87")
    assert "Пояснительная записка" in out and "ПП-87" in out
