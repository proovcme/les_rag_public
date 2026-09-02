import pytest

from proxy.services.tool_contract_service import (
    EffectClass,
    IdempotencyPolicy,
    ResultBudget,
    RetryPolicy,
    ToolContract,
)
from proxy.services.tool_registry_service import (
    Availability,
    ToolRegistration,
    ToolRegistry,
    canonical_tool_registry,
)


def _registration(
    name: str = "read_source",
    version: str = "1.0.0",
    *,
    available: bool = True,
) -> ToolRegistration:
    contract = ToolContract(
        name=name,
        version=version,
        title=name.replace("_", " ").title(),
        category="source",
        summary="Read bounded evidence",
        input_schema={"type": "object"},
        result_schema="les_tool_result_v1",
        effect=EffectClass.READ,
        scopes=("dataset",),
        timeout_seconds=30,
        retry=RetryPolicy.SAFE,
        idempotency=IdempotencyPolicy.DERIVED,
        result_budget=ResultBudget(max_chars=7000, max_items=20),
        model_owned_fields=(),
        provenance="source_refs_required",
    )
    return ToolRegistration(
        contract=contract,
        handler=lambda args: {"echo": args},
        availability=lambda runtime: Availability(
            available=available,
            reason="available" if available else "backend unavailable",
        ),
    )


def test_registry_rejects_duplicate_name_or_version() -> None:
    registry = ToolRegistry()
    registry.register(_registration())

    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register(_registration())


def test_registry_rejects_second_active_version_of_same_name() -> None:
    registry = ToolRegistry()
    registry.register(_registration(version="1.0.0"))

    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register(_registration(version="1.1.0"))


def test_registry_exposes_runtime_availability_without_removing_contract() -> None:
    registry = ToolRegistry([_registration(available=False)])

    registration = registry.require("read_source")
    availability = registration.availability({"provider": "local"})

    assert registration.contract.name == "read_source"
    assert availability == Availability(available=False, reason="backend unavailable")


def test_canonical_registry_contains_each_existing_handler_once() -> None:
    registry = canonical_tool_registry()
    names = [item.contract.name for item in registry.registrations()]

    assert len(names) == len(set(names))
    assert {
        "dataset_map",
        "search_sources",
        "read_source",
        "read_pdf_source",
        "read_excel_source",
        "look_at_pdf_page",
        "search_project_tables",
        "read_project_table",
        "assemble_project_volume",
        "web_search",
        "web_read",
        "filesystem_roots",
        "filesystem_list",
        "filesystem_stat",
        "filesystem_read_text",
        "filesystem_search",
        "filesystem_hash",
        "build_lsr_workbook",
        "build_vor_workbook",
    } == set(names)


def test_canonical_registration_uses_existing_handler() -> None:
    registration = canonical_tool_registry().require("filesystem_roots")

    payload = registration.handler({})

    assert payload["schema"] == "les_tool_result_v1"
    assert payload["tool"] == "filesystem_roots"
