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


def test_normative_conditions_question_goes_straight_to_retrieval():
    decision = build_clarification_decision(
        "В каких случаях допускается не выполнять систему дымоудаления"
    )

    assert decision.needs_clarification is False
    assert decision.classification.dataset_filter == "NTD_FIRE"
    assert decision.classification.intent == "lookup"


def test_scoped_smoke_control_question_goes_straight_to_retrieval():
    decision = build_clarification_decision(
        "Область: противодымная вентиляция. Для каких помещений и проектных ситуаций допускается не предусматривать противодымную вентиляцию"
    )

    assert decision.needs_clarification is False
    assert decision.classification.dataset_filter == "NTD_FIRE"
    assert decision.classification.intent == "lookup"


def test_explicit_filter_allows_broad_review():
    classification = classify_for_clarification(
        "проверь документы на нарушения",
        dataset_filter="NTD_FIRE",
    )

    assert classification.dataset_filter == "NTD_FIRE"
    assert classification.reasons == []
    assert classification.scope == "explicit"


def test_enumeration_pp87_query_is_lookup_not_blocked():
    # Регрессия: «Перечень разделов проектной документации по ПП87» — каноничный
    # перечислительный запрос. Слово «документации» (токен broad-обзора «документац»)
    # НЕ должно утягивать его в broad_review и блокировать через NEEDS_CLARIFICATION.
    decision = build_clarification_decision("Перечень разделов проектной документации по ПП87")

    assert decision.needs_clarification is False
    assert decision.classification.intent == "lookup"
    assert decision.classification.reasons == []


def test_enumeration_intent_wins_over_broad_document_token():
    # «перечень/состав/список/перечисли …» определяет lookup даже рядом с «документац».
    for q in (
        "перечисли разделы проектной документации",
        "список разделов рабочей документации по объекту",
    ):
        assert classify_for_clarification(q).intent == "lookup", q


def test_table_query_does_not_need_clarification():
    decision = build_clarification_decision("посчитай общую стоимость по всем строкам сметы")

    assert decision.needs_clarification is False
    assert decision.classification.dataset_filter == "TABLE"
    assert decision.classification.reasons == []


@pytest.mark.asyncio
async def test_chat_asks_to_narrow_scope_before_retrieval():
    # v0.22: проектный запрос при scope=all («проверь все документы») перехватывает
    # scope_clarification РАНЬШЕ старого build_clarification — и не молча ищет весь корпус.
    # Инвариант сохранён: ретрив не запускается до выбора области. Раньше тест ждал
    # NEEDS_CLARIFICATION (v0.21) — это поведение superseded scope_clarification (v0.22).
    class BackendThatMustNotRun:
        async def list_datasets(self):
            raise AssertionError("list_datasets should not run before scope is chosen")

        async def retrieve(self, *args, **kwargs):
            raise AssertionError("retrieve should not run before scope is chosen")

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

    assert response["crag_status"] == "DETERMINISTIC"
    assert response["sources"] == []
    assert "област" in response["answer"].lower()        # просит выбрать область поиска
    route = response["query_route"]
    assert route["channel"] == "scope_clarification"
    # #2: query_route несёт честный profile-трейс (auto-путь, regex-канал — не «pending»).
    assert route["profile"]["channel"] == "scope_clarification"
    assert route["profile"]["route_source"] == "regex"
    assert route["profile"]["profile_id"] == "auto"


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
async def test_chat_generation_paused_under_memory_pressure(monkeypatch):
    monkeypatch.setenv("LES_CHAT_MIN_FREE_GB", "8.0")
    monkeypatch.setenv("LES_CHAT_MAX_SWAP_PCT", "60.0")

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


@pytest.mark.asyncio
async def test_chat_generation_paused_during_dispatcher_reindex(monkeypatch):
    class BackendThatMustNotRun:
        async def retrieve(self, *args, **kwargs):
            raise AssertionError("retrieve should not run while guarded reindex is active")

    class FakeDispatcher:
        def __init__(self, **kwargs):
            pass

        def reindex_status_payload(self):
            return {"running": True}

    monkeypatch.setattr(chat_router, "RuntimeDispatcher", FakeDispatcher)
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
            metrics_cache={"ram_free_gb": 12.0, "swap_pct": 0.0},
        )
    )

    with pytest.raises(chat_router.HTTPException) as exc:
        await chat_router.chat(
            chat_router.ChatRequest(question="ширина путей эвакуации", dataset_filter="NTD_FIRE"),
            _user=object(),
        )

    assert exc.value.status_code == 409
    assert "active_jobs=1" in exc.value.detail


@pytest.mark.asyncio
async def test_chat_returns_effective_dataset_filter_on_no_data(monkeypatch):
    class EmptyBackend:
        collection_name = "test_collection"

        async def list_datasets(self):
            return [SimpleNamespace(id="fire-id", name="NTD_FIRE_Index")]

        async def retrieve(self, *args, **kwargs):
            return []

    class FakeDispatcher:
        def __init__(self, **kwargs):
            pass

        def reindex_status_payload(self):
            return {"running": False}

    monkeypatch.setattr(chat_router, "RuntimeDispatcher", FakeDispatcher)
    chat_router.set_chat_state(
        chat_router.ChatRouterState(
            rag_backend=EmptyBackend(),
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
            metrics_cache={"ram_free_gb": 12.0, "swap_pct": 0.0},
        )
    )

    response = await chat_router.chat(
        chat_router.ChatRequest(
            question="Какая ширина путей эвакуации?",
            dataset_filter="NTD_FIRE",
            semantic_cache_enabled=False,
        ),
        _user=object(),
    )

    assert response["crag_status"] == "NO_DATA"
    assert response["effective_dataset_filter"] == "NTD_FIRE"
    assert response["query_route"]["dataset_filter"] == "NTD_FIRE"
