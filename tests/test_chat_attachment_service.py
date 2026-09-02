import json
import time

import pytest

from proxy.services.chat_attachment_service import (
    cleanup_expired,
    consume_read_attachment,
    preserve_read_attachment,
    resolve_read_attachment,
)


def test_read_attachment_is_server_owned_hash_checked_and_consumable(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-safe-source")
    root = tmp_path / "store"
    metadata = preserve_read_attachment(
        source,
        attachment_id="read_123456abcdef",
        original_name="ВОР.pdf",
        root=root,
    )

    stored, resolved = resolve_read_attachment("read_123456abcdef", root=root)
    assert stored.read_bytes() == source.read_bytes()
    assert resolved["sha256"] == metadata["sha256"]
    assert str(stored).startswith(str(root))

    consume_read_attachment("read_123456abcdef", root=root)
    with pytest.raises(FileNotFoundError):
        resolve_read_attachment("read_123456abcdef", root=root)


def test_read_attachment_rejects_client_paths_and_tampering(tmp_path):
    with pytest.raises(ValueError):
        resolve_read_attachment("../../etc/passwd", root=tmp_path)

    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    preserve_read_attachment(
        source,
        attachment_id="read_abcdef123456",
        original_name="source.txt",
        root=tmp_path / "store",
    )
    stored, _ = resolve_read_attachment("read_abcdef123456", root=tmp_path / "store")
    stored.write_text("changed!", encoding="utf-8")
    with pytest.raises(ValueError, match="mismatch"):
        resolve_read_attachment("read_abcdef123456", root=tmp_path / "store")


def test_expired_attachment_is_removed(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("old", encoding="utf-8")
    root = tmp_path / "store"
    preserve_read_attachment(
        source,
        attachment_id="read_111111111111",
        original_name="source.txt",
        root=root,
    )
    metadata_path = root / "read_111111111111.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["created_at_epoch"] = time.time() - 100
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert cleanup_expired(root=root, max_age_sec=10) == 1
    assert not metadata_path.exists()


def test_default_attachment_root_follows_windows_state_root(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    source = tmp_path / "source.csv"
    source.write_text("source_row;title\n1;work\n", encoding="utf-8")
    monkeypatch.setenv("LES_WINDOWS_STATE_ROOT", str(state_root))
    monkeypatch.delenv("LES_CHAT_ATTACHMENT_ROOT", raising=False)

    preserve_read_attachment(
        source,
        attachment_id="read_112233aabbcc",
        original_name="source.csv",
    )
    stored, _metadata = resolve_read_attachment("read_112233aabbcc")

    assert stored.parent == (state_root / "storage" / "chat_attachments").resolve()
