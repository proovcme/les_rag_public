"""Active source adapters must not depend on the retired unified harness."""

from __future__ import annotations

import builtins

from proxy.services import source_adapters


def test_file_body_filter_uses_standalone_document_classifier(tmp_path, monkeypatch):
    dataset = tmp_path / "project"
    dataset.mkdir()
    (dataset / "Спецификация оборудования.txt").write_text(
        "Котёл указан в спецификации.",
        encoding="utf-8",
    )

    real_import = builtins.__import__

    def reject_retired_harness(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "proxy.services.unified_construction_harness_service":
            raise ImportError("retired unified harness is unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", reject_retired_harness)

    result = source_adapters.search_file_body(
        ["котёл"],
        dataset_ids=["project"],
        storage_root=tmp_path,
        doc_type_filter={"specification"},
    )

    assert result.status == source_adapters.FOUND
    assert result.matches[0].source_ref.endswith("Спецификация оборудования.txt#L1")
