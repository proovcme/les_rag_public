import os

import pytest
from fastapi import HTTPException

from proxy.routers import auth, settings


@pytest.mark.asyncio
async def test_auth_verify_binds_and_rejects_mismatched_fingerprint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    conn = auth.auth_db()
    conn.execute(
        "INSERT INTO auth_keys (key_value, holder_name, role) VALUES (?, ?, ?)",
        ("user-key", "User", "user"),
    )
    conn.commit()
    conn.close()

    first = await auth.auth_verify(auth.AuthVerifyReq(key="user-key", fingerprint="device-a"))
    assert first == {"role": "user", "holder": "User"}

    with pytest.raises(HTTPException) as exc:
        await auth.auth_verify(auth.AuthVerifyReq(key="user-key", fingerprint="device-b"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_auth_key_lifecycle_endpoints(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    created = await auth.auth_create_key(
        auth.AuthKeyCreate(key_value="les_user", holder_name="User", role="user", expires_days=1),
        _admin=object(),
    )
    assert created["status"] == "created"
    assert created["expires_at"]

    rows = await auth.auth_list_keys(_admin=object())
    assert rows[0]["key_value"] == "les_user"
    assert rows[0]["device_bound"] == 0

    await auth.auth_verify(auth.AuthVerifyReq(key="les_user", fingerprint="device-a"))
    rows = await auth.auth_list_keys(_admin=object())
    assert rows[0]["device_bound"] == 1

    toggled = await auth.auth_toggle_key(
        auth.AuthKeyToggle(key_value="les_user", is_active=0),
        _admin=object(),
    )
    assert toggled == {"status": "ok", "key_value": "les_user", "is_active": 0}
    with pytest.raises(HTTPException) as disabled:
        await auth.auth_verify(auth.AuthVerifyReq(key="les_user", fingerprint="device-a"))
    assert disabled.value.status_code == 401

    await auth.auth_toggle_key(auth.AuthKeyToggle(key_value="les_user", is_active=1), _admin=object())
    reset = await auth.auth_reset_device(auth.AuthKeyToggle(key_value="les_user"), _admin=object())
    assert reset == {"status": "ok", "key_value": "les_user"}
    await auth.auth_verify(auth.AuthVerifyReq(key="les_user", fingerprint="device-b"))

    deleted = await auth.auth_delete_key_body(auth.AuthKeyDelete(key_value="les_user"), _admin=object())
    assert deleted == {"status": "deleted", "key_value": "les_user"}
    assert await auth.auth_list_keys(_admin=object()) == []


@pytest.mark.asyncio
async def test_auth_create_key_rejects_unknown_role(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    with pytest.raises(HTTPException) as exc:
        await auth.auth_create_key(
            auth.AuthKeyCreate(key_value="les_bad", holder_name="Bad", role="owner"),
            _admin=object(),
        )

    assert exc.value.status_code == 400


def test_seed_admin_key_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("ADMIN_PASSWORD", "secret-admin")

    auth.seed_admin_key()
    auth.seed_admin_key()

    conn = auth.auth_db()
    try:
        rows = conn.execute(
            "SELECT key_value, holder_name, role FROM auth_keys WHERE role='admin'"
        ).fetchall()
    finally:
        conn.close()

    assert [dict(row) for row in rows] == [
        {"key_value": "secret-admin", "holder_name": "admin", "role": "admin"}
    ]


@pytest.mark.asyncio
async def test_save_settings_updates_env_file_and_process_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("LLM_MODEL=old\nQDRANT_URL=http://qdrant:6333\n")
    monkeypatch.setattr(settings, "ENV_PATH", env_path)
    monkeypatch.setattr(settings, "docker_control_enabled", lambda: False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    result = await settings.save_settings(
        settings.SettingsRequest(llm_model="new-model", mlx_url="http://mlx:8080"),
        restart=False,
        _admin=object(),
    )

    assert result == {
        "status": "saved",
        "updated": {"LLM_MODEL": "new-model", "MLX_URL": "http://mlx:8080"},
        "restarting": False,
    }
    assert "LLM_MODEL=new-model" in env_path.read_text()
    assert "MLX_URL=http://mlx:8080" in env_path.read_text()
    assert os.environ["LLM_MODEL"] == "new-model"


@pytest.mark.asyncio
async def test_save_settings_updates_mail_imap_without_exposing_password(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("MAIL_IMAP_HOST=old.example.com\nMAIL_IMAP_PASSWORD=old-secret\n")
    monkeypatch.setattr(settings, "ENV_PATH", env_path)
    monkeypatch.setenv("MAIL_IMAP_PASSWORD", "old-secret")

    result = await settings.save_settings(
        settings.SettingsRequest(
            mail_imap_host="imap.yandex.ru",
            mail_imap_port=993,
            mail_imap_ssl=True,
            mail_imap_login="mail@yandex.ru",
            mail_imap_password="app-secret",
            mail_imap_folders="INBOX,Sent",
            mail_attachment_ocr_enabled=True,
        ),
        restart=False,
        _admin=object(),
    )

    assert result["updated"]["MAIL_IMAP_HOST"] == "imap.yandex.ru"
    assert result["updated"]["MAIL_IMAP_PASSWORD"] == "***"
    text = env_path.read_text()
    assert "MAIL_IMAP_HOST=imap.yandex.ru" in text
    assert "MAIL_IMAP_PASSWORD=app-secret" in text
    assert os.environ["MAIL_IMAP_LOGIN"] == "mail@yandex.ru"

    payload = await settings.get_settings(_user=object())
    assert payload["mail"]["imap_password_set"] is True
    assert "password" not in payload["mail"]


@pytest.mark.asyncio
async def test_save_settings_rejects_unsafe_values(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENV_PATH", tmp_path / ".env")

    with pytest.raises(HTTPException) as bad_url:
        await settings.save_settings(
            settings.SettingsRequest(mlx_url="file:///tmp/socket"),
            restart=False,
            _admin=object(),
        )
    assert bad_url.value.status_code == 400

    with pytest.raises(HTTPException) as newline:
        await settings.save_settings(
            settings.SettingsRequest(llm_model="ok\nEVIL=1"),
            restart=False,
            _admin=object(),
        )
    assert newline.value.status_code == 400
