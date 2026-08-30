from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path

import pytest

from tools import release_orchestrator, release_receipt
from tools.release_classification import ReleaseClassification


TARGET = "b" * 40
BASE = "a" * 40


def _args(tmp_path: Path, **overrides):
    values = {
        "root": tmp_path / "repo",
        "work_root": tmp_path / "release-work",
        "branch": "codex/release",
        "target": "HEAD",
        "base": BASE,
        "host": "legion",
        "full_feed": tmp_path / "latest.json",
        "skip_gates": False,
        "runtime": tmp_path / "Programs" / "LES" / "runtime",
        "state": tmp_path / "State" / "LES",
        "install": tmp_path / "Programs" / "LES",
        "repo_root": r"C:\Users\Oleg\les_rag",
        "attempt": None,
    }
    values.update(overrides)
    values["root"].mkdir(parents=True, exist_ok=True)
    return argparse.Namespace(**values)


def _patch_classification():
    return ReleaseClassification(
        kind="patch",
        runtime_files=("proxy/example.py",),
        triggers=(),
        ignored_version_surfaces=(),
    )


def test_prepare_selects_patch_without_calling_full_builder(monkeypatch, tmp_path):
    args = _args(tmp_path)
    args.full_feed.write_text(
        json.dumps({"target_commit": BASE, "version": "0.30.0"}),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        release_orchestrator,
        "require_release_source",
        lambda **_kwargs: TARGET,
    )
    monkeypatch.setattr(
        release_orchestrator,
        "resolve_commit",
        lambda _root, value="HEAD": BASE if value == BASE else TARGET,
    )
    monkeypatch.setattr(
        release_orchestrator,
        "load_contract",
        lambda _root: {"product_version": "0.30.8", "build_number": 648},
    )
    monkeypatch.setattr(
        release_orchestrator,
        "classify_release",
        lambda *_args, **_kwargs: _patch_classification(),
    )
    monkeypatch.setattr(
        release_orchestrator,
        "run_prepare_gates",
        lambda _root: [{"command": "gates", "exit_code": 0}],
    )

    def patch_builder(**kwargs):
        calls.append("patch")
        public = kwargs["output"] / "public"
        acceptance = kwargs["output"] / "acceptance"
        public.mkdir(parents=True)
        acceptance.mkdir(parents=True)
        archive = public / "les-patch.zip"
        archive.write_bytes(b"exact-candidate")
        (public / "les-update.json").write_text("{}", encoding="utf-8")
        (acceptance / "les-patch.zip").write_bytes(archive.read_bytes())
        (acceptance / "latest.json").write_text("{}", encoding="utf-8")
        return {
            "assets": sorted(public.iterdir()),
            "candidate_assets": [archive],
            "acceptance_path": acceptance,
        }

    monkeypatch.setattr(release_orchestrator, "build_patch_candidate", patch_builder)
    monkeypatch.setattr(
        release_orchestrator,
        "build_full_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("full builder called")),
    )

    result = release_orchestrator.prepare(args)

    assert calls == ["patch"]
    assert result["release_class"] == "patch"
    assert result["stage"] == "prepared"
    assert Path(result["state_path"]).is_file()
    assert [item["name"] for item in result["artifacts"]] == ["les-patch.zip"]


def test_accept_uses_prepared_bytes_without_rebuilding(monkeypatch, tmp_path):
    args = _args(tmp_path)
    public = tmp_path / "candidate" / "public"
    acceptance = tmp_path / "candidate" / "acceptance"
    public.mkdir(parents=True)
    acceptance.mkdir(parents=True)
    archive = public / "les-patch.zip"
    archive.write_bytes(b"exact-candidate")
    (acceptance / "les-patch.zip").write_bytes(archive.read_bytes())
    (acceptance / "latest.json").write_text("{}", encoding="utf-8")
    state_path = release_receipt.create_attempt(
        root=args.work_root / "attempts",
        release_class="patch",
        product_version="0.30.8",
        build_number=648,
        target_commit=TARGET,
        base_commits=[BASE],
        host="legion",
        assets=[archive],
    )
    release_receipt.transition(
        state_path,
        expected="planned",
        target="prepared",
        evidence={"acceptance_path": str(acceptance), "gates": []},
    )
    args.attempt = state_path
    monkeypatch.setattr(release_orchestrator, "resolve_commit", lambda *_args: TARGET)
    monkeypatch.setattr(release_orchestrator, "is_local_host", lambda _host: True)
    monkeypatch.setattr(
        release_orchestrator,
        "build_patch_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("candidate rebuilt")),
    )
    monkeypatch.setattr(
        release_orchestrator,
        "run_local_acceptance",
        lambda **kwargs: {
            "accepted": True,
            "release_class": "patch",
            "starting_identity": {"target_commit": BASE},
            "first_install": {"target_commit": TARGET},
            "first_smoke": {"ok": True},
            "rollback": {"state": "rolled_back"},
            "restored_smoke": {"ok": True},
            "second_install": {"target_commit": TARGET},
            "final_smoke": {"ok": True},
            "final_identity": {
                "product_version": "0.30.8",
                "build_number": 648,
                "target_commit": TARGET,
            },
        },
    )

    result = release_orchestrator.accept(args)

    assert result["stage"] == "accepted"
    assert [item["stage"] for item in result["transitions"]][-5:] == [
        "legion_installed",
        "legion_smoke_passed",
        "rollback_passed",
        "legion_reinstalled",
        "accepted",
    ]


def test_accept_failure_is_persisted_and_not_publishable(monkeypatch, tmp_path):
    args = _args(tmp_path)
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    archive = candidate / "les-patch.zip"
    archive.write_bytes(b"candidate")
    state_path = release_receipt.create_attempt(
        root=args.work_root / "attempts",
        release_class="patch",
        product_version="0.30.8",
        build_number=648,
        target_commit=TARGET,
        base_commits=[BASE],
        host="legion",
        assets=[archive],
    )
    release_receipt.transition(
        state_path,
        expected="planned",
        target="prepared",
        evidence={"acceptance_path": str(candidate)},
    )
    args.attempt = state_path
    monkeypatch.setattr(release_orchestrator, "resolve_commit", lambda *_args: TARGET)
    monkeypatch.setattr(release_orchestrator, "is_local_host", lambda _host: True)
    monkeypatch.setattr(
        release_orchestrator,
        "run_local_acceptance",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("Legion smoke failed")),
    )

    with pytest.raises(RuntimeError, match="Legion smoke failed"):
        release_orchestrator.accept(args)

    failed = release_receipt.load_attempt(state_path)
    assert failed["stage"] == "failed"
    assert failed["publishable"] is False


def test_skipped_gates_make_attempt_permanently_non_publishable(monkeypatch, tmp_path):
    args = _args(tmp_path, skip_gates=True)
    monkeypatch.setattr(release_orchestrator, "resolve_commit", lambda *_args: TARGET)
    monkeypatch.setattr(
        release_orchestrator,
        "load_contract",
        lambda _root: {"product_version": "0.30.8", "build_number": 648},
    )
    monkeypatch.setattr(
        release_orchestrator,
        "classify_release",
        lambda *_args, **_kwargs: _patch_classification(),
    )
    monkeypatch.setattr(
        release_orchestrator,
        "build_patch_candidate",
        lambda **kwargs: _minimal_candidate(kwargs["output"]),
    )

    result = release_orchestrator.prepare(args)

    assert result["publishable"] is False
    assert result["non_publishable_reason"] == "prepare gates were skipped"


def test_remote_full_acceptance_binds_installer_and_exact_target(monkeypatch, tmp_path):
    args = _args(tmp_path)
    installer = tmp_path / "LES-Setup.exe"
    installer.write_bytes(b"installer")
    attempt_path = release_receipt.create_attempt(
        root=tmp_path / "attempts",
        release_class="full",
        product_version="0.30.8",
        build_number=648,
        target_commit=TARGET,
        base_commits=[BASE],
        host="legion",
        assets=[installer],
    )
    attempt = release_receipt.load_attempt(attempt_path)
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(tuple(command))
        output = json.dumps({"accepted": True, "release_class": "full"})
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(release_orchestrator, "_run", fake_run)

    result = release_orchestrator.run_remote_acceptance(
        attempt=attempt,
        acceptance_path=Path(r"C:\cache\LES-Setup.exe"),
        args=args,
    )

    assert result["accepted"] is True
    execution = commands[-1]
    encoded = execution[execution.index("-EncodedCommand") + 1]
    script = base64.b64decode(encoded).decode("utf-16le")
    assert "windows_release_acceptance.py full" in script
    assert TARGET in script
    assert attempt["artifacts"][0]["sha256"] in script


def _minimal_candidate(output: Path):
    public = output / "public"
    acceptance = output / "acceptance"
    public.mkdir(parents=True)
    acceptance.mkdir(parents=True)
    asset = public / "les-patch.zip"
    asset.write_bytes(b"candidate")
    (acceptance / "les-patch.zip").write_bytes(asset.read_bytes())
    (acceptance / "latest.json").write_text("{}", encoding="utf-8")
    return {
        "assets": [asset],
        "candidate_assets": [asset],
        "acceptance_path": acceptance,
    }


@pytest.mark.parametrize(
    "stage",
    ["prepared", "legion_smoke_passed", "rollback_passed", "legion_reinstalled"],
)
def test_publish_refuses_every_preaccepted_stage(tmp_path, stage):
    args, state_path = _attempt_at_stage(tmp_path, stage)
    args.attempt = state_path

    with pytest.raises(RuntimeError, match="installed acceptance required"):
        release_orchestrator.publish(args)


def test_publish_advances_only_after_draft_verification_and_postflight(
    monkeypatch, tmp_path
):
    args, state_path = _attempt_at_stage(tmp_path, "accepted")
    args.attempt = state_path
    callbacks = []

    def publish_patch(**kwargs):
        for stage in ("draft_uploaded", "draft_verified", "published"):
            callbacks.append(stage)
            kwargs["stage_callback"](stage, {"ok": True})
        return {"published": True, "assets": ["les-patch.zip"]}

    monkeypatch.setattr(release_orchestrator, "resolve_commit", lambda *_args: TARGET)
    monkeypatch.setattr(release_orchestrator, "publish_patch_candidate", publish_patch)
    monkeypatch.setattr(
        release_orchestrator,
        "verify_public_provenance",
        lambda **_kwargs: {"ok": True, "target_commit": TARGET},
    )

    result = release_orchestrator.publish(args)

    assert callbacks == ["draft_uploaded", "draft_verified", "published"]
    assert result["stage"] == "postflight_verified"
    assert result["transitions"][-1]["evidence"]["target_commit"] == TARGET


def test_published_attempt_resumes_only_independent_postflight(monkeypatch, tmp_path):
    args, state_path = _attempt_at_stage(tmp_path, "published")
    args.attempt = state_path
    public = tmp_path / "candidate" / "public"
    (public / "release-receipt.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(release_orchestrator, "resolve_commit", lambda *_args: TARGET)
    monkeypatch.setattr(
        release_orchestrator,
        "publish_patch_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("release republished")),
    )
    monkeypatch.setattr(
        release_orchestrator,
        "verify_public_provenance",
        lambda **_kwargs: {"ok": True, "target_commit": TARGET},
    )

    result = release_orchestrator.publish(args)

    assert result["stage"] == "postflight_verified"


def test_run_release_preserves_prepare_accept_publish_boundaries(monkeypatch, tmp_path):
    args = _args(tmp_path, publish=True, skip_gates=False)
    calls = []
    state_path = tmp_path / "release-state.json"
    monkeypatch.setattr(
        release_orchestrator,
        "prepare",
        lambda _args: calls.append("prepare") or {"state_path": str(state_path)},
    )
    monkeypatch.setattr(
        release_orchestrator,
        "accept",
        lambda _args: calls.append("accept") or {"stage": "accepted"},
    )
    monkeypatch.setattr(
        release_orchestrator,
        "publish",
        lambda _args: calls.append("publish") or {"stage": "postflight_verified"},
    )

    result = release_orchestrator.run_release(args)

    assert calls == ["prepare", "accept", "publish"]
    assert args.attempt == state_path
    assert result["stage"] == "postflight_verified"


def _attempt_at_stage(tmp_path: Path, stage: str):
    args = _args(tmp_path)
    public = tmp_path / "candidate" / "public"
    acceptance = tmp_path / "candidate" / "acceptance"
    public.mkdir(parents=True)
    acceptance.mkdir(parents=True)
    archive = public / "les-patch.zip"
    archive.write_bytes(b"candidate")
    (public / "les-update.json").write_text("{}", encoding="utf-8")
    (public / "latest.json").write_text("{}", encoding="utf-8")
    (public / "les-patch.zip.sha256").write_text("checksum", encoding="ascii")
    (public / "release-notes.md").write_text("notes", encoding="utf-8")
    state_path = release_receipt.create_attempt(
        root=args.work_root / "attempts",
        release_class="patch",
        product_version="0.30.8",
        build_number=648,
        target_commit=TARGET,
        base_commits=[BASE],
        host="legion",
        assets=[archive],
    )
    release_receipt.transition(
        state_path,
        expected="planned",
        target="prepared",
        evidence={
            "candidate_root": str(public.parent),
            "acceptance_path": str(acceptance),
        },
    )
    current = "prepared"
    for target_stage in release_receipt.STAGES[
        release_receipt.STAGES.index("legion_installed") :
    ]:
        if release_receipt.STAGES.index(target_stage) > release_receipt.STAGES.index(stage):
            break
        release_receipt.transition(
            state_path,
            expected=current,
            target=target_stage,
            evidence={"ok": True},
        )
        current = target_stage
    return args, state_path
