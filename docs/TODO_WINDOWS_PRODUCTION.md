# TODO · Windows production / Legion

Последнее обновление: 2026-07-13. Целевой production — Legion/Windows. Этот файл — короткий
release-gate; детали эксплуатации находятся в `SKILL.md` и `docs/INSTALL_RUNBOOK.md`.

## Готово

- [x] Tauri/NSIS installer с runtime LES `0.24.0.400` собран как desktop SemVer `5.1.400`.
- [x] Installer `18 286 949` байт, SHA-256
  `6754d527e4345d4c19c57b85a551d5c831b067fb5ba31e7916fbe7df38575abd`.
- [x] Тихая установка в отдельный каталог завершилась с exit code `0`; внутри подтверждены
  `LES_VERSION=0.24.0.400`, Windows bootstrap, `SentenceTransformerReranker`,
  `QdrantLlamaIndexAdapter` и Windows-safe `process_status`.
- [x] Legion запускает Ollama `qwen3.5:9b`, embedding `bge-m3:latest`; Qdrant работает в Docker
  как `les-light-qdrant`.
- [x] Текущий тестовый индекс имеет совместимый contract-v2 и named `dense` + `bm25_sparse`.
- [x] Runtime `0.24.0.402` собран как Tauri `5.1.402`, установлен поверх предыдущего RC и
  сохранил persistent marker/junction при повторной NSIS-установке.
- [x] Финальный кодовый RC `0.24.0.403` / Tauri `5.1.403`: `18 295 881` байт, SHA-256
  `b7491f086a7a2508478530aca1c8406520ea93c5a05cfae242be3d4227c7c37a`; silent update `0`,
  `2894 passed`, `2894 collected`.
- [x] Mutable Windows state вынесен в `%LOCALAPPDATA%\LES`; изолированный smoke подтвердил
  идемпотентную legacy-миграцию, backup и доступ runtime-v2 к данным runtime-v1.
- [x] Qdrant на Legion перенесён из writable layer контейнера в named volume
  `les-qdrant-data`; до/после `6/6` points, старый контейнер и файловый backup сохранены.
- [x] Установленный runtime с persistent MetaDB видит compatible contract-v2,
  `dense_available=true`; live native probe дал dense `1`, sparse `1`, RRF `3`.
- [x] Обновление приложения сделано только ручным: отдельные кнопки проверки и установки,
  публичный выпуск содержит `latest.json`, `LES-Setup.exe` и `LES-Setup.exe.sha256`; контрольная
  сумма сверяется до запуска установщика. Фоновой проверки и автоустановки нет.
- [x] Выпускной staging исключает `.codex_tmp/**` и `tmp/**`; bootstrap убирает оставшиеся
  хвосты этих каталогов из заменяемого runtime после обновления старой установки.
- [x] `.405` опубликован: `11 931 827` байт, SHA-256
  `4853797e3ed00ce9d7b623bc2c21525494dee34301083cbf2ceb4357c04b2ee5`; тихое обновление
  завершилось с кодом `0`, версия, `.env` и постоянный marker сохранены.
- [x] Установленная `.405` читает прямой `latest.json` без GitHub API: текущая и последняя
  версии `0.24.0.405`, пакет полный, повторное обновление не предлагается.
- [x] Живой `retrieve-debug` на установленной `.405`: `qdrant_native_hybrid+rerank`, каналы
  `dense` + `qdrant_sparse`, `fusion=rrf`, BGE-реранжирование применено, `quality=good`, 5 результатов.
- [x] Полные гейты: `make verify` собрал `2902`, `make test` — `2902 passed`.
- [x] В `.406` bootstrap больше не открывает полурабочий интерфейс без локального RAG:
  `uv`, Ollama и Docker Desktop обязательны, отсутствующие компоненты ставятся через winget
  (у `uv` есть официальный резервный установщик), Qdrant обязан пройти проверку здоровья.
- [x] Bootstrap пишет `%LOCALAPPDATA%\LES\logs\bootstrap-status.json`; Tauri запускает PowerShell
  без консольного окна и показывает точную причину, код, официальный адрес установки и журнал.
- [x] Внешняя ЛСР получила единый пользовательский маршрут
  `/api/chat/attachments → attachment_id → /api/chat → artifact` и постоянную идемпотентность:
  повтор не создаёт новое вложение и не вызывает платную модель второй раз.
- [x] Цены ФГИС доступны пакетно через `/api/prices/lookup-batch` и
  `les_price_lookup_batch`, без десятков последовательных обращений на одну ЛСР.
- [x] Кодовый гейт `.406`: focused `36 passed`, RAG-core `168 passed`, полный `make test` —
  `2908 passed`, `make verify` — `2908 collected`; `public-check`, `uv lock --check`,
  `git diff --check` и `cargo check` зелёные.

## После выпуска

- [x] Разделить immutable application/runtime code и mutable state. Все пользовательские данные,
  `.env`, MetaDB, `storage`, `RAG_Content`, логи и job-state должны переживать обновление в
  `%LOCALAPPDATA%\LES`; Qdrant должен использовать постоянный Docker volume. Installer не должен
  создавать новую пустую MetaDB рядом с новой версией кода.
- [x] Добавить безопасную миграцию существующего Windows state с backup и идемпотентным повтором.
  Живой smoke 2026-07-13 доказал дефект: чистый `.400` runtime увидел `0` SQLite chunks и `6`
  points существующей Qdrant collection, поэтому contract стал missing и dense был выключен.
- [x] Получить на Legion целый `BAAI/bge-reranker-v2-m3` и проверить SHA-256
  `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`. Onboarding записал
  verification marker и прошёл model-load probe: `0,951604` для релевантной пары против `0,000016`.
- [x] Сделать загрузку reranker в bootstrap проверяемой: временный файл, resume, checksum/model-load
  probe, атомарная публикация только после успеха. Ошибка не должна оставлять файл под боевым именем.
- [x] Зафиксировать точный SHA-256 BGE marker и выполнить отдельный семантический probe:
  релевантный фрагмент `0,999349`, шумовые `0,000016`; холодный запуск `12,728 с`, прогретый `0,114 с`.
- [ ] Выполнить отдельную проверку parent/context expansion и один сквозной запрос в диалоге после
  завершения фоновой загрузки ФГИС, не смешивая приёмку модели и долгую индексацию источников.
- [x] Полный updater ФГИС ЦС доказал рабочий pipeline: каталог и 148/148 price books пройдены,
  job перешёл к ГЭСН. По решению оператора продолжение фоновой загрузки не блокирует выпуск.
- [ ] Добавить Authenticode-подпись Windows installer, чтобы убрать предупреждение SmartScreen;
  это эксплуатационное улучшение после первого ручного выпуска, не фоновое автообновление.
- [x] Пересобрать `.405`, повторить тихую установку/обновление, `make verify`, полный `make test`,
  живую проверку RAG и опубликовать выпуск.
- [ ] Собрать `.406` на Legion, проверить чистый первый запуск отдельно без заранее установленных
  `uv`, Ollama и Docker Desktop, затем повторить обновление поверх `.405` с сохранением state.
- [ ] Выполнить внешний сквозной smoke обычным пользовательским ключом:
  вложение → идемпотентный чат `mode=smeta` → XLSX → повтор того же ключа без второго model call.

## Вердикт

Код `.406` закрывает падение первого запуска и внешний контракт ЛСР. Выпуск считается готовым
только после сборки на Legion и двух живых проверок выше. Открыты также Authenticode и отдельная
проверка parent/context после завершения тяжёлой фоновой задачи ФГИС.
