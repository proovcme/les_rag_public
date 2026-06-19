"""agent_router_service.py — Ярус 2: чат сам выбирает инструмент (function-calling).

Когда детерминированные regex-каналы не сработали, LLM-роутер по описанию инструментов
выбирает ОДИН подходящий — но **исполняет существующий детерминированный обработчик**
(числа/действия считает код, не LLM, ADR-11). Это превращает Совушку из «набора каналов» в
агент над своими инструментами: спрашиваешь как угодно — она сама решает, что вызвать.

За флагом ``LES_AGENT_LOOP`` (по умолчанию off). Любой сбой/«none» → None → обычный путь
(RAG) как фолбэк. Ядро чат-пути не меняется — это аддитивная ступень перед RAG.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# Инструмент: имя, описание (для выбора моделью), обработчик(question, project_id) → dict|None.
def _h_asbuilt(q: str, pid: int):
    from proxy.services.asbuilt_chat_service import maybe_handle_asbuilt_query
    return maybe_handle_asbuilt_query(q, project_id=pid)


def _h_les_md(q: str, pid: int):
    from proxy.services.les_md_chat_service import maybe_handle_les_md_query
    return maybe_handle_les_md_query(q, project_id=pid)


def _h_registry(q: str, pid: int):
    from proxy.services.project_registry_chat_service import registry_answer
    return registry_answer()


def _h_field(q: str, pid: int):
    from proxy.services.field_intake_service import maybe_handle_field_command
    return maybe_handle_field_command(q, project_id=pid)


def _h_task(q: str, pid: int):
    from proxy.services.task_service import maybe_handle_task_command
    return maybe_handle_task_command(q, dataset_filter="", project_id=pid)


def _h_preset(q: str, pid: int):
    from proxy.services.preset_chat_service import maybe_handle_preset_query
    return maybe_handle_preset_query(q, project_id=pid)


_TOOLS: tuple[dict[str, Any], ...] = (
    {"name": "asbuilt", "handler": _h_asbuilt,
     "desc": "Извлечь фактически смонтированный объём из сканов исполнительных схем/чек-листов в указанной папке (нужен путь)."},
    {"name": "les_md", "handler": _h_les_md,
     "desc": "Понять папку: прочитать или собрать LES.md, привязать к проекту, дочитать договор/титул (нужен путь)."},
    {"name": "project_registry", "handler": _h_registry,
     "desc": "СПИСОК всех объектов/проектов ЛЕС (реестр, карта). НЕ для вопросов о содержании одного объекта."},
    {"name": "field", "handler": _h_field,
     "desc": "Записать полевой объём работ или дать свод по журналу объёмов."},
    {"name": "task", "handler": _h_task,
     "desc": "Поставить, закрыть или показать задачи."},
    {"name": "preset", "handler": _h_preset,
     "desc": "Переключить режим работы: local (всё локально) / cloud (облако) / mix; или показать текущий."},
    {"name": "none", "handler": None,
     "desc": "ЛЮБОЙ вопрос об информации/содержании/фактах (что известно про X, расскажи/объясни про X, "
             "справка по объекту) — обычный поиск по документам (RAG). Это выбор ПО УМОЛЧАНИЮ."},
)
_BY_NAME = {t["name"]: t for t in _TOOLS}


def _is_on() -> bool:
    return os.getenv("LES_AGENT_LOOP", "false").strip().lower() in ("1", "true", "yes", "on")


def _classify(question: str) -> str:
    """LLM выбирает имя инструмента (или 'none'). Best-effort; сбой → 'none'."""
    from proxy.services.les_md_service import _llm_text

    catalog = "\n".join(f"- {t['name']}: {t['desc']}" for t in _TOOLS)
    prompt = (
        "Ты — маршрутизатор инструментов строительной системы ЛЕС. Инструменты — ТОЛЬКО для "
        "ДЕЙСТВИЙ (извлечь объём, переключить режим, понять папку, записать объём, список объектов). "
        "Если оператор спрашивает ИНФОРМАЦИЮ или факты (что известно про X, расскажи/объясни про X, "
        "справка по объекту, какие требования) — это none (обычный поиск по документам). "
        "Сомневаешься — none. Выбери ОДИН инструмент или none. Верни ТОЛЬКО JSON {\"tool\": \"<имя>\"}.\n\n"
        f"Инструменты:\n{catalog}\n\nЗапрос: {question}"
    )
    raw = _llm_text(prompt, max_tokens=40)
    if not raw:
        return "none"
    m = re.search(r'"tool"\s*:\s*"([a-z_]+)"', raw)
    if m:
        return m.group(1)
    for name in _BY_NAME:  # модель могла вернуть просто имя
        if name in raw.lower():
            return name
    return "none"


def maybe_agent_route(question: str, *, project_id: int = 0) -> Optional[dict[str, Any]]:
    """Ярус 2: LLM выбирает инструмент → исполняет детерминированный обработчик. Off/сбой → None."""
    if not _is_on() or not (question or "").strip():
        return None
    try:
        name = _classify(question)
    except Exception as err:  # noqa: BLE001
        logger.warning("[AGENT] classify failed: %s", err)
        return None
    tool = _BY_NAME.get(name)
    if not tool or tool["handler"] is None:
        return None
    try:
        res = tool["handler"](question, project_id)
    except Exception as err:  # noqa: BLE001
        logger.warning("[AGENT] tool %s failed: %s", name, err)
        return None
    if not res:  # обработчик не смог (напр. нет пути) → фолбэк на обычный путь
        return None
    res.setdefault("operation", name)
    res["agent_tool"] = name
    logger.info("[AGENT] запрос → инструмент «%s»", name)
    return res
