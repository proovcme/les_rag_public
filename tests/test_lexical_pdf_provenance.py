"""PDF page provenance must survive Qdrant -> lexical SQLite -> source adapter."""

from __future__ import annotations

import hashlib
import sqlite3
from types import SimpleNamespace

import pytest
from qdrant_client import models

from backend.qdrant_adapter import QdrantLlamaIndexAdapter
from proxy.services.lexical_index_service import LexicalIndex


_BBOX = [72.0, 90.0, 480.0, 130.0]


def _pdf_page_payload(**extra) -> dict:
    text = "## Page 2\n\nGEOTECHNICAL REPORT CATEGORYIII CONFIRMED"
    payload = {
        "text": text,
        "dataset_id": "sample-pd",
        "doc_id": "doc-1",
        "file_name": "geotechnical-report.pdf",
        "content_hash": hashlib.sha1(text.encode()).hexdigest(),
        "chunk_ord": 77,
        "type": "pdf_page_text",
        "source_layer": "pdf_text_layer",
        "page": 2,
        "source_ref": "geotechnical-report.pdf#page=2",
        "pdf_page_passport_schema": "les.pdf.page-passport.v1",
        "pdf_fragment_bboxes": [
            {"fragment_id": "f1", "bbox": _BBOX, "source_ref": "geotechnical-report.pdf#page=2"},
        ],
    }
    payload.update(extra)
    return payload


def test_lexical_rows_carry_real_pdf_page_provenance() -> None:
    point = models.PointStruct(id="p-1", vector=[0.1, 0.2], payload=_pdf_page_payload())

    row = QdrantLlamaIndexAdapter._lexical_rows_from_points([point])[0]

    assert row["source_page"] == 2
    assert row["source_page"] != row["chunk_ord"]
    assert row["source_ref"] == "geotechnical-report.pdf#page=2"
    assert row["extraction_method"] == "pdf_text_layer"
    assert row["extraction_version"] == "les.pdf.page-passport.v1"
    assert row["bbox_json"]


def test_provenance_schema_is_additive_and_roundtrip_reaches_adapter(
    tmp_path, monkeypatch
) -> None:
    from proxy.services import source_adapters as sa

    lexical_db = tmp_path / "lexical.db"
    # Simulate a pre-bridge lexical DB: schema migration must preserve the row and FTS data.
    with sqlite3.connect(lexical_db) as conn:
        conn.executescript(
            """
            CREATE TABLE lexical_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                point_id TEXT NOT NULL,
                dataset_id TEXT DEFAULT '',
                doc_id TEXT DEFAULT '',
                doc_name TEXT DEFAULT '',
                text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                chunk_ord INTEGER,
                section_heading TEXT DEFAULT '',
                parent_id TEXT DEFAULT '',
                parent_ord INTEGER,
                child_ord INTEGER,
                parent_heading TEXT DEFAULT '',
                context_before TEXT DEFAULT '',
                context_after TEXT DEFAULT '',
                context_kind TEXT DEFAULT '',
                updated_at REAL NOT NULL,
                UNIQUE(collection, point_id)
            );
            INSERT INTO lexical_chunks (
                collection,point_id,dataset_id,doc_id,doc_name,text,content_hash,chunk_ord,updated_at
            ) VALUES ('keep','old','old-ds','old-doc','old.pdf','PRESERVED OLD ROW','old-hash',1,1.0);
            """
        )

    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(lexical_db))
    monkeypatch.setenv("RAG_COLLECTION_NAME", "test-pdf-provenance")
    point = models.PointStruct(id="p-1", vector=[0.1, 0.2], payload=_pdf_page_payload())
    index = LexicalIndex(str(lexical_db))
    index.upsert_chunks(
        "test-pdf-provenance",
        QdrantLlamaIndexAdapter._lexical_rows_from_points([point]),
    )
    index.mark_collection("test-pdf-provenance", point_count=1, indexed_count=1)

    with sqlite3.connect(lexical_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(lexical_chunks)")}
        preserved = conn.execute(
            "SELECT text FROM lexical_chunks WHERE collection='keep' AND point_id='old'"
        ).fetchone()
    assert {
        "source_page", "source_ref", "bbox_json", "extraction_method", "extraction_version"
    }.issubset(columns)
    assert preserved == ("PRESERVED OLD ROW",)

    result = sa.search_lexical_chunks(["CATEGORYIII"], dataset_ids=["sample-pd"])

    assert result.matches
    match = result.matches[0]
    assert match.page == 2
    assert match.page != int(match.chunk_id)
    assert match.bbox == _BBOX
    assert match.extraction_method == "pdf_text_layer"
    assert match.extraction_version == "les.pdf.page-passport.v1"


def test_missing_provenance_is_not_invented(tmp_path, monkeypatch) -> None:
    from proxy.services import source_adapters as sa

    lexical_db = tmp_path / "lexical.db"
    monkeypatch.setenv("RAG_LEXICAL_DB_PATH", str(lexical_db))
    monkeypatch.setenv("RAG_COLLECTION_NAME", "test-plain")
    text = "CATEGORYIII appears in a markdown chunk without a PDF page"
    point = models.PointStruct(
        id="p-2",
        vector=[0.1, 0.2],
        payload={
            "text": text,
            "dataset_id": "sample-pd",
            "doc_id": "doc-2",
            "file_name": "notes.md",
            "content_hash": hashlib.sha1(text.encode()).hexdigest(),
            "chunk_ord": 3,
        },
    )
    index = LexicalIndex(str(lexical_db))
    index.upsert_chunks("test-plain", QdrantLlamaIndexAdapter._lexical_rows_from_points([point]))
    index.mark_collection("test-plain", point_count=1, indexed_count=1)

    result = sa.search_lexical_chunks(["CATEGORYIII"], dataset_ids=["sample-pd"])

    assert result.matches
    assert result.matches[0].page is None
    assert result.matches[0].bbox is None
    assert result.matches[0].extraction_method == ""
