"""Human-readable projection of the next RIM session action.

The projection never mutates the session and never chooses an estimate
decision.  It only translates the durable state machine into one explicit UI
action.
"""

from __future__ import annotations

from typing import Any


def next_step_for_session(session: dict[str, Any]) -> dict[str, str]:
    """Return the single next user-visible action for a RIM session."""
    if session.get("pending_question_id"):
        return {
            "kind": "answer_question",
            "label": "Ответить на вопрос",
            "prompt": "",
            "detail": "Ответьте на открытый вопрос: ответ будет связан именно с ним.",
            "tab": "",
        }

    phase = str(session.get("phase") or "")
    mapping = str(session.get("mapping_status") or "not_started")
    scenario = str(session.get("scenario_status") or "not_started")
    pricing = str(session.get("pricing_status") or "unpriced")

    if phase == "intake":
        return {
            "kind": "agent_turn",
            "label": "Разобрать файл",
            "prompt": "Продолжи разбор загруженного файла.",
            "detail": "Qwen преобразует источник в проверяемую ВОР и задаст только необходимый вопрос.",
            "tab": "vor",
        }
    if mapping == "not_started":
        return {
            "kind": "agent_turn",
            "label": "Подобрать нормы и рассчитать",
            "prompt": "Подбери нормы и подготовь черновик ЛСР.",
            "detail": "Qwen продолжит typed-подбор норм; код проверит ссылки, единицы и рассчитает черновик.",
            "tab": "mapping",
        }
    if mapping in {"candidates_ready", "mapping_selected"}:
        return {
            "kind": "agent_turn",
            "label": "Продолжить проверку и расчёт",
            "prompt": "Продолжи проверку mapping и подготовь черновик ЛСР.",
            "detail": "Сохранённый mapping будет продолжен с global review без повторного поиска всех строк.",
            "tab": "mapping",
        }
    if mapping in {"mapping_globally_reviewed", "mapping_locked"} and pricing not in {
        "priced_draft",
        "priced_final",
    }:
        return {
            "kind": "agent_turn",
            "label": "Рассчитать черновик ЛСР",
            "prompt": "Рассчитай черновик ЛСР по проверенному mapping.",
            "detail": "Код построит canonical-сценарий и выполнит детерминированный расчёт.",
            "tab": "lsr",
        }
    if scenario == "ready" and pricing not in {"priced_draft", "priced_final"}:
        return {
            "kind": "calculate",
            "label": "Рассчитать черновик ЛСР",
            "prompt": "",
            "detail": "Сценарий готов; требуется детерминированный расчёт.",
            "tab": "lsr",
        }
    if pricing == "priced_draft":
        return {
            "kind": "review_draft",
            "label": "Проверить черновик ЛСР",
            "prompt": "",
            "detail": "Черновик рассчитан. Проверьте его перед финальной блокировкой.",
            "tab": "lsr",
        }
    if pricing == "priced_final":
        return {
            "kind": "complete",
            "label": "Финальная ЛСР готова",
            "prompt": "",
            "detail": "Расчёт финализирован и доступен для выгрузки.",
            "tab": "final",
        }
    return {
        "kind": "blocked",
        "label": "Проверить рабочую таблицу",
        "prompt": "",
        "detail": "Следующий шаг заблокирован текущими замечаниями или неполными решениями.",
        "tab": "requirements",
    }
