"""Operator-facing answer scenarios and contracts for chat responses.

This layer tells UI/operators what workflow is running, what shape of answer is
expected, and whether the returned payload satisfies the shallow contract. It
does not validate domain math itself; numeric/evidence checks remain in the
concrete tools.
"""

from __future__ import annotations

import re
from typing import Any

from proxy.services.workflow_plan_service import build_workflow_plan


ANSWER_CONTRACTS: dict[str, dict[str, Any]] = {
    "auto": {
        "id": "auto",
        "label": "Авто",
        "expects": ["answer", "query_route"],
        "tables": "when_useful",
        "evidence": "depends_on_route",
    },
    "prose": {
        "id": "prose",
        "label": "Свободный текст",
        "expects": ["answer"],
        "tables": "optional",
        "evidence": "optional",
    },
    "grounded_answer_v1": {
        "id": "grounded_answer_v1",
        "label": "Ответ по источникам",
        "expects": ["answer", "sources", "source_map", "crag_status"],
        "tables": "when_requirements_or_values_repeat",
        "evidence": "required",
    },
    "estimate_table_v1": {
        "id": "estimate_table_v1",
        "label": "Сметная таблица",
        "expects": ["answer", "provenance", "total_status"],
        "tables": "required",
        "evidence": "numeric_provenance_required",
    },
    "estimate_preliminary_v1": {
        "id": "estimate_preliminary_v1",
        "label": "Предварительная смета",
        "expects": ["answer", "defense", "assumptions"],
        "tables": "required",
        "evidence": "assumptions_must_be_marked",
    },
    "findings_table_v1": {
        "id": "findings_table_v1",
        "label": "Таблица замечаний",
        "expects": ["answer", "defense", "normalized_remarks"],
        "tables": "required",
        "evidence": "required_for_findings",
    },
    "tool_result_v1": {
        "id": "tool_result_v1",
        "label": "Результат инструмента",
        "expects": ["answer", "query_route"],
        "tables": "when_useful",
        "evidence": "tool_defined",
    },
}


SCENARIOS: dict[str, dict[str, Any]] = {
    "estimate_harness": {
        "id": "estimate_harness",
        "label": "Сметная декомпозиция",
        "contract": "estimate_preliminary_v1",
        "progress": [
            "Разбираю объект на позиции",
            "Ищу нормы и ресурсы",
            "Считаю и помечаю допущения",
            "Собираю предварительную таблицу",
        ],
    },
    "normcontrol": {
        "id": "normcontrol",
        "label": "Нормоконтроль",
        "contract": "findings_table_v1",
        "progress": [
            "Определяю комплект проверки",
            "Проверяю правила и источники",
            "Собираю замечания",
            "Формирую отчёт",
        ],
    },
    "grounded_rag": {
        "id": "grounded_rag",
        "label": "Поиск по источникам",
        "contract": "grounded_answer_v1",
        "progress": [
            "Уточняю область поиска",
            "Ищу фрагменты в источниках",
            "Собираю контекст",
            "Формирую ответ с источниками",
        ],
    },
    "table_query": {
        "id": "table_query",
        "label": "Табличный расчёт",
        "contract": "tool_result_v1",
        "progress": [
            "Ищу табличные источники",
            "Читаю строки и поля",
            "Считаю результат кодом",
            "Собираю таблицу ответа",
        ],
    },
    "mail_query": {
        "id": "mail_query",
        "label": "Поиск по почте",
        "contract": "tool_result_v1",
        "progress": [
            "Проверяю почтовый индекс",
            "Ищу релевантные письма",
            "Собираю выдержки",
            "Формирую ответ",
        ],
    },
    "free_llm": {
        "id": "free_llm",
        "label": "Свободный ответ",
        "contract": "prose",
        "progress": [
            "Готовлю свободный ответ",
            "Печатаю текст",
        ],
    },
    "attachment_context": {
        "id": "attachment_context",
        "label": "Ответ по вложению",
        "contract": "prose",
        "progress": [
            "Читаю прикреплённый файл",
            "Выделяю полезный контекст",
            "Формирую ответ",
        ],
    },
    "command": {
        "id": "command",
        "label": "Команда",
        "contract": "tool_result_v1",
        "progress": [
            "Распознаю команду",
            "Выполняю действие",
            "Возвращаю результат",
        ],
    },
    "tool": {
        "id": "tool",
        "label": "Инструмент",
        "contract": "tool_result_v1",
        "progress": [
            "Выбираю сценарий работы",
            "Выполняю поиск или расчёт",
            "Собираю ответ",
        ],
    },
}


MODE_SCENARIOS = {
    "smeta": "estimate_harness",
    "smeta_harness": "estimate_harness",
    "review": "normcontrol",
    "doc_review": "normcontrol",
    "rag": "grounded_rag",
    "free": "free_llm",
}


CHANNEL_SCENARIOS = {
    "smeta_mode": "estimate_harness",
    "harness_mode": "estimate_harness",
    "review_mode": "normcontrol",
    "normcontrol": "normcontrol",
    "doc_review": "normcontrol",
    "table": "table_query",
    "mail": "mail_query",
    "attachment_context": "attachment_context",
    "command": "command",
    "free_mode": "free_llm",
    "rag": "grounded_rag",
}


def _copy_contract(contract_id: str) -> dict[str, Any]:
    base = ANSWER_CONTRACTS.get(contract_id) or ANSWER_CONTRACTS["auto"]
    return dict(base)


def _copy_scenario(scenario_id: str) -> dict[str, Any]:
    base = SCENARIOS.get(scenario_id) or SCENARIOS["tool"]
    return {
        "id": base["id"],
        "label": base["label"],
        "contract": base["contract"],
        "progress": list(base["progress"]),
    }


def scenario_for_request(*, mode: str | None, question: str = "", has_attachment: bool = False) -> dict[str, Any]:
    """Best-effort scenario before routing finishes, used for early SSE progress."""
    m = (mode or "").strip().lower()
    if m in MODE_SCENARIOS:
        return _copy_scenario(MODE_SCENARIOS[m])
    if has_attachment:
        return _copy_scenario("attachment_context")
    q = (question or "").casefold().replace("ё", "е")
    if any(word in q for word in ("таблиц", "сумм", "метраж", "объем", "стоимость", "ведомост")):
        return _copy_scenario("table_query")
    if any(word in q for word in ("письм", "почт", "mail", "email")):
        return _copy_scenario("mail_query")
    return _copy_scenario("tool")


def scenario_for_payload(payload: dict[str, Any]) -> dict[str, Any]:
    route = payload.get("query_route") if isinstance(payload, dict) else {}
    route = route if isinstance(route, dict) else {}
    channel = str(route.get("channel") or "")
    operation = str(route.get("operation") or route.get("intent") or "")
    profile = route.get("profile") if isinstance(route.get("profile"), dict) else {}
    profile_id = str((profile or {}).get("profile_id") or "")

    for key in (channel, operation, profile_id):
        if key in CHANNEL_SCENARIOS:
            return _copy_scenario(CHANNEL_SCENARIOS[key])
    if payload.get("table_query"):
        return _copy_scenario("table_query")
    if profile_id == "grounded_rag":
        return _copy_scenario("grounded_rag")
    return _copy_scenario("tool")


def contract_for_payload(payload: dict[str, Any]) -> dict[str, Any]:
    route = payload.get("query_route") if isinstance(payload, dict) else {}
    route = route if isinstance(route, dict) else {}
    profile = route.get("profile") if isinstance(route.get("profile"), dict) else {}
    contract_id = str((profile or {}).get("output_contract") or "")
    scenario = scenario_for_payload(payload)
    if not contract_id or contract_id == "auto":
        contract_id = scenario.get("contract") or "auto"
    contract = _copy_contract(contract_id)
    contract["status"] = "declared"
    return contract


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _field_value(payload: dict[str, Any], field: str) -> Any:
    if field == "source_map":
        trace = payload.get("retrieval_trace") if isinstance(payload.get("retrieval_trace"), dict) else {}
        return payload.get("source_map") or trace.get("source_map") or trace.get("source_map_preview")
    if field == "provenance":
        return payload.get("provenance") or payload.get("source_map") or payload.get("evidence_summary")
    if field == "defense":
        return payload.get("defense") or payload.get("defense_contract_v1")
    return payload.get(field)


def _answer_has_markdown_table(answer: str) -> bool:
    lines = [line.strip() for line in (answer or "").splitlines()]
    for idx, line in enumerate(lines[:-1]):
        next_line = lines[idx + 1]
        if line.count("|") >= 2 and next_line.count("|") >= 2 and re.search(r"\|\s*:?-{3,}:?\s*\|", next_line):
            return True
    return False


def _has_structured_table(payload: dict[str, Any]) -> bool:
    for key in ("table_query", "normalized_remarks", "rows", "items", "positions"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
        if isinstance(value, dict) and any(_has_value(v) for v in value.values()):
            return True
    return False


def check_contract(payload: dict[str, Any], contract: dict[str, Any] | None = None) -> dict[str, Any]:
    """Shallow machine check for the declared answer contract.

    The check is intentionally non-blocking: it reports missing shape/evidence
    signals, while domain validators and deterministic tools remain the source
    of truth for calculations and factual correctness.
    """
    if not isinstance(payload, dict):
        return {"status": "warn", "missing": ["payload"], "warnings": ["Ответ не является объектом"]}
    contract = contract or contract_for_payload(payload)
    expected = [str(x) for x in (contract.get("expects") or [])]
    missing = [field for field in expected if not _has_value(_field_value(payload, field))]
    warnings: list[str] = []

    answer = str(payload.get("answer") or payload.get("response") or "")
    has_table = _answer_has_markdown_table(answer) or _has_structured_table(payload)
    if contract.get("tables") == "required" and not has_table:
        warnings.append("Требуется таблица, но в payload не найдено табличной структуры")

    evidence_mode = str(contract.get("evidence") or "")
    if evidence_mode in {"required", "required_for_findings"}:
        has_sources = _has_value(payload.get("sources"))
        has_source_map = _has_value(_field_value(payload, "source_map"))
        if not (has_sources or has_source_map):
            warnings.append("Требуется evidence, но источники/source_map не найдены")
    if evidence_mode == "numeric_provenance_required" and not _has_value(_field_value(payload, "provenance")):
        warnings.append("Требуется происхождение чисел, но provenance/evidence не найдены")
    if evidence_mode == "assumptions_must_be_marked":
        has_assumptions = _has_value(payload.get("assumptions")) or any(
            marker in answer.casefold() for marker in ("assume", "допущен", "missing", "не хватает")
        )
        if not has_assumptions:
            warnings.append("Предварительный расчёт должен явно помечать допущения")

    status = "pass" if not missing and not warnings else "warn"
    return {
        "contract_id": contract.get("id") or "auto",
        "status": status,
        "missing": missing,
        "warnings": warnings,
        "observed": {
            "answer": bool(answer.strip()),
            "table": has_table,
            "sources": _has_value(payload.get("sources")),
            "source_map": _has_value(_field_value(payload, "source_map")),
        },
    }


def decorate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach scenario and answer_contract if absent. Mutates and returns payload."""
    if not isinstance(payload, dict):
        return payload
    payload.setdefault("scenario", scenario_for_payload(payload))
    payload.setdefault("answer_contract", contract_for_payload(payload))
    payload.setdefault("answer_contract_check", check_contract(payload, payload["answer_contract"]))
    payload.setdefault("workflow_plan", build_workflow_plan(payload))
    return payload
