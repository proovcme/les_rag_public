"""Маршрутизация локал/облако по чувствительности данных (ADR-9) + учёт расходов.

ADR-9: облако — только OpenRouter/OpenAI. Данные размечены чувствительностью на
датасете:

* ``P0`` — local-only (почта, договоры, персональные данные) — **в облако нельзя**;
* ``P1`` — cloud-ok (нормативка, открытые справочники);
* ``P2`` — cloud-ok-с-согласия (чертежи, данные проектов) — нужен явный consent.

Облако недоступно → деградация на локальный fallback, не отказ. Числа, решения и
суммы расходов считает алгоритм, не LLM (ADR-11) — здесь только pure-функции, без
сетевого I/O, чтобы политику можно было покрыть офлайн-тестами.

Дефолт чувствительности — **P0** (fail-closed): немаркированный датасет считается
приватным и в облако не уходит, пока оператор явно не пометит его P1/P2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping

# Провайдеры, физически отправляющие данные за пределы машины (ADR-9 — только эти два).
CLOUD_PROVIDERS = frozenset(
    {"openrouter", "openai", "openai-compatible", "openai_compatible"}
)
# Локальные провайдеры, конкурирующие с MLX за RAM/Metal — на тесной памяти
# их безопаснее свести к MLX (полевой вывод W3.3: ollama рядом с MLX → swap).
LOCAL_RAM_COMPETITORS = frozenset({"ollama", "lemonade"})

_VALID_SENSITIVITY = ("P0", "P1", "P2")
# Чем меньше индекс — тем строже (P0 строжайший). Используется в most_restrictive.
_RESTRICTIVENESS = {"P0": 0, "P2": 1, "P1": 2}


def is_cloud_provider(provider: str | None) -> bool:
    return (provider or "").strip().lower() in CLOUD_PROVIDERS


def normalize_sensitivity(value: object) -> str:
    """Любое значение → P0/P1/P2; мусор и пусто → P0 (fail-closed)."""
    token = str(value or "").strip().upper()
    if token in _VALID_SENSITIVITY:
        return token
    # Терпим формы «p1», «P1 cloud-ok», «уровень p2».
    for level in _VALID_SENSITIVITY:
        if level in token:
            return level
    return "P0"


def most_restrictive(sensitivities: Iterable[object]) -> str:
    """Самый строгий уровень среди задействованных датасетов.

    Пустой набор → P0: если непонятно, чьи это данные, считаем приватными.
    """
    levels = [normalize_sensitivity(s) for s in sensitivities]
    if not levels:
        return "P0"
    return min(levels, key=lambda lvl: _RESTRICTIVENESS[lvl])


def cloud_allowed(sensitivities: Iterable[object], *, consent: bool = False) -> bool:
    """Можно ли отправить эту выборку в облако.

    P0 → никогда. P2 → только при явном consent. P1 → да.
    """
    level = most_restrictive(sensitivities)
    if level == "P0":
        return False
    if level == "P2":
        return bool(consent)
    return True


@dataclass(frozen=True)
class RoutingDecision:
    provider: str
    is_cloud: bool
    downgraded: bool
    reason: str
    sensitivity: str


def decide_provider(
    configured_provider: str,
    sensitivities: Iterable[object],
    *,
    consent: bool = False,
    local_fallback: str = "mlx",
) -> RoutingDecision:
    """Финальный провайдер с учётом чувствительности данных.

    Если настроено облако, но политика не разрешает — принудительно локальный
    fallback. Локальные провайдеры пропускаются как есть (политика их не трогает).
    """
    provider = (configured_provider or "mlx").strip().lower() or "mlx"
    level = most_restrictive(sensitivities)
    if not is_cloud_provider(provider):
        return RoutingDecision(provider, False, False, "", level)
    if cloud_allowed(sensitivities, consent=consent):
        return RoutingDecision(provider, True, False, "", level)
    if level == "P2":
        reason = (
            f"данные P2 требуют согласия — облако {provider} запрещено без consent, "
            f"fallback на {local_fallback}"
        )
    else:
        reason = (
            f"данные {level} (local-only) — облако {provider} физически запрещено, "
            f"fallback на {local_fallback}"
        )
    return RoutingDecision(local_fallback, False, True, reason, level)


def memory_aware_provider(
    provider: str,
    *,
    available_gb: float | None,
    threshold_gb: float,
    local_fallback: str = "mlx",
) -> tuple[str, str]:
    """RAM-осознанный выбор локального провайдера (полевой вывод W3.3).

    Если выбран локальный конкурент MLX за память (ollama/lemonade) и свободной
    RAM меньше порога — сводим к MLX, который управляет своей памятью сам
    (TTL-выгрузка, metal-семафор). Облако и так не ест локальную RAM — не трогаем.
    Возвращает (provider, reason|"").
    """
    name = (provider or "").strip().lower()
    if name not in LOCAL_RAM_COMPETITORS:
        return name or "mlx", ""
    if available_gb is None or threshold_gb <= 0:
        return name, ""
    if available_gb < threshold_gb:
        return (
            local_fallback,
            f"свободной RAM {available_gb:.1f}ГБ < {threshold_gb:.1f}ГБ — "
            f"провайдер {name} сведён к {local_fallback} (защита от swap)",
        )
    return name, ""


# --- Учёт расходов облака (токены → $) -------------------------------------

# Цены за 1M токенов вход/выход (срез «Рекомендации по моделям», июнь 2026).
# Сопоставление по подстроке имени модели; перекрывается через env LES_CLOUD_PRICES.
DEFAULT_PRICE_TABLE: dict[str, tuple[float, float]] = {
    "gpt-5.5": (5.0, 30.0),
    "gpt-5.4": (2.5, 15.0),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.0, 8.0),
}


def load_price_table_from_env(env: Mapping[str, str] | None = None) -> dict[str, tuple[float, float]]:
    """Слить дефолтную таблицу цен с переопределениями из env.

    Формат ``LES_CLOUD_PRICES="model:in/out,model2:in/out"`` — цены за 1M токенов.
    Кривые записи молча игнорируются (цена не должна ронять чат).
    """
    table = dict(DEFAULT_PRICE_TABLE)
    raw = (env or os.environ).get("LES_CLOUD_PRICES", "").strip()
    if not raw:
        return table
    for item in raw.split(","):
        item = item.strip()
        if not item or ":" not in item:
            continue
        model, _, prices = item.partition(":")
        in_out = prices.replace(" ", "").split("/")
        if len(in_out) != 2:
            continue
        try:
            table[model.strip().lower()] = (float(in_out[0]), float(in_out[1]))
        except ValueError:
            continue
    return table


def _price_for(model: str, table: Mapping[str, tuple[float, float]]) -> tuple[float, float] | None:
    name = (model or "").strip().lower()
    if not name:
        return None
    if name in table:
        return table[name]
    # Сопоставление по подстроке: «openai/gpt-5.5» → «gpt-5.5».
    for key, price in table.items():
        if key in name:
            return price
    return None


def estimate_cost_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    price_table: Mapping[str, tuple[float, float]] | None = None,
) -> float:
    """Оценка стоимости одного облачного вызова в долларах.

    Неизвестная модель → 0.0 (считаем токены, но в $ не переводим — лучше
    недооценить, чем выдумать цену). Локальные вызовы сюда не приходят.
    """
    table = price_table if price_table is not None else DEFAULT_PRICE_TABLE
    price = _price_for(model, table)
    if price is None:
        return 0.0
    in_per_1m, out_per_1m = price
    return (max(0, prompt_tokens) * in_per_1m + max(0, completion_tokens) * out_per_1m) / 1_000_000.0
