# Карта исполняемого кода ЛЕС

> Сгенерировано `tools/code_runtime_map.py`. Не редактировать вручную.

Это консервативная статическая карта импортов и зарегистрированных FastAPI-маршрутов. Статус `DORMANT_CANDIDATE` означает только отсутствие доказанного пути от продуктовых entrypoint, явного runtime-helper или теста; он **не является доказательством мёртвого кода**.

Полный построчный inventory находится в `docs/generated/code_runtime_map.json`.

## Статусы

| Статус | Что доказано |
| --- | --- |
| PRODUCT_REACHABLE | Есть статический путь от боевой точки входа |
| RUNTIME_SUPPORT | Явно перечислен как отдельный helper Windows runtime |
| TEST_OR_TOOL_ONLY | Тест, служебный скрипт или достигается только из такого кода |
| DORMANT_CANDIDATE | Статический потребитель не найден; требуется ручная проверка |

## Сводка

| Метрика | Значение |
| --- | --- |
| Python-файлов под git | 1084 |
| Строк Python | 380529 |
| PRODUCT_REACHABLE | 370 |
| RUNTIME_SUPPORT | 11 |
| TEST_OR_TOOL_ONLY | 702 |
| DORMANT_CANDIDATE | 1 |
| Зарегистрированных API-маршрутов | 340 |
| Ошибок разбора | 0 |

## Крупнейшие продуктовые модули

| Файл | Строк | Прямых потребителей |
| --- | --- | --- |
| proxy/services/chat_evidence_application_service.py | 12725 | 44 |
| proxy/smeta_core/document_workflow.py | 9530 | 20 |
| sovushka/pages/chat.py | 7792 | 7 |
| proxy/routers/chat.py | 4797 | 47 |
| backend/qdrant_adapter.py | 4580 | 29 |
| sovushka/uikit/tokens.py | 4290 | 2 |
| sovushka/pages/documents.py | 3976 | 3 |
| proxy/routers/datasets.py | 3787 | 16 |
| sovushka/styles.py | 3301 | 3 |
| proxy/services/rim_lsr_trace_service.py | 3057 | 32 |
| sovushka/pages/samovar.py | 2966 | 3 |
| proxy/services/workbook_research_job_service.py | 2856 | 26 |
| proxy/services/smeta_chat_adapter_service.py | 2461 | 17 |
| proxy/services/dataset_memory_service.py | 2288 | 7 |
| proxy/services/lsr_norm_quality_gate_service.py | 2233 | 10 |
| mlx_host.py | 2216 | 2 |
| proxy/services/estimate_harness_service.py | 2052 | 4 |
| proxy/smeta_core/norm_browser.py | 1799 | 16 |
| proxy/services/project_pdf_table_service.py | 1653 | 4 |
| proxy/smeta_core/rim_session.py | 1645 | 6 |
| sovushka/pages/diag.py | 1605 | 3 |
| proxy/services/lsr_workbook_adapter_service.py | 1595 | 16 |
| proxy/services/checklist_review_service.py | 1518 | 2 |
| proxy/routers/mail.py | 1476 | 3 |
| proxy/services/cad_bim_graph.py | 1425 | 8 |
| proxy/services/retrieval_service.py | 1409 | 10 |
| proxy/services/tool_harness_service.py | 1408 | 13 |
| proxy/services/rim_agent_turn_service.py | 1286 | 2 |
| proxy/services/smeta_artifact_service.py | 1236 | 3 |
| proxy/services/attachment_source_catalog_service.py | 1209 | 19 |

## Сметный монолит: фактические потребители

### `proxy/smeta_core/document_workflow.py`

Статус: `PRODUCT_REACHABLE`; строк: 9530.

| Импортируемый символ | Потребители |
| --- | --- |
| `MAPPING_VALIDATION_CONTRACT_VERSION` | `proxy/services/rim_mapping_progress_service.py`<br>`tests/test_rim_mapping_progress.py` |
| `Progress` | `proxy/services/smeta_agent_runner_service.py` |
| `SmetaNormToolSession` | `proxy/services/smeta_agent_runner_service.py`<br>`tests/test_flexible_code_resolver.py`<br>`tests/test_smeta_catalog_query_derive.py`<br>`tests/test_smeta_memory_isolation.py` |
| `_batch_norm_tools` | `proxy/services/smeta_agent_runner_service.py`<br>`tests/test_smeta_core.py` |
| `_mapping_output_schema` | `proxy/services/smeta_agent_runner_service.py` |
| `_nested_array_transport` | `tests/test_smeta_core.py` |
| `_norm_card_for_model` | `tests/test_smeta_core.py` |
| `_normalize_mapping_row_transport` | `tests/test_smeta_core.py` |
| `_one_item_tool_transport` | `tests/test_smeta_core.py` |
| `_resolve_bounded_catalog_query` | `tests/test_smeta_catalog_query_derive.py` |
| `_resolve_norm_code_transport` | `tests/test_smeta_core.py` |
| `_resolve_selected_node_id` | `tests/test_smeta_catalog_query_derive.py` |
| `_run_batch_norm_agent` | `proxy/services/rim_agent_turn_service.py` |
| `_run_global_norm_review` | `proxy/services/rim_agent_turn_service.py`<br>`tools/smeta_agent_benchmark.py` |
| `_run_native_norm_agent` | `tools/smeta_agent_benchmark.py` |
| `_tool_arguments` | `tests/test_smeta_core.py` |
| `_tool_array_argument` | `tests/test_smeta_core.py` |
| `_tool_bool` | `tests/test_smeta_core.py` |
| `batch_norm_tools` | `proxy/services/rim_agent_action_service.py`<br>`tools/smeta_model_quality_benchmark.py` |
| `bounded_catalog_query_from_work_features` | `tests/test_smeta_catalog_query_derive.py` |
| `finalize_locked_mapping_revision` | `proxy/routers/chat.py` |
| `resolve_extracted_norm_code_flexible` | `tests/test_flexible_code_resolver.py` |
| `run_vor_document_workflow` | `proxy/services/smeta_chat_application_service.py`<br>`tools/smeta_agent_benchmark.py`<br>`tools/smeta_document_local_run.py`<br>`tools/smeta_model_quality_benchmark.py`<br>`tools/smeta_stability_ab_run.py` |

## Кандидаты на проверку

| Файл | Строк | Почему только кандидат |
| --- | --- | --- |
| sovushka/pages/mail.py | 626 | Нет доказанного статического пути; проверить dynamic/subprocess/external use |

## Ограничения

- Карта видит обычные Python-импорты и декораторы `APIRouter`, но не доказывает фактическую частоту вызова.
- Строковые импорты, plugin discovery, subprocess и внешние entrypoint требуют ручной проверки.
- Удаление возможно только после отдельного поиска потребителей, теста и проверки установленного Windows runtime.
