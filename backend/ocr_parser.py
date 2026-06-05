"""
ocr_parser.py — Визуальное распознавание документов через MLX (GLM-OCR).
"""
import os
import gc
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


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
        logger.info(f"[OCR] Рендеринг PDF в изображения: {pdf_path.name}")
        import pypdfium2 as pdfium
        from PIL import Image

        doc = pdfium.PdfDocument(str(pdf_path))
        images = []
        try:
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                scale = dpi / 72.0
                bitmap = page.render(scale=scale)
                pil_img = bitmap.to_pil()
                images.append(pil_img)
        finally:
            doc.close()
        logger.info(f"[OCR] Успешно отрендерено страниц: {len(images)}")
        return images

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
