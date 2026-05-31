#!/usr/bin/env python3
"""
Скрипт проверки работоспособности MLX-Native GLM-OCR парсера.
Позволяет протестировать рендеринг PDF, ленивую загрузку VLM, OCR и очистку памяти Metal.
"""
import os
import sys
import time
import logging
from pathlib import Path

# Добавляем корневую директорию проекта в пути импорта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_mlx_ocr")

def get_current_ram_mb() -> float:
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except ImportError:
        return 0.0

def main():
    logger.info("=== Старт теста MLX-Native GLM-OCR ===")
    
    # 1. Проверяем наличие входного файла
    if len(sys.argv) < 2:
        logger.error("Использование: python scratch/test_mlx_ocr.py <путь_к_тестовому_pdf>")
        return 1
        
    pdf_path = Path(sys.argv[1]).resolve()
    if not pdf_path.exists():
        logger.error(f"Файл не найден: {pdf_path}")
        return 1

    # Импортируем наш парсер
    try:
        from backend.ocr_parser import MLXVisualOCRParser
    except ImportError as e:
        logger.error(f"Не удалось импортировать MLXVisualOCRParser: {e}")
        return 1

    model_id = os.getenv("RAG_OCR_MODEL", "mlx-community/GLM-OCR-4bit")
    logger.info(f"Используем модель: {model_id}")
    
    ram_init = get_current_ram_mb()
    logger.info(f"RAM перед инициализацией: {ram_init:.1f} MB")

    # 2. Инициализируем парсер
    parser = MLXVisualOCRParser(model_id=model_id)

    # 3. Тестируем конвертацию PDF в картинки
    t0 = time.time()
    try:
        images = parser.pdf_to_images(pdf_path, dpi=150)
        logger.info(f"Успешно срендерено страниц: {len(images)} (время: {time.time() - t0:.2f} сек)")
    except Exception as e:
        logger.error(f"Ошибка рендеринга PDF: {e}", exc_info=True)
        return 1

    if not images:
        logger.error("Нет страниц для распознавания.")
        return 1

    # 4. Тестируем OCR первой страницы
    logger.info("Загружаем модель и распознаем первую страницу...")
    ram_before_load = get_current_ram_mb()
    
    t_ocr_start = time.time()
    try:
        first_page_text = parser.ocr_page(images[0])
        t_ocr = time.time() - t_ocr_start
        
        ram_loaded = get_current_ram_mb()
        logger.info(f"RAM с загруженной моделью: {ram_loaded:.1f} MB (прирост: {ram_loaded - ram_before_load:.1f} MB)")
        logger.info(f"Распознавание страницы 1 завершено за {t_ocr:.2f} сек!")
        
        print("\n--- [РЕЗУЛЬТАТ РАСПОЗНАВАНИЯ СТРАНИЦЫ 1] ---")
        print(first_page_text)
        print("--------------------------------------------\n")
        
    except Exception as e:
        logger.error(f"Ошибка OCR: {e}", exc_info=True)
        parser.unload_model()
        return 1

    # 5. Тестируем выгрузку модели и очистку Metal
    logger.info("Тестируем выгрузку модели из оперативной памяти...")
    parser.unload_model()
    
    # Небольшая пауза для завершения сборки мусора
    time.sleep(1)
    
    ram_after_unload = get_current_ram_mb()
    logger.info(f"RAM после выгрузки: {ram_after_unload:.1f} MB (высвобождено: {ram_loaded - ram_after_unload:.1f} MB)")
    
    logger.info("=== Тест успешно завершен ===")
    return 0

if __name__ == "__main__":
    sys.exit(main())
