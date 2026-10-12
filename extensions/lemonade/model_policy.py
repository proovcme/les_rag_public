"""Pure Lemonade model-option policy; no HTTP or persistence lives here."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Mapping


_FLASH_FLAG = re.compile(
    r"(?:[ \t]+|^)(?:--flash-attn|-fa)(?:=|\s+)(?:on|off|auto)(?=[ \t]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class FlashAttentionDecision:
    eligible: bool
    reason_code: str
    proposed_change: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proposed_change",
            MappingProxyType(dict(self.proposed_change)),
        )


def _force_flash_attention(arguments: Any) -> str:
    without_old = _FLASH_FLAG.sub("", str(arguments or "")).strip()
    return f"{without_old} --flash-attn on".strip()


def evaluate_flash_attention_policy(options: Mapping[str, Any]) -> FlashAttentionDecision:
    """Evaluate one factual Lemonade model-options response without mutating it."""
    recipe = str(options.get("recipe") or "").strip().casefold()
    if recipe == "flm":
        return FlashAttentionDecision(False, "flm_not_supported", {})
    if recipe != "llamacpp":
        return FlashAttentionDecision(False, "recipe_not_llamacpp", {})
    effective = options.get("effective")
    if not isinstance(effective, Mapping):
        return FlashAttentionDecision(False, "effective_options_missing", {})
    current_args = str(effective.get("llamacpp_args") or "").strip()
    proposed_args = _force_flash_attention(current_args)
    if proposed_args == current_args:
        return FlashAttentionDecision(False, "already_enabled", {})
    return FlashAttentionDecision(
        True,
        "change_required",
        {"llamacpp_args": proposed_args},
    )


_CARNICE_MODEL = re.compile(r"Carnice-Qwen3\.6-MoE-35B", re.IGNORECASE)

# Проверенные на Windows/Vulkan параметры запуска Carnice.
#
# ctx_size: ниже 16384 исполнение падает на пресет qwen-9b-restrictive (вход 6000),
# а реальные запросы LES дают 17-20 тыс. токенов входа плюс до 4096 на вывод.
# 32768 работает, но на интегрированной графике (AMD 890M, системная память) процесс
# занимает ~12,4 ГБ: при накоплении лишних llama-server возникает
# vk::Device::allocateMemory: ErrorOutOfDeviceMemory.
#
# temp 0.2: инженерные ответы должны быть воспроизводимыми. Влияние температуры на
# правдивость на 66 прогонах не подтвердилось, но разброс формулировок она даёт.
#
# preserve_thinking здесь НЕ задаётся: Lemonade добавляет его самостоятельно, а
# отключение рассуждений выполняет запрос LES через chat_template_kwargs.enable_thinking.
_CARNICE_RECIPE_OPTIONS: Mapping[str, Any] = MappingProxyType({
    "ctx_size": 32768,
    "llamacpp_args": (
        "--min-p 0.00 --repeat-penalty 1.0 --temp 0.2 "
        "--top-k 20 --top-p 0.95 --flash-attn on"
    ),
    "merge_args": True,
    "pinned": False,
})

# Выбранная роль ответа на 08.09.2026. Значения — снятые с работающей установки, а не
# перенесённые с Carnice: у XXS дополнительно закреплены `--parallel 1` и таймеры вендора.
#
# --parallel 1: несколько слотов KV-кэша делят одно окно контекста, и при 28-32 тыс.
# входа запрос перестаёт помещаться. Заметного выигрыша по памяти переход 4 -> 1 не дал,
# но предсказуемость окна важнее.
#
# evict/downsize_idle_timeout: политика простоя принадлежит вендору. Она зафиксирована
# здесь только потому, что оператор выбрал эти значения вручную; adapter idle-unload и
# эти таймеры остаются двумя разными механизмами, единый владелец пока не назначен.
_XXS_RECIPE_OPTIONS: Mapping[str, Any] = MappingProxyType({
    "ctx_size": 32768,
    "downsize_idle_timeout": 60,
    "evict_idle_timeout": 300,
    "llamacpp_args": (
        "--min-p 0.00 --repeat-penalty 1.0 --temp 0.2 "
        "--top-k 20 --top-p 0.95 --flash-attn on --parallel 1"
    ),
    "merge_args": True,
    "pinned": False,
})

# Эмбеддер уходит из памяти раньше модели ответа. Обе модели держались по 300 с и
# вместе занимали около 14 ГБ из 31; на KV-кэш при декодировании места не оставалось,
# и вендор отвечал `decode() failed: vk::Device::allocateMemory: ErrorOutOfDeviceMemory`.
# Загрузка эмбеддера стоит секунды, модели ответа — минуты, поэтому короткий таймер
# именно у него.
_EMBEDDING_RECIPE_OPTIONS: Mapping[str, Any] = MappingProxyType({
    "ctx_size": 2048,
    "evict_idle_timeout": 60,
    "llamacpp_backend": "vulkan",
})

# Точные идентификаторы, а не семейство: у соседних квантований своя проверенная
# конфигурация, и распространять одну на все Qwen3.6-35B нельзя.
_EXACT_RECIPE_OPTIONS: Mapping[str, Mapping[str, Any]] = MappingProxyType({
    "qwen3.6-35b-a3b-gguf-ud-iq2_xxs-unsloth": _XXS_RECIPE_OPTIONS,
    # Модель ответа с 17.09: сравнение на сметном запросе прохода 4 (13,7 ГБ, 18 ток/с,
    # без подстановки чужого товара ради цены). Проверенный профиль тот же, что у XXS.
    "qwen3.6-35b-a3b-gguf-ud-iq2_m": _XXS_RECIPE_OPTIONS,
    "qwen3-embedding-0.6b-gguf": _EMBEDDING_RECIPE_OPTIONS,
})


def recommended_recipe_options(model_id: str) -> dict[str, Any]:
    """Эталонные опции запуска модели, принадлежащие модулю, а не кэшу Lemonade.

    `~/.cache/lemonade/recipe_options.json` живёт вне репозитория и теряется при
    переустановке: модель, отсутствующая там, стартует без ctx_size, из-за чего снимок
    возможностей не получает observed_context_tokens. Эта функция — источник истины,
    по которому такой файл можно восстановить или сверить.

    Сначала точное совпадение идентификатора, затем семейство Carnice. Модель, для
    которой проверенных значений нет, возвращает пустой словарь: выдумывать настройки
    запуска по похожему имени опаснее, чем оставить вендорские умолчания.
    """
    normalized = str(model_id or "").strip().casefold()
    exact = _EXACT_RECIPE_OPTIONS.get(normalized)
    if exact is not None:
        return dict(exact)
    if not _CARNICE_MODEL.search(str(model_id or "")):
        return {}
    return dict(_CARNICE_RECIPE_OPTIONS)


def plan_recipe_options_bootstrap(
    existing: Mapping[str, Any],
    catalogue_model_ids: Any,
) -> dict[str, Any]:
    """Спланировать восполнение `recipe_options.json`, не переписывая чужие решения.

    Файл живёт вне репозитория и теряется при переустановке; модель без записи стартует
    без `ctx_size`, из-за чего снимок возможностей теряет `observed_context_tokens`,
    а исполнение падает на пресет qwen-9b-restrictive. Здесь только план: что добавить
    (`add`) и где ручная настройка расходится с проверенной (`differs`). Существующие
    записи не изменяются — оператор мог править их намеренно.
    """
    current = dict(existing or {})
    add: dict[str, Any] = {}
    differs: dict[str, Any] = {}
    for model_id in catalogue_model_ids or ():
        recommended = recommended_recipe_options(str(model_id or ""))
        if not recommended:
            continue
        # Встроенные модели вендор хранит под `builtin.`; второй ключ создал бы дубль
        # с расходящимися значениями, поэтому уважаем уже существующий.
        key = f"user.{model_id}"
        if key not in current and f"builtin.{model_id}" in current:
            key = f"builtin.{model_id}"
        present = current.get(key)
        if present is None:
            add[key] = recommended
            continue
        if not isinstance(present, Mapping):
            differs[key] = {"reason": "not_a_mapping"}
            continue
        mismatch = {
            field: {"current": present.get(field), "recommended": value}
            for field, value in recommended.items()
            if present.get(field) != value
        }
        if mismatch:
            differs[key] = mismatch
    return {"add": add, "differs": differs}


def apply_recipe_options_bootstrap(path: Any, catalogue_model_ids: Any) -> dict[str, Any]:
    """Восполнить `recipe_options.json` недостающими записями наших моделей.

    Файл принадлежит Lemonade и живёт вне репозитория: при переустановке он теряется,
    и модель стартует без `ctx_size`. Дописываем только отсутствующее, прежний файл
    сохраняем рядом с суффиксом `.bak-<timestamp>`. Существующие записи не изменяются:
    расхождения возвращаются в отчёте, решение по ним принимает оператор.
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    target = Path(path)
    existing: dict[str, Any] = {}
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            existing = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError) as error:
            return {"added": [], "differs": {}, "backup": None, "error": str(error)}

    plan = plan_recipe_options_bootstrap(existing, catalogue_model_ids)
    if not plan["add"]:
        return {"added": [], "differs": plan["differs"], "backup": None}

    backup_name = None
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_name = f"{target.name}.bak-{stamp}"
        target.with_name(backup_name).write_text(
            target.read_text(encoding="utf-8"), encoding="utf-8"
        )

    merged = {**existing, **plan["add"]}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(merged, ensure_ascii=False, indent=4, sort_keys=True), encoding="utf-8"
    )
    return {"added": sorted(plan["add"]), "differs": plan["differs"], "backup": backup_name}
