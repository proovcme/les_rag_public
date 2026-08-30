from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import release_receipt


TARGET = "a" * 40
BASE = "b" * 40


def _attempt(tmp_path: Path, *, assets: list[Path] | None = None) -> Path:
    return release_receipt.create_attempt(
        root=tmp_path / "work",
        release_class="patch",
        product_version="0.30.8",
        build_number=648,
        target_commit=TARGET,
        base_commits=[BASE],
        host="legion",
        assets=assets or [],
    )


def _accept(path: Path) -> None:
    current = "planned"
    for target in release_receipt.STAGES[1 : release_receipt.STAGES.index("accepted") + 1]:
        release_receipt.transition(
            path,
            expected=current,
            target=target,
            evidence={"ok": True},
        )
        current = target


def test_release_attempt_rejects_skipped_transition(tmp_path):
    state = _attempt(tmp_path)

    with pytest.raises(RuntimeError, match="invalid release transition"):
        release_receipt.transition(
            state,
            expected="planned",
            target="legion_installed",
            evidence={},
        )


def test_one_byte_asset_drift_invalidates_attempt(tmp_path):
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    state = _attempt(tmp_path, assets=[asset])
    asset.write_bytes(b"Candidate")

    with pytest.raises(RuntimeError, match="artifact binding changed"):
        release_receipt.verify_binding(
            release_receipt.load_attempt(state),
            commit=TARGET,
            assets=[asset],
        )


def test_release_id_is_independent_of_the_work_directory(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "nested" / "first.zip"
    second.parent.mkdir()
    first.write_bytes(b"same")
    second.write_bytes(b"same")

    one = release_receipt.load_attempt(_attempt(tmp_path / "one", assets=[first]))
    two = release_receipt.load_attempt(_attempt(tmp_path / "two", assets=[second]))

    assert one["release_id"] == two["release_id"]


def test_failed_attempt_preserves_completed_evidence_and_cannot_be_public(tmp_path):
    state = _attempt(tmp_path)
    release_receipt.transition(
        state,
        expected="planned",
        target="prepared",
        evidence={"gates": "passed"},
    )
    failed = release_receipt.fail_attempt(
        state,
        stage="legion_install",
        error="candidate did not start",
        recovery={"rolled_back": True},
    )

    assert failed["stage"] == "failed"
    assert failed["transitions"][1]["evidence"] == {"gates": "passed"}
    with pytest.raises(RuntimeError, match="accepted release attempt required"):
        release_receipt.write_public_receipt(
            state, tmp_path / "release-receipt.json"
        )


def test_public_receipt_redacts_paths_and_sensitive_fields(tmp_path):
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    state = _attempt(tmp_path, assets=[asset])
    current = "planned"
    for target in release_receipt.STAGES[1 : release_receipt.STAGES.index("accepted") + 1]:
        evidence = (
            {
                "ok": True,
                "runtime_path": r"C:\Users\Oleg\AppData\Local\Programs\LES",
                "api_token": "secret-value",
            }
            if target == "legion_smoke_passed"
            else {"ok": True}
        )
        release_receipt.transition(
            state,
            expected=current,
            target=target,
            evidence=evidence,
        )
        current = target

    public = release_receipt.write_public_receipt(
        state, tmp_path / "release-receipt.json"
    )
    text = public.read_text(encoding="utf-8")
    payload = json.loads(text)

    assert payload["schema"] == "les.release-receipt.v1"
    assert payload["accepted"] is True
    assert "C:\\Users\\Oleg" not in text
    assert "secret-value" not in text
    assert payload["artifacts"][0].keys() == {"name", "bytes", "sha256"}


def test_public_receipt_is_deterministic_for_unchanged_attempt(tmp_path):
    state = _attempt(tmp_path)
    _accept(state)
    first = release_receipt.write_public_receipt(state, tmp_path / "first.json")
    second = release_receipt.write_public_receipt(state, tmp_path / "second.json")

    assert first.read_bytes() == second.read_bytes()


def test_non_publishable_mark_is_permanent_for_development_attempt(tmp_path):
    state = _attempt(tmp_path)
    marked = release_receipt.mark_non_publishable(
        state, reason="prepare gates were skipped"
    )

    assert marked["publishable"] is False
    assert marked["non_publishable_reason"] == "prepare gates were skipped"
    _accept(state)
    with pytest.raises(RuntimeError, match="accepted release attempt required"):
        release_receipt.write_public_receipt(
            state, tmp_path / "release-receipt.json"
        )
