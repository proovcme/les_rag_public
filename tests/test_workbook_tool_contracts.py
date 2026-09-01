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


def test_lsr_contract_accepts_plain_model_output_without_a_decision_schema():
    registry = canonical_tool_registry()
    lsr_schema = registry.require("build_lsr_workbook").contract.input_schema
    vor_schema = registry.require("build_vor_workbook").contract.input_schema

    decisions_schema = lsr_schema["properties"]["decisions"]
    assert decisions_schema["items"] == {"type": "object"}
    assert "maxItems" not in decisions_schema
    assert "decisions" in vor_schema["properties"]
    assert "decisions" not in vor_schema.get("required", [])


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
