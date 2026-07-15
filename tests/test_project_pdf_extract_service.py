import sqlite3

import pytest

import proxy.services.project_pdf_extract_service as project_pdf_extract_service
from proxy.services.project_pdf_extract_service import (
    PROJECT_PDF_EXTRACT_SCHEMA,
    PROJECT_PDF_FILE_EXTRACT_SCHEMA,
    _coverage,
    _discipline,
    _doc_role,
    _looks_electrical,
    _prioritize_source_refs,
    _summary_status,
    compact_project_pdf_extract_for_model,
    project_pdf_extract_root,
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


def _seed_db_many(path, dataset_id, files):
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
    for idx, file_name in enumerate(files, 1):
        conn.execute(
            "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"doc-{idx}", dataset_id, file_name, "PENDING", 0, "DOCUMENT", "text", "", "markdown", ""),
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
    assert summary["list_integration"]["status"] == "ready"
    assert summary["list_integration"]["document_registry"]["document_count"] == 1
    assert (storage_root / dataset_id / "_les_pdf_extract" / "table_registry.jsonl").exists()
    assert (storage_root / dataset_id / "_les_pdf_extract" / "document_registry.json").exists()

    status = project_pdf_extract_status(dataset_id, storage_root=storage_root, meta_db_path=str(db))
    assert status["summary_exists"] is True
    assert status["stale"] is False

    compact = compact_project_pdf_extract_for_model(summary)
    assert compact["context_role"] == "navigation_not_evidence"
    assert compact["files"][0]["file_name"] == "PD/ИОС.ЭС.ПЗ.pdf"
    assert compact["list_integration"]["status"] == "ready"


def test_compact_project_pdf_extract_hides_low_signal_navigation_from_old_summary():
    compact = compact_project_pdf_extract_for_model({
        "status": "ok",
        "source_navigation": [
            {"role": "UNKNOWN: требует ручной/визуальной классификации", "source_refs": ["x#page=1"]},
            {"role": "SPEC: спецификации оборудования/изделий/материалов", "source_refs": ["x#page=2"]},
        ],
    })

    assert [item["role"] for item in compact["source_navigation"]] == [
        "SPEC: спецификации оборудования/изделий/материалов"
    ]


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

    assert summary["status"] == "failed"
    assert summary["coverage"]["files_attempted"] == 1
    assert summary["coverage"]["files_extracted"] == 0
    assert summary["coverage"]["extract_errors"] == 1
    assert summary["files"][0]["status"] == "extract_error"
    assert any("empty_pdf_source" in warning for warning in summary["files"][0]["warnings"])


def test_run_project_pdf_extract_resumes_from_file_checkpoints_after_summary_loss(tmp_path, monkeypatch):
    dataset_id = "ds-resume"
    storage_root = tmp_path / "storage"
    dataset_root = storage_root / dataset_id
    dataset_root.mkdir(parents=True)
    for file_name in ("a.pdf", "b.pdf"):
        (dataset_root / file_name).write_bytes(b"%PDF checkpoint fixture")
    db = tmp_path / "meta.db"
    _seed_db_many(db, dataset_id, ["a.pdf", "b.pdf"])
    calls = []

    def fake_extract(doc, **kwargs):
        calls.append(doc["file_name"])
        return {
            "schema": PROJECT_PDF_FILE_EXTRACT_SCHEMA,
            "file_name": doc["file_name"],
            "doc_id": doc["id"],
            "source_path": (dataset_root / doc["file_name"]).as_posix(),
            "doc_role": "проектный PDF",
            "cipher": "",
            "stage": "",
            "discipline": "",
            "layers": [],
            "artifact_paths": {},
            "source_refs": [],
            "source_refs_total": 0,
            "source_refs_truncated": False,
            "status": "ok",
            "warnings": [],
            "warnings_total": 0,
            "warnings_truncated": False,
            "sidecar_dir": "",
        }

    monkeypatch.setattr(project_pdf_extract_service, "_extract_pdf_file", fake_extract)

    first = run_project_pdf_extract(
        dataset_id,
        storage_root=storage_root,
        meta_db_path=str(db),
        max_files=1,
        max_pages=3,
        force=True,
    )
    assert first["status"] == "partial"
    assert first["coverage"]["files_attempted"] == 1
    assert first["batch"] == {"new_files": 1, "reused_files": 0, "max_new_files": 1}
    (storage_root / dataset_id / "_les_pdf_extract" / "summary.json").unlink()

    resumed = run_project_pdf_extract(
        dataset_id,
        storage_root=storage_root,
        meta_db_path=str(db),
        max_files=1,
        max_pages=3,
        force=False,
    )

    assert calls == ["a.pdf", "b.pdf"]
    assert resumed["status"] == "ok"
    assert resumed["coverage"]["files_attempted"] == 2
    assert resumed["coverage"]["files_unattempted"] == 0
    assert resumed["batch"] == {"new_files": 1, "reused_files": 1, "max_new_files": 1}

    (dataset_root / "a.pdf").write_bytes(b"%PDF changed fixture")
    changed = run_project_pdf_extract(
        dataset_id,
        storage_root=storage_root,
        meta_db_path=str(db),
        max_files=1,
        max_pages=3,
        force=False,
    )
    assert calls == ["a.pdf", "b.pdf", "a.pdf"]
    assert changed["batch"] == {"new_files": 1, "reused_files": 1, "max_new_files": 1}


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("Договор.pdf", "проектный PDF"),
        ("Состав проектной документации.pdf", "состав тома"),
        ("395.01-ИОС.СС4.ВОР.pdf", "ведомость объемов работ"),
        ("395.01-ИОС.СС4.СО.pdf", "спецификация оборудования"),
        ("395.01-ПЗУ.pdf", "проектный PDF"),
        ("395.01-ПЗ.pdf", "пояснительная записка"),
    ],
)
def test_doc_role_uses_delimited_codes_not_substrings(file_name, expected):
    assert _doc_role(file_name, {}) == expected


def test_doc_role_does_not_trust_uncorroborated_document_kind():
    fields = {"document_kind_code": "ВОР", "cipher_norm": "ДОГОВОР"}
    assert _doc_role("Договор.pdf", fields) == "проектный PDF"


@pytest.mark.parametrize(
    ("file_name", "fields", "expected"),
    [
        ("Условия подключения.pdf", {}, ""),
        ("Проверка расчётов.pdf", {}, ""),
        ("395.01-ИОС.ОВ.pdf", {}, "ОВ"),
        ("395.01-ИОС.СС4.ВОР.pdf", {}, "СС4"),
        ("Общие данные.pdf", {"subdiscipline_code": "НАЛИЧИЕ", "cipher_norm": "НАЛИЧИЕ"}, ""),
        ("Общие данные.pdf", {"subdiscipline_code": "ЭС", "cipher_norm": "395.01-ИОС.ЭС"}, "ЭС"),
    ],
)
def test_discipline_is_explicit_and_whitelisted(file_name, fields, expected):
    assert _discipline(file_name, fields) == expected


def test_project_composition_does_not_make_every_pdf_electrical():
    pd_manifest = {
        "volume_contents_register": {
            "rows": [{"designation": "ИОС.ЭС", "name": "Система электроснабжения"}],
        },
    }
    assert _looks_electrical("395.01-ОВ.pdf", {}, pd_manifest) is False
    assert _looks_electrical("395.01-ЭС.pdf", {}, pd_manifest) is True


def test_source_ref_priority_keeps_rows_before_generic_pages():
    refs = [f"file.pdf#page={page}" for page in range(1, 50)]
    refs.extend(["file.pdf#page=7#table=2#row=4", "book.xlsx!R12"])
    prioritized = _prioritize_source_refs(refs)
    assert prioritized[:2] == ["file.pdf#page=7#table=2#row=4", "book.xlsx!R12"]


def test_coverage_reports_actual_volume_rows_and_attempts():
    coverage = _coverage(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        [{"status": "ok", "doc_role": "состав тома"}, {"status": "extract_error"}],
        None,
        volume_rows=37,
    )
    assert coverage["files_attempted"] == 2
    assert coverage["files_unattempted"] == 1
    assert coverage["files_limit_truncated"] is True
    assert coverage["files_extracted"] == 1
    assert coverage["volume_rows"] == 37


def test_summary_status_is_partial_when_file_limit_skips_documents():
    docs = [{"id": "a"}, {"id": "b"}]
    assert _summary_status(docs, [{"status": "ok"}]) == "partial"


@pytest.mark.parametrize("dataset_id", ["../escape", "/tmp/escape", "a/b", ".", ""])
def test_project_pdf_extract_root_rejects_unsafe_dataset_id(tmp_path, dataset_id):
    with pytest.raises(ValueError, match="safe path component"):
        project_pdf_extract_root(dataset_id, storage_root=tmp_path)
