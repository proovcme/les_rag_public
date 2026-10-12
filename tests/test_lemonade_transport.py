from dataclasses import FrozenInstanceError

import pytest

from extensions.lemonade.contracts import LemonadeHealth, LemonadeModelDescriptor
from extensions.lemonade.transport import lemonade_transport_options
from proxy.services.llm_transport_profile_service import apply_transport_options


@pytest.mark.parametrize(
    ("provider", "model_id", "backend", "body", "expected"),
    [
        (
            "lemonade",
            "Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S",
            "llama_cpp",
            {"model": "Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S", "max_tokens": 400},
            {
                "model": "Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S",
                "max_tokens": 400,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        ),
        (
            "lemonade",
            "Qwen3.6-35B-A3B-FLM",
            "flm",
            {"model": "Qwen3.6-35B-A3B-FLM"},
            {"model": "Qwen3.6-35B-A3B-FLM"},
        ),
        (
            "lemonade",
            "Qwen3.5-35B-A3B-GGUF",
            "llama_cpp",
            {"model": "Qwen3.5-35B-A3B-GGUF"},
            {"model": "Qwen3.5-35B-A3B-GGUF"},
        ),
        (
            "openai",
            "Qwen3.6-35B-A3B-GGUF",
            "llama_cpp",
            {"model": "Qwen3.6-35B-A3B-GGUF"},
            {"model": "Qwen3.6-35B-A3B-GGUF"},
        ),
        (
            "lemonade",
            "Qwen3.6-35B-A3B-GGUF",
            "llama_cpp",
            {"chat_template_kwargs": {"custom": "kept", "enable_thinking": True}},
            {"chat_template_kwargs": {"custom": "kept", "enable_thinking": True}},
        ),
    ],
)
def test_lemonade_transport_policy_matrix(provider, model_id, backend, body, expected):
    original = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in body.items()
    }

    result = lemonade_transport_options(
        body,
        provider=provider,
        model_id=model_id,
        backend=backend,
    )

    assert result == expected
    assert body == original


def test_shared_transport_delegates_lemonade_policy_from_explicit_facts():
    result = apply_transport_options(
        {"model": "Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S"},
        "lemonade",
        model_id="Carnice-Qwen3.6-MoE-35B-A3B-IQ2_S",
        backend="llama_cpp",
    )

    assert result["chat_template_kwargs"] == {"enable_thinking": False}


def test_freetoken_transport_contract_remains_exact():
    original = {
        "model": "Qwen3.6-35B-A3B-NVFP4",
        "max_tokens": 400,
        "chat_template_kwargs": {"custom_flag": "kept"},
    }

    result = apply_transport_options(original, "freetoken")

    assert result == {
        "model": "Qwen3.6-35B-A3B-NVFP4",
        "max_tokens": 400,
        "chat_template_kwargs": {
            "custom_flag": "kept",
            "enable_thinking": False,
        },
    }
    assert original["chat_template_kwargs"] == {"custom_flag": "kept"}


@pytest.mark.parametrize("model_id", ["", "   "])
def test_model_descriptor_rejects_blank_model_id(model_id):
    with pytest.raises(ValueError, match="model_id"):
        LemonadeModelDescriptor(model_id=model_id, backend="llama_cpp")


def test_model_descriptor_rejects_unknown_backend():
    with pytest.raises(ValueError, match="backend"):
        LemonadeModelDescriptor(model_id="Qwen3.6-35B", backend="mystery")


def test_lemonade_contracts_are_immutable():
    descriptor = LemonadeModelDescriptor(
        model_id="Qwen3.6-35B-A3B-GGUF",
        backend="llama_cpp",
    )
    health = LemonadeHealth(available=True, models=(descriptor,))

    with pytest.raises(FrozenInstanceError):
        descriptor.model_id = "changed"
    with pytest.raises(FrozenInstanceError):
        health.available = False
