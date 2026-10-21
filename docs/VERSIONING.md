# Версионирование ЛЕС

Текущее состояние выпуска — в [RELEASE_LEDGER](RELEASE_LEDGER.md) и `/api/version`.
`tools/sync_version_contract.py` синхронизирует все machine surfaces, включая
единственную local editable `les-v2` version в uv.lock. Dependency records не
разрешаются и не изменяются. Это исключает последующую автоправку tracked lock
при каноническом uv-run gate. `test_software_versions.py` проверяет сохранение
всех остальных записей, а `--check` выявляет рассинхронизацию до выпуска.

Текущий source-кандидат —0.31.246/build974/desktop5.1.974; фактически установлен
971/0.31.243. Основная suite973 прошла6726passed/20skipped, но updater gate
остановлен WinError5; полный974 gate и exact installer/live ещё pending.
Номера кандидата не являются доказательством установки или customer-ready.

## Исторические замеры кандидатов

Кандидат0.31.199/build927: read-only ЭТМ и две регрессии коммерческих цен.
Frozen927:4411 passed,20 historical skipped,mail66,metadata31;
структурные гейты exit0. Установка pending; фактически установлен926/8748b76f,
native EXE5.1.813. Приёмка iPRO и профессиональная готовность разных ВОР/ЛСР
не подтверждены. customer-ready=false. [RELEASE_LEDGER](RELEASE_LEDGER.md).

Установлен runtime0.31.198/build926, code commit8748b76f; native EXE5.1.813.
926 исправляет running checkpoint при ModelTransportError. GREEN10;
full926:4367 passed,20 historical skipped, mail66,metadata31. Живые контроли
полного БАП и первого frame4 завершены и отрицательны; customer-ready=false.
Точная область и результаты — [RELEASE_LEDGER](RELEASE_LEDGER.md).

Текущий кандидат —0.31.197/build925; фактически установлен924/41ea6db3,
native shell5.1.813.925 исправляет допуск непоказанного discovery inventory;
full925r2:4363 passed,20 исторических skipped, mail66, metadata31,
structural/docs/map gates exit0; установленная приёмка pending. customer-ready=false.

Канонический машинный источник — [`config/version.json`](../config/version.json).

Исторический контракт — candidate0.31.170/build898; установлен897 f3c348e4.
Фактическая установка подтверждается `/api/version`; native shell5.1.813.
898 читает явно подписанные записи с разными разделителями без дополнительных inference. Готовность
заказчику не подтверждена; exact installer и профессиональная приёмка pending.

Историческая запись872 — candidate 0.31.144/build 872; установлен 0.31.143/build 871
(`e8657ba38eed88dac8de327b5e4dd9b2999869f4`), API/GUI и 19 runtime hashes сверены.
872 включает двухстрочный encoding fixture Windows prepare, literal navigation
показанных полных шифров при missing exact read и lossless replay pointer aliases.
Модель и runtime-профиль не меняются. Private prepare 871: 2924 passed /
1 encoding fixture failure / 20 skipped / 6 warnings (219.48s). Точный CP866/UTF-8
репро сохранён; исправленный suite — 17 passed (4.18s). Exact private prepare 872 pending.
Metadata872: canonical verify exit0 (23.48s), 2945 collected; version/docs/release
fixtures31 passed (4.99s), documentation contract0. Полный canonical872 pending.
Native RRF 871 exit0; original 90s smoke: 7 pass / 1 warn / 2 timeout fail.
Отдельный finite 180s smoke: 10 pass / 0 warn / 0 fail, exit0 (112.66s);
исходный failed run сохранён. Native EXE858 retained. Professional871 **FAILED**:
same-identity B0/B1 без XLSX, required46993/47433 при budget46246; готовность не заявлена.
Точные результаты и состояние установки — [`RELEASE_LEDGER.md`](RELEASE_LEDGER.md).

## Три разных назначения

| Поле | Пример | Для чего |
|---|---:|---|
| `product_version` | `0.31.250` | Единственная версия, которую видит пользователь; обычный SemVer `X.Y.Z` |
| `build_number` | `978` | Монотонный номер Windows-сборки; не является четвёртой частью версии |
| `desktop_version` | `5.1.978` | Внутренняя версия Tauri/NSIS для обновления ранее выпущенных `5.1.x` пакетов |
| `harness_schema_version` | `0.24` | Версия внутреннего строительного контракта, а не продукта |

`proxy/services/version_service.py` читает этот файл и сохраняет старые поля API только для
совместимости клиентов. Новый код использует `product_version` и `build_number`.

## Когда менять номер

- `PATCH`: исправление, документация, установщик, регрессия без нового несовместимого контракта;
- `MINOR`: новая совместимая возможность продукта;
- `MAJOR`: несовместимое изменение публичного API или формата пользовательских данных;
- `build_number`: увеличивается при каждой опубликованной Windows-сборке независимо от типа версии.

Следующая версия и номер сборки задаются один раз в `config/version.json`. Точные версии Qdrant,
Ollama, моделей, Python, uv и Tauri ведутся в [`SOFTWARE_VERSIONS.md`](SOFTWARE_VERSIONS.md).

## Выпуск

Из чистой отправленной ветки:

```text
make release RELEASE_ARGS='run --host legion --publish'
```

Команда не публикует результат, пока exact candidate не установлен на Legion,
не прошёл smoke, controlled rollback и повторную установку. Фактический commit,
SHA и стадии сохраняются в receipt. Полный канон —
[`RELEASE_PROCEDURE.md`](RELEASE_PROCEDURE.md); состояние версии —
[`RELEASE_LEDGER.md`](RELEASE_LEDGER.md).
