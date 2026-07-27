import json
import sqlite3

from proxy.services.project_document_registry_service import (
    assemble_virtual_volume,
    build_project_document_registry,
)
from proxy.services.tool_harness_service import ToolHarness


def _seed_documents(path, dataset_id, rows):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO datasets VALUES (?, ?)", (dataset_id, "Рабочая документация ИЦ"))
        conn.execute("CREATE TABLE les_projects (id INTEGER PRIMARY KEY, name TEXT, code TEXT, address TEXT, status TEXT)")
        conn.execute("INSERT INTO les_projects VALUES (1, 'Инновационный центр', '395.01/B481', 'Санкт-Петербург', 'active')")
        conn.execute("CREATE TABLE les_project_links (id INTEGER PRIMARY KEY, project_id INTEGER, kind TEXT, ref TEXT)")
        conn.execute("INSERT INTO les_project_links VALUES (1, 1, 'dataset', ?)", (dataset_id,))
        conn.execute(
            """
            CREATE TABLE documents (
                id TEXT, dataset_id TEXT, file_name TEXT, status TEXT, chunk_count INTEGER,
                doc_type TEXT, content_type TEXT, domain TEXT, pipeline TEXT, source_path TEXT
            )
            """
        )
        conn.executemany("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def test_document_registry_classifies_and_assembles_virtual_volume(tmp_path):
    dataset_id = "ds-docs"
    source_root = tmp_path / "source"
    ar_pdf = source_root / "АР" / "PDF" / "395.01-B481.120100.1.6-АР.pdf"
    ar_cover = source_root / "АР" / "Редактируемая версия" / "Раздел АР (обложка + титул).pdf"
    ar_xlsx = source_root / "АР" / "Редактируемая версия" / "395_01_AR_SO.xlsx"
    ov_pdf = source_root / "ОВ" / "PDF" / "395.01-B481.120100.1.6-ОВ.pdf"
    kp_xlsx = source_root / "Сметы" / "КП оборудование.xlsx"
    for path in (ar_pdf, ar_cover, ar_xlsx, ov_pdf, kp_xlsx):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    db = tmp_path / "meta.db"
    rows = [
        ("ar-pdf", dataset_id, "АР/PDF/395.01-B481.120100.1.6-АР.pdf", "PENDING", 0, "DOCUMENT", "", "", "", ar_pdf.as_posix()),
        ("ar-cover", dataset_id, "АР/Редактируемая версия/Раздел АР (обложка + титул).pdf", "PENDING", 0, "DOCUMENT", "", "", "", ar_cover.as_posix()),
        ("ar-xlsx", dataset_id, "АР/Редактируемая версия/395_01_AR_SO.xlsx", "PENDING", 0, "TABLE", "", "", "", ar_xlsx.as_posix()),
        ("ov-pdf", dataset_id, "ОВ/PDF/395.01-B481.120100.1.6-ОВ.pdf", "PENDING", 0, "DOCUMENT", "", "", "", ov_pdf.as_posix()),
        ("kp-xlsx", dataset_id, "Сметы/КП оборудование.xlsx", "PENDING", 0, "TABLE", "", "", "", kp_xlsx.as_posix()),
    ]
    _seed_documents(db, dataset_id, rows)
    extract_root = tmp_path / "storage" / dataset_id / "_les_pdf_extract"
    extract_root.mkdir(parents=True)
    drawing_path = extract_root / "ar" / "drawing_manifest.json"
    drawing_path.parent.mkdir()
    drawing_path.write_text(
        json.dumps({
            "page_count": 42,
            "fields": {
                "cipher_norm": "395.01/B481.120100.1.6-АР",
                "discipline_code": "АР",
                    "stage": "Р",
                    "sheet_no": "1",
                    "sheet_count": "6000",
                    "declared_format": "А1",
            },
        }),
        encoding="utf-8",
    )
    summary = {
        "files": [{
            "doc_id": "ar-pdf",
            "file_name": ar_pdf.name,
            "source_path": ar_pdf.as_posix(),
            "artifact_paths": {"drawing_manifest": drawing_path.as_posix()},
            "cipher": "395.01/B481.120100.1.6-АР",
            "discipline": "АР",
        }],
        "volume_register": [{
            "designation": "1-10",
            "name": "Ведомость рабочих чертежей",
            "source_ref": f"{ar_pdf.name}#page=3:volume_contents",
        }]
    }
    (extract_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    registry = build_project_document_registry(
        dataset_id,
        storage_root=tmp_path / "storage",
        meta_db_path=str(db),
    )
    assembled = assemble_virtual_volume(dataset_id, "АР", storage_root=tmp_path / "storage")

    assert registry["document_count"] == 5
    assert registry["volume_count"] == 2
    assert registry["role_counts"]["primary_volume"] == 2
    assert registry["role_counts"]["cover_title"] == 1
    ar_record = next(item for item in registry["documents"] if item["document_id"] == "ar-pdf")
    assert ar_record["index"] == "395.01/B481.120100.1.6-АР"
    assert ar_record["marka"] == "АР"
    assert ar_record["stage"] == "РД"
    assert ar_record["sheet_no"] == "1"
    assert ar_record["sheet_count"] == ""
    assert ar_record["page_count"] == 42
    assert ar_record["classification"]["stage_source"] == "drawing_manifest"
    assert ar_record["ingestion"]["doc_type"] == "DOCUMENT"
    documentation = registry["documentation"]
    assert documentation["project_count"] == 1
    assert documentation["projects"][0]["project_id"] == 1
    assert documentation["projects"][0]["association_basis"] == "les_project_dataset_link"
    assert documentation["related_entity_count"] == 1
    assert documentation["related_entities"][0]["related_kind"] == "commercial_offer"
    assert {stage["stage"] for stage in documentation["projects"][0]["stages"]} == {"РД"}
    ov_record = next(item for item in registry["documents"] if item["document_id"] == "ov-pdf")
    assert ov_record["stage"] == "РД"
    assert ov_record["classification"]["stage_source"] == "dataset_name"
    assert "sheets" not in registry["volumes"][0]["components"][0]
    assert "source_path" not in registry["documentation"]["projects"][0]["stages"][0]["volumes"][0]["sections"][0]["documents"][0]
    assert assembled["components"][0]["source_path"]
    assert assembled["status"] == "complete"
    assert assembled["volume"]["volume_key"] == "АР"
    assert [item["assembly_role"] for item in assembled["components"]][:2] == ["cover_title", "primary_volume"]
    assert assembled["volume"]["volume_register_count"] == 1
    assert assembled["is_evidence"] is False
    tool = ToolHarness().call(
        "assemble_project_volume",
        {"dataset_id": dataset_id, "index": "АР", "storage_root": (tmp_path / "storage").as_posix()},
    )
    assert tool["status"] == "ok"
    assert tool["result"]["volume"]["volume_key"] == "АР"
    assert tool["evidence"][0]["is_evidence"] is False


def test_virtual_volume_reports_missing_index(tmp_path):
    root = tmp_path / "storage" / "ds" / "_les_pdf_extract"
    root.mkdir(parents=True)
    (root / "document_registry.json").write_text(
        json.dumps({"schema": "project_document_registry_v1", "volumes": []}),
        encoding="utf-8",
    )

    result = assemble_virtual_volume("ds", "НЕИЗВЕСТНЫЙ", storage_root=tmp_path / "storage")

    assert result["status"] == "missing"
    assert result["components"] == []


def test_flat_folder_groups_volumes_by_cipher_not_directory(tmp_path):
    dataset_id = "flat-docs"
    source = tmp_path / "incoming"
    paths = []
    rows = []
    for discipline in ("АР", "ОВ"):
        path = source / f"395.01-B481.120100.1.6-{discipline}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        paths.append(path)
        rows.append((discipline, dataset_id, path.name, "PENDING", 0, "DOCUMENT", "", "", "", path.as_posix()))
    db = tmp_path / "meta.db"
    _seed_documents(db, dataset_id, rows)
    extract_root = tmp_path / "storage" / dataset_id / "_les_pdf_extract"
    extract_root.mkdir(parents=True)
    (extract_root / "summary.json").write_text(json.dumps({"files": [], "volume_register": []}), encoding="utf-8")

    registry = build_project_document_registry(dataset_id, storage_root=tmp_path / "storage", meta_db_path=str(db))

    assert registry["volume_count"] == 2
    assert {volume["index"] for volume in registry["volumes"]} == {
        "395.01-B481.120100.1.6-АР",
        "395.01-B481.120100.1.6-ОВ",
    }
    assert all(volume["status"] == "complete" for volume in registry["volumes"])
    assert all(volume["association_basis"] == "cipher_exact" for volume in registry["volumes"])
