from __future__ import annotations

from types import SimpleNamespace

import pytest

from proxy.services.smeta_agent_runner_service import (
    GoogleAdkSmetaRunner,
    QwenAgentSmetaRunner,
    _google_function_schema,
    normalize_smeta_agent_engine,
)
from proxy.smeta_core import document_workflow as workflow


WORK = {"work_id": "w1", "title": "Монтаж блока", "unit": "шт", "quantity": 1}
CODE = "ГЭСН01-01-001-01"


def _mapping_args() -> dict:
    return {
        "rows": [{
            "work_id": "w1",
            "decision": "bind",
            "norm_code": CODE,
            "selection_kind": "exact",
            "applicability": "exact",
            "analog_limitations": [],
            "technology_check": {
                "matched_operations": ["монтаж"],
                "missing_operations": [],
                "extra_operations": [],
                "foreign_resources": [],
                "overlaps_with_work_ids": [],
                "overlap_resolution": "нет",
                "conditions_checked": [],
                "unresolved_conditions": [],
                "conclusion": "applicable",
            },
            "reason": "карточка соответствует работе",
        }],
    }


@pytest.fixture
def norm_backend(monkeypatch):
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [{
            "norm_code": CODE,
            "title": "Монтаж блока",
            "measure_unit": "шт",
            "work_steps": ["монтаж"],
            "resource_preview": [],
        }]}
        for query in queries
    })
    monkeypatch.setattr(workflow.nr_sp_service, "candidates", lambda **_kwargs: [])
    monkeypatch.setattr(workflow.gesn_service, "get_norm", lambda *_args, **_kwargs: {
        "name": "Монтаж блока", "unit": "шт", "work_steps": ["монтаж"], "resources": [],
    })


def test_common_tool_session_requires_opened_norm(norm_backend):
    session = workflow.SmetaNormToolSession([WORK], candidate_limit=4)
    premature = session.execute("submit_lsr_mapping", _mapping_args(), turn=1)
    assert premature == {"ok": True, "rows": 1}
    assert session.accepted_rows["w1"]["precalculation_blockers"][0]["code"] == "norm_card_not_opened"

    fresh = workflow.SmetaNormToolSession([WORK], candidate_limit=4)
    searched = fresh.execute(
        "search_norms_batch", {"items": [{"work_id": "w1", "query": "монтаж блока"}]}, turn=1,
    )
    assert searched["rows"][0]["candidates"][0]["norm_code"] == CODE
    read = fresh.execute(
        "read_norms_batch", {"items": [{"work_id": "w1", "norm_code": CODE}]}, turn=2,
    )
    assert read["rows"][0]["ok"] is True
    assert fresh.execute("submit_lsr_mapping", _mapping_args(), turn=3) == {"ok": True, "rows": 1}
    assert fresh.complete is True
    assert [item["tool"] for item in fresh.tool_trajectory] == [
        "search_norms_batch", "read_norms_batch", "submit_lsr_mapping",
    ]


def test_qwen_agent_adapter_uses_common_session(monkeypatch, norm_backend):
    import qwen_agent.agents

    class FakeAgent:
        def __init__(self, *, function_list, **_kwargs):
            self.tools = {tool.name: tool for tool in function_list}

        def run(self, *, messages, **_kwargs):
            assert "work_items" in messages[0]["content"]
            self.tools["search_norms_batch"].call({
                "items": [{"work_id": "w1", "query": "монтаж блока"}],
            })
            self.tools["read_norms_batch"].call({
                "items": [{"work_id": "w1", "norm_code": CODE}],
            })
            self.tools["submit_lsr_mapping"].call(_mapping_args())
            yield []

    monkeypatch.setattr(qwen_agent.agents, "FnCallAgent", FakeAgent)
    result = QwenAgentSmetaRunner().run_batch(
        [WORK], candidate_limit=4, max_turns=4, progress=None, user_request="сделай смету",
    )
    assert result["valid_model_rows"] == 1
    assert result["agent_trace"]["engine"] == "qwen_agent"
    assert result["agent_trace"]["tool_turns"] == 3


def test_google_adk_adapter_uses_common_session(monkeypatch, norm_backend):
    import google.adk.agents
    import google.adk.runners
    import google.adk.sessions

    class FakeAgent:
        def __init__(self, *, tools, **_kwargs):
            self.tools = {tool.name: tool for tool in tools}

    class FakeSessionService:
        async def create_session(self, **_kwargs):
            return object()

    class FakeEvent:
        usage_metadata = SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15,
        )

        def model_dump(self, **_kwargs):
            return {"author": "les_smeta_google_adk"}

    class FakeRunner:
        def __init__(self, *, agent, **_kwargs):
            self.agent = agent

        async def run_async(self, **_kwargs):
            await self.agent.tools["search_norms_batch"].run_async(
                args={"items": [{"work_id": "w1", "query": "монтаж блока"}]}, tool_context=None,
            )
            await self.agent.tools["read_norms_batch"].run_async(
                args={"items": [{"work_id": "w1", "norm_code": CODE}]}, tool_context=None,
            )
            await self.agent.tools["submit_lsr_mapping"].run_async(
                args=_mapping_args(), tool_context=None,
            )
            yield FakeEvent()

        async def close(self):
            return None

    monkeypatch.setattr(google.adk.agents, "LlmAgent", FakeAgent)
    monkeypatch.setattr(google.adk.runners, "Runner", FakeRunner)
    monkeypatch.setattr(google.adk.sessions, "InMemorySessionService", FakeSessionService)
    result = GoogleAdkSmetaRunner(
        api_key="test-key", cloud_consent=True,
    ).run_batch([WORK], candidate_limit=4, max_turns=4, progress=None, user_request="")
    assert result["valid_model_rows"] == 1
    assert result["agent_trace"]["engine"] == "google_adk"
    assert result["agent_trace"]["token_usage"]["total_tokens"] == 15


def test_runner_guards_and_cancellation():
    assert normalize_smeta_agent_engine("QWEN_AGENT") == "qwen_agent"
    with pytest.raises(ValueError, match="unsupported"):
        normalize_smeta_agent_engine("unknown")
    with pytest.raises(PermissionError, match="consent"):
        GoogleAdkSmetaRunner(api_key="key", cloud_consent=False)
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        GoogleAdkSmetaRunner(api_key="", cloud_consent=True)
    with pytest.raises(RuntimeError, match="cancelled"):
        QwenAgentSmetaRunner(cancel_check=lambda: True).run_batch(
            [WORK], candidate_limit=4, max_turns=2, progress=None, user_request="",
        )
    assert _google_function_schema({
        "type": "object", "allOf": [{"if": {"const": "x"}, "then": {}}],
        "properties": {}, "required": [],
    }) == {"type": "object", "properties": {}, "required": []}


def test_settings_persist_google_key_without_exposing_it():
    from proxy.routers import settings

    request = settings.SettingsRequest(
        smeta_agent_engine="google_adk",
        smeta_google_model="gemini-3.5-flash",
        google_api_key="secret-value",
        cloud_consent=True,
    )
    updates = settings._provider_updates(request)
    assert updates["LES_SMETA_AGENT_ENGINE"] == "google_adk"
    assert updates["GOOGLE_API_KEY"] == "secret-value"
    assert settings._redact_sensitive_updates(updates)["GOOGLE_API_KEY"] == "***"
