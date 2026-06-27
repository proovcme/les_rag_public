# ALGO-workflow-plan — единый план работы с информацией

## Назначение

`workflow_plan_v1` — общий машинный скелет ответа ЛЕС: какой workflow выполнялся, какие входы нужны,
какие evidence/claims собраны, чего не хватает, что заблокировано и кто финализирует результат.

Это не новый движок расчёта и не замена модулей. Это тонкий контракт поверх уже существующих smeta,
normcontrol, RAG, table, mail и future checklist workflows, чтобы доменные модули не росли отдельными
ветками с разными словами для одного и того же состояния.

## Точки входа

- `proxy/services/workflow_plan_service.py` — сборка `workflow_plan_v1` из payload ответа.
- `proxy/services/answer_contract_service.py::decorate_payload()` — добавляет `scenario`,
  `answer_contract`, `answer_contract_check`, затем `workflow_plan` ко всем chat payload.
- `proxy/services/doc_review_service.py::review_to_json()` — добавляет `workflow_plan` в JSON
  нормоконтроля напрямую, чтобы отчёты и чат имели один контракт.

## Контракт

Ключевые поля:

- `workflow_id` — `object_estimate`, `normcontrol`, `grounded_rag`, `table_query`, `mail_query`, …
- `contract_id` — ожидаемая форма ответа (`estimate_table_v1`, `findings_table_v1`, …).
- `status` — `complete`, `preliminary`, `needs_data`, `needs_review`, `blocked`, `planned`.
- `finality` — `final_for_current_sources`, `human_required`, `not_final`, `unknown`.
- `required_inputs` — что нужно этому workflow в принципе.
- `missing_inputs` — чего не хватило в этом конкретном ответе.
- `evidence_policy` — какой тип доказательности обязателен.
- `claim_summary` — count/status по defense-claims и normalized remarks.
- `source_summary` — счётчики sources/source_map/trace.
- `blockers` и `next_actions` — действия оператора/инженера.

## Инварианты

- План не отвечает пользователю и не запускает инструменты.
- План не делает weak evidence сильным: если модуль вернул `manual_required`, план пишет
  `needs_review/human_required`.
- План не превращает ориентир в финальную смету: `not_defensible`, `computed_assumed` и blockers остаются
  `preliminary` или `needs_review`.
- План одинаково применим к смете, нормоконтролю, чек-листам, таблицам и RAG.

## Зачем

Смета и нормоконтроль перестают изобретать разные payload-языки. Следующие слои могут смотреть не на
частный модуль, а на общий контракт:

```
source/profile → workflow_plan → evidence claims → answer/report/UI
```

Это первый маленький шаг к единому механизму работы с информацией без большого workflow-движка.

## Тесты

- `tests/test_answer_contract_service.py` — chat payload получает `workflow_plan`, claim summary,
  missing inputs и next actions.
- `tests/test_doc_review_gost_21_101_2026.py` — normcontrol JSON содержит `workflow_plan_v1`.
- `tests/test_smeta_chat_service.py` — object-estimate после chat-декорации получает общий план.
