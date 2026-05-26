from types import SimpleNamespace

import pytest

from proxy.routers import chat as chat_router
from proxy.services.clarification_service import build_clarification_decision, classify_for_clarification


def test_broad_review_without_domain_needs_clarification():
    decision = build_clarification_decision("проверь все документы")

    assert decision.needs_clarification is True
    assert "broad_review_without_domain" in decision.classification.reasons
    assert "missing_scope" in decision.classification.reasons
    assert decision.suggested_filters == ["NTD", "TABLE_SMETA", "GKRF"]
    assert len(decision.questions) >= 2


def test_routed_lookup_goes_straight_to_retrieval():
    decision = build_clarification_decision("какое сечение кабеля заземления по ПУЭ")

    assert decision.needs_clarification is False
    assert decision.classification.dataset_filter == "NTD_ELECTRICAL"
    assert decision.questions == []


def test_explicit_filter_allows_broad_review():
    classification = classify_for_clarification(
        "проверь документы на нарушения",
        dataset_filter="NTD_FIRE",
    )

    assert classification.dataset_filter == "NTD_FIRE"
    assert classification.reasons == []
    assert classification.scope == "explicit"


@pytest.mark.asyncio
async def test_chat_returns_clarification_before_retrieval():
    class BackendThatMustNotRun:
        async def list_datasets(self):
            raise AssertionError("list_datasets should not run for clarification")

        async def retrieve(self, *args, **kwargs):
            raise AssertionError("retrieve should not run for clarification")

    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=BackendThatMustNotRun(),
            llm_semaphore=SimpleNamespace(_value=1),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "chat"},
        )
    )

    response = await chat_router.chat(
        chat_router.ChatRequest(question="проверь все документы"),
        _user=object(),
    )

    assert response["crag_status"] == "NEEDS_CLARIFICATION"
    assert response["sources"] == []
    assert response["clarifying_questions"] == response["clarification"]["questions"]
    assert response["suggested_filters"] == ["NTD", "TABLE_SMETA", "GKRF"]


@pytest.mark.asyncio
async def test_chat_generation_paused_in_indexing_mode():
    class BackendThatMustNotRun:
        async def retrieve(self, *args, **kwargs):
            raise AssertionError("retrieve should not run while indexing mode is active")

    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=BackendThatMustNotRun(),
            llm_semaphore=SimpleNamespace(_value=1),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "indexing"},
        )
    )

    with pytest.raises(chat_router.HTTPException) as exc:
        await chat_router.chat(
            chat_router.ChatRequest(question="ширина путей эвакуации", dataset_filter="NTD_FIRE"),
            _user=object(),
        )

    assert exc.value.status_code == 409
    assert "Indexing mode is active" in exc.value.detail


@pytest.mark.asyncio
async def test_chat_generation_paused_under_memory_pressure():
    class BackendThatMustNotRun:
        async def retrieve(self, *args, **kwargs):
            raise AssertionError("retrieve should not run while memory guard is closed")

    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=BackendThatMustNotRun(),
            llm_semaphore=SimpleNamespace(_value=1),
            crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
            chat_metrics={
                "latency_search": [],
                "latency_gen": [],
                "tokens": [],
                "crag_pass": 0,
                "crag_fail": 0,
            },
            reranker_available=False,
            reranker_cls=None,
            current_mode={"mode": "chat"},
            metrics_cache={"ram_free_gb": 5.0, "swap_pct": 86.0},
        )
    )

    with pytest.raises(chat_router.HTTPException) as exc:
        await chat_router.chat(
            chat_router.ChatRequest(question="ширина путей эвакуации", dataset_filter="NTD_FIRE"),
            _user=object(),
        )

    assert exc.value.status_code == 503
    assert "ram_free_gb=5.0 < 8.0" in exc.value.detail
    assert "swap_pct=86.0 > 60.0" in exc.value.detail
