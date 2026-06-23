# Аудит жёсткой детерминации: что перехватывает и мешает RAG

**Установка Олега:** ЛЕС — это RAG, которому ПОМОГАЮТ встроенные инструменты детерминации.
Сейчас собрано наоборот — детерминированные keyword-каналы стоят ГЕЙТОМ перед RAG и перехватывают
запрос. Это костыли. См. [[rag-over-presets-not-keyword-channels]], [[les-as-harness-vision]].

**Решения (2026-06-23):** (1) разворачиваем через аудит → потом код; (2) команды ТОЖЕ становятся
инструментами агент-роутера (единый механизм). Цель — RAG/агент-роутер основной, детерминизм = его
инструменты, RAG по умолчанию.

## Поток СЕЙЧАС (перевёрнут)

```
route_query → intent.channel {table|mail|field|rag}     ← keyword-классификатор (стр. query_router.py)
   │
КАСКАД _det_channels (chat.py ~838): «первый сработавший = ответ»   ← 11 keyword-ГЕЙТОВ
   tasks → preset → asbuilt → les_md → registry → glossary → smeta → help → field → decision → memory
   │ (+ отдельно: clause_lookup regex, table_query substring, mail keyword-список)
maybe_autonote (авто-факт)
   │
Ярус 2 agent_router (LLM выбирает инструмент)   ← ЗА ФЛАГОМ LES_AGENT_LOOP, как FALLBACK «если regex не поймал»
   │
RAG retrieve_chat_chunks   ← в самом низу
```

То есть LLM-роутер инструментов (правильный механизм) **выключен и стоит последним**, а keyword-костыли — первыми.

## Инвентарь гейтов

| Гейт | Триггер (механизм) | Перехватывает | Под ним сервис | Становится |
|---|---|---|---|---|
| **route_query** | `TABLE_AGGREGATE/MAIL/FIELD/NORMATIVE/FIRE_TOKENS` (substring) | разводит на table/mail/field/rag ДО всего | — | роутер решает; default **rag** |
| `tasks` | regex команды | «создай задачу / выполнено» | task_service | **инструмент** (есть: `task`) |
| `preset` | keyword | «режим cloud/local/mix» | preset | **инструмент** (есть: `preset`) |
| `asbuilt` | keyword | приёмка ИД-сканов | asbuilt_intake | **инструмент** (есть: `asbuilt`) |
| `les_md` | keyword | «пойми папку» LES.md | les_md | **инструмент** (есть: `les_md`) |
| `registry` | keyword | реестр проектов | project_registry | **инструмент** (есть: `project_registry`) |
| `glossary` | «что такое X» substring | определения | smeta_ontology | **инструмент** (новый) — костыль: «кац»⊂«специфиКАЦия» |
| `smeta` | `_PRICE/_KAC/_STESN/_ASSEMBLE_WORDS` + `_GESN_RE` + «дай смету» | цена/КАЦ/стеснённость/сборка/объект-смета | fgis_price, kac, stesnennost, lsr_assembly, object_estimate | **инструменты** (price/kac/stesn/lsr_assemble — уже MCP; object_estimate — костыль-шаблон) |
| `help` | `_TOPIC_HINTS` | «что умеешь / как спрашивать» | help_chat | **инструмент** или RAG |
| `field` | regex | «прими объём» | field_intake | **инструмент** (есть: `field`) |
| `decision` | keyword | «зафиксируй решение» | decision_service | **инструмент** (новый) |
| `memory` | «запомни/забудь» | заметки | memory_service | **инструмент** (новый) |
| **clause_lookup** | `CLAUSE_RE` «пункт N.N / СП X» | прямой вынос пункта норматива | — | **инструмент** (полезный — точечный fetch пункта) |
| **table_query** | `TABLE_QUERY_TOKENS` substring | «сумма/итого по таблице» | table_sql/table_query | **инструмент** (есть: `table_agg`) — костыль: substring |
| **mail** | `MAIL_QUERY_TOKENS` + substring-фильтр | вопросы про переписку | mail_query | **RAG по письмам** (чиню отдельным агентом) + навигация-инструмент |
| `maybe_autonote` | факт≠вопрос | авто-сохранение фактов | memory | решение роутера (или оставить как тихий side-effect) |
| **wants_model** | «своими словами…» | страховка-побег к модели | sovushka_tone | МООТ при RAG-default (нет гейта — нечего обходить) |
| **object_estimate** | `_OBJECT_WORDS/_MATERIAL_WORDS` + template-match | «дай смету на <объект>» | object_templates.yaml | **RAG/LLM-рассуждение о составе работ** над корпусом норм + инструменты-калькуляторы; НЕ шаблон-пресет |
| **answer_form** | keyword → форма/`max_tokens` | форма/длина ответа | — | низкий приоритет; можно оставить или отдать LLM (длину уже снял) |

## Что уже есть (цель миграции)

`agent_router_service.py` (Ярус 2) — `_TOOLS` каталог + LLM выбирает один инструмент по описаниям →
исполняет детерминированный handler. **Уже умеет 6:** asbuilt, les_md, project_registry, field, task,
preset (+ `none`). Это ровно «RAG, которому помогают инструменты» — но выключено флагом и как fallback.
Плюс 14→16 MCP-инструментов (`tools/les_mcp_server.py`): price_lookup, kac, stesnennost, lsr_assemble,
gesn_expand, table_agg, glossary, bor, project_summary, form_generate, smeta_save, journal_append, …

## Целевой поток

```
вопрос → agent_router (LLM): нужен ли ИНСТРУМЕНТ?
   ├─ да  → исполнить детерминированный инструмент (цена/гэсн/лср/кац/стеснённость/таблица/память/задача/решение/реестр/…)
   │        числа/даты/агрегации/команды — здесь, детерминированно (ADR-11)
   └─ нет → RAG retrieve + LLM-ответ из корпуса с цитатами   ← DEFAULT
```

Никаких keyword-гейтов на ПОНИМАНИЕ. Substring/regex-триггеры удаляются; их работу берёт роутер
(LLM решает «это запрос цены → tool price_lookup») и RAG (всё остальное).

## План миграции (поэтапно, golden 16/16 на каждом шаге)

1. **Дозарегистрировать инструменты в agent_router**: glossary, smeta-набор (price/kac/stesnennost/
   lsr_assemble/object_estimate), help, table_agg, clause, memory, decision. Описания — чёткие (LLM
   выбирает по ним).
2. **Включить agent_router основным** (снять флаг-fallback; поднять ПЕРЕД каскадом). Замер латентности/
   стоимости (роутер = +1 дешёвый LLM-вызов, `max_tokens=40`).
3. **Демоутить keyword-гейты по одному** (glossary → smeta → help → table → clause → mail → registry/
   asbuilt/les_md/preset/task/field/decision/memory): убирать перехват, проверять что роутер ловит
   намерение и зовёт тот же инструмент. На каждом шаге: golden 16/16 + живой пруф на 3 ПЕРЕФОРМУЛИРОВКАХ
   (главный тест — не ломается «шаг в сторону»).
4. **route_query → default rag**: убрать keyword-классификацию channel; table/mail/field — через инструменты.
5. **object_estimate**: перевести с шаблон-матча на RAG/LLM-рассуждение о составе (отдельный заход).
6. **Снести мёртвое**: wants_model (моот), лишние `_WORDS/_TOKENS/_RE`, `_det_channels` каскад.

## Гейты безопасности
- Доменный golden `tools/rag_golden_set.py` = 16/16 ДО и ПОСЛЕ каждого шага.
- Тест на ПЕРЕФОРМУЛИРОВКИ (3 формулировки одного смысла → одинаково осмысленно) — анти-пресет-регресс.
- `make verify` зелёный; обратимость (флаги на время миграции).
- Команды (memory/task/decision) — проверить, что роутер не путает «запомни X» с вопросом про X.

## Риск, который держим в голове
Роутер добавляет 1 LLM-вызов на запрос (выбор инструмента). При недоверенном/медленном канале —
короткий таймаут + fallback в RAG, не вешать чат ([[local-bases-untrusted-channel]]). Локальная малая
модель (`max_tokens=40`) для роутинга — дёшево и быстро.
