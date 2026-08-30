import json

from tools import rag_dataset_story_acceptance as probe


def test_request_uses_exact_open_question_and_explicit_dataset_scope():
    payload = probe.chat_payload("dataset-1")

    assert payload["question"] == "Расскажи про датасет."
    assert payload["scope"] == {
        "scope_type": "dataset",
        "project_ids": [],
        "dataset_ids": ["dataset-1"],
    }
    assert payload["semantic_cache_enabled"] is False
    assert "expected" not in json.dumps(payload, ensure_ascii=False).casefold()


def test_not_ready_corpus_is_na_instead_of_quality_failure():
    report = probe.not_ready_report(
        "dataset-1",
        {"ready": False, "rrf_ready": False, "reason": "generation_coverage_incomplete"},
    )

    assert report["status"] == "N/A: corpus not ready"
    assert report["dataset_id"] == "dataset-1"
    assert report["readiness_reason"] == "generation_coverage_incomplete"
    assert "score" not in report


def test_report_keeps_answer_and_exact_model_call_evidence_trace():
    response = {
        "answer": "Описание без автоматической оценки.",
        "retrieval_trace": {
            "context_governor": {
                "calls": [
                    {
                        "purpose": "answer",
                        "sections": [
                            {
                                "kind": "evidence",
                                "objects": [
                                    {
                                        "object_id": "evidence:0",
                                        "text": "строка источника",
                                        "sha256": "a" * 64,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        },
    }

    report = probe.acceptance_report("dataset-1", response)

    assert report["answer"] == response["answer"]
    assert report["model_calls"] == response["retrieval_trace"]["context_governor"]["calls"]
    assert "passed" not in report
