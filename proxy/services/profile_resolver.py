"""ProfileResolver — единый контракт маршрутизации (ревью Codex §10.1A, §10.2).

Все источники выбора пути (явный режим, команда, regex, keyword-каскад, LLM-router,
fallback) приводятся к ОДНОМУ результату `ProfileResolution`. Сейчас формализован первый
источник — ЯВНЫЙ РЕЖИМ из UI: он отображается в декларативный `Profile`. Остальные источники
(router/каскад) пока резолвятся ниже по конвейеру и помечаются профилем `auto`; их слияние в
этот же резолвер — следующий инкремент (поведение не меняем).

Инвариант (§10.3 №4): резолвер НЕ отвечает пользователю — только выбирает профиль.

Профиль — декларативная сущность (Codex §3): не «какая модель отвечает», а какой workflow
исполняется. Поля policy сейчас в основном ДОКУМЕНТИРУЮТ намерение (не все ещё энфорсятся) —
это контракт, по которому достраивается claim-валидация / эскалация / output-контракты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RouteSource = Literal[
    "explicit_mode", "command", "regex", "keyword", "llm_router", "fallback"
]

# executor: где исполняется. deterministic = 0 LLM (код); router = решает нижний слой.
Executor = Literal["deterministic", "local_small", "local_large", "cloud_large", "router", "none"]


@dataclass(frozen=True)
class Profile:
    """Декларативный профиль исполнения = {модель · роль · инструменты · политики · контракт}."""
    id: str
    executor: Executor
    role: str                       # роль/prompt-pack
    tools: tuple[str, ...]          # разрешённые инструменты ("*" = любой, решает router)
    grounded: bool                  # использует ли ретрив (заземление)
    validation_policy: str          # fail_open | fail_warn | require_citations | require_numeric_provenance
    escalation_policy: str          # none | on_low_confidence | on_tool_failure
    failure_policy: str             # say_no_data | ask_clarification | mark_preliminary
    output_contract: str            # id схемы вывода | "prose"


# Реестр профилей. Текущие режимы UI портированы 1:1 (поведение не меняется).
PROFILES: dict[str, Profile] = {
    "object_estimate": Profile(
        id="object_estimate", executor="deterministic", role="сметчик-калькулятор",
        tools=("object_estimate", "get_norm", "lsr_assembly"), grounded=False,
        validation_policy="require_numeric_provenance", escalation_policy="none",
        failure_policy="mark_preliminary", output_contract="estimate_table_v1",
    ),
    "normcontrol": Profile(
        id="normcontrol", executor="deterministic", role="нормоконтролёр",
        tools=("run_normcontrol",), grounded=False,
        validation_policy="fail_open", escalation_policy="none",
        failure_policy="say_no_data", output_contract="findings_table_v1",
    ),
    "kp_stub": Profile(
        id="kp_stub", executor="none", role="—", tools=(), grounded=False,
        validation_policy="fail_open", escalation_policy="none",
        failure_policy="say_no_data", output_contract="prose",
    ),
    "grounded_rag": Profile(
        id="grounded_rag", executor="router", role="эксперт-заземление",
        tools=("retrieval", "citation_check", "table_lookup"), grounded=True,
        validation_policy="fail_warn", escalation_policy="on_low_confidence",
        failure_policy="say_no_data", output_contract="grounded_answer_v1",
    ),
    "free_llm": Profile(
        id="free_llm", executor="local_large", role="вольный", tools=(), grounded=False,
        validation_policy="fail_open", escalation_policy="none",
        failure_policy="mark_preliminary", output_contract="prose",
    ),
    # ЭКСПЕРИМЕНТАЛЬНЫЙ ХАРНЕСС: модель раскладывает объект → дёргает инструменты (петля).
    # Рядом со старым object_estimate (YAML), не вместо. Числа из инструментов, не из модели.
    "estimate_harness": Profile(
        id="estimate_harness", executor="cloud_large", role="сметчик-харнесс",
        tools=("propose_schema", "search_norm", "add_position"), grounded=False,
        validation_policy="require_numeric_provenance", escalation_policy="none",
        failure_policy="mark_preliminary", output_contract="estimate_preliminary_v1",
    ),
    # auto — нет явного режима: путь решают router/каскад/RAG ниже по конвейеру.
    "auto": Profile(
        id="auto", executor="router", role="—", tools=("*",), grounded=True,
        validation_policy="fail_warn", escalation_policy="on_low_confidence",
        failure_policy="say_no_data", output_contract="auto",
    ),
}

# Явный режим UI → профиль.
MODE_TO_PROFILE: dict[str, str] = {
    "smeta": "object_estimate",
    "review": "normcontrol",
    "kp": "kp_stub",
    "rag": "grounded_rag",
    "free": "free_llm",
    "smeta_harness": "estimate_harness",
}


@dataclass
class ProfileResolution:
    """Единый результат маршрутизации (Codex §10.1A)."""
    profile_id: str
    route_source: RouteSource
    confidence: float
    reasons: list[str] = field(default_factory=list)

    @property
    def profile(self) -> Profile:
        return PROFILES[self.profile_id]

    def as_trace(self) -> dict:
        """Компактный след для query_route / истории (воспроизводимость, Codex §15)."""
        p = self.profile
        return {
            "profile_id": self.profile_id,
            "route_source": self.route_source,
            "confidence": round(self.confidence, 3),
            "executor": p.executor,
            "validation_policy": p.validation_policy,
        }


def resolve(*, mode: str | None, question: str) -> ProfileResolution:
    """Запрос → ProfileResolution. Сейчас приоритет: ЯВНЫЙ РЕЖИМ → иначе auto (router/каскад).

    Следующие инкременты добавят источники (command/regex/keyword/llm_router) ПЕРЕД auto,
    сохраняя контракт. Резолвер чистый и детерминированный — без сети и сайд-эффектов."""
    m = (mode or "").strip().lower()
    if m in MODE_TO_PROFILE:
        pid = MODE_TO_PROFILE[m]
        return ProfileResolution(pid, "explicit_mode", 1.0, [f"user selected mode={m}"])
    if m:
        # неизвестный режим — не падаем, идём общим путём
        return ProfileResolution("auto", "fallback", 0.0, [f"unknown mode={m!r} → auto"])
    return ProfileResolution("auto", "llm_router", 0.0, ["no explicit mode → router/cascade decides"])
