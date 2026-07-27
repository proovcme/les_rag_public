# Индекс skills

Статус проверен 2026-07-23. Skill определяет reasoning discipline модели; код
реализует чтение, инструменты, валидацию, вычисления и сохранение трассы.

| Skill | Область | Статус и граница |
|---|---|---|
| [`SKILL.md`](../SKILL.md) | эксплуатационный канон LES | active; runtime, public demo, сборка, гейты и guardrails |
| [`skills/rag_search/SKILL.md`](../skills/rag_search/SKILL.md) | инженерный поиск | active; модель связывает evidence, навигация не подменяет факт |
| [`skills/smeta/SKILL.md`](../skills/smeta/SKILL.md) | сметный агент | canonical; модель выбирает нормы/аналоги/resources, код валидирует и считает |
| [`skills/normcontrol/SKILL.md`](../skills/normcontrol/SKILL.md) | нормоконтроль | active; computed checks отделены от инженерного замечания |
| `products/artel/skills/agnostis/SKILL.md` | legacy entrypoint ARTEL | находится в pinned Agnostis submodule |
| `products/artel/skills/revit-api-operator/SKILL.md` | live Revit operator | модель выбирает действие по evidence; mutation только через validation/transaction/safety contract |
| `products/artel/skills/revit-family-generator/SKILL.md` | генератор Revit family | model-owned specification; missing dimensions не выводятся кодом |
| `products/artel/skills/revit-family/SKILL.md` | family quality/catalog | отдельный продукт ARTEL; LES использует только integration boundary |

## Общие запреты

- Skill не хранит объектные ответы, тестовые суммы или скрытый selector.
- Ranking, regex и typed reader не принимают профессиональное решение за модель.
- Внешний ключ не сохраняется в skill, документации, `.env` публичного demo или
  payload ответа; BYOK относится к одной пользовательской сессии.
- Изменение skill требует профильного regression test и обновления карты модуля.
