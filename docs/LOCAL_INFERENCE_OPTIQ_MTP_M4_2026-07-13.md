# OptiQ MTP на Mac mini M4 — живой отчёт 2026-07-13

## Решение

`mlx-optiq 0.3.3` в production LES **не вводить**. MTP-head реально работает, но исходный
OpenAI hook теряет request sampler и фактически исполняет greedy. После диагностического
исправления sampler рабочий production uplift составляет только `2,6%` по p50 decode и
`1,1%` по p50 wall — ниже обязательных `15%` и ниже порога отказа `10%`.

Штатный MLX host во время проверки был остановлен штатным runtime-control, каждый benchmark
server запускался отдельно на `127.0.0.1:18080`. После теста временный server остановлен,
production MLX host возвращён на `:8080` и проверен `HTTP 200`.

## Среда

- Mac mini M4, 24 ГБ unified memory;
- один snapshot:
  `mlx-community/Qwen3.5-9B-OptiQ-4bit@1f7c283df48075ff4e50c24251b7d29d603bdc02`;
- MTP sidecar: `optiq/mtp.safetensors`, 29 tensors, 185 МБ;
- изолированный runtime вне uv-проекта:
  `~/.cache/les-bench/optiq-0.3.3`, `mlx-optiq==0.3.3`, `mlx==0.32.0`,
  `mlx-lm==0.31.3`;
- sampler: greedy `temperature=0`; production `temperature=0.7`, `top_p=0.8`,
  `top_k=20`; исправленный контроль выполнен без request `seed`;
- основной профиль: ровно `1041` prompt tokens и `384` completion tokens;
- один cold и пять warm запросов, настоящий stream; prompt cache проверялся отдельно.

Во время серии macOS показывала около `3,1–3,3 ГБ` уже выделенного swap. Второй загруженной
LLM не было. Диагностический wrapper измерил MLX peak напрямую: `8 824 155 922` bytes
(`8,82 ГБ`) на warm production MTP. Upstream OpenAI response это значение не возвращает.

## Результаты

| Engine / режим | p50 decode | p95 decode | p50 TTFT | p50 wall | Cache |
|---|---:|---:|---:|---:|---:|
| stock `mlx_lm.server`, greedy | `3,75 tok/s` | `3,99 tok/s` | `13,49 с` | `115,86 с` | `0` |
| stock `mlx_lm.server`, production sampler | `3,73 tok/s` | `3,88 tok/s` | `13,05 с` | `114,95 с` | `0` |
| `optiq serve` без MTP, greedy | `3,71 tok/s` | `3,94 tok/s` | смешан cache hit/miss | `104,27 с` | до `1040` |
| `optiq serve --mtp --mtp-depth 2`, greedy | `5,20 tok/s` | `5,21 tok/s` | `14,77 с` | `88,68 с` | `0` |
| MTP depth 1, исправленный production sampler | `3,83 tok/s` | `4,01 tok/s` | `13,56 с` | `113,74 с` | `0` |

Greedy MTP uplift относительно OptiQ AR p50:

`5,198 / 3,709 - 1 = 40,2%`.

Относительно stock greedy p50 uplift `38,6%`. Это валидный greedy-контроль, но не результат
рабочего sampler. Direct synthetic benchmark `11,19 tok/s` и API serving decode — разные
траектории исполнения; выдавать первое за скорость чата нельзя.

Исправленный production MTP дал aggregate acceptance `67,4%`. Относительно stock production
p50 decode вырос с `3,73` до `3,83 tok/s` (`+2,6%`), p50 wall снизился с `114,95` до
`113,74 с` (`-1,1%`), p95 wall — с `123,96` до `116,94 с` (`-5,7%`). Формальное wall parity
есть, но практического выигрыша нет: обязательный `15%` uplift провален и срабатывает заранее
согласованный отказ при приросте менее `10%`.

Прежние `5,47 tok/s` и `84,24 с`, подписанные как production, **недействительны**: HTTP body
содержал production sampler, но OptiQ MTP hook получил только готовый `sampler` callback,
проигнорировал его и использовал свои defaults `temperature=0/top_p=0/top_k=0`, то есть greedy.

Дополнительные smoke:

- tool call `lookup_norm`: stream и non-stream прошли, имя/аргументы распознаны;
- продолжение после tool result: stream и non-stream прошли;
- прежний `8192→256`, подписанный production MTP, также недействителен как production-замер;
- одинаковый системный prefix около 6k токенов и разные вопросы: cold TTFT `96,25 с`,
  повтор `74,10 с`, но оба ответа вернули `cached_tokens=0`; cache-гейт провален.

## Найденные runtime-дефекты

В `mlx-lm 0.31.3` запрос без `seed` считается batchable и уходит в `BatchGenerator`.
OptiQ 0.3.3 подключает MTP патчем `mlx_lm.server.stream_generate`, а batch-path этот hook
обходит. Поэтому сервер может написать `MTP speculation enabled`, фактически не загрузив
MTP-head. Доказательство реального включения — только строки:

```text
[optiq.serve] attaching MTP engine to loaded model ...
[MTP inject] Loaded 29 tensors .../optiq/mtp.safetensors
[optiq.serve] MTP engine ready (depth=2).
```

Диагностический launcher принудительно выставляет `ModelProvider.is_batchable=False`, поэтому
исправленный прогон без `seed` действительно использовал MTP.

Вторая ошибка критичнее: `mlx_lm.server` передаёт в `stream_generate` готовый `sampler`, но
`install_mtp_speculation()` читает только отсутствующие kwargs `temperature/temp`, `top_p`,
`top_k`, `min_p`. В результате любой OpenAI request sampler молча превращается в greedy.
Launcher переносит sampling arguments через request worker context непосредственно в
`OptiqEngine.generate_stream`; telemetry каждого запроса подтверждает `0.7/0.8/20`.

Третья ошибка: MTP hook не использует переданный `prompt_cache`; `OptiqEngine.generate_stream`
создаёт новый cache на каждый запрос. Поэтому MTP cache был принудительно выключен. Иначе при
cache hit сервер передал бы движку только остаток prompt вместе с cache, который движок игнорирует.

## Почему production-гейт не пройден

1. Исправленный рабочий uplift `2,6%` ниже обязательных `15%` и ниже порога отказа `10%`.
2. Upstream MTP OpenAI path не применяет request sampler; без внешнего patch замер неверен.
3. Upstream MTP path зависит от `seed` для обхода batch generator.
4. MTP engine игнорирует server prompt cache; безопасный prefix reuse отсутствует.
5. Acceptance `67,4%` и peak `8,82 ГБ` получены только sidecar-wrapper, не публичным API.
6. Серия `20/20` не запускалась после терминального performance fail: она проверяет стабильность
   кандидата, который сначала должен пройти speed gate.
7. Абсолютный исправленный API decode `3,83 tok/s` не достигает целевых `13–15 tok/s`.

## Воспроизведение

Runtime создаётся вне проекта:

```bash
uv venv ~/.cache/les-bench/optiq-0.3.3
uv pip install --python ~/.cache/les-bench/optiq-0.3.3/bin/python 'mlx-optiq[serve]==0.3.3'
```

У пакета 0.3.3 нет зарегистрированного extra с именем `serve`; uv предупреждает об этом,
но server-компоненты входят в базовую поставку.

Исправленный диагностический endpoint:

```bash
LES_OPTIQ_TELEMETRY_JSONL=/tmp/les-optiq-mtp.jsonl \
~/.cache/les-bench/optiq-0.3.3/bin/python tools/optiq_mtp_probe_server.py serve \
  --model mlx-community/Qwen3.5-9B-OptiQ-4bit \
  --mtp --mtp-depth 1 --port 18080 --prompt-cache-size 0

uv run python tools/local_inference_benchmark.py \
  --base-url http://127.0.0.1:18080/v1 \
  --model benchmark-model \
  --engine optiq-0.3.3-mtp1-corrected \
  --profiles throughput-1041x384 \
  --samplers production \
  --warm-runs 5 \
  --stream yes --omit-seed \
  --telemetry-jsonl /tmp/les-optiq-mtp.jsonl \
  --output /tmp/les-optiq-mtp.json
```

Следующий пересмотр возможен после версии OptiQ, которая одновременно:

- принудительно отключает batch-path при `--mtp` без зависимости от request seed;
- передаёт фактические request sampler parameters в MTP engine;
- возвращает acceptance/drafted counts и peak memory через API;
- корректно использует общий prompt cache без потери префикса;
- даёт минимум `15%` p50 decode uplift и сохраняет `p50_wall_mtp <= p50_wall_stock`.
