"""
rules_extractor.py — Модуль извлечения структурированных требований на базе google/langextract.
"""
import os
import uuid
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EngineeringRule(BaseModel):
    subject: str = Field(description="Субъект правила (например, 'эвакуационный выход', 'пожарный извещатель')")
    parameter: str = Field(description="Физический или технический параметр (например, 'ширина', 'расстояние', 'высота')")
    operator: str = Field(description="Математический оператор (например, '>=', '<=', '=', 'не менее', 'не более')")
    value: float = Field(description="Численное значение параметра (например, 1.2, 15, 0.5)")
    unit: str = Field(description="Единица измерения (например, 'м', 'сек', 'чел', 'кв.м')")
    condition: Optional[str] = Field(None, description="Дополнительные условия или ограничения (например, 'при числе людей более 15')")


class StructuredRulesExtractor:
    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or os.getenv("RAG_OCR_MODEL", "mlx-community/GLM-OCR-4bit")
        self.api_key = os.getenv("GEMINI_API_KEY")

    def extract_rules(self, text: str, document_id: str, file_key: str, chunk_id: str) -> List[Dict[str, Any]]:
        """
        Извлекает структурированные нормативные правила из текста чанка с помощью google/langextract.
        Сохраняет точные символьные offsets исходного текста для source grounding.
        """
        if not text or not text.strip():
            return []

        try:
            import langextract as lx
        except ImportError:
            logger.warning("[EXTRACTOR] Библиотека langextract не установлена. Извлечение правил пропущено.")
            return []

        prompt = (
            "Extract structured engineering compliance rules from the provided text. "
            "For each rule, locate the exact text matches in the source text. "
            "Verify that the extracted values are mathematically correct and correspond directly to the source text."
        )

        from langextract.data import ExampleData, Extraction
        example_extraction = Extraction(
            extraction_class="EngineeringRule",
            extraction_text="1,2 м",
            attributes={
                "subject": "эвакуационный выход",
                "parameter": "ширина",
                "operator": "не менее",
                "value": "1.2",
                "unit": "м",
                "condition": "при числе людей более 15"
            }
        )
        examples = [
            ExampleData(
                text="Ширина эвакуационных выходов из помещений должна быть не менее 1,2 м при числе людей более 15.",
                extractions=[example_extraction]
            )
        ]

        try:
            # Если задан GEMINI_API_KEY, используем его для максимального качества
            if self.api_key:
                result = lx.extract(
                    text,
                    prompt_description=prompt,
                    examples=examples,
                    model_id="gemini-1.5-flash",
                    api_key=self.api_key
                )
            else:
                # Иначе используем локальный провайдер по умолчанию (Ollama/MLX)
                result = lx.extract(
                    text,
                    prompt_description=prompt,
                    examples=examples,
                    model_id="mlx"
                )

            rules = []
            # В langextract результатом может быть AnnotatedDocument или список AnnotatedDocument
            # Мы извлекаем extractions из результата
            extractions = []
            if hasattr(result, "extractions") and result.extractions:
                extractions = result.extractions
            elif isinstance(result, list) and len(result) > 0 and hasattr(result[0], "extractions"):
                extractions = result[0].extractions

            for ext in extractions:
                start_char, end_char = 0, 0
                if ext.char_interval:
                    start_char = ext.char_interval.start_pos or 0
                    end_char = ext.char_interval.end_pos or 0

                attrs = ext.attributes or {}
                
                # Пробуем распарсить значение как число
                try:
                    val = float(attrs.get("value", 0.0))
                except (ValueError, TypeError):
                    val = 0.0

                rules.append({
                    "id": str(uuid.uuid4()),
                    "document_id": document_id,
                    "file_key": file_key,
                    "chunk_id": chunk_id,
                    "subject": attrs.get("subject", "N/A"),
                    "parameter": attrs.get("parameter", "N/A"),
                    "operator": attrs.get("operator", "N/A"),
                    "value": val,
                    "unit": attrs.get("unit", "N/A"),
                    "condition": attrs.get("condition", None),
                    "char_start": start_char,
                    "char_end": end_char
                })
            return rules

        except Exception as e:
            logger.error(f"[EXTRACTOR] Ошибка извлечения правил для чанка {chunk_id}: {e}", exc_info=True)
            return []
