from copy import deepcopy
from types import SimpleNamespace

import pytest

from proxy.services.vor_result_integrity_service import audit_vor_result_integrity


def _work(source="Раздел!R2", operation_id="work-a", quantity=1, unit="шт", **extra):
    return {"source_row": source, "row_role": "work", "operation_id": operation_id,
            "title": "Названная моделью операция", "quantity": quantity, "unit": unit, **extra}


def _supply(source="Раздел!R3", role="material", parent="work-a", **extra):
    return {"source_row": source, "row_role": role, "title": "Изделие",
            "work_row": parent, "quantity": 1, "unit": "шт", **extra}


@pytest.mark.parametrize("rows", [[], [{"row_role": "header", "title": "Раздел"}],
                                 [{"row_role": "заголовок", "title": "Данные"}]])
def test_empty_or_header_only_result_is_not_a_materials_only_result(rows):
    assert audit_vor_result_integrity(rows) == []


def test_nonempty_result_without_work_cannot_pass_as_a_complete_vor():
    rows = [
        {"row_role": "header", "title": "Отделка"},
        _supply("Таблица 8!R9", "equipment", "", open_gap="Назначение изделия требует уточнения"),
        {"source_row": "Таблица 8!R10", "row_role": "unresolved", "open_gap": "Нет геометрии"},
    ]
    assert audit_vor_result_integrity(rows) == [{
        "code": "no_work_operations", "source_row": "Таблица 8!R9", "row_index": 1,
        "reason": "В результате есть содержательные строки, но нет ни одной строки работы (row_role=work).",
    }]


@pytest.mark.parametrize("role", ["material", "equipment", "resource", "материал", "оборудование", "ресурс"])
@pytest.mark.parametrize("parent", ["work-a", "Раздел!R2", "R2"])
def test_explicit_supply_links_resolve_to_existing_work_without_name_rules(role, parent):
    assert audit_vor_result_integrity([_work(), _supply(role=role, parent=parent)]) == []


def test_multiple_works_and_material_at_one_address_are_valid_link_endpoints():
    rows = [
        _work("DOCX_T5!R12", "prepare", quantity=4, unit="м²"),
        _work("DOCX_T5!R12", "finish", quantity=4, unit="м²"),
        _supply("DOCX_T5!R12", parent="DOCX_T5!R12", operation_id="product"),
        _supply("DOCX_T5!R12", role="resource", parent="finish"),
    ]
    assert audit_vor_result_integrity(rows) == []


@pytest.mark.parametrize("parent", ["Отопление!R16", "R16", "not-present"])
def test_a_link_to_a_nonexistent_work_reports_the_authored_reference(parent):
    issues = audit_vor_result_integrity([_work(), _supply("Отопление!R15", parent=parent)])
    assert [issue["code"] for issue in issues] == ["invalid_work_relationship"]
    assert issues[0]["source_row"] == "Отопление!R15"
    assert issues[0]["work_row"] == parent
    assert issues[0]["target_exists"] is False


@pytest.mark.parametrize("parent", ["other-product", "ЭОМ!R6", "R6"])
def test_a_reference_to_another_material_is_not_a_work_relationship(parent):
    rows = [_work(), _supply("ЭОМ!R6", parent="work-a", operation_id="other-product"),
            _supply("ЭОМ!R7", parent=parent)]
    issues = audit_vor_result_integrity(rows)
    assert [issue["code"] for issue in issues] == ["invalid_work_relationship"]
    assert issues[0]["target_exists"] is True
    assert issues[0]["target_roles"] == ["material"]


@pytest.mark.parametrize("parent", ["own-product", "АР!R20", "R20"])
def test_material_self_link_without_a_work_at_that_address_is_invalid(parent):
    rows = [_work(), _supply("АР!R20", parent=parent, operation_id="own-product")]
    assert [issue["code"] for issue in audit_vor_result_integrity(rows)] == ["invalid_work_relationship"]


def test_relative_link_never_falls_back_to_a_work_on_another_sheet():
    rows = [_work("Силовая сеть!R2"), _supply("Вентиляция!R3", parent="R2")]
    assert [issue["code"] for issue in audit_vor_result_integrity(rows)] == ["invalid_work_relationship"]


@pytest.mark.parametrize("parent", [None, "", " ", "-", "—"])
def test_unexplained_supply_without_a_link_is_a_gap_even_with_a_work_at_same_address(parent):
    issues = audit_vor_result_integrity([_work(), _supply("Раздел!R2", parent=parent)])
    assert [issue["code"] for issue in issues] == ["missing_work_relationship"]


@pytest.mark.parametrize("explanation", [
    {"coverage": "Только поставка заказчику, монтаж не входит в объём задания."},
    {"open_gap": "Не установлено, к какой из двух операций относится изделие."},
    {"coverage": "Изделие исключено из работ по указанию заказчика."},
])
def test_explicit_exclusion_or_open_question_is_preserved_without_inventing_installation(explanation):
    rows = [_work(), _supply(parent="", **explanation)]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows) == []
    assert rows == before


@pytest.mark.parametrize("explanation", [{"coverage": "-"}, {"open_gap": "  "}, {"coverage": True}])
def test_an_empty_placeholder_is_not_a_relationship_explanation(explanation):
    assert [issue["code"] for issue in audit_vor_result_integrity([
        _work(), _supply(parent="", **explanation)
    ])] == ["missing_work_relationship"]


def test_an_explanation_does_not_make_an_invalid_explicit_link_valid():
    rows = [_work(), _supply(parent="ghost-operation", coverage="Поставка отдельно")]
    assert [issue["code"] for issue in audit_vor_result_integrity(rows)] == ["invalid_work_relationship"]


@pytest.mark.parametrize("quantity", [None, "", " \t"])
def test_missing_work_quantity_is_distinct_from_a_numeric_zero(quantity):
    issues = audit_vor_result_integrity([_work(quantity=quantity)])
    assert [issue["code"] for issue in issues] == ["missing_work_quantity"]


@pytest.mark.parametrize("quantity", [0, 0.0, "0", "0,00"])
def test_zero_quantity_is_preserved_and_does_not_become_a_missing_quantity(quantity):
    rows = [_work(quantity=quantity)]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows) == []
    assert rows == before


@pytest.mark.parametrize("unit", [None, "", " ", "-", "—"])
def test_a_work_without_a_unit_has_its_own_issue(unit):
    assert [issue["code"] for issue in audit_vor_result_integrity([_work(unit=unit)])] == ["missing_work_unit"]


def test_a_title_that_sounds_like_installation_does_not_reclassify_material():
    rows = [_supply(parent="", title="Монтаж и установка оборудования", coverage="Только поставка")]
    assert [issue["code"] for issue in audit_vor_result_integrity(rows)] == ["no_work_operations"]


def test_a_norm_code_without_an_authored_work_role_does_not_create_an_operation():
    rows = [{"source_row": "Ведомость!R8", "norm_code": "AUTHORED-CODE", "quantity": 2, "unit": "м"}]
    assert [issue["code"] for issue in audit_vor_result_integrity(rows)] == ["no_work_operations"]


def test_optional_catalog_normalizes_technical_aliases_without_changing_the_result():
    class Catalog:
        def lookup(self, value):
            return SimpleNamespace(locator="Таблица!R40") if value == "source-alias" else None

    rows = [_work("Таблица!R40"), _supply("Таблица!R41", parent="source-alias")]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows, source_catalog=Catalog()) == []
    assert rows == before


def test_relative_reference_uses_the_catalog_sheet_of_an_aliased_source():
    class Catalog:
        def lookup(self, value):
            locators = {"work-alias": "Зал!R40", "product-alias": "Зал!R41"}
            return SimpleNamespace(locator=locators[value]) if value in locators else None

    rows = [_work("work-alias"), _supply("product-alias", parent="R40")]
    before = deepcopy(rows)
    assert audit_vor_result_integrity(rows, source_catalog=Catalog()) == []
    assert rows == before


def test_all_authored_fields_remain_unchanged_when_several_issues_are_reported():
    rows = [
        _work("Лист 3!R4", quantity=None, unit="", coverage="Не хватает размеров"),
        _supply("Лист 3!R5", parent="missing-work", nested={"evidence_refs": ["Q1.H2"]}),
        _supply("Лист 3!R6", parent=""),
    ]
    before = deepcopy(rows)
    assert [issue["code"] for issue in audit_vor_result_integrity(rows)] == [
        "missing_work_quantity", "missing_work_unit", "invalid_work_relationship", "missing_work_relationship",
    ]
    assert rows == before
