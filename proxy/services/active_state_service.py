"""Universal active task state for LES modules.

Active state is working memory, not evidence. It helps short follow-up commands
continue the current task, while facts and numbers still require sources or trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ActiveState:
    module_id: str
    task: str
    input_type: str = ""
    last_action: str = ""
    current_result: str = ""
    accepted_decisions: list[str] = field(default_factory=list)
    open_branches: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    current_objects: list[dict[str, Any]] = field(default_factory=list)
    status: str = "draft"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "task": self.task,
            "input_type": self.input_type,
            "last_action": self.last_action,
            "current_result": self.current_result,
            "accepted_decisions": list(self.accepted_decisions),
            "open_branches": list(self.open_branches),
            "exclusions": list(self.exclusions),
            "assumptions": list(self.assumptions),
            "current_objects": list(self.current_objects),
            "status": self.status,
            "updated_at": self.updated_at,
        }


class ActiveStateStore:
    """Small in-memory state store used by tests and lightweight runtime glue."""

    def __init__(self) -> None:
        self._states: dict[str, ActiveState] = {}

    def get(self, session_id: str) -> ActiveState | None:
        return self._states.get(str(session_id))

    def set(self, session_id: str, state: ActiveState) -> ActiveState:
        state.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._states[str(session_id)] = state
        return state

    def patch(self, session_id: str, **changes: Any) -> ActiveState:
        cur = self.get(session_id)
        if cur is None:
            cur = ActiveState(
                module_id=str(changes.pop("module_id", "general_project_rag")),
                task=str(changes.pop("task", "")),
            )
        for key, value in changes.items():
            if hasattr(cur, key):
                setattr(cur, key, value)
        return self.set(session_id, cur)

    def clear(self, session_id: str) -> None:
        self._states.pop(str(session_id), None)


def active_state_from_dict(data: dict[str, Any] | None) -> ActiveState | None:
    if not isinstance(data, dict) or not data.get("module_id"):
        return None
    return ActiveState(
        module_id=str(data.get("module_id") or "general_project_rag"),
        task=str(data.get("task") or ""),
        input_type=str(data.get("input_type") or ""),
        last_action=str(data.get("last_action") or ""),
        current_result=str(data.get("current_result") or ""),
        accepted_decisions=[str(x) for x in data.get("accepted_decisions") or []],
        open_branches=[str(x) for x in data.get("open_branches") or []],
        exclusions=[str(x) for x in data.get("exclusions") or []],
        assumptions=[str(x) for x in data.get("assumptions") or []],
        current_objects=[dict(x) for x in data.get("current_objects") or [] if isinstance(x, dict)],
        status=str(data.get("status") or "draft"),
        updated_at=str(data.get("updated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )


def render_active_state(state: ActiveState | dict[str, Any] | None) -> str:
    """Render active state for the model as working memory, not as proof."""
    obj = active_state_from_dict(state) if isinstance(state, dict) else state
    if obj is None:
        return ""

    def _line(label: str, value: Any) -> str:
        if isinstance(value, list):
            text = "; ".join(str(x) for x in value if str(x).strip())
        else:
            text = str(value or "").strip()
        return f"{label}: {text}" if text else f"{label}: —"

    object_lines = []
    for idx, item in enumerate(obj.current_objects, 1):
        title = item.get("title") or item.get("name") or item.get("id") or f"объект {idx}"
        status = item.get("status") or ""
        object_lines.append(f"{idx}. {title}" + (f" ({status})" if status else ""))

    return "\n".join([
        "Активное состояние задачи.",
        "Используй как рабочую память; факты и числа проверяй по источникам или расчётной трассе.",
        _line("Модуль", obj.module_id),
        _line("Задача", obj.task),
        _line("Тип входа", obj.input_type),
        _line("Последнее действие", obj.last_action),
        _line("Текущий результат", obj.current_result),
        _line("Принятые решения", obj.accepted_decisions),
        _line("Открытые развилки", obj.open_branches),
        _line("Исключения/ограничения", obj.exclusions),
        _line("Допущения", obj.assumptions),
        "Текущие таблицы/объекты:",
        "\n".join(object_lines) if object_lines else "—",
        _line("Статус", obj.status),
    ])
