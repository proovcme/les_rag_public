# Workbook contract consistency

**Goal:** Согласовать опубликованные модели поля с уже поддерживаемыми обоснованиями ВОР и расчётами ЛСР.

**Architecture:** Существующий model-authored результат и terminal carrier сохраняются. Код не выбирает нормы, работы, ресурсы, родителей или коэффициенты; новые циклы не добавляются.

**Spec:** AGENTS.md; измерения `artifacts/live_982/{vor_docx01,lsr_ordinary01,hybrid_vor_csv01}`.

**Constraints:** Без зависимостей, предметного forcing и изменения обязательности optional-полей. Доставленная 982 и её решения сохраняются. Подбор модели не объявляется исправленным тестами схемы.

- [x] RED: тесты действительного native decode и объявленных calc/resource полей; краткие перечни ВОР включают coverage, covered_by_work_id, evidence_refs.
- [x] GREEN: единый перечень полей ВОР в трёх активных инструкциях; описание существующих optional полей native terminal schema.
- [x] По живому hint982 подтверждён дополнительный барьер: authored expected2 при показанной durable1. Версионировать normal model transport, не ослаблять прежний admission/storeCAS.
- [x] Pure snapshot/binding: immutable до ответа; exact ID/source; raw CAS audit;51owner tests включая legacy aliases.
- [x] Active wiring: snapshot в том же контексте/held/pending, resume без latest, durable audit; race/legacy/B0 parity tests (219related GREEN).
- [ ] Проверить профильные тесты, version/map/architecture/verify и канонический test; обновить модуль, карту и ledger.
- [ ] Exact local installer baseline → candidate → rollback; затем обычный ВОР/ЛСР и прямой B0 на тех же модели/источнике/задании.
- [ ] Инженерное уточнение сохраняет книгу/принятые решения; оценка содержимого физического файла отдельно от технической упаковки.

**Review focus:** Составные работы одной строки; неоднозначный родитель; неизвестный и нулевой объём; вложенные literal ресурсные решения; повторное продолжение без смены ценовой базы. При провале live качество не объявлять подтверждённым.
