from proxy.services.chat_profile_service import registry_snapshot
from proxy.services.tool_registry_service import canonical_tool_registry
from proxy.services.workbook_tool_service import (
    available_chat_workbook_tools,
    register_workbook_contracts,
)
from proxy.services import workbook_tool_service


def test_only_canonical_workbook_names_are_registered():
    registry = canonical_tool_registry()
    names = {item.contract.name for item in registry.registrations()}

    assert {"build_lsr_workbook", "build_vor_workbook"} <= names
    assert not {name for name in names if name.startswith("estimate_") and "workbook" in name}
    for name in ("build_lsr_workbook", "build_vor_workbook"):
        contract = registry.require(name).contract
        assert contract.effect.value == "draft"
        assert contract.idempotency.value == "required"
        assert contract.result_schema == "les.workbook_tool_result.v1"
        assert contract.result_budget.max_chars >= 500_000
        assert contract.result_budget.max_items >= 20_000


def test_installing_contracts_does_not_activate_profile_revision(tmp_path):
    db = tmp_path / "meta.db"
    before = registry_snapshot(db_path=db)
    active_before = {item["mode"]: item["active_revision_id"] for item in before["profiles"]}

    register_workbook_contracts(canonical_tool_registry())

    after = registry_snapshot(db_path=db)
    assert {item["mode"]: item["active_revision_id"] for item in after["profiles"]} == active_before


def test_new_factory_estimator_seed_includes_canonical_workbook_tools(tmp_path):
    snapshot = registry_snapshot(db_path=tmp_path / "fresh.db")
    estimator = next(item for item in snapshot["profiles"] if item["mode"] == "estimator")

    assert {"build_lsr_workbook", "build_vor_workbook"} <= set(estimator["active"]["tools"])


def test_chat_only_advertises_workbook_tools_with_a_real_adapter():
    assert available_chat_workbook_tools(executor_configured=True) == frozenset(
        {"build_lsr_workbook", "build_vor_workbook"}
    )
    assert available_chat_workbook_tools(executor_configured=False) == frozenset()


def test_workbook_contracts_keep_lsr_rows_plain_and_require_authored_vor_rows():
    registry = canonical_tool_registry()
    lsr_schema = registry.require("build_lsr_workbook").contract.input_schema
    vor_schema = registry.require("build_vor_workbook").contract.input_schema

    decisions_schema = lsr_schema["properties"]["decisions"]
    assert decisions_schema["items"] == {"type": "object"}
    assert "maxItems" not in decisions_schema
    assert lsr_schema["properties"]["confirmed_data"] == {
        "type": "object",
        "additionalProperties": {"type": "object"},
    }
    assert "confirmed_data" not in lsr_schema.get("required", [])
    vor_rows = vor_schema["properties"]["decisions"]
    assert "decisions" in vor_schema["required"]
    assert "minItems" not in vor_rows and "maxItems" not in vor_rows
    assert vor_rows["items"]["additionalProperties"] is True
    assert tuple(vor_rows["items"]["properties"]["row_role"]["enum"]) == (
        "work", "material", "equipment", "resource", "unresolved", "header",
    )
    assert "norm_code" not in vor_rows["items"]["required"]
    assert tuple(vor_rows["items"]["required"]) == ("source_row", "row_role", "title")
    assert "confirmed_data" not in vor_schema.get("properties", {})


def test_vor_native_schema_accepts_header_zero_unknown_and_extra_authored_fields():
    from proxy.services.structured_extract import validate

    schema = canonical_tool_registry().require("build_vor_workbook").contract.input_schema
    rows = [{
        "source_row": "Исходник!R2", "row_role": role, "work_row": "",
        "title": "Авторское решение", "unit": "" if role == "header" else "м",
        "quantity": quantity, "open_gap": "", "coverage": "Авторский состав",
        "operation_id": "op_known", "expected_revision": 4,
        "custom_source_basis": {"literal": "kept", "formula": "a*b"},
    } for role, quantity in (("header", None), ("work", 0), ("unresolved", None))]
    assert validate({"attachment_id": "read_123456abcdef", "decisions": rows}, schema) == []
    assert validate({"attachment_id": "read_123456abcdef", "decisions": []}, schema) == []
    assert validate({"attachment_id": "read_123456abcdef", "decisions": [
        {"source_row": "Sheet!R2", "row_role": "work", "title": "Saved literal decision"},
    ]}, schema) == []
    assert validate({"attachment_id": "read_123456abcdef"}, schema)
    assert validate({"attachment_id": "read_123456abcdef", "decisions": None}, schema)
    for field, value in (("row_role", "invented"), ("source_row", 2), ("quantity", {"not": "a literal"})):
        assert validate({"attachment_id": "read_123456abcdef", "decisions": [{**rows[1], field: value}]}, schema)
    for required in ("source_row", "row_role", "title"):
        incomplete = {key: value for key, value in rows[1].items() if key != required}
        assert validate({"attachment_id": "read_123456abcdef", "decisions": [incomplete]}, schema)


def test_vor_native_schema_keeps_literal_decimal_and_existing_optional_nulls():
    from proxy.services.structured_extract import validate

    schema = canonical_tool_registry().require("build_vor_workbook").contract.input_schema
    row = {"source_row": "S!R2", "row_role": "work", "title": "Literal decision", "quantity": "23,6",
           "unit": None, "work_row": None, "open_gap": None, "section": None, "coverage": None,
           "covered_by_work_id": None, "operation_id": None, "expected_revision": None}
    assert validate({"attachment_id": "read_owned", "decisions": [row]}, schema) == []
    assert validate({"attachment_id": "read_owned", "decisions": [{**row, "expected_revision": 1}]}, schema) == []
    for invalid in (0, -1, "1", True):
        assert validate({"attachment_id": "read_owned", "decisions": [{**row, "expected_revision": invalid}]}, schema)
    for strict in ("source_row", "row_role", "title"):
        assert validate({"attachment_id": "read_owned", "decisions": [{**row, strict: None}]}, schema)


def test_vor_native_summary_requires_work_decisions_instead_of_specification_copy():
    summary = canonical_tool_registry().require("build_vor_workbook").contract.summary
    assert "model-authored" in summary
    assert "never model decisions" not in summary
    assert "preserves the source specification rows" not in summary


def test_chat_workbook_capabilities_come_from_the_executor_manifest():
    assert hasattr(workbook_tool_service, "chat_workbook_adapters")
    adapters = workbook_tool_service.chat_workbook_adapters()

    assert frozenset(adapters) == available_chat_workbook_tools(executor_configured=True)
    assert set(adapters) == {"build_lsr_workbook", "build_vor_workbook"}
    assert all(callable(adapter) for adapter in adapters.values())


def test_every_factory_profile_tool_has_a_real_execution_boundary(tmp_path):
    registry = canonical_tool_registry()
    registrations = {item.contract.name: item for item in registry.registrations()}
    context_bound = {
        name
        for name, item in registrations.items()
        if "execution_context_required" in item.contract.tags
    }
    chat_adapters = set(workbook_tool_service.chat_workbook_adapters())
    snapshot = registry_snapshot(db_path=tmp_path / "profiles.db")

    promised = {
        str(name)
        for profile in snapshot["profiles"]
        for name in profile["active"]["tools"]
    }
    assert promised <= set(registrations)
    assert context_bound == chat_adapters
    for name in promised - context_bound:
        assert registrations[name].handler.__name__ != "_handler_requires_execution_context"
