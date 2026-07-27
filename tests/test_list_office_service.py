"""Л.И.С.Т. Студия: append-only офисные ревизии и provenance."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture()
def studio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    forms_dir = tmp_path / "forms"
    forms_dir.mkdir()
    (forms_dir / "letter.yaml").write_text(
        "id: letter\n"
        "title: Техническое письмо\n"
        "legal_basis: Шаблон организации\n"
        "fields:\n"
        "  - { key: object_name, label: Объект, source: manual }\n"
        "  - { key: subject, label: Тема, source: manual }\n"
        "  - { key: today, label: Дата, source: date.today }\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LES_FORMS_DIR", str(forms_dir))
    monkeypatch.setenv("LES_LIST_OFFICE_DIR", str(tmp_path / "list_office"))
    import proxy.services.forms_service as forms_service
    import proxy.services.list_office_service as list_office_service

    importlib.reload(forms_service)
    return importlib.reload(list_office_service)


def test_create_draft_keeps_source_untouched_and_records_evidence(studio, tmp_path: Path):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"immutable source")

    draft = studio.create_draft(
        "letter",
        "docx",
        manual={"object_name": "БЦ Север", "subject": "Согласование"},
        dataset_id="PROJECT_Index",
        source_refs=[{
            "dataset_id": "PROJECT_Index",
            "doc_id": "doc-1",
            "file_name": original.name,
            "source_ref": "original.pdf#page=3",
        }],
    )

    assert original.read_bytes() == b"immutable source"
    assert draft["schema"] == "list.office_artifact.v1"
    assert draft["immutable"] is True
    assert draft["originals_modified"] is False
    assert draft["source_refs"][0]["source_ref"] == "original.pdf#page=3"
    artifact = studio.artifact_file(draft["revision_id"])
    assert artifact is not None
    assert artifact[0].suffix == ".docx"
    assert artifact[0] != original


def test_new_revision_is_append_only(studio):
    first = studio.create_draft("letter", "xlsx", manual={"object_name": "А"})
    second = studio.create_draft(
        "letter",
        "xlsx",
        document_id=first["document_id"],
        manual={"object_name": "Б"},
    )

    assert first["revision_no"] == 1
    assert second["revision_no"] == 2
    assert first["revision_id"] != second["revision_id"]
    assert len(studio.list_artifacts()) == 2
    assert studio.artifact_file(first["revision_id"]) is not None
    assert studio.artifact_file(second["revision_id"]) is not None


def test_missing_fields_are_visible_and_tamper_fails_closed(studio):
    draft = studio.create_draft("letter", "docx", manual={})
    assert {item["key"] for item in draft["missing_fields"]} == {"object_name", "subject"}

    target, _manifest = studio.artifact_file(draft["revision_id"])
    target.write_bytes(b"tampered")
    assert studio.artifact_file(draft["revision_id"]) is None


def test_rejects_unsupported_format_and_invalid_document_id(studio):
    with pytest.raises(ValueError, match="DOCX"):
        studio.create_draft("letter", "pdf")
    with pytest.raises(ValueError, match="document_id"):
        studio.create_draft("letter", "docx", document_id="../escape")


def test_office_artifact_routes_are_registered_before_generic_form_routes():
    from proxy.routers.forms import router

    paths = [route.path for route in router.routes]
    assert "/api/forms/artifacts" in paths
    assert "/api/forms/artifacts/{revision_id}/download" in paths
    assert paths.index("/api/forms/artifacts") < paths.index("/api/forms/{form_id}/fields")


def test_failed_render_does_not_publish_partial_revision(studio, monkeypatch: pytest.MonkeyPatch):
    def fail_generate(*_args, **_kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(studio.forms_service, "generate", fail_generate)
    with pytest.raises(RuntimeError, match="render failed"):
        studio.create_draft("letter", "docx")

    assert studio.list_artifacts() == []
    assert not list(studio._documents_dir().glob("*/revisions/.*.tmp"))
