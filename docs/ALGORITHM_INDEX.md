# Индекс алгоритмов ЛЕС

Статус проверен по коду и тестам 2026-07-23. Этот индекс отвечает на вопрос,
какие `docs/ALGO-*` являются текущим контрактом, а какие сохранены как решение
или tombstone. Подробности и формулы остаются в самих документах.

| Алгоритм | Статус | Основные точки входа | Проверка |
|---|---|---|---|
| [ALGO-asbuilt-intake.md](ALGO-asbuilt-intake.md) | active | `proxy/services/asbuilt_*`, `tools/asbuilt_extract.py` | `tests/test_asbuilt*` |
| [ALGO-context-memory.md](ALGO-context-memory.md) | active | `context_memory_service`, `dataset_memory_service` | `tests/test_context_memory_service.py`, `tests/test_dataset_memory_service.py` |
| [ALGO-electrical-schematics.md](ALGO-electrical-schematics.md) | active MVP | `electrical_schematic_service`, `electrical_materials_service` | `tests/test_electrical_*` |
| [ALGO-evidence-packet.md](ALGO-evidence-packet.md) | active | `evidence_packet_service`, `chat_evidence_application_service` | `tests/test_evidence_packet_service.py` |
| [ALGO-external-radar.md](ALGO-external-radar.md) | active | `external_radar_service`, `proxy/routers/external_radar.py` | `tests/test_external_radar*` |
| [ALGO-fgis-price.md](ALGO-fgis-price.md) | active | `fgis_price_service`, `fgis_price_fetch_service` | `tests/test_fgis_*`, `tests/test_price*` |
| [ALGO-gesn.md](ALGO-gesn.md) | active | `gesn_service`, `tools/gesn_*` | `tests/test_gesn_*` |
| [ALGO-harvest.md](ALGO-harvest.md) | active supporting loop | `harvest_service`, `tools/harvest_dataset.py` | `tests/test_harvest*` |
| [ALGO-kac.md](ALGO-kac.md) | active | `kac_service`, `kac_pdf_service` | `tests/test_kac_*` |
| [ALGO-les-md.md](ALGO-les-md.md) | active | `les_md_service`, `project_service` | `tests/test_les_md*` |
| [ALGO-lsr-assembly.md](ALGO-lsr-assembly.md) | active | `rim_lsr_trace_service`, `rim_trace_xlsx_service` | `tests/test_lsr_*`, `tests/test_rim_*` |
| [ALGO-mail-intake.md](ALGO-mail-intake.md) | active | `mail_registry_service`, `mail_sync_service`, Outlook sidecar | `make test-mail` |
| [ALGO-normcontrol.md](ALGO-normcontrol.md) | active | `normcontrol_service`, `doc_review_service` | `tests/test_normcontrol*`, `tests/test_doc_review*` |
| [ALGO-notebook-study.md](ALGO-notebook-study.md) | active | `notebook_study_service`, `notebook_service` | `tests/test_notebook_study_service.py` |
| [ALGO-object-estimate.md](ALGO-object-estimate.md) | historical tombstone | removed `object_estimate_service`; current route is `estimate_harness_service` | regression assertions in estimate/profile tests |
| [ALGO-pdf-ingestion.md](ALGO-pdf-ingestion.md) | active | `backend/converter.py`, PDF/source-map services | `tests/test_converter*`, `tests/test_project_pdf_*` |
| [ALGO-pdf-layout.md](ALGO-pdf-layout.md) | active | `backend/pdf_layout.py` | PDF layout/converter tests |
| [ALGO-rag-best-practices.md](ALGO-rag-best-practices.md) | canonical invariant | named `dense + bm25_sparse`, native RRF, rerank, context expansion | `make test-rag-core` |
| [ALGO-routing.md](ALGO-routing.md) | active | `profile_resolver`, `query_router`, `agent_router_service` | profile/router tests |
| [ALGO-smeta-ontology.md](ALGO-smeta-ontology.md) | active | `smeta_ontology_service`, `config/domain/smeta_ontology.yaml` | ontology/smeta tests |
| [ALGO-smeta.md](ALGO-smeta.md) | canonical flow | `smeta_chat_application_service`, `smeta_agent_runner_service`, smeta core | smeta profile |
| [ALGO-spec-to-bor.md](ALGO-spec-to-bor.md) | active | `spec_to_bor_service` | `tests/test_spec_to_bor_service.py` |
| [ALGO-stesnennost.md](ALGO-stesnennost.md) | active | `stesnennost_service`, LSR router | stesnennost/LSR tests |
| [ALGO-table-query.md](ALGO-table-query.md) | active | `table_query_service`, Parquet readers | `tests/test_table_query_service.py` |
| [ALGO-tool-harness.md](ALGO-tool-harness.md) | active | `tool_harness_service`, `tools/les_tool_harness.py` | tool-harness tests |
| [ALGO-vl-lora.md](ALGO-vl-lora.md) | decision record | benchmark method; LoRA is not the current route | benchmark evidence only |
| [ALGO-workflow-plan.md](ALGO-workflow-plan.md) | active | `workflow_plan_service` | workflow-plan tests |

## Инварианты, проверенные сквозным аудитом

- Профессиональный выбор нормы, аналога, покрытия и ресурсного действия остаётся
  за моделью; код показывает карточки, валидирует ссылки/единицы и считает.
- Production RAG использует одну contract-versioned named collection:
  `dense + bm25_sparse → native RRF → rerank → parent/context expansion`.
- Навигационная карта, notebook и registry не являются доказательством сами по себе.
- Числа из таблиц, ГЭСН/РИМ и журналов считает typed code по полному набору строк.
- `MISSING`, конфликт и неполная область проверки не превращаются в `pass` или ноль.

`make docs-check` гарантирует наличие всех алгоритмов в этом индексе и валидность
ссылок; предметную корректность по-прежнему подтверждают профильные тесты и живые
приёмочные сценарии.
