# Версионирование ЛЕС

Канонический машинный источник — [`config/version.json`](../config/version.json).

Текущий контракт — candidate 0.31.144/build 872; установлен 0.31.143/build 871
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
| `product_version` | `0.31.146` | Единственная версия, которую видит пользователь; обычный SemVer `X.Y.Z` |
| `build_number` | `874` | Монотонный номер Windows-сборки; не является четвёртой частью версии |
| `desktop_version` | `5.1.874` | Внутренняя версия Tauri/NSIS для обновления ранее выпущенных `5.1.x` пакетов |
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
