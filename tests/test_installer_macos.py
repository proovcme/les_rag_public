"""Offline tests for the macOS double-click installer tooling."""

from __future__ import annotations

import plistlib

from tools import build_macos_app, onboard_models


def test_resolve_models_reads_env_and_skips_non_hf(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "MLX_MODEL=mlx-community/Qwen3.5-4B-OptiQ-4bit",
                "LLM_MODEL=mlx-community/Qwen3.5-4B-OptiQ-4bit  # same as MLX",
                "EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B",
                "RAG_OCR_MODEL=gemma4:12b",  # ollama tag — not an HF repo
                "COREML_EMBED_MODEL=artifacts/coreml/x.mlpackage",  # local path
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(onboard_models, "ROOT", tmp_path)

    models = onboard_models.resolve_models()

    # Dedup of MLX/LLM, ollama tag and local path dropped.
    assert models == [
        "mlx-community/Qwen3.5-4B-OptiQ-4bit",
        "Qwen/Qwen3-Embedding-0.6B",
    ]


def test_resolve_models_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(onboard_models, "ROOT", tmp_path)  # no .env, no env.example
    models = onboard_models.resolve_models()
    assert "mlx-community/Qwen3.5-4B-OptiQ-4bit" in models
    assert "Qwen/Qwen3-Embedding-0.6B" in models


def test_is_cloud_only(tmp_path, monkeypatch):
    monkeypatch.setattr(onboard_models, "ROOT", tmp_path)
    (tmp_path / ".env").write_text("LES_PROVIDER=openai\n", encoding="utf-8")
    assert onboard_models.is_cloud_only() is True
    (tmp_path / ".env").write_text("LES_PROVIDER=local\n", encoding="utf-8")
    assert onboard_models.is_cloud_only() is False


def test_info_plist_is_valid_and_versioned(tmp_path):
    contents = tmp_path / "Contents"
    contents.mkdir()
    build_macos_app._write_info_plist(contents, "9.9.9")

    parsed = plistlib.loads((contents / "Info.plist").read_bytes())
    assert parsed["CFBundleVersion"] == "9.9.9"
    assert parsed["CFBundleExecutable"] == "LES"
    assert parsed["CFBundleIdentifier"] == "me.ovc.les"
