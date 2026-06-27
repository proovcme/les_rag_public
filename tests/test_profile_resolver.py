"""ProfileResolver — контракт маршрутизации (Codex §10.1A)."""

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
        "smeta": "estimate_harness",
        "review": "normcontrol",
        "kp": "kp_stub",
        "rag": "grounded_rag",
        "free": "free_llm",
    }
    for mode, expect in cases.items():
        r = resolve(mode=mode, question="x")
        assert r.profile_id == expect
        assert r.route_source == "explicit_mode"
        assert r.confidence == 1.0


def test_no_mode_is_auto_pending():
    # без режима резолвер НЕ угадывает источник (это была бы ложь в trace): профиль auto,
    # источник pending — конкретный канал проставит конвейер через refine.
    r = resolve(mode=None, question="что такое стеснённость")
    assert r.profile_id == "auto"
    assert r.route_source == "pending"
    assert r.confidence == 0.0
    assert r.channel is None
    r2 = resolve(mode="", question="x")
    assert r2.profile_id == "auto"
    assert r2.route_source == "pending"


def test_unknown_mode_falls_back_not_crash():
    r = resolve(mode="boGUS", question="x")
    assert r.profile_id == "auto"
    assert r.route_source == "fallback"


def test_mode_case_insensitive():
    assert resolve(mode="SMETA", question="x").profile_id == "estimate_harness"
    assert resolve(mode=" Rag ", question="x").profile_id == "grounded_rag"


def test_every_mode_target_profile_exists():
    for pid in MODE_TO_PROFILE.values():
        assert pid in PROFILES


def test_profile_carries_declarative_policy():
    p = resolve(mode="smeta", question="x").profile
    assert p.executor == "cloud_large"            # смета = model-first tool loop
    assert p.validation_policy == "require_numeric_provenance"
    assert "search_norm" in p.tools and "add_position" in p.tools
    free = resolve(mode="free", question="x").profile
    assert free.grounded is False                  # вольный — без ретрива
    rag = resolve(mode="rag", question="x").profile
    assert rag.grounded is True                    # РАГ — заземлён


def test_as_trace_compact():
    t = resolve(mode="smeta", question="x").as_trace()
    assert t["profile_id"] == "estimate_harness"
    assert t["route_source"] == "explicit_mode"
    assert t["executor"] == "cloud_large"
    # без refine канал/операция не протекают в trace
    assert "channel" not in t and "operation" not in t


# ── auto-путь: один контракт ProfileResolution для каскада/router/RAG (долг #2) ──

def test_route_source_for_channel_honest():
    # команда / regex-каналы / llm-router / keyword-каскад / неизвестный канал → fallback
    assert route_source_for_channel("command") == "command"
    for ch in ("glossary", "registry", "tasks", "memory", "scope_clarification", "decision"):
        assert route_source_for_channel(ch) == "regex", ch
    assert route_source_for_channel("agent") == "llm_router"
    for ch in ("table", "mail", "rag", "reconcile", "spec_to_bor", "project_summary", "outline"):
        assert route_source_for_channel(ch) == "keyword", ch
    assert route_source_for_channel("does_not_exist") == "fallback"
    assert route_source_for_channel("") == "fallback"
    assert route_source_for_channel("GLOSSARY") == "regex"   # регистронезависимо


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


def test_refine_keeps_profile_but_records_channel():
    # auto-путь: профиль НЕ меняется (auto остаётся auto), фиксируется КАК принят маршрут.
    r = resolve(mode=None, question="что такое ОЖР")
    out = r.refine(route_source=route_source_for_channel("glossary"),
                   channel="glossary", operation="term_explain")
    assert out is r                                  # чейнится, мутирует
    assert r.profile_id == "auto"                    # профиль не подменён
    assert r.route_source == "regex"
    assert r.channel == "glossary" and r.operation == "term_explain"
    assert r.confidence == confidence_for_source("regex")
    t = r.as_trace()
    assert t["channel"] == "glossary" and t["operation"] == "term_explain"
    assert t["route_source"] == "regex" and t["profile_id"] == "auto"


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
    """Мокнутый ChatRouterState: ретрив падает с AssertionError → доказывает, что
    детерминированный канал ответил ДО ретрива."""
    from types import SimpleNamespace

    class _Backend:
        async def list_datasets(self):
            raise AssertionError("retrieval must not run for a deterministic channel")

        async def retrieve(self, *a, **k):
            raise AssertionError("retrieve must not run for a deterministic channel")

    chat_router.set_chat_state(chat_router.ChatRouterState(
        rag_backend=_Backend(), llm_semaphore=SimpleNamespace(_value=1),
        crag_stats={"verified": 0, "no_data": 0, "hallucination": 0},
        chat_metrics={"latency_search": [], "latency_gen": [], "tokens": [],
                      "crag_pass": 0, "crag_fail": 0},
        reranker_available=False, reranker_cls=None, current_mode={"mode": "chat"}))


@pytest.mark.asyncio
async def test_query_route_carries_honest_profile_for_glossary():
    # auto-путь, regex-канал «glossary»: trace говорит ПРАВДУ о том, как принят маршрут,
    # а не остаётся «pending»/«llm_router». Это и есть закрытие долга #2 (один контракт).
    from proxy.routers import chat as chat_router
    _mock_chat_state(chat_router)
    resp = await chat_router.chat(
        chat_router.ChatRequest(question="что такое ОЖР"), _user=object())
    assert resp["crag_status"] == "DETERMINISTIC"
    prof = resp["query_route"]["profile"]
    assert prof["profile_id"] == "auto"
    assert prof["route_source"] == "regex"
    assert prof["channel"] == "glossary"


@pytest.mark.asyncio
async def test_query_route_carries_profile_for_explicit_mode(monkeypatch):
    # явный режим «Смета» → профиль estimate_harness, источник explicit_mode. В тесте петлю
    # закрываем сразу, чтобы не дергать живую LLM.
    from proxy.routers import chat as chat_router
    _mock_chat_state(chat_router)
    monkeypatch.setattr(chat_router, "_harness_complete", lambda messages: '{"final": true}')
    resp = await chat_router.chat(
        chat_router.ChatRequest(question="что такое ОЖР", mode="smeta"), _user=object())
    prof = resp["query_route"]["profile"]
    assert prof["profile_id"] == "estimate_harness"
    assert prof["route_source"] == "explicit_mode"
    assert prof["executor"] == "cloud_large"
