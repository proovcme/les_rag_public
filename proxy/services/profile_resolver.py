"""ProfileResolver — единый контракт маршрутизации (ревью Codex §10.1A, §10.2).

Все источники выбора пути (явный режим, команда, regex, keyword-каскад, LLM-router,
fallback) приводятся к ОДНОМУ результату `ProfileResolution`. Формализован ЯВНЫЙ РЕЖИМ
(mode→Profile) И auto-путь: когда режим не задан, `resolve` возвращает профиль `auto` в
состоянии `pending` («какой задачу решаю — ещё не решено»), а конвейер чата уточняет
резолюцию через `refine(...)`, как только конкретный источник (command/regex/keyword/
llm_router/fallback) выбрал канал. Так «какой канал дёрнут» перестаёт быть неявным
control-flow и становится одним записанным контрактом (`query_route.profile`).

Инвариант (§10.3 №4): резолвер НЕ отвечает пользователю — только выбирает профиль.

Профиль — декларативная сущность (Codex §3): не «какая модель отвечает», а какой workflow
исполняется. Поля policy сейчас в основном ДОКУМЕНТИРУЮТ намерение (не все ещё энфорсятся) —
это контракт, по которому достраивается claim-валидация / эскалация / output-контракты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# pending = режим не задан, конкретный источник резолвится ниже по конвейеру (refine).
RouteSource = Literal[
    "explicit_mode", "command", "regex", "keyword", "llm_router", "fallback", "pending"
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


# Реестр профилей.
PROFILES: dict[str, Profile] = {
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
    # Модель первична: она раскладывает объект → вызывает инструменты; харнесс проверяет числа.
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
    "smeta": "estimate_harness",
    "review": "normcontrol",
    "kp": "kp_stub",
    "rag": "grounded_rag",
    "free": "free_llm",
    "smeta_harness": "estimate_harness",
}


# ── channel → честный route_source (auto-путь). Объявлено ОДНОЙ таблицей, а не неявно
#    разбросано по control-flow chat.py: «какой канал → каким источником выбран». ──
CHANNEL_SOURCES: dict[str, RouteSource] = {
    "command": "command",
    # детерминированные regex/SQL-каналы (0 LLM): первый сработавший — ответ
    "tasks": "regex", "preset": "regex", "asbuilt": "regex", "les_md": "regex",
    "doc_registry": "regex", "registry": "regex", "glossary": "regex", "smeta": "regex",
    "help": "regex", "field": "regex", "decision": "regex", "memory": "regex",
    "scope_clarification": "regex",
    # Ярус 2 / router_primary: локальная LLM выбрала инструмент
    "agent": "llm_router",
    # keyword-каскад query_router + детерминированные табличные/сводные каналы
    "table": "keyword", "mail": "keyword", "rag": "keyword",
    "reconcile": "keyword", "spec_to_bor": "keyword",
    "project_summary": "keyword", "outline": "keyword",
}

# documentary-confidence по источнику (Codex §3: поля контракта документируют намерение)
_SOURCE_CONFIDENCE: dict[str, float] = {
    "explicit_mode": 1.0, "command": 1.0, "regex": 0.9,
    "llm_router": 0.8, "keyword": 0.6, "fallback": 0.0, "pending": 0.0,
}


def route_source_for_channel(channel: str) -> RouteSource:
    """Канал auto-пути → честный источник выбора. Неизвестный канал → fallback."""
    return CHANNEL_SOURCES.get((channel or "").strip().lower(), "fallback")


def confidence_for_source(source: str) -> float:
    return _SOURCE_CONFIDENCE.get(source, 0.0)


@dataclass
class ProfileResolution:
    """Единый результат маршрутизации (Codex §10.1A).

    Для auto-пути резолюция доуточняется конвейером через ``refine`` (см. модуль-докстринг):
    режим даёт профиль и `pending`, а сработавший канал — честный `route_source`/`channel`.
    """
    profile_id: str
    route_source: RouteSource
    confidence: float
    reasons: list[str] = field(default_factory=list)
    channel: Optional[str] = None      # конкретный сработавший канал (auto-путь)
    operation: Optional[str] = None    # операция канала (для trace)

    @property
    def profile(self) -> Profile:
        return PROFILES[self.profile_id]

    def refine(self, *, route_source: RouteSource, channel: str | None = None,
               operation: str | None = None, confidence: float | None = None,
               reason: str | None = None) -> "ProfileResolution":
        """Уточнить резолюцию выбранным каналом. Профиль НЕ меняется (auto остаётся auto):
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
    """Запрос → ProfileResolution. Приоритет: ЯВНЫЙ РЕЖИМ → иначе auto в состоянии `pending`.

    Без режима резолвер не угадывает источник (это была бы ложь в trace): он отдаёт профиль
    `auto`/`pending`, а конкретный источник проставляет конвейер через `refine`, когда канал
    реально выбран. Резолвер чистый и детерминированный — без сети и сайд-эффектов."""
    m = (mode or "").strip().lower()
    if m in MODE_TO_PROFILE:
        pid = MODE_TO_PROFILE[m]
        return ProfileResolution(pid, "explicit_mode", 1.0, [f"user selected mode={m}"])
    if m:
        # неизвестный режим — не падаем, идём общим путём
        return ProfileResolution("auto", "fallback", 0.0, [f"unknown mode={m!r} → auto"])
    return ProfileResolution("auto", "pending", 0.0, ["no explicit mode → pipeline resolves channel"])
