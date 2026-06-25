"""#4: профиль-специфичные оверрайды .env (Windows: ollama вместо Mac/MLX-дефолтов).

`lesctl init --profile windows-lite` раньше писал .env как копию env.example (CoreML/MLX —
маковские дефолты), а оверрайды профиля не применял → эмбеддер/провайдер настроены неверно.
Теперь profile_env_overrides + apply_env_overrides идемпотентно проставляют правильные ключи.
"""

from tools.install_les import apply_env_overrides, profile_env_overrides


def test_windows_lite_overrides_point_to_ollama():
    ov = profile_env_overrides("windows-lite")
    assert ov["LES_LLM_PROVIDER"] == "ollama"
    assert ov["OLLAMA_MODEL"] == "qwen3.5:9b"
    # эмбеддер → ollama /v1/embeddings (bge-m3, 1024 dims); НЕ MLX-хост и НЕ coreml
    assert ov["MLX_URL"] == "http://127.0.0.1:11434"
    assert ov["EMBED_MODEL"] == "bge-m3" and ov["EMBEDDING_MODEL"] == "bge-m3"
    assert ov["RAG_VECTOR_SIZE"] == "1024"
    assert ov["EMBED_BACKEND"] != "coreml"
    assert ov["CHAT_VALIDATION_ENABLED"] == "false"


def test_other_profiles_have_no_overrides():
    # маковский/прочие профили не трогаем — поведение прежнее
    assert profile_env_overrides("mac-native") == {}
    assert profile_env_overrides("linux-docker") == {}
    assert profile_env_overrides(None) == {}


def test_apply_overrides_updates_existing_and_appends_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        "EMBED_BACKEND=coreml\n"
        "MLX_URL=http://127.0.0.1:8080\n"
        "UNRELATED=keep-me\n",
        encoding="utf-8",
    )
    applied = apply_env_overrides(
        {"EMBED_BACKEND": "ollama", "MLX_URL": "http://127.0.0.1:11434", "NEW_KEY": "val"},
        target=env,
    )
    text = env.read_text(encoding="utf-8")
    # существующие ключи обновлены (CoreML→ollama, MLX→ollama)
    assert "EMBED_BACKEND=ollama" in text and "EMBED_BACKEND=coreml" not in text
    assert "MLX_URL=http://127.0.0.1:11434" in text and ":8080" not in text
    # отсутствующий ключ дописан, посторонние строки и комментарий сохранены
    assert "NEW_KEY=val" in text
    assert "UNRELATED=keep-me" in text and "# comment" in text
    assert set(applied) == {"EMBED_BACKEND", "MLX_URL", "NEW_KEY"}


def test_apply_overrides_idempotent(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LES_LLM_PROVIDER=mlx\n", encoding="utf-8")
    ov = {"LES_LLM_PROVIDER": "ollama"}
    apply_env_overrides(ov, target=env)
    apply_env_overrides(ov, target=env)  # второй прогон не дублирует
    assert env.read_text(encoding="utf-8").count("LES_LLM_PROVIDER=") == 1


def test_apply_empty_overrides_noop(tmp_path):
    env = tmp_path / ".env"
    env.write_text("X=1\n", encoding="utf-8")
    assert apply_env_overrides({}, target=env) == []
    assert env.read_text(encoding="utf-8") == "X=1\n"
