from __future__ import annotations

import hashlib

import pytest

from proxy.services.canonical_promotion_service import (
    CanonicalPromotionError,
    accept_promotion_report,
    load_exact_promotion_receipt,
    resolve_promoted_route,
)
from proxy.services.canonical_route_service import CanonicalRouteMode


def _revision(*, revision_id: str, revision_no: int, content: bytes, parent: str | None):
    digest = hashlib.sha256(content).hexdigest()
    return {
        "artifact_id": "art_123",
        "revision_id": revision_id,
        "revision_no": revision_no,
        "parent_revision_id": parent,
        "sha256": digest,
        "download_sha256": digest,
        "byte_size": len(content),
        "source_scope": ["attachment:read_123456abcdef"],
        "profile_revision_id": "profile:7",
        "model_identity": "qwen3.5:9b",
        "model_preset": "qwen-9b-restrictive",
        "decision_checkpoint_id": f"cp-{revision_no}",
        "missing_count": 0,
        "blocker_count": 0,
        "visible_sheet_count": 1,
        "header_cell_count": 2,
        "data_row_count": 1,
    }


def _report() -> dict:
    return {
        "schema": "les.live_workbook_acceptance.v1",
        "evidence_kind": "live_runtime",
        "runtime": {
            "source_commit_full": "a" * 40,
            "build_number": 624,
            "runtime_alignment": "aligned",
            "profile_revision_id": "profile:7",
            "model_preset": "qwen-9b",
            "observed_model_preset": "qwen-9b-restrictive",
            "model_identity": "qwen3.5:9b",
        },
        "attachment": {
            "attachment_id": "read_123456abcdef",
            "sha256": hashlib.sha256(b"source").hexdigest(),
        },
        "revision_1": _revision(
            revision_id="rev_1", revision_no=1, content=b"one", parent=None
        ),
        "revision_2": _revision(
            revision_id="rev_2", revision_no=2, content=b"two", parent="rev_1"
        ),
        "elapsed_seconds": 1.25,
    }


def test_accept_report_is_append_only_and_loads_only_exact_runtime(tmp_path) -> None:
    db = tmp_path / "meta.db"
    receipt = accept_promotion_report(
        db,
        _report(),
        operator_confirmed=True,
        actor="admin:test",
    )

    assert receipt.passed is True
    assert len(receipt.acceptance_sha256) == 64
    assert load_exact_promotion_receipt(
        db,
        source_commit="a" * 40,
        build_number=624,
        preset_id="qwen-9b-restrictive",
        observed_model_identity="qwen3.5:9b",
    ) == receipt
    assert load_exact_promotion_receipt(
        db,
        source_commit="b" * 40,
        build_number=624,
        preset_id="qwen-9b-restrictive",
        observed_model_identity="qwen3.5:9b",
    ) is None


def test_accept_report_requires_explicit_operator_confirmation(tmp_path) -> None:
    with pytest.raises(CanonicalPromotionError, match="OPERATOR_CONFIRMATION_REQUIRED"):
        accept_promotion_report(
            tmp_path / "meta.db",
            _report(),
            operator_confirmed=False,
            actor="admin:test",
        )


def test_only_real_9b_live_report_can_be_accepted(tmp_path) -> None:
    report = _report()
    report["runtime"]["model_preset"] = "qwen-35b"
    report["runtime"]["observed_model_preset"] = "qwen-35b-extended"
    report["runtime"]["model_identity"] = "qwen3.5:35b"
    report["revision_1"]["model_identity"] = "qwen3.5:35b"
    report["revision_2"]["model_identity"] = "qwen3.5:35b"
    report["revision_1"]["model_preset"] = "qwen-35b-extended"
    report["revision_2"]["model_preset"] = "qwen-35b-extended"

    with pytest.raises(CanonicalPromotionError, match="NINE_B_PRESET_REQUIRED"):
        accept_promotion_report(
            tmp_path / "meta.db",
            report,
            operator_confirmed=True,
            actor="admin:test",
        )


def test_explicit_active_uses_exact_stored_receipt(tmp_path, monkeypatch) -> None:
    db = tmp_path / "meta.db"
    receipt = accept_promotion_report(
        db, _report(), operator_confirmed=True, actor="admin:test"
    )

    class Preset:
        preset_id = "qwen-9b-restrictive"

    class Connection:
        model_id = "qwen3.5:9b"
        effective_preset = Preset()

    class Resolver:
        def resolve(self, _role):
            return Connection()

    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "active")
    decision = resolve_promoted_route(
        resolver=Resolver(),
        db_path=db,
        runtime_identity={"git_commit_full": "a" * 40, "build_number": 624},
    )

    assert receipt.passed is True
    assert decision.effective is CanonicalRouteMode.ACTIVE
    assert decision.reason == "promotion_receipt_exact"


def test_active_stays_shadow_when_model_binding_changed(tmp_path, monkeypatch) -> None:
    db = tmp_path / "meta.db"
    accept_promotion_report(db, _report(), operator_confirmed=True, actor="admin:test")

    class Preset:
        preset_id = "qwen-9b-restrictive"

    class Connection:
        model_id = "different-model"
        effective_preset = Preset()

    class Resolver:
        def resolve(self, _role):
            return Connection()

    monkeypatch.setenv("LES_CANONICAL_AGENT_ROUTE_MODE", "active")
    decision = resolve_promoted_route(
        resolver=Resolver(),
        db_path=db,
        runtime_identity={"git_commit_full": "a" * 40, "build_number": 624},
    )

    assert decision.effective is CanonicalRouteMode.SHADOW
