# Алгоритм: ЭТМ — коммерческие цены поставщика

Read-only мост к Product API ЭТМ для материалов, которых **нет в ФГИС ЦС**.
Цены идут в ЛСР через КАЦ (`kac_map`), не как отдельная pricebook-книга.

## Границы

| API | В ЛЕС |
|---|---|
| Product: login, Price, Goods (v2) | **Да** — цены и карточки-кандидаты |
| Product: Remains, SgGds, Info | Позже (не v1) |
| Order: create/status/delivery | **Нет** — не для расчёта сметы |

Серверы: prod `https://ipro.etm.ru/api/v1`, test `https://itest2.etm.ru/api/v1`.
Goods-карточки: `https://ipro.etm.ru/api/v2/goods/{id}`.

## Ownership

- **Модель или пользователь** выбирает код ЭТМ / артикул / код клиента (`type=etm|cli|mnf`).
- Код **не** invent-ит номенклатуру и **не** подставляет цену без provenance.
- ФГИС parquet остаётся официальным hot-path; ЭТМ **не** `LES_DEFAULT_PRICEBOOK`.

## Шаги

1. `needs_kac(fgis_code)` → материала нет в локальной книге ФГИС.
2. Оператор/модель задаёт `etm`/`cli`/`mnf` код (browse Goods даёт candidates only).
3. `POST /api/prices/etm/lookup-batch` → quotes с `source_kind=supplier_api`.
4. `build_kac_map_from_quotes` кладёт цену в `kac_map` по **resource_code и** нормализованному имени.
5. Calculator / `rim_lsr_trace` берёт `kac` при miss ФГИС; иначе MISSING.
6. Все поля цены API = 0 → `individual_quote_required`, цена остаётся пустой (не 0).

## Лимиты и креды

- Login ≤ 1 / 2 мин; session ~8 ч.
- Price / Goods ≤ 1 req/s; batch ≤ 50 кодов.
- Env: `LES_ETM_LOGIN`, `LES_ETM_PASSWORD`, optional `LES_ETM_BASE_URL`, `LES_ETM_TIMEOUT_SEC`, `LES_ETM_VAT_PCT`.
- Креды класть в **`config/local/secrets.env`** (gitignore; шаблон `secrets.env.example`). Не коммитить и не писать пароль в `windows-cuda.env`.
- Дефолтное поле цены: `pricewnds` (с НДС) → net в `analyze_kac` / bridge через `vat_pct`.
- Секреты и session-id не логируются и не отдаются в status/API.

## Проверка (можно параллельно со сборкой ЛСР)

Живой гейт **не рестартит** proxy/UI и не мешает текущему document workflow:

```text
uv run python tools/etm_live_smoke.py
```

Ожидание: `login: ok`, `ok: true`. Код по умолчанию `9536092` (или `LES_ETM_SMOKE_CODE` / `--code`). Пароль и session-id в вывод не попадают. Login ЭТМ ≤ 1 / 2 мин — не крутить smoke в цикле.

Если smoke пишет `authentication failed: Неверный логин или пароль` — это ответ Product API, не баг адаптера. Логин API часто вида `690000889TA`, а телефон iPRO-сайта может не приниматься. Нужен API-доступ, согласованный с менеджером ЭТМ. Prod `https://ipro.etm.ru/api/v1`, test `https://itest2.etm.ru/api/v1`.

После следующего старта LES (`LES-START.ps1` или `start-light.ps1` подхватывают `secrets.env`):

1. Совушка → **Инструменты** → «ЭТМ: настроен (read-only Product API)».
2. Тот же код → «Запросить цену ЭТМ» → цена с provenance, не 0.
3. `GET /api/prices/etm/status` → `"configured": true` без login/password.

ЭТМ не выбирает нормы ГЭСН. Это коммерческие quotes → `kac_map` для материалов вне ФГИС ЦС, после того как модель/оператор указали код ЭТМ.

## Где в коде

- Адаптер: `proxy/services/etm_price_service.py`
- API: `GET /api/prices/etm/status`, `POST /api/prices/etm/lookup-batch`, `POST /api/prices/etm/browse`
- Live smoke: `tools/etm_live_smoke.py` (без рестарта LES)
- КАЦ: `proxy/services/kac_service.py`, `ALGO-kac.md`
- Трасса цены: `proxy/services/rim_lsr_trace_service.py` (`source=kac`)
- Тесты: `tests/test_etm_price_service.py`, `tests/test_prices_etm_router.py`, `tests/test_etm_live_smoke.py`

## Статус

✅ актуальный контракт v1 (Product Price + Goods browse + kac_map wiring).
