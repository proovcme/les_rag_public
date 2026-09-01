from proxy.services.chat_capability_scope_service import (
    filter_profile_tools,
    resolve_selected_sources_only,
)


def test_dataset_selection_alone_preserves_profile_web_tools():
    assert filter_profile_tools(
        ["search_sources", "web_search", "read_source"],
        selected_sources_only=False,
    ) == ["search_sources", "web_search", "read_source"]


def test_selected_sources_only_removes_public_web_tools_from_registry():
    assert filter_profile_tools(
        ["search_sources", "web_search", "read_source"],
        selected_sources_only=True,
    ) == ["search_sources", "read_source"]


def test_follow_up_keeps_frozen_scope_until_user_explicitly_changes_it():
    traces = [{
        "evidence_manifest": {
            "scope": {"dataset_ids": ["ds"], "selected_sources_only": True}
        }
    }]

    assert resolve_selected_sources_only(None, traces) is True
    assert resolve_selected_sources_only(False, traces) is False
    assert resolve_selected_sources_only(None, []) is False
