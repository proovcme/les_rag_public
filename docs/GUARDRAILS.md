# GUARDRAILS — что НЕ ломаем + как катим в прод

> Дисциплина выпуска (модель locia). **Стабильность важнее фич.** Прод — живой; деплой только после
> тестов, с механикой отката. Состояние/версия — [RELEASE_LEDGER.md](RELEASE_LEDGER.md).

## 1. Прод-гейт: в рантайм только после тестов

Последовательность выката (цель — `make ship`, пока вручную в этом порядке):

```
1. make verify        # офлайн-гейт: compileall + pytest --collect-only (импорт-смоук)
2. make test          # полная сюита — должна быть зелёной (или явный список known-fail)
3. make smoke-basic   # живой HTTP-смок против рантайма (:8050/:8051)
4. bump версии 0.23.N.P + строка в RELEASE_LEDGER + releases.md
5. uv run python -m tools.deploy_to_runtime --apply [--restart]   # cp + deploy stamp
6. make smoke-basic   # post-deploy: подтвердить, что живое не упало
```

**Деплой запрещён, если шаги 1-3 красные** (или без явного решения оператора по known-fail).

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

## 5. Известное (на 2026-06-27, в долг)

- `make test`: 9 fail / 2037 pass (version-эндпоинт ×3, help `topic_slices` TypeError, 3× chat live-сервисы, profile_resolver glossary) — разобрать при возврате к коду.
- `make smoke-basic`: 8/1 (chat_project_noscope таймаут; chat_glossary 82с) — латентность чата.
- Версия `0.23.N.P` зафиксирована в доке (RELEASE_LEDGER); внедрение в `version_service`/`/api/version` — в очереди (код на паузе).
