"""ProfileResolver — контракт маршрутизации (Codex §10.1A)."""

from types import SimpleNamespace

import pytest

from proxy.services.profile_resolver import (
    CHANNEL_SOURCES,
    MODE_TO_PROFILE,
    PROFILES,
    confidence_for_source,
    resolve,
    route_source_for_channel,
)


def test_explicit_modes_map_to_profiles():
    cases = {
        "smeta": "estimator",
        "review": "engineer",
        "kp": "agent",
        "rag": "search",
        "free": "agent",
    }
    for mode, expect in cases.items():
        r = resolve(mode=mode, question="x")
        assert r.profile_id == expect
        assert r.route_source == "explicit_mode"
        assert r.confidence == 1.0


def test_no_mode_defaults_to_agent():
    r = resolve(mode=None, question="что такое стеснённость")
    assert r.profile_id == "agent"
    assert r.route_source == "fallback"
    assert r.confidence == 1.0
    assert r.channel is None
    r2 = resolve(mode="", question="x")
    assert r2.profile_id == "agent"
    assert r2.route_source == "fallback"


def test_unknown_mode_falls_back_not_crash():
    r = resolve(mode="boGUS", question="x")
    assert r.profile_id == "agent"
    assert r.route_source == "fallback"


def test_mode_case_insensitive():
    assert resolve(mode="SMETA", question="x").profile_id == "estimator"
    assert resolve(mode=" Rag ", question="x").profile_id == "search"


def test_every_mode_target_profile_exists():
    for pid in MODE_TO_PROFILE.values():
        assert pid in PROFILES


def test_profile_carries_declarative_policy():
    p = resolve(mode="smeta", question="x").profile
    assert p.executor == "cloud_large"            # смета = model-first tool loop
    assert p.validation_policy == "require_numeric_provenance"
    assert "search_norm" in p.tools and "add_position" in p.tools
    free = resolve(mode="free", question="x").profile
    assert free.grounded is True                   # legacy free → Agent с evidence
    rag = resolve(mode="rag", question="x").profile
    assert rag.grounded is True                    # РАГ — заземлён
    review = resolve(mode="review", question="x").profile
    assert review.executor == "router"             # visible final формулирует модель
    assert review.grounded is True
    assert review.validation_policy == "require_citations"


def test_as_trace_compact():
    t = resolve(mode="smeta", question="x").as_trace()
    assert t["profile_id"] == "estimator"
    assert t["route_source"] == "explicit_mode"
    assert t["executor"] == "cloud_large"
    # без refine канал/операция не протекают в trace
    assert "channel" not in t and "operation" not in t


# ── auto-путь: один контракт ProfileResolution для каскада/router/RAG (долг #2) ──

def test_route_source_for_channel_honest():
    # команда / model-tool-selector / retrieval-intent / неизвестный legacy-канал → fallback
    assert route_source_for_channel("command") == "command"
    assert route_source_for_channel("agent") == "llm_router"
    for ch in ("table", "mail", "field", "rag"):
        assert route_source_for_channel(ch) == "keyword", ch
    for ch in ("glossary", "registry", "tasks", "memory", "decision", "project_summary"):
        assert route_source_for_channel(ch) == "fallback", ch
    assert route_source_for_channel("does_not_exist") == "fallback"
    assert route_source_for_channel("") == "fallback"
    assert route_source_for_channel("RAG") == "keyword"   # регистронезависимо


def test_every_known_channel_maps_to_valid_source():
    valid = {"explicit_mode", "command", "regex", "keyword", "llm_router", "fallback", "pending"}
    for ch, src in CHANNEL_SOURCES.items():
        assert src in valid, (ch, src)


def test_confidence_ladder():
    # явный режим/команда > regex > llm_router > keyword > fallback/pending
    c = confidence_for_source
    assert c("command") == 1.0 == c("explicit_mode")
    assert c("regex") > c("llm_router") > c("keyword") > c("fallback")
    assert c("pending") == 0.0
    assert c("unknown") == 0.0


def test_refine_keeps_profile_but_records_model_tool_channel():
    # Default Agent remains explicit while the concrete channel is recorded.
    r = resolve(mode=None, question="что такое ОЖР")
    out = r.refine(route_source=route_source_for_channel("agent"),
                   channel="agent", operation="term_explain")
    assert out is r                                  # чейнится, мутирует
    assert r.profile_id == "agent"
    assert r.route_source == "llm_router"
    assert r.channel == "agent" and r.operation == "term_explain"
    assert r.confidence == confidence_for_source("llm_router")
    t = r.as_trace()
    assert t["channel"] == "agent" and t["operation"] == "term_explain"
    assert t["route_source"] == "llm_router" and t["profile_id"] == "agent"


def test_refine_rag_fallback_vs_keyword():
    # default_rag (ничего не поймало) → честный fallback; пойманный по словарю → keyword.
    r = resolve(mode=None, question="x")
    r.refine(route_source="fallback", channel="rag", operation="default_rag")
    assert r.route_source == "fallback" and r.confidence == 0.0
    r2 = resolve(mode=None, question="y")
    r2.refine(route_source="keyword", channel="rag", operation="hvac_keyword")
    assert r2.route_source == "keyword" and r2.confidence > 0.0


def test_refine_explicit_confidence_override():
    r = resolve(mode=None, question="x").refine(route_source="llm_router", channel="agent",
                                                confidence=0.42, reason="router picked tool")
    assert r.confidence == 0.42
    assert "router picked tool" in r.reasons


# ── end-to-end: query_route.profile честен и протянут в каждый ответ (#2) ──

def _mock_chat_state(chat_router):
    """Мокнутый ChatRouterState без пользовательского корпуса."""
    class _Backend:
        async def list_datasets(self):
            return []

        async def retrieve(self, *a, **k):
            raise AssertionError("retrieve must not run for a deterministic channel")

    chat_router.set_chat_state(chat_router.ChatRouterState(
        rag_backend=_Backend(), llm_semaphore=SimpleNamespace(_value=1),
        crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
        chat_metrics={"latency_search": [], "latency_gen": [], "tokens": [],
                      "crag_pass": 0, "crag_fail": 0},
        reranker_available=False, reranker_cls=None, current_mode={"mode": "chat"}))


def test_professional_legacy_channels_cannot_claim_deterministic_route():
    for channel in ("glossary", "registry", "tasks", "memory", "decision", "project_summary"):
        assert channel not in CHANNEL_SOURCES
        assert route_source_for_channel(channel) == "fallback"


@pytest.mark.asyncio
async def test_query_route_carries_profile_for_explicit_mode(monkeypatch):
    from proxy.routers import chat as chat_router
    _mock_chat_state(chat_router)

    async def fake_evidence(request, _runtime, _boundary):
        assert request.profile_snapshot["mode"] == "estimator"
        return {
            "answer": "offline explicit-mode probe",
            "query_route": request.query_route_payload,
            "sources": [],
        }

    monkeypatch.setattr(chat_router, "run_chat_evidence_application", fake_evidence)
    resp = await chat_router.chat(
        chat_router.ChatRequest(question="что такое ОЖР", mode="estimator"), _user=object())
    prof = resp["query_route"]["profile"]
    assert prof["profile_id"] == "estimator"
    assert prof["route_source"] == "explicit_mode"
    assert prof["executor"] == "cloud_large"
    assert resp["query_route"]["profile_snapshot"]["mode"] == "estimator"


@pytest.mark.asyncio
async def test_default_agent_does_not_auto_hijack_work_estimate(monkeypatch):
    from proxy.routers import chat as chat_router
    _mock_chat_state(chat_router)

    called = {"mode": ""}

    async def fake_evidence(request, _runtime, _boundary):
        called["mode"] = request.profile_snapshot["mode"]
        return {
            "answer": "ordinary agent RAG",
            "query_route": request.query_route_payload,
            "sources": [],
        }

    monkeypatch.setattr(chat_router, "run_chat_evidence_application", fake_evidence)
    monkeypatch.setattr(
        chat_router,
        "_harness_complete",
        lambda *_a, **_k: pytest.fail("legacy harness final must not run"),
    )

    resp = await chat_router.chat(
        chat_router.ChatRequest(
            question=(
                "регион санкт-петербург, нужно рассчитать сметную стоимость работ по "
                "разработке траншеи вручную, объем выработки грунта 200 м3"
            )
        ),
        _user=object(),
    )

    prof = resp["query_route"]["profile"]
    assert prof["profile_id"] == "agent"
    assert called["mode"] == "agent"
