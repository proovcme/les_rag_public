"""Offline tests for the first-run provider onboarding wizard."""

from __future__ import annotations

from tools import onboard_provider as op


def test_build_updates_mlx_sets_both_model_keys():
    updates = op.build_updates("mlx")
    assert updates["LES_LLM_PROVIDER"] == "mlx"
    # MLX shares the model between host start and proxy request path.
    assert updates["MLX_MODEL"] == updates["LLM_MODEL"]
    assert updates["LES_CLOUD_CONSENT"] == "false"


def test_build_updates_cloud_writes_key_and_consent():
    updates = op.build_updates("openrouter", api_key="sk-test", model="gpt-x")
    assert updates["LES_LLM_PROVIDER"] == "openrouter"
    assert updates["OPENROUTER_API_KEY"] == "sk-test"
    assert updates["OPENROUTER_MODEL"] == "gpt-x"
    assert updates["OPENROUTER_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert updates["LES_CLOUD_CONSENT"] == "true"


def test_build_updates_openai_default_base_url():
    updates = op.build_updates("openai", api_key="k")
    assert updates["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
    assert updates["OPENAI_API_KEY"] == "k"


def test_build_updates_ollama_is_local_no_key():
    updates = op.build_updates("ollama")
    assert updates["LES_LLM_PROVIDER"] == "ollama"
    assert updates["OLLAMA_BASE_URL"].startswith("http://127.0.0.1")
    assert "OLLAMA_API_KEY" not in updates  # no key given → not written
    assert updates["LES_CLOUD_CONSENT"] == "false"


def test_build_updates_rejects_unknown_provider():
    try:
        op.build_updates("gpt5")
    except ValueError as exc:
        assert "unknown provider" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown provider")


def test_persist_env_is_idempotent_and_replaces(tmp_path):
    env = tmp_path / ".env"
    env.write_text("LES_LLM_PROVIDER=mlx\nKEEP=1\n", encoding="utf-8")
    op.persist_env({"LES_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"}, path=env)
    text = env.read_text(encoding="utf-8")
    assert "LES_LLM_PROVIDER=openai" in text
    assert text.count("LES_LLM_PROVIDER=") == 1  # replaced, not duplicated
    assert "KEEP=1" in text  # untouched lines preserved
    assert "OPENAI_API_KEY=k" in text  # new key appended


def test_already_configured(tmp_path):
    env = tmp_path / ".env"
    assert op.already_configured(env) is False
    env.write_text("LES_LLM_PROVIDER=mlx\n", encoding="utf-8")
    assert op.already_configured(env) is True


def test_main_skip_if_configured(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("LES_LLM_PROVIDER=openai\n", encoding="utf-8")
    monkeypatch.setattr(op, "ENV_PATH", env)
    assert op.main(["--skip-if-configured"]) == 0
    assert "пропускаю" in capsys.readouterr().out
    # Unchanged.
    assert env.read_text(encoding="utf-8").strip() == "LES_LLM_PROVIDER=openai"


def test_main_non_interactive_provider_writes_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(op, "ENV_PATH", env)
    assert op.main(["--provider", "openrouter", "--api-key", "sk-1"]) == 0
    text = env.read_text(encoding="utf-8")
    assert "LES_LLM_PROVIDER=openrouter" in text
    assert "OPENROUTER_API_KEY=sk-1" in text


def test_main_show(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("LES_LLM_PROVIDER=ollama\n", encoding="utf-8")
    monkeypatch.setattr(op, "ENV_PATH", env)
    assert op.main(["--show"]) == 0
    assert capsys.readouterr().out.strip() == "ollama"
