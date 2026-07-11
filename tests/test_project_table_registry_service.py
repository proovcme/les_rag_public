import json

import fitz
import pytest

from proxy.services.project_table_registry_service import (
    build_project_table_registry,
    read_project_table,
    search_project_tables,
)
from proxy.services.project_pdf_table_service import PROJECT_PDF_TABLE_ALGO_VERSION
from proxy.services.tool_harness_service import ToolHarness


def _make_table_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=220, height=150)
    for x in (10, 100, 210):
        page.draw_line((x, 10), (x, 110), color=(0, 0, 0), width=1)
    for y in (10, 40, 70, 110):
        page.draw_line((10, y), (210, y), color=(0, 0, 0), width=1)
    for x, y, text in (
        (15, 30, "Panel"),
        (105, 30, "Room"),
        (15, 60, "N1"),
        (105, 60, "Server"),
        (15, 90, "N2"),
        (105, 90, "Office"),
    ):
        page.insert_text((x, y), text, fontsize=8)
    doc.save(path)
    doc.close()


def test_registry_build_search_and_exact_source_read(tmp_path):
    dataset_id = "ds-tables"
    storage_root = tmp_path / "storage"
    source = tmp_path / "project" / "panel.pdf"
    source.parent.mkdir(parents=True)
    _make_table_pdf(source)
    manifest_root = storage_root / dataset_id / "_les_pdf_extract" / "panel"
    manifest_root.mkdir(parents=True)
    manifest = {
        "schema": "project_pdf_table_manifest_v1",
        "algo_version": PROJECT_PDF_TABLE_ALGO_VERSION,
        "detector_version": f"pymupdf:{fitz.VersionBind}",
        "source_path": source.as_posix(),
        "file_name": source.name,
        "pages": [
            {
                "page": 1,
                "table_type_candidates": [
                    {
                        "source_ref": f"{source.as_posix()}#page=1#table=1",
                        "semantic_type": "ELEC/CABLE_JOURNAL: панели и помещения кабельного журнала",
                        "category": "engineering",
                        "confidence": 0.92,
                        "sample": "Panel | Room / N1 | Server / N2 | Office",
                        "bbox": [10.0, 10.0, 210.0, 110.0],
                    }
                ],
            }
        ],
    }
    (manifest_root / "project_pdf_table_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    summary = build_project_table_registry(dataset_id, storage_root=storage_root)
    result = search_project_tables(dataset_id, "panel server", storage_root=storage_root)
    table_id = result["items"][0]["table_id"]
    read = read_project_table(dataset_id, table_id, storage_root=storage_root)

    assert summary["table_count"] == 1
    assert summary["normalized_sample_tables"] == 1
    assert result["returned"] == 1
    assert result["is_evidence"] is False
    assert read["is_evidence"] is True
    assert read["status"] == "ok"
    assert len(table_id) == 32
    assert read["headers"] == ["Panel", "Room"]
    assert read["rows"] == [["N1", "Server"], ["N2", "Office"]]
    assert read["normalized_rows"][0] == {"Panel": "N1", "Room": "Server"}
    assert read["source_ref"].endswith("#page=1#table=1")

    tool = ToolHarness().call(
        "search_project_tables",
        {"dataset_id": dataset_id, "q": "panel server", "storage_root": storage_root.as_posix()},
    )
    exact = ToolHarness().call(
        "read_project_table",
        {"dataset_id": dataset_id, "table_id": table_id, "storage_root": storage_root.as_posix()},
    )
    assert tool["status"] == "ok"
    assert tool["evidence"][0]["is_evidence"] is False
    assert exact["status"] == "ok"
    assert exact["evidence"][0]["is_evidence"] is True


def test_exact_read_is_stale_after_source_pdf_changes(tmp_path):
    dataset_id = "ds-stale"
    storage_root = tmp_path / "storage"
    source = tmp_path / "project" / "panel.pdf"
    source.parent.mkdir(parents=True)
    _make_table_pdf(source)
    manifest_root = storage_root / dataset_id / "_les_pdf_extract" / "panel"
    manifest_root.mkdir(parents=True)
    manifest = {
        "schema": "project_pdf_table_manifest_v1",
        "algo_version": PROJECT_PDF_TABLE_ALGO_VERSION,
        "detector_version": f"pymupdf:{fitz.VersionBind}",
        "source_path": source.as_posix(),
        "file_name": source.name,
        "pages": [{"page": 1, "table_type_candidates": [{
            "source_ref": f"{source.as_posix()}#page=1#table=1",
            "semantic_type": "ROOM: экспликации помещений",
            "category": "engineering",
            "confidence": 0.9,
            "sample": "Panel | Room / N1 | Server",
            "bbox": [10.0, 10.0, 210.0, 110.0],
        }]}],
    }
    (manifest_root / "project_pdf_table_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    build_project_table_registry(dataset_id, storage_root=storage_root)
    table_id = search_project_tables(dataset_id, "Panel", storage_root=storage_root)["items"][0]["table_id"]
    source.write_bytes(source.read_bytes() + b"\n% changed")

    read = read_project_table(dataset_id, table_id, storage_root=storage_root)

    assert read["status"] == "stale"
    assert read["reason"] == "source_document_changed"
    assert read["is_evidence"] is False
    tool = ToolHarness().call(
        "read_project_table",
        {"dataset_id": dataset_id, "table_id": table_id, "storage_root": storage_root.as_posix()},
    )
    assert tool["status"] == "blocked"
    assert tool["evidence"] == []


def test_registry_search_hides_noise_by_default(tmp_path):
    dataset_id = "ds-noise"
    root = tmp_path / "storage" / dataset_id / "_les_pdf_extract"
    manifest_root = root / "noise"
    manifest_root.mkdir(parents=True)
    manifest = {
        "source_path": "/tmp/noise.pdf",
        "file_name": "noise.pdf",
        "pages": [{"page": 1, "table_type_candidates": [{
            "source_ref": "/tmp/noise.pdf#page=1#table=1",
            "semantic_type": "NOISE: строки-нумераторы/разорванные табличные сетки",
            "category": "noise",
            "sample": "1 | 2 | 3",
        }]}],
    }
    (manifest_root / "project_pdf_table_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    build_project_table_registry(dataset_id, storage_root=tmp_path / "storage")

    assert search_project_tables(dataset_id, "1", storage_root=tmp_path / "storage")["returned"] == 0
    assert search_project_tables(
        dataset_id,
        "1",
        include_noise=True,
        storage_root=tmp_path / "storage",
    )["returned"] == 1


def test_table_reader_rejects_invalid_id(tmp_path):
    with pytest.raises(ValueError, match="table_id"):
        read_project_table("ds", "../bad", storage_root=tmp_path)
