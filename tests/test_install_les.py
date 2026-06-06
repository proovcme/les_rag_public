from tools import install_les


def test_ensure_dirs_creates_required_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(install_les, "ROOT", tmp_path)

    created = install_les.ensure_dirs()

    assert "data" in created
    assert "RAG_Content" in created
    assert (tmp_path / "data" / "mail_imap_checkpoints").exists()


def test_init_env_does_not_overwrite_existing_env(tmp_path, monkeypatch):
    monkeypatch.setattr(install_les, "ROOT", tmp_path)
    (tmp_path / "env.example").write_text("ADMIN_PASSWORD=example\n", encoding="utf-8")
    (tmp_path / ".env").write_text("ADMIN_PASSWORD=real\n", encoding="utf-8")

    result = install_les.init_env()

    assert result == ".env exists"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "ADMIN_PASSWORD=real\n"


def test_init_env_can_create_env(tmp_path, monkeypatch):
    monkeypatch.setattr(install_les, "ROOT", tmp_path)
    (tmp_path / "env.example").write_text("ADMIN_PASSWORD=example\n", encoding="utf-8")

    result = install_les.init_env()

    assert result == ".env created from env.example"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "ADMIN_PASSWORD=example\n"
