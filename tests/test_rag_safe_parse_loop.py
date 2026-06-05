from tools import rag_safe_parse_loop as loop


def test_memory_ok_respects_thresholds():
    ok, detail = loop.memory_ok({"ok": True, "ram_free_gb": 9, "swap_pct": 10}, 8, 45)
    assert ok is True
    assert "ram_free_gb=9" in detail

    ok, detail = loop.memory_ok({"ok": True, "ram_free_gb": 4, "swap_pct": 10}, 8, 45)
    assert ok is False
    assert "ram_free_gb=4" in detail

    ok, detail = loop.memory_ok({"ok": True, "ram_free_gb": 9, "swap_pct": 80}, 8, 45)
    assert ok is False
    assert "swap_pct=80" in detail


def test_pending_total_reads_snapshot_totals():
    assert loop.pending_total({"totals": {"pending_files": 42}}) == 42
    assert loop.pending_total({"totals": {}}) == 0


def test_rag_snapshot_marks_qdrant_sqlite_mismatch(monkeypatch):
    def _fake_get_json(url, timeout):
        return {
            "rag": {
                "status": "degraded",
                "totals": {"pending_files": 3},
                "qdrant": {"points_match_sqlite_chunks": False},
            }
        }

    monkeypatch.setattr(loop, "get_json", _fake_get_json)

    snapshot = loop.rag_snapshot("http://proxy", 1)

    assert snapshot["ok"] is False
    assert snapshot["totals"]["pending_files"] == 3


def test_rag_snapshot_accepts_matching_qdrant(monkeypatch):
    def _fake_get_json(url, timeout):
        return {
            "rag": {
                "status": "degraded",
                "totals": {"pending_files": 3},
                "qdrant": {"points_match_sqlite_chunks": True},
            }
        }

    monkeypatch.setattr(loop, "get_json", _fake_get_json)

    snapshot = loop.rag_snapshot("http://proxy", 1)

    assert snapshot["ok"] is True
