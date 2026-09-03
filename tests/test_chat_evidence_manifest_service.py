from __future__ import annotations

from types import SimpleNamespace

from proxy.services.chat_evidence_manifest_service import (
    build_evidence_manifest,
    compact_prior_evidence_index,
    format_prior_evidence_index,
)


def _chunk(ref: str, code: str):
    return SimpleNamespace(
        content=f"FULL EVIDENCE BODY {code}",
        doc_name="smeta_norm_cards.v1",
        doc_id="",
        score=0.8,
        meta={
            "dataset_id": "smeta",
            "model_evidence_ref": ref,
            "norm_code": code,
            "source_ref": f"fsnb#norm={code}",
        },
    )


def test_manifest_freezes_actual_model_visible_handles_scope_and_citations():
    scope = {"dataset_ids": ["smeta"], "selected_sources_only": True}
    chunks = [_chunk("Q1.H1", "ГЭСН01"), _chunk("Q1.H2", "ГЭСН02")]

    manifest = build_evidence_manifest(
        query="подбор норм",
        scope=scope,
        chunks=chunks,
        answer="Выбрано Q1.H2.",
    )
    scope["dataset_ids"].append("mutated")
    chunks[1].meta["norm_code"] = "MUTATED"

    assert manifest["schema"] == "les.chat-evidence-manifest.v1"
    assert manifest["scope"] == {
        "dataset_ids": ["smeta"],
        "selected_sources_only": True,
    }
    assert [item["id"] for item in manifest["model_visible"]] == ["Q1.H1", "Q1.H2"]
    assert manifest["cited_ids"] == ["Q1.H2"]
    assert manifest["model_visible"][1]["locator"]["card_code"] == "ГЭСН02"


def test_manifest_accepts_model_written_source_ranges():
    chunks = [_chunk(f"Q1.H{index}", f"ГЭСН0{index}") for index in range(1, 5)]

    manifest = build_evidence_manifest(
        query="подбор норм",
        scope={"dataset_ids": ["smeta"]},
        chunks=chunks,
        answer="Использованы [Источник 1–4].",
    )

    assert manifest["cited_ids"] == ["Q1.H1", "Q1.H2", "Q1.H3", "Q1.H4"]


def test_compact_prior_index_keeps_locators_but_not_full_evidence_bodies():
    manifest = build_evidence_manifest(
        query="подбор норм",
        scope={"dataset_ids": ["smeta"]},
        chunks=[_chunk("Q1.H1", "ГЭСН01")],
        answer="Q1.H1",
    )

    compact = compact_prior_evidence_index([manifest], max_items=24)
    rendered = format_prior_evidence_index(compact)

    assert compact[0]["id"] == "Q1.H1"
    assert compact[0]["locator"]["card_code"] == "ГЭСН01"
    assert "FULL EVIDENCE BODY" not in str(compact)
    assert "FULL EVIDENCE BODY" not in rendered
    assert "Q1.H1" in rendered
