from __future__ import annotations

from pathlib import Path

import pytest

from tools import windows_release_acceptance as acceptance


TARGET = {
    "product_version": "0.30.8",
    "build_number": 648,
    "target_commit": "b" * 40,
}
STARTING = {
    "product_version": "0.30.0",
    "build_number": 634,
    "target_commit": "a" * 40,
    "capabilities": {"core": True, "qdrant": True, "answer": False, "embedding": True},
}


def _patch_dependencies(monkeypatch, calls):
    installs = iter(
        [
            {"backup_root": "backup", "target_commit": TARGET["target_commit"]},
            {"backup_root": "backup-2", "target_commit": TARGET["target_commit"]},
        ]
    )
    monkeypatch.setattr(
        acceptance,
        "snapshot_installed",
        lambda *_args, **_kwargs: STARTING,
    )
    monkeypatch.setattr(
        acceptance,
        "install_patch",
        lambda **_kwargs: calls.append("install") or next(installs),
    )
    monkeypatch.setattr(
        acceptance,
        "installed_smoke",
        lambda **kwargs: calls.append(f"smoke:{kwargs['expected']['target_commit'][0]}")
        or {"ok": True, "capabilities": STARTING["capabilities"]},
    )
    monkeypatch.setattr(
        acceptance,
        "rollback_patch",
        lambda **_kwargs: calls.append("rollback") or {"state": "rolled_back"},
    )


def test_patch_acceptance_orders_install_smoke_rollback_reinstall(
    monkeypatch, tmp_path
):
    calls = []
    _patch_dependencies(monkeypatch, calls)

    result = acceptance.accept_patch(
        package_dir=tmp_path / "candidate",
        runtime=tmp_path / "Programs" / "LES" / "runtime",
        state=tmp_path / "State" / "LES",
        expected=TARGET,
    )

    assert calls == [
        "install",
        "smoke:b",
        "rollback",
        "smoke:a",
        "install",
        "smoke:b",
    ]
    assert result["accepted"] is True
    assert result["starting_identity"]["target_commit"] == "a" * 40
    assert result["final_identity"]["target_commit"] == "b" * 40


def test_patch_acceptance_rolls_back_and_stops_when_first_smoke_fails(
    monkeypatch, tmp_path
):
    calls = []
    _patch_dependencies(monkeypatch, calls)
    monkeypatch.setattr(
        acceptance,
        "installed_smoke",
        lambda **_kwargs: calls.append("smoke")
        or (_ for _ in ()).throw(RuntimeError("candidate unhealthy")),
    )

    with pytest.raises(RuntimeError, match="candidate unhealthy"):
        acceptance.accept_patch(
            package_dir=tmp_path / "candidate",
            runtime=tmp_path / "Programs" / "LES" / "runtime",
            state=tmp_path / "State" / "LES",
            expected=TARGET,
        )
    assert calls == ["install", "smoke", "rollback"]


def test_capability_continuity_rejects_a_lost_previously_available_role():
    after = {**STARTING, "capabilities": {**STARTING["capabilities"], "qdrant": False}}

    with pytest.raises(RuntimeError, match="capability disappeared: qdrant"):
        acceptance.require_capability_continuity(STARTING, after)


def test_capability_continuity_allows_a_role_that_was_already_unavailable():
    after = {**STARTING, "capabilities": {**STARTING["capabilities"], "answer": False}}

    acceptance.require_capability_continuity(STARTING, after)


def test_snapshot_never_claims_model_capabilities_when_core_is_down(
    monkeypatch, tmp_path
):
    runtime = tmp_path / "Programs" / "LES" / "runtime"
    state = tmp_path / "State" / "LES"
    (runtime / "config").mkdir(parents=True)
    state.mkdir(parents=True)
    (runtime / "config" / "version.json").write_text(
        '{"product_version":"0.30.0","build_number":634}', encoding="utf-8"
    )
    (runtime / ".les_deploy_stamp.json").write_text(
        '{"deployed_commit":"' + "a" * 40 + '"}', encoding="utf-8"
    )

    def fake_request(url, **_kwargs):
        if url.endswith("/api/version"):
            return {"deployed_commit": "a" * 40}
        if url.endswith("/api/health"):
            return {
                "status": "error",
                "backend": "qdrant_llama",
                "embedding": {"embedding_model": "configured"},
            }
        return {"proxy": {"llm_provider": {"model": "configured"}}}

    monkeypatch.setattr(acceptance, "_request_json", fake_request)
    monkeypatch.setattr(acceptance, "_ui_ready", lambda: True)

    snapshot = acceptance.snapshot_installed(runtime, state)

    assert snapshot["capabilities"] == {
        "core": False,
        "qdrant": False,
        "answer": False,
        "embedding": False,
    }


def test_full_acceptance_uses_same_install_rollback_reinstall_sequence(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(acceptance, "snapshot_installed", lambda *_a, **_k: STARTING)
    monkeypatch.setattr(
        acceptance.windows_update_engine,
        "runtime_root",
        lambda install: Path(install) / "runtime",
    )
    monkeypatch.setattr(
        acceptance,
        "install_full",
        lambda **_kwargs: calls.append("install")
        or {"recovery_root": "recovery", "target_commit": TARGET["target_commit"]},
    )
    monkeypatch.setattr(
        acceptance,
        "installed_smoke",
        lambda **kwargs: calls.append(f"smoke:{kwargs['expected']['target_commit'][0]}")
        or {"ok": True, "capabilities": STARTING["capabilities"]},
    )
    monkeypatch.setattr(
        acceptance,
        "rollback_full",
        lambda **_kwargs: calls.append("rollback") or {"state": "rolled_back"},
    )

    result = acceptance.accept_full(
        job_path=tmp_path / "hard-job.json",
        install=tmp_path / "Programs" / "LES",
        state=tmp_path / "State" / "LES",
        expected=TARGET,
    )

    assert calls == [
        "install",
        "smoke:b",
        "rollback",
        "smoke:a",
        "install",
        "smoke:b",
    ]
    assert result["accepted"] is True
