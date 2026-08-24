import sqlite3
import time

from backend.qdrant_adapter import (
    MetaDB,
    UnsupportedIndexingSourceError,
    _classify_parse_failure,
    _legacy_navigation_count_candidate,
    _parse_failure_policy,
    _point_fingerprint_coverage_ready,
)


def test_dense_readiness_requires_complete_point_fingerprint_coverage():
    assert _point_fingerprint_coverage_ready(points=0, matching=0) is True
    assert _point_fingerprint_coverage_ready(points=3, matching=3) is True
    assert _point_fingerprint_coverage_ready(points=3, matching=0) is False
    assert _point_fingerprint_coverage_ready(points=3, matching=2) is False


def test_legacy_navigation_count_repair_requires_exact_safe_delta():
    assert _legacy_navigation_count_candidate(
        expected=100,
        actual=108,
        navigation=8,
        dense=108,
        sparse=108,
        lexical_matches=True,
    ) is True
    assert _legacy_navigation_count_candidate(
        expected=100,
        actual=108,
        navigation=7,
        dense=108,
        sparse=108,
        lexical_matches=True,
    ) is False
    assert _legacy_navigation_count_candidate(
        expected=100,
        actual=108,
        navigation=48,
        dense=108,
        sparse=108,
        lexical_matches=True,
        source_actual=100,
        source_navigation=40,
    ) is True
    assert _legacy_navigation_count_candidate(
        expected=100,
        actual=108,
        navigation=48,
        dense=108,
        sparse=108,
        lexical_matches=True,
        source_actual=99,
        source_navigation=40,
    ) is False
    assert _legacy_navigation_count_candidate(
        expected=100,
        actual=108,
        navigation=8,
        dense=108,
        sparse=107,
        lexical_matches=True,
    ) is False


def test_metadb_applies_navigation_count_repairs_atomically(tmp_path):
    db_path = tmp_path / "meta.db"
    db = MetaDB(str(db_path))
    dataset_id = db.create_dataset("Project")
    db.add_document(dataset_id, "doc.pdf")
    db.update_document_status(dataset_id, "doc.pdf", "INDEXED", 100)
    db.update_dataset_chunk_count(dataset_id)

    assert db.apply_document_chunk_count_repairs(
        [(dataset_id, "doc.pdf", 108)]
    ) == 1
    assert db.indexed_files_with_counts(dataset_id) == [("doc.pdf", 108)]
    assert db.list_datasets()[0].chunk_count == 108


def test_retry_policy_is_bounded_and_has_stable_code(monkeypatch):
    monkeypatch.setenv("RAG_PARSE_MAX_ATTEMPTS", "3")
    code, retryable, retry_after = _parse_failure_policy(
        RuntimeError("missing prevalidated sparse vector"),
        attempts=1,
    )
    assert code == "SPARSE_VECTOR_PREVALIDATION_MISSING"
    assert retryable is True
    assert retry_after > time.time()

    _, retryable, retry_after = _parse_failure_policy(
        RuntimeError("missing prevalidated sparse vector"),
        attempts=3,
    )
    assert retryable is False
    assert retry_after == 0


def test_failure_disposition_distinguishes_skipped_retryable_and_terminal(monkeypatch):
    monkeypatch.setenv("RAG_PARSE_MAX_ATTEMPTS", "2")

    skipped = _classify_parse_failure(UnsupportedIndexingSourceError("needs converter"), attempts=1)
    retryable = _classify_parse_failure(RuntimeError("qdrant point count mismatch"), attempts=1)
    exhausted = _classify_parse_failure(RuntimeError("qdrant point count mismatch"), attempts=2)
    deterministic = _classify_parse_failure(ValueError("invalid document structure"), attempts=1)

    assert (skipped.error_code, skipped.disposition, skipped.retryable) == (
        "UNSUPPORTED_INDEXING_SOURCE", "skipped", False,
    )
    assert (retryable.disposition, retryable.retryable) == ("retryable", True)
    assert (exhausted.disposition, exhausted.retryable) == ("terminal", False)
    assert (deterministic.error_code, deterministic.disposition) == ("PARSE_FAILED", "terminal")


def test_metadb_requeues_interrupted_and_due_retryable_errors(tmp_path):
    db_path = tmp_path / "meta.db"
    db = MetaDB(str(db_path))
    dataset_id = db.create_dataset("Project")
    db.add_document(dataset_id, "interrupted.pdf")
    db.add_document(dataset_id, "retry.pdf")
    db.add_document(dataset_id, "terminal.pdf")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE documents SET status='PENDING', stage='EMBED' WHERE file_name='interrupted.pdf'"
        )
        conn.execute(
            "UPDATE documents SET status='ERROR', retryable=1, retry_after=0, parse_attempts=1 "
            "WHERE file_name='retry.pdf'"
        )
        conn.execute(
            "UPDATE documents SET status='ERROR', retryable=0, error_code='UNSUPPORTED' "
            "WHERE file_name='terminal.pdf'"
        )

    assert db.recover_interrupted_parsing() == 2
    with sqlite3.connect(db_path) as conn:
        rows = dict(conn.execute("SELECT file_name, status FROM documents").fetchall())
    assert rows == {
        "interrupted.pdf": "PENDING",
        "retry.pdf": "PENDING",
        "terminal.pdf": "ERROR",
    }
    recovery = db.health_snapshot()["indexing_recovery"]
    assert recovery["retryable_errors"] == 0
    assert recovery["terminal_errors"] == 1
    assert recovery["by_error_code"]["UNSUPPORTED"]["files"] == 1


def test_bounded_repair_is_allowlisted_capped_and_excludes_module_datasets(tmp_path):
    db_path = tmp_path / "meta.db"
    db = MetaDB(str(db_path))
    user_id = db.create_dataset("Project")
    module_id = db.create_dataset("Module")
    for name in ("a.pdf", "b.pdf", "terminal.pdf", "exhausted.pdf"):
        db.add_document(user_id, name)
    db.add_document(module_id, "system.pdf")
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE datasets SET module_id='artel', dataset_scope='system' WHERE id=?", (module_id,))
        conn.execute(
            "UPDATE documents SET status='ERROR', error_code='SPARSE_VECTOR_PREVALIDATION_MISSING', "
            "parse_attempts=1 WHERE file_name IN ('a.pdf','b.pdf','system.pdf')"
        )
        conn.execute(
            "UPDATE documents SET status='ERROR', error_code='PARSE_FAILED', parse_attempts=1 "
            "WHERE file_name='terminal.pdf'"
        )
        conn.execute(
            "UPDATE documents SET status='ERROR', error_code='QDRANT_POINT_COUNT_MISMATCH', parse_attempts=4 "
            "WHERE file_name='exhausted.pdf'"
        )

    result = db.requeue_repairable_errors(max_files=1, max_attempts=4)

    assert result["repaired_files"] == 1
    assert result["eligible_files"] == 2
    assert result["remaining_files"] == 1
    with sqlite3.connect(db_path) as conn:
        states = dict(conn.execute("SELECT file_name, status FROM documents").fetchall())
    assert sum(states[name] == "PENDING" for name in ("a.pdf", "b.pdf")) == 1
    assert states["system.pdf"] == "ERROR"
    assert states["terminal.pdf"] == "ERROR"
    assert states["exhausted.pdf"] == "ERROR"
    repair = db.health_snapshot()["indexing_recovery"]["bounded_repair"]
    assert repair == {
        "status": "repaired",
        "ran_at": result["ran_at"],
        "repaired_files": 1,
        "eligible_files": 2,
        "max_files": 1,
    }


def test_skipped_document_has_stable_non_retryable_reason(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    dataset_id = db.create_dataset("Project")
    db.add_document(dataset_id, "drawing.dwg")

    db.mark_document_skipped(dataset_id, "drawing.dwg", message="typed converter required")

    recovery = db.health_snapshot()["indexing_recovery"]
    assert recovery["skipped_files"] == 1
    assert recovery["skipped_by_error_code"] == {
        "UNSUPPORTED_INDEXING_SOURCE": {"files": 1, "disposition": "skipped"}
    }
