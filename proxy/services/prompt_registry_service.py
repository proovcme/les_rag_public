"""Central prompt registry for LES chat modes."""

from __future__ import annotations

from typing import Any

from proxy.services.notebook_service import gesn_notebook_prompt_excerpt

LES_SYSTEM_PROMPT = (
    "Ты — Л.Е.С., инженерный evidence-harness для строительных задач. "
    "Модель связывает смысл, выбирает workflow и объясняет; код считает, проверяет единицы, "
    "агрегирует таблицы и фиксирует MISSING/BLOCKED. "
    "Число без происхождения не является результатом. "
    "Блокноты/паспорта используй как навигацию и фон, но не как evidence."
)

MODE_PROMPTS: dict[str, str] = {
    "smeta": (
        "Режим «Смета»: разложи объект на проверяемые работы и вызови инструменты. "
        "Не придумывай коды ГЭСН, объёмы, коэффициенты и деньги. "
        "Если данных нет, оставь slots пустыми: харнесс запросит параметры."
    ),
    "rag": (
        "Режим RAG: отвечай только по найденному контексту документов. "
        "Если источника нет, скажи, каких данных не хватает."
    ),
    "normcontrol": (
        "Режим нормоконтроля: связывай требования, найденные признаки и замечания. "
        "Финальное инженерное решение остаётся за человеком."
    ),
    "free": (
        "Свободный режим: отвечай прямо, но явно отделяй общие знания от проверенных источников."
    ),
    "kp": (
        "Режим КП: готовь структуру коммерческого предложения только на основе подтверждённых позиций."
    ),
}


def mode_prompt(mode: str) -> str:
    return MODE_PROMPTS.get((mode or "").strip().lower(), "")


def build_mode_system_prompt(mode: str, *, notebook_context: str = "", extra: str = "") -> str:
    parts = [LES_SYSTEM_PROMPT]
    mp = mode_prompt(mode)
    if mp:
        parts.append(mp)
    if notebook_context:
        parts.append(notebook_context.strip())
    if extra:
        parts.append(extra.strip())
    return "\n\n".join(p for p in parts if p)


def build_smeta_batch_system_prompt(tool_contract: str, *, notebook_context: str | None = None) -> str:
    nb = notebook_context if notebook_context is not None else gesn_notebook_prompt_excerpt()
    return build_mode_system_prompt(
        "smeta",
        notebook_context=nb,
        extra=tool_contract,
    )


def prompt_registry_snapshot() -> dict[str, Any]:
    return {
        "schema": "prompt_registry_v1",
        "common": LES_SYSTEM_PROMPT,
        "modes": dict(MODE_PROMPTS),
    }
