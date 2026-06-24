"""ProfileResolver — контракт маршрутизации (Codex §10.1A)."""

from proxy.services.profile_resolver import (
    MODE_TO_PROFILE,
    PROFILES,
    resolve,
)


def test_explicit_modes_map_to_profiles():
    cases = {
        "smeta": "object_estimate",
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


def test_no_mode_is_auto_router():
    r = resolve(mode=None, question="что такое стеснённость")
    assert r.profile_id == "auto"
    assert r.route_source == "llm_router"
    r2 = resolve(mode="", question="x")
    assert r2.profile_id == "auto"


def test_unknown_mode_falls_back_not_crash():
    r = resolve(mode="boGUS", question="x")
    assert r.profile_id == "auto"
    assert r.route_source == "fallback"


def test_mode_case_insensitive():
    assert resolve(mode="SMETA", question="x").profile_id == "object_estimate"
    assert resolve(mode=" Rag ", question="x").profile_id == "grounded_rag"


def test_every_mode_target_profile_exists():
    for pid in MODE_TO_PROFILE.values():
        assert pid in PROFILES


def test_profile_carries_declarative_policy():
    p = resolve(mode="smeta", question="x").profile
    assert p.executor == "deterministic"          # смета = 0 LLM
    assert p.validation_policy == "require_numeric_provenance"
    free = resolve(mode="free", question="x").profile
    assert free.grounded is False                  # вольный — без ретрива
    rag = resolve(mode="rag", question="x").profile
    assert rag.grounded is True                    # РАГ — заземлён


def test_as_trace_compact():
    t = resolve(mode="smeta", question="x").as_trace()
    assert t["profile_id"] == "object_estimate"
    assert t["route_source"] == "explicit_mode"
    assert t["executor"] == "deterministic"
