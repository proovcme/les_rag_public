"""Типизированные границы нового сметного ядра.

Здесь намеренно нет ранжирования, выбора норм и профессиональных правил. Контракты
фиксируют то, что выбрала модель, и то, что затем проверил/посчитал код.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class EvidenceStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class CalculationStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNSAFE_SOURCE = "unsafe_source"
    NOT_CALCULATED = "not_calculated"


@dataclass(frozen=True)
class WorkItem:
    work_id: str
    title: str
    quantity: float | None = None
    unit: str = ""
    section: str = ""
    source_row: int | None = None
    note: str = ""
    source_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormCandidate:
    """Карточка retrieval-кандидата, а не решение кода."""

    norm_code: str
    title: str
    measure_unit: str
    source_ref: str = ""
    applicability_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormBinding:
    """Явное решение модели/пользователя, которое код может валидировать."""

    work_id: str
    norm_code: str
    selected_by: str
    selection_kind: str
    is_analog: bool
    reason: str = ""
    source_refs: tuple[str, ...] = ()
    analog_limitations: tuple[str, ...] = ()
    applicability: str = ""
    technology_check: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.selected_by not in {"model", "user"}:
            raise ValueError("selected_by must be 'model' or 'user'; code cannot select a norm")


@dataclass(frozen=True)
class CoverageBinding:
    """One composite priced norm explicitly covers another visible VOR row."""

    work_id: str
    covered_by_work_id: str
    selected_by: str
    reason: str
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.selected_by not in {"model", "user"}:
            raise ValueError("coverage decision belongs to model or user")
        if not self.work_id or not self.covered_by_work_id or self.work_id == self.covered_by_work_id:
            raise ValueError("coverage requires two distinct work ids")
        if not self.reason.strip():
            raise ValueError("coverage requires an explicit reason")


@dataclass(frozen=True)
class NRSPBinding:
    """Explicit choice when an official collection has more than one NR/SP row."""

    work_id: str
    rule_id: str
    selected_by: str
    reason: str = ""
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.selected_by not in {"model", "user"}:
            raise ValueError("NR/SP choice belongs to model or user")


@dataclass(frozen=True)
class ResourceLine:
    work_id: str
    norm_code: str
    kind: str
    name: str
    unit: str
    quantity: float
    code: str = ""
    price: float | None = None
    price_source: str = ""
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceBinding:
    """Explicit model/user decision over a norm resource or a project material.

    Code applies the decision and resolves an exact FGIS code. It never invents
    a replacement, exclusion, reuse rule, quantity or price.
    """

    work_id: str
    action: str
    selected_by: str
    resource_name: str = ""
    resource_code: str = ""
    unit: str = ""
    quantity: float | None = None
    quantity_basis: str = "explicit"
    target_resource_code: str = ""
    target_resource_name: str = ""
    explicit_price: float | None = None
    price_source_ref: str = ""
    reason: str = ""
    basis_ref: str = ""
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.selected_by not in {"model", "user"}:
            raise ValueError("resource decision belongs to model or user")
        if self.action not in {"add", "replace", "exclude", "reuse"}:
            raise ValueError("resource action must be add|replace|exclude|reuse")
        if self.action in {"add", "replace"}:
            if self.quantity_basis not in {"explicit", "target_norm", "source_work"}:
                raise ValueError("resource quantity_basis must be explicit|target_norm|source_work")
            if not self.resource_name.strip() or not self.unit.strip():
                raise ValueError("add/replace requires resource_name and unit")
            if self.quantity_basis == "explicit" and self.quantity is None:
                raise ValueError("explicit resource quantity is required")
            if self.quantity is not None and float(self.quantity) < 0:
                raise ValueError("resource quantity cannot be negative")
            if self.quantity_basis == "target_norm" and self.action != "replace":
                raise ValueError("target_norm quantity is valid only for replace")
            if self.quantity_basis == "source_work" and self.action != "add":
                raise ValueError("source_work quantity is valid only for add")
        if self.action in {"replace", "exclude", "reuse"} and not (
            self.target_resource_code.strip() or self.target_resource_name.strip()
        ):
            raise ValueError("replace/exclude/reuse requires an explicit target resource")
        if self.explicit_price is not None and not self.price_source_ref.strip():
            raise ValueError("an explicit price requires price_source_ref")


@dataclass(frozen=True)
class ResourceReview:
    """Explicit model/user confirmation of the selected norm resource set."""

    work_id: str
    status: str
    selected_by: str
    reason: str = ""
    labor_status: str = "unresolved"
    labor_reason: str = ""
    machine_status: str = "unresolved"
    machine_reason: str = ""
    material_status: str = "unresolved"
    material_reason: str = ""
    dominant_status: str = "not_required"
    dominant_reason: str = ""

    def __post_init__(self) -> None:
        if self.selected_by not in {"model", "user"}:
            raise ValueError("resource review belongs to model or user")
        if self.status not in {"keep_all_confirmed", "actions_confirmed", "unresolved"}:
            raise ValueError("resource review status is invalid")
        if self.status != "unresolved" and not self.reason.strip():
            raise ValueError("confirmed resource review requires a reason")
        allowed = {"confirmed", "not_present", "unresolved", "rejected"}
        components = (
            ("labor", self.labor_status, self.labor_reason),
            ("machine", self.machine_status, self.machine_reason),
            ("material", self.material_status, self.material_reason),
        )
        for name, status, reason in components:
            if status not in allowed:
                raise ValueError(f"{name} review status is invalid")
            if status in {"confirmed", "rejected"} and not reason.strip():
                raise ValueError(f"{name} review requires a reason")
        if self.dominant_status not in {"not_required", "confirmed", "unresolved"}:
            raise ValueError("dominant review status is invalid")
        if self.dominant_status in {"confirmed", "unresolved"} and not self.dominant_reason.strip():
            raise ValueError("dominant review requires a reason")

    def component_confirmed(self, component: str) -> bool:
        return str(getattr(self, f"{component}_status", "unresolved")) in {
            "confirmed", "not_present",
        }


@dataclass(frozen=True)
class PriceTraceRecord:
    resource_code: str
    price: float | None
    source_type: str
    source_ref: str = ""
    region: str = ""
    period: str = ""
    note: str = ""


@dataclass(frozen=True)
class CoefficientTrace:
    coefficient_id: str
    value: float
    applies_to: tuple[str, ...]
    selected_by: str
    source_ref: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        if self.selected_by not in {"model", "user"}:
            raise ValueError("coefficient selection belongs to model or user")


@dataclass
class LSRScenario:
    scenario_id: str
    title: str
    work_items: list[WorkItem]
    bindings: list[NormBinding]
    resource_bindings: list[ResourceBinding]
    resource_reviews: list[ResourceReview]
    coverage_bindings: list[CoverageBinding]
    nr_sp_bindings: list[NRSPBinding]
    price_trace_records: list[PriceTraceRecord]
    coefficient_traces: list[CoefficientTrace]
    trace: dict[str, Any]
    evidence_status: EvidenceStatus
    calculation_status: CalculationStatus
    amount_known: float = 0.0
    blockers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema: str = "lsr_scenario_v1"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_status"] = self.evidence_status.value
        payload["calculation_status"] = self.calculation_status.value
        return payload


@dataclass
class LSRRevision:
    scenario: LSRScenario
    revision_id: str = field(default_factory=lambda: uuid4().hex)
    parent_revision_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "model"
    change_note: str = ""
    schema: str = "lsr_revision_v1"

    def __post_init__(self) -> None:
        if self.created_by not in {"model", "user"}:
            raise ValueError("revision owner must be model or user")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scenario"]["evidence_status"] = self.scenario.evidence_status.value
        payload["scenario"]["calculation_status"] = self.scenario.calculation_status.value
        return payload


@dataclass
class SmetaWorkflowResult:
    evidence_status: EvidenceStatus
    calculation_status: CalculationStatus
    amount_known: float = 0.0
    blockers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)

    schema: str = "smeta_workflow_result_v1"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_status"] = self.evidence_status.value
        payload["calculation_status"] = self.calculation_status.value
        return payload
