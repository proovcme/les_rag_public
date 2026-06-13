"""W3.3 — политика маршрутизации локал/облако (ADR-9) + учёт расходов.

Pure-функции из backend.inference.routing: офлайн, без сети и БД. Главная приёмка
карты — «задача с P0-датасетом физически не может уйти в облако» — закреплена здесь.
"""

from __future__ import annotations

from backend.inference.routing import (
    cloud_allowed,
    decide_provider,
    estimate_cost_usd,
    is_cloud_provider,
    load_price_table_from_env,
    memory_aware_provider,
    most_restrictive,
    normalize_sensitivity,
)


# --- классификация провайдеров ----------------------------------------------

def test_is_cloud_provider():
    assert is_cloud_provider("openrouter")
    assert is_cloud_provider("openai")
    assert is_cloud_provider("openai_compatible")
    assert not is_cloud_provider("mlx")
    assert not is_cloud_provider("ollama")
    assert not is_cloud_provider("")
    assert not is_cloud_provider(None)


# --- нормализация и строгость -----------------------------------------------

def test_normalize_sensitivity_fail_closed():
    assert normalize_sensitivity("P1") == "P1"
    assert normalize_sensitivity("p2") == "P2"
    assert normalize_sensitivity("P0 local-only") == "P0"
    # мусор и пусто → P0 (приватно)
    assert normalize_sensitivity("") == "P0"
    assert normalize_sensitivity(None) == "P0"
    assert normalize_sensitivity("чёрт-те что") == "P0"


def test_most_restrictive():
    assert most_restrictive(["P1", "P2", "P1"]) == "P2"
    assert most_restrictive(["P1", "P0"]) == "P0"  # один P0 заражает всю выборку
    assert most_restrictive(["P1", "P1"]) == "P1"
    assert most_restrictive([]) == "P0"  # пусто → приватно


def test_cloud_allowed():
    assert cloud_allowed(["P1"]) is True
    assert cloud_allowed(["P0"]) is False
    assert cloud_allowed(["P2"]) is False  # без consent
    assert cloud_allowed(["P2"], consent=True) is True
    assert cloud_allowed(["P1", "P0"]) is False  # смешанная с P0 — нельзя
    assert cloud_allowed([]) is False  # пусто — нельзя


# --- ГЛАВНАЯ ПРИЁМКА: P0 не уходит в облако ---------------------------------

def test_p0_dataset_can_never_go_cloud():
    """Приёмка W3.3: настроено облако, данные P0 → принудительный локальный fallback."""
    for cloud in ("openrouter", "openai", "openai_compatible"):
        d = decide_provider(cloud, ["P0"], consent=True)  # даже с consent
        assert d.is_cloud is False
        assert d.downgraded is True
        assert d.provider == "mlx"
        assert "P0" in d.reason or "local-only" in d.reason


def test_mixed_selection_with_p0_blocks_cloud():
    d = decide_provider("openai", ["P1", "P2", "P0"], consent=True)
    assert d.provider == "mlx" and d.downgraded


def test_p1_goes_cloud():
    d = decide_provider("openrouter", ["P1"])
    assert d.is_cloud is True and d.downgraded is False
    assert d.provider == "openrouter"


def test_p2_needs_consent():
    no = decide_provider("openai", ["P2"], consent=False)
    assert no.downgraded and no.provider == "mlx"
    yes = decide_provider("openai", ["P2"], consent=True)
    assert yes.is_cloud and not yes.downgraded


def test_empty_sensitivities_fail_closed_for_cloud():
    d = decide_provider("openai", [], consent=True)
    assert d.provider == "mlx" and d.downgraded  # неизвестно чьи данные → не в облако


def test_local_provider_untouched_by_policy():
    for local in ("mlx", "ollama", "lemonade"):
        d = decide_provider(local, ["P0"])
        assert d.provider == local
        assert d.downgraded is False
        assert d.is_cloud is False


# --- memory-aware ------------------------------------------------------------

def test_memory_aware_downgrades_competitor_on_low_ram():
    prov, reason = memory_aware_provider("ollama", available_gb=3.0, threshold_gb=6.0)
    assert prov == "mlx" and reason


def test_memory_aware_keeps_competitor_with_enough_ram():
    prov, reason = memory_aware_provider("ollama", available_gb=12.0, threshold_gb=6.0)
    assert prov == "ollama" and reason == ""


def test_memory_aware_ignores_cloud_and_mlx():
    assert memory_aware_provider("openai", available_gb=1.0, threshold_gb=6.0) == ("openai", "")
    assert memory_aware_provider("mlx", available_gb=1.0, threshold_gb=6.0) == ("mlx", "")


def test_memory_aware_unknown_ram_keeps_provider():
    prov, reason = memory_aware_provider("ollama", available_gb=None, threshold_gb=6.0)
    assert prov == "ollama" and reason == ""


# --- учёт расходов -----------------------------------------------------------

def test_estimate_cost_known_model():
    # gpt-5.5: $5/$30 за 1M → 1M вход + 1M выход = $35
    assert estimate_cost_usd("gpt-5.5", 1_000_000, 1_000_000) == 35.0


def test_estimate_cost_substring_match():
    # провайдерный префикс не мешает сопоставлению
    assert estimate_cost_usd("openai/gpt-5.4", 1_000_000, 0) == 2.5


def test_estimate_cost_unknown_model_is_zero():
    assert estimate_cost_usd("some-local-model", 1_000_000, 1_000_000) == 0.0


def test_price_table_env_override():
    table = load_price_table_from_env({"LES_CLOUD_PRICES": "my-model:1/2, gpt-5.5:10/20"})
    assert table["my-model"] == (1.0, 2.0)
    assert table["gpt-5.5"] == (10.0, 20.0)  # дефолт перекрыт
    assert estimate_cost_usd("my-model", 1_000_000, 1_000_000, table) == 3.0


def test_price_table_env_garbage_ignored():
    table = load_price_table_from_env({"LES_CLOUD_PRICES": "broken,no-slash:5,ok:1/1"})
    assert table["ok"] == (1.0, 1.0)
    assert "broken" not in table
    assert "no-slash" not in table
