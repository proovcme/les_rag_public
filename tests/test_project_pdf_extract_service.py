import sqlite3

import pytest

from proxy.services.project_pdf_extract_service import (
    PROJECT_PDF_EXTRACT_SCHEMA,
    PROJECT_PDF_FILE_EXTRACT_SCHEMA,
    compact_project_pdf_extract_for_model,
    project_pdf_extract_status,
    run_project_pdf_extract,
)

fitz = pytest.importorskip("fitz")


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(320, 620, 560, 810),
        "\n".join(
            [
                "Object: Innovation Center",
                "Cipher: IC-PD-IOS-ES-PZ-001",
                "Stage: P",
                "Sheet: 1",
                "Sheets: 4",
            ]
        ),
        fontsize=9,
    )
    page.insert_text((50, 90), "Оглавление")
    page.insert_text((50, 115), "1 Общие данные 3")
    page.insert_text((50, 140), "2 Электроснабжение 5")
    doc.save(str(path))
    doc.close()


def _seed_db(path, dataset_id, file_name):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE documents (
            id TEXT,
            dataset_id TEXT,
            file_name TEXT,
            status TEXT,
            chunk_count INTEGER,
            doc_type TEXT,
            content_type TEXT,
            domain TEXT,
            pipeline TEXT,
            source_path TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("doc-1", dataset_id, file_name, "INDEXED", 3, "DOCUMENT", "text", "", "markdown", ""),
    )
    conn.commit()
    conn.close()


def test_run_project_pdf_extract_writes_sidecars_without_reindex(tmp_path):
    dataset_id = "ds-pdf"
    storage_root = tmp_path / "storage"
    pdf = storage_root / dataset_id / "PD" / "ИОС.ЭС.ПЗ.pdf"
    pdf.parent.mkdir(parents=True)
    _make_pdf(pdf)
    db = tmp_path / "meta.db"
    _seed_db(db, dataset_id, "PD/ИОС.ЭС.ПЗ.pdf")

    summary = run_project_pdf_extract(
        dataset_id,
        storage_root=storage_root,
        meta_db_path=str(db),
        max_files=10,
        max_pages=3,
        force=True,
    )

    assert summary["schema"] == PROJECT_PDF_EXTRACT_SCHEMA
    assert summary["is_evidence"] is False
    assert summary["coverage"]["pdf_documents"] == 1
    assert summary["coverage"]["files_ok"] == 1
    assert summary["files"][0]["schema"] == PROJECT_PDF_FILE_EXTRACT_SCHEMA
    assert summary["files"][0]["status"] == "ok"
    assert "drawing_manifest" in summary["files"][0]["artifact_paths"]
    assert "pd_rd_manifest" in summary["files"][0]["artifact_paths"]
    assert (storage_root / dataset_id / "_les_pdf_extract" / "summary.json").exists()

    status = project_pdf_extract_status(dataset_id, storage_root=storage_root, meta_db_path=str(db))
    assert status["summary_exists"] is True
    assert status["stale"] is False

    compact = compact_project_pdf_extract_for_model(summary)
    assert compact["context_role"] == "navigation_not_evidence"
    assert compact["files"][0]["file_name"] == "PD/ИОС.ЭС.ПЗ.pdf"


def test_run_project_pdf_extract_keeps_going_on_empty_pdf(tmp_path):
    dataset_id = "ds-empty-pdf"
    storage_root = tmp_path / "storage"
    pdf = storage_root / dataset_id / "broken.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"")
    db = tmp_path / "meta.db"
    _seed_db(db, dataset_id, "broken.pdf")

    summary = run_project_pdf_extract(
        dataset_id,
        storage_root=storage_root,
        meta_db_path=str(db),
        max_files=10,
        max_pages=3,
        force=True,
    )

    assert summary["status"] == "ok"
    assert summary["coverage"]["extract_errors"] == 1
    assert summary["files"][0]["status"] == "extract_error"
    assert any("empty_pdf_source" in warning for warning in summary["files"][0]["warnings"])
