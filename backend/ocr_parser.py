"""
ocr_parser.py — Визуальное распознавание документов (скан-OCR).

Два бэкенда:
- ``mlx``    — MLXVisualOCRParser (исторический GLM-OCR / любой MLX-VLM, оффлайн на Metal);
- ``ollama`` — OllamaVisualOCRParser: OpenAI-совместимый vision-эндпоинт (ollama/llama.cpp),
  по умолчанию модель ``gemma4:12b`` (локальный vision-кандидат, ADR-9).

GLM-OCR-модель удалена из рантайма → дефолтный бэкенд скан-OCR — ``ollama`` (gemma4:12b).
Бэкенд и модель выбираются через env (см. ``make_ocr_parser``); при отсутствии конфигурации
парсер деградирует мягко (пустой результат + лог), не роняя индексацию.
"""
import os
import gc
import base64
import logging
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

        logger.info(f"[OCR] Загрузка модели MLX GLM-OCR: {self.model_id}")
        try:
            from mlx_vlm import load
            self.model, self.processor = load(self.model_id)
            logger.info("[OCR] Модель успешно загружена")
        except Exception as e:
            logger.error(f"[OCR] Ошибка загрузки модели {self.model_id}: {e}", exc_info=True)
            raise

    def unload_model(self) -> None:
        """Unload model from memory and clean Metal device caches."""
        if self.model is None and self.processor is None:
            return

        logger.info(f"[OCR] Выгрузка модели MLX GLM-OCR {self.model_id}")
        self.model = None
        self.processor = None

        # Explicitly run GC
        gc.collect()

        # Clean Metal command queue / memory allocator cache
        try:
            import mlx.core as mx
            mx.metal.clear_cache()
            logger.info("[OCR] Кэш Metal успешно очищен")
        except Exception as e:
            logger.warning(f"[OCR] Не удалось очистить кэш Metal: {e}")

    def pdf_to_images(self, pdf_path: Path, dpi: int = 150) -> List["PIL.Image.Image"]:
        """Convert PDF pages to PIL Images using pypdfium2."""
        return render_pdf_to_images(pdf_path, dpi=dpi)

    def ocr_page(self, image: "PIL.Image.Image", prompt: str = "Text Recognition:") -> str:
        """Run OCR on a single PIL Image."""
        self.load_model()
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template

        try:
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
        except Exception as e:
            logger.error(f"[OCR] Ошибка генерации OCR для страницы: {e}", exc_info=True)
            return f"[Ошибка распознавания страницы: {e}]"

    def parse_pdf(self, pdf_path: Path, prompt: str = "Text Recognition:", dpi: int = 150) -> str:
        """Perform OCR on all pages of a PDF document and return unified Markdown."""
        try:
            images = self.pdf_to_images(pdf_path, dpi=dpi)
            if not images:
                return ""

            pages_md = []
            for idx, img in enumerate(images, 1):
                logger.info(f"[OCR] Обработка страницы {idx}/{len(images)} ({pdf_path.name})")
                page_text = self.ocr_page(img, prompt=prompt)
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
        except Exception as e:
            logger.error(f"[OCR] Ошибка vision-OCR ({self.model_id} @ {self.base_url}): {e}")
            return f"[Ошибка распознавания страницы: {e}]"

    def parse_pdf(self, pdf_path: Path, prompt: Optional[str] = None, dpi: int = 150) -> str:
        if prompt:
            self.prompt = prompt
        images = render_pdf_to_images(pdf_path, dpi=dpi)
        if not images:
            return ""
        pages_md = []
        for idx, img in enumerate(images, 1):
            logger.info(f"[OCR] Стр. {idx}/{len(images)} ({pdf_path.name}) → {self.model_id}")
            pages_md.append(f"## Стр. {idx}\n\n{self.ocr_page(img)}")
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

        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as f:
            image.convert("RGB").save(f.name)
            try:
                out = subprocess.run(
                    [self.binary, f.name, "stdout", "-l", self.lang, "--psm", self.psm],
                    capture_output=True, timeout=float(os.getenv("RAG_OCR_TESSERACT_TIMEOUT", "120")),
                )
                return out.stdout.decode("utf-8", errors="ignore").strip()
            except FileNotFoundError:
                logger.error("[OCR] tesseract не найден (%s) — brew install tesseract tesseract-lang", self.binary)
                return ""
            except Exception as e:  # noqa: BLE001
                logger.error("[OCR] tesseract ошибка: %s", e)
                return ""

    def parse_pdf(self, pdf_path: Path, prompt: Optional[str] = None, dpi: int = 0) -> str:
        dpi = dpi or int(os.getenv("RAG_OCR_TESSERACT_DPI", "300"))  # tesseract любит 300
        images = render_pdf_to_images(pdf_path, dpi=dpi)
        if not images:
            return ""
        pages = []
        for idx, img in enumerate(images, 1):
            logger.info("[OCR] Стр. %s/%s (%s) → tesseract %s", idx, len(images), pdf_path.name, self.lang)
            pages.append(f"## Стр. {idx}\n\n{self.ocr_page(img)}")
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
