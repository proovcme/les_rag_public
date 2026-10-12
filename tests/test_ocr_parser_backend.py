"""W11.6 — переключение скан-OCR на gemma4:12b (ollama). Офлайн: фабрика + тело запроса.

Сеть не дёргаем: проверяем выбор бэкенда по env и форму OpenAI-совместимого
vision-запроса (как mail-VLM путь).
"""

from __future__ import annotations

import pytest
from PIL import Image

from backend.ocr_parser import (
    DEFAULT_OCR_MODEL,
    MLXVisualOCRParser,
    OCRProcessingError,
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


def test_ollama_failure_is_typed_and_does_not_leak_transport_details(monkeypatch):
    import httpx

    parser = OllamaVisualOCRParser(base_url="http://private-host:11434")
    logged = []
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("C:/secret/model.gguf token=private")
        ),
    )
    monkeypatch.setattr("backend.ocr_parser.logger.error", lambda *args: logged.append(args))

    with pytest.raises(OCRProcessingError) as raised:
        parser.ocr_page(Image.new("RGB", (8, 8)))

    assert raised.value.code == "ollama_vision_failed"
    assert "secret" not in str(raised.value)
    assert "private-host" not in str(logged)
    assert "model.gguf" not in str(logged)


def test_mlx_load_failure_is_typed_and_does_not_leak_details(monkeypatch):
    parser = MLXVisualOCRParser(model_id="C:/secret/model")
    logged = []
    monkeypatch.setattr(
        parser,
        "load_model",
        lambda: (_ for _ in ()).throw(RuntimeError("C:/secret/model weights corrupt")),
    )
    monkeypatch.setattr("backend.ocr_parser.logger.error", lambda *args: logged.append(args))

    with pytest.raises(OCRProcessingError) as raised:
        parser.ocr_page(Image.new("RGB", (8, 8)))

    assert raised.value.code == "mlx_vision_load_failed"
    assert "secret" not in str(raised.value)
    assert "secret" not in str(logged)


@pytest.mark.parametrize("parser", [OllamaVisualOCRParser(), MLXVisualOCRParser()])
def test_visual_parse_pdf_annotates_typed_failure_with_page(monkeypatch, tmp_path, parser):
    images = [Image.new("RGB", (8, 8)), Image.new("RGB", (8, 8))]
    if isinstance(parser, MLXVisualOCRParser):
        monkeypatch.setattr(parser, "pdf_to_images", lambda *_args, **_kwargs: images)
        monkeypatch.setattr(parser, "unload_model", lambda: None)
    else:
        monkeypatch.setattr("backend.ocr_parser.render_pdf_to_images", lambda *_args, **_kwargs: images)
    calls = 0

    def fail_second(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OCRProcessingError("vision_backend_failed")
        return "page one"

    monkeypatch.setattr(parser, "ocr_page", fail_second)
    with pytest.raises(OCRProcessingError) as raised:
        parser.parse_pdf(tmp_path / "scan.pdf")
    assert raised.value.code == "vision_backend_failed"
    assert raised.value.page == 2
    assert "Ошибка распознавания" not in str(raised.value)
