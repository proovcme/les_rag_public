"""Выбор имени модели для совместимого хоста: роль вместо переменной окружения.

Реальный отказ 09.09: служебные вызовы чата слали адаптеру имя MLX-модели, адаптер
затирал его своим `LEMONADE_MODEL` (устаревшая Carnice), вендор поднимал вторую
35B-модель на 11,17 ГБ, свободная память падала до 1,8 ГБ и чат отклонялся с 503.
"""

from __future__ import annotations

from extensions.lemonade.role_model import RoleModelCache, select_chat_model


CATALOGUE = (
    "Qwen3.6-35B-A3B-GGUF-UD-IQ2_XXS-unsloth",
    "Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S",
    "qwen3.5-9b-FLM",
)
ROLE = "Qwen3.6-35B-A3B-GGUF-UD-IQ2_XXS-unsloth"


def test_unknown_requested_model_falls_back_to_the_selected_role():
    """Имя MLX-модели вендору неизвестно — отправляем модель роли, а не окружение."""
    assert select_chat_model(
        "mlx-community/Qwen3.5-9B-OptiQ-4bit",
        catalogue=CATALOGUE,
        role_model=ROLE,
        fallback="Carnice-Qwen3.6-MoE-35B-A3B-i1-GGUF-IQ2_S",
    ) == ROLE


def test_empty_request_uses_the_selected_role():
    assert select_chat_model("", catalogue=CATALOGUE, role_model=ROLE, fallback="qwen3.5-9b-FLM") == ROLE


def test_known_requested_model_is_respected():
    """Явно названная и существующая у вендора модель больше не переписывается."""
    assert select_chat_model(
        "qwen3.5-9b-FLM", catalogue=CATALOGUE, role_model=ROLE, fallback=""
    ) == "qwen3.5-9b-FLM"


def test_requested_model_matches_catalogue_case_and_latest_suffix():
    assert select_chat_model(
        "QWEN3.5-9B-FLM:latest", catalogue=CATALOGUE, role_model=ROLE, fallback=""
    ) == "qwen3.5-9b-FLM"


def test_environment_is_only_the_last_resort():
    """Без реестра остаётся окружение — но именно последним, а не первым."""
    assert select_chat_model(
        "", catalogue=CATALOGUE, role_model="", fallback="qwen3.5-9b-FLM"
    ) == "qwen3.5-9b-FLM"
    assert select_chat_model("", catalogue=(), role_model="", fallback="") == ""


def test_empty_catalogue_does_not_promote_an_unknown_request():
    """Каталог недоступен — довериться можно только роли, а не присланному имени."""
    assert select_chat_model(
        "mlx-community/Qwen3.5-9B-OptiQ-4bit", catalogue=(), role_model=ROLE, fallback=""
    ) == ROLE


def test_role_cache_reuses_value_and_refreshes_after_ttl():
    calls: list[int] = []
    now = {"value": 100.0}

    def loader() -> str:
        calls.append(1)
        return f"model-{len(calls)}"

    cache = RoleModelCache(loader, ttl_seconds=5.0, clock=lambda: now["value"])
    assert cache.get() == "model-1"
    now["value"] = 103.0
    assert cache.get() == "model-1"
    assert len(calls) == 1

    now["value"] = 106.0
    assert cache.get() == "model-2"
    assert len(calls) == 2


def test_role_cache_keeps_last_known_value_when_registry_fails():
    """Недоступный реестр не должен обнулять имя — иначе запрос уйдёт без модели."""
    state = {"fail": False}

    def loader() -> str:
        if state["fail"]:
            raise RuntimeError("registry locked")
        return ROLE

    cache = RoleModelCache(loader, ttl_seconds=0.0, clock=lambda: 0.0)
    assert cache.get() == ROLE
    state["fail"] = True
    assert cache.get() == ROLE


def test_role_cache_returns_empty_string_before_any_success():
    cache = RoleModelCache(lambda: (_ for _ in ()).throw(RuntimeError("нет базы")))
    assert cache.get() == ""
