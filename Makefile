# Л.Е.С. (LES_v2) — dev-гейт. Офлайн, без живых сервисов (Qdrant/MLX не нужны).
# Требует uv. `make verify` — перед объявлением правки готовой.
.PHONY: verify test smoke-basic ship help

PKGS := backend proxy sovushka tools sovushka_ng.py proxy_server.py mlx_host.py
SMOKE_ARGS ?=

help:
	@echo "make verify       — офлайн-гейт: compileall (синтаксис) + pytest --collect-only (импорт-смоук)"
	@echo "make test         — полная сюита pytest (часть тестов требует живых Qdrant/MLX)"
	@echo "make smoke-basic  — L1 HTTP-smoke базовых функций против живого runtime (:8050/:8051)"
	@echo "make ship         — прод-гейт: verify → test → smoke-basic (зелёное = можно деплоить); см. docs/GUARDRAILS.md"

verify:
	uv run python -m compileall -q $(PKGS)
	uv run python -m pytest --collect-only -q
	@echo "OK — verify зелёный (синтаксис + импорт-смоук). Полные тесты: make test."

test:
	uv run python -m pytest

smoke-basic:
	uv run python tools/basic_function_smoke.py $(SMOKE_ARGS)

# Прод-гейт (docs/GUARDRAILS.md): прогнать все гейты ПЕРЕД деплоем. НЕ деплоит сам (рестарт proxy —
# явный шаг оператора). Зелёное → bump LES_VERSION + строка в docs/RELEASE_LEDGER.md, затем deploy.
ship: verify test smoke-basic
	@echo ""
	@echo "== ship-гейт ЗЕЛЁНЫЙ. Дальше вручную (docs/GUARDRAILS.md):"
	@echo "   1) bump LES_VERSION (proxy/services/version_service.py) + строка в docs/RELEASE_LEDGER.md"
	@echo "   2) uv run python -m tools.deploy_to_runtime --apply --restart"
	@echo "   3) make smoke-basic  (post-deploy)"
	@echo "   откат: git checkout <prev_commit> + deploy --apply ; данные — tools/restore_runtime.sh"
