# Аудит ARTEL и план стабилизации

Дата среза: 2026-07-23
Базовая ветка: `audit/normcontrol-stabilization`, commit `4753097`
Источник продукта: [proovcme/Agnostis](https://github.com/proovcme/Agnostis)
Pinned commit: `0ecccf54362870a75ecaf96f99fb6129dfe3a0fa`

## Вердикт

В исходном `public/main` ARTEL был неполным: LES содержал Python tools, schemas
и tests, но не содержал `products/artel` и не мог собрать Revit product. Это
создавало ложное впечатление доступного модуля при отсутствующем source tree.

В этой ветке граница исправлена:

- ARTEL остаётся отдельным публичным продуктом Agnostis;
- LES содержит pinned submodule `products/artel`;
- clean clone с `--recurse-submodules` получает source, backend, Revit add-in,
  installer, OpenAPI, skills и knowledge contract;
- LES-owned duplicate release builder удалён;
- URL submodule — публичный HTTPS;
- весь текущий ARTEL offline-профиль даёт `95 passed`.

Однако pinned commit находится в открытом draft PR Agnostis #2, а живой
Legion/Revit install не принят. Поэтому статус — **полный reviewable source и
зелёный offline contract, но не stable Windows/Revit release**.

## Что доступно команде

- Revit add-in и Family Factory для Revit 2024/2025.
- Backend `Agnostis.Api`.
- OpenAPI и model/tool contracts.
- Skills Revit API operator и family generator.
- Confirmation-gated operator plan и safety controls.
- Installer scripts и LES/ARTEL Index integration.
- Conformance fixtures, packaging и SDK XML tests.
- Зафиксированный source commit вместо плавающей ветки.

## Что было сломано в public/main

1. `.gitmodules` знал только `les-list`; `products/artel` отсутствовал.
2. ARTEL packaging tests ссылались на несуществующее дерево.
3. LES владел устаревшим `build_artel_release.py`, хотя продукт и релиз должны
   жить отдельно.
4. Не было единой версии source между LES integration и Agnostis.
5. Команда не могла воспроизвести Revit build из public clone.

## Что ещё не stable

1. Agnostis PR #2 остаётся draft; pinned commit ещё не является утверждённым
   default branch release.
2. Нет подтверждённого CI на Windows с Revit SDK 2024/2025.
3. На Legion ранее были Revit 2025 и add-in manifest, но отсутствовал временный
   runtime package, поэтому diagnose/autorun не запускался.
4. Нет завершённого end-to-end smoke:
   `установка → запуск backend → Revit pane → draft → confirmation → transaction
   → validation report → LES RAG`.
5. Нет подписанного installer artifact, checksum manifest и проверенного
   upgrade/rollback.
6. Knowledge bundle велик; его лицензии, происхождение и release budget должны
   проверяться в Agnostis, а не скрываться в LES.
7. Связь с локальной/облачной моделью нуждается в том же provider setup и
   session-scoped BYOK contract, что LES.

## Определение stable

ARTEL стабилен, когда:

- Agnostis default branch содержит утверждённый pinned source;
- Windows CI собирает add-in/backend/installer для Revit 2024 и 2025;
- installer ставит, обновляет и удаляет продукт без ручного temp-runtime;
- Revit actions требуют preview/confirmation, проверяют fingerprint и имеют
  transaction rollback;
- read-only вопросы не мутируют модель;
- validation report возвращается в ARTEL Index/LES с provenance;
- локальный и облачный provider проходят одинаковый tool contract;
- signed/checksummed artifact проходит чистую установку и upgrade на Legion;
- LES integration использует только submodule/API, не дублирует product source.

## План до стабильного

### P0 — утвердить product boundary и публичную сборку

1. Провести review и merge Agnostis PR #2 либо выпустить заменяющий commit.
2. Обновить gitlink LES на утверждённый commit.
3. Добавить Windows CI: .NET restore/build/tests, packaging checks и installer
   dry-run.
4. Зафиксировать license/provenance manifest для knowledge bundle.

Критерий выхода: `git clone --recurse-submodules` и один документированный
build command воспроизводят артефакты без private repo.

### P1 — Legion/Revit acceptance

1. Собрать versioned installer, а не временный `%TEMP%` runtime.
2. Установить на Legion для Revit 2024/2025.
3. Прогнать backend health, pane load, live query, confirmation-gated action,
   rollback и validation report.
4. Проверить upgrade и uninstall с сохранением пользовательских данных.

Критерий выхода: повторный smoke проходит после reboot и без ручного копирования
файлов.

### P2 — интеграция и профессиональная приёмка

1. Проверить family generation на утверждённом наборе RFA cases.
2. Измерить schema validity, parameter/FOP compliance, geometry checks,
   unsupported-action rate и human rejection reasons.
3. Закрыть session-scoped provider setup и отсутствие утечки ключей.
4. Добавить совместимый ARTEL Index export и LES retrieval smoke.

Критерий выхода: утверждённый набор семейств проходит автоматические и ручные
гейты, а provenance возвращается в LES.

## Риски и границы

- Эта ветка не сливает ARTEL source внутрь LES; source принадлежит Agnostis.
- Gitlink указывает на draft commit и требует вашего решения по PR.
- `95 passed` — offline evidence, не подтверждение установленного Revit add-in.
- Runtime, installer publication и Legion не изменялись.
