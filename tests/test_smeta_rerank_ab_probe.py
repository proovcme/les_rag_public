from pathlib import Path


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
    )

    assert report["rerank_status"] == ["ok"]
    assert report["top1_changed"] == 2
    assert all(row["rerank_status"] == "ok" for row in report["rows"])
    assert all(row["rag_status"] == "ready" for row in report["rows"])
