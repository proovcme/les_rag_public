# Состояние системы Л.Е.С. (27.05.2026 — закрытие длинной сессии)

## Итог

Л.Е.С. переведён в рабочий Core ML контур для embedding и validator, индекс закрыт, внешний доступ через `https://les.ovc.me` поднят, а тестовая линейка зелёная.

## Runtime

- Proxy health: `1003/1003` indexed, `0` pending, `0` errors, `248917` chunks.
- Qdrant collection: `les_rag_qwen3_06b`, `248917` points, `points_match_sqlite_chunks=true`.
- MLX Host: main model `mlx-community/Qwen3.5-4B-OptiQ-4bit`.
- Embedder: Core ML `Qwen/Qwen3-Embedding-0.6B`, package `artifacts/coreml/qwen3_embedding_06b_b1_s512_static.mlpackage`, `cpu_and_gpu`, isolated worker, fallback disabled.
- Validator: Core ML `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`, package `artifacts/coreml/validator_minilm_l6_b1_s512.mlpackage`, `cpu_only`, isolated worker, `VALIDATOR_BACKEND=coreml`, fallback disabled.
- Deterministic smoke backend remains available through `VALIDATOR_BACKEND=rules`.

## Data And Features

- `BOOKS_Index` хвост закрыт: `1 indexed`, `0 pending`, `2845 chunks`.
- `MAIL_Index` закрыт: `200 indexed`, `0 pending`, `475 chunks`.
- FIRE/HVAC quality hardening закрыт как системный слой, а не точечный патч:
  - `NTD_FIRE`: `179 files`, `32126 chunks` в health by-domain.
  - `NTD_HVAC`: `23 files`, `8297 chunks`; 10 HVAC docs перенесены selective guarded route-change reindex.
  - Lexical index rebuilt: `indexed_count=248917`, `point_count=248917`.
  - `golden/domain_fire_hvac_set.json` проходит `16/16` с проверкой route filter, source top-N и expanded evidence.
  - Вопросы “где смотреть/какие нормы/каким нормативом” отвечаются через `deterministic_source_lookup`, чтобы не превращать простую навигацию по нормам в LLM+validator gamble.
- Table query MVP читает Parquet row-level artifacts напрямую для сумм, количеств и строк без LLM.
- Е.Ж.И.К. умеет deterministic mail questions по `.eml/.msg`, участникам и thread metadata.
- Chat history пишет route/retrieval/dataset trace; user feedback сохраняется через `/api/chat/history/{id}/feedback`. Видимая кнопка `Плохой ответ` пишет статус `bad_answer` в SQLite, `logs/chat_feedback.jsonl` и `[CHAT_FEEDBACK]` warning в `logs/proxy.log`; `/api/chat/learning` отдаёт успешные/подтверждённые/размеченные кейсы для будущих эвристик.

## External Access

- `https://les.ovc.me` работает через П.А.У.К. reverse tunnel и Caddy.
- Внешний доступ требует В.О.Л.К. API key; admin key даёт полный доступ к chat/admin/diagnostics.
- Для передачи ключа не фиксировать секрет в git-документации. Хранить ключ во внешнем password manager или окружении оператора.

## Cleanup

- Repo/runtime cleanup удалил лишние snapshots, старые reindex backups, неиспользуемые Core ML packages и раздутые logs.
- Hugging Face cache оставлен только под активные модели:
  - `models--mlx-community--Qwen3.5-4B-OptiQ-4bit`
  - `models--Qwen--Qwen3-Embedding-0.6B`
  - `models--MoritzLaurer--multilingual-MiniLMv2-L6-mnli-xnli`
- Контрольный размер: repo около `11G`, HF cache около `4.6G`, `artifacts/coreml` около `1.3G`, свободно около `145Gi`.

## Verification

- `uv run pytest -q` -> `352 passed`.
- `uv run python tools/rag_golden_set.py --cases golden/domain_fire_hvac_set.json` -> `16/16`.
- Live local FIRE/HVAC smoke:
  - `Найди пункт 7.3 в СП 7.13130` -> `VERIFIED`, `deterministic_clause`, `NTD_FIRE`.
  - `Где смотреть требования к микроклимату помещений?` -> `VERIFIED`, `deterministic_source_lookup`, `NTD_HVAC`, sources include `СП 60.13330`.
- Live feedback smoke через `https://les.ovc.me/api/chat/history/{id}/feedback` -> `bad_answer` записан в `logs/chat_feedback.jsonl` и `logs/proxy.log`.
- `tools/runtime_smoke.py` через `https://les.ovc.me` -> `12/12 OK`.
- Direct public table query “посчитай общую стоимость по всем строкам сметы” -> `VERIFIED`, `deterministic_table`, `42 580`.
- `uv lock --check` -> OK.
- `git diff --check` -> OK.

## Next

- Пускать живые вопросы через коллегу и собирать feedback/golden examples; FIRE/HVAC вопросы расширять как acceptance set, а не править по одному ответу.
- Расширять validator golden set из реальных `validation_context_windows`, а не синтетикой.
- Добивать К.О.Т., Е.Ж.И.К., Parquet/table UX и dataset-cleanup heuristics по подтверждённым ответам.
- Не делать full reindex и не возвращать удалённые модели без явной причины и отдельного плана.
