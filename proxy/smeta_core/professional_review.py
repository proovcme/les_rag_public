"""Professional review contracts that never choose an estimating decision.

The deterministic layer records contradictions that a model or estimator must
review.  It may not replace a norm, coverage link, resource action or
coefficient.  Mapping revisions are append-only snapshots of model/user-owned
decisions; calculation revisions remain in :mod:`proxy.smeta_core.workflow`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import re
from typing import Any
from uuid import uuid4


_WORD_RE = re.compile(r"[а-яёa-z0-9]{4,}", re.IGNORECASE)
_DEMOLITION = ("демонтаж", "разборк", "снят", "разобрат")
_INSTALLATION = ("монтаж", "установк", "устройств", "прокладк", "креплен")


@dataclass(frozen=True)
class EvidenceBudget:
    """Independent technical limits; none of them selects a professional answer."""

    search_calls: int = 4
    read_calls: int = 4
    opened_cards: int = 12
    elapsed_seconds: float = 180.0

    def __post_init__(self) -> None:
        if min(self.search_calls, self.read_calls, self.opened_cards) < 1:
            raise ValueError("evidence budgets must be positive")
        if self.elapsed_seconds <= 0:
            raise ValueError("elapsed evidence budget must be positive")

    @classmethod
    def from_environment(cls) -> "EvidenceBudget":
        return cls(
            search_calls=int(os.getenv("LES_SMETA_SEARCH_BUDGET", "4")),
            read_calls=int(os.getenv("LES_SMETA_READ_BUDGET", "4")),
            opened_cards=int(os.getenv("LES_SMETA_OPENED_CARD_BUDGET", "12")),
            elapsed_seconds=float(os.getenv("LES_SMETA_TASK_TIME_BUDGET_SEC", "180")),
        )


@dataclass(frozen=True)
class ModelScopePlan:
    """Model-authored retrieval scope; code validates and executes it verbatim."""

    work_id: str
    scope_mode: str
    queries: tuple[str, ...]
    search_intents: tuple[str, ...]
    base_types: tuple[str, ...] = ()
    collections: tuple[str, ...] = ()
    explicit_scope_mode: bool = True
    schema: str = "smeta_scope_plan_v1"

    def __post_init__(self) -> None:
        if not self.work_id:
            raise ValueError("scope plan requires work_id")
        if self.scope_mode not in {"scoped", "global"}:
            raise ValueError("scope_mode must be scoped|global")
        if not self.queries:
            raise ValueError("scope plan requires at least one model query")
        if self.scope_mode == "scoped" and (not self.base_types or not self.collections):
            raise ValueError("scoped plan requires model-selected base_types and collections")
        if self.scope_mode == "global" and (self.base_types or self.collections):
            raise ValueError("global plan cannot contain base_types or collections")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for field_name in ("queries", "search_intents", "base_types", "collections"):
            payload[field_name] = list(payload[field_name])
        return payload


@dataclass(frozen=True)
class ProfessionalConflict:
    conflict_id: str
    code: str
    severity: str
    work_ids: tuple[str, ...]
    claim: str
    evidence: dict[str, Any]
    requires_model_review: bool = True
    schema: str = "smeta_professional_conflict_v1"

    def __post_init__(self) -> None:
        if self.severity not in {"warning", "error"}:
            raise ValueError("professional conflict severity must be warning|error")
        if not self.work_ids:
            raise ValueError("professional conflict requires work ids")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["work_ids"] = list(self.work_ids)
        return payload


@dataclass(frozen=True)
class MappingRevision:
    mapping_run_id: str
    revision_kind: str
    decisions: dict[str, dict[str, Any]]
    source_rows: tuple[dict[str, Any], ...]
    professional_conflicts: tuple[dict[str, Any], ...] = ()
    accepted_conflict_ids: tuple[str, ...] = ()
    calculation_context: dict[str, Any] = field(default_factory=dict)
    revision_id: str = field(default_factory=lambda: uuid4().hex)
    parent_revision_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "model"
    mapping_status: str = "mapping_selected"
    change_note: str = ""
    schema: str = "smeta_mapping_revision_v1"

    def __post_init__(self) -> None:
        if self.revision_kind not in {"row_mapping", "global_review", "user_lock"}:
            raise ValueError("unknown mapping revision kind")
        if self.created_by not in {"model", "user"}:
            raise ValueError("mapping revision owner must be model or user")
        allowed_statuses = {
            "mapping_selected", "mapping_globally_reviewed", "mapping_user_reviewed", "mapping_locked",
        }
        if self.mapping_status not in allowed_statuses:
            raise ValueError("unknown mapping status")
        if self.revision_kind == "user_lock" and self.mapping_status != "mapping_locked":
            raise ValueError("user lock revision must be mapping_locked")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["source_rows"] = list(self.source_rows)
        payload["professional_conflicts"] = list(self.professional_conflicts)
        payload["accepted_conflict_ids"] = list(self.accepted_conflict_ids)
        return payload


def save_mapping_revision(revision: MappingRevision, *, root: str | Path) -> Path:
    target_root = Path(root)
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / f"mapping_{revision.revision_id}.json"
    if target.exists():
        raise FileExistsError(f"mapping revision already exists: {revision.revision_id}")
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(revision.as_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp.replace(target)
    return target


def load_mapping_revision(revision_id: str, *, root: str | Path) -> dict[str, Any]:
    safe_id = "".join(ch for ch in str(revision_id) if ch.isalnum() or ch in {"-", "_"})
    if safe_id != revision_id or not safe_id:
        raise ValueError("invalid mapping revision id")
    return json.loads((Path(root) / f"mapping_{safe_id}.json").read_text(encoding="utf-8"))


def create_user_lock_revision(
    revision_id: str,
    *,
    root: str | Path,
    reviewed_by: str,
    review_note: str,
    accepted_conflict_ids: tuple[str, ...] = (),
) -> MappingRevision:
    """Create an explicit user-owned lock without rewriting the model revision."""

    source = load_mapping_revision(revision_id, root=root)
    if str(source.get("revision_kind") or "") == "user_lock":
        raise ValueError("mapping revision is already locked")
    source_status = str(source.get("mapping_status") or "")
    single_row_mapping = source_status == "mapping_selected" and len(source.get("source_rows") or []) == 1
    if source_status != "mapping_globally_reviewed" and not single_row_mapping:
        raise ValueError("only a globally reviewed mapping can be locked")
    if not str(reviewed_by or "").strip():
        raise ValueError("reviewed_by is required")
    if not str(review_note or "").strip():
        raise ValueError("review_note is required")
    required_conflicts = {
        str(item.get("conflict_id") or "")
        for item in (source.get("professional_conflicts") or [])
        if str(item.get("conflict_id") or "")
    }
    accepted = {str(item) for item in accepted_conflict_ids if str(item)}
    missing = sorted(required_conflicts - accepted)
    if missing:
        raise ValueError(
            "professional conflicts must be explicitly accepted before lock: " + ", ".join(missing)
        )
    revision = MappingRevision(
        mapping_run_id=str(source.get("mapping_run_id") or ""),
        revision_kind="user_lock",
        decisions=dict(source.get("decisions") or {}),
        source_rows=tuple(source.get("source_rows") or ()),
        professional_conflicts=(),
        accepted_conflict_ids=tuple(sorted(accepted)),
        calculation_context=dict(source.get("calculation_context") or {}),
        parent_revision_id=revision_id,
        created_by="user",
        mapping_status="mapping_locked",
        change_note=f"{reviewed_by}: {review_note.strip()}",
    )
    save_mapping_revision(revision, root=root)
    return revision


def _conflict(
    code: str,
    work_ids: tuple[str, ...],
    claim: str,
    evidence: dict[str, Any],
    *,
    severity: str = "error",
) -> ProfessionalConflict:
    return ProfessionalConflict(
        conflict_id=uuid4().hex,
        code=code,
        severity=severity,
        work_ids=work_ids,
        claim=claim,
        evidence=evidence,
    )


def _card_text(cards: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for card in cards:
        parts.extend([
            str(card.get("title") or card.get("norm_name") or ""),
            str(card.get("work_steps") or card.get("composition") or ""),
        ])
    return " ".join(parts).casefold()


def _tokens(value: object) -> set[str]:
    stop = {"работ", "устройств", "монтаж", "установк", "систем", "комплект"}
    return {token.casefold() for token in _WORD_RE.findall(str(value or "")) if token.casefold() not in stop}


def detect_professional_conflicts(
    work_rows: list[dict[str, Any]],
    selections: dict[str, dict[str, Any]],
    *,
    opened_cards: dict[str, list[dict[str, Any]]] | None = None,
    query_trace: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return evidence-backed contradictions without mutating ``selections``."""

    rows = {str(row.get("work_id") or ""): row for row in work_rows}
    opened_cards = opened_cards or {}
    intents_by_work: dict[str, set[str]] = {}
    for item in query_trace or []:
        work_id = str(item.get("work_id") or "")
        intents_by_work.setdefault(work_id, set()).update(
            str(value).strip() for value in (item.get("search_intents") or []) if str(value).strip()
        )
    conflicts: list[ProfessionalConflict] = []
    for work_id, selection in selections.items():
        row = rows.get(work_id) or {}
        norm_code = str(selection.get("norm_code") or "")
        provider = str(selection.get("covered_by_work_id") or "")
        applicability = str(selection.get("applicability") or "")
        kind = str(selection.get("selection_kind") or "")
        limitations = [str(item) for item in (selection.get("analog_limitations") or []) if str(item).strip()]
        technology = selection.get("technology_check") if isinstance(selection.get("technology_check"), dict) else {}

        if norm_code and (applicability in {"close_analog", "weak_analog"} or limitations) and kind == "exact":
            conflicts.append(_conflict(
                "analog_declared_exact", (work_id,),
                "Строка объявлена exact, но модель одновременно зафиксировала признаки аналога.",
                {"norm_code": norm_code, "applicability": applicability, "analog_limitations": limitations},
            ))
        if norm_code and (
            str(technology.get("conclusion") or "") == "not_applicable"
            or bool(technology.get("missing_operations"))
            or bool(technology.get("unresolved_conditions"))
        ):
            conflicts.append(_conflict(
                "technology_check_contradicts_bind", (work_id,),
                "Модель выбрала bind, хотя её собственная технологическая проверка содержит конфликт.",
                {"norm_code": norm_code, "technology_check": technology},
            ))
        title = str(row.get("title") or "").casefold()
        card_text = _card_text(opened_cards.get(work_id) or [])
        if norm_code and any(token in title for token in _DEMOLITION):
            card_has_demolition = any(token in card_text for token in _DEMOLITION)
            card_has_installation = any(token in card_text for token in _INSTALLATION)
            if card_text and card_has_installation and not card_has_demolition:
                conflicts.append(_conflict(
                    "operation_direction_conflict", (work_id,),
                    "Исходная строка описывает демонтаж, а открытая карточка подтверждает только монтажную операцию.",
                    {"norm_code": norm_code, "source_title": row.get("title"), "opened_card_text": card_text[:1200]},
                ))
        actions_by_target: dict[str, set[str]] = {}
        for action in selection.get("resource_bindings") or []:
            if not isinstance(action, dict):
                continue
            target = str(action.get("target_resource_code") or action.get("target_resource_name") or "").strip().casefold()
            if target:
                actions_by_target.setdefault(target, set()).add(str(action.get("action") or ""))
        for target, actions in actions_by_target.items():
            if len(actions) > 1:
                conflicts.append(_conflict(
                    "resource_action_collision", (work_id,),
                    "Один ресурс получил несколько несовместимых модельных действий.",
                    {"target_resource": target, "actions": sorted(actions)},
                ))
        coefficient_values = {
            key: selection.get(key)
            for key in ("coefficient_value", "k_ozp", "k_em")
            if selection.get(key) not in (None, "", 1, 1.0)
        }
        if coefficient_values and not str(selection.get("coefficient_source_ref") or "").strip():
            conflicts.append(_conflict(
                "coefficient_source_missing", (work_id,),
                "Модель предложила числовой коэффициент без ссылки на типизированное нормативное значение.",
                {"coefficient_values": coefficient_values},
            ))
        if provider:
            provider_selection = selections.get(provider) or {}
            if provider not in rows or not provider_selection.get("norm_code"):
                conflicts.append(_conflict(
                    "coverage_provider_invalid", (work_id, provider),
                    "covered_by ссылается на строку без прямой выбранной нормы.",
                    {"covered_by_work_id": provider, "provider_selection": provider_selection},
                ))
            else:
                provider_text = _card_text(opened_cards.get(provider) or [])
                source_tokens = _tokens(row.get("title"))
                evidence_tokens = _tokens(provider_text)
                if provider_text and source_tokens and not source_tokens.intersection(evidence_tokens):
                    conflicts.append(_conflict(
                        "coverage_not_evidenced", (work_id, provider),
                        "В открытой карточке строки-провайдера не найдено лексического подтверждения покрываемой операции.",
                        {
                            "covered_title": row.get("title"),
                            "provider_norm_code": provider_selection.get("norm_code"),
                            "provider_card_text": provider_text[:1200],
                        },
                        severity="warning",
                    ))
        if not norm_code and not provider:
            intents = intents_by_work.get(work_id) or set()
            if intents and len(intents) < 2:
                conflicts.append(_conflict(
                    "unbound_search_intent_narrow", (work_id,),
                    "Unbound основан менее чем на двух различных поисковых намерениях.",
                    {"search_intents": sorted(intents)},
                    severity="warning",
                ))

    bound_by_norm: dict[str, list[str]] = {}
    for work_id, selection in selections.items():
        norm_code = str((selection or {}).get("norm_code") or "").strip()
        if norm_code:
            bound_by_norm.setdefault(norm_code, []).append(str(work_id))
    for norm_code, work_ids in bound_by_norm.items():
        for index, left_id in enumerate(work_ids):
            left = rows.get(left_id) or {}
            left_tokens = _tokens(left.get("title"))
            for right_id in work_ids[index + 1:]:
                right = rows.get(right_id) or {}
                right_tokens = _tokens(right.get("title"))
                smaller = min(len(left_tokens), len(right_tokens))
                overlap = (
                    len(left_tokens.intersection(right_tokens)) / smaller
                    if smaller else 0.0
                )
                same_unit = str(left.get("unit") or "").strip().casefold() == str(
                    right.get("unit") or ""
                ).strip().casefold()
                same_section = str(left.get("section") or "").strip().casefold() == str(
                    right.get("section") or ""
                ).strip().casefold()
                if same_unit and same_section and overlap >= 0.5:
                    conflicts.append(_conflict(
                        "possible_duplicate_norm_binding",
                        (left_id, right_id),
                        "Две похожие строки одного раздела получили одну норму; требуется проверить coverage и двойной учет.",
                        {
                            "norm_code": norm_code,
                            "left_title": left.get("title"),
                            "right_title": right.get("title"),
                            "title_token_overlap": round(overlap, 4),
                            "unit": left.get("unit"),
                            "section": left.get("section"),
                        },
                        severity="warning",
                    ))
    return [item.as_dict() for item in conflicts]


def mapping_quality_metrics(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Professional golden metrics; no dataset-specific answer enters runtime code."""

    ids = sorted(set(expected) | set(actual))
    counters = {
        "rows": len(ids), "expected_bind": 0, "actual_bind": 0, "correct_bind": 0,
        "wrong_bind": 0, "hallucinated_norm": 0, "expected_unbound": 0,
        "correct_unbound": 0, "expected_covered_by": 0, "actual_covered_by": 0,
        "correct_covered_by": 0,
        "opened_card_evaluable_bind": 0, "unopened_card_bind": 0,
        "unit_conflict": 0, "resource_double_count": 0,
        "price_evaluable_bind": 0, "price_complete_bind": 0,
    }
    for work_id in ids:
        exp = expected.get(work_id) or {}
        got = actual.get(work_id) or {}
        exp_code = str(exp.get("norm_code") or "")
        got_code = str(got.get("norm_code") or "")
        exp_coverage = str(exp.get("covered_by_work_id") or "")
        got_coverage = str(got.get("covered_by_work_id") or "")
        if exp_code:
            counters["expected_bind"] += 1
        if got_code:
            counters["actual_bind"] += 1
            if got_code == exp_code:
                counters["correct_bind"] += 1
            else:
                counters["wrong_bind"] += 1
                if not exp_code:
                    counters["hallucinated_norm"] += 1
            opened_codes = got.get("opened_norm_codes")
            if isinstance(opened_codes, list):
                counters["opened_card_evaluable_bind"] += 1
                if got_code not in {str(item) for item in opened_codes}:
                    counters["unopened_card_bind"] += 1
            if "price_complete" in got:
                counters["price_evaluable_bind"] += 1
                if bool(got.get("price_complete")):
                    counters["price_complete_bind"] += 1
        if bool(got.get("unit_conflict")):
            counters["unit_conflict"] += 1
        if bool(got.get("resource_double_count")):
            counters["resource_double_count"] += 1
        if not exp_code and not exp_coverage:
            counters["expected_unbound"] += 1
            if not got_code and not got_coverage:
                counters["correct_unbound"] += 1
        if exp_coverage:
            counters["expected_covered_by"] += 1
        if got_coverage:
            counters["actual_covered_by"] += 1
        if exp_coverage and got_coverage == exp_coverage:
            counters["correct_covered_by"] += 1

    def ratio(numerator: str, denominator: str) -> float | None:
        base = counters[denominator]
        return round(counters[numerator] / base, 4) if base else None

    return {
        "schema": "smeta_mapping_quality_metrics_v1",
        **counters,
        "exact_bind_precision": ratio("correct_bind", "actual_bind"),
        "wrong_bind_rate": ratio("wrong_bind", "actual_bind"),
        "unbound_recall": ratio("correct_unbound", "expected_unbound"),
        "covered_by_precision": ratio("correct_covered_by", "actual_covered_by"),
        "unopened_card_bind_rate": ratio("unopened_card_bind", "opened_card_evaluable_bind"),
        "unit_conflict_rate": ratio("unit_conflict", "rows"),
        "resource_double_count_rate": ratio("resource_double_count", "rows"),
        "price_completeness": ratio("price_complete_bind", "price_evaluable_bind"),
    }
