"""ProfileResolver — единый контракт маршрутизации (ревью Codex §10.1A, §10.2).

Все источники выбора пути (явный режим, команда, retrieval-intent, LLM-router,
fallback) приводятся к ОДНОМУ результату `ProfileResolution`. В продукте есть четыре
явных профиля; при отсутствии или неизвестном режиме безопасный default — `agent`.
Конвейер уточняет резолюцию через `refine(...)`, когда конкретный источник выбрал
канал. Так «какой канал дёрнут» перестаёт быть неявным control-flow и становится
одним записанным контрактом (`query_route.profile`).

Инвариант (§10.3 №4): резолвер НЕ отвечает пользователю — только выбирает профиль.

Профиль — декларативная сущность (Codex §3): не «какая модель отвечает», а какой workflow
исполняется. Поля policy сейчас в основном ДОКУМЕНТИРУЮТ намерение (не все ещё энфорсятся) —
это контракт, по которому достраивается claim-валидация / эскалация / output-контракты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# pending сохраняется только для совместимости старых trace readers.
RouteSource = Literal[
    "explicit_mode", "command", "regex", "keyword", "llm_router", "fallback", "pending"
]

# executor: где исполняется. deterministic допустим только для control-plane команд;
# любой видимый профессиональный ответ проходит через модельный router/tool loop.
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


# Реестр профилей.  Runtime text/tool revisions live in chat_profile_service;
# this compact policy registry keeps routing and answer contracts explicit.
PROFILES: dict[str, Profile] = {
    "engineer": Profile(
        id="engineer", executor="router", role="инженер",
        tools=("doc_review", "retrieval", "citation_check"), grounded=True,
        validation_policy="require_citations", escalation_policy="on_tool_failure",
        failure_policy="say_no_data", output_contract="findings_table_v1",
    ),
    "search": Profile(
        id="search", executor="router", role="исследователь",
        tools=("retrieval", "citation_check", "table_lookup"), grounded=True,
        validation_policy="fail_warn", escalation_policy="on_low_confidence",
        failure_policy="say_no_data", output_contract="grounded_answer_v1",
    ),
    "agent": Profile(
        id="agent", executor="router", role="универсальный агент", tools=("*",), grounded=True,
        validation_policy="fail_warn", escalation_policy="on_tool_failure",
        failure_policy="say_no_data", output_contract="grounded_answer_v1",
    ),
    # Совместимый id старого профиля; активный route режима «Смета» отвечает model+RAG.
    "estimator": Profile(
        id="estimator", executor="cloud_large", role="сметчик",
        tools=("rag_context", "estimate_reasoning", "search_norm", "add_position"), grounded=True,
        validation_policy="require_numeric_provenance", escalation_policy="none",
        failure_policy="mark_preliminary", output_contract="estimate_preliminary_v1",
    ),
}

# Явный режим UI → профиль.
MODE_TO_PROFILE: dict[str, str] = {
    "search": "search",
    "rag": "search",
    "agent": "agent",
    "text": "agent",
    "free": "agent",
    "auto": "agent",
    "estimator": "estimator",
    "smeta": "estimator",
    "smeta_harness": "estimator",
    "engineer": "engineer",
    "review": "engineer",
    "doc_review": "engineer",
    "normcontrol": "engineer",
    "kp": "agent",
}


# ── channel → честный route_source. Объявлено ОДНОЙ таблицей, а не неявно
#    разбросано по control-flow chat.py: «какой канал → каким источником выбран». ──
CHANNEL_SOURCES: dict[str, RouteSource] = {
    "command": "command",
    # Модельный tool-selector выбрал инструмент.
    "agent": "llm_router",
    # Retrieval-intent сужает evidence, но не формулирует ответ.
    "table": "keyword", "mail": "keyword", "rag": "keyword",
    "field": "keyword",
}

# documentary-confidence по источнику (Codex §3: поля контракта документируют намерение)
_SOURCE_CONFIDENCE: dict[str, float] = {
    "explicit_mode": 1.0, "command": 1.0, "regex": 0.9,
    "llm_router": 0.8, "keyword": 0.6, "fallback": 0.0, "pending": 0.0,
}


def route_source_for_channel(channel: str) -> RouteSource:
    """Фактический канал → честный источник выбора. Неизвестный канал → fallback."""
    return CHANNEL_SOURCES.get((channel or "").strip().lower(), "fallback")


def confidence_for_source(source: str) -> float:
    return _SOURCE_CONFIDENCE.get(source, 0.0)


@dataclass
class ProfileResolution:
    """Единый результат маршрутизации (Codex §10.1A).

    Резолюция доуточняется конвейером через ``refine``: режим даёт профиль,
    а сработавший канал — честный `route_source`/`channel`.
    """
    profile_id: str
    route_source: RouteSource
    confidence: float
    reasons: list[str] = field(default_factory=list)
    channel: Optional[str] = None      # конкретный сработавший канал
    operation: Optional[str] = None    # операция канала (для trace)

    @property
    def profile(self) -> Profile:
        return PROFILES[self.profile_id]

    def refine(self, *, route_source: RouteSource, channel: str | None = None,
               operation: str | None = None, confidence: float | None = None,
               reason: str | None = None) -> "ProfileResolution":
        """Уточнить резолюцию выбранным каналом. Профиль НЕ меняется:
        фиксируем КАК принят маршрут и КАКОЙ канал сработал. Чейнится, мутирует и возвращает self."""
        self.route_source = route_source
        if channel is not None:
            self.channel = channel
        if operation is not None:
            self.operation = operation
        self.confidence = confidence if confidence is not None else confidence_for_source(route_source)
        if reason:
            self.reasons.append(reason)
        return self

    def as_trace(self) -> dict:
        """Компактный след для query_route / истории (воспроизводимость, Codex §15)."""
        p = self.profile
        t = {
            "profile_id": self.profile_id,
            "route_source": self.route_source,
            "confidence": round(self.confidence, 3),
            "executor": p.executor,
            "validation_policy": p.validation_policy,
            "output_contract": p.output_contract,
        }
        if self.channel:
            t["channel"] = self.channel
        if self.operation:
            t["operation"] = self.operation
        return t


def resolve(*, mode: str | None, question: str) -> ProfileResolution:
    """Запрос → explicit profile resolution; Agent is the product default."""
    m = (mode or "").strip().lower()
    if m in MODE_TO_PROFILE:
        pid = MODE_TO_PROFILE[m]
        return ProfileResolution(pid, "explicit_mode", 1.0, [f"user selected mode={m}"])
    if m:
        return ProfileResolution("agent", "fallback", 0.0, [f"unknown mode={m!r} → agent"])
    return ProfileResolution("agent", "fallback", 1.0, ["no explicit mode → default agent"])
