import json

from tools import rag_eval_report as report


def test_record_from_json_keeps_ragas_relevant_fields():
    record = report.record_from_json(
        {
            "case_id": "c1",
            "mode": "chat",
            "ok": True,
            "detail": "passed",
            "elapsed": 1.2,
            "question": "q",
            "answer": "a",
            "reference_answer": "ref",
            "expected_terms": ["term"],
            "source_hints": ["source"],
            "crag_status": "VERIFIED",
        }
    )

    assert record.case_id == "c1"
    assert record.expected_terms == ("term",)
    assert record.source_hints == ("source",)


def test_summarize_counts_crag_guard_and_ragas_ready():
    records = [
        report.EvalRecord(
            case_id="c1",
            mode="chat",
            ok=True,
            detail="passed",
            elapsed=1.0,
            crag_status="VERIFIED",
            question="q",
            answer="a",
            reference_answer="ref",
        ),
        report.EvalRecord(
            case_id="c2",
            mode="chat",
            ok=True,
            detail="GUARDED_STOP",
            elapsed=0.1,
            guarded_stop=True,
        ),
        report.EvalRecord(case_id="c3", mode="retrieval", ok=False, detail="missing", elapsed=2.0),
    ]

    summary = report.summarize(records)

    assert summary.total == 3
    assert summary.ok == 2
    assert summary.failed == 1
    assert summary.guarded == 1
    assert summary.ragas_ready == 1
    assert summary.crag == {"VERIFIED": 1}


def test_load_records_accepts_jsonl_and_legacy_human_lines(tmp_path):
    path = tmp_path / "baseline.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"case_id": "c1", "mode": "chat", "ok": True, "detail": "passed", "elapsed": 1.0}),
                "[OK  ] chat      c2                            2.50s chunks=1  top=0.000 crag=VERIFIED passed",
            ]
        ),
        encoding="utf-8",
    )

    records = report.load_records([path])

    assert [record.case_id for record in records] == ["c1", "c2"]
    assert records[1].crag_status == "VERIFIED"
