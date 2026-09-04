# Л.Е.С. (LES_v2) — dev-гейт. Офлайн, без живых сервисов (Qdrant/MLX не нужны).
# Требует uv. `make verify` — перед объявлением правки готовой.
.PHONY: version-sync architecture-gate verify test test-unit test-smoke test-coverage test-ci test-integration test-release test-release-critical test-architecture test-legacy test-legacy-full test-focused test-rag-core test-mail test-mail-release test-updater test-tauri platform-gate smeta-base smeta-base-source smeta-base-update smoke-active-artifacts smoke-general-native-rrf smoke-smeta-rerank smoke-basic smoke-basic-release public-check ship-check ship-full-check deploy-runtime post-deploy-rag-smoke post-deploy-smoke ship ship-full release patch-release github-patch-release release-multiplatform build-windows-update-shell prepare-windows-update prepare-mac-update inspect-mac-update apply-mac-update status-mac-update preflight-audit-rag-update prepare-audit-rag prepare-audit-rag-legion inspect-audit-rag-update deploy-audit-rag deploy-audit-rag-mac live-workbook-acceptance test-model-connections-live help

PATCH_RELEASE_ARGS ?=
RELEASE_ARGS ?=
GITHUB_PATCH_RELEASE_ARGS ?=
MULTIPLATFORM_RELEASE_ARGS ?=
AUDIT_RAG_UPDATE_ARGS ?=
MAC_UPDATE_BRANCH ?= codex/audit-rag
WINDOWS_UPDATE_ARGS ?=
WINDOWS_SHELL_ARGS ?=
DEPLOY_FORCE_FILES ?=
LIVE_WORKBOOK_ACCEPTANCE_ARGS ?=
MODEL_CONNECTION_LIVE_ARGS ?=
PYTEST_BASETEMP ?= .test-tmp

PKGS := backend proxy sovushka tools sovushka_ng.py proxy_server.py mlx_host.py
SMOKE_ARGS ?=
FOCUS_TESTS ?= tests/test_rim_agent_turn.py tests/test_rim_next_step_service.py tests/test_rim_session.py tests/test_rim_scenarios.py tests/test_rim_api.py tests/test_rag_hierarchy.py tests/test_rag_config.py tests/test_rag_rrf_readiness.py tests/test_smeta_application_boundary.py tests/test_runtime_router.py tests/test_sovushka_uikit.py tests/test_sovushka_chat.py tests/test_web_search_service.py tests/test_mail_router.py tests/test_outlook_mail_poller.py
RAG_CORE_TESTS ?= tests/test_datasets_router.py tests/test_rag_config.py tests/test_qdrant_adapter_parse.py tests/test_build_rag_contract_sibling.py tests/test_activate_qdrant_generation.py tests/test_rag_generation_supervisor.py tests/test_rag_rrf_readiness.py tests/test_system_dataset_service.py tests/test_retrieval_quality_service.py tests/test_retrieval_service.py tests/test_saferag_service.py tests/test_source_excerpts.py tests/test_source_adapter_classifier_boundary.py tests/test_evidence_packet_service.py tests/test_rag_golden_set.py tests/test_rag_index_contract_audit.py tests/test_notebook_study_service.py tests/test_runtime_config_registry_service.py tests/test_rag_advanced_policy_service.py tests/test_rag_advanced_preflight_service.py tests/test_rag_pipeline_status_service.py tests/test_colbert_late_interaction.py tests/test_colbert_generation_service.py tests/test_raptor_tree.py tests/test_raptor_publication_worker.py tests/test_raptor_qdrant_store.py tests/test_raptor_summarizer.py tests/test_raptor_publication_service.py tests/test_raptor_retrieval.py tests/test_parse_resume.py tests/test_basic_function_smoke.py tests/test_rag_advanced_synthetic_benchmark.py
RELEASE_CRITICAL_TESTS ?= tests/test_fgis_full_update.py tests/test_smeta_release_baseline.py tests/test_qdrant_collection_layout.py tests/test_datasets_router.py tests/test_rag_config.py tests/test_document_explorer_service.py tests/test_process_status.py
UNIT_TESTS ?= tests/test_answer_contract_service.py tests/test_architecture_contract_gate.py tests/test_candidate_selection_service.py tests/test_chat_evidence_application_service.py tests/test_context_governor_service.py tests/test_evidence_contract.py tests/test_model_execution_preset_service.py tests/test_model_preset_workflow_parity.py tests/test_numeric_provenance.py tests/test_publication_check.py tests/test_query_router.py tests/test_smeta_resource_normalizer.py tests/test_tool_harness_service.py tests/test_typed_memory_projection_service.py tests/test_workbook_tool_contracts.py tests/test_workbook_tool_service.py
MEMORY_TESTS ?= tests/test_memory_core.py tests/test_memory_api.py tests/test_memory_ui_contract.py tests/test_smeta_memory_isolation.py
SMETA_DOCUMENT_TESTS ?= tests/test_smeta_chat_application_service.py tests/test_ks_forms_service.py tests/test_rim_coverage_header.py tests/test_forms_templates.py tests/test_command_service.py
MODEL_CONNECTION_TESTS ?= tests/test_candidate_acceptance_service.py tests/test_canonical_promotion_service.py tests/test_canonical_route_service.py tests/test_les_runtime_control.py tests/test_live_workbook_acceptance_contract.py tests/test_model_capability_service.py tests/test_model_connection_chat_integration.py tests/test_model_connection_embeddings_integration.py tests/test_model_connection_live_acceptance.py tests/test_model_connection_registry_service.py tests/test_model_connection_resolver_service.py tests/test_model_connection_security_service.py tests/test_model_connections_router.py tests/test_model_engine_extension_service.py tests/test_model_preset_workflow_parity.py tests/test_model_secret_service.py tests/test_openai_compatible_transport_service.py tests/test_sovushka_model_connections.py
INTEGRATION_TESTS ?= tests/test_smeta_structured_base.py tests/test_smeta_norm_browser.py tests/test_smeta_rerank_ab_probe.py tests/test_activate_smeta_rag_generation.py tests/test_gesn_update_pipeline.py tests/test_rag_readiness_service.py tests/test_smeta_generation_coordinator.py tests/test_rebuild_active_smeta_rag.py tests/test_smeta_generation_reconciliation_service.py tests/test_smeta_update_entrypoints.py tests/test_update_resilience_matrix.py tests/test_sovushka_rag_warning.py tests/test_windows_runtime_entrypoints.py $(RELEASE_CRITICAL_TESTS)
CURRENT_TESTS ?= $(sort $(UNIT_TESTS) $(INTEGRATION_TESTS) $(RAG_CORE_TESTS) $(FOCUS_TESTS) $(MEMORY_TESTS) $(SMETA_DOCUMENT_TESTS) $(MODEL_CONNECTION_TESTS) tests/test_code_runtime_map.py tests/test_documentation_contract.py tests/test_test_profiles.py tests/test_software_versions.py)
LEGACY_ARCHITECTURE_TESTS ?= tests/test_construction_harness.py tests/test_resource_cost_v05.py tests/test_resource_cost_v06.py tests/test_unified_adapters_v09.py tests/test_unified_async_v10.py tests/test_unified_construction_harness.py tests/test_unified_construction_v04.py tests/test_unified_filebody_v12.py tests/test_unified_live_v07.py tests/test_unified_operational_v08.py tests/test_unified_real_v11.py
ARTEL_TESTS := $(wildcard tests/test_artel*.py)
ARCHITECTURE_EXCLUDED_TESTS := $(LEGACY_ARCHITECTURE_TESTS) $(ARTEL_TESTS)
ARCHITECTURE_IGNORE_ARGS := $(foreach test,$(ARCHITECTURE_EXCLUDED_TESTS),--ignore=$(test))
LES_RELEASE_IGNORE_ARGS := $(ARCHITECTURE_IGNORE_ARGS)
MAIL_TESTS ?= tests/test_chat_mail_query.py tests/test_converter_email.py tests/test_ezhik_imap_smoke.py tests/test_mail_ingest.py tests/test_mail_profile.py tests/test_mail_push_service.py tests/test_mail_query_service.py tests/test_mail_registry_service.py tests/test_mail_router.py tests/test_mail_threads.py tests/test_outlook_mail_poller.py
UPDATER_TESTS ?= tests/test_release_classification.py tests/test_release_receipt.py tests/test_release_orchestrator.py tests/test_github_patch_release.py tests/test_vps_patch.py tests/test_windows_application_update.py tests/test_windows_release_acceptance.py tests/test_windows_update_shell.py tests/test_update_service.py tests/test_manual_update_ui.py tests/test_mac_update.py
POST_DEPLOY_RETRIES ?= 12
POST_DEPLOY_DELAY ?= 1
SMETA_BASE_UPDATE_ARGS ?= --all --rate 1.0
SMETA_BASELINE_ROOT ?= .

help:
	@echo "make verify       — офлайн-гейт: compileall (синтаксис) + pytest --collect-only (импорт-смоук)"
	@echo "make architecture-gate — fail-closed границы canonical Registry/Governor/profile/workbook architecture"
	@echo "make test         — короткий канонический contract/behavior gate"
	@echo "make test-unit    — быстрые hermetic unit-тесты чистых вычислительных/контрактных функций"
	@echo "make test-integration — поведенческие тесты временных SQLite/Parquet/API/release-артефактов"
	@echo "make test-release — канонический contract/behavior gate + smoke active-артефактов"
	@echo "make test-release-critical — совместимый псевдоним make test-integration"
	@echo "make test-architecture — совместимый псевдоним короткого канонического gate"
	@echo "make test-legacy — отдельный opt-in прогон исторического Unified/Construction Harness"
	@echo "make test-legacy-full — прежняя 3204-test suite; только opt-in диагностика"
	@echo "make test-focused — быстрые профильные pytest; переопредели FOCUS_TESTS='tests/test_x.py ...'"
	@echo "make test-rag-core — обязательный offline integrity-гейт RAG-ядра"
	@echo "make test-mail      — обязательный offline профиль Е.Ж.И.К. (IMAP/registry/RAG/API/UI/Windows static)"
	@echo "make test-mail-release — test-mail + Rust compile-check Tauri; live Outlook проверяется на Windows"
	@echo "make test-updater — короткий behavior-гейт updater: validate/apply/rollback/data/process, без общей suite/build/baseline"
	@echo "make prepare-windows-update — после короткого gate собрать bounded runtime/app ZIP; параметры через WINDOWS_UPDATE_ARGS"
	@echo "make build-windows-update-shell — Windows-only cargo build одного attested les-desktop.exe, без installer/baseline"
	@echo "make test-tauri    — Rust compile-check Tauri desktop shell"
	@echo "make platform-gate — portable verify → full tests → native Tauri build на текущей ОС"
	@echo "make smeta-base   — пересобрать checked unified parquet → structured SQLite → SMETA_SERVICE cards без скачивания"
	@echo "make smeta-base-source — пересобрать raw/cache → unified parquet → smeta-base без скачивания"
	@echo "make smeta-base-update — скачать/обновить ГЭСН из ФГИС и прогнать полный smeta-base pipeline; args: SMETA_BASE_UPDATE_ARGS='--all --rate 1.0'"
	@echo "make smoke-active-artifacts — проверить фактическую active smeta-base/FSEM, SHA и provenance"
	@echo "make smoke-general-native-rrf — живой release smoke общего dense+sparse→native RRF без reranker/LLM"
	@echo "make smoke-smeta-rerank — отдельный opt-in A/B smoke Qdrant→reranker для сметной диагностики"
	@echo "make smoke-basic  — L1 HTTP-smoke базовых функций против живого runtime (:8050/:8051)"
	@echo "make smoke-basic-release — тот же L1 smoke, но P1 блокирует выкат"
	@echo "make public-check — guardrail перед публичным git: tracked data/secrets/license/docs"
	@echo "make ship-check   — быстрый pre-deploy гейт: verify → test-focused → test-rag-core → active artifacts"
	@echo "make ship-full-check — полный pre-deploy гейт: verify → test → active artifacts"
	@echo "make deploy-runtime — dev→runtime cp-деплой + restart + stamp; только проверенные divergent-файлы через DEPLOY_FORCE_FILES='path ...'"
	@echo "make ship         — быстрый выкат: ship-check → deploy-runtime → native-RRF smoke → post-deploy-smoke"
	@echo "make ship-full    — полный выкат версии: ship-full-check → deploy-runtime → native-RRF smoke → post-deploy-smoke"
	@echo "make release      — единственный публичный выпуск: prepare → Legion install/smoke/rollback/reinstall → accepted draft → postflight"
	@echo "make prepare-mac-update — собрать малый пакет изменённых runtime-файлов из чистого pushed commit"
	@echo "make inspect-mac-update — показать локальный манифест и точный размер пакета"
	@echo "make apply-mac-update — транзакционно установить пакет на Mac, проверить и откатить при ошибке"
	@echo "make status-mac-update — показать состояние установки/отката"
	@echo "make deploy-audit-rag — совместимый псевдоним apply-mac-update; Legion намеренно отключён"
	@echo "make version-sync — синхронизировать Cargo/Tauri/паспорт версий из config/version.json"
	@echo "make live-workbook-acceptance — opt-in receipt ordinary workbook chat on real user-owned input"
	@echo "make test-model-connections-live — opt-in redacted receipt for exact configured 9B/35B revisions"

version-sync:
	uv run python tools/sync_version_contract.py

architecture-gate:
	uv run python tools/architecture_contract_gate.py

live-workbook-acceptance:
	uv run python tools/live_workbook_acceptance.py $(LIVE_WORKBOOK_ACCEPTANCE_ARGS)

test-model-connections-live:
	uv run python tools/model_connection_live_acceptance.py $(MODEL_CONNECTION_LIVE_ARGS)

verify:
	uv run python tools/sync_version_contract.py --check
	uv run python tools/code_runtime_map.py --check
	uv run python -m compileall -q $(PKGS)
	uv run python -m pytest --basetemp=$(PYTEST_BASETEMP)/verify --collect-only -q $(CURRENT_TESTS)
	@echo "OK — verify зелёный (синтаксис + импорт-смоук current gate)."

test:
	uv run python tools/code_runtime_map.py --check
	uv run python -m pytest --basetemp=$(PYTEST_BASETEMP)/test -q --durations=20 $(CURRENT_TESTS)

test-unit:
	uv run python -m pytest --basetemp=$(PYTEST_BASETEMP)/unit -q --durations=15 $(UNIT_TESTS)

test-smoke:
	uv run python tools/test_runner.py smoke

test-coverage:
	uv run python tools/test_runner.py coverage

test-ci:
	uv run python tools/test_runner.py ci

test-integration:
	uv run python -m pytest --basetemp=$(PYTEST_BASETEMP)/integration -q --durations=15 $(INTEGRATION_TESTS)

test-release: test smoke-active-artifacts
	@echo "OK — code regression и фактические active-артефакты зелёные. Далее обязателен installed Windows smoke."

test-release-critical: test-integration

test-architecture:
	$(MAKE) test

test-legacy:
	uv run python -m pytest -o addopts= --basetemp=$(PYTEST_BASETEMP)/legacy --durations=20 $(LEGACY_ARCHITECTURE_TESTS)

test-legacy-full:
	uv run python -m pytest -o addopts= --basetemp=$(PYTEST_BASETEMP)/legacy-full --durations=20 $(ARCHITECTURE_IGNORE_ARGS)

test-focused:
	uv run python -m pytest --basetemp=$(PYTEST_BASETEMP)/focused $(FOCUS_TESTS)

test-rag-core:
	uv run python -m pytest --basetemp=$(PYTEST_BASETEMP)/rag-core -q --durations=15 $(RAG_CORE_TESTS)

test-mail:
	uv run python -m pytest --basetemp=$(PYTEST_BASETEMP)/mail -q --durations=15 $(MAIL_TESTS)

test-mail-release: test-mail test-tauri
	@echo "OK — offline/static mail gate зелёный. Следующий обязательный гейт: installed Legion + classic Outlook."

test-updater:
	uv run python tools/platform_release_gate.py updater
	@echo "OK — updater behavior-гейт зелёный; build, baseline и общая LES suite не запускались."

test-tauri:
	cargo check --manifest-path desktop/tauri/src-tauri/Cargo.toml

platform-gate:
	uv run python tools/platform_release_gate.py verify
	uv run python tools/platform_release_gate.py test
	uv run python tools/platform_release_gate.py build

smeta-base:
	uv run python -m tools.smeta_generation_coordinator --source data/gesn_base/gesn2022_unified.parquet
	uv run python -m tools.build_smeta_service_rag

smeta-base-source:
	uv run python -m tools.gesn_unify_base
	$(MAKE) smeta-base

smeta-base-update:
	uv run python -m tools.gesn_update_from_fgis $(SMETA_BASE_UPDATE_ARGS)

smoke-active-artifacts:
	uv run python -m tools.smeta_release_baseline verify-root --root $(SMETA_BASELINE_ROOT)

smoke-general-native-rrf:
	uv run python tools/rag_golden_set.py --cases golden/general_native_rrf_release_smoke.json --require-native-rrf

smoke-smeta-rerank:
	uv run python -m tools.smeta_rerank_ab_probe --require-ok --require-hybrid --require-quality \
		--query "монтаж блока аварийного питания светильника" \
		--expect-after "аварийн|блок питания|светильник" \
		--query "монтаж патч панели 24 порта" \
		--expect-after "кросс|телефон|коммутац" \
		--report-path artifacts/smeta_rerank_ab_smoke.json

smoke-basic:
	uv run python tools/basic_function_smoke.py $(SMOKE_ARGS)

# Release/ship путь обязан считать P1 блокером; ручной dev-smoke остаётся неблокирующим для P1.
smoke-basic-release:
	uv run python tools/basic_function_smoke.py --release $(SMOKE_ARGS)

public-check:
	uv run python tools/publication_check.py

# Быстрый prod-гейт без деплоя: для малых итераций внутри версии.
ship-check: verify test-focused test-rag-core smoke-active-artifacts
	@echo ""
	@echo "== ship-check ЗЕЛЁНЫЙ: verify → test-focused → test-rag-core → active artifacts."

# Полный prod-гейт без деплоя: запускать на границе версии/релиза и перед большими изменениями.
ship-full-check: verify test smoke-active-artifacts
	@echo ""
	@echo "== ship-full-check ЗЕЛЁНЫЙ: verify → test → active artifacts."

deploy-runtime:
ifneq ($(strip $(DEPLOY_FORCE_FILES)),)
	uv run python -m tools.deploy_to_runtime --apply --force --files $(DEPLOY_FORCE_FILES)
endif
	uv run python -m tools.deploy_to_runtime --apply --restart

post-deploy-smoke:
	@set -e; \
	for i in $$(seq 1 $(POST_DEPLOY_RETRIES)); do \
		if uv run python tools/basic_function_smoke.py --release $(SMOKE_ARGS); then \
			echo ""; \
			echo "== post-deploy smoke ЗЕЛЁНЫЙ."; \
			exit 0; \
		fi; \
		echo "post-deploy smoke попытка $$i/$(POST_DEPLOY_RETRIES) не прошла, ждём $(POST_DEPLOY_DELAY)s..."; \
		sleep $(POST_DEPLOY_DELAY); \
	done; \
	echo "post-deploy smoke не поднялся после $(POST_DEPLOY_RETRIES) попыток"; \
	exit 1

post-deploy-rag-smoke:
	@set -e; \
	for i in $$(seq 1 $(POST_DEPLOY_RETRIES)); do \
		if uv run python tools/rag_golden_set.py --cases golden/general_native_rrf_release_smoke.json --require-native-rrf; then \
			echo ""; \
			echo "== post-deploy native-RRF smoke ЗЕЛЁНЫЙ."; \
			exit 0; \
		fi; \
		echo "post-deploy native-RRF smoke attempt $$i/$(POST_DEPLOY_RETRIES) failed; waiting $(POST_DEPLOY_DELAY)s..."; \
		sleep $(POST_DEPLOY_DELAY); \
	done; \
	echo "post-deploy native-RRF smoke failed after $(POST_DEPLOY_RETRIES) attempts"; \
	exit 1

# Быстрый выкат: версия/леджер должны быть обновлены в этом же изменении ДО запуска.
ship: ship-check deploy-runtime post-deploy-rag-smoke post-deploy-smoke
	@echo ""
	@echo "== ship ЗЕЛЁНЫЙ: код проверен, runtime обновлён, post-deploy smoke прошёл."

# Полный выкат версии: длинную сюиту гоняем на границе версии, а не на каждой мелкой UI-итерации.
ship-full: ship-full-check deploy-runtime post-deploy-rag-smoke post-deploy-smoke
	@echo ""
	@echo "== ship-full ЗЕЛЁНЫЙ: полный gate, runtime обновлён, post-deploy smoke прошёл."

patch-release:
	uv run python tools/patch_release.py $(PATCH_RELEASE_ARGS)

release:
	uv run python tools/release_orchestrator.py $(RELEASE_ARGS)

github-patch-release:
	uv run python tools/github_patch_release.py $(GITHUB_PATCH_RELEASE_ARGS)

release-multiplatform:
	uv run python tools/multiplatform_release.py $(MULTIPLATFORM_RELEASE_ARGS)

build-windows-update-shell: test-updater
	uv run python tools/windows_update_shell.py $(WINDOWS_SHELL_ARGS)

prepare-windows-update: test-updater
	uv run python tools/vps_patch.py build $(WINDOWS_UPDATE_ARGS)

prepare-mac-update:
	LES_MAC_UPDATE_BRANCH="$(MAC_UPDATE_BRANCH)" uv run python tools/mac_update.py prepare $(AUDIT_RAG_UPDATE_ARGS)

inspect-mac-update:
	LES_MAC_UPDATE_BRANCH="$(MAC_UPDATE_BRANCH)" uv run python tools/mac_update.py inspect $(AUDIT_RAG_UPDATE_ARGS)

apply-mac-update:
	LES_MAC_UPDATE_BRANCH="$(MAC_UPDATE_BRANCH)" uv run python tools/mac_update.py apply $(AUDIT_RAG_UPDATE_ARGS)

status-mac-update:
	LES_MAC_UPDATE_BRANCH="$(MAC_UPDATE_BRANCH)" uv run python tools/mac_update.py status $(AUDIT_RAG_UPDATE_ARGS)

preflight-audit-rag-update inspect-audit-rag-update: inspect-mac-update

prepare-audit-rag: prepare-mac-update

prepare-audit-rag-legion:
	@echo "Legion отключён: сначала принимаем Mac updater."
	@exit 2

deploy-audit-rag-mac deploy-audit-rag: apply-mac-update
