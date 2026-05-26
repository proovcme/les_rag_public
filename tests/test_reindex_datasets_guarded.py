import json
import sqlite3

from tools import reindex_datasets_guarded as guarded


def _init_rag_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT, status TEXT, chunk_count INTEGER DEFAULT 0)")
    conn.execute(
        """
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            dataset_id TEXT,
            file_name TEXT,
            status TEXT,
            file_hash TEXT,
            file_mtime REAL,
            file_size INTEGER,
            chunk_count INTEGER DEFAULT 0,
            last_error TEXT DEFAULT ''
        )
        """
    )
    conn.executemany(
        "INSERT INTO datasets (id, name, status, chunk_count) VALUES (?, ?, ?, ?)",
        [
            ("ds-hvac", "NTD_HVAC_Index", "IDLE", 30),
            ("ds-fire", "NTD_FIRE_Index", "IDLE", 20),
        ],
    )
    conn.executemany(
        "INSERT INTO documents (id, dataset_id, file_name, status, file_size, chunk_count) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("hvac-a", "ds-hvac", "a.pdf", "INDEXED", 200, 20),
            ("hvac-b", "ds-hvac", "b.pdf", "PENDING", 100, 0),
            ("fire-a", "ds-fire", "a.pdf", "INDEXED", 50, 10),
        ],
    )
    conn.commit()
    conn.close()


def _init_auth_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE auth_keys (
            key_value TEXT PRIMARY KEY,
            holder_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'user',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            expires_at TEXT DEFAULT NULL,
            device_fingerprint TEXT DEFAULT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO auth_keys (key_value, holder_name, role, is_active) VALUES (?, ?, ?, ?)",
        [
            ("admin-secret", "Admin", "admin", 1),
            ("user-secret", "User", "user", 1),
            ("disabled", "Disabled", "user", 0),
        ],
    )
    conn.commit()
    conn.close()


def test_mask_key_hides_middle_and_reports_length():
    assert guarded.mask_key("") == "<empty>"
    assert guarded.mask_key("abc") == "*** (3 chars)"
    assert guarded.mask_key("admin-secret") == "ad...et (12 chars)"


def test_dataset_summaries_and_target_docs(tmp_path):
    db_path = tmp_path / "rag.db"
    _init_rag_db(db_path)

    summaries = guarded.dataset_summaries(str(db_path), ["NTD_HVAC_Index", "NTD_FIRE_Index"])
    assert [(row["name"], row["indexed_files"], row["pending_files"]) for row in summaries] == [
        ("NTD_FIRE_Index", 1, 0),
        ("NTD_HVAC_Index", 1, 1),
    ]

    docs = guarded.load_target_docs(str(db_path), ["NTD_HVAC_Index", "NTD_FIRE_Index"])
    assert [(doc.dataset_name, doc.file_name, doc.file_size) for doc in docs] == [
        ("NTD_FIRE_Index", "a.pdf", 50),
        ("NTD_HVAC_Index", "a.pdf", 200),
    ]


def test_mark_pending_and_restore_doc(tmp_path):
    db_path = tmp_path / "rag.db"
    _init_rag_db(db_path)
    doc = guarded.load_target_docs(str(db_path), ["NTD_HVAC_Index"])[0]

    guarded.mark_doc_pending(str(db_path), doc)
    pending = guarded.load_doc(str(db_path), doc.id)
    assert pending["status"] == "PENDING"
    assert pending["chunk_count"] == 0

    guarded.restore_doc_indexed(str(db_path), doc)
    restored = guarded.load_doc(str(db_path), doc.id)
    assert restored["status"] == "INDEXED"
    assert restored["chunk_count"] == 20


def test_active_keys_by_role_uses_active_keys_only(tmp_path):
    db_path = tmp_path / "auth.db"
    _init_auth_db(db_path)

    keys = guarded.active_keys_by_role(str(db_path))
    assert keys["admin"]["key_value"] == "admin-secret"
    assert keys["user"]["key_value"] == "user-secret"


def test_completed_doc_ids_from_log(tmp_path):
    log_path = tmp_path / "reindex.jsonl"
    rows = [
        {"event": "doc_start", "doc": {"id": "not-yet"}},
        {
            "event": "doc_parse",
            "current": {"id": "done-a", "status": "INDEXED"},
            "result": {"result": {"errors": 0}},
        },
        {
            "event": "doc_parse",
            "current": {"id": "failed", "status": "ERROR"},
            "result": {"result": {"errors": 1}},
        },
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    assert guarded.completed_doc_ids_from_log(str(log_path)) == {"done-a"}


def test_campaign_state_records_completed_doc(tmp_path):
    state_path = tmp_path / "state.json"
    doc = guarded.TargetDoc(
        id="doc-a",
        dataset_id="ds-fire",
        dataset_name="NTD_FIRE_Index",
        file_name="a.pdf",
        file_size=100,
        chunk_count=7,
    )
    state = guarded.empty_campaign_state(["NTD_FIRE_Index"], "rag.db")

    guarded.record_completed_doc(state_path, state, doc, {"chunk_count": 5}, tmp_path / "run")
    loaded = guarded.load_campaign_state(state_path, ["NTD_FIRE_Index"], "rag.db")

    assert guarded.completed_doc_ids_from_state(loaded) == {"doc-a"}
    assert loaded["completed"]["doc-a"]["old_chunk_count"] == 7
    assert loaded["completed"]["doc-a"]["new_chunk_count"] == 5


def test_import_completed_logs_into_state_is_idempotent(tmp_path):
    log_path = tmp_path / "reindex.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "event": "doc_parse",
                "current": {"id": "done-a", "status": "INDEXED"},
                "result": {"result": {"errors": 0}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state = guarded.empty_campaign_state(["NTD_FIRE_Index"], "rag.db")

    assert guarded.import_completed_logs_into_state(state, [str(log_path)]) == 1
    assert guarded.import_completed_logs_into_state(state, [str(log_path)]) == 0
    assert guarded.completed_doc_ids_from_state(state) == {"done-a"}


def test_compact_rag_keeps_totals_qdrant_and_problem_datasets():
    compact = guarded.compact_rag(
        {
            "status": "degraded",
            "totals": {"pending_files": 1},
            "qdrant": {"points_match_sqlite_chunks": True},
            "datasets": [
                {"name": "ok", "pending_files": 0, "error_files": 0},
                {"name": "pending", "pending_files": 1, "error_files": 0},
            ],
        }
    )

    assert compact == {
        "status": "degraded",
        "totals": {"pending_files": 1},
        "qdrant": {"points_match_sqlite_chunks": True},
        "active_datasets": [{"name": "pending", "pending_files": 1, "error_files": 0}],
    }
