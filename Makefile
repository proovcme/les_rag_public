# Л.Е.С. (LES_v2) — dev-гейт. Офлайн, без живых сервисов (Qdrant/MLX не нужны).
# Требует uv. `make verify` — перед объявлением правки готовой.
.PHONY: verify test help

PKGS := backend proxy sovushka tools sovushka_ng.py proxy_server.py mlx_host.py

help:
	@echo "make verify  — офлайн-гейт: compileall (синтаксис) + pytest --collect-only (импорт-смоук тестов)"
	@echo "make test    — полная сюита pytest (часть тестов требует живых Qdrant/MLX)"

verify:
	uv run python -m compileall -q $(PKGS)
	uv run python -m pytest --collect-only -q
	@echo "OK — verify зелёный (синтаксис + импорт-смоук). Полные тесты: make test."

test:
	uv run python -m pytest
