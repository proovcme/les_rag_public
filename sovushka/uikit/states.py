"""Pure feedback-state mapping shared by public Sovushka surfaces."""

from __future__ import annotations

from typing import Any


def feedback_state(
    kind: str,
    *,
    error_code: str = "",
    detail: str = "",
) -> dict[str, Any]:
    normalized = str(kind or "").strip().casefold()
    presets = {
        "loading": ("Загрузка", "Получаем данные и проверяем источники."),
        "empty": ("Пока пусто", "Добавьте данные или измените область поиска."),
        "error": (
            "Не удалось выполнить действие",
            "Повторите попытку или откройте технические детали.",
        ),
        "blocked": (
            "Поиск по источникам недоступен",
            "Ответ не сформирован, чтобы не подменять выбранные документы.",
        ),
    }
    if normalized not in presets:
        raise ValueError(f"Unknown feedback state: {kind}")
    title, default_detail = presets[normalized]
    return {
        "kind": normalized,
        "title": title,
        "detail": str(detail or default_detail),
        "error_code": str(error_code or ""),
    }
