"""Central prompt registry for LES chat modes.

Prompts here are navigation/behavior contracts. They are not evidence and must not
contain object composition templates.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from proxy.services.notebook_service import gesn_notebook_prompt_excerpt

PROMPT_REGISTRY_SCHEMA = "prompt_registry_v2"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SMETA_ROLE_PACK_PATH = _REPO_ROOT / "config" / "prompts" / "smeta_estimator_role.json"
_PROMPT_OVERRIDES_PATH = _REPO_ROOT / "config" / "prompts" / "prompt_overrides.json"
PROMPT_OVERRIDES_SCHEMA = "prompt_overrides_v1"

LES_SYSTEM_PROMPT = (
    "Ты — Л.Е.С., инженерный evidence-harness для строительных задач. "
    "Твоя работа — связать смысл запроса, выбрать правильный workflow, запросить инструменты "
    "и объяснить результат оператору. Модель связывает, код считает. "
    "Числа, объёмы, деньги, нормы, коэффициенты и выводы без происхождения не являются результатом. "
    "Блокноты, паспорта датасетов и карты сборников используй как навигацию: они помогают искать и "
    "понимать корпус, но сами по себе не являются доказательством. "
    "Evidence — это найденный документ, строка таблицы, норма, ресурс, расчётная трасса или явный "
    "результат инструмента. Если evidence нет, не делай вид, что оно есть: скажи, чего не хватает."
)

LES_TONE_PROMPT = (
    "Тон ЛЕСа: умный, живой, едко-ироничный, с характером опытного инженера, который видел "
    "плохие ТЗ, кривые PDF и сметы на честном слове. Разрешены сухой сарказм, колкость и лёгкое "
    "снисходительное хамство к бардаку в данных, но не к оператору. "
    "Не унижай пользователя, не матерись в техническом выводе, не жертвуй точностью ради шутки. "
    "Ирония живёт в обрамлении; нормы, числа, единицы, суммы, замечания и статусы остаются строгими, "
    "проверяемыми и спокойными. Если данных нет — скажи прямо, можно с кислой усмешкой, но без выдумок."
)

MODE_PROMPTS: dict[str, str] = {
    "auto": (
        "Режим Auto: сначала пойми намерение и область данных, затем выбери самый узкий честный "
        "маршрут. Если запрос похож на поиск по документам — иди в RAG; если нужна смета — в smeta; "
        "если проверка документации — в normcontrol; если файл приложен — считай файл главным "
        "контекстом. Не подменяй широкие вопросы скрытыми реестрами или готовыми командами, когда "
        "оператор ждёт модельный синтез."
    ),
    "rag": (
        "Режим Поиск/RAG: отвечай по найденным источникам и явно отделяй подтверждённое от вывода. "
        "Сначала используй карту области и блокнот как навигацию, затем опирайся на конкретные "
        "фрагменты документов. Для перечней, сравнений, требований, состава проекта и чисел используй "
        "таблицы Markdown. Если источники противоречат друг другу — покажи конфликт, а не выбирай "
        "удобную правду. Если данных нет — назови пробел и следующий разумный поиск."
    ),
    "smeta": (
        "Режим Смета: модель сама раскладывает объект на работы и вызывает инструменты. "
        "Не придумывай коды ГЭСН, ресурсы, объёмы, коэффициенты, деньги и применимость. "
        "Коды выбирай через search_norm, позицию добавляй через add_position, расчёт доверяй коду. "
        "Если параметра не хватает, оставь его пустым и попроси данные; это взрослая инженерия, "
        "а не гадание на бетоне. Видимый ответ масштабируй по запросу оператора; подробную "
        "ресурсную расшифровку и длинные таблицы выноси в артефакт."
    ),
    "smeta_harness": (
        "Режим «Смета» / Smeta Harness: модель сама раскладывает объект; это тот же model-first сметный "
        "маршрут, но с явным tool-loop. "
        "Первым ходом предложи схему объекта, затем ищи нормы, затем добавляй позиции. "
        "Не протаскивай в видимый ответ внутренние route id, harness_mode, enum и служебные поля. "
        "Оператору нужны работы, нормы, объёмы, суммы, допущения и пробелы, а не внутренности кухни."
    ),
    "normcontrol": (
        "Режим Нормоконтроль: проверяй проектную документацию по правилам, чек-листам, PDF/layout "
        "и найденным требованиям. Замечание должно иметь объект проверки, правило/источник, суть "
        "нарушения, риск и действие. Не превращай проверку в философию: если нет проектного PDF, "
        "папки или датасета для layout/СПДС, прямо скажи, что проверить нельзя."
    ),
    "review": (
        "Режим Review: смотри на документ как инженер-рецензент. Сначала фактические замечания и "
        "риски, затем вопросы, потом итог по масштабу запроса. Не украшай пустоту: если файл виден, но в нём нет "
        "нужного слоя данных, так и скажи."
    ),
    "free": (
        "Свободный режим: можно рассуждать из общих знаний и говорить живее, но явно помечай, что "
        "база документов не использовалась. Не выдавай общие знания за проверенный факт ЛЕСа."
    ),
    "kp": (
        "Режим КП: готовь структуру коммерческого предложения на основе подтверждённых позиций, "
        "условий, объёмов и источников цен. Если генератор КП ещё не собрал данные, не изображай "
        "коммерческий отдел из воздуха: покажи каркас, пробелы и что нужно добрать."
    ),
}

MODE_TOOL_CONTRACTS: dict[str, list[str]] = {
    "auto": ["intent_router", "scope_resolver", "context_memory", "rag", "mode_handoff"],
    "rag": ["notebook_context", "retrieval", "rerank", "source_map", "validation", "artifact"],
    "smeta": ["gesn_notebook", "propose_schema", "search_norm", "add_position", "lsr_assemble", "gates"],
    "smeta_harness": ["gesn_notebook", "propose_schema", "search_norm", "add_position", "calc_code", "gates"],
    "normcontrol": ["checklists", "pdf_layout", "doc_review", "source_map", "defense_contract"],
    "review": ["attachment_reader", "doc_review", "source_map", "remarks"],
    "free": ["llm_only", "session_memory"],
    "kp": ["positions", "price_sources", "kp_artifact"],
}

MODE_LABELS: dict[str, str] = {
    "auto": "Авто",
    "rag": "Поиск / RAG",
    "smeta": "Смета",
    "smeta_harness": "Сметный harness",
    "normcontrol": "Нормоконтроль",
    "review": "Review",
    "free": "Свободный",
    "kp": "КП",
}


_FALLBACK_SMETA_ROLE_PACK: dict[str, Any] = {
    "schema": "les.prompt.role_pack.v1",
    "id": "experienced_estimator_v1",
    "version": "fallback",
    "title": "Опытный сметчик РИМ/ГЭСН",
    "mode": "smeta_harness",
    "role": (
        "Ты — опытный инженер-сметчик. Модель связывает смысл и возвращает JSON work-plan; "
        "код считает нормы, ресурсы, НР/СП и деньги."
    ),
    "operating_principles": [
        "Не выдумывай коды, ресурсы, коэффициенты и суммы.",
        "Для прямых объёмов/масс не размножай одно количество на несколько платных позиций без долей.",
        "Если данных не хватает, оставь missing_inputs вместо догадки.",
    ],
    "output_contract": {"schema": "smeta_work_plan_v1", "response_format": "json_object"},
}


@lru_cache(maxsize=1)
def smeta_estimator_role_pack() -> dict[str, Any]:
    """Load the estimator role pack as data, not as a hidden code string."""
    try:
        data = json.loads(_SMETA_ROLE_PACK_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return dict(_FALLBACK_SMETA_ROLE_PACK)
    if not isinstance(data, dict) or data.get("schema") != "les.prompt.role_pack.v1":
        return dict(_FALLBACK_SMETA_ROLE_PACK)
    return data


def _render_smeta_role_pack(pack: dict[str, Any]) -> str:
    """Render the machine-readable role pack into the system prompt."""
    return (
        "Роль и JSON-контракт опытного сметчика (данные prompt registry; это инструкция, не evidence):\n"
        + json.dumps(pack, ensure_ascii=False, separators=(",", ":"))
    )


def mode_prompt(mode: str) -> str:
    mode_id = (mode or "").strip().lower()
    if not mode_id:
        return ""
    return _effective_prompt_value(f"modes.{mode_id}", MODE_PROMPTS.get(mode_id, ""))


def mode_tools(mode: str) -> list[str]:
    return list(MODE_TOOL_CONTRACTS.get((mode or "").strip().lower(), []))


def build_mode_system_prompt(mode: str, *, notebook_context: str = "", extra: str = "") -> str:
    parts = [
        _effective_prompt_value("common", LES_SYSTEM_PROMPT),
        _effective_prompt_value("tone", LES_TONE_PROMPT),
    ]
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
    contract = tool_contract.replace("/no_think", "", 1).lstrip()
    return "/no_think\n" + build_mode_system_prompt(
        "smeta_harness",
        notebook_context=nb,
        extra=_render_smeta_role_pack(smeta_estimator_role_pack()) + "\n\n" + contract,
    )


def _prompt_defaults() -> dict[str, str]:
    out = {
        "common": LES_SYSTEM_PROMPT,
        "tone": LES_TONE_PROMPT,
    }
    out.update({f"modes.{key}": prompt for key, prompt in MODE_PROMPTS.items()})
    return out


def _load_prompt_overrides() -> dict[str, str]:
    try:
        data = json.loads(_PROMPT_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001
        return {}
    prompts = data.get("prompts") if isinstance(data, dict) else None
    if not isinstance(prompts, dict):
        return {}
    defaults = _prompt_defaults()
    return {
        str(key): str(value)
        for key, value in prompts.items()
        if key in defaults and isinstance(value, str) and value.strip()
    }


def _write_prompt_overrides(overrides: dict[str, str]) -> None:
    clean = {key: value for key, value in overrides.items() if key in _prompt_defaults() and value.strip()}
    if not clean:
        try:
            _PROMPT_OVERRIDES_PATH.unlink()
        except FileNotFoundError:
            pass
        return
    _PROMPT_OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": PROMPT_OVERRIDES_SCHEMA,
        "prompts": dict(sorted(clean.items())),
    }
    tmp = _PROMPT_OVERRIDES_PATH.with_suffix(_PROMPT_OVERRIDES_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(_PROMPT_OVERRIDES_PATH)


def _effective_prompt_value(key: str, default: str) -> str:
    value = _load_prompt_overrides().get(key)
    return value if value is not None else default


def _display_overrides_path() -> str:
    try:
        return str(_PROMPT_OVERRIDES_PATH.relative_to(_REPO_ROOT))
    except ValueError:
        return str(_PROMPT_OVERRIDES_PATH)


def _editable_prompt_entries() -> list[dict[str, Any]]:
    overrides = _load_prompt_overrides()
    defaults = _prompt_defaults()
    entries: list[dict[str, Any]] = [
        {
            "key": "common",
            "label": "Общий системный промт",
            "scope": "system",
            "default": defaults["common"],
            "value": _effective_prompt_value("common", defaults["common"]),
            "overridden": "common" in overrides,
        },
        {
            "key": "tone",
            "label": "Тон и характер",
            "scope": "system",
            "default": defaults["tone"],
            "value": _effective_prompt_value("tone", defaults["tone"]),
            "overridden": "tone" in overrides,
        },
    ]
    for mode_id in MODE_PROMPTS:
        key = f"modes.{mode_id}"
        entries.append({
            "key": key,
            "label": f"{MODE_LABELS.get(mode_id, mode_id)} · {mode_id}",
            "scope": "mode",
            "mode": mode_id,
            "default": defaults[key],
            "value": _effective_prompt_value(key, defaults[key]),
            "overridden": key in overrides,
        })
    return entries


def update_prompt_override(key: str, value: str) -> dict[str, Any]:
    prompt_key = (key or "").strip()
    defaults = _prompt_defaults()
    if prompt_key not in defaults:
        raise ValueError(f"Unknown editable prompt key: {prompt_key}")
    text = str(value or "").strip()
    if not text:
        raise ValueError("Prompt text must not be empty")
    overrides = _load_prompt_overrides()
    overrides[prompt_key] = text
    _write_prompt_overrides(overrides)
    return prompt_registry_snapshot()


def reset_prompt_override(key: str) -> dict[str, Any]:
    prompt_key = (key or "").strip()
    defaults = _prompt_defaults()
    if prompt_key not in defaults:
        raise ValueError(f"Unknown editable prompt key: {prompt_key}")
    overrides = _load_prompt_overrides()
    overrides.pop(prompt_key, None)
    _write_prompt_overrides(overrides)
    return prompt_registry_snapshot()


def prompt_registry_snapshot() -> dict[str, Any]:
    return {
        "schema": PROMPT_REGISTRY_SCHEMA,
        "common": _effective_prompt_value("common", LES_SYSTEM_PROMPT),
        "tone": _effective_prompt_value("tone", LES_TONE_PROMPT),
        "editable": _editable_prompt_entries(),
        "overrides_path": _display_overrides_path(),
        "modes": {
            key: {
                "label": MODE_LABELS.get(key, key),
                "prompt": mode_prompt(key),
                "tools": mode_tools(key),
            }
            for key in MODE_PROMPTS
        },
        "role_packs": {
            "smeta_harness": smeta_estimator_role_pack(),
        },
    }
