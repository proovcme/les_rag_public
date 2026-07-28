import json

from tools import rag_golden_set as golden


def test_request_payload_includes_filter_when_present():
    case = golden.GoldenCase(id="c1", question="вопрос", dataset_filter="NTD", top_k=6)

    assert golden.request_payload(case) == {
        "question": "вопрос",
        "dataset_filter": "NTD",
        "top_k": 6,
    }


def test_evaluate_response_passes_when_terms_and_source_match():
    case = golden.GoldenCase(
        id="evac",
        question="ширина путей",
        min_chunks=1,
        min_top_score=0.5,
        must_find=("эвакуац",),
        source_any=("1.13130",),
    )
    response = {
        "chunks": [
            {
                "score": 0.73,
                "doc_name": "СП 1.13130.2020.docx",
                "preview": "Минимальная ширина назначается по таблице.",
                "expanded_preview": "Минимальная ширина эвакуационных путей назначается по таблице.",
            }
        ]
    }

    result = golden.evaluate_response(case, response, elapsed=0.2)

    assert result.ok is True
    assert result.chunks == 1
    assert result.top_score == 0.73
    assert result.sources == ("СП 1.13130.2020.docx",)


def test_evaluate_response_reports_missing_expected_evidence():
    case = golden.GoldenCase(
        id="pp87",
        question="разделы",
        expected_route_filter="GKRF",
        min_chunks=2,
        min_top_score=0.6,
        must_find=("раздел", "проект"),
        source_any=("87",),
        source_top_any=("Постановление",),
        source_top_k=2,
    )
    response = {
        "query_route": {"dataset_filter": "NTD"},
        "chunks": [
            {
                "score": 0.41,
                "doc_name": "СП 3.13130.docx",
                "preview": "Требования к системам оповещения.",
            }
        ]
    }

    result = golden.evaluate_response(case, response)

    assert result.ok is False
    assert "chunks=1 < 2" in result.detail
    assert "top_score=0.410 < 0.600" in result.detail
    assert "missing terms: раздел, проект" in result.detail
    assert "missing source hint: 87" in result.detail
    assert "missing top-2 source hint: Постановление" in result.detail
    assert "route=NTD != GKRF" in result.detail


def test_evaluate_response_checks_expected_retrieval_quality():
    case = golden.GoldenCase(
        id="missing-source",
        question="широкий запрос по разнородному корпусу",
        min_chunks=1,
        expected_quality_status="weak",
    )

    passed = golden.evaluate_response(case, {
        "retrieval_trace": {"quality_status": "weak"},
        "chunks": [{"score": 0.31, "doc_name": "neighbour.pdf", "preview": "смежный том"}],
    })
    failed = golden.evaluate_response(case, {
        "retrieval_trace": {"quality_status": "good"},
        "chunks": [{"score": 0.31, "doc_name": "neighbour.pdf", "preview": "смежный том"}],
    })

    assert passed.ok is True
    assert failed.ok is False
    assert "quality=good != weak" in failed.detail


def test_load_cases_accepts_cases_object(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "c1",
                        "question": "q",
                        "dataset_filter": "NTD",
                        "expected_route_filter": "NTD_FIRE",
                        "must_find": ["term"],
                        "source_any": ["source"],
                        "source_top_any": ["top-source"],
                        "source_top_k": 2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = golden.load_cases(path)

    assert cases == [
        golden.GoldenCase(
            id="c1",
            question="q",
            dataset_filter="NTD",
            expected_route_filter="NTD_FIRE",
            must_find=("term",),
            must_find_same_chunk=True,
            source_any=("source",),
            source_top_any=("top-source",),
            source_top_k=2,
        )
    ]


def test_expected_terms_do_not_pass_from_filename_or_cross_chunk_scatter():
    case = golden.GoldenCase(
        id="strict-content",
        question="q",
        must_find=("вентиляц", "условие"),
    )

    filename_only = golden.evaluate_response(case, {
        "chunks": [{"doc_name": "Вентиляция.docx", "preview": "условие применения"}],
    })
    scattered = golden.evaluate_response(case, {
        "chunks": [
            {"doc_name": "a.docx", "preview": "вентиляция"},
            {"doc_name": "b.docx", "preview": "условие"},
        ],
    })

    assert filename_only.ok is False
    assert "missing terms: вентиляц" in filename_only.detail
    assert scattered.ok is False
    assert "split across unrelated chunks" in scattered.detail


def test_source_verified_gate_rejects_cases_without_source_expectations():
    cases = [
        golden.GoldenCase(id="missing", question="q", must_find=("term",)),
        golden.GoldenCase(id="verified", question="q", source_any=("SP.pdf",)),
    ]

    assert golden.validate_source_verified_cases(cases) == ["missing"]


def test_native_rrf_gate_checks_successful_trace():
    case = golden.GoldenCase(id="rrf", question="q", min_chunks=1)
    chunk = {"score": 0.8, "doc_name": "source.pdf", "preview": "evidence"}

    passed = golden.evaluate_response(
        case,
        {"chunks": [chunk], "retrieval_trace": {"status": "ok", "fusion": "rrf"}},
        require_native_rrf=True,
    )
    failed = golden.evaluate_response(
        case,
        {"chunks": [chunk], "retrieval_trace": {"status": "degraded", "fusion": "dense"}},
        require_native_rrf=True,
    )

    assert passed.ok is True
    assert failed.ok is False
    assert "retrieval_status=degraded != ok" in failed.detail
    assert "fusion=dense != rrf" in failed.detail
