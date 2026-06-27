"""W2.7 — классификация исхода ретрива для замера словарного покрытия weak."""

from __future__ import annotations

from tools.measure_weak_retry import classify_weak_case


def test_strong_no_retry():
    assert classify_weak_case("strong", 0) == "strong"
    assert classify_weak_case("ok", 0) == "strong"


def test_closed_by_dictionary():
    # был weak, словарный ретрай поднял качество (retry_count>0, финал не weak)
    assert classify_weak_case("strong", 1) == "closed_by_dict"
    assert classify_weak_case("ok", 2) == "closed_by_dict"


def test_residual_weak():
    # остался weak — кандидат на LLM-ступень, независимо от ретрая
    assert classify_weak_case("weak", 0) == "residual_weak"
    assert classify_weak_case("weak", 1) == "residual_weak"


def test_case_insensitive_status():
    assert classify_weak_case("WEAK", 0) == "residual_weak"
    assert classify_weak_case("Weak", 3) == "residual_weak"


def test_none_retry_count_safe():
    assert classify_weak_case("strong", None) == "strong"  # type: ignore[arg-type]
