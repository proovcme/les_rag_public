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
                "preview": "Минимальная ширина эвакуационных путей назначается по таблице.",
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
        min_chunks=2,
        min_top_score=0.6,
        must_find=("раздел", "проект"),
        source_any=("87",),
    )
    response = {
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
                        "must_find": ["term"],
                        "source_any": ["source"],
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
            must_find=("term",),
            source_any=("source",),
        )
    ]
