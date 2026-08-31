# Выпуск ЛЕС

Это единственная актуальная публичная процедура. Старые `patch-release`,
`github-patch-release` и `release-multiplatform` остаются внутренними адаптерами;
оператор не запускает через них публикацию.

## Полный проход

Из чистой ветки, отправленной в `origin`, принять кандидата на текущем Legion и
опубликовать тот же immutable attempt одной командой:

```text
make release RELEASE_ARGS='run --host local --publish'
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
3. На текущем Legion (`--host local`) ставит точные candidate bytes штатным
   путём, проверяет identity,
   живые proxy/UI отдельно от внешних capabilities и, если Qdrant был доступен, временный native
   `dense + qdrant_sparse → RRF` dataset.
4. Выполняет controlled rollback, проверяет восстановленную версию и повторно
   ставит те же candidate bytes.
5. Только после stage `accepted` проверяет, что публичный `main` является
   предком принятого commit, и выполняет обычный non-force fast-forward до
   exact target. Divergence останавливает выпуск до создания draft; force push
   запрещён. До проверки ancestry публичный репозиторий не изменяется.
6. Создаёт GitHub draft с явным target commit, добавляет
   `release-receipt.json`, скачивает все assets обратно и сверяет SHA.
7. Публикует draft и независимо сверяет public main, tag, feed, receipt и assets.

Построитель cumulative patch читает Git history пакетно и печатает
ограниченный прогресс по ancestry и manifest-файлам. Результат автоматического
public-main sync (`before`, `after`, `fast_forwarded`) записывается в persisted
attempt. Если последующий шаг упал, повторный `publish` продолжает тот же
attempt; уже выполненный exact sync становится безопасным no-op.

Ручной fast-forward нужен только как диагностическое восстановление после
осознанного устранения divergence. Обычная процедура не требует отдельного
`git push public` между приёмкой и публикацией.

## Раздельное выполнение и продолжение

```text
make release RELEASE_ARGS='prepare --host local'
make release RELEASE_ARGS='accept --host local'
make release RELEASE_ARGS='status --attempt dist/release-work/<id>/release-state.json'
make release RELEASE_ARGS='publish'
```

Последний attempt записан в `dist/release-work/latest.json`. Кандидат после
prepare не пересобирается. Сохранённый draft продолжается с последней
подтверждённой стадии; опубликованный выпуск повторно не публикуется, а только
повторяет postflight.

`local` — явный псевдоним машины, на которой запущен оркестратор. Имя или SSH
alias (например, `legion`) указывается только при действительно удалённой
приёмке; оно никогда не подменяется неявно.

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
