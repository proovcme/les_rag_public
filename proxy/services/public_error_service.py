"""Stable operator-facing chat errors without internal exception leakage."""

from __future__ import annotations

from typing import Any


_SERVER_ERRORS: dict[int, tuple[str, str]] = {
    500: (
        "INTERNAL_CHAT_ERROR",
        "Не удалось завершить запрос. Повторите попытку или откройте диагностику.",
    ),
    502: (
        "MODEL_UPSTREAM_ERROR",
        "Назначенная модель не смогла завершить запрос. Повторите попытку.",
    ),
    503: (
        "MODEL_SERVICE_UNAVAILABLE",
        "Сервис модели временно недоступен. Проверьте подключение или повторите запрос.",
    ),
    504: (
        "MODEL_TIMEOUT",
        "Истекло время ожидания ответа модели. Повторите запрос.",
    ),
}


def public_error_payload(*, status_code: int, detail: Any) -> dict[str, str]:
    """Return the only error fields allowed across the chat/UI boundary."""

    if isinstance(detail, dict):
        code = str(detail.get("code") or "").strip()
        message = str(detail.get("detail") or detail.get("message") or "").strip()
        if code and message:
            return {"code": code, "detail": message}

    if status_code >= 500:
        code, message = _SERVER_ERRORS.get(status_code, _SERVER_ERRORS[500])
        return {"code": code, "detail": message}

    message = str(detail or "Запрос отклонён").strip()
    return {"code": "REQUEST_REJECTED", "detail": message}
