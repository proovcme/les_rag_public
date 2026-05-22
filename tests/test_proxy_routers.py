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
