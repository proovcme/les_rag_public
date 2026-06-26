# Session Summary 10 — LES3: W5 отзывчивость UI (SSE-стрим, push, удаление лайт-шеллов)

Workspace: `/Users/ovc/Projects/LES_v2` · Runtime clone: `/Users/ovc/Projects/LES_v2_reinstall_stress`
Дата закрытия: `2026-06-14` · Ветка: `feat/les3-p1` (синхронна с origin, HEAD `d7dc987`)

---

## 🔜 ПРОМТ-ХЕНДОФФ (вставить в следующую сессию)

> Продолжаем LES3 по `docs/LES3_PLAN.md`. Прочитай `AGENTS.md`, `docs/CODE_MAP.md`, `SKILL.md` и память.
> Принципы: **LLM-минимализм** (ADR-11), **облако только OpenRouter+OpenAI** (ADR-9), **GUI-first**.
> После каждого шага: документация + SKILL + CODE_MAP + план, `make verify`, git commit+push.
>
> **Волна W5 закрыта** (W5.1/5.2/5.3/5.4/5.5/5.6/5.7 — все). Но у W5.1/5.2/5.4-5.5 остаток `[live]` —
> **браузерная приёмка оператора не проведена** (см. ниже). Бери:
> 1. **🔴 Браузерная приёмка W5** (ПЕРВЫМ, до новых карт — это outward-facing): задеплоить ветку в
>    рантайм-клон, прогнать **внешний smoke 12/12** (`tools/runtime_smoke.py --proxy-url https://les.ovc.me`),
>    `browser_smoke`, `zerotier_access_smoke`, и руками: первый токен чата `<2с` (SSE), прогресс-бар реиндекса
>    в САМОВАРе, Speckle-панель в ⚙. Если что-то красит — чинить ДО новых карт.
> 2. **Полевая вертикаль W8.2/W8.3** (фото→VLM→подтверждение) — разблокировано W3.3 (облако готово).
> 3. **W6.1** агрегатные BIM-чанки — требует окно реиндекса, согласовать.
> 4. На решение оператора: перенос `local_private_archive` (8.9 ГБ) на `/Volumes/Data`.

---

## Что сделано в этой сессии (W5.1/5.2/5.4/5.5)

### W5.1 — SSE-стриминг чата — ЗАКРЫТА (код), [live]-приёмка за оператором
- Тело `chat()` → ядро `_run_chat(req, token_sink=None)`. Старый `POST /api/chat` — тонкая обёртка
  `token_sink=None`: путь `stream:False` **неизменен по построению** (M5/смоуки/АРТЕЛЬ/`chat_format_smoke`).
- Новый `POST /api/chat/stream` → `StreamingResponse(text/event-stream)`, события **token/reset/final/error**;
  финал несёт авторитетный payload (вердикт валидации в `crag_status`). Стримит только generic-LLM путь
  (`_post_llm`, `stream:True`); детерминированные/кэш/clarification — сразу `final`. Ретрай строгого промпта
  и деградация облако→MLX шлют `reset`. `stream_options{include_usage}` — только облаку (MLX без риска 400).
- Клиент: `state.api_post_stream` (SSE-парсер) + инкрементальный `label.set_text` в `pages/chat.py`;
  откат на `/api/chat` если стрим не дал ни одного токена. 6 тестов (`tests/test_chat_stream_w51.py`).

### W5.2 — Push `/api/live` вместо поллинга — ЗАКРЫТА (код), [live]-приёмка за оператором
- `GET /api/live` (`runtime.py`, SSE): каждые `LES_LIVE_INTERVAL_SEC` (деф. 3с) событие `snapshot` со сводкой
  `metrics/status/indexing_mode/jobs_summary/reindex` (`_live_snapshot`, устойчив к сбою ветки).
- Клиент: `state.live_subscribe()` (один долгоживущий SSE) + `_apply_live_snapshot()`. `bg_loop` стал
  **push-first**: убран высокочастотный поллинг (metrics 6/мин, status 3/мин), остаётся редкое (mlx 30с,
  samovar 60с) + переподключение push + фолбэк-поллинг если push лёг. ПРОРАБ рендерит из `state`,
  лог-таймер САМОВАРа читает локальный `proxy.log` (не HTTP).
- **Прогресс-бар реиндекса** в САМОВАРе из `state["reindex"]` (N/M + текущий файл), 3с-таймер без HTTP.
  5 тестов (`tests/test_live_push_w52.py`).

### W5.4/5.5 — Удалены ОБА лайт-шелла, единственный UI на NiceGUI — ЗАКРЫТА (код), [live]-приёмка за оператором
- `lite_chat.py` (844) и `lite_admin.py` (1600) **удалены**. Всё не-HTML консолидировано в новый
  **`sovushka/lite_bridge.py`** (`register_lite_bridge_routes`): мост `/lite-api/*`→proxy (контур
  les.ovc.me/M5/smoke 12/12/вьювер CAD/BIM), `/lite-runtime/*` (рестарты, loopback/trusted), статика+страница
  вьювера `/les/cad-bim-viewer`, редиректы `/`→`/classic`, `/les`+`/les/lite`→`/les/classic`. M5 сохранён.
- **Сверка панелей перед удалением:** LLM Provider («СЕЙЧАС ОТВЕЧАЕТ») и Mail/IMAP **уже были** в NiceGUI
  (диалог настроек `components/header.py`); dispatcher/реиндекс/выгрузка — в САМОВАРе/ПРОРАБе. Единственный
  пробел — **Speckle/CAD-BIM JSON** — портирован в диалог настроек (поля + «Проверить Speckle» / «Импорт
  JSON-графа», сохранение общим 💾).
- Тесты: HTML-шелл-тесты удалены; юнит-тесты моста/доверия/рантайма → `tests/test_lite_bridge.py` (14) +
  инвентаризация маршрутов (мост/рантайм/вьювер/редиректы живы на `app`). `zerotier_access_smoke` — ярлыки
  обновлены (urlopen следует за 307 → 200 на trusted).

## Состояние / незакрытое
- **Origin синхронен (`d7dc987`); рантайм-клон НЕ обновлялся** — сервисы намеренно не дёргал (CLAUDE.md:
  не рестартить без нужды; W5.4-5.5 outward-facing, приёмка браузерная за оператором).
- **`make verify` зелёный (652 теста; было 642: +6 W5.1, +5 W5.2, +14−15 W5.4-5.5).**
- **🔴 Главный остаток — браузерная приёмка W5** (см. хендофф п.1). Риск-точки для проверки на живом:
  (1) MLX принимает `stream:true` в `/api/chat/stream` (chat уже стримит — должно ОК); (2) внешний smoke
  12/12 после удаления шеллов (мост сохранён, редиректы 307); (3) вьювер CAD/BIM `/les/cad-bim-viewer` и
  его статика; (4) M5-экран ходит через `/lite-api/*`.
- `local_private_archive` (8.9 ГБ) — перенос ждёт решения оператора.

## Принципы / решения
- W5.1 **старый эндпоинт неизменен по построению** — рефактор через ядро `_run_chat`, обёртка `token_sink=None`.
- W5.4-5.5 **мост ≠ шелл**: удалены только HTML-шеллы, мост/рантайм/вьювер вынесены в `lite_bridge.py`.
- Сверка перед удалением показала: панели (кроме Speckle) уже жили в NiceGUI — порта почти не потребовалось.
