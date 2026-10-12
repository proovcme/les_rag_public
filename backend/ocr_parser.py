"""
ocr_parser.py — Визуальное распознавание документов (скан-OCR).

Три бэкенда:
- ``mlx``    — MLXVisualOCRParser (исторический GLM-OCR / любой MLX-VLM, оффлайн на Metal);
- ``ollama`` — OllamaVisualOCRParser: OpenAI-совместимый vision-эндпоинт (ollama/llama.cpp),
  по умолчанию модель ``gemma4:12b`` (локальный vision-кандидат, ADR-9).
- ``tesseract`` — локальный CLI с постраничным рендерингом и закрытым PNG на Windows.

GLM-OCR-модель удалена из рантайма → дефолтный бэкенд скан-OCR — ``ollama`` (gemma4:12b).
Бэкенд и модель выбираются через env (см. ``make_ocr_parser``); при отсутствии конфигурации
ошибка распознавания возвращается как OCRProcessingError, никогда как текст evidence.
Обязательный OCR завершает файл явной ошибкой, сохраняя его прежний индекс.
"""
import os
import gc
import base64
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Дефолтный локальный vision для скан-OCR после удаления GLM-OCR (ADR-9).
DEFAULT_OCR_MODEL = "gemma4:12b"
_OCR_PROMPT = (
    "Перепиши весь текст с этой страницы документа дословно и полностью, сохраняя структуру: "
    "заголовки, списки, таблицы (как текст со столбцами). Только распознанный текст, без "
    "комментариев и пояснений."
)


class OCRProcessingError(RuntimeError):
    """Stable, non-secret OCR failure contract for callers and subprocesses."""

    def __init__(self, code: str, *, page: int | None = None):
        self.code = code
        self.page = page
        suffix = f":page={page}" if page is not None else ""
        super().__init__(f"{code}{suffix}")


def iter_pdf_images(pdf_path: Path, dpi: int = 150) -> Iterator[tuple[int, "PIL.Image.Image"]]:
    """Yield one independent page image at a time and release renderer resources."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            bitmap = None
            image = None
            try:
                bitmap = page.render(scale=dpi / 72.0)
                image = bitmap.to_pil().copy()
                yield page_index + 1, image
            finally:
                if image is not None:
                    image.close()
                if bitmap is not None:
                    close = getattr(bitmap, "close", None)
                    if callable(close):
                        close()
                close = getattr(page, "close", None)
                if callable(close):
                    close()
    finally:
        doc.close()


def render_pdf_to_images(pdf_path: Path, dpi: int = 150) -> List["PIL.Image.Image"]:
    """PDF → список PIL-изображений (pypdfium2). Общий рендер для всех бэкендов."""
    logger.info(f"[OCR] Рендеринг PDF в изображения: {pdf_path.name}")
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    images = []
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            bitmap = page.render(scale=dpi / 72.0)
            images.append(bitmap.to_pil())
    finally:
        doc.close()
    logger.info(f"[OCR] Успешно отрендерено страниц: {len(images)}")
    return images


class MLXVisualOCRParser:
    def __init__(self, model_id: str = "mlx-community/GLM-OCR-4bit"):
        self.model_id = model_id
        self.model = None
        self.processor = None

    def load_model(self) -> None:
        """Lazy loading of the MLX GLM-OCR model and processor."""
        if self.model is not None and self.processor is not None:
            return

        logger.info("[OCR] Загрузка модели MLX vision-OCR")
        try:
            from mlx_vlm import load
            self.model, self.processor = load(self.model_id)
            logger.info("[OCR] Модель успешно загружена")
        except OCRProcessingError:
            raise
        except Exception:
            logger.error("[OCR] MLX vision failed: mlx_vision_load_failed")
            raise OCRProcessingError("mlx_vision_load_failed") from None

    def unload_model(self) -> None:
        """Unload model from memory and clean Metal device caches."""
        if self.model is None and self.processor is None:
            return

        logger.info("[OCR] Выгрузка модели MLX vision-OCR")
        self.model = None
        self.processor = None

        # Explicitly run GC
        gc.collect()

        # Clean Metal command queue / memory allocator cache
        try:
            import mlx.core as mx
            mx.metal.clear_cache()
            logger.info("[OCR] Кэш Metal успешно очищен")
        except Exception:
            logger.warning("[OCR] Не удалось очистить кэш Metal")

    def pdf_to_images(self, pdf_path: Path, dpi: int = 150) -> List["PIL.Image.Image"]:
        """Convert PDF pages to PIL Images using pypdfium2."""
        return render_pdf_to_images(pdf_path, dpi=dpi)

    def ocr_page(self, image: "PIL.Image.Image", prompt: str = "Text Recognition:") -> str:
        """Run OCR on a single PIL Image."""
        try:
            self.load_model()
        except OCRProcessingError:
            raise
        except Exception:
            logger.error("[OCR] MLX vision failed: mlx_vision_load_failed")
            raise OCRProcessingError("mlx_vision_load_failed") from None

        try:
            from mlx_vlm import generate
            from mlx_vlm.prompt_utils import apply_chat_template

            formatted_prompt = apply_chat_template(
                self.processor, self.model.config, prompt, num_images=1
            )
            res = generate(
                self.model,
                self.processor,
                prompt=formatted_prompt,
                image=image,
                temperature=0.0,
                repetition_penalty=1.2,
                repetition_context_size=64,
                max_tokens=1024
            )
            if hasattr(res, "text"):
                return res.text or ""
            return res or ""
        except OCRProcessingError:
            raise
        except Exception:
            logger.error("[OCR] MLX vision failed: mlx_vision_generate_failed")
            raise OCRProcessingError("mlx_vision_generate_failed") from None

    def parse_pdf(self, pdf_path: Path, prompt: str = "Text Recognition:", dpi: int = 150) -> str:
        """Perform OCR on all pages of a PDF document and return unified Markdown."""
        try:
            images = self.pdf_to_images(pdf_path, dpi=dpi)
            if not images:
                return ""

            pages_md = []
            for idx, img in enumerate(images, 1):
                logger.info(f"[OCR] Обработка страницы {idx}/{len(images)} ({pdf_path.name})")
                try:
                    page_text = self.ocr_page(img, prompt=prompt)
                except OCRProcessingError as error:
                    raise OCRProcessingError(error.code, page=idx) from error
                pages_md.append(f"## Стр. {idx}\n\n{page_text}")

            return "\n\n".join(pages_md)
        finally:
            self.unload_model()


def _pil_to_png_b64(image) -> str:
    """PIL Image → base64 PNG для data-URL в vision-запросе."""
    import io

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def build_vlm_ocr_body(model: str, image_b64: str, *, prompt: str = _OCR_PROMPT,
                       max_tokens: int = 1536, mime: str = "image/png") -> dict:
    """Тело OpenAI-совместимого vision-запроса (одна страница). Вынесено для тестируемости."""
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }


class OllamaVisualOCRParser:
    """Скан-OCR через OpenAI-совместимый vision-эндпоинт (ollama/llama.cpp), напр. gemma4:12b.

    Зеркалит mail-VLM путь (`backend/mail_profile._vlm_image_bytes`): POST
    `{base_url}/v1/chat/completions` с image_url(data-url). База/модель — из env.
    """

    def __init__(self, model_id: str = DEFAULT_OCR_MODEL, base_url: str = "",
                 *, prompt: str = _OCR_PROMPT, max_tokens: int = 1536, timeout: float = 120.0):
        self.model_id = model_id
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.api_key = os.getenv("OLLAMA_API_KEY", "").strip()
        self.prompt = prompt
        self.max_tokens = max_tokens
        self.timeout = timeout

    def ocr_page(self, image) -> str:
        import httpx

        body = build_vlm_ocr_body(self.model_id, _pil_to_png_b64(image),
                                  prompt=self.prompt, max_tokens=self.max_tokens)
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = httpx.post(f"{self.base_url}/v1/chat/completions", json=body,
                              headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return str(content or "").strip()
        except OCRProcessingError:
            raise
        except Exception:
            logger.error("[OCR] Ollama vision failed: ollama_vision_failed")
            raise OCRProcessingError("ollama_vision_failed") from None

    def parse_pdf(self, pdf_path: Path, prompt: Optional[str] = None, dpi: int = 150) -> str:
        if prompt:
            self.prompt = prompt
        images = render_pdf_to_images(pdf_path, dpi=dpi)
        if not images:
            return ""
        pages_md = []
        for idx, img in enumerate(images, 1):
            logger.info(f"[OCR] Стр. {idx}/{len(images)} ({pdf_path.name}) → {self.model_id}")
            try:
                page_text = self.ocr_page(img)
            except OCRProcessingError as error:
                raise OCRProcessingError(error.code, page=idx) from error
            pages_md.append(f"## Стр. {idx}\n\n{page_text}")
        return "\n\n".join(pages_md)


class TesseractOCRParser:
    """Скан-OCR через бинарь Tesseract (offline, без Python-зависимостей → не конфликтует с MLX).

    Лучший локальный путь для русского: `brew install tesseract tesseract-lang`. Зовётся
    subprocess'ом — изолирован от proxy-venv (transformers 5.x и пр. не трогает). Язык —
    ``RAG_OCR_TESSERACT_LANG`` (дефолт ``rus+eng``), бинарь — ``RAG_OCR_TESSERACT_BIN``.
    """

    def __init__(self, lang: str = "", binary: str = ""):
        import shutil

        self.lang = lang or os.getenv("RAG_OCR_TESSERACT_LANG", "rus+eng")
        self.binary = (binary or os.getenv("RAG_OCR_TESSERACT_BIN", "")
                       or shutil.which("tesseract") or "/opt/homebrew/bin/tesseract")
        self.psm = os.getenv("RAG_OCR_TESSERACT_PSM", "6")  # 6 — единый блок текста

    def ocr_page(self, image) -> str:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory(prefix="les-ocr-") as directory:
            image_path = Path(directory) / "page.png"
            converted = image.convert("RGB")
            try:
                converted.save(image_path)
            finally:
                converted.close()
            try:
                completed = subprocess.run(
                    [self.binary, str(image_path), "stdout", "-l", self.lang, "--psm", self.psm],
                    capture_output=True,
                    timeout=float(os.getenv("RAG_OCR_TESSERACT_TIMEOUT", "120")),
                )
            except FileNotFoundError:
                logger.error("[OCR] tesseract execution failed: tesseract_missing")
                raise OCRProcessingError("tesseract_missing") from None
            except subprocess.TimeoutExpired:
                logger.error("[OCR] tesseract превысил таймаут")
                raise OCRProcessingError("tesseract_timeout") from None
            if completed.returncode != 0:
                logger.error("[OCR] tesseract завершился с кодом %s", completed.returncode)
                raise OCRProcessingError(f"tesseract_exit_{completed.returncode}")
            return completed.stdout.decode("utf-8", errors="ignore").strip()

    def parse_pdf(self, pdf_path: Path, prompt: Optional[str] = None, dpi: int = 0) -> str:
        dpi = dpi or int(os.getenv("RAG_OCR_TESSERACT_DPI", "300"))  # tesseract любит 300
        pages = []
        for page_number, image in iter_pdf_images(pdf_path, dpi):
            logger.info("[OCR] Стр. %s (%s) → tesseract %s", page_number, pdf_path.name, self.lang)
            try:
                text = self.ocr_page(image)
            except OCRProcessingError as error:
                raise OCRProcessingError(error.code, page=page_number) from error
            if text.strip():
                pages.append(f"## Стр. {page_number}\n\n{text}")
        return "\n\n".join(pages)


def make_ocr_parser(model_id: Optional[str] = None):
    """Фабрика скан-OCR парсера по env. Бэкенд: ``RAG_OCR_BACKEND`` (tesseract|ollama|mlx).

    ``tesseract`` — лучший локальный путь для русского (бинарь, изолирован от venv, без VLM).
    ``ollama`` (gemma4:12b) — vision-VLM. ``mlx`` — MLX-VLM (оффлайн-Metal).
    """
    backend = os.getenv("RAG_OCR_BACKEND", "ollama").strip().lower()
    model = model_id or os.getenv("RAG_OCR_MODEL", DEFAULT_OCR_MODEL)
    if backend in ("tesseract", "tess"):
        return TesseractOCRParser()
    if backend in ("mlx", "mlx-vlm"):
        # Историческая GLM-OCR модель удалена — для MLX-пути нужна явная MLX-VLM модель.
        return MLXVisualOCRParser(model_id=model if model != DEFAULT_OCR_MODEL else "mlx-community/GLM-OCR-4bit")
    return OllamaVisualOCRParser(
        model_id=model if model != "mlx-community/GLM-OCR-4bit" else DEFAULT_OCR_MODEL,
        base_url=os.getenv("RAG_OCR_URL", ""),
    )
