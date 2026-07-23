# Priority corpus inventory

Статус: generated read-only snapshot. Не evidence; не запускает parse/OCR/reindex и не меняет источники.
Сгенерирован: `2026-07-10T07:43:02+00:00`.
Runtime: `degraded` · collection `les_rag_qwen3_06b_native_v1` · points/sqlite `True`.

## ПД ИЦ

- Dataset: `ПД_Инновационный центр` · `1728e431-56d1-410f-8bf9-fdbf2543dce0`.
- Назначение: главный проектный корпус. Owner: **UNSET**.
- Runtime: `ERROR`; notebook `good`; reader `bootstrap`; revision `rev-87f00a878f528fa0`.
- Документы: 674; declared chunks: 17144; statuses: SKIPPED: 328, INDEXED: 297, PENDING: 49.
- Типы: CAD_BIM: 328, DOCUMENT: 173, SMETA: 130, NORMATIVE: 31, SPEC: 9, TABLE: 3.
- Решение: **triage_pending**. Автоматический quarantine: нет.

### Pending

- `ПД_Инновационный центр/ПД_Инновационный центр/1. ПЗ/1_RAW/Раздел ПД №1_ПЗ_ТЧ-ИД.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/1. ПЗ/1_RAW/Раздел ПД №1_ПЗ_ТЧ-ИРД.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/1. ПЗ/2_PDF/395.01-B481.120000.2.4-ПЗ_часть1.pdf` · SMETA · TABLE_SMETA · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/1. ПЗ/2_PDF/395.01-B481.120000.2.4-ПЗ_часть2.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/10(1) МЭЭ/2_PDF/395.01-В481.120000.2.4-ЭЭ.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/10. ОДИ/2_PDF/395.01-В481.120000.2.4-ОДИ.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/11(1) ТБЭ/2_PDF/395.01-В481.120000.2.4-ТБЭ.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/12. Прочее/2_PDF/12.1. ГОЧС/395.01-В481.120000.2.4-ГОЧС.pdf` · DOCUMENT · DOCS_OTHER · chunks 0

### Indexed без declared chunks

- `ПД_Инновационный центр/ПД_Инновационный центр/12. Прочее/2_PDF/12.2. Проект СЗЗ/Приложение Д/Приложение Д_tmp.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/3. АР/1_RAW/Пояснительная записка/ПРИЛОЖЕНИЕ А.docx` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/3. АР/1_RAW/Пояснительная записка/ПРИЛОЖЕНИЕ А.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/3. АР/1_RAW/Пояснительная записка/ПРИЛОЖЕНИЕ Б.docx` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/3. АР/1_RAW/Пояснительная записка/ПРИЛОЖЕНИЕ Б.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/4. КР/1_RAW/395.01B481.120100.1.4-КР/_03_ГИП.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/4. КР/1_RAW/395.01B481.120100.2.4-КР/_03_ГИП.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- `ПД_Инновационный центр/ПД_Инновационный центр/5. ИОС/1_RAW/5.5. ИОС Сети связи/5.5.3. СС3/0 Раздел 5.5.3 Р.pdf` · DOCUMENT · DOCS_OTHER · chunks 0
- Pending по типу: DOCUMENT: 37, SMETA: 11, NORMATIVE: 1.
- Pending по расширению: .pdf: 49.
- Повторяющиеся имена pending: _01_СРО.pdf: 2.
- **Drift:** runtime dataset status `ERROR`, но Document Explorer не видит строк `ERROR`; требуется сверка статуса, не parse.

## BAI

- Dataset: `BAI` · `449190eb-050e-422f-91a6-54852469201a`.
- Назначение: компактный project regression. Owner: **UNSET**.
- Runtime: `IDLE`; notebook `good`; reader `bootstrap`; revision `rev-2c38f3e10375b135`.
- Документы: 80; declared chunks: 5955; statuses: INDEXED: 75, SKIPPED: 5.
- Типы: SMETA: 32, NORMATIVE: 21, DOCUMENT: 20, CAD_BIM: 5, TABLE: 2.
- Решение: **baseline_candidate**. Автоматический quarantine: нет.
- Служебные записи исключены из zero-chunk defect: 1.

## Fire

- Dataset: `NTD_FIRE_Index` · `5a17e366-4c9a-489e-bfda-518f8fe1223f`.
- Назначение: нормативный retrieval golden. Owner: **UNSET**.
- Runtime: `COMPLETED`; notebook `good`; reader `bootstrap`; revision `rev-62a487a122237ae0`.
- Документы: 125; declared chunks: 17808; statuses: INDEXED: 125.
- Типы: NORMATIVE: 125.
- Решение: **baseline_candidate**. Автоматический quarantine: нет.

## Сметы: проектные таблицы

- Production dataset отсутствует. Бывший `TABLE_SMETA_Index`
  (`a1cc873f-2173-4fc9-bdc5-12e6707ef99b`) содержал только test ВОР/CSV и generated
  norm/price/service cards и удалён 2026-07-10 из MetaDB/Qdrant/FTS/storage.
- Решение: будущие реальные ВОР/ЛСР — user/project dataset; module cards — typed
  `SMETA_SERVICE_Index` (`dataset_scope=system`, `module_id=smeta`).

## Сметы: нормативная опора

- Dataset: `SMETA_RU_NORM_FSNB2022_Index` · `9bc6cd77-37f8-4be2-a95a-64d20891ca49`.
- Назначение: нормы и расценки; отдельный source layer. Owner: **UNSET**.
- Runtime: `IDLE`; notebook `good`; reader `bootstrap`; revision `rev-33fe97648d0725da`.
- Документы: 193; declared chunks: 1296; statuses: INDEXED: 191, PENDING: 2.
- Типы: DOCUMENT: 188, SMETA: 5.
- Решение: **triage_pending**. Автоматический quarantine: нет.

### Pending

- `fsnb2022/FSNB-2022_i18_24.06.2026/source_files/æ»αáó«τ¡¿¬ èæÉ éÑαß¿∩ ⁿ43 «Γ 20.05.2026 ⁿ315 »α.xlsx` · SMETA · TABLE_SMETA · chunks 0
- `TABLE_SMETA/SMETA_RU_NORM/fsnb2022/FSNB-2022_i18_24.06.2026/source_files/æ»αáó«τ¡¿¬ èæÉ éÑαß¿∩ ⁿ43 «Γ 20.05.2026 ⁿ315 »α.xlsx` · SMETA · SMETA_RU_NORM_FSNB2022 · chunks 0
- Pending по типу: SMETA: 2.
- Pending по расширению: .xlsx: 2.
- Повторяющиеся имена pending: æ»αáó«τ¡¿¬ èæÉ éÑαß¿∩ ⁿ43 «Γ 20.05.2026 ⁿ315 »α.xlsx: 2.

## Следующий ход

Назначить owner и операторское решение для каждого pending/error/zero-chunk файла. Только затем выбирать первый dataset для index-quality; этот отчёт сам не является основанием для ответа модели или массового изменения корпуса.
