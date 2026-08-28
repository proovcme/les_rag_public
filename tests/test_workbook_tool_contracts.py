from proxy.services.chat_profile_service import registry_snapshot
from proxy.services.tool_registry_service import canonical_tool_registry
from proxy.services.workbook_tool_service import register_workbook_contracts


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
