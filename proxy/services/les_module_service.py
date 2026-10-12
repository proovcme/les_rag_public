"""LES core module registry and lightweight turn routing.

This layer chooses the professional module/context for a turn. It does not solve
domain tasks: smeta decomposition, norm selection, document findings, QTO rules,
and contract interpretation remain model/domain responsibilities.
"""

from __future__ import annotations

import copy
import importlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from proxy.services.les_module_contracts import (
    ModuleContractError,
    ModuleManifest,
    is_safe_module_id,
    validate_manifest,
)


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_MODULE_CONFIG = _ROOT / "config" / "modules.json"
_MODULE_CONFIG_SCHEMA = "les.module-registry.v1"
_SAFE_PACKAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_FEATURE_MODULES: dict[str, Any] = {
    "schema": "les.feature-modules.v1",
    "registry": {"status": "ready", "reason_code": None},
    "modules": {},
}


@dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    title: str
    triggers: tuple[str, ...]
    short_system_delta: str
    skill_snippets: tuple[str, ...]
    retrieval_scopes: tuple[str, ...]
    state_shape: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    tool_policy: str
    output_style: str


_COMMON_STATE_SHAPE = (
    "task",
    "input_type",
    "last_action",
    "current_result",
    "accepted_decisions",
    "open_branches",
    "exclusions",
    "assumptions",
    "current_objects",
    "status",
)


MODULE_REGISTRY: dict[str, ModuleSpec] = {
    "smeta": ModuleSpec(
        module_id="smeta",
        title="Сметы",
        triggers=("смет", "вор", "гэсн", "фер", "рим", "лср", "кс-2", "фгис", "расцен"),
        short_system_delta=(
            "Режим: сметы. Работай как инженер-сметчик: собери или уточни ВОР, "
            "отдели работы от поставки, выбери нормативный/ценовой ход, дай стоимость "
            "работ final/partial/scenario, покажи допущения и добор."
        ),
        skill_snippets=(
            "smeta.gesn_pricing_workflow",
            "smeta.specification_to_bor",
            "smeta.quantity_conflict",
            "smeta.rim_scenario_estimate",
            "smeta.active_continuation",
        ),
        retrieval_scopes=("active_state", "source_facts", "table_rows", "lookup_records", "calculation_trace"),
        state_shape=_COMMON_STATE_SHAPE + ("current_bor", "selected_quantity_variant", "method", "last_norm_table"),
        allowed_tools=("retrieval", "calculation", "lookup", "export", "validation"),
        tool_policy="tools calculate, retrieve, validate, trace, and export after the model decision",
        output_style="professional estimator answer; no internal JSON unless requested",
    ),
    "normcontrol": ModuleSpec(
        module_id="normcontrol",
        title="Нормоконтроль",
        triggers=("нормоконтрол", "замечани", "гост", "спдс", "провер", "нарушени"),
        short_system_delta=(
            "Режим: нормоконтроль. Проверяй документ по требованиям, показывай объект "
            "проверки, норму, риск и действие."
        ),
        skill_snippets=("normcontrol.findings", "core.source_grounding"),
        retrieval_scopes=("active_state", "source_facts", "document_chunks", "table_rows"),
        state_shape=_COMMON_STATE_SHAPE + ("checked_document", "findings", "requirements"),
        allowed_tools=("retrieval", "validation", "export"),
        tool_policy="tools find requirements and validate structure; the model writes findings",
        output_style="findings table plus short professional explanation",
    ),
    "bim_qto": ModuleSpec(
        module_id="bim_qto",
        title="BIM/QTO",
        triggers=("bim", "ifc", "revit", "rvt", "qto", "объем", "элемент", "модель"),
        short_system_delta=(
            "Режим: BIM/QTO. Работай с элементами модели, классификацией и объёмами; "
            "отделяй геометрию, свойства и расчётные выводы."
        ),
        skill_snippets=("bim_qto.quantities", "core.source_grounding"),
        retrieval_scopes=("active_state", "domain_objects", "source_facts", "calculation_trace"),
        state_shape=_COMMON_STATE_SHAPE + ("model", "elements", "quantities", "classification"),
        allowed_tools=("retrieval", "calculation", "validation", "export"),
        tool_policy="tools extract and calculate quantities; the model decides interpretation",
        output_style="engineering QTO answer with sources and quantity trace",
    ),
    "docs_review": ModuleSpec(
        module_id="docs_review",
        title="Проверка документации",
        triggers=("проверь", "ревью", "проектн", "документац", "раздел", "пд", "рд"),
        short_system_delta=(
            "Режим: проверка проектной документации. Дай инженерные замечания, риски, "
            "источники и следующий добор."
        ),
        skill_snippets=("docs_review.professional_review", "core.source_grounding"),
        retrieval_scopes=("active_state", "source_facts", "document_chunks", "table_rows"),
        state_shape=_COMMON_STATE_SHAPE + ("reviewed_files", "findings", "questions"),
        allowed_tools=("retrieval", "validation", "export"),
        tool_policy="tools retrieve and validate; the model writes professional review",
        output_style="review findings first, then questions and summary",
    ),
    "procurement": ModuleSpec(
        module_id="procurement",
        title="КП и закупки",
        triggers=("кп", "коммерческ", "поставщик", "закуп", "конъюнктур", "прайс"),
        short_system_delta=(
            "Режим: КП/закупки. Сравни предложения, условия, цены, полноту и риски; "
            "не превращай отсутствующую цену в ноль."
        ),
        skill_snippets=("procurement.offer_compare", "core.source_grounding"),
        retrieval_scopes=("active_state", "source_facts", "table_rows", "lookup_records"),
        state_shape=_COMMON_STATE_SHAPE + ("offers", "price_lines", "commercial_terms"),
        allowed_tools=("retrieval", "calculation", "validation", "export"),
        tool_policy="tools parse and sum offers; the model decides commercial interpretation",
        output_style="comparison table with gaps and recommendation",
    ),
    "contracts": ModuleSpec(
        module_id="contracts",
        title="Договоры",
        triggers=("договор", "контракт", "услови", "ответственност", "срок", "оплат"),
        short_system_delta=(
            "Режим: договоры. Разбери условия, обязательства, риски и вопросы юристу; "
            "не выдавай юридическую гарантию."
        ),
        skill_snippets=("contracts.risk_review", "core.source_grounding"),
        retrieval_scopes=("active_state", "source_facts", "document_chunks"),
        state_shape=_COMMON_STATE_SHAPE + ("contract", "clauses", "risks"),
        allowed_tools=("retrieval", "validation", "export"),
        tool_policy="tools find clauses; the model evaluates risk and wording",
        output_style="contract risk review with clause references",
    ),
    "general_project_rag": ModuleSpec(
        module_id="general_project_rag",
        title="Проектная память",
        triggers=("проект", "файл", "документ", "найди", "что известно", "покажи"),
        short_system_delta=(
            "Режим: проектная память. Используй документы, карту корпуса и активное "
            "состояние, отделяя найденные факты от инженерного вывода."
        ),
        skill_snippets=("core.source_grounding", "core.active_continuation"),
        retrieval_scopes=("active_state", "source_facts", "document_chunks", "table_rows"),
        state_shape=_COMMON_STATE_SHAPE,
        allowed_tools=("retrieval", "validation", "export"),
        tool_policy="tools retrieve and validate; the model synthesizes",
        output_style="clear professional answer with sources and gaps",
    ),
}


_MODE_TO_MODULE = {
    "smeta": "smeta",
    "smeta_direct": "smeta",
    "smeta_harness": "smeta",
    "normcontrol": "normcontrol",
    "review": "docs_review",
    "rag": "general_project_rag",
    "auto": "general_project_rag",
    "kp": "procurement",
}

_FOLLOWUP_PREFIXES = (
    "добавь",
    "подпиши",
    "пересчитай",
    "убери",
    "замени",
    "покажи",
    "оформи",
    "экспортируй",
    "сделай",
)


def module_spec(module_id: str) -> ModuleSpec:
    return MODULE_REGISTRY.get(module_id) or MODULE_REGISTRY["general_project_rag"]


def classify_turn(user_input: str, *, has_active_state: bool = False) -> str:
    text = " ".join(str(user_input or "").casefold().split())
    if has_active_state and any(text.startswith(prefix) for prefix in _FOLLOWUP_PREFIXES):
        return "active_continuation"
    if any(word in text for word in ("экспорт", "xlsx", "pdf", "отчет", "отчёт")):
        return "export"
    if any(word in text for word in ("сравни", "сопостав", "разница")):
        return "comparison"
    if any(word in text for word in ("посчитай", "рассчитай", "стоимость", "сумма", "процент")):
        return "calculation_or_estimate"
    if any(word in text for word in ("проверь", "нормоконтроль", "замечания")):
        return "check"
    return "new_task"


def route_module(
    user_input: str,
    *,
    mode: str = "auto",
    active_state: dict[str, Any] | None = None,
) -> ModuleSpec:
    """Select a LES module for the turn without solving the domain task."""
    active_module = str((active_state or {}).get("module_id") or "").strip()
    turn_type = classify_turn(user_input, has_active_state=bool(active_module))
    if turn_type == "active_continuation" and active_module:
        return module_spec(active_module)

    mode_module = _MODE_TO_MODULE.get((mode or "").strip().lower())
    if mode_module and mode_module != "general_project_rag":
        return module_spec(mode_module)

    text = str(user_input or "").casefold()
    scores: dict[str, int] = {}
    for module_id, spec in MODULE_REGISTRY.items():
        scores[module_id] = sum(1 for trigger in spec.triggers if trigger in text)
    best = max(scores.items(), key=lambda item: item[1])
    if best[1] <= 0:
        return MODULE_REGISTRY["general_project_rag"]
    return MODULE_REGISTRY[best[0]]


def _feature_registry(status: str, reason_code: str | None, modules: dict[str, Any]) -> None:
    global _FEATURE_MODULES
    _FEATURE_MODULES = {
        "schema": "les.feature-modules.v1",
        "registry": {"status": status, "reason_code": reason_code},
        "modules": modules,
    }


def _load_manifest_factory(entry_point: str, *, package: str) -> Any:
    prefix = f"{package}."
    if not entry_point.startswith(prefix) or entry_point.count(":") != 1:
        raise ModuleContractError("MODULE_ENTRY_POINT_INVALID")
    module_name, attribute = entry_point.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, attribute)
    if not callable(factory):
        raise ModuleContractError("MODULE_ENTRY_POINT_INVALID")
    return factory


def load_enabled_modules(
    config_path: Path | None = None,
    package: str = "modules",
) -> tuple[ModuleManifest, ...]:
    """Load only manifests named in the explicit registry, isolating optional failures."""
    if not _SAFE_PACKAGE_RE.fullmatch(str(package or "")):
        _feature_registry("disabled", "MODULE_PACKAGE_INVALID", {})
        return ()

    path = Path(config_path) if config_path is not None else _DEFAULT_MODULE_CONFIG
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != _MODULE_CONFIG_SCHEMA:
            raise ValueError("schema")
        entries = payload.get("modules")
        if not isinstance(entries, list):
            raise ValueError("modules")
        normalized: list[dict[str, Any]] = []
        module_ids: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"module_id", "enabled", "manifest"}:
                raise ValueError("entry")
            module_id = entry.get("module_id")
            enabled = entry.get("enabled")
            manifest_entry = entry.get("manifest")
            if (
                not is_safe_module_id(module_id)
                or not isinstance(enabled, bool)
                or not isinstance(manifest_entry, str)
            ):
                raise ValueError("entry types")
            module_ids.append(module_id)
            normalized.append(entry)
        if len(module_ids) != len(set(module_ids)):
            _feature_registry("disabled", "MODULE_CONFIG_DUPLICATE_ID", {})
            return ()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        _feature_registry("disabled", "MODULE_CONFIG_INVALID", {})
        return ()

    reports: dict[str, Any] = {}
    loaded: list[ModuleManifest] = []
    for entry in normalized:
        module_id = entry["module_id"]
        if not entry["enabled"]:
            reports[module_id] = {
                "status": "disabled",
                "api_version": None,
                "capabilities": [],
                "reason_code": "MODULE_DISABLED",
            }
            continue
        try:
            factory = _load_manifest_factory(entry["manifest"], package=package)
            manifest = validate_manifest(factory(), module_id)
        except ModuleContractError as error:
            reports[module_id] = {
                "status": "disabled",
                "api_version": None,
                "capabilities": [],
                "reason_code": error.code,
            }
            continue
        except Exception:
            reports[module_id] = {
                "status": "disabled",
                "api_version": None,
                "capabilities": [],
                "reason_code": "MODULE_ENTRY_POINT_UNAVAILABLE",
            }
            continue
        loaded.append(manifest)
        reports[module_id] = {
            "status": "enabled",
            "api_version": manifest.api_version,
            "capabilities": list(manifest.capabilities),
            "reason_code": None,
        }

    _feature_registry("ready", None, reports)
    return tuple(loaded)


def module_registry_snapshot() -> dict[str, Any]:
    snapshot = {
        module_id: {
            "title": spec.title,
            "triggers": list(spec.triggers),
            "short_system_delta": spec.short_system_delta,
            "skill_snippets": list(spec.skill_snippets),
            "retrieval_scopes": list(spec.retrieval_scopes),
            "state_shape": list(spec.state_shape),
            "allowed_tools": list(spec.allowed_tools),
            "tool_policy": spec.tool_policy,
            "output_style": spec.output_style,
        }
        for module_id, spec in MODULE_REGISTRY.items()
    }
    snapshot["feature_modules"] = copy.deepcopy(_FEATURE_MODULES)
    return snapshot


def allowed_tool(module_id: str, tool_type: str) -> bool:
    return str(tool_type or "").strip().lower() in set(module_spec(module_id).allowed_tools)


def module_ids() -> Iterable[str]:
    return MODULE_REGISTRY.keys()
