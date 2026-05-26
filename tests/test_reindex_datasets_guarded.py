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
