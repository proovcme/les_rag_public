# Л.Е.С. (LES_v2) — dev-гейт. Офлайн, без живых сервисов (Qdrant/MLX не нужны).
# Требует uv. `make verify` — перед объявлением правки готовой.
.PHONY: verify test test-focused smoke-basic public-check ship-check ship-full-check deploy-runtime post-deploy-smoke ship ship-full help

PKGS := backend proxy sovushka tools sovushka_ng.py proxy_server.py mlx_host.py
SMOKE_ARGS ?=
FOCUS_TESTS ?= tests/test_sovushka_chat.py tests/test_static_assets.py tests/test_smeta_chat_service.py tests/test_estimate_harness.py tests/test_profile_resolver.py tests/test_doc_review_gost_21_101_2026.py tests/test_doc_review_chat_tool.py tests/test_title_block_extract.py tests/test_service_source_registry.py
POST_DEPLOY_RETRIES ?= 12
POST_DEPLOY_DELAY ?= 1

help:
	@echo "make verify       — офлайн-гейт: compileall (синтаксис) + pytest --collect-only (импорт-смоук)"
	@echo "make test         — полная сюита pytest (часть тестов требует живых Qdrant/MLX)"
	@echo "make test-focused — быстрые профильные pytest; переопредели FOCUS_TESTS='tests/test_x.py ...'"
	@echo "make smoke-basic  — L1 HTTP-smoke базовых функций против живого runtime (:8050/:8051)"
	@echo "make public-check — guardrail перед публичным git: tracked data/secrets/license/docs"
	@echo "make ship-check   — быстрый гейт без деплоя: verify → test-focused → smoke-basic"
	@echo "make ship-full-check — полный гейт без деплоя: verify → test → smoke-basic"
	@echo "make deploy-runtime — dev→runtime cp-деплой + restart + deploy stamp"
	@echo "make ship         — быстрый выкат: ship-check → deploy-runtime → post-deploy-smoke"
	@echo "make ship-full    — полный выкат версии: ship-full-check → deploy-runtime → post-deploy-smoke"

verify:
	uv run python -m compileall -q $(PKGS)
	uv run python -m pytest --collect-only -q
	@echo "OK — verify зелёный (синтаксис + импорт-смоук). Полные тесты: make test."

test:
	uv run python -m pytest

test-focused:
	uv run python -m pytest $(FOCUS_TESTS)

smoke-basic:
	uv run python tools/basic_function_smoke.py $(SMOKE_ARGS)

public-check:
	uv run python tools/publication_check.py

# Быстрый prod-гейт без деплоя: для малых итераций внутри версии.
ship-check: verify test-focused smoke-basic
	@echo ""
	@echo "== ship-check ЗЕЛЁНЫЙ: verify → test-focused → smoke-basic."

# Полный prod-гейт без деплоя: запускать на границе версии/релиза и перед большими изменениями.
ship-full-check: verify test smoke-basic
	@echo ""
	@echo "== ship-full-check ЗЕЛЁНЫЙ: verify → test → smoke-basic."

deploy-runtime:
	uv run python -m tools.deploy_to_runtime --apply --restart

post-deploy-smoke:
	@set -e; \
	for i in $$(seq 1 $(POST_DEPLOY_RETRIES)); do \
		if uv run python tools/basic_function_smoke.py $(SMOKE_ARGS); then \
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
