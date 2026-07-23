# LES external integration surface

Дата снимка: 2026-07-14
Ветка/контекст: `main`
Назначение: единая карта HTTP API, bridge API, MLX API и MCP-инструментов, которые можно использовать для внешних подключений и интеграций.

Источник снимка:
- FastAPI proxy routes: `proxy/routers/*.py`, `proxy/app.py`
- Sovushka bridge/runtime routes: `sovushka/lite_bridge.py`, `sovushka/m5_display.py`
- MLX host routes: `mlx_host.py`
- MCP: `tools/les_mcp_server.py --list`

Важно: это current-code inventory. Старых `/api/speckle/*` в коде нет; актуальная CAD/BIM поверхность сейчас `/api/cad-bim/*`.

## Base URLs

| Контур | URL | Для чего |
|---|---|---|
| Local proxy API | `http://127.0.0.1:8050` | Основной FastAPI proxy, все `/api/*` |
| Sovushka UI / bridge | `http://127.0.0.1:8051` | UI, `/lite-api/*`, `/lite-runtime/*`, CAD/BIM viewer |
| ZeroTier UI / bridge | `http://10.195.146.98:8051` | Доверенный доступ из ZeroTier |
| Public site | `https://les.ovc.me` | Статический лендинг и `/updates/*`; живой LES API/UI публично закрыт |
| MLX host | `http://127.0.0.1:8080` | OpenAI-compatible локальная генерация/embeddings/rerank/validate |
| Qdrant | `http://127.0.0.1:6333` | Нативный Qdrant HTTP API; не LES-router |
| MCP stdio | `uv run python tools/les_mcp_server.py` | Инструменты LES наружу для MCP-клиентов |

## Auth and bridge rules

- Direct proxy `/api/*`: обычно нужен `X-API-Key` или `Authorization: Bearer ...`, либо trusted loopback/ZeroTier/proxy.
- Public bridge `/lite-api/{path}` maps to proxy `/api/{path}`. Example: `POST /lite-api/chat` -> `POST /api/chat`.
- `/lite-api/auth/verify` and `/lite-api/auth/trust` are public bridge exceptions.
- `/lite-runtime/*` is local/trusted only.
- Admin/root-admin endpoints are dangerous for runtime/index/backup/delete flows; expose them only on trusted networks.
- MLX host is intended as internal service. `/v1/*` is OpenAI-compatible, but should not be public without an explicit gateway/auth layer.

## Primary integration flows

| Flow | Preferred API |
|---|---|
| Chat / RAG answer | `POST /api/chat` or `POST /api/chat/stream`; public bridge `POST /lite-api/chat` |
| Upload attachment for next chat turn | `POST /api/rag/attach` |
| Dataset CRUD/index/upload | `/api/rag/datasets*`, `/api/rag/upload*`, `/api/rag/sync*`, `/api/rag/index-external`, `/api/rag/cloud-drives*` |
| Source/document reading | `/api/documents/*`, `/api/rag/file/*`, `/api/rag/tree` |
| Tool execution from external UI/agent | `/api/tools/registry`, `/api/tools/shortlist`, `/api/tools/call` |
| CAD/BIM viewer/import/context | `/api/cad-bim/*`, `/les/cad-bim-viewer` |
| Smeta/LSR/KAC/prices | `/api/lsr/*`, `/api/prices/*`, `/api/kac/*`, MCP `les_*` smeta tools |
| Normcontrol/doc-review | `/api/normcontrol/*`, `/api/doc-review/*` |
| Local LLM compatible API | MLX `/v1/chat/completions`, `/v1/embeddings`, `/v1/rerank` |

## Proxy HTTP API inventory

### Auth

| Method | Path | Handler |
|---|---|---|
| `POST` | `/api/auth/verify` | `auth_verify` |
| `GET` | `/api/auth/trust` | `auth_trust` |
| `GET` | `/api/auth/keys` | `auth_list_keys` |
| `POST` | `/api/auth/keys` | `auth_create_key` |
| `POST` | `/api/auth/keys/toggle` | `auth_toggle_key` |
| `POST` | `/api/auth/keys/reset-device` | `auth_reset_device` |
| `DELETE` | `/api/auth/keys/{key_value}` | `auth_delete_key` |
| `POST` | `/api/auth/keys/delete` | `auth_delete_key_body` |

### Runtime, status, logs, jobs

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/health` | `health` |
| `GET` | `/api/version` | `version` |
| `GET` | `/api/status` | `get_status` |
| `GET` | `/api/metrics` | `get_metrics` |
| `GET` | `/api/mode` | `get_mode` |
| `POST` | `/api/mode` | `set_mode` |
| `GET` | `/api/indexing-mode` | `get_indexing_mode` |
| `POST` | `/api/indexing-mode` | `set_indexing_mode` |
| `GET` | `/api/live` | `live_stream` |
| `POST` | `/api/warmup` | `warmup_models` |
| `GET` | `/api/runtime/dispatcher/status` | `runtime_dispatcher_status` |
| `POST` | `/api/runtime/dispatcher/reindex/start` | `runtime_dispatcher_reindex_start` |
| `POST` | `/api/runtime/dispatcher/reindex/pause` | `runtime_dispatcher_reindex_pause` |
| `POST` | `/api/runtime/dispatcher/reindex/resume` | `runtime_dispatcher_reindex_resume` |
| `GET` | `/api/runtime/dispatcher/route-changes/status` | `runtime_dispatcher_route_changes_status` |
| `POST` | `/api/runtime/dispatcher/route-changes/start` | `runtime_dispatcher_route_changes_start` |
| `POST` | `/api/runtime/dispatcher/route-changes/pause` | `runtime_dispatcher_route_changes_pause` |
| `POST` | `/api/runtime/dispatcher/mlx/unload` | `runtime_dispatcher_mlx_unload` |
| `GET` | `/api/backup/status` | `get_backup_status` |
| `POST` | `/api/backup/create` | `create_backup` |
| `POST` | `/api/backup/delete` | `delete_backup` |
| `GET` | `/api/backup/archives` | `list_backup_archives` |
| `POST` | `/api/backup/restore` | `restore_backup` |
| `GET` | `/api/jobs/summary` | `get_jobs_summary` |
| `GET` | `/api/jobs` | `get_jobs` |
| `GET` | `/api/logs/recent` | `recent_logs` |
| `GET` | `/api/logs/stream` | `log_stream` |
| `GET` | `/api/diag` | `run_diagnostics` |

### Chat and model-facing API

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/commands` | `list_chat_commands` |
| `POST` | `/api/chat` | `chat` |
| `POST` | `/api/chat/stream` | `chat_stream` |
| `GET` | `/api/chat/history` | `get_chat_history` |
| `GET` | `/api/chat/sessions` | `get_chat_sessions` |
| `GET` | `/api/chat/memory/{session_id}` | `get_chat_memory` |
| `POST` | `/api/chat/history/{history_id}/feedback` | `save_chat_feedback` |
| `GET` | `/api/chat/learning` | `get_learning_history` |
| `GET` | `/api/smeta-artifacts/download` | `smeta_artifact_download` |
| `POST` | `/api/rerank` | `rerank_direct` |

### Scope and prompts

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/scope/options` | `scope_options_endpoint` |
| `POST` | `/api/scope/resolve` | `scope_resolve_endpoint` |
| `GET` | `/api/prompts` | `list_prompts` |
| `PATCH` | `/api/prompts/{prompt_key:path}` | `update_prompt` |
| `DELETE` | `/api/prompts/{prompt_key:path}` | `reset_prompt` |

### RAG datasets, indexing, uploads, sources

| Method | Path | Handler |
|---|---|---|
| `POST` | `/api/search` | `search` |
| `GET` | `/api/rag/datasets` | `list_datasets` |
| `POST` | `/api/rag/datasets` | `create_dataset` |
| `DELETE` | `/api/rag/datasets/{dataset_id}` | `delete_dataset` |
| `DELETE` | `/api/rag/datasets` | `delete_all_datasets` |
| `GET` | `/api/rag/documents` | `list_documents` |
| `POST` | `/api/rag/retrieve-debug` | `retrieve_debug` |
| `PATCH` | `/api/rag/datasets/{dataset_id}/sensitivity` | `set_dataset_sensitivity` |
| `PATCH` | `/api/rag/datasets/{dataset_id}/group` | `set_dataset_group` |
| `GET` | `/api/rag/datasets/{dataset_id}/profile` | `dataset_context_profile` |
| `POST` | `/api/rag/datasets/{dataset_id}/profile/refresh` | `refresh_dataset_context_profile` |
| `PATCH` | `/api/rag/datasets/{dataset_id}/profile/guidance` | `update_dataset_operator_guidance` |
| `POST` | `/api/rag/datasets/profiles/warmup` | `warmup_dataset_context_profiles` |
| `POST` | `/api/rag/datasets/profiles/benchmark` | `benchmark_dataset_context_profiles` |
| `GET` | `/api/rag/datasets/{dataset_id}/extraction-status` | `extraction_status_endpoint` |
| `POST` | `/api/rag/datasets/{dataset_id}/repair` | `repair_dataset` |
| `POST` | `/api/rag/datasets/{dataset_id}/reconcile` | `reconcile_dataset_endpoint` |
| `POST` | `/api/rag/datasets/{dataset_id}/extract-body/dry-run` | `extract_body_dry_run` |
| `POST` | `/api/rag/datasets/{dataset_id}/extract-body/write` | `extract_body_write` |
| `GET` | `/api/rag/graph/edges` | `graph_reference_edges` |
| `GET` | `/api/rag/graph/full` | `graph_full` |
| `GET` | `/api/rag/sources` | `list_sources` |
| `GET` | `/api/rag/smart-plan` | `smart_plan` |
| `GET` | `/api/rag/watch/status` | `folder_watch_status` |
| `GET` | `/api/rag/watch/reindex-plan` | `folder_reindex_plan` |
| `POST` | `/api/rag/watch/scan` | `folder_watch_scan` |
| `POST` | `/api/rag/sync-smart` | `sync_smart` |
| `POST` | `/api/rag/external/intake-plan` | `external_intake_plan` |
| `POST` | `/api/rag/index-external` | `index_external` |
| `POST` | `/api/rag/external/check` | `check_external_dataset` |
| `POST` | `/api/rag/external/sync` | `sync_external_dataset` |
| `GET` | `/api/rag/browse-external` | `browse_external` |
| `GET` | `/api/rag/cloud-drives` | `cloud_drives` |
| `POST` | `/api/rag/cloud-drives/list` | `cloud_drive_list` |
| `POST` | `/api/rag/cloud-drives/sync` | `cloud_drive_sync` |
| `POST` | `/api/rag/sync/{folder}` | `sync_folder` |
| `POST` | `/api/rag/parse-batch/{dataset_id}` | `parse_dataset_batch` |
| `POST` | `/api/rag/parse-scheduler` | `parse_scheduler` |
| `POST` | `/api/rag/upload/{dataset_id}` | `upload_file` |
| `POST` | `/api/rag/attach` | `attach_chat_file` |
| `POST` | `/api/rag/upload-smart` | `upload_file_smart` |
| `GET` | `/api/rag/tree` | `rag_tree` |
| `GET` | `/api/rag/file/text` | `rag_file_text` |
| `GET` | `/api/rag/file/raw` | `rag_file_raw` |

### Documents, notebooks, service sources

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/documents/datasets` | `document_datasets` |
| `GET` | `/api/documents/datasets/{dataset_id}/documents` | `dataset_documents` |
| `GET` | `/api/documents/by-id/{doc_id}` | `document_by_id` |
| `GET` | `/api/documents/by-id/{doc_id}/chunks` | `document_chunks_by_id` |
| `GET` | `/api/documents/datasets/{dataset_id}/chunks/{doc_name:path}` | `document_chunks` |
| `GET` | `/api/documents/search` | `document_search` |
| `POST` | `/api/notebooks/warmup` | `warmup_notebooks` |
| `GET` | `/api/notebooks/{dataset_id}` | `dataset_notebook` |
| `GET` | `/api/notebooks/{dataset_id}/memory` | `dataset_typed_memory` |
| `POST` | `/api/notebooks/{dataset_id}/memory/refresh` | `refresh_dataset_typed_memory` |
| `POST` | `/api/notebooks/{dataset_id}/memory/read` | `read_dataset_memory` |
| `GET` | `/api/service-sources` | `list_service_sources` |
| `GET` | `/api/service-sources/notebooks` | `list_service_source_notebooks` |
| `GET` | `/api/service-sources/{source_id}` | `get_service_source` |
| `POST` | `/api/service-sources/{source_id}/process` | `process_source` |

### Tools API

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/tools/registry` | `tool_registry` |
| `POST` | `/api/tools/shortlist` | `tool_shortlist` |
| `POST` | `/api/tools/call` | `tool_call` |
| `GET` | `/api/tools/filesystem/roots` | `filesystem_roots` |
| `GET` | `/api/tools/filesystem/list` | `filesystem_list` |

### CAD/BIM, graph, ontology, diff

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/cad-bim/graph/summary` | `cad_bim_graph_summary` |
| `GET` | `/api/cad-bim/imports` | `cad_bim_imports` |
| `GET` | `/api/cad-bim/source` | `cad_bim_source` |
| `GET` | `/api/cad-bim/element` | `cad_bim_element_context` |
| `GET` | `/api/cad-bim/highlight` | `cad_bim_get_highlight` |
| `POST` | `/api/cad-bim/highlight` | `cad_bim_set_highlight` |
| `POST` | `/api/cad-bim/import` | `cad_bim_import` |
| `GET` | `/api/diff/cad-bim/imports` | `cad_bim_imports` |
| `GET` | `/api/diff/cad-bim` | `cad_bim_diff` |
| `POST` | `/api/diff/text` | `text_diff` |
| `GET` | `/api/ontology/backbone` | `ontology_backbone` |
| `GET` | `/api/ontology/elements` | `ontology_elements` |
| `GET` | `/api/ontology/lbs` | `ontology_lbs` |
| `GET` | `/api/ontology/containers` | `containers_list` |
| `GET` | `/api/ontology/cde-summary` | `containers_cde_summary` |
| `POST` | `/api/ontology/containers` | `containers_register` |
| `POST` | `/api/ontology/containers/state` | `containers_set_state` |
| `POST` | `/api/ontology/containers/supersede` | `containers_supersede` |
| `GET` | `/api/edges` | `edges_list` |
| `GET` | `/api/edges/for` | `edges_for` |
| `POST` | `/api/edges/backfill` | `edges_backfill` |

### Projects, decisions, estimates

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/projects` | `projects_list` |
| `POST` | `/api/projects` | `projects_create` |
| `GET` | `/api/projects/{project_id}` | `projects_get` |
| `GET` | `/api/projects/{project_id}/dossier` | `projects_dossier` |
| `PATCH` | `/api/projects/{project_id}` | `projects_status` |
| `DELETE` | `/api/projects/{project_id}` | `projects_delete` |
| `POST` | `/api/projects/{project_id}/links` | `projects_link` |
| `GET` | `/api/projects/{project_id}/links` | `projects_links` |
| `DELETE` | `/api/projects/{project_id}/links` | `projects_unlink` |
| `GET` | `/api/decisions` | `decisions_list` |
| `GET` | `/api/decisions/{decision_id}` | `decisions_get` |
| `POST` | `/api/decisions` | `decisions_create` |
| `PATCH` | `/api/decisions/{decision_id}` | `decisions_status` |
| `POST` | `/api/decisions/{new_id}/supersedes/{old_id}` | `decisions_supersede` |
| `GET` | `/api/estimates/{project_id}` | `estimates_list` |
| `GET` | `/api/estimates/item/{estimate_id}` | `estimate_get` |
| `POST` | `/api/estimates/{project_id}/import` | `estimate_import` |

### Smeta, BOR, prices, KAC, LSR

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/bor/reconcile` | `reconcile_preview` |
| `POST` | `/api/bor/reconcile/generate` | `reconcile_generate` |
| `GET` | `/api/bor/reconcile/download` | `reconcile_download` |
| `GET` | `/api/bor/{dataset_id}/preview` | `bor_preview` |
| `POST` | `/api/bor/{dataset_id}/generate` | `bor_generate` |
| `GET` | `/api/bor/{dataset_id}/download` | `bor_download` |
| `GET` | `/api/bor/{dataset_id}/from-spec` | `spec_bor_preview` |
| `POST` | `/api/bor/{dataset_id}/from-spec/generate` | `spec_bor_generate` |
| `GET` | `/api/bor/{dataset_id}/from-spec/download` | `spec_bor_download` |
| `GET` | `/api/bor/{dataset_id}/plan-fact` | `plan_fact_preview` |
| `POST` | `/api/bor/{dataset_id}/plan-fact/generate` | `plan_fact_generate` |
| `GET` | `/api/bor/{dataset_id}/plan-fact/download` | `plan_fact_download` |
| `GET` | `/api/prices/books` | `prices_books` |
| `GET` | `/api/prices/lookup` | `prices_lookup` |
| `GET` | `/api/prices/search` | `prices_search` |
| `POST` | `/api/prices/import` | `prices_import` |
| `GET` | `/api/prices/sources/subjects` | `prices_sources_subjects` |
| `GET` | `/api/prices/sources/periods` | `prices_sources_periods` |
| `POST` | `/api/prices/update` | `prices_update` |
| `GET` | `/api/prices/needs` | `prices_needs` |
| `POST` | `/api/kac/analyze` | `kac_analyze` |
| `POST` | `/api/kac/lsr-lines` | `kac_lsr_lines` |
| `POST` | `/api/kac/generate` | `kac_generate` |
| `GET` | `/api/kac/download` | `kac_download` |
| `GET` | `/api/kac/needs` | `kac_needs` |
| `GET` | `/api/lsr/stesnennost/conditions` | `stesn_conditions` |
| `POST` | `/api/lsr/stesnennost/apply` | `stesn_apply` |
| `GET` | `/api/lsr/gesn` | `gesn_list` |
| `GET` | `/api/lsr/gesn/{code}/expand` | `gesn_expand` |
| `POST` | `/api/lsr/assemble` | `lsr_assemble` |
| `POST` | `/api/lsr/rim-trace` | `lsr_rim_trace` |
| `POST` | `/api/lsr/rim-trace/export` | `lsr_rim_trace_export` |
| `POST` | `/api/lsr/lsr-trace` | `lsr_multi_trace` |
| `POST` | `/api/lsr/lsr-trace/from-rows` | `lsr_multi_trace_from_rows` |
| `POST` | `/api/lsr/lsr-trace/export` | `lsr_multi_trace_export` |
| `POST` | `/api/lsr/lsr-trace/from-rows/export` | `lsr_multi_trace_from_rows_export` |
| `POST` | `/api/lsr/export` | `lsr_export` |
| `GET` | `/api/lsr/download` | `lsr_download` |

### Normcontrol, doc-review, verify, forms

| Method | Path | Handler |
|---|---|---|
| `POST` | `/api/normcontrol/{dataset_id}/run` | `normcontrol_run` |
| `GET` | `/api/normcontrol/{dataset_id}/download` | `normcontrol_download` |
| `GET` | `/api/doc-review/rulepacks` | `doc_review_rulepacks` |
| `POST` | `/api/doc-review/{dataset_id}/run` | `doc_review_run` |
| `GET` | `/api/doc-review/{dataset_id}/download` | `doc_review_download` |
| `GET` | `/api/doc-review/{dataset_id}/decisions` | `doc_review_decisions` |
| `POST` | `/api/doc-review/{dataset_id}/decision` | `doc_review_set_decision` |
| `POST` | `/api/verify/extract` | `verify_extract` |
| `GET` | `/api/verify/image` | `verify_image` |
| `POST` | `/api/verify/save` | `verify_save` |
| `GET` | `/api/verify/list` | `verify_list` |
| `POST` | `/api/extract/structured` | `structured` |
| `GET` | `/api/forms` | `forms_list` |
| `GET` | `/api/forms/{form_id}/fields` | `forms_fields` |
| `POST` | `/api/forms/{form_id}/generate` | `forms_generate` |
| `GET` | `/api/forms/{form_id}/download` | `forms_download` |

### Field, worklog, incoming control, tasks, notes

| Method | Path | Handler |
|---|---|---|
| `POST` | `/api/field` | `field_create` |
| `GET` | `/api/field` | `field_list` |
| `GET` | `/api/field/summary` | `field_summary` |
| `PATCH` | `/api/field/{entry_id}` | `field_patch` |
| `DELETE` | `/api/field/{entry_id}` | `field_delete` |
| `POST` | `/api/field/extract-asbuilt` | `field_extract_asbuilt` |
| `POST` | `/api/field/export` | `field_export` |
| `GET` | `/api/field/download` | `field_download` |
| `GET` | `/api/worklog/{project_id}` | `worklog_get` |
| `PATCH` | `/api/worklog/{project_id}/meta` | `worklog_set_meta` |
| `POST` | `/api/worklog/{project_id}/export` | `worklog_export` |
| `GET` | `/api/worklog/{project_id}/download` | `worklog_download` |
| `GET` | `/api/incoming-control/{project_id}/journal` | `journal` |
| `POST` | `/api/incoming-control/{project_id}/records` | `add_record` |
| `GET` | `/api/incoming-control/{project_id}/act/{control_id}` | `act` |
| `GET` | `/api/incoming-control/{project_id}/quality-docs` | `quality_docs` |
| `POST` | `/api/incoming-control/{project_id}/quality-docs` | `add_quality_doc` |
| `POST` | `/api/incoming-control/{project_id}/export` | `export` |
| `GET` | `/api/incoming-control/{project_id}/download` | `download` |
| `POST` | `/api/tasks` | `tasks_create` |
| `GET` | `/api/tasks` | `tasks_list` |
| `PATCH` | `/api/tasks/{task_id}` | `tasks_patch` |
| `POST` | `/api/notes` | `notes_create` |
| `GET` | `/api/notes` | `notes_list` |
| `DELETE` | `/api/notes/{note_id}` | `notes_delete` |

### Mail, external radar, file map, LES MD

| Method | Path | Handler |
|---|---|---|
| `GET` | `/api/mail/status` | `mail_status` |
| `GET` | `/api/mail/messages` | `list_mail_messages` |
| `GET` | `/api/mail/threads` | `list_mail_threads` |
| `GET` | `/api/mail/threads/{thread_key}` | `get_mail_thread` |
| `POST` | `/api/mail/import-local` | `import_local_mail` |
| `POST` | `/api/mail/push` | `push_mail` |
| `POST` | `/api/mail/import-archive` | `import_mail_archive` |
| `POST` | `/api/mail/import-imap` | `import_imap_mail` |
| `POST` | `/api/mail/import-apple-mail` | `import_apple_mail` |
| `GET` | `/api/external-radar/summary` | `external_radar_summary` |
| `POST` | `/api/filemap/scan` | `filemap_scan` |
| `GET` | `/api/filemap/search` | `filemap_search` |
| `GET` | `/api/filemap/stats` | `filemap_stats` |
| `GET` | `/api/filemap/candidates` | `filemap_candidates` |
| `POST` | `/api/filemap/index` | `filemap_index` |
| `POST` | `/api/les-md/read` | `les_md_read` |
| `POST` | `/api/les-md/draft` | `les_md_draft` |
| `GET` | `/api/les-md/context/{project_id}` | `les_md_context` |

### Status page

| Method | Path | Handler |
|---|---|---|
| `GET` | `/` | `status_page` |
| `GET` | `/login` | `login_page` |

## Sovushka bridge and UI routes

These are served by the UI process, not the proxy.

| Method | Path | Purpose |
|---|---|---|
| any | `/lite-api/{path:path}` | Bridge to proxy `/api/{path}`; supports `GET`, `POST`, `PUT`, `PATCH`, `DELETE` |
| `GET` | `/` | Redirect to `/classic` |
| `GET` | `/les`, `/les/` | Redirect to `/les/classic` |
| `GET` | `/les/lite`, `/les/lite/` | Redirect to `/les/classic` |
| `GET` | `/les/cad-bim-viewer`, `/les/cad-bim-viewer/` | CAD/BIM viewer HTML |
| static | `/les/cad-bim-viewer/assets/*` | CAD/BIM viewer assets |
| static | `/les/cad-bim-viewer/web-ifc/*` | web-ifc wasm/runtime files |
| static | `/les/cad-bim-viewer/fragments/*` | ThatOpen fragments worker/assets |
| static | `/les/cad-bim-viewer/ifc-sample/*` | Local IFC sample files |
| `GET` | `/lite-runtime/status` | Local/trusted runtime status |
| `GET` | `/lite-runtime/reindex-status` | Local/trusted reindex status |
| `GET` | `/lite-runtime/pick-folder` | Loopback-only native folder picker |
| `POST` | `/lite-runtime/action/{action}` | Local/trusted actions: `start_indexer`, `stop_indexer`, `restart_proxy`, `restart_mlx`, `restart_qdrant`, `restart_ui` |
| `GET` | `/m5`, `/m5/`, `/display/m5`, `/display/m5/` | M5 display page |

## MLX host API

Base: `http://127.0.0.1:8080`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Host/model/memory health |
| `POST` | `/api/unload_val` | Unload validator model |
| `POST` | `/api/unload_all` | Unload all heavy models |
| `GET` | `/api/host_memory` | Host RAM/swap snapshot |
| `GET` | `/api/ps` | Ollama-compatible loaded model list |
| `POST` | `/api/switch_model` | Switch main/validator model |
| `GET` | `/v1/models` | OpenAI-compatible model list |
| `POST` | `/api/generate` | Ollama-compatible generation |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completions; streaming supported |
| `POST` | `/api/validate` | LES validation: `VERIFIED` / `NO_DATA` / `HALLUCINATION` |
| `POST` | `/api/embeddings` | Ollama-style embeddings |
| `POST` | `/v1/embeddings` | OpenAI-compatible embeddings |
| `POST` | `/v1/rerank` | Rerank API |

## MCP server

Start:

```bash
cd /Users/ovc/Projects/LES_v2
uv run python tools/les_mcp_server.py
```

List tools:

```bash
uv run python tools/les_mcp_server.py --list
```

Example MCP client registration:

```json
{
  "mcpServers": {
    "les": {
      "command": "uv",
      "args": ["run", "python", "tools/les_mcp_server.py"],
      "cwd": "/Users/ovc/Projects/LES_v2"
    }
  }
}
```

### MCP tools

| Tool | Description |
|---|---|
| `les_table_sum` | Сумма/кол-во по таблицам Parquet, без LLM |
| `les_reconcile` | Сверка ВОР-КС-2-смета-ИД по количествам |
| `les_bor` | Свод ВОР из спецификаций |
| `les_spec_to_bor` | ВОР работ из спецификации форма 9 |
| `les_project_summary` | Сводка проекта: ТЭП, стадии, состав |
| `les_form_generate` | Генерация формы: спецификация, ВОР, смета, АОСР |
| `les_price_lookup` | Цена ФГИС ЦС по коду ресурса из Сплит-формы |
| `les_glossary` | Определение ВОР/КАЦ/ЛСР/КС + деривация |
| `les_kac` | КАЦ: 3+ КП на материал -> выбор экономичного + линии ЛСР |
| `les_stesnennost` | Коэффициент стеснённости -> пересчёт позиций ЛСР |
| `les_lsr_assemble` | Сборка ЛСР: объём+ресурсы -> цены -> НР/СП -> итог |
| `les_gesn_expand` | Норма ГЭСН + объём -> ресурсы |
| `les_table_agg` | Агрегация по таблицам с группировкой |
| `les_gesn_fetch` | Дотянуть норму ГЭСН-2022 из API smetnoedelo в базу |
| `les_smeta_save` | ДЕЙСТВИЕ: собранную смету -> документ ВОР/ЛСР в проект |
| `les_journal_append` | ДЕЙСТВИЕ: дописать запись в журнал работ, pending/idempotent |

## Integration notes

- For public integrations prefer `/lite-api/*` through `https://les.ovc.me` and pass `X-API-Key` or `Authorization`.
- For trusted local tools on the same machine prefer direct proxy `http://127.0.0.1:8050/api/*`.
- For browser/UI plugins prefer the bridge: `/lite-api/chat`, `/lite-api/rag/attach`, `/lite-api/cad-bim/*`.
- For programmatic deterministic construction tools prefer MCP where possible; it keeps external agents away from internal admin endpoints.
- Avoid exposing destructive endpoints publicly: dataset delete, backup restore/delete, runtime restart/unload, prompt mutation, external indexing, filesystem tool call.
