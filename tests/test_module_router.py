from proxy.services.les_module_service import (
    allowed_tool,
    classify_turn,
    module_registry_snapshot,
    route_module,
)


def test_module_router_selects_smeta():
    spec = route_module("Дай смету по ВОР и подбери ГЭСН", mode="auto")
    assert spec.module_id == "smeta"
    assert "lookup" in spec.allowed_tools


def test_module_router_selects_normcontrol():
    spec = route_module("Проверь раздел РД по ГОСТ и дай замечания", mode="auto")
    assert spec.module_id in {"normcontrol", "docs_review"}


def test_module_router_selects_general_project_rag():
    spec = route_module("Что известно по проекту и какие документы есть?", mode="auto")
    assert spec.module_id == "general_project_rag"


def test_followup_uses_active_module_instead_of_restart():
    active = {"module_id": "smeta", "task": "Оценка СКС"}
    spec = route_module("добавь номера ГЭСН", mode="auto", active_state=active)
    assert spec.module_id == "smeta"
    assert classify_turn("добавь номера ГЭСН", has_active_state=True) == "active_continuation"


def test_module_registry_is_not_smeta_only():
    snap = module_registry_snapshot()
    assert "smeta" in snap
    assert "bim_qto" in snap
    assert "contracts" in snap
    assert "general_project_rag" in snap


def test_tool_policy_is_limited_by_module():
    assert allowed_tool("smeta", "calculation") is True
    assert allowed_tool("contracts", "calculation") is False
