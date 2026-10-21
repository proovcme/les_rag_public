import json
from pathlib import Path
import sys

import pytest


def test_rerank_probe_reports_transport_status_and_order_change(monkeypatch):
    from tools import smeta_rerank_ab_probe as probe

    def browse(queries, *, rerank, **_kwargs):
        return {
            query: {
                "cards": [
                    {
                        "norm_code": "N-2" if rerank else "N-1",
                        "title": "ranked" if rerank else "raw",
                    }
                ],
                "retrieval_trace": {
                    "rerank_status": "ok" if rerank else "disabled_by_caller",
                    "rag": {"status": "ready", "reason": ""},
                },
            }
            for query in queries
        }

    monkeypatch.setattr(probe, "browse_norms_many", browse)

    report = probe.run_probe(
        ["работа 1", "работа 2"],
        limit=8,
        depth=3,
        base_path=Path("base.sqlite"),
        expected_terms={"работа 1": ["ranked"], "работа 2": ["ranked"]},
    )

    assert report["rerank_status"] == ["ok"]
    assert report["top1_changed"] == 2
    assert all(row["rerank_status"] == "ok" for row in report["rows"])
    assert all(row["rag_status"] == "ready" for row in report["rows"])
    assert report["quality_checks"] == 2
    assert report["quality_passed"] == 2


def test_rerank_probe_exposes_semantically_bad_but_healthy_order(monkeypatch):
    from tools import smeta_rerank_ab_probe as probe

    monkeypatch.setattr(
        probe,
        "browse_norms_many",
        lambda queries, **_kwargs: {
            query: {
                "cards": [{"norm_code": "N-1", "title": "железобетонная панель"}],
                "retrieval_trace": {
                    "rerank_status": "ok",
                    "rag": {"status": "ok", "reason": ""},
                },
            }
            for query in queries
        },
    )

    report = probe.run_probe(
        ["монтаж патч панели"],
        limit=8,
        depth=3,
        expected_terms={"монтаж патч панели": ["кросс", "телефон", "коммутац"]},
    )

    assert report["rerank_status"] == ["ok"]
    assert report["quality_checks"] == 1
    assert report["quality_passed"] == 0
    assert report["rows"][0]["quality_match"] is False


def test_rerank_probe_preserves_structured_cards_and_full_stage_traces(monkeypatch):
    from tools import smeta_rerank_ab_probe as probe

    title = "Устройство конструкции с проверяемым составом работ " * 3
    cards = [
        {
            "norm_key": "TEST:01",
            "norm_code": "TEST-01",
            "title": title,
            "measure_unit": "100 м²",
            "resource_preview": [{"name": "not part of the compact identity"}],
        },
        {
            "norm_key": "TEST:02",
            "norm_code": "TEST-02",
            "title": "Другая технология",
            "measure_unit": "шт.",
        },
    ]
    before_trace = {
        "lexical_candidates": 24,
        "rag_candidates": 24,
        "fusion_candidates": 40,
        "rerank_status": "disabled_by_caller",
        "rag": {"status": "ok", "missing_norm_keys": {"буквальный запрос": 0}},
    }
    after_trace = {
        **before_trace,
        "rerank_status": "ok",
        "rerank_ms": 17.25,
        "returned_candidates": 2,
    }

    def browse(queries, *, rerank, **_kwargs):
        return {
            query: {
                "cards": list(reversed(cards)) if rerank else cards,
                "retrieval_trace": after_trace if rerank else before_trace,
            }
            for query in queries
        }

    monkeypatch.setattr(probe, "browse_norms_many", browse)

    row = probe.run_probe(["буквальный запрос"], limit=6, depth=1)["rows"][0]
    compact = [
        {key: card[key] for key in ("norm_key", "norm_code", "title", "measure_unit")}
        for card in cards
    ]

    assert row["before_trace"] == before_trace
    assert row["after_trace"] == after_trace
    assert row["before_cards"] == compact
    assert row["after_cards"] == list(reversed(compact))
    assert len(row["before"]) == len(row["after"]) == 1
    assert len(row["before_cards"][0]["title"]) > 70


def test_rerank_probe_cli_reads_literal_queries_from_utf8_file(monkeypatch, tmp_path):
    from tools import smeta_rerank_ab_probe as probe

    queries = [
        "  Монтаж конструкции № 7 — участок «А»  ",
        "ГЭСНм Санкт-Петербург 2026 установка вентилятора настенного",
    ]
    query_file = tmp_path / "буквальные запросы.json"
    query_file.write_text(json.dumps(queries, ensure_ascii=False), encoding="utf-8")
    report_path = tmp_path / "отчёт выдачи.json"
    observed = []

    def browse(actual_queries, *, rerank, **_kwargs):
        observed.append((list(actual_queries), rerank))
        return {
            query.strip(): {
                "cards": [],
                "retrieval_trace": {
                    "rerank_status": "ok" if rerank else "disabled_by_caller",
                    "rag": {"status": "ok", "reason": ""},
                },
            }
            for query in actual_queries
        }

    monkeypatch.setattr(probe, "browse_norms_many", browse)
    monkeypatch.setattr(sys, "argv", [
        "smeta_rerank_ab_probe", "--queries-file", str(query_file),
        "--limit", "6", "--report-path", str(report_path),
    ])

    assert probe.main() == 0
    assert observed == [(queries, False), (queries, True)]
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert [row["query"] for row in saved["rows"]] == queries
    assert saved["rerank_status"] == ["ok"]
    assert all(row["after_trace"]["rag"]["status"] == "ok" for row in saved["rows"])


def test_rerank_probe_cli_rejects_mixing_query_file_and_query(monkeypatch, tmp_path):
    from tools import smeta_rerank_ab_probe as probe

    query_file = tmp_path / "queries.json"
    query_file.write_text('["from file"]', encoding="utf-8")
    report_path = tmp_path / "report.json"
    called = []
    monkeypatch.setattr(probe, "run_probe", lambda *_args, **_kwargs: called.append(True))
    monkeypatch.setattr(sys, "argv", [
        "smeta_rerank_ab_probe", "--queries-file", str(query_file),
        "--query", "from argument", "--report-path", str(report_path),
    ])

    with pytest.raises(SystemExit) as error:
        probe.main()

    assert error.value.code == 2
    assert called == []
    assert not report_path.exists()


@pytest.mark.parametrize("payload", [{"queries": ["query"]}, ["query", 7], [None]])
def test_rerank_probe_cli_rejects_non_string_query_array(monkeypatch, tmp_path, payload):
    from tools import smeta_rerank_ab_probe as probe

    query_file = tmp_path / "queries.json"
    query_file.write_text(json.dumps(payload), encoding="utf-8")
    report_path = tmp_path / "report.json"
    called = []
    monkeypatch.setattr(probe, "run_probe", lambda *_args, **_kwargs: called.append(True))
    monkeypatch.setattr(sys, "argv", [
        "smeta_rerank_ab_probe", "--queries-file", str(query_file),
        "--report-path", str(report_path),
    ])

    with pytest.raises(SystemExit) as error:
        probe.main()

    assert error.value.code == 2
    assert called == []
    assert not report_path.exists()
