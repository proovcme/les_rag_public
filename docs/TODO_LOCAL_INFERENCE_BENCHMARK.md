# TODO — MLX vs Ollama для локального LES

Статус: MLX↔Ollama A/B, выбор MLX-кванта и OptiQ MTP p50/p95 выполнены; production MTP
отклонён до исправления telemetry/prefix-cache.

## OptiQ MTP 0.3.3 — результат 2026-07-13

Первичная серия выявилась некорректной для production sampler: OptiQ MTP hook проигнорировал
переданный `mlx_lm` sampler callback и фактически работал greedy. После диагностического
исправления sampler, single-request path и telemetry на профиле `1041→384`, один cold и пять warm:

- OptiQ AR p50 greedy: `3,71 tok/s`;
- OptiQ MTP p50 greedy: `5,20 tok/s`, uplift `40,2%`;
- исправленный MTP depth 1 p50 production: `3,83 tok/s`, acceptance `67,4%`;
- p50 wall: `113,74 с` против stock `114,95 с` (`-1,1%`);
- peak MLX memory: `8,82 ГБ`;
- tool call и продолжение после tool result прошли в stream/non-stream;
- повтор общего 6k-префикса вернул `cached_tokens=0`; cache-гейт провален;
- `8192→256`: TTFT `92,87 с`, decode `4,77 tok/s`, wall `146,57 с`.

Решение: в production не вводить. Рабочий decode uplift только `2,6%`, ниже обязательных
`15%` и порога отказа `10%`; серия 20/20 после terminal performance fail не нужна. Upstream
0.3.3 также теряет sampler, зависит от `seed`, не публикует telemetry и не использует переданный
prompt cache в MTP engine. Прежние production-цифры `5,47 tok/s`/`84,24 с` недействительны.
Полный отчёт:
[LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md](LOCAL_INFERENCE_OPTIQ_MTP_M4_2026-07-13.md).

## Диагностический результат 2026-07-13

На Mac mini M4/24 ГБ проверены прямые запросы к движкам без LES/RAG:

- `Qwen3.5-9B-MLX-4bit`, MLX: длинный вход `3 692` токена — prefill `87,3 tok/s`,
  decode `5,1 tok/s`, всего `67,8 с` на `128` выходных токенов;
- `qwen3.5:9b`, Ollama `Q4_K_M`: тот же профиль — prefill `79,9 tok/s`,
  decode `3,9 tok/s`, всего `79,5 с`;
- `qwen3:8b`, Ollama `Q4_K_M`: вход `4 098` токенов — prefill `81,7 tok/s`,
  decode `4,1 tok/s`, всего `84,8 с` на `128` выходных токенов;
- короткий контроль Ollama: `qwen3:8b` — `5,0 tok/s`, `qwen3-vl:8b` —
  `4,6 tok/s`, `gemma4:12b` — `3,1 tok/s`; Ollama сообщает `100% GPU`.
- отдельный `gemma4:12b` runtime с `OLLAMA_FLASH_ATTENTION=1` дал `3,3 tok/s`
  вместо `3,1 tok/s`; прирост недостаточен. Эта сборка мультимодальная
  (`vision` + `audio`) и не является лёгким text-only кандидатом для LES chat.

Модель не повреждена: обе копии корректно загружаются, дают связные ответы и соблюдают
простое evidence-задание. Прямой MLX-контроль вернул точные `80/75` за `9,0 с`.
Переключение LES на Ollama не принято: на этой машине тот же 9B медленнее MLX.

Живой BAI-прогон после удаления query-time deep-profile rebuild показал
`notebook_study_latency_sec=0.011` вместо примерно `39 с`. Оставшаяся задержка связана
главным образом с prefill длинного evidence-пакета и скоростью decode локальной 9B.
Следующий честный этап — пять повторов на MLX dense 8B/9B и проверка Metal/macOS,
а не смена backend вслепую.

## Выбор кванта MLX 2026-07-13

Официальный `mlx_lm benchmark` выполнен на одной машине и с одним профилем:
`512` входных токенов, `384` выходных, три прогретых запуска.

| Модель | Prefill avg | Decode avg | Peak memory |
|---|---:|---:|---:|
| `Qwen3.5-9B-MLX-4bit` | `91,13 tok/s` | `7,19 tok/s` | `5,78 ГБ` |
| `Qwen3.5-9B-OptiQ-4bit` | `152,53 tok/s` | `11,19 tok/s` | `7,84 ГБ` |

OptiQ быстрее uniform примерно на `67%` в prefill и `56%` в decode ценой около
`36%` дополнительной peak memory. Первый OptiQ-прогон не учитывается: он включал
компиляцию mixed-precision kernels и не отражал warm runtime.

Функциональный smoke OptiQ пройден: русский ответ, OpenAI-compatible tool call,
продолжение после tool result и реальный BAI RRF/notebook-запрос. BAI end-to-end занял
`57,5 с`: retrieval/rerank `38,4 с`, generation `18,5 с`; это подтверждает, что wall time
нельзя приписывать только модели. OptiQ принят основным локальным default в `0.24.0.396`.

Gemma/BaseRT не вводятся в production автоматически. Их можно сравнить отдельным экспериментом,
но LES не должен переключать две модели по скрытому роутеру: операторский выбор явный, в памяти
держится одна генеративная модель.

## Решение, которое должен дать тест

Оставлять MLX основным локальным chat runtime только при измеримом преимуществе
на реальной работе LES. Если Ollama не хуже по качеству и быстрее/стабильнее по
TTFT, памяти или эксплуатации, переключить локальный chat на Ollama. RAG,
evidence-пакет и модельные полномочия при этом не меняются: меняется только
OpenAI-compatible inference backend.

## Честные условия сравнения

- одна модель одного размера и сопоставимой 4-bit квантизации;
- одинаковые system/user messages и chat template;
- одинаковые `max_tokens`, temperature и stop conditions;
- одинаковые короткий, средний и длинный контексты;
- отдельные cold и warm прогоны;
- никакого скрытого reader, validator, reranker или параллельной индексации;
- не менее пяти повторов после одного прогревочного запуска;
- отдельный end-to-end прогон через реальный RRF LES.

## Метрики

1. Cold load, TTFT и полное wall time.
2. Prefill tokens/s и decode tokens/s.
3. RSS, Metal/CPU memory, compressor и swap до/во время/после запроса.
4. Освобождение памяти после TTL/unload.
5. Стабильность на серии из 20 запросов и после длинного контекста.
6. Качество на одинаковом наборе вопросов: полнота, ссылки на evidence,
   неподтверждённые утверждения и соблюдение формата.
7. End-to-end время LES отдельно от raw inference.

## Нагрузочные профили

- короткий prompt, 128 output tokens;
- 8k input tokens, 256 output tokens;
- 16k input tokens, 512 output tokens;
- notebook/RRF обзор датасета;
- серия из 20 смешанных запросов;
- один запрос одновременно с разрешённым retrieval, без индексации.

## Критерий выбора

Провайдер принимается как основной, если он не проигрывает по качеству, не
создаёт устойчивый swap/утечку и даёт лучший либо сопоставимый p50/p95 TTFT и
wall time. Разница менее 10% считается паритетом; при паритете выбирается более
простой и наблюдаемый runtime.

## Не смешивать с текущим ремонтом

Текущий дефект LES уже доказан независимо от сравнения: прежний MLX endpoint
имитировал stream после полной генерации, а notebook-study мог запускать скрытый
reader. Сравнение начинается только после выкладки настоящего stream и удаления
скрытого fan-out, иначе оно сравнивает оркестраторы, а не MLX и Ollama.
