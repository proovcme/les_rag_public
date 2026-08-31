# Выпуск ЛЕС

Это единственная актуальная публичная процедура. Старые `patch-release`,
`github-patch-release` и `release-multiplatform` остаются внутренними адаптерами;
оператор не запускает через них публикацию.

## Полный проход

Из чистой ветки, отправленной в `origin`:

```text
make release RELEASE_ARGS='run --host legion --publish'
```

Команда последовательно и с сохранением state выполняет:

1. Сверяет `HEAD`, upstream, версию и generated maps; запускает `make verify`,
   `make test`, `make test-updater` и `make public-check`.
   Базу накопительного patch берёт только из проверенного
   `dist/release-work/full-base/latest.json`; исторический `dist/latest.json`
   не участвует в классификации. `--full-feed` нужен только для явной замены
   этого attested full-base.
2. Автоматически выбирает soft patch или полный NSIS-выпуск и фиксирует SHA
   устанавливаемого ZIP/EXE в immutable attempt.
3. На Legion ставит точные candidate bytes штатным путём, проверяет identity,
   живые proxy/UI отдельно от внешних capabilities и, если Qdrant был доступен, временный native
   `dense + qdrant_sparse → RRF` dataset.
4. Выполняет controlled rollback, проверяет восстановленную версию и повторно
   ставит те же candidate bytes.
5. Только после stage `accepted` создаёт GitHub draft с явным target commit,
   добавляет `release-receipt.json`, скачивает все assets обратно и сверяет SHA.
6. Публикует draft и независимо сверяет public main, tag, feed, receipt и assets.

Без `--publish` команда останавливается на принятом кандидате. Это каноническая
непубличная репетиция:

```text
make release RELEASE_ARGS='run --host legion'
```

## Раздельное выполнение и продолжение

```text
make release RELEASE_ARGS='prepare --host legion'
make release RELEASE_ARGS='accept --host legion'
make release RELEASE_ARGS='status --attempt dist/release-work/<id>/release-state.json'
make release RELEASE_ARGS='publish'
```

Последний attempt записан в `dist/release-work/latest.json`. Кандидат после
prepare не пересобирается. Сохранённый draft продолжается с последней
подтверждённой стадии; опубликованный выпуск повторно не публикуется, а только
повторяет postflight.

## Стоп-условия

- Любое расхождение commit или одного байта прекращает выпуск.
- Исчезновение ранее доступной capability прекращает приёмку.
- Недоступный до обновления внешний Qdrant получает честный `N/A`; ЛЕС его не
  устанавливает и не запускает.
- `%LOCALAPPDATA%\LES` не входит в application transaction.
- `--skip-gates` создаёт навсегда непубликуемый dev-attempt.
- Ошибка после публикации — критический immutable-release incident; stage
  `postflight_verified` не выставляется.

Receipt и текущую стадию смотреть командой `status`. Публичная публикация до
успешных install, smoke, rollback и reinstall на Legion технически запрещена.
