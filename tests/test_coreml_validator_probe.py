import json
from argparse import Namespace

import pytest

pytest.importorskip("torch", reason="optional extra mac-mlx/coreml (нет на офлайн-CI)")

from tools import coreml_validator_probe as probe


def test_load_cases_accepts_golden_object(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "c1",
                        "expected": "VERIFIED",
                        "question": "q",
                        "context": "c",
                        "answer": "a",
                        "label_rationale": "kept for audit",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert probe.load_cases(path) == [
        {
            "id": "c1",
            "expected": "VERIFIED",
            "question": "q",
            "context": "c",
            "answer": "a",
            "label_rationale": "kept for audit",
        }
    ]


def test_threshold_sweep_maps_low_confidence_to_no_data():
    rows = [
        {
            "id": "verified_low",
            "backend": "coreml",
            "expected": "NO_DATA",
            "actual": "VERIFIED",
            "status": "OK",
            "ok": False,
            "score": 0.51,
            "latency_sec": 0.01,
        }
    ]

    sweep = probe._threshold_sweep(rows, [0.0, 0.6])

    assert sweep[0]["accuracy"] == 0.0
    assert sweep[1]["accuracy"] == 1.0
    assert sweep[1]["threshold"] == 0.6


def test_compare_skips_missing_coreml_package(tmp_path):
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "empty",
                        "expected": "NO_DATA",
                        "question": "q",
                        "context": "",
                        "answer": "a",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = probe.compare_backends(
        Namespace(
            cases=str(cases),
            use_rag_context_windows=False,
            materialized_cases="",
            backends="rules,coreml",
            coreml_model=str(tmp_path / "missing.mlpackage"),
            require_coreml=False,
            tokenizer="unused",
            local_files_only=True,
            compute_units="cpu_only",
            labels="ENTAILMENT,NEUTRAL,CONTRADICTION",
            seq_len=512,
            attention_mask_rank=2,
            context_mode="windows",
            pair_mode="answer",
            entailment_threshold=0.8,
            contradiction_threshold=0.6,
            decision_margin=0.05,
            mlx_url="http://127.0.0.1:8080",
            qdrant_url="http://127.0.0.1:6333",
            embed_model="",
            timeout=1.0,
            thresholds="0,0.6",
            output="",
        )
    )

    assert result["summary"]["rules"]["accuracy"] == 1.0
    assert result["summary"]["coreml"]["skipped"] == 1
    assert result["rows"][1]["status"] == "SKIPPED"
