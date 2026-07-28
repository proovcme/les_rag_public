# Внутреннее обновление Mac

## Что получает оператор

`make prepare-mac-update` создаёт небольшой локальный ZIP только из изменённых runtime-файлов
между deploy stamp установленной версии и точным commit разрешённой ветки. По умолчанию это
`codex/audit-rag`; отдельная UI-ветка задаётся явно через
`MAC_UPDATE_BRANCH=codex/sovushka-ui-kit`. Сборка приложения, полная pytest-сюита, smeta
baseline, пользовательские документы и индексы в пакет не входят.

После подготовки один и тот же механизм доступен:

- из терминала: `make apply-mac-update`;
- в Совушке: «Настройки → Быстрое обновление ЛЕС → Проверить патч → Установить».

Установка завершается только после совпадения commit, product version и build number, HTTP health
proxy/UI и совместимого RAG index contract. При провале изменённые файлы и deploy stamp
автоматически восстанавливаются из локальной точки отката.

## Команды

```bash
make prepare-mac-update
make inspect-mac-update
make apply-mac-update
make status-mac-update
```

Для отдельной UI-ветки один и тот же параметр передаётся prepare/inspect/apply/status:

```bash
make prepare-mac-update MAC_UPDATE_BRANCH=codex/sovushka-ui-kit
make inspect-mac-update MAC_UPDATE_BRANCH=codex/sovushka-ui-kit
make apply-mac-update MAC_UPDATE_BRANCH=codex/sovushka-ui-kit
make status-mac-update MAC_UPDATE_BRANCH=codex/sovushka-ui-kit
```

`prepare-audit-rag`, `inspect-audit-rag-update`, `deploy-audit-rag-mac` и
`deploy-audit-rag` временно оставлены совместимыми Mac-only псевдонимами. Подготовка и
установка Legion этим контуром отключены до отдельной приёмки Mac updater.

## Инварианты

- подготовка разрешена только из чистой явно названной `codex/*` ветки, где `HEAD`
  совпадает с тем же `origin/<branch>`; синтаксис git refs и выход за `codex/`
  отклоняются;
- архив и detached helper проверяются независимыми SHA-256;
- архив содержит только объявленные в manifest файлы из runtime allowlist;
- `.env`, `data/`, `storage/`, `RAG_Content/`, индексы, секреты, desktop/installer и baseline
  запрещены на уровнях builder, API validator и detached helper;
- перед заменой каждый установленный файл обязан совпасть с base или target SHA;
- частично восстановленный старый runtime принимается только когда его полный текущий SHA
  подтверждён сохранённым `file_hash_bundle` прежнего deploy stamp для того же пути; произвольный
  drift продолжает блокировать установку;
- одноразовый исторический drift допускается только через committed
  `config/mac_runtime_reconciliation.json` с точными current/target SHA; после замены runtime
  снова обязан совпасть с Git. Запись активна только пока runtime имеет её exact
  `accepted_sha256`; после успешного выравнивания она не блокирует следующие изменения того же файла;
- пакет content-addressed и локальный: updater не публикует feed, tag, GitHub Release и не
  обращается к Legion;
- повторная установка уже применённого пакета возвращает «Mac уже обновлён».
- публичный `/api/version` показывает статус и несовпавшие пути, но не раскрывает
  внутренний `file_hash_bundle`; updater проверяет ownership по локальному stamp.

Кэш: `/Users/ovc/LES_update_cache/mac`. Точки отката:
`/Users/ovc/LES_recovery/mac-updates/<update_id>`.
Каждая recovery-точка хранит также `previous_deploy_stamp.json`, а новый stamp наследует SHA
нетронутых файлов и обновляет только фактически заменённые пути.

## Проверка

```bash
uv run pytest -q tests/test_mac_update.py tests/test_manual_update_ui.py
make verify
```

`tests/test_mac_update.py` отдельно доказывает успешную атомарную замену и возврат исходного файла
при провале smoke на временном runtime.
