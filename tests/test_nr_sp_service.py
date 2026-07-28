"""НР/СП по виду работ: сопоставление нормы → нормативы.

Значения сверены с официальными Приказами Минстроя:
  НР — 812/пр (графа «Территория»), СП — 774/пр. Кровли дополнительно сверены на эталоне.
"""

from __future__ import annotations

from proxy.services.nr_sp_service import resolve


def test_kровли_verified():
    r = resolve(code="ГЭСН12")
    assert r["nr_pct"] == 109 and r["sp_pct"] == 57
    assert r["label"] == "Кровли" and r["default"] is False
    assert resolve("Монтаж медного отлива")["status"] == "unresolved"


def test_otdelochnye_from_orders():
    # Пр/812-15 = 100, Пр/774-15 = 49 (Отделочные работы)
    r = resolve(code="ГЭСН15")
    assert r["nr_pct"] == 100 and r["sp_pct"] == 49
    assert r["default"] is False


def test_zemlyanye_from_orders():
    # Пр/812-1.1 = 92, Пр/774-1.1 = 46 (Земляные, механизированным способом)
    r = resolve(code="ГЭСН01", rule_id="nrsp-1.1")
    assert r["nr_pct"] == 92 and r["sp_pct"] == 46
    assert r["default"] is False


def test_kirpich_from_orders():
    # Пр/812-8 = 110, Пр/774-8 = 69 (Конструкции из кирпича и блоков)
    r = resolve(code="ГЭСН08")
    assert r["nr_pct"] == 110 and r["sp_pct"] == 69
    assert r["default"] is False


def test_santehnika_from_orders():
    # Пр/812-16 = 121, Пр/774-16 = 72 (Сантехнические внутренние)
    r = resolve(code="ГЭСН17")
    assert r["nr_pct"] == 121 and r["sp_pct"] == 72
    assert r["default"] is False


def test_code_collection_takes_priority_over_generic_words():
    r = resolve("сборка конструкций", code="ГЭСНм38")
    assert r["label"] == "Изготовление технологических металлических конструкций в условиях производственных баз"
    assert r["nr_pct"] == 90 and r["sp_pct"] == 45
    assert r["default"] is False


def test_code_collection_normalization():
    assert resolve(code="ГЭСН12")["label"] == "Кровли"
    assert resolve(code="ГЭСН:12")["label"] == "Кровли"
    assert resolve(code="12-01-001-01")["status"] == "unresolved"


def test_collection_subtype_can_override_general_collection():
    assert resolve(code="ГЭСН27")["status"] == "ambiguous"
    r = resolve(code="ГЭСН27", rule_id="nrsp-21.1")
    assert "устройство покрытий дорожек" in r["label"]
    assert r["nr_pct"] == 113 and r["sp_pct"] == 77


def test_expanded_collections_cover_construction_and_montage():
    assert resolve(code="ГЭСН22")["label"] == "Наружные сети водопровода, канализации, теплоснабжения, газопроводы"
    assert resolve(code="ГЭСНм12")["label"] == "Технологические трубопроводы"


def test_default_for_unknown():
    # Вид без точного collection/rule не получает молчаливый норматив.
    r = resolve("Пусконаладочные работы систем автоматики XYZ")
    assert r["default"] is True
    assert r["nr_pct"] is None and r["sp_pct"] is None
    assert resolve("")["status"] == "unresolved"
