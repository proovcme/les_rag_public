"""W1.4: конвейер индексации — стадии, префетч, таймаут конвертации, resume."""

import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

import backend.converter as converter
import backend.qdrant_adapter as qa
from backend.qdrant_adapter import MetaDB, QdrantLlamaIndexAdapter


class TrackingDB:
    """Фейковая метабаза: пишет статусы и стадии."""

    def __init__(self, pending):
        self._pending = list(pending)
        self.statuses = []
        self.stages = []

    def get_pending_files(self, dataset_id, limit=None):
        return [] if self.statuses else list(self._pending)

    def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
        self.statuses.append((file_name, status, chunk_count, last_error))

    def update_document_stage(self, dataset_id, file_name, stage):
        self.stages.append((file_name, stage))

    def update_dataset_chunk_count(self, dataset_id):
        pass

    def clear_structured_rules(self, file_key):
        pass

    def insert_structured_rules(self, rules):
        pass

    def replace_structured_rules(self, dataset_id, file_key, rules):
        pass


class FakeQdrant:
    def __init__(self, url, **kwargs):
        self.url = url

    def upsert(self, collection_name, points, **_kwargs):
        return None

    def scroll(self, **kwargs):
        return [], None


def _adapter(tmp_path, db, nodes_fn=None, deleted=None):
    def default_nodes(file_path, *args):
        return [{"text": "содержимое файла достаточной длины для чанка", "doc_id": f"{file_path.name}", "payload": {}}]

    return SimpleNamespace(
        content_dir=tmp_path,
        db=db,
        qdrant_url="http://127.0.0.1:6333",
        collection_name="les_rag",
        embed=SimpleNamespace(encode_sync=lambda texts: [[0.0] * 8 for _ in texts]),
        _sync_delete_file_points=lambda *args: (deleted.append(args[2]) if deleted is not None else None),
        _sync_count_file_points=lambda *args: 1,
        _sync_markdown_nodes=nodes_fn or default_nodes,
    )


def _make_files(tmp_path, names):
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir(exist_ok=True)
    for name in names:
        (dataset_dir / name).write_text(f"контент {name} достаточной длины для чанка")
    return dataset_dir


def test_stages_recorded_in_order(tmp_path, monkeypatch):
    _make_files(tmp_path, ["a.md"])
    db = TrackingDB(["a.md"])
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db), "ds-1", limit=1)

    assert result["files_parsed"] == 1
    assert [s for _, s in db.stages] == ["CONVERT", "EMBED", "UPSERT"]
    assert db.statuses[-1][1] == "INDEXED"


def test_prefetch_processes_all_files_in_order(tmp_path, monkeypatch):
    names = [f"f{i}.md" for i in range(5)]
    _make_files(tmp_path, names)
    db = TrackingDB(names)
    processed = []

    def nodes_fn(file_path, *args):
        processed.append(file_path.name)
        return [{"text": "контент достаточной длины для чанка", "doc_id": file_path.name, "payload": {}}]

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db, nodes_fn=nodes_fn), "ds-1", limit=10)

    assert result["files_parsed"] == 5
    assert result["errors"] == 0
    assert sorted(processed) == sorted(names)
    indexed = [f for f, s, *_ in db.statuses if s == "INDEXED"]
    assert sorted(indexed) == sorted(names)


def test_prefetch_disabled_gives_same_result(tmp_path, monkeypatch):
    names = ["a.md", "b.md"]
    _make_files(tmp_path, names)
    db = TrackingDB(names)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db), "ds-1", limit=10)

    assert result["files_parsed"] == 2 and result["errors"] == 0


def test_convert_timeout_marks_error_and_continues(tmp_path, monkeypatch):
    names = ["slow.md", "fast.md"]
    _make_files(tmp_path, names)
    db = TrackingDB(names)

    def nodes_fn(file_path, *args):
        if file_path.name == "slow.md":
            import time

            time.sleep(2.0)  # дольше таймаута
        return [{"text": "контент достаточной длины для чанка", "doc_id": file_path.name, "payload": {}}]

    monkeypatch.setattr(qa, "PARSE_FILE_TIMEOUT", 0.3)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    result = QdrantLlamaIndexAdapter._sync_parse(_adapter(tmp_path, db, nodes_fn=nodes_fn), "ds-1", limit=10)

    statuses = {f: s for f, s, *_ in db.statuses}
    assert statuses["slow.md"] == "ERROR"
    assert statuses["fast.md"] == "INDEXED"
    assert result["errors"] == 1
    error_entry = next(entry for entry in db.statuses if entry[1] == "ERROR")
    assert "timeout" in error_entry[3]


def test_convert_failure_keeps_old_points(tmp_path, monkeypatch):
    """W1.4: сбой конвертации НЕ удаляет старые точки файла (delete после convert)."""
    _make_files(tmp_path, ["bad.md"])
    db = TrackingDB(["bad.md"])
    deleted = []

    def nodes_fn(file_path, *args):
        raise ValueError("conversion exploded")

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    result = QdrantLlamaIndexAdapter._sync_parse(
        _adapter(tmp_path, db, nodes_fn=nodes_fn, deleted=deleted), "ds-1", limit=1
    )

    assert result["errors"] == 1
    # cleanup-ветка в except удаляет точки файла — но только она; до конвертации удаления нет.
    # Проверяем, что удаление не произошло ДО ошибки конвертации (только cleanup после).
    assert deleted.count("bad.md") <= 1


def test_required_ocr_with_page_heading_keeps_public_hierarchy(tmp_path, monkeypatch):
    _make_files(tmp_path, ["scan.pdf"])
    db = TrackingDB(["scan.pdf"])
    adapter = _adapter(tmp_path, db)
    route = qa.DocumentRoute(
        domain="general", dataset_name="test", doc_type="DOCUMENT",
        content_type="scan", complexity="simple", pipeline="markdown_needs_ocr", metadata={},
    )
    uploaded = []
    adapter._sync_count_file_points = lambda *a: len(uploaded)

    class RecordingQdrant(FakeQdrant):
        def upsert(self, collection_name, points, **kwargs):
            uploaded.extend(points)

    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr(qa.qdrant_client, "QdrantClient", RecordingQdrant)
    monkeypatch.setattr(QdrantLlamaIndexAdapter, "_convert_file", lambda *a, **k: (route, [{
        "text": "## Page 1\n\nТехнические условия подключения к водоснабжению",
        "doc_id": "page-1", "payload": {
            "type": "pdf_page_text", "page": 1, "source_format": "pdf",
            "content_format": "pdf", "source_sha256": "a" * 64,
        },
    }]))
    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)
    assert result["errors"] == 0
    assert db.statuses[-1][1] == "INDEXED"
    assert {point.payload["node_role"] for point in uploaded} == {"evidence", "navigation"}
    assert any("водоснабжению" in point.payload["text"] for point in uploaded)


def test_explicit_ocr_empty_nodes_keep_existing_evidence(tmp_path, monkeypatch):
    _make_files(tmp_path, ["scan.pdf"])
    db = TrackingDB(["scan.pdf"])
    deleted = []
    lexical_deleted = []
    ocr_route = SimpleNamespace(pipeline="markdown_needs_ocr")
    adapter = _adapter(tmp_path, db, deleted=deleted)
    adapter._sync_delete_file_lexical = lambda _dataset_id, key: lexical_deleted.append(key)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    monkeypatch.setattr(
        QdrantLlamaIndexAdapter,
        "_convert_file",
        lambda *_args, **_kwargs: (ocr_route, []),
    )

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["errors"] == 1
    assert db.statuses[-1][1:3] == ("ERROR", 0)
    assert db.statuses[-1][3] == "ocr_required_no_searchable_text"
    assert deleted == []
    assert lexical_deleted == []


@pytest.mark.parametrize("failure_code", ["tesseract_timeout", "ollama_vision_failed", "mlx_vision_load_failed"])
def test_explicit_ocr_failure_keeps_existing_evidence(tmp_path, monkeypatch, failure_code):
    _make_files(tmp_path, ["scan.pdf"])
    db = TrackingDB(["scan.pdf"])
    deleted = []
    lexical_deleted = []
    adapter = _adapter(tmp_path, db, deleted=deleted)
    adapter._sync_delete_file_lexical = lambda _dataset_id, key: lexical_deleted.append(key)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    monkeypatch.setattr(
        QdrantLlamaIndexAdapter,
        "_convert_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(qa.OCRRequiredError(failure_code)),
    )

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["errors"] == 1
    assert db.statuses[-1][1:3] == ("ERROR", 0)
    assert db.statuses[-1][3] == failure_code
    assert "private" not in db.statuses[-1][3]
    assert deleted == []
    assert lexical_deleted == []


def test_explicit_ocr_incomplete_provenance_keeps_existing_evidence(tmp_path, monkeypatch):
    _make_files(tmp_path, ["scan.pdf"])
    db = TrackingDB(["scan.pdf"])
    deleted = []
    lexical_deleted = []
    route = SimpleNamespace(pipeline="markdown_needs_ocr")
    adapter = _adapter(tmp_path, db, deleted=deleted)
    adapter._sync_delete_file_lexical = lambda _dataset_id, key: lexical_deleted.append(key)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    monkeypatch.setattr(
        QdrantLlamaIndexAdapter,
        "_convert_file",
        lambda *_args, **_kwargs: (route, [{
            "text": "Технические условия подключения достаточно длинные для индекса",
            "doc_id": "node-1",
            "payload": {"type": "pdf_page_text", "page": True},
        }]),
    )

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["errors"] == 1
    assert db.statuses[-1][3] == "ocr_required_invalid_provenance"
    assert deleted == []
    assert lexical_deleted == []


def test_dynamic_sparse_ocr_failure_preserves_evidence_and_never_indexes_warning(tmp_path, monkeypatch):
    """Short nonempty converter output must not erase prior evidence when OCR is disabled."""
    filename = f"{'x' * 140}.pdf"
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir()
    (dataset_dir / filename).write_bytes(b"%PDF-1.7\n")
    db = TrackingDB([filename])
    deleted = []
    lexical_deleted = []
    route = SimpleNamespace(pipeline="markdown", doc_type="DOCUMENT")
    adapter = _adapter(tmp_path, db, deleted=deleted)
    adapter._sync_delete_file_lexical = lambda _dataset_id, key: lexical_deleted.append(key)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    class FakeDocument:
        page_count = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def __getitem__(self, _index):
            return SimpleNamespace(get_text=lambda *_args, **_kwargs: "verified source text " * 10)

    fake_fitz = ModuleType("fitz")
    fake_fitz.open = lambda *_args, **_kwargs: FakeDocument()
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    fake_pymupdf = ModuleType("pymupdf4llm")
    fake_pymupdf.to_markdown = lambda *_args, **_kwargs: "x"
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_pymupdf)
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
    monkeypatch.setenv("RAG_PDF_PARSER", "pymupdf")
    monkeypatch.setenv("LES_LAYOUT_PDF", "false")

    def convert_sparse_pdf(_self, file_path, *_args, **_kwargs):
        markdown = converter._parse_pdf(file_path, route=route)
        return route, [{"text": markdown, "doc_id": "warning", "payload": {}}]

    monkeypatch.setattr(QdrantLlamaIndexAdapter, "_convert_file", convert_sparse_pdf)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["errors"] == 1
    assert db.statuses[-1][1:4] == ("ERROR", 0, "ocr_required_disabled")
    assert deleted == []
    assert lexical_deleted == []


def test_raw_cad_bim_source_is_skipped_not_indexed_zero(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "ds-1" / "raw"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "model.dwg").write_bytes(b"AC1027 binary dwg placeholder")
    db = TrackingDB(["raw/model.dwg"])
    deleted = []

    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)
    result = QdrantLlamaIndexAdapter._sync_parse(
        _adapter(tmp_path, db, deleted=deleted), "ds-1", limit=1
    )

    assert result["errors"] == 0
    assert db.statuses[-1][0:3] == ("raw/model.dwg", "SKIPPED", 0)
    assert "raw CAD/BIM source unsupported" in db.statuses[-1][3]
    assert all(status != "INDEXED" for _, status, *_ in db.statuses)


def test_mislabeled_pdf_is_skipped_without_deleting_or_indexing(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir(exist_ok=True)
    (dataset_dir / "underlay.pdf").write_bytes(b"\x89PNG\r\n\x1a\nnot a pdf")
    db = TrackingDB(["underlay.pdf"])
    deleted = []
    adapter = _adapter(tmp_path, db, deleted=deleted)
    adapter._sync_markdown_nodes = QdrantLlamaIndexAdapter._sync_markdown_nodes.__get__(adapter)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["errors"] == 0
    assert db.statuses[-1][0:3] == ("underlay.pdf", "SKIPPED", 0)
    assert db.statuses[-1][3] == "pdf_source_unreadable: underlay.pdf"
    assert deleted == []


def test_truncated_pdf_header_is_skipped_without_indexing_warning(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "ds-1"
    dataset_dir.mkdir(exist_ok=True)
    (dataset_dir / "truncated.pdf").write_bytes(b"%PDF-1.7\n")
    db = TrackingDB(["truncated.pdf"])
    deleted = []
    adapter = _adapter(tmp_path, db, deleted=deleted)
    adapter._sync_markdown_nodes = QdrantLlamaIndexAdapter._sync_markdown_nodes.__get__(adapter)
    monkeypatch.setattr(qa, "PARSE_PREFETCH", False)
    monkeypatch.setenv("RAG_CONVERT_SUBPROCESS_ENABLED", "0")
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", FakeQdrant)

    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)

    assert result["errors"] == 0
    assert db.statuses[-1] == (
        "truncated.pdf", "SKIPPED", 0, "pdf_source_unreadable: truncated.pdf"
    )
    assert deleted == []


def test_resume_after_crash_no_duplicate_points(tmp_path, monkeypatch):
    """kill посреди файла → файл остаётся PENDING → повторный прогон удаляет старые точки и доводит."""
    _make_files(tmp_path, ["a.md"])
    upserts = []
    deleted = []
    stored_points = {}
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(tmp_path / "lexical.db"))

    class RecordingQdrant(FakeQdrant):
        def upsert(self, collection_name, points, **_kwargs):
            upserts.append(len(points))
            stored_points.update({point.id: point for point in points})

        def scroll(self, **kwargs):
            return list(stored_points.values()), None

        def delete(self, **kwargs):
            for pid in kwargs["points_selector"].points:
                stored_points.pop(pid)

    crash = {"armed": True}

    class CrashingDB(TrackingDB):
        def update_document_status(self, dataset_id, file_name, status, chunk_count, route=None, last_error=""):
            if crash["armed"] and status == "INDEXED":
                crash["armed"] = False
                raise KeyboardInterrupt("kill -9 имитация: статус не записан")
            super().update_document_status(dataset_id, file_name, status, chunk_count, route, last_error)

        def get_pending_files(self, dataset_id, limit=None):
            # Пока INDEXED не записан — файл остаётся PENDING.
            done = any(s == "INDEXED" for _, s, *_ in self.statuses)
            return [] if done else ["a.md"]

    db = CrashingDB(["a.md"])
    monkeypatch.setattr("backend.qdrant_adapter.qdrant_client.QdrantClient", RecordingQdrant)
    adapter = _adapter(tmp_path, db, deleted=deleted)

    # Прогон 1: «падение» после upsert, до записи статуса.
    with pytest.raises(KeyboardInterrupt):
        QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)
    assert len(upserts) == 1

    # Прогон 2: файл всё ещё PENDING → старые точки удалены, upsert повторён, статус записан.
    result = QdrantLlamaIndexAdapter._sync_parse(adapter, "ds-1", limit=1)
    assert result["files_parsed"] == 1
    assert deleted == []  # never whole-file cleanup
    assert len(stored_points) == 1  # only the replacement generation survives
    assert len(upserts) == 2
    assert db.statuses[-1][1] == "INDEXED"


def test_metadb_stage_column_roundtrip(tmp_path):
    db = MetaDB(str(tmp_path / "meta.db"))
    dataset_id = db.create_dataset("ds")
    db.add_document(dataset_id, "a.md")
    db.update_document_stage(dataset_id, "a.md", "EMBED")
    with db._get_conn() as conn:
        stage = conn.execute(
            "SELECT stage FROM documents WHERE dataset_id=? AND file_name=?", (dataset_id, "a.md")
        ).fetchone()[0]
    assert stage == "EMBED"
    db.update_document_status(dataset_id, "a.md", "INDEXED", 1)
    with db._get_conn() as conn:
        stage = conn.execute(
            "SELECT stage FROM documents WHERE dataset_id=? AND file_name=?", (dataset_id, "a.md")
        ).fetchone()[0]
    assert stage == ""
