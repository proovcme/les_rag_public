"""W11.6 — переключение скан-OCR на gemma4:12b (ollama). Офлайн: фабрика + тело запроса.

Сеть не дёргаем: проверяем выбор бэкенда по env и форму OpenAI-совместимого
vision-запроса (как mail-VLM путь).
"""

from __future__ import annotations

import pytest

from backend.ocr_parser import (
    DEFAULT_OCR_MODEL,
    MLXVisualOCRParser,
    OllamaVisualOCRParser,
    build_vlm_ocr_body,
    make_ocr_parser,
)


@pytest.fixture(autouse=True)
def _clean_ocr_env(monkeypatch):
    for key in ("RAG_OCR_BACKEND", "RAG_OCR_MODEL", "RAG_OCR_URL", "OLLAMA_BASE_URL", "OLLAMA_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_default_backend_is_ollama_gemma():
    parser = make_ocr_parser()
    assert isinstance(parser, OllamaVisualOCRParser)
    assert parser.model_id == DEFAULT_OCR_MODEL == "gemma4:12b"


def test_env_selects_mlx_backend(monkeypatch):
    monkeypatch.setenv("RAG_OCR_BACKEND", "mlx")
    monkeypatch.setenv("RAG_OCR_MODEL", "mlx-community/some-vlm-4bit")
    parser = make_ocr_parser()
    assert isinstance(parser, MLXVisualOCRParser)
    assert parser.model_id == "mlx-community/some-vlm-4bit"


def test_legacy_glm_model_env_falls_back_to_gemma(monkeypatch):
    # старый .env с RAG_OCR_MODEL=GLM (модель удалена) на ollama-бэкенде → gemma
    monkeypatch.setenv("RAG_OCR_MODEL", "mlx-community/GLM-OCR-4bit")
    parser = make_ocr_parser()
    assert isinstance(parser, OllamaVisualOCRParser)
    assert parser.model_id == "gemma4:12b"


def test_explicit_model_override_respected(monkeypatch):
    monkeypatch.setenv("RAG_OCR_MODEL", "qwen2.5vl:7b")
    assert make_ocr_parser().model_id == "qwen2.5vl:7b"


def test_base_url_from_ollama_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://10.0.0.5:11434/")
    parser = make_ocr_parser()
    assert parser.base_url == "http://10.0.0.5:11434"  # trailing slash снят


def test_rag_ocr_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("RAG_OCR_URL", "http://vision-host:8000")
    assert make_ocr_parser().base_url == "http://vision-host:8000"


# ── тело vision-запроса ──

def test_build_body_shape():
    body = build_vlm_ocr_body("gemma4:12b", "QkFTRTY0", max_tokens=777)
    assert body["model"] == "gemma4:12b"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 777
    content = body["messages"][0]["content"]
    text_part = next(p for p in content if p["type"] == "text")
    img_part = next(p for p in content if p["type"] == "image_url")
    assert "дословно" in text_part["text"]
    assert img_part["image_url"]["url"] == "data:image/png;base64,QkFTRTY0"


def test_no_glm_default_anywhere_in_active_path():
    # дефолтная фабрика не должна тянуть удалённую GLM-OCR модель
    assert "GLM" not in make_ocr_parser().model_id
