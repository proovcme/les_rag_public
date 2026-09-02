from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import release_receipt


TARGET = "a" * 40
BASE = "b" * 40
TREE = "c" * 40


def _gate(tmp_path: Path) -> Path:
    return release_receipt.create_gate_receipt(
        root=tmp_path / "work",
        target_commit=TARGET,
        target_tree=TREE,
        product_version="0.30.40",
        build_number=680,
        desktop_version="5.1.680",
        branch="codex/release",
        upstream_commit=TARGET,
        policy=[("verify", ("make", "verify"))],
        results=[{"gate": "verify", "exit_code": 0, "duration_ms": 7}],
        clean=True,
    )


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


def test_checkpoint_is_persisted_without_advancing_stage_and_is_idempotent(tmp_path):
    state = _attempt(tmp_path)
    _accept(state)
    evidence = {"before": BASE, "after": TARGET, "fast_forwarded": True}

    recorded = release_receipt.record_checkpoint(
        state,
        expected="accepted",
        name="public_main_sync",
        evidence=evidence,
    )
    repeated = release_receipt.record_checkpoint(
        state,
        expected="accepted",
        name="public_main_sync",
        evidence={"before": TARGET, "after": TARGET, "fast_forwarded": False},
    )

    assert recorded["stage"] == "accepted"
    assert repeated["checkpoints"]["public_main_sync"] == evidence
    public = release_receipt.write_public_receipt(state, tmp_path / "receipt.json")
    assert json.loads(public.read_text(encoding="utf-8"))["checkpoints"] == {
        "public_main_sync": evidence
    }


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
def test_gate_receipt_reuses_only_exact_commit_tree_version_and_policy(tmp_path):
    path = _gate(tmp_path)
    receipt = release_receipt.load_gate_receipt(path)
    exact = {
        "target_commit": TARGET,
        "target_tree": TREE,
        "product_version": "0.30.40",
        "build_number": 680,
        "desktop_version": "5.1.680",
        "branch": "codex/release",
        "upstream_commit": TARGET,
        "policy": [("verify", ("make", "verify"))],
    }

    release_receipt.verify_gate_receipt(receipt, **exact)
    with pytest.raises(RuntimeError, match="gate receipt binding changed"):
        release_receipt.verify_gate_receipt(
            receipt,
            **{**exact, "target_tree": "d" * 40},
        )


def test_gate_receipt_rejects_failed_results(tmp_path):
    with pytest.raises(ValueError, match="successful gate results"):
        release_receipt.create_gate_receipt(
            root=tmp_path,
            target_commit=TARGET,
            target_tree=TREE,
            product_version="0.30.40",
            build_number=680,
            desktop_version="5.1.680",
            branch="codex/release",
            upstream_commit=TARGET,
            policy=[("verify", ("make", "verify"))],
            results=[{"gate": "verify", "exit_code": 1, "duration_ms": 7}],
            clean=True,
        )


def test_gate_receipt_creation_is_idempotent_for_same_evidence(tmp_path):
    first = _gate(tmp_path)
    first_bytes = first.read_bytes()

    second = _gate(tmp_path)

    assert second == first
    assert second.read_bytes() == first_bytes


def test_failed_acceptance_does_not_change_artifact_receipt_or_bytes(tmp_path):
    gate_path = _gate(tmp_path)
    asset = tmp_path / "LES-Setup.exe"
    asset.write_bytes(b"installer")
    artifact_path = release_receipt.create_artifact_receipt(
        root=tmp_path / "work",
        gate_receipt=gate_path,
        release_class="full",
        target_commit=TARGET,
        base_commits=[BASE],
        product_version="0.30.40",
        build_number=680,
        desktop_version="5.1.680",
        assets=[asset],
        candidate_root=tmp_path,
        acceptance_path=tmp_path,
        runtime_manifest_sha256="d" * 64,
        entrypoint_registry_sha256="e" * 64,
        build_evidence={"duration_ms": 10},
        publishable=True,
    )
    before = artifact_path.read_bytes()
    attempt_path = release_receipt.create_acceptance_attempt(
        artifact_path,
        host="local",
    )
    failed = release_receipt.fail_acceptance_attempt(
        attempt_path,
        failed_stage="smoke",
        error="injected",
        recovery={"ok": True},
    )

    assert failed["result"] == "failed"
    assert artifact_path.read_bytes() == before
    assert asset.read_bytes() == b"installer"
    assert release_receipt.accepted_attempts(artifact_path) == []


def test_artifact_verification_rejects_one_byte_drift_and_writes_revocation(tmp_path):
    gate_path = _gate(tmp_path)
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    artifact_path = release_receipt.create_artifact_receipt(
        root=tmp_path / "work",
        gate_receipt=gate_path,
        release_class="patch",
        target_commit=TARGET,
        base_commits=[BASE],
        product_version="0.30.40",
        build_number=680,
        desktop_version="5.1.680",
        assets=[asset],
        candidate_root=tmp_path,
        acceptance_path=tmp_path,
        runtime_manifest_sha256="d" * 64,
        entrypoint_registry_sha256="e" * 64,
        build_evidence={},
        publishable=True,
    )
    artifact = release_receipt.load_artifact_receipt(artifact_path)
    asset.write_bytes(b"Candidate")

    with pytest.raises(RuntimeError, match="artifact binding changed"):
        release_receipt.verify_artifact_receipt(
            artifact,
            commit=TARGET,
            assets=[asset],
        )
    revocation = release_receipt.revoke_artifact(
        artifact_path,
        reason="artifact binding changed",
    )
    assert revocation.is_file()
    assert release_receipt.load_artifact_receipt(artifact_path)["status"] == "ready"


def test_artifact_receipt_tampering_is_detected_before_acceptance(tmp_path):
    gate_path = _gate(tmp_path)
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    artifact_path = release_receipt.create_artifact_receipt(
        root=tmp_path / "work",
        gate_receipt=gate_path,
        release_class="patch",
        target_commit=TARGET,
        base_commits=[BASE],
        product_version="0.30.40",
        build_number=680,
        desktop_version="5.1.680",
        assets=[asset],
        candidate_root=tmp_path,
        acceptance_path=tmp_path,
        runtime_manifest_sha256="d" * 64,
        entrypoint_registry_sha256="e" * 64,
        build_evidence={},
        publishable=True,
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["build_number"] = 681
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="integrity check failed"):
        release_receipt.load_artifact_receipt(artifact_path)


def test_only_successful_attempt_is_returned_for_publication(tmp_path):
    gate_path = _gate(tmp_path)
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    artifact_path = release_receipt.create_artifact_receipt(
        root=tmp_path / "work",
        gate_receipt=gate_path,
        release_class="patch",
        target_commit=TARGET,
        base_commits=[BASE],
        product_version="0.30.40",
        build_number=680,
        desktop_version="5.1.680",
        assets=[asset],
        candidate_root=tmp_path,
        acceptance_path=tmp_path,
        runtime_manifest_sha256="d" * 64,
        entrypoint_registry_sha256="e" * 64,
        build_evidence={},
        publishable=True,
    )
    failed_path = release_receipt.create_acceptance_attempt(artifact_path, host="local")
    release_receipt.fail_acceptance_attempt(
        failed_path,
        failed_stage="smoke",
        error="no",
        recovery={"ok": True},
    )
    accepted_path = release_receipt.create_acceptance_attempt(
        artifact_path,
        host="local",
        retry_of=json.loads(failed_path.read_text(encoding="utf-8"))["acceptance_id"],
    )
    accepted = release_receipt.complete_acceptance_attempt(
        accepted_path,
        evidence={"accepted": True, "final_identity": {"target_commit": TARGET}},
    )

    assert release_receipt.accepted_attempts(artifact_path) == [accepted]


def test_public_artifact_receipt_binds_only_successful_acceptance(tmp_path):
    gate_path = _gate(tmp_path)
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    artifact_path = release_receipt.create_artifact_receipt(
        root=tmp_path / "work",
        gate_receipt=gate_path,
        release_class="patch",
        target_commit=TARGET,
        base_commits=[BASE],
        product_version="0.30.40",
        build_number=680,
        desktop_version="5.1.680",
        assets=[asset],
        candidate_root=tmp_path,
        acceptance_path=tmp_path,
        runtime_manifest_sha256="d" * 64,
        entrypoint_registry_sha256="e" * 64,
        build_evidence={},
        publishable=True,
    )
    attempt_path = release_receipt.create_acceptance_attempt(
        artifact_path, host="Legion"
    )
    accepted = release_receipt.complete_acceptance_attempt(
        attempt_path,
        evidence={
            "accepted": True,
            "final_identity": {"target_commit": TARGET},
            "runtime": r"C:\Users\Oleg\AppData\Local\LES",
            "api_token": "must-not-leak",
        },
    )

    destination = tmp_path / "release-receipt.json"
    release_receipt.write_public_artifact_receipt(
        artifact_path, attempt_path, destination
    )
    public = json.loads(destination.read_text(encoding="utf-8"))

    assert public["schema"] == release_receipt.PUBLIC_ARTIFACT_SCHEMA
    assert public["artifact_id"] == accepted["artifact_id"]
    assert public["acceptance_id"] == accepted["acceptance_id"]
    assert public["evidence"]["runtime"] == "[redacted-path]"
    assert public["evidence"]["api_token"] == "[redacted]"
    assert "artifact_path" not in public


def test_public_artifact_receipt_rejects_failed_acceptance(tmp_path):
    gate_path = _gate(tmp_path)
    asset = tmp_path / "les-patch.zip"
    asset.write_bytes(b"candidate")
    artifact_path = release_receipt.create_artifact_receipt(
        root=tmp_path / "work",
        gate_receipt=gate_path,
        release_class="patch",
        target_commit=TARGET,
        base_commits=[BASE],
        product_version="0.30.40",
        build_number=680,
        desktop_version="5.1.680",
        assets=[asset],
        candidate_root=tmp_path,
        acceptance_path=tmp_path,
        runtime_manifest_sha256="d" * 64,
        entrypoint_registry_sha256="e" * 64,
        build_evidence={},
        publishable=True,
    )
    attempt_path = release_receipt.create_acceptance_attempt(
        artifact_path, host="Legion"
    )
    release_receipt.fail_acceptance_attempt(
        attempt_path, failed_stage="smoke", error="no", recovery={}
    )

    with pytest.raises(RuntimeError, match="successful acceptance required"):
        release_receipt.write_public_artifact_receipt(
            artifact_path, attempt_path, tmp_path / "release-receipt.json"
        )
