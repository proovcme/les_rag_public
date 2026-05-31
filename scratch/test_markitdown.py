#!/usr/bin/env python3
"""
Синтетический тест для проверки универсального конвертера Microsoft MarkItDown.
Конвертирует тестовый DOCX-документ из базы знаний LES.
"""
import os
import sys
import logging
from pathlib import Path

# Добавляем корневую директорию проекта в пути импорта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_markitdown")

def main():
    logger.info("=== Старт теста Microsoft MarkItDown ===")
    
    # Ищем тестовый docx-файл в RAG_Content
    rag_content_dir = PROJECT_ROOT / "RAG_Content" / "NTD"
    test_file = rag_content_dir / "test_document.docx"
    
    if not test_file.exists() or test_file.stat().st_size == 0:
        # Если конкретный файл не найден или пустой, берем первый непустой .docx в папке
        docx_files = [f for f in rag_content_dir.glob("*.docx") if f.stat().st_size > 0]
        if docx_files:
            test_file = docx_files[0]
        else:
            logger.error("В папке RAG_Content/NTD не найдено ни одного непустого .docx файла!")
            return 1
            
    logger.info(f"Тестируем конвертацию файла: {test_file.name} ({test_file.stat().st_size // 1024} KB)")

    try:
        from markitdown import MarkItDown
    except ImportError:
        logger.error("Библиотека 'markitdown' не установлена! Запустите 'uv sync' или 'pip install markitdown'.")
        return 1

    try:
        import time
        start = time.time()
        
        md = MarkItDown()
        result = md.convert(str(test_file))
        
        logger.info(f"Конвертация завершена за {time.time() - start:.2f} сек!")
        print("\n--- [РЕЗУЛЬТАТ КОНВЕРТАЦИИ MARKITDOWN] ---")
        print(result.text_content[:2000])  # Выводим первые 2000 символов
        if len(result.text_content) > 2000:
            print("...\n*[обрезано]*")
        print("------------------------------------------\n")
        
    except Exception as e:
        logger.error(f"Ошибка во время конвертации: {e}", exc_info=True)
        return 1

    logger.info("=== Тест MarkItDown успешно завершен ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
