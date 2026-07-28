# Л.Е.С. (LES_v2) — dev-гейт. Офлайн, без живых сервисов (Qdrant/MLX не нужны).
# Требует uv. `make verify` — перед объявлением правки готовой.
.PHONY: version-sync verify test test-unit test-integration test-release test-release-critical test-architecture test-legacy test-focused test-rag-core test-mail test-mail-release test-tauri smeta-base smeta-base-source smeta-base-update smoke-active-artifacts smoke-smeta-rerank smoke-basic smoke-basic-release public-check ship-check ship-full-check deploy-runtime post-deploy-smoke ship ship-full patch-release help

PATCH_RELEASE_ARGS ?=

PKGS := backend proxy sovushka tools sovushka_ng.py proxy_server.py mlx_host.py
SMOKE_ARGS ?=
FOCUS_TESTS ?= tests/test_sovushka_chat.py tests/test_static_assets.py tests/test_smeta_chat_service.py tests/test_estimate_harness.py tests/test_profile_resolver.py tests/test_doc_review_gost_21_101_2026.py tests/test_doc_review_chat_tool.py tests/test_title_block_extract.py tests/test_service_source_registry.py
RAG_CORE_TESTS ?= tests/test_datasets_router.py tests/test_rag_config.py tests/test_qdrant_adapter_parse.py tests/test_build_rag_contract_sibling.py tests/test_system_dataset_service.py tests/test_retrieval_quality_service.py tests/test_retrieval_service.py tests/test_saferag_service.py tests/test_source_excerpts.py tests/test_evidence_packet_service.py tests/test_rag_golden_set.py tests/test_rag_index_contract_audit.py tests/test_notebook_study_service.py
RELEASE_CRITICAL_TESTS ?= tests/test_fgis_full_update.py tests/test_smeta_release_baseline.py tests/test_qdrant_collection_layout.py tests/test_datasets_router.py tests/test_rag_config.py tests/test_document_explorer_service.py tests/test_process_status.py
UNIT_TESTS ?= tests/test_answer_contract_service.py tests/test_candidate_selection_service.py tests/test_evidence_contract.py tests/test_numeric_provenance.py tests/test_publication_check.py tests/test_query_router.py tests/test_smeta_resource_normalizer.py
INTEGRATION_TESTS ?= tests/test_smeta_structured_base.py tests/test_smeta_norm_browser.py tests/test_smeta_rerank_ab_probe.py $(RELEASE_CRITICAL_TESTS)
LEGACY_ARCHITECTURE_TESTS ?= tests/test_construction_harness.py tests/test_resource_cost_v05.py tests/test_resource_cost_v06.py tests/test_unified_adapters_v09.py tests/test_unified_async_v10.py tests/test_unified_construction_harness.py tests/test_unified_construction_v04.py tests/test_unified_filebody_v12.py tests/test_unified_live_v07.py tests/test_unified_operational_v08.py tests/test_unified_real_v11.py
ARTEL_TESTS := $(wildcard tests/test_artel*.py)
ARCHITECTURE_EXCLUDED_TESTS := $(LEGACY_ARCHITECTURE_TESTS) $(ARTEL_TESTS)
ARCHITECTURE_IGNORE_ARGS := $(foreach test,$(ARCHITECTURE_EXCLUDED_TESTS),--ignore=$(test))
LES_RELEASE_IGNORE_ARGS := $(ARCHITECTURE_IGNORE_ARGS)
MAIL_TESTS ?= tests/test_chat_mail_query.py tests/test_converter_email.py tests/test_ezhik_imap_smoke.py tests/test_mail_ingest.py tests/test_mail_profile.py tests/test_mail_push_service.py tests/test_mail_query_service.py tests/test_mail_registry_service.py tests/test_mail_router.py tests/test_mail_threads.py tests/test_outlook_mail_poller.py
POST_DEPLOY_RETRIES ?= 12
POST_DEPLOY_DELAY ?= 1
SMETA_BASE_UPDATE_ARGS ?= --all --rate 1.0

help:
	@echo "make verify       — офлайн-гейт: compileall (синтаксис) + pytest --collect-only (импорт-смоук)"
	@echo "make test         — каноническая LES-сюита без legacy Unified Harness и отдельного ARTEL"
	@echo "make test-unit    — быстрые hermetic unit-тесты чистых вычислительных/контрактных функций"
	@echo "make test-integration — поведенческие тесты временных SQLite/Parquet/API/release-артефактов"
	@echo "make test-release — полная LES-сюита + smoke реальных active-артефактов"
	@echo "make test-release-critical — совместимый псевдоним make test-integration"
	@echo "make test-architecture — совместимый псевдоним канонической LES-сюиты"
	@echo "make test-legacy — отдельный opt-in прогон исторического Unified/Construction Harness"
	@echo "make test-focused — быстрые профильные pytest; переопредели FOCUS_TESTS='tests/test_x.py ...'"
	@echo "make test-rag-core — обязательный offline integrity-гейт RAG-ядра"
	@echo "make test-mail      — обязательный offline профиль Е.Ж.И.К. (IMAP/registry/RAG/API/UI/Windows static)"
	@echo "make test-mail-release — test-mail + Rust compile-check Tauri; live Outlook проверяется на Windows"
	@echo "make test-tauri    — Rust compile-check Tauri desktop shell"
	@echo "make smeta-base   — пересобрать checked unified parquet → structured SQLite → SMETA_SERVICE cards без скачивания"
	@echo "make smeta-base-source — пересобрать raw/cache → unified parquet → smeta-base без скачивания"
	@echo "make smeta-base-update — скачать/обновить ГЭСН из ФГИС и прогнать полный smeta-base pipeline; args: SMETA_BASE_UPDATE_ARGS='--all --rate 1.0'"
	@echo "make smoke-active-artifacts — проверить фактическую active smeta-base/FSEM, SHA и provenance"
	@echo "make smoke-smeta-rerank — живой A/B smoke Qdrant→reranker; ошибка/обход reranker блокирует ship"
	@echo "make smoke-basic  — L1 HTTP-smoke базовых функций против живого runtime (:8050/:8051)"
	@echo "make smoke-basic-release — тот же L1 smoke, но P1 блокирует выкат"
	@echo "make public-check — guardrail перед публичным git: tracked data/secrets/license/docs"
	@echo "make ship-check   — быстрый гейт без деплоя: verify → test-focused → smoke-basic"
	@echo "make ship-full-check — полный гейт без деплоя: verify → test → smoke-basic"
	@echo "make deploy-runtime — dev→runtime cp-деплой + restart + deploy stamp"
	@echo "make ship         — быстрый выкат: ship-check → deploy-runtime → post-deploy-smoke"
	@echo "make ship-full    — полный выкат версии: ship-full-check → deploy-runtime → post-deploy-smoke"
	@echo "make patch-release — Windows: gates → Legion build/install/RRF-smoke → artifacts; публикация только PATCH_RELEASE_ARGS='--publish --notes-file ...'"
	@echo "make version-sync — синхронизировать Cargo/Tauri/паспорт версий из config/version.json"

version-sync:
	uv run python tools/sync_version_contract.py

verify:
	uv run python tools/sync_version_contract.py --check
	uv run python -m compileall -q $(PKGS)
	uv run python -m pytest --collect-only -q $(ARCHITECTURE_IGNORE_ARGS)
	@echo "OK — verify зелёный (синтаксис + импорт-смоук). Полные тесты: make test."

test:
	uv run python -m pytest --durations=20 $(ARCHITECTURE_IGNORE_ARGS)

test-unit:
	uv run python -m pytest -q --durations=15 $(UNIT_TESTS)

test-integration:
	uv run python -m pytest -q --durations=15 $(INTEGRATION_TESTS)

test-release: test smoke-active-artifacts
	@echo "OK — code regression и фактические active-артефакты зелёные. Далее обязателен installed Windows smoke."

test-release-critical: test-integration

test-architecture:
	uv run python -m pytest --durations=20 $(ARCHITECTURE_IGNORE_ARGS)

test-legacy:
	uv run python -m pytest -o addopts= --durations=20 $(LEGACY_ARCHITECTURE_TESTS)

test-focused:
	uv run python -m pytest $(FOCUS_TESTS)

test-rag-core:
	uv run python -m pytest -q --durations=15 $(RAG_CORE_TESTS)

test-mail:
	uv run python -m pytest -q --durations=15 $(MAIL_TESTS)

test-mail-release: test-mail test-tauri
	@echo "OK — offline/static mail gate зелёный. Следующий обязательный гейт: installed Legion + classic Outlook."

test-tauri:
	$(HOME)/.cargo/bin/cargo check --manifest-path desktop/tauri/src-tauri/Cargo.toml

smeta-base:
	uv run python -m tools.build_smeta_structured_base
	uv run python -m tools.build_smeta_service_rag

smeta-base-source:
	uv run python -m tools.gesn_unify_base
	$(MAKE) smeta-base

smeta-base-update:
	uv run python -m tools.gesn_update_from_fgis $(SMETA_BASE_UPDATE_ARGS)

smoke-active-artifacts:
	uv run python -m tools.smeta_release_baseline verify-root --root .

smoke-smeta-rerank:
	uv run python -m tools.smeta_rerank_ab_probe --require-ok \
		--query "монтаж блока аварийного питания светильника" \
		--query "монтаж патч панели 24 порта" \
		--report-path artifacts/smeta_rerank_ab_smoke.json

smoke-basic:
	uv run python tools/basic_function_smoke.py $(SMOKE_ARGS)

# Release/ship путь обязан считать P1 блокером; ручной dev-smoke остаётся неблокирующим для P1.
smoke-basic-release:
	uv run python tools/basic_function_smoke.py --release $(SMOKE_ARGS)

public-check:
	uv run python tools/publication_check.py

# Быстрый prod-гейт без деплоя: для малых итераций внутри версии.
ship-check: verify test-focused test-rag-core smoke-active-artifacts smoke-smeta-rerank smoke-basic-release
	@echo ""
	@echo "== ship-check ЗЕЛЁНЫЙ: verify → test-focused → test-rag-core → active artifacts → smoke-basic."

# Полный prod-гейт без деплоя: запускать на границе версии/релиза и перед большими изменениями.
ship-full-check: verify test smoke-active-artifacts smoke-smeta-rerank smoke-basic-release
	@echo ""
	@echo "== ship-full-check ЗЕЛЁНЫЙ: verify → test → active artifacts → smoke-basic."

deploy-runtime:
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

# Быстрый выкат: версия/леджер должны быть обновлены в этом же изменении ДО запуска.
ship: ship-check deploy-runtime post-deploy-smoke
	@echo ""
	@echo "== ship ЗЕЛЁНЫЙ: код проверен, runtime обновлён, post-deploy smoke прошёл."

# Полный выкат версии: длинную сюиту гоняем на границе версии, а не на каждой мелкой UI-итерации.
ship-full: ship-full-check deploy-runtime post-deploy-smoke
	@echo ""
	@echo "== ship-full ЗЕЛЁНЫЙ: полный gate, runtime обновлён, post-deploy smoke прошёл."

patch-release:
	uv run python tools/patch_release.py $(PATCH_RELEASE_ARGS)
