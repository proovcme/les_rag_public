# Версионирование ЛЕС

Канонический машинный источник — [`config/version.json`](../config/version.json).

## Три разных назначения

| Поле | Пример | Для чего |
|---|---:|---|
| `product_version` | `0.31.5` | Единственная версия, которую видит пользователь; обычный SemVer `X.Y.Z` |
| `build_number` | `711` | Монотонный номер Windows-сборки; не является четвёртой частью версии |
| `desktop_version` | `5.1.711` | Внутренняя версия Tauri/NSIS для обновления ранее выпущенных `5.1.x` пакетов |
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
