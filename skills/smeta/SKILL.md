---
name: smeta
description: Use when working on LES estimating/сметы — pricing (ГЭСН/ФГИС ЦС/КАЦ), LSR assembly, РИМ-trace, Приложение № 4 form, object estimates, or any «цена/смета/ЛСР/ВОР/НР/СП» task. Numbers are computed by code (ADR-11), never by the LLM.
---

# Сметный модуль ЛЕС — operator/agent skill

Канон-поток и эталон — [docs/ALGO-smeta.md](../../docs/ALGO-smeta.md); карта модулей — [docs/MODULE_INDEX.md](../../docs/MODULE_INDEX.md)
(раздел «Смета»). **Числа считает КОД** (ADR-11, 0 LLM в расчёте); каждое число цитируемо и закрыто
тестом. Сквозной эталон: позиция **«Устройство обрешётки» ГЭСН12-01-034-02 @ 0.61 = 11813.04 ₽**;
смета 2× = 23626.08.

## Поток (объём → ВСЕГО)

```
ВОР (объём) → норма ГЭСН → ресурсы (расход×объём) → цены (ФГИС ЦС / КАЦ) →
ОЗП/ЭМ(машины+ЗПМ)/М → стеснённость(k) → НР/СП (от ФОТ) → Всего по позиции → свод по разделам →
[объектная смета: + непредвиденные 2% + НДС 20% → ВСЕГО]
```
Бухгалтерия позиции: прямые=ОЗП+ЭМ+М; ФОТ=ОЗП+ЗПМ; НР=ФОТ·нр%; СП=ФОТ·сп%; Всего=прямые+НР+СП.

## Чат-команды (детерминированно, 0 LLM)

| Хочу | Команда |
|---|---|
| цена ресурса по коду | `цена 91.05.01-017` |
| нужен ли КАЦ | `нужен ли КАЦ для <код>` |
| коэф. стеснённости | `коэффициент стеснённости для города` |
| собрать позицию от кода | `собери ГЭСН12-01-034-02 объём 0.61` |
| объектная смета из фразы | `дай смету на деревянный дом 100 м²` |

## Кирпичи (модуль → сервис → док)

| Кирпич | Сервис | Док |
|---|---|---|
| норма ГЭСН → ресурсы | `gesn_service` | [ALGO-gesn](../../docs/ALGO-gesn.md) |
| цена по коду (ФГИС ЦС) | `fgis_price_service` | [ALGO-fgis-price](../../docs/ALGO-fgis-price.md) |
| КАЦ (≥3 КП) | `kac_service` | [ALGO-kac](../../docs/ALGO-kac.md) |
| стеснённость | `stesnennost_service` | [ALGO-stesnennost](../../docs/ALGO-stesnennost.md) |
| НР/СП по виду работ | `nr_sp_service` | [ALGO-object-estimate](../../docs/ALGO-object-estimate.md) |
| сборка ЛСР + РИМ-трасса + форма Прил.4 | `lsr_assembly_service`, `rim_lsr_trace_service`, `rim_trace_xlsx_service` | [ALGO-lsr-assembly](../../docs/ALGO-lsr-assembly.md) |
| объектная смета (фраза→ВСЕГО) | `object_estimate_service` | [ALGO-object-estimate](../../docs/ALGO-object-estimate.md) |
| спецификация Ф9 → ВОР | `spec_to_bor_service` | [ALGO-spec-to-bor](../../docs/ALGO-spec-to-bor.md) |
| онтология понятий | `smeta_ontology_service` | [ALGO-smeta-ontology](../../docs/ALGO-smeta-ontology.md) |

API: `POST /api/lsr/{assemble,rim-trace,lsr-trace}[/export]`, `/api/prices/*`, `/api/kac/*`, `/api/bor/*`.
MCP: `les_lsr_assemble`, `les_price_lookup`, `les_kac`, `les_stesnennost`, `les_gesn_expand`.
Форма ЛСР = **Приложение № 4** к 421/пр (одно- и многопозиционная: разделы + итоги + «ВСЕГО по смете»).

## Правила (не нарушать)

- **Числа — код, не LLM.** LLM в лучшем случае парсит фразу; геометрия/нормы/цены/НР-СП/хвост — детерминированная арифметика. Источник цены различается честно: текущая ФГИС ЦС / база×индекс / КАЦ / явная / `missing` (не молчаливый 0).
- **Базы локально** (parquet); сеть (ФГИС ЦС) — узкий fallback по запросу ([[local-bases-untrusted-channel]]). Индекс для база×индекс — официально письма Минстроя ИФ/09 ([[minstroy-indices-source]], бэклог v0.26+).
- **Знание ≠ веса:** ставки НР/СП, коэффициенты, шаблоны объектов — в редактируемых `config/domain/*.yaml`, не в fine-tune.

## Честные границы

- Объектная смета: **два шаблона** — `wooden_house` (брус ИЖС) и `monolith_office` (монолит/офис), оба в `config/domain/object_templates.yaml`. Объект вне покрытых (каркас/ангар) → **честный отказ**, не выдумка. Расширение — добавить шаблон в yaml (данные, не логика).
- Базовые нормы из parquet несут материалы/машины, но не тариф ОЗП/ОТм у части норм → ОЗП=0 до загрузки тарифов (смета всё равно собирается на доступном). Машинист-агрегат без разряда → флаг «нет цены».
- Геометрия грубая (P = 4·√(S/N)); подбор кода нормы под произвольную работу ВОР — отдельный шаг.

## Расширить

- Новый тип объекта → шаблон в `config/domain/object_templates.yaml` (геометрия + позиции с кодами ГЭСН + work_kind).
- Норма не в базе → добор из ФГИС ЦС (`tools/gesn_bulk_import.py`, бесплатно) или импорт ГРАНД/НСИ (`tools/gesn_import.py`).
- Тесты-эталоны: `tests/test_gesn_service.py`, `test_lsr_assembly_service.py`, `test_rim_lsr_trace_service.py`, `test_rim_trace_xlsx.py` (gold 11813.04 / смета 23626.08). Меняешь расчёт — gold должен сойтись.
