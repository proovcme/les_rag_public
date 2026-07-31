from __future__ import annotations

import os

import pytest

from tools.smeta_model_quality_benchmark import (
    _model_environment,
    _parse_profiles,
    analyze_result,
)


def test_profiles_require_distinct_explicit_model_labels():
    assert _parse_profiles(["qwen=qwen3.5:9b", "gemma=gemma4:12b"]) == [
        ("qwen", "qwen3.5:9b"),
        ("gemma", "gemma4:12b"),
    ]
    with pytest.raises(ValueError, match="duplicate profile"):
        _parse_profiles(["local=a", "local=b"])
    with pytest.raises(ValueError, match="at least two"):
        _parse_profiles(["local=a"])


def test_model_environment_is_identical_and_restored(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "before")
    with _model_environment(
        "gemma4:12b",
        base_url="http://127.0.0.1:11434",
        seed=17,
        num_ctx=32768,
        tool_max_tokens=1800,
        mapping_max_tokens=8000,
    ):
        assert os.environ["LES_SMETA_DOCUMENT_PROVIDER"] == "ollama"
        assert os.environ["LES_SMETA_DOCUMENT_MODEL"] == "gemma4:12b"
        assert os.environ["OLLAMA_MODEL"] == "gemma4:12b"
        assert os.environ["LES_SMETA_DOCUMENT_SEED"] == "17"
        assert os.environ["LES_SMETA_DOCUMENT_THINK"] == "false"
    assert os.environ["OLLAMA_MODEL"] == "before"
    assert "LES_SMETA_DOCUMENT_MODEL" not in os.environ


def test_analysis_separates_calculation_integrity_from_professional_qrels():
    result = {
        "intake": {
            "work_items": [
                {
                    "work_id": "w1", "source_no": "10", "source_row": 5,
                    "title": "Монтаж шкафа", "unit": "шт", "quantity": 1,
                },
                {
                    "work_id": "w2", "source_no": "11", "source_row": 6,
                    "title": "Пусконаладка", "unit": "шт", "quantity": 1,
                },
                {
                    "work_id": "w3", "source_no": "12", "source_row": 7,
                    "title": "Неясная работа", "unit": "м", "quantity": 0,
                },
            ],
        },
        "selections": {
            "w1": {"norm_code": "ГЭСНм08-01-001-01", "norm_family": "ГЭСНм"},
            "w2": {"covered_by_work_id": "w1", "reason": "в составе"},
        },
        "catalog_trace": [
            {"work_id": "w1", "level": "family"},
            {"work_id": "w1", "level": "collection"},
        ],
        "query_trace": [
            {"work_id": "w1", "filters": {"base_types": ["ГЭСНм"], "collections": ["08"]}},
        ],
        "model_trace": [
            {
                "assistant": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search_norms_batch",
                                "arguments": {"items": [{"work_id": "w1", "queries": ["шкаф"]}]},
                            },
                        },
                        {
                            "function": {
                                "name": "search_norms_batch",
                                "arguments": {"items": [{"work_id": "w1", "queries": ["шкаф"]}]},
                            },
                        },
                    ],
                },
            },
        ],
        "lsr": {
            "sections": [
                {
                    "positions": [
                        {
                            "work_id": "w1", "code": "ГЭСНм08-01-001-01",
                            "source_quantity": 1.0, "source_unit": "шт",
                            "norm_source_integrity": {"source_ref": "fsnb.sqlite#guid=1"},
                        },
                    ],
                },
            ],
            "coverage": [
                {"work_id": "w1", "status": "accepted"},
                {"work_id": "w2", "status": "covered_by"},
            ],
            "blockers": [{"code": "norm_selection_required", "work_id": "w3"}],
        },
    }
    analysis = analyze_result(
        result,
        row_timings={"w1": {"elapsed_sec": 4.25}},
        qrels={
            "schema": "les.smeta.qrels.v1",
            "rows": {
                "10": {
                    "acceptable_norm_codes": ["ГЭСНм08-01-001-01"],
                    "expected_family": "ГЭСНм",
                },
            },
        },
    )

    rows = {row["work_id"]: row for row in analysis["rows"]}
    assert rows["w1"]["status"] == "calculated"
    assert rows["w1"]["norm_correctness"] == "correct"
    assert rows["w1"]["route_correctness"] == "correct"
    assert rows["w1"]["route_structural"] == "verified"
    assert rows["w1"]["unit_integrity"] is True
    assert rows["w1"]["volume_integrity"] is True
    assert rows["w1"]["provenance_integrity"] is True
    assert rows["w1"]["tool_calls"] == 2
    assert rows["w1"]["tool_repeats"] == 1
    assert rows["w1"]["elapsed_sec"] == 4.25
    assert rows["w2"]["status"] == "calculated"
    assert rows["w2"]["norm_correctness"] == "not_adjudicated"
    assert rows["w3"]["status"] == "missing"
    assert analysis["summary"]["empty_or_zero_rows"] == 1
    assert analysis["summary"]["professionally_adjudicated_rows"] == 1
