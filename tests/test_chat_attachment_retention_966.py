"""Real OS-lock coverage; no application runtime or model is contacted."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from proxy.services import chat_attachment_service as attachments


IDENT = "read_123456abcdef"


def _source(tmp_path):
    source = tmp_path / "source.csv"
    source.write_bytes(b"title;quantity\nwork;12\n")
    root = tmp_path / "source store"
    metadata = attachments.preserve_read_attachment(
        source, attachment_id=IDENT, original_name="source.csv", root=root)
    return root, metadata


def _operation_worker(root, operation, sha256, ready, done, output):
    from proxy.services import chat_attachment_service as service
    try:
        if operation == "timeout":
            service._METADATA_LOCK_TIMEOUT_SEC = 0.05
        ready.set()
        if operation in {"resolve", "timeout"}:
            service.resolve_read_attachment(IDENT, root=root)
        elif operation == "retain":
            service.retain_read_attachment_for_workbook(IDENT, expected_sha256=sha256, root=root)
        elif operation == "consume":
            service.consume_read_attachment(IDENT, root=root)
        elif operation == "cleanup":
            service.cleanup_expired(root=root, max_age_sec=-1)
        elif operation == "preserve":
            source = Path(root).parent / "source.csv"
            service.preserve_read_attachment(source, attachment_id=IDENT,
                original_name="source.csv", root=root)
        output.put("ok")
    except Exception as exc:  # Worker transports the actual failure to pytest.
        output.put((type(exc).__name__, str(exc)))
    finally:
        done.set()


@pytest.mark.parametrize("operation", ["resolve", "retain", "consume", "cleanup", "preserve"])
def test_every_lifecycle_operation_uses_same_cross_process_lock(tmp_path, operation):
    root, metadata = _source(tmp_path)
    context = multiprocessing.get_context("spawn")
    ready, done, output = context.Event(), context.Event(), context.Queue()
    worker = context.Process(target=_operation_worker,
        args=(root, operation, metadata["sha256"], ready, done, output))
    metadata_path, _ = attachments._paths(IDENT, root)
    try:
        with attachments._attachment_metadata_lock(metadata_path):
            worker.start()
            assert ready.wait(10)
            assert not done.wait(0.15), f"{operation} bypassed the shared lock"
        assert done.wait(10)
        worker.join(10)
        assert worker.exitcode == 0
        assert output.get(timeout=2) == "ok"
        if operation in {"consume", "cleanup"}:
            assert not metadata_path.exists()
        else:
            path, current = attachments.resolve_read_attachment(IDENT, root=root)
            assert path.read_bytes() == (tmp_path / "source.csv").read_bytes()
            assert current["sha256"] == metadata["sha256"]
            if operation == "retain":
                assert current["retained_for_workbook"] is True
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(10)
        output.close()


def test_lock_timeout_is_bounded_visible_and_does_not_mutate_metadata(tmp_path):
    root, metadata = _source(tmp_path)
    metadata_path, _ = attachments._paths(IDENT, root)
    before = metadata_path.read_bytes()
    context = multiprocessing.get_context("spawn")
    ready, done, output = context.Event(), context.Event(), context.Queue()
    worker = context.Process(target=_operation_worker,
        args=(root, "timeout", metadata["sha256"], ready, done, output))
    try:
        with attachments._attachment_metadata_lock(metadata_path):
            worker.start()
            assert ready.wait(10) and done.wait(10)
            result = output.get(timeout=2)
            assert result == ("TimeoutError", "chat attachment metadata is busy")
            assert metadata_path.read_bytes() == before
        worker.join(10)
        assert worker.exitcode == 0
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(10)
        output.close()


def _hold_lock_worker(metadata_path, ready):
    from proxy.services import chat_attachment_service as service
    with service._attachment_metadata_lock(Path(metadata_path)):
        ready.set()
        multiprocessing.Event().wait(30)


def test_process_exit_releases_lock_without_unlinking_shared_lockfile(tmp_path):
    root, _ = _source(tmp_path)
    metadata_path, _ = attachments._paths(IDENT, root)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    worker = context.Process(target=_hold_lock_worker, args=(metadata_path, ready))
    try:
        worker.start()
        assert ready.wait(10)
        worker.terminate()  # Only this test's exact child process, never an application service.
        worker.join(10)
        assert not worker.is_alive()
        path, _ = attachments.resolve_read_attachment(IDENT, root=root)
        assert path.is_file() and metadata_path.with_suffix(".lock").is_file()
    finally:
        if worker.is_alive():
            worker.terminate()
        worker.join(10)


def _concurrent_pin_worker(root, sha256, both_read, both_written, output):
    from proxy.services import chat_attachment_service as service
    original_resolve, original_write = service.resolve_read_attachment, Path.write_text

    def synchronize_read(*args, **kwargs):
        result = original_resolve(*args, **kwargs)
        assert result[1].get("retained_for_workbook") is not True
        both_read.wait(timeout=10)
        return result

    def synchronize_write(path, *args, **kwargs):
        result = original_write(path, *args, **kwargs)
        if path.name.endswith(".retain.tmp"):
            both_written.wait(timeout=10)
        return result

    service.resolve_read_attachment = synchronize_read
    Path.write_text = synchronize_write
    try:
        output.put(service.retain_read_attachment_for_workbook(
            IDENT, expected_sha256=sha256, root=root))
    except Exception as exc:  # Parent receives errors instead of accepting a crashed worker.
        output.put((type(exc).__name__, str(exc)))


def test_independent_processes_pin_the_same_original_without_stale_metadata(tmp_path):
    root, metadata = _source(tmp_path)
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    both_read, both_written = context.Barrier(2), context.Barrier(2)
    workers = [context.Process(target=_concurrent_pin_worker,
        args=(root, metadata["sha256"], both_read, both_written, output)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        results = [output.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
        assert all(isinstance(result, dict) and result["retained_for_workbook"] is True
            and result["sha256"] == metadata["sha256"] for result in results), results
        path, saved = attachments.resolve_read_attachment(IDENT, root=root)
        assert path.read_bytes() == (tmp_path / "source.csv").read_bytes()
        assert saved["retained_for_workbook"] is True
        assert not list(root.glob("*.retain.tmp"))
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(10)
        output.close()


def test_retained_metadata_and_bytes_survive_cleanup_and_consume(tmp_path):
    root, metadata = _source(tmp_path)
    pinned = attachments.retain_read_attachment_for_workbook(
        IDENT, expected_sha256=metadata["sha256"], root=root)
    assert attachments.cleanup_expired(root=root, max_age_sec=-1) == 0
    attachments.consume_read_attachment(IDENT, root=root)
    path, current = attachments.resolve_read_attachment(IDENT, root=root)
    assert current == pinned and path.is_file()
    assert json.loads((root / f"{IDENT}.json").read_text(encoding="utf-8")) == pinned
    attachments.consume_read_attachment(IDENT, root=root, force=True)
    assert not path.exists()


def test_pin_commit_rechecks_source_and_never_resurrects_consumed_metadata(tmp_path, monkeypatch):
    root, metadata = _source(tmp_path)
    original_write = Path.write_text

    def consume_after_staging(path, *args, **kwargs):
        result = original_write(path, *args, **kwargs)
        if path.name.endswith(".retain.tmp"):
            attachments.consume_read_attachment(IDENT, root=root)
        return result

    monkeypatch.setattr(Path, "write_text", consume_after_staging)
    with pytest.raises(FileNotFoundError, match="chat attachment not found"):
        attachments.retain_read_attachment_for_workbook(
            IDENT, expected_sha256=metadata["sha256"], root=root)
    assert not (root / f"{IDENT}.json").exists()
    assert not (root / f"{IDENT}.csv").exists()
    assert not list(root.glob("*.retain.tmp"))


def test_pin_commit_preserves_current_server_metadata_for_same_source(tmp_path, monkeypatch):
    root, metadata = _source(tmp_path)
    metadata_path, _ = attachments._paths(IDENT, root)
    original_write = Path.write_text
    changed = False

    def metadata_changed_after_staging(path, *args, **kwargs):
        nonlocal changed
        result = original_write(path, *args, **kwargs)
        if path.name.endswith(".retain.tmp") and not changed:
            changed = True
            with attachments._attachment_metadata_lock(metadata_path):
                current = json.loads(metadata_path.read_text(encoding="utf-8"))
                current["server_extension"] = {"literal": "not lost"}
                original_write(metadata_path, json.dumps(current), encoding="utf-8")
        return result

    monkeypatch.setattr(Path, "write_text", metadata_changed_after_staging)
    pinned = attachments.retain_read_attachment_for_workbook(
        IDENT, expected_sha256=metadata["sha256"], root=root)
    assert pinned["server_extension"] == {"literal": "not lost"}
    assert pinned["sha256"] == metadata["sha256"]
    assert pinned["retained_for_workbook"] is True
    assert not list(root.glob("*.retain.tmp"))


def test_missing_attachment_root_keeps_public_error_and_does_not_create_storage(tmp_path):
    root = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="chat attachment not found"):
        attachments.resolve_read_attachment(IDENT, root=root)
    attachments.consume_read_attachment(IDENT, root=root)
    assert not root.exists()
