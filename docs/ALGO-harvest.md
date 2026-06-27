# Алгоритм: harvest-петля — verify-правки → train-set + таксономия ошибок

Превращает ручную верификацию распознанных таблиц в **размеченный датасет** и **отчёт по классам
ошибок** распознавания. 0 LLM. Цель — данные и сигнал для решения «нужна ли VL-LoRA».

## Идея

`verify_service`: оператор правит таблицу, извлечённую vision/OCR со скана → результат сохраняется
как ground truth (картинка страницы + target-строки). С захватом исходного предсказания модели
(`pred_rows`) каждая правка = **размеченный дифф «модель дала → оператор исправил»**.
Долговечный актив — **датасет** (картинка→target), не адаптер: переучить LoRA на новой базе дёшево.

## Шаги

1. **Захват предсказания**: `save_verification(..., pred_rows=...)` хранит исходное извлечение рядом
   с исправленным (роутер `/api/verify/save` + фронт `verify.py` шлют снимок до правок).
2. **Train-set** (`build_training_set`): записи `verdict ∈ {ok, corrected}` с картинкой →
   `data/train/dataset.jsonl` (`image, target_rows, pred_rows, columns`) + `manifest.json` (счётчики).
   Базонезависимый — для бенча и LoRA на любой базовой VL.
3. **Таксономия** (`error_taxonomy`): для `corrected` с `pred_rows` — дифф структуры (missing/extra
   row/column) и ячеек. Класс ячейки (`classify_cell`):
   - `char_confusion` — путаница цифр/латиницы-кириллицы (5↔S, О↔0) — **главный кандидат на LoRA**;
   - `numeric_value` · `whitespace_case` · `empty_pred` · `text_value`.
4. **Сигнал** `lora_signal`: доминантный класс ≥40% на ≥20 проанализированных → кандидат под LoRA.

## Где в коде

- Сервис: `proxy/services/harvest_service.py`; источник — `verify_service.VERIFY_DIR/CACHE_DIR`.
- CLI: `tools/harvest_dataset.py` (build + taxonomy, сводка/JSON).
- Стыкуется с `tools/extract_bench.py` (field-accuracy — «первый шаг к вопросу нужна ли LoRA»).
- Тест: `tests/test_harvest_service.py`.

## Решение про VL-LoRA (зафиксировано)

LoRA — для **перцепции** (распознавание), не для фактов (факты → онтология/RAG, см. [[ALGO-smeta-ontology]]).
Гейт перед обучением: промпт уперся + ошибки systematic (бенч) + N примеров + VL тренируется в MLX.
Не делать спекулятивно — копить разметку (бесплатный побочный продукт verify) и мерять.

## Границы

- Старые verify-записи без `pred_rows` идут в train-set, но не в таксономию (нечего диффать).
- Сопоставление строк pred↔target — по индексу (best-effort); выравнивание по ключу — задел.
