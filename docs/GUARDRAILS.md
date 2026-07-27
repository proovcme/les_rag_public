# GUARDRAILS — что НЕ ломаем + как катим в прод

> Дисциплина выпуска (модель locia). **Стабильность важнее фич.** Прод — живой; деплой только после
> тестов, с механикой отката. Состояние/версия — [RELEASE_LEDGER.md](RELEASE_LEDGER.md).

## 1. Прод-гейт: в рантайм только после тестов

Последовательность выката:

```
1. bump версии 0.23.N.P + строка в RELEASE_LEDGER + releases.md
2. make ship          # verify → focused tests → smoke → deploy-runtime → retry post-deploy-smoke
```

Для проверки без деплоя или полного релизного gate:

```
make ship-check       # verify → test-focused → smoke-basic
make ship-full-check  # verify → test → smoke-basic
make ship-full        # полный gate + deploy + retry post-deploy-smoke
```

**Деплой запрещён, если выбранный gate красный** (или без явного решения оператора по known-fail).

## 2. Откат

```
код:     git checkout <prev_commit> -- <files>  →  tools.deploy_to_runtime --apply --restart
данные:  tools/restore_runtime.sh               (Qdrant snapshot + SQLite stop/start)
версия:  /api/version → deploy_stamp.deployed_commit = на что откатывать
```

Деплой пишет `.les_deploy_stamp.json` (commit + хэш-бандл файлов) → всегда видно, что откатывать.

## 3. Риск-тиры (не мешать в одном пакете)

| Тир | Что | Куда |
|---|---|---|
| 🟢 низкий | доки, тексты, CSS/UI без схемы, мелкие фиксы | в ветку фичи, обычный цикл |
| 🟡 средний | формы/конфиг/новые сервисы без миграций | отдельный пакет + тесты |
| 🔴 высокий | схема БД, workflow, MLX/инференс, инсталлятор, ядро (Совушка/прокси) | отдельная ветка, НЕ hotfix, ревью |

- Не мешать схему/workflow и косметику в одном коммите.
- Ядро (RAG/прокси/Совушка) — не трогать без явной нужды ([[dev-stage-working-style]]).
- Ничего не удалять — архив, не снос ([[dev-stage-working-style]]).

## 4. Документация = код

- Док не должен врать о коде. При расхождении прав КОД ([[docs-overhaul-shining-repo]]).
- Карта модулей со статусом док↔код — [MODULE_INDEX.md](MODULE_INDEX.md); при правке модуля обнови строку + статус.
- Не плодить датированные саммари — состояние в `git log` + RELEASE_LEDGER + `/api/version`.
- Deploy stamp не должен врать: не подгонять `deployed_commit` косметически; не звать готовым без проверки на рантайме ([[deploy-stamp-discipline]]).

## 5. Контракт стабильной функции

Любая новая рабочая функция считается включённой только если выполнены все пункты:

- **GUI-контроль:** оператор видит состояние, может явно запустить/остановить/скрыть/открыть связанный блок и не зависит от скрытого auto-flow.
- **Ошибки как результат:** ожидаемые сбои ввода, конвертации, поиска, генерации и файлового вывода возвращают HTTP 4xx/5xx с понятным `detail` или показываются в чате/панели; исключение не должно уносить весь workflow.
- **Evidence/provenance:** для расчётов и RAG-ответов есть source/formula/assumption/MISSING/BLOCKED-след; число без происхождения не считается результатом. Для защищаемых выводов использовать системный `DefensePack/DefenseClaim` (`defense_contract_v1`): claim → basis/source/formula → assumptions/gaps/actions → defensibility.
- **Тест:** есть точечный regression test на основной happy path и хотя бы один управляемый fail path для рискованного ввода.
- **Док:** модульный/ALGO/ledger-док обновлён в том же пакете, версия `LES_VERSION` поднята.
- **Гейт:** перед готовностью минимум `make verify`; для логики — `make test` или обоснованный focused-test + явный residual risk.

## 6. Известное (на 2026-06-27, в долг)

- `make ship`: с 0.23.6.10 быстрый итерационный gate (`verify → focused tests → smoke → deploy → retry-smoke`).
- `make ship-full`: полный gate версии (`verify → test → smoke → deploy → retry-smoke`); последний полный pytest 2026-06-27: 2068 passed / 6 warnings.
- post-deploy `make smoke-basic`: pass=9 / warn=0 / fail=0; live deterministic chat latency: glossary ~49ms, project_noscope ~10ms.
- live attachment-check: `crag_status=ATTACHMENT`, `route=attachment_context/read_attachment`, `sources=['attachment:demo.txt']`.
- 0.23.6.8 задеплоено на рантайм через `tools.deploy_to_runtime --apply --restart`; `/api/version.runtime_alignment=aligned`.
