"""agent_router_service.py — Ярус 2: чат сам выбирает инструмент (function-calling).

Когда детерминированные regex-каналы не сработали, LLM-роутер по описанию инструментов
выбирает ОДИН подходящий — но **исполняет существующий детерминированный обработчик**
(числа/действия считает код, не LLM, ADR-11). Это превращает Совушку из «набора каналов» в
агент над своими инструментами: спрашиваешь как угодно — она сама решает, что вызвать.

За флагом ``LES_AGENT_LOOP`` (по умолчанию off). Любой сбой/«none» → None → обычный путь
(RAG) как фолбэк. Ядро чат-пути не меняется — это аддитивная ступень перед RAG.

Дешёвые рычаги надёжности (ADR-11, ПЕРЕД любой LoRA):
  • чёткие описания + 1-2 примера-триггера на каждый инструмент (по ним LLM выбирает);
  • few-shot в промпте (вопрос → tool), включая переформулировки и явные none/RAG;
  • constrained output: имя из ответа модели валидируется ПО КАТАЛОГУ; неизвестное/пусто → none.
Замер устойчивости — `tools/router_bench.py` (tool-selection accuracy, в т.ч. на переформулировках).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ── handlers: тонкие обёртки над СУЩЕСТВУЮЩИМИ сервисами (сервисы не переписываем) ──
# Контракт handler(question, project_id) → dict | None. None → инструмент «не смог» → фолбэк в RAG.

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


def _h_glossary(q: str, pid: int):
    from proxy.services.glossary_chat_service import maybe_handle_glossary_query
    return maybe_handle_glossary_query(q, project_id=pid)


def _h_help(q: str, pid: int):
    from proxy.services.help_chat_service import maybe_handle_help_query
    return maybe_handle_help_query(q, project_id=pid)


def _h_memory(q: str, pid: int):
    from proxy.services.memory_service import maybe_handle_memory_command
    return maybe_handle_memory_command(q, project_id=pid)


def _h_decision(q: str, pid: int):
    from proxy.services.decision_service import maybe_handle_decision_command
    return maybe_handle_decision_command(q, project_id=pid)


# Сметная семья (price/kac/stesnennost/lsr_assemble/object_estimate): диспетчер
# maybe_handle_smeta_query сам парсит код/условие/объект и считает детерминированно.
# Роутер РАЗДЕЛЯЕТ интенты на уровне ВЫБОРА (это и меряет бенч), исполнение — в проверенном
# диспетчере (одни числа, без дубля парсинга).
def _h_smeta(q: str, pid: int):
    from proxy.services.smeta_chat_service import maybe_handle_smeta_query
    return maybe_handle_smeta_query(q, project_id=pid)


# table_agg / clause: исполнение требует RAG-контекста (chunks/collection), которого на этапе
# роутинга нет. Регистрируем интент (LLM узнаёт его — это меряет бенч), но handler уступает
# дорогу обычному пути RAG/каскаду (там есть retrieval-контекст). None → корректный фолбэк.
def _h_table_agg(q: str, pid: int):
    return None


def _h_clause(q: str, pid: int):
    return None


# ── каталог инструментов: имя, описание (по нему LLM выбирает), примеры-триггеры, handler ──
_TOOLS: tuple[dict[str, Any], ...] = (
    {"name": "asbuilt", "handler": _h_asbuilt,
     "desc": "Извлечь фактически смонтированный объём из сканов исполнительных схем/чек-листов "
             "в указанной папке (нужен путь).",
     "examples": ["вытащи смонтированный объём из папки /scans/корпус5",
                  "прими исполнительные схемы из /ИД"]},
    {"name": "les_md", "handler": _h_les_md,
     "desc": "Понять папку: прочитать или собрать LES.md, привязать к проекту, дочитать "
             "договор/титул (нужен путь).",
     "examples": ["пойми папку /Projects/Банкрот", "собери LES.md для этого объекта"]},
    {"name": "project_registry", "handler": _h_registry,
     "desc": "СПИСОК всех объектов/проектов ЛЕС (реестр, карта). НЕ для вопросов о содержании "
             "одного объекта.",
     "examples": ["какие у нас объекты", "покажи реестр проектов"]},
    {"name": "field", "handler": _h_field,
     "desc": "Записать ПОЛЕВОЙ выполненный объём работ в журнал или дать свод по журналу объёмов.",
     "examples": ["прими объём: уложено 120 м кабеля", "сводка по журналу объёмов"]},
    {"name": "task", "handler": _h_task,
     "desc": "Поставить, закрыть или показать ЗАДАЧИ (поручения).",
     "examples": ["создай задачу проверить АОСР", "покажи мои задачи"]},
    {"name": "preset", "handler": _h_preset,
     "desc": "Переключить РЕЖИМ работы системы: local (всё локально) / cloud (облако) / mix; "
             "или показать текущий.",
     "examples": ["переключись на облако", "какой сейчас режим"]},
    {"name": "glossary", "handler": _h_glossary,
     "desc": "ОПРЕДЕЛЕНИЕ строительного/сметного термина из онтологии: «что такое X», «что значит X».",
     "examples": ["что такое КАЦ", "что значит стеснённость"]},
    {"name": "price_lookup", "handler": _h_smeta,
     "desc": "ЦЕНА/стоимость/расценка ресурса по КОДУ ФГИС ЦС (например 91.05.01-017).",
     "examples": ["цена ресурса 91.05.01-017", "сколько стоит 01.7.15.06-0111"]},
    {"name": "kac", "handler": _h_smeta,
     "desc": "Нужен ли КАЦ (конъюнктурный анализ цен) для кода — есть ли материал в ФГИС ЦС.",
     "examples": ["нужен ли КАЦ для 91.05.01-017", "есть ли 14.4.02.05 в ФГИС ЦС"]},
    {"name": "stesnennost", "handler": _h_smeta,
     "desc": "ПОПРАВОЧНЫЙ КОЭФФИЦИЕНТ стеснённости / на усложняющие условия производства работ "
             "(к ОЗП/ЭМ). Это РАСЧЁТ коэффициента, НЕ определение термина (определение → glossary).",
     "examples": ["коэффициент стеснённости для действующего предприятия",
                  "какой коэф стеснённости в городе",
                  "поправочный коэффициент на усложняющие условия производства работ"]},
    {"name": "lsr_assemble", "handler": _h_smeta,
     "desc": "Собрать/рассчитать сметную ПОЗИЦИЮ от кода ГЭСН/ФЕР (NN-NN-NNN-NN) с ресурсами и ценами.",
     "examples": ["собери смету по ГЭСН12-01-034-02 объём 50",
                  "посчитай позицию ФЕР08-02-001-01"]},
    {"name": "object_estimate", "handler": _h_smeta,
     "desc": "Укрупнённая СМЕТА на ОБЪЕКТ по описанию («дай смету на дом 120 м², 2 этажа») — "
             "типовой состав работ → ВОР → ЛСР.",
     "examples": ["дай смету на дом 150 м² одноэтажный", "посчитай смету на гараж 40 м²"]},
    {"name": "table_agg", "handler": _h_table_agg,
     "desc": "АГРЕГАЦИЯ по табличным данным (сумма/итого/количество по ведомости/спецификации): "
             "«сколько всего кабеля», «итого по позициям».",
     "examples": ["сколько всего кабеля по спецификации", "итого по ведомости объёмов"]},
    {"name": "clause", "handler": _h_clause,
     "desc": "Точечный ВЫНОС текста ПУНКТА норматива по ссылке (пункт N.N СП/ГОСТ X).",
     "examples": ["приведи пункт 4.2.1 СП 1.13130", "процитируй п. 6.1 ГОСТ 21.501"]},
    {"name": "memory", "handler": _h_memory,
     "desc": "КОМАНДА памяти: «запомни …», «забудь заметку N», «мои заметки» (сохранить/удалить/"
             "показать заметки оператора). НЕ для вопросов про содержание.",
     "examples": ["запомни: прораб на объекте Иванов", "покажи мои заметки"]},
    {"name": "decision", "handler": _h_decision,
     "desc": "КОМАНДА слоя решений: «реши: …», «зафиксируй решение …», «решения» (записать/показать "
             "проектные решения). НЕ для вопросов про содержание.",
     "examples": ["реши: кабель вести по лотку обоснование: экономия",
                  "покажи решения по объекту"]},
    {"name": "none", "handler": None,
     "desc": "ЛЮБОЙ вопрос об информации/содержании/фактах (что известно про X, расскажи/объясни "
             "про X, справка по объекту, какие требования) — обычный поиск по документам (RAG). "
             "Это выбор ПО УМОЛЧАНИЮ.",
     "examples": ["какие требования к огнестойкости стен", "что известно про объект Банкрот",
                  "расскажи про систему дымоудаления"]},
)
_BY_NAME = {t["name"]: t for t in _TOOLS}
_VALID_NAMES = frozenset(_BY_NAME)

# Few-shot: вопрос → tool. Включает ПЕРЕФОРМУЛИРОВКИ и явные none/RAG-кейсы — учит модель,
# что «расскажи/какие требования» = none, а действие/команда = конкретный инструмент.
_FEWSHOT: tuple[tuple[str, str], ...] = (
    ("сколько стоит ресурс 91.05.01-017", "price_lookup"),
    ("что такое конъюнктурный анализ цен", "glossary"),
    ("запомни что прораб Иванов", "memory"),
    ("какие требования к ширине эвакуационных путей", "none"),
    ("расскажи что известно про дымоудаление на объекте", "none"),
    ("переключись в локальный режим", "preset"),
)


def _is_on() -> bool:
    flags = (os.getenv("LES_AGENT_LOOP", "false"), os.getenv("LES_ROUTER_PRIMARY", "false"))
    return any(f.strip().lower() in ("1", "true", "yes", "on") for f in flags)


def router_primary() -> bool:
    """Роутер ОСНОВНОЙ — зовётся ПЕРЕД keyword-каскадом (инверсия, AUDIT_DETERMINISM шаг 2)."""
    return os.getenv("LES_ROUTER_PRIMARY", "false").strip().lower() in ("1", "true", "yes", "on")


def _build_prompt(question: str) -> str:
    catalog_lines = []
    for t in _TOOLS:
        line = f"- {t['name']}: {t['desc']}"
        ex = t.get("examples") or []
        if ex:
            line += " Примеры: " + " | ".join(f"«{e}»" for e in ex)
        catalog_lines.append(line)
    catalog = "\n".join(catalog_lines)
    fewshot = "\n".join(f'Запрос: {q}\n{{"tool": "{name}"}}' for q, name in _FEWSHOT)
    return (
        "Ты — маршрутизатор инструментов строительной системы ЛЕС. Инструменты — ТОЛЬКО для "
        "ДЕЙСТВИЙ и КОМАНД (извлечь объём, цена/КАЦ/стеснённость/смета по коду, переключить режим, "
        "понять папку, записать объём, список объектов, запомнить/решить, список задач). "
        "Если оператор спрашивает ИНФОРМАЦИЮ или факты (что известно про X, расскажи/объясни про X, "
        "справка по объекту, какие требования) — это none (обычный поиск по документам). "
        "Сомневаешься — none. Выбери РОВНО ОДИН инструмент из списка по имени или none. "
        "Верни ТОЛЬКО JSON {\"tool\": \"<имя>\"} без пояснений.\n\n"
        f"Инструменты:\n{catalog}\n\n"
        f"Примеры:\n{fewshot}\n\n"
        f"Запрос: {question}"
    )


def _parse_tool(raw: str) -> str:
    """Достать имя из ответа модели. Constrained: имя валидируется по каталогу позже."""
    if not raw:
        return ""
    m = re.search(r'"tool"\s*:\s*"([a-z_]+)"', raw)
    if m:
        return m.group(1)
    # модель могла вернуть просто имя (без JSON) — ищем точное имя инструмента в тексте
    low = raw.lower()
    for name in _VALID_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", low):
            return name
    return ""


def _route_llm_text(prompt: str, *, max_tokens: int = 40) -> str:
    """ЛОКАЛЬНЫЙ быстрый вызов для РОУТИНГА (MLX :8080), НЕ облако — роутинг без канала.

    Роутер-бенч = 100% на локальной Qwen3.5-4B → выбор инструмента не зависит от облачного канала
    ([[local-bases-untrusted-channel]]). КОРОТКИЙ таймаут: роутер не должен вешать чат; сбой → ''
    (→ none → каскад/RAG). Эндпоинт/модель — env (дефолт локальный MLX-хост).
    """
    import os

    import httpx

    # Роутер — на ТОЙ ЖЕ модели, что и ответ (по умолчанию провайдер OPENAI_*): на облаке это
    # ~0.5-1с вместо ~7с локальной 4B на КАЖДЫЙ запрос. LES_ROUTER_* — явный override (локальный MLX
    # для канал-независимости, если нужен). Короткий таймаут; сбой → none → RAG, чат не вешаем.
    base = os.getenv("LES_ROUTER_BASE_URL", os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8080/v1")).rstrip("/")
    model = os.getenv("LES_ROUTER_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1"))
    key = os.getenv("LES_ROUTER_API_KEY", os.getenv("OPENAI_API_KEY", "local"))
    timeout = int(os.getenv("LES_ROUTER_TIMEOUT", "12"))
    url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
    # gpt-5.x / o-серия требуют max_completion_tokens вместо max_tokens (иначе 400).
    ml = model.lower()
    tok_key = ("max_completion_tokens"
               if (ml.startswith("gpt-5") or (len(ml) >= 2 and ml[0] == "o" and ml[1].isdigit()))
               else "max_tokens")
    try:
        resp = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, timeout=timeout, json={
            "model": model, "temperature": 0.0, tok_key: max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        })
        resp.raise_for_status()
        return str(resp.json().get("choices", [{}])[0].get("message", {}).get("content", "") or "")
    except Exception as err:  # noqa: BLE001 — best-effort; сбой → none → RAG, не вешать чат
        logger.warning("[AGENT] router LLM недоступен: %s", err)
        return ""


def _classify(question: str) -> str:
    """LLM выбирает имя инструмента. Constrained output: неизвестное/пусто → 'none'.

    Сырой строке НЕ доверяем — имя сверяется с каталогом ``_VALID_NAMES``; любой шум, выдумка
    или пустой ответ схлопываются в 'none' (вопрос уходит в RAG). Best-effort; сбой → 'none'.
    """
    raw = _route_llm_text(_build_prompt(question), max_tokens=40)
    name = _parse_tool(raw)
    if name not in _VALID_NAMES:   # constrained: галлюцинация/шум/пусто → дефолт
        if name:
            logger.info("[AGENT] неизвестный инструмент «%s» от модели → none", name)
        return "none"
    return name


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
    if not res:  # обработчик не смог (напр. нет пути/кода/контекста) → фолбэк на обычный путь
        return None
    res.setdefault("operation", name)
    res["agent_tool"] = name
    logger.info("[AGENT] запрос → инструмент «%s»", name)
    return res
