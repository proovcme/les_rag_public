from __future__ import annotations

from types import SimpleNamespace

import pytest

from proxy.services.smeta_agent_runner_service import (
    GoogleAdkSmetaRunner,
    QwenAgentSmetaRunner,
    _google_function_schema,
    _qwen_terminal_schema,
    _requires_evidence_continuation,
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
            "candidate_evaluations": [{
                "candidate_code": CODE,
                "operation_match": "exact",
                "object_match": "exact",
                "unit_match": "compatible",
                "scope_match": "exact",
                "foreign_resources": [],
                "decision": "selected",
                "reason": "открытая карточка соответствует работе",
            }],
            "technology_check": {
                "matched_operations": ["монтаж"],
                "missing_operations": [],
                "extra_operations": [],
                "foreign_resources": [],
                "overlaps_with_work_ids": [],
                "overlap_resolution": "нет",
                "conditions_checked": ["измеритель и состав работ"],
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


def test_rim_tool_session_rejects_bind_before_scoped_search_and_typed_read(
    norm_backend,
):
    session = workflow.SmetaNormToolSession(
        [WORK],
        candidate_limit=4,
        require_scoped_search=True,
    )

    premature = session.execute("submit_lsr_mapping", _mapping_args(), turn=1)

    assert premature["ok"] is False
    assert premature["errors"][0]["error"] == (
        "RIM bind requires a typed card opened by read_norms_batch"
    )
    assert session.accepted_rows == {}


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
    assert result["agent_trace"]["terminal_recovery_attempted"] is False


def test_qwen_agent_recovers_terminal_mapping_with_same_model_context(monkeypatch, norm_backend):
    import qwen_agent.agents

    calls = []

    class FakeAgent:
        def __init__(self, *, function_list, **_kwargs):
            self.tools = {tool.name: tool for tool in function_list}

        def run(self, *, messages, **_kwargs):
            calls.append(messages)
            self.tools["search_norms_batch"].call({
                "items": [{
                    "work_id": "w1",
                    "query": "монтаж блока",
                    "search_intent": "source_literal",
                }],
            })
            self.tools["read_norms_batch"].call({
                "items": [{"work_id": "w1", "norm_code": CODE}],
            })
            yield [{"role": "assistant", "content": "Карточка подходит."}]

    monkeypatch.setattr(qwen_agent.agents, "FnCallAgent", FakeAgent)
    runner = QwenAgentSmetaRunner()
    recovered = []

    def structured_terminal_mapping(**kwargs):
        recovered.append(kwargs)
        return _mapping_args()

    monkeypatch.setattr(runner, "_structured_terminal_mapping", structured_terminal_mapping)
    result = runner.run_batch(
        [WORK], candidate_limit=4, max_turns=4, progress=None, user_request="сделай смету",
    )

    assert result["valid_model_rows"] == 1
    assert len(calls) == 1
    assert recovered[0]["final_messages"][-1]["content"] == "Карточка подходит."
    assert result["agent_trace"]["terminal_recovery_attempted"] is True
    assert result["model_trace"][-1]["transport"] == "same_model_json_schema_recovery"


def test_qwen_returns_to_tools_when_structured_bind_needs_opened_comparison(monkeypatch, norm_backend):
    import qwen_agent.agents

    alternative = "ГЭСН01-01-001-02"
    monkeypatch.setattr(workflow, "browse_norms_many", lambda queries, **_kwargs: {
        query: {"backend": "rrf", "cards": [
            {"norm_code": CODE, "title": "Монтаж блока", "measure_unit": "шт"},
            {"norm_code": alternative, "title": "Установка блока", "measure_unit": "шт"},
        ]} for query in queries
    })
    runs = []

    class FakeAgent:
        def __init__(self, *, function_list, **_kwargs):
            self.tools = {tool.name: tool for tool in function_list}

        def run(self, *, messages, **_kwargs):
            runs.append(messages)
            if len(runs) == 1:
                self.tools["search_norms_batch"].call({
                    "items": [{
                        "work_id": "w1", "query": "монтаж блока", "search_intent": "source_literal",
                    }],
                })
                yield [{"role": "assistant", "content": "Выбираю первую норму."}]
                return
            self.tools["read_norms_batch"].call({
                "items": [
                    {"work_id": "w1", "norm_code": CODE},
                    {"work_id": "w1", "norm_code": alternative},
                ],
            })
            mapping = _mapping_args()
            mapping["rows"][0]["candidate_evaluations"].append({
                "candidate_code": alternative,
                "operation_match": "partial",
                "object_match": "exact",
                "unit_match": "compatible",
                "scope_match": "partial",
                "foreign_resources": [],
                "decision": "rejected",
                "reason": "вторая карточка покрывает только часть операции",
            })
            self.tools["submit_lsr_mapping"].call(mapping)
            yield [{"role": "assistant", "content": ""}]

    monkeypatch.setattr(qwen_agent.agents, "FnCallAgent", FakeAgent)
    runner = QwenAgentSmetaRunner()
    monkeypatch.setattr(runner, "_structured_terminal_mapping", lambda **_kwargs: _mapping_args())

    result = runner.run_batch(
        [WORK], candidate_limit=4, max_turns=6, progress=None, user_request="сделай смету",
    )

    assert len(runs) == 2
    assert result["valid_model_rows"] == 1
    assert result["agent_trace"]["evidence_continuation_used"] is True
    assert len(result["selections"]["w1"]["candidate_evaluations"]) == 2


def test_qwen_recovery_retry_requires_evidence_for_models_existing_unbound_decision():
    session = workflow.SmetaNormToolSession([WORK], candidate_limit=4)
    session.query_trace.append({
        "work_id": "w1",
        "queries": ["монтаж блока", "установка блока ФСНБ"],
    })

    schema, allowed = _qwen_terminal_schema(session, {
        "ok": False,
        "errors": [{"work_id": "w1", "error": "invalid unbound_evidence"}],
    })

    row = schema["properties"]["rows"]["items"]
    assert row["properties"]["decision"]["enum"] == ["unbound"]
    assert "unbound_evidence" in row["required"]
    assert row["properties"]["unbound_evidence"]["properties"]["queries_used"]["items"]["enum"] == [
        "монтаж блока", "установка блока ФСНБ",
    ]
    assert allowed["w1"]["opened_norm_codes"] == []


def test_qwen_recovery_retry_requires_complete_existing_bind_decision():
    session = workflow.SmetaNormToolSession([WORK], candidate_limit=4)

    schema, _allowed = _qwen_terminal_schema(session, {
        "ok": False,
        "errors": [{"work_id": "w1", "error": "incomplete bind evidence"}],
    })

    row = schema["properties"]["rows"]["items"]
    assert row["properties"]["decision"]["enum"] == ["bind"]
    assert {
        "norm_code", "selection_kind", "applicability",
        "analog_limitations", "candidate_evaluations", "technology_check",
    }.issubset(row["required"])
    assert "required" in row["properties"]["technology_check"]


def test_qwen_resumes_tools_only_when_terminal_repair_needs_new_evidence():
    assert _requires_evidence_continuation({
        "errors": [{
            "details": [
                "candidate_evaluations requires opening at least one shown alternative before bind",
            ],
        }],
    }) is True
    assert _requires_evidence_continuation({
        "errors": [{"details": ["technology_check.conditions_checked must describe checked conditions"]}],
    }) is False


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
