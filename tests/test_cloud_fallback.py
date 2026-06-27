"""Облачный фолбэк по моделям: цепочка моделей + конечный таймаут на модель.
Зависший/ошибившийся провайдер не держит запрос 300с, а уступает следующей
модели, затем локальному MLX (W3.3)."""
import pytest

from proxy.routers.chat import LlmRuntime, _llm_runtime, cloud_fallback_models, cloud_model_timeout


def _rt(provider: str, model: str) -> LlmRuntime:
    return LlmRuntime(provider, "https://x/v1", "https://x/v1/chat/completions", model, "k", False)


def test_openrouter_chain_primary_first(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "vendor/b, vendor/c , vendor/d")
    chain = cloud_fallback_models(_rt("openrouter", "vendor/a"))
    assert chain == ["vendor/a", "vendor/b", "vendor/c", "vendor/d"]


def test_openrouter_dedup_primary(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "vendor/a,vendor/b,vendor/a")
    chain = cloud_fallback_models(_rt("openrouter", "vendor/a"))
    assert chain == ["vendor/a", "vendor/b"]  # primary не дублируется


def test_openrouter_no_env_means_single(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODELS", raising=False)
    assert cloud_fallback_models(_rt("openrouter", "vendor/a")) == ["vendor/a"]


def test_openai_compatible_uses_openai_models(monkeypatch):
    monkeypatch.setenv("OPENAI_MODELS", "m2,m3")
    assert cloud_fallback_models(_rt("openai", "m1")) == ["m1", "m2", "m3"]
    # openrouter env не должен влиять на openai
    monkeypatch.setenv("OPENROUTER_MODELS", "rr")
    assert cloud_fallback_models(_rt("openai", "m1")) == ["m1", "m2", "m3"]


def test_non_cloud_single_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "a,b,c")
    assert cloud_fallback_models(_rt("mlx", "qwen3:14b")) == ["qwen3:14b"]


def test_blank_entries_ignored(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", " , ,vendor/b, ")
    assert cloud_fallback_models(_rt("openrouter", "vendor/a")) == ["vendor/a", "vendor/b"]


def test_model_timeout_default_and_override(monkeypatch):
    monkeypatch.delenv("LES_CLOUD_MODEL_TIMEOUT_SEC", raising=False)
    assert cloud_model_timeout() == 45.0
    monkeypatch.setenv("LES_CLOUD_MODEL_TIMEOUT_SEC", "20")
    assert cloud_model_timeout() == 20.0


def test_direct_llm_runtime_downgrades_cloud_without_key(monkeypatch):
    monkeypatch.setenv("LES_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MLX_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("LLM_MODEL", "mlx-local")

    rt = _llm_runtime()

    assert rt.provider == "mlx"
    assert rt.model == "mlx-local"
