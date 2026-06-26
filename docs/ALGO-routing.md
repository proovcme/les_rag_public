# Алгоритм: маршрутизация запроса чата (ProfileResolver + agent-router)

Как ЛЕС выбирает, ЧЕМ отвечать на запрос. Канон текущей механики (сверено с кодом 2026-06-27).
История решения «инвертировать детерминизм» — в [AUDIT_DETERMINISM.md](AUDIT_DETERMINISM.md) (исполнено).

## Принцип (инверсия детерминизма — исполнена)

Раньше keyword-каскад (11 детерм. каналов) стоял ПЕРВЫМ и перехватывал намерение по словам. Теперь
**основной — агент-роутер** (LLM выбирает инструмент по смыслу), а keyword-каскад — спящий фолбэк.
Детерминизм живёт в **инструментах и гейтах**, а не в перехвате по подстроке.

```
запрос → runtime_admission (очередь/режим)
       → ProfileResolver.resolve()  → Profile (контур ответа)         [profile_resolver.py]
       → agent_router (router_primary ON по умолчанию)                 [agent_router_service.py]
           │ LLM выбирает инструмент из каталога _TOOLS (price/kac/lsr/glossary/doc_review/asbuilt…)
           ▼ инструмент исполняется в chat.py (где есть scope/effective_dataset_ids)
       → если роутер ничего не выбрал И not router_primary() → keyword-каскад _det_channels (фолбэк)
       → иначе → RAG-конвейер (retrieval → saferag C-RAG → dispatcher), профиль задаёт каркас ответа
```

## ProfileResolver — единый контракт

`proxy/services/profile_resolver.py`: `resolve()` → `Profile` (dataclass), `refine()`, `as_trace()`;
реестр `PROFILES`, `MODE_TO_PROFILE`. Режим-чип GUI → профиль:

| Режим (чип) | Профиль | Контур |
|---|---|---|
| Сметы | `object_estimate` | объектная смета / сметные инструменты |
| Нормоконтроль | `normcontrol` | doc-review по rulepack |
| Поиск (default) | `grounded_rag` | RAG с цитатами |
| (свободный) | `free_llm` | прямой LLM |
| КП | `kp_stub` | заглушка КП |

`query_route.profile` несёт честный `route_source` + `channel` в trace каждого ответа.

## Где в коде

- Резолвер профиля: `proxy/services/profile_resolver.py`
- Агент-роутер (каталог инструментов + LLM-выбор): `proxy/services/agent_router_service.py` (`router_primary()` — флаг `LES_ROUTER_PRIMARY`, дефолт **ON**)
- Детерм. политика финала: `proxy/services/deterministic_policy_service.py` (legacy-каналы дают final ТОЛЬКО при явном намерении/команде/точном термине)
- Область поиска: `proxy/services/scope_service.py` (all/project/dataset…; проектный запрос при scope=all → не искать молча, спросить)
- Поток: `proxy/routers/chat.py` (`_run_chat`: роутер ПЕРЕД каскадом; каскад = `not router_primary()`)
- Обзор на ревью: [ARCHITECTURE_les_algorithm.md](ARCHITECTURE_les_algorithm.md) §10

## Граница

- `table_query` детект всё ещё substring (`_looks_like_table_query`) — но теперь под router-интентом, агрегация пост-ретрив над Parquet ([[ALGO-table-query]]).
- Цель «детерминированные автоответы по широким словам запрещены» (ROADMAP §2.3) — соблюдается: final от legacy-канала только на явный сигнал ([[no-determinism-in-chat-directive]]).
