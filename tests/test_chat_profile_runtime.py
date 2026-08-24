from __future__ import annotations

import inspect

from proxy.routers import chat as chat_router
from proxy.routers.chat import ChatRequest
from proxy.services.chat_evidence_application_service import (
    profile_research_rounds,
    profile_system_prompt,
    profile_temperature,
)
from proxy.services.profile_resolver import resolve
from proxy.services.smeta_chat_adapter_service import _smeta_direct_light_system_prompt
from proxy.services.tool_harness_service import ToolHarness


def _snapshot(mode: str = "agent") -> dict:
    return {
        "schema": "les.chat_profile_snapshot.v1",
        "revision_id": f"user:profile:{mode}:1",
        "mode": mode,
        "prompt_text": "ПРОМПТ ПРОФИЛЯ",
        "skill_text": "# СКИЛЛ ПРОФИЛЯ\n\nВыполняй исследование.",
        "tools": ["dataset_map"],
        "prompt_sha256": "a" * 64,
        "skill_sha256": "b" * 64,
    }


def test_profile_resolver_defaults_to_agent_and_never_returns_auto():
    assert resolve(mode=None, question="обычная задача").profile_id == "agent"
    assert resolve(mode="text", question="обычная задача").profile_id == "agent"
    assert resolve(mode="rag", question="найди документ").profile_id == "search"
    assert resolve(mode="smeta", question="подбери нормы").profile_id == "estimator"
    assert resolve(mode="doc_review", question="проверь проект").profile_id == "engineer"


def test_chat_request_accepts_explicit_profile_revision_application():
    req = ChatRequest(
        question="применить профиль",
        mode="search",
        profile_revision_id="user:profile:search:1",
        apply_profile_revision=True,
    )

    assert req.profile_revision_id == "user:profile:search:1"
    assert req.apply_profile_revision is True


def test_evidence_system_prompt_uses_exact_selected_prompt_and_skill():
    text = profile_system_prompt(_snapshot("search"), strict=False)

    assert text.startswith("ПРОМПТ ПРОФИЛЯ")
    assert "# СКИЛЛ ПРОФИЛЯ" in text
    assert "реальные материалы текущего запроса" in text


def test_tool_shortlist_cannot_escape_profile_allowlist():
    tools = ToolHarness().shortlist(
        "найди в интернете и прочитай файлы",
        mode="agent",
        allowed_tools=["dataset_map"],
        limit=10,
    )["tools"]

    assert [item["name"] for item in tools] == ["dataset_map"]


def test_estimator_visible_prompt_accepts_profile_prompt_and_skill():
    text = _smeta_direct_light_system_prompt(_snapshot("estimator"))

    assert text.startswith("ПРОМПТ ПРОФИЛЯ")
    assert "# СКИЛЛ ПРОФИЛЯ" in text
    assert "сметном модуле ЛЕС" in text


def test_profile_model_and_rag_policies_control_generation_and_research():
    snapshot = _snapshot()
    snapshot["model_policy"] = {"temperature": 0.6}
    snapshot["rag_policy"] = {"iterative": False}

    assert profile_temperature(snapshot, fallback=0.2) == 0.6
    assert profile_research_rounds(snapshot, configured=12) == 1

    snapshot["model_policy"] = {"temperature": 99}
    snapshot["rag_policy"] = {"iterative": True}
    assert profile_temperature(snapshot, fallback=0.2) == 2.0
    assert profile_research_rounds(snapshot, configured=12) == 12


def test_estimator_profile_uses_the_same_general_evidence_flow():
    source = inspect.getsource(chat_router._run_chat)

    assert 'if _PROFILE == "estimator"' not in source
    assert "run_smeta_direct_application(" not in source
    assert "run_smeta_document_application(" not in source
    assert "run_chat_evidence_application(" in source
