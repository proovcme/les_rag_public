"""Native updater boot keeps operational settings and guarded recovery intact."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tests import test_windows_application_update as fixture
from tools import windows_runtime, windows_update_engine, vps_patch_apply


HARD = windows_update_engine
SOFT = vps_patch_apply
BASELINE = {"LES_ASBUILT_FIXTURE": "1", "RAG_CHAT_RERANK_CANDIDATE_K": "64", "RERANK_MAX_TEXT_CHARS": "4000"}


def hooks(monkeypatch, engine, state):
    events, live, generic_snapshots = [], {}, []
    # Only the generic function's copied environment is replaced; no process
    # environment is inspected, altered, serialized or sent anywhere.
    monkeypatch.setattr(windows_runtime, "os", SimpleNamespace(environ={}))
    (state / ".env").write_text("LES_LLM_PROVIDER=ollama\nLES_ASBUILT_FIXTURE=1 # Примечание только фикстуры\n", encoding="utf-8")

    def generic(runtime, state, *_args):
        events.append("generic_headless_start")
        effective = windows_runtime.runtime_environment(runtime, state)
        live.update({key: effective[key] for key in BASELINE})
        generic_snapshots.append(dict(live))

    def native(*_args):
        events.append("native_entry")
        if not live:  # The fixture reproduces the first backend winning its ports.
            live.update(BASELINE)
        return "own-fixture-native-task"

    def health(**_kwargs):
        events.append("health")
        if live != BASELINE:
            raise RuntimeError("FIXTURE_PRODUCT_FACTORS_CHANGED_BY_GENERIC_FIRST")
        return {"fixture_native_profile_preserved": True}

    def stopped(*_args):
        events.append("stop")
        live.clear()

    monkeypatch.setattr(engine, "start_runtime", generic)
    monkeypatch.setattr(engine, "start_desktop", native)
    monkeypatch.setattr(engine, "wait_ready", health)
    monkeypatch.setattr(engine, "stop_runtime", stopped)
    monkeypatch.setattr(engine, "stop_desktop", lambda: None)
    monkeypatch.setattr(engine, "remove_task", lambda *_args: None)
    monkeypatch.setattr(engine, "application_tree_lock_owners", lambda _install: [])
    return events, live, generic, native, health, stopped, generic_snapshots


def test_hard_ready_native_boot_precedes_health_and_cannot_follow_generic_ports(tmp_path, monkeypatch):
    engine, expected_rc = HARD, 0
    monkeypatch.setattr(fixture, "windows_update_engine", engine)
    install, state, job = fixture._hard_job(tmp_path)
    fixture._mock_hard_lifecycle(monkeypatch)
    events, live, _generic, _native, _health, _stopped, bad_snapshots = hooks(monkeypatch, engine, state)
    before_bytes = (state / ".env").read_bytes()
    assert engine.apply_hard_job(job) == expected_rc
    assert "generic_headless_start" not in events
    assert bad_snapshots == []
    assert events.index("native_entry") < events.index("health") and live == BASELINE
    assert (state / ".env").read_bytes() == before_bytes
    assert (state / "data/user.db").read_bytes() == b"user-owned"


def test_hard_failed_apply_restores_old_tree_through_native_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, "windows_update_engine", HARD)
    install, state, job = fixture._hard_job(tmp_path)
    (install / "runtime/.les_deploy_stamp.json").write_text(json.dumps({
        "deployed_commit": "a" * 40, "product_version": "0.25.19", "build_number": 492}))
    fixture._mock_hard_lifecycle(monkeypatch)
    events, live, _generic, _native, health, *_ = hooks(monkeypatch, HARD, state)
    def fail_new_only(**kwargs):
        assert kwargs["timeout"] == 120
        if kwargs["expected_commit"] == "b" * 40:
            raise RuntimeError("fixture new-version smoke failed")
        assert kwargs["expected_commit"] == "a" * 40
        return health(**kwargs)
    monkeypatch.setattr(HARD, "wait_ready", fail_new_only)
    assert HARD.apply_hard_job(job) == 1
    assert (install / "runtime/old-code.txt").read_text() == "old"
    assert "generic_headless_start" not in events and events.count("native_entry") == 2
    status = json.loads((state / "artifacts/updates/hard-status.json").read_text())
    assert status["stage"] == "rolled_back" and "fixture new-version smoke failed" in status["error"]
    assert status["rollback_recovery_error"] == ""
    assert status["rollback_recovery"] == {"fixture_native_profile_preserved": True}


@pytest.mark.parametrize("old_identity", ["known", "unknown"])
def test_hard_recovery_never_claims_ready_on_async_launch_or_missing_identity(tmp_path, monkeypatch, old_identity):
    monkeypatch.setattr(fixture, "windows_update_engine", HARD)
    install, state, job = fixture._hard_job(tmp_path)
    if old_identity == "known":
        (install / "runtime/.les_deploy_stamp.json").write_text(json.dumps({
            "deployed_commit": "a" * 40, "product_version": "0.25.19", "build_number": 492}))
    else:
        (install / "runtime/.les_deploy_stamp.json").unlink()
    fixture._mock_hard_lifecycle(monkeypatch)
    events, live, *_ = hooks(monkeypatch, HARD, state)
    def not_ready(**kwargs):
        assert kwargs["timeout"] == 120
        if kwargs["expected_commit"] == "b" * 40:
            raise RuntimeError("ORIGINAL_NEW_RELEASE_FAILURE")
        status = json.loads((state / "artifacts/updates/hard-status.json").read_text())
        assert status.get("stage") != "rolled_back"
        raise RuntimeError("OLD_NATIVE_NOT_IDENTITY_READY")
    monkeypatch.setattr(HARD, "wait_ready", not_ready)
    assert HARD.apply_hard_job(job) == 1
    status = json.loads((state / "artifacts/updates/hard-status.json").read_text())
    assert status["stage"] == "rollback_restart_failed"
    assert status["error"] == "ORIGINAL_NEW_RELEASE_FAILURE"
    assert status["rollback_recovery"] == {}
    if old_identity == "known":
        assert status["rollback_recovery_error"] == "OLD_NATIVE_NOT_IDENTITY_READY"
        assert events.count("native_entry") == 2
    else:
        assert "PREVIOUS_APPLICATION_IDENTITY_UNPROVEN" in status["rollback_recovery_error"]
        assert events.count("native_entry") == 1


def installed_hard_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, "windows_update_engine", HARD)
    install, state, job = fixture._hard_job(tmp_path)
    previous = {"deployed_commit": "a" * 40, "product_version": "0.25.19", "build_number": 492}
    (install / "runtime/.les_deploy_stamp.json").write_text(json.dumps(previous))
    fixture._mock_hard_lifecycle(monkeypatch)
    events, live, *_ = hooks(monkeypatch, HARD, state)
    assert HARD.apply_hard_job(job) == 0
    status = json.loads((state / "artifacts/updates/hard-status.json").read_text())
    events.clear()
    return install, state, job, status, events, live


@pytest.mark.parametrize("api_ready", [False, True])
def test_hard_resume_does_not_dispatch_generic_runtime_before_native_health(tmp_path, monkeypatch, api_ready):
    install, state, job, status, events, live = installed_hard_fixture(tmp_path, monkeypatch)
    if api_ready:
        monkeypatch.setattr(HARD, "_json_url", lambda *_args, **_kwargs: {"fixture_alive": True})
    else:
        monkeypatch.setattr(HARD, "_json_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fixture API down")))
    assert HARD.resume_hard_job(job) == 0
    assert events == (["native_entry", "health"] if api_ready else ["stop", "native_entry", "health"])
    assert live == BASELINE


def test_accepted_hard_rollback_preserves_native_health_and_identity_guards(tmp_path, monkeypatch):
    install, state, job, status, events, live = installed_hard_fixture(tmp_path, monkeypatch)
    result = HARD.rollback_accepted_hard_update(install=install, state=state,
        recovery_root=Path(status["recovery_root"]), expected_target_commit="b" * 40)
    assert result["state"] == "rolled_back"
    assert events == ["stop", "stop", "native_entry", "health"] and live == BASELINE
    assert (install / "runtime/old-code.txt").read_text() == "old"


def _rename_error_974(winerror, message="fixture tree rename blocked"):
    error = PermissionError(message) if winerror in {5, 32, 33} else OSError(message)
    if winerror is not None:
        error.winerror = winerror
    return error


def _rename_clock_974(monkeypatch):
    clock = {"seconds": 0.0, "sleeps": []}

    def sleep(seconds):
        assert 0 < seconds <= 0.25
        clock["sleeps"].append(seconds)
        clock["seconds"] += seconds

    monkeypatch.setattr(HARD, "time", SimpleNamespace(
        monotonic=lambda: clock["seconds"], sleep=sleep))
    return clock


@pytest.mark.parametrize("winerror", [5, 32, 33])
@pytest.mark.parametrize("route", ["primary", "recovery"])
def test_hard_rollback_retries_only_transient_outgoing_tree_locks_974(
        tmp_path, monkeypatch, winerror, route):
    install, state, _job, status, events, live = installed_hard_fixture(tmp_path, monkeypatch)
    recovery = Path(status["recovery_root"])
    before_state = (state / "data/user.db").read_bytes()
    actual_replace, attempts = HARD.os.replace, []
    clock = _rename_clock_974(monkeypatch)
    smoke_error = RuntimeError("fixture previous native health failed")
    if route == "recovery":
        healthy = HARD.wait_ready

        def health(**kwargs):
            if kwargs["expected_commit"] == "a" * 40:
                raise smoke_error
            return healthy(**kwargs)

        monkeypatch.setattr(HARD, "wait_ready", health)

    def replace(source, target):
        source, target = Path(source), Path(target)
        outgoing = source == install and (
            target.name.startswith("LES.candidate-rollback-") if route == "primary" else target == recovery)
        if outgoing:
            attempts.append((source, target))
            if len(attempts) <= 2:
                raise _rename_error_974(winerror)
        return actual_replace(source, target)

    monkeypatch.setattr(HARD.os, "replace", replace)
    if route == "primary":
        result = HARD.rollback_accepted_hard_update(install=install, state=state,
            recovery_root=recovery, expected_target_commit="b" * 40)
        assert result["state"] == "rolled_back"
        assert (install / "runtime/old-code.txt").read_bytes() == b"old"
        assert not recovery.exists()
        assert events == ["stop", "stop", "native_entry", "health"]
    else:
        with pytest.raises(RuntimeError) as caught:
            HARD.rollback_accepted_hard_update(install=install, state=state,
                recovery_root=recovery, expected_target_commit="b" * 40)
        assert caught.value is smoke_error
        assert (install / "runtime/new-code.txt").read_bytes() == b"new"
        assert (recovery / "runtime/old-code.txt").read_bytes() == b"old"
        assert not any("ACCEPTED_HARD_ROLLBACK_RECOVERY_FAILED" in note
                       for note in getattr(caught.value, "__notes__", ()))
        assert events.count("native_entry") == 2
    assert len(attempts) == 3 and len(clock["sleeps"]) == 2
    assert live == BASELINE and "generic_headless_start" not in events
    assert (state / "data/user.db").read_bytes() == before_state


def test_hard_rollback_terminal_first_rename_is_bounded_and_preserves_both_trees_974(
        tmp_path, monkeypatch):
    install, state, _job, status, events, _live = installed_hard_fixture(tmp_path, monkeypatch)
    recovery = Path(status["recovery_root"])
    actual_replace, attempts = HARD.os.replace, []
    error = _rename_error_974(5)
    clock = _rename_clock_974(monkeypatch)

    def replace(source, target):
        if Path(source) == install:
            attempts.append((Path(source), Path(target)))
            raise error
        return actual_replace(source, target)

    monkeypatch.setattr(HARD.os, "replace", replace)
    with pytest.raises(PermissionError) as caught:
        HARD.rollback_accepted_hard_update(install=install, state=state,
            recovery_root=recovery, expected_target_commit="b" * 40)
    assert caught.value is error
    assert len(attempts) > 1 and 5 <= clock["seconds"] <= 5.25
    assert (install / "runtime/new-code.txt").read_bytes() == b"new"
    assert (recovery / "runtime/old-code.txt").read_bytes() == b"old"
    assert all(not target.exists() for _source, target in attempts)
    assert events == ["stop"]


def test_hard_rollback_terminal_second_rename_restores_the_same_candidate_974(
        tmp_path, monkeypatch):
    install, state, _job, status, events, _live = installed_hard_fixture(tmp_path, monkeypatch)
    recovery = Path(status["recovery_root"])
    actual_replace, moves = HARD.os.replace, []
    error = _rename_error_974(87, "fixture replacement rename rejected")
    clock = _rename_clock_974(monkeypatch)

    def replace(source, target):
        source, target = Path(source), Path(target)
        moves.append((source, target))
        if source == recovery and target == install:
            raise error
        return actual_replace(source, target)

    monkeypatch.setattr(HARD.os, "replace", replace)
    with pytest.raises(OSError) as caught:
        HARD.rollback_accepted_hard_update(install=install, state=state,
            recovery_root=recovery, expected_target_commit="b" * 40)
    assert caught.value is error and clock["sleeps"] == []
    assert (install / "runtime/new-code.txt").read_bytes() == b"new"
    assert (recovery / "runtime/old-code.txt").read_bytes() == b"old"
    archived = moves[0][1]
    assert moves == [(install, archived), (recovery, install), (archived, install)]
    assert not archived.exists() and events == ["stop"]


@pytest.mark.parametrize("winerror", [None, 87], ids=["posix-permission", "other-windows-error"])
def test_hard_rollback_nonretryable_first_error_is_not_delayed_or_replaced_974(
        tmp_path, monkeypatch, winerror):
    install, state, _job, status, _events, _live = installed_hard_fixture(tmp_path, monkeypatch)
    recovery = Path(status["recovery_root"])
    error = PermissionError("fixture POSIX permission") if winerror is None else _rename_error_974(winerror)
    actual_replace, attempts = HARD.os.replace, []
    clock = _rename_clock_974(monkeypatch)

    def replace(source, target):
        if Path(source) == install:
            attempts.append((Path(source), Path(target)))
            raise error
        return actual_replace(source, target)

    monkeypatch.setattr(HARD.os, "replace", replace)
    with pytest.raises(OSError) as caught:
        HARD.rollback_accepted_hard_update(install=install, state=state,
            recovery_root=recovery, expected_target_commit="b" * 40)
    assert caught.value is error and len(attempts) == 1 and clock["sleeps"] == []
    assert (install / "runtime/new-code.txt").read_bytes() == b"new"
    assert (recovery / "runtime/old-code.txt").read_bytes() == b"old"


@pytest.mark.parametrize("changed", ["target-appears", "source-disappears"])
@pytest.mark.parametrize("when", ["at-failure", "during-sleep"])
def test_hard_rollback_does_not_retry_across_changed_filesystem_preconditions_974(
        tmp_path, monkeypatch, changed, when):
    install, state, _job, status, _events, _live = installed_hard_fixture(tmp_path, monkeypatch)
    recovery = Path(status["recovery_root"])
    actual_replace, attempts = HARD.os.replace, []
    parked = install.with_name("LES.externally-moved-fixture")
    error = _rename_error_974(32)
    _rename_clock_974(monkeypatch)

    def change_filesystem(source, target):
        if changed == "target-appears":
            target.mkdir()
            (target / "foreign.txt").write_bytes(b"foreign directory must survive")
        else:
            actual_replace(source, parked)

    def replace(source, target):
        source, target = Path(source), Path(target)
        if source == install:
            attempts.append((source, target))
            if when == "at-failure":
                change_filesystem(source, target)
            raise error
        return actual_replace(source, target)

    if when == "during-sleep":
        advance_clock = HARD.time.sleep

        def sleep(seconds):
            advance_clock(seconds)
            change_filesystem(*attempts[-1])

        monkeypatch.setattr(HARD.time, "sleep", sleep)
    monkeypatch.setattr(HARD.os, "replace", replace)
    with pytest.raises(OSError) as caught:
        HARD.rollback_accepted_hard_update(install=install, state=state,
            recovery_root=recovery, expected_target_commit="b" * 40)
    assert caught.value is error and len(attempts) == 1
    if changed == "target-appears":
        assert (install / "runtime/new-code.txt").read_bytes() == b"new"
        assert (attempts[0][1] / "foreign.txt").read_bytes() == b"foreign directory must survive"
    else:
        assert not install.exists() and (parked / "runtime/new-code.txt").read_bytes() == b"new"
    assert (recovery / "runtime/old-code.txt").read_bytes() == b"old"


def test_hard_rollback_failed_second_move_and_repair_keep_both_trees_and_original_error_974(
        tmp_path, monkeypatch):
    install, state, _job, status, events, _live = installed_hard_fixture(tmp_path, monkeypatch)
    recovery = Path(status["recovery_root"])
    actual_replace, moves = HARD.os.replace, []
    original = _rename_error_974(87, "fixture replacement rename rejected")
    repair_error = _rename_error_974(87, "fixture repair rename blocked")
    _rename_clock_974(monkeypatch)

    def replace(source, target):
        source, target = Path(source), Path(target)
        moves.append((source, target))
        if source == recovery and target == install:
            raise original
        if source != install and target == install:
            raise repair_error
        return actual_replace(source, target)

    monkeypatch.setattr(HARD.os, "replace", replace)
    with pytest.raises(OSError) as caught:
        HARD.rollback_accepted_hard_update(install=install, state=state,
            recovery_root=recovery, expected_target_commit="b" * 40)
    assert caught.value is original
    notes = getattr(caught.value, "__notes__", ())
    assert any("fixture repair rename blocked" in note for note in notes)
    archived = moves[0][1]
    assert not install.exists()
    assert (archived / "runtime/new-code.txt").read_bytes() == b"new"
    assert (recovery / "runtime/old-code.txt").read_bytes() == b"old"
    assert moves == [(install, archived), (recovery, install), (archived, install)]
    assert events == ["stop"]


@pytest.mark.parametrize("target_ready", [True, False])
def test_hard_rollback_recovery_returns_candidate_with_no_generic_boot(tmp_path, monkeypatch, target_ready):
    install, state, job, status, events, live = installed_hard_fixture(tmp_path, monkeypatch)
    observed = []
    def health_by_identity(**kwargs):
        observed.append(kwargs["expected_commit"])
        if kwargs["expected_commit"] == "a" * 40:
            raise RuntimeError("fixture restored smoke failed")
        assert kwargs["expected_commit"] == "b" * 40 and kwargs["timeout"] == 120
        if not target_ready:
            raise RuntimeError("candidate recovery smoke failed")
        return {"fixture_recovered_target": True}
    monkeypatch.setattr(HARD, "wait_ready", health_by_identity)
    with pytest.raises(RuntimeError, match="fixture restored smoke failed") as caught:
        HARD.rollback_accepted_hard_update(install=install, state=state,
            recovery_root=Path(status["recovery_root"]), expected_target_commit="b" * 40)
    assert (install / "runtime/new-code.txt").read_text() == "new"
    assert "generic_headless_start" not in events and events.count("native_entry") == 2
    assert observed == ["a" * 40, "b" * 40]
    if not target_ready:
        assert any("ACCEPTED_HARD_ROLLBACK_RECOVERY_FAILED" in value for value in caught.value.__notes__)


def test_soft_ready_cannot_let_generic_boot_win_before_native_health(tmp_path, monkeypatch):
    engine, expected_rc = SOFT, 0
    monkeypatch.setattr(fixture, "vps_patch_apply", engine)
    runtime, state, job = fixture._prepared_job(tmp_path)
    actual_restored_wait = engine._wait_restored_ready
    actual_native_probe = engine._probe_native_runtime
    fixture._patch_windows_actions(monkeypatch)
    monkeypatch.setattr(engine, "_wait_restored_ready", actual_restored_wait)
    monkeypatch.setattr(engine, "_probe_native_runtime", actual_native_probe)
    events, live, generic, native, health, stopped, _snapshots = hooks(monkeypatch, HARD, state)
    monkeypatch.setattr(engine, "_start_runtime", lambda runtime, state: generic(runtime, state))
    if hasattr(engine, "_probe_native_runtime"):
        monkeypatch.setattr(engine, "windows_update_engine", HARD)
        monkeypatch.setattr(HARD, "probe_environment", lambda *_args: events.append("dependency_probe"))
    monkeypatch.setattr(engine, "_stop_runtime", stopped)
    monkeypatch.setattr(engine, "start_desktop", native)
    monkeypatch.setattr(engine, "_wait_ready", lambda *_args: health())
    # Failed source version enters its old fallback; fixture-only HTTP shape.
    monkeypatch.setattr(engine.urllib.request, "urlopen", lambda *_args, **_kwargs: SimpleNamespace(
        __enter__=lambda self: self, __exit__=lambda *_args: None, status=200))
    assert engine.apply_job(job) == expected_rc
    assert "generic_headless_start" not in events and live == BASELINE
    assert events.index("dependency_probe") < events.index("native_entry") < events.index("health")
    assert (state / "data/user-owned.db").read_bytes() == b"never replace me"


def test_explicit_headless_helpers_still_dispatch_their_original_cli(tmp_path, monkeypatch):
    runtime, state, logs = tmp_path / "runtime", tmp_path / "own-state", tmp_path / "logs"
    commands = []
    monkeypatch.setattr(HARD, "run_bounded", lambda args, **kwargs: commands.append((args, kwargs)))
    HARD.start_runtime(runtime, state, logs)
    assert len(commands) == 1
    args, options = commands[0]
    assert "start" in args and args[args.index("--runtime") + 1] == str(runtime)
    assert args[args.index("--state") + 1] == str(state) and options["timeout"] == 180
    events = []
    monkeypatch.setattr(HARD, "probe_environment", lambda *_args: events.append("probe"))
    monkeypatch.setattr(HARD, "start_runtime", lambda *_args: events.append("headless-start"))
    SOFT._start_runtime(runtime, state)
    assert events == ["probe", "headless-start"]


def soft_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(fixture, "vps_patch_apply", SOFT)
    runtime, state, job = fixture._prepared_job(tmp_path)
    (runtime / ".les_deploy_stamp.json").write_text(json.dumps({
        "deployed_commit": "a" * 40, "product_version": "0.25.17", "build_number": 490}))
    actual_restored_wait = SOFT._wait_restored_ready
    actual_native_probe = SOFT._probe_native_runtime
    fixture._patch_windows_actions(monkeypatch)
    monkeypatch.setattr(SOFT, "_wait_restored_ready", actual_restored_wait)
    monkeypatch.setattr(SOFT, "_probe_native_runtime", actual_native_probe)
    events, live, _generic, native, health, stopped, _snapshots = hooks(monkeypatch, HARD, state)
    monkeypatch.setattr(SOFT, "windows_update_engine", HARD)
    monkeypatch.setattr(HARD, "probe_environment", lambda *_args: events.append("dependency_probe"))
    monkeypatch.setattr(SOFT, "_stop_runtime", stopped)
    monkeypatch.setattr(SOFT, "start_desktop", native)
    monkeypatch.setattr(SOFT, "_wait_ready", lambda *_args: health())
    monkeypatch.setattr(SOFT.urllib.request, "urlopen", lambda *_args, **_kwargs: pytest.fail("No bare UI-only health may qualify restored identity"))
    return runtime, state, job, events, live, health


@pytest.mark.parametrize("ready", [True, False])
def test_soft_failed_apply_waits_previous_identity_before_rollback_green(tmp_path, monkeypatch, ready):
    runtime, state, job, events, live, health = soft_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(SOFT, "_wait_ready", lambda *_args: (_ for _ in ()).throw(RuntimeError("ORIGINAL_SOFT_FAILURE")))
    observed = []
    def restored(**kwargs):
        observed.append(kwargs)
        assert kwargs["expected_commit"] == "a" * 40 and kwargs["expected_build"] == 490 and kwargs["timeout"] == 120
        status = json.loads((state / "artifacts/updates/status.json").read_text())
        assert status.get("stage") != "rolled_back"
        if not ready:
            raise RuntimeError("RESTORED_SOFT_NATIVE_NOT_READY")
        return health(**kwargs)
    monkeypatch.setattr(HARD, "wait_ready", restored)
    assert SOFT.apply_job(job) == 1
    status = json.loads((state / "artifacts/updates/status.json").read_text())
    assert status["error"] == "ORIGINAL_SOFT_FAILURE" and len(observed) == 1
    assert "generic_headless_start" not in events and events.count("stop") == 3
    assert status["stage"] == ("rolled_back" if ready else "rollback_restart_failed")
    assert status["rollback_recovery_error"] == ("" if ready else "RESTORED_SOFT_NATIVE_NOT_READY")
    assert bool(status["rollback_recovery"]) is ready
    assert (runtime / "proxy/example.py").read_bytes() == b"OLD = True\n"


def test_soft_missing_previous_identity_cannot_pass_a_healthy_ui(tmp_path, monkeypatch):
    runtime, state, job, events, live, health = soft_fixture(tmp_path, monkeypatch)
    (runtime / ".les_deploy_stamp.json").write_text(json.dumps({"deployed_commit": "a" * 40}))
    monkeypatch.setattr(SOFT, "_wait_ready", lambda *_args: (_ for _ in ()).throw(RuntimeError("ORIGINAL_SOFT_FAILURE")))
    monkeypatch.setattr(HARD, "wait_ready", lambda **_kwargs: pytest.fail("Unproven stamp cannot invoke identity health"))
    assert SOFT.apply_job(job) == 1
    status = json.loads((state / "artifacts/updates/status.json").read_text())
    assert status["stage"] == "rollback_restart_failed"
    assert status["error"] == "ORIGINAL_SOFT_FAILURE"
    assert "cannot prove restored identity" in status["rollback_recovery_error"]
    assert status["rollback_recovery"] == {}


def test_soft_accepted_rollback_preserves_one_native_contour_and_identity_health(tmp_path, monkeypatch):
    runtime, state, job, events, live, health = soft_fixture(tmp_path, monkeypatch)
    assert SOFT.apply_job(job) == 0
    status = json.loads((state / "artifacts/updates/status.json").read_text())
    events.clear()
    result = SOFT.rollback_accepted_patch(runtime=runtime, state=state, backup_root=Path(status["backup_root"]), expected_target_commit="b" * 40)
    assert result["state"] == "rolled_back" and live == BASELINE
    assert events == ["stop", "dependency_probe", "stop", "native_entry", "health"]


@pytest.mark.parametrize("target_ready", [True, False])
def test_soft_accepted_rollback_failure_recovers_target_via_identity_health(tmp_path, monkeypatch, target_ready):
    runtime, state, job, events, live, health = soft_fixture(tmp_path, monkeypatch)
    assert SOFT.apply_job(job) == 0
    status = json.loads((state / "artifacts/updates/status.json").read_text())
    events.clear()
    observed = []
    def by_identity(**kwargs):
        observed.append(kwargs["expected_commit"])
        assert kwargs["timeout"] == 120
        if kwargs["expected_commit"] == "a" * 40:
            raise RuntimeError("ORIGINAL_ACCEPTED_SOFT_ROLLBACK_FAILED")
        assert kwargs["expected_commit"] == "b" * 40
        if not target_ready:
            raise RuntimeError("TARGET_RECOVERY_NOT_READY")
        return health(**kwargs)
    monkeypatch.setattr(HARD, "wait_ready", by_identity)
    with pytest.raises(RuntimeError, match="ORIGINAL_ACCEPTED_SOFT_ROLLBACK_FAILED") as caught:
        SOFT.rollback_accepted_patch(runtime=runtime, state=state, backup_root=Path(status["backup_root"]), expected_target_commit="b" * 40)
    assert observed == ["a" * 40, "b" * 40]
    assert "generic_headless_start" not in events
    assert (runtime / "proxy/example.py").read_bytes() == b"NEW = True\n"
    if not target_ready:
        assert any("TARGET_RECOVERY_NOT_READY" in note for note in caught.value.__notes__)


def attach_actual_foreign_guard(monkeypatch, engine, state, events, live, at_stop):
    """Exercise the real WindowsRuntime.stop callee with fixture-only listeners."""
    observed = {"calls": 0, "foreign": False, "terminated": []}
    monkeypatch.setattr(windows_runtime, "_listening_pids", lambda _ports: {8050: 900001, 8051: 900002} if observed["foreign"] else {})
    monkeypatch.setattr(windows_runtime, "_live_runtime_matches", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(windows_runtime, "_recorded_runtime_owns_listeners", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(windows_runtime, "_port_free", lambda _port: True)
    def forbidden_terminate(pid, **_kwargs):
        observed["terminated"].append(pid)
        pytest.fail("A foreign PID must never be terminated")
    monkeypatch.setattr(windows_runtime, "_terminate_pid", forbidden_terminate)
    def guarded_stop(runtime, passed_state, *_args):
        assert passed_state == state
        observed["calls"] += 1
        observed["foreign"] |= observed["calls"] >= at_stop
        events.append("real_stop_foreign" if observed["foreign"] else "real_stop_absent")
        result = windows_runtime.stop(state, runtime=runtime)
        assert result["status"] == "stopped" and result["pids"] == []
        live.clear()
    monkeypatch.setattr(engine, "stop_runtime", guarded_stop)
    return guarded_stop, observed


@pytest.mark.parametrize("route,at_stop,native_before_reject", [
    ("hard_apply", 2, 0), ("hard_failure", 4, 1), ("hard_resume", 1, 0),
    ("hard_accepted_rollback", 2, 0), ("hard_rollback_recovery", 4, 1),
    ("soft_apply", 2, 0), ("soft_failure", 3, 1),
    ("soft_accepted_rollback", 2, 0), ("soft_rollback_recovery", 4, 1),
])
def test_all_nine_routes_keep_actual_foreign_pid_stop_effects(tmp_path, monkeypatch, route, at_stop, native_before_reject):
    if route.startswith("hard"):
        if route in {"hard_apply", "hard_failure"}:
            monkeypatch.setattr(fixture, "windows_update_engine", HARD)
            install, state, job = fixture._hard_job(tmp_path)
            (install / "runtime/.les_deploy_stamp.json").write_text(json.dumps({
                "deployed_commit": "a" * 40, "product_version": "0.25.19", "build_number": 492}))
            fixture._mock_hard_lifecycle(monkeypatch)
            events, live, *_ = hooks(monkeypatch, HARD, state)
            status = None
        else:
            install, state, job, status, events, live = installed_hard_fixture(tmp_path, monkeypatch)
        _guard, observed = attach_actual_foreign_guard(monkeypatch, HARD, state, events, live, at_stop)
        if route == "hard_resume":
            monkeypatch.setattr(HARD, "_json_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fixture API down")))
            with pytest.raises(RuntimeError, match="foreign_port_owner"):
                HARD.resume_hard_job(job)
        elif route in {"hard_apply", "hard_failure"}:
            if route == "hard_failure":
                monkeypatch.setattr(HARD, "wait_ready", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture first native health failed")))
            assert HARD.apply_hard_job(job) == 1
            after = json.loads((state / "artifacts/updates/hard-status.json").read_text())
            assert after["stage"] != "rolled_back" and "foreign_port_owner" in after["rollback_recovery_error"]
        else:
            if route == "hard_rollback_recovery":
                monkeypatch.setattr(HARD, "wait_ready", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture previous native health failed")))
            with pytest.raises(RuntimeError):
                HARD.rollback_accepted_hard_update(install=install, state=state,
                    recovery_root=Path(status["recovery_root"]), expected_target_commit="b" * 40)
    else:
        runtime, state, job, events, live, _health = soft_fixture(tmp_path, monkeypatch)
        if route in {"soft_accepted_rollback", "soft_rollback_recovery"}:
            assert SOFT.apply_job(job) == 0
            status = json.loads((state / "artifacts/updates/status.json").read_text())
            events.clear()
        guard, observed = attach_actual_foreign_guard(monkeypatch, HARD, state, events, live, at_stop)
        monkeypatch.setattr(SOFT, "_stop_runtime", lambda runtime, state: guard(runtime, state))
        if route in {"soft_apply", "soft_failure"}:
            if route == "soft_failure":
                monkeypatch.setattr(SOFT, "_wait_ready", lambda *_args: (_ for _ in ()).throw(RuntimeError("fixture first native health failed")))
            assert SOFT.apply_job(job) == 1
            after = json.loads((state / "artifacts/updates/status.json").read_text())
            assert after["stage"] != "rolled_back" and "foreign_port_owner" in after["rollback_recovery_error"]
        else:
            if route == "soft_rollback_recovery":
                monkeypatch.setattr(HARD, "wait_ready", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("fixture previous native health failed")))
            with pytest.raises(RuntimeError):
                SOFT.rollback_accepted_patch(runtime=runtime, state=state, backup_root=Path(status["backup_root"]), expected_target_commit="b" * 40)
    assert observed["calls"] >= at_stop and observed["terminated"] == []
    assert events.count("native_entry") == native_before_reject
    assert "generic_headless_start" not in events
