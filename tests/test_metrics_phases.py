"""W0.1: пофазные метрики латентности — офлайн-тесты сводки."""

from proxy.routers.runtime import summarize_phases


def test_summarize_phases_empty():
    assert summarize_phases([]) == {}


def test_summarize_phases_averages():
    phases = [
        {"retrieval": 1.0, "generation": 2.0, "validation": 0.5},
        {"retrieval": 3.0, "generation": 4.0, "validation": 1.5},
    ]
    result = summarize_phases(phases)
    assert result["retrieval"] == 2.0
    assert result["generation"] == 3.0
    assert result["validation"] == 1.0


def test_summarize_phases_ignores_non_numeric_and_missing_keys():
    phases = [
        {"retrieval": 1.0, "note": "warm"},
        {"retrieval": 2.0, "context": 0.4},
    ]
    result = summarize_phases(phases)
    assert result["retrieval"] == 1.5
    assert result["context"] == 0.4
    assert "note" not in result


def test_summarize_phases_rounds_to_ms():
    result = summarize_phases([{"generation": 1.23456}])
    assert result["generation"] == 1.235
