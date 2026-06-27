"""Evidence contract — единый формат доказательной выдачи (Construction RAG Harness v0.1).

RAG перестаёт быть «отдал контекст LLM» и становится evidence-driven: каждый факт/число
в ответе несёт ТИП происхождения. LLM связывает, но не добавляет фактов/чисел вне контракта.

ИНВАРИАНТ (проверяется в коде, НЕ в промпте):
  • RETRIEVED-факт обязан иметь source_refs.
  • Любое ЧИСЛО (value!=None) обязано быть COMPUTED (формула/входы) | RETRIEVED (источник) |
    ASSUMED (допущение). MISSING/BLOCKED — без значения (нет основания).
  • LLM НЕ имеет права вставить число, которого нет в evidence-контракте.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceType(str, Enum):
    RETRIEVED = "RETRIEVED"   # извлечено из источника (норма/документ/таблица)
    COMPUTED = "COMPUTED"     # вычислено кодом по формуле над входами
    ASSUMED = "ASSUMED"       # принято допущением (явно)
    MISSING = "MISSING"       # нет данных/входа (нельзя посчитать)
    BLOCKED = "BLOCKED"       # отклонено предохранителем (норма/единица/магнитуда)


class DefenseStatus(str, Enum):
    SUPPORTED = "supported"                 # подтверждено источником/проверкой
    COMPUTED = "computed"                   # вычислено кодом и воспроизводимо
    ASSUMED = "assumed"                     # принято допущением
    MISSING = "missing"                     # не хватает данных
    BLOCKED = "blocked"                     # остановлено guardrail
    PARTIAL = "partial"                     # часть основания есть, часть отсутствует
    MANUAL_REQUIRED = "manual_required"     # нужен инженерный/операторский вердикт
    NOT_DEFENSIBLE = "not_defensible"       # нельзя защищать как финальный результат


# Типы, которым РАЗРЕШЕНО нести число.
_VALUE_TYPES = {EvidenceType.RETRIEVED, EvidenceType.COMPUTED, EvidenceType.ASSUMED}


class EvidenceError(ValueError):
    """Нарушение инварианта evidence-контракта."""


@dataclass
class EvidenceItem:
    type: EvidenceType
    title: str
    value: float | None = None
    unit: str = ""
    source_refs: list[str] = field(default_factory=list)
    formula: str = ""
    inputs: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    status: str = "supported"   # supported | computed | preliminary | missing | blocked | rejected

    def __post_init__(self) -> None:
        # число только у разрешённых типов
        if self.value is not None and self.type not in _VALUE_TYPES:
            raise EvidenceError(f"{self.type.value} не может нести число (value={self.value})")
        # RETRIEVED обязан иметь источник
        if self.type is EvidenceType.RETRIEVED and not self.source_refs:
            raise EvidenceError(f"RETRIEVED без source_refs: {self.title!r}")
        # COMPUTED с числом обязан иметь основание (формула/входы/источник)
        if self.type is EvidenceType.COMPUTED and self.value is not None \
                and not (self.formula or self.inputs or self.source_refs):
            raise EvidenceError(f"COMPUTED без provenance (формула/входы/источник): {self.title!r}")
        # ASSUMED обязан нести явное допущение
        if self.type is EvidenceType.ASSUMED and not self.assumptions:
            raise EvidenceError(f"ASSUMED без явного допущения: {self.title!r}")

    def payload(self) -> dict[str, Any]:
        return {"type": self.type.value, "title": self.title, "value": self.value, "unit": self.unit,
                "source_refs": self.source_refs, "formula": self.formula, "inputs": self.inputs,
                "assumptions": self.assumptions, "blockers": self.blockers, "status": self.status}


@dataclass
class EvidenceBlock:
    type: EvidenceType
    title: str
    items: list[EvidenceItem] = field(default_factory=list)
    status: str = ""

    def payload(self) -> dict[str, Any]:
        return {"type": self.type.value, "title": self.title, "status": self.status,
                "items": [i.payload() for i in self.items]}


@dataclass
class DefenseClaim:
    """Одна защищаемая единица ответа: утверждение, расчётная строка или замечание.

    Это системный слой над evidence: UI/экспорт/нормоконтроль могут показывать одинаковую
    структуру "что утверждаем → на чём стоит → чего не хватает → кто финализирует".
    """
    id: str
    title: str
    statement: str
    status: DefenseStatus | str
    domain: str = ""
    severity: str = ""
    value: float | None = None
    unit: str = ""
    source_refs: list[str] = field(default_factory=list)
    formulas: list[dict[str, Any]] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    related_evidence: list[str] = field(default_factory=list)
    confidence: float | None = None

    def __post_init__(self) -> None:
        self.status = DefenseStatus(self.status)
        if self.status is DefenseStatus.SUPPORTED and not (self.source_refs or self.formulas or self.inputs):
            raise EvidenceError(f"DefenseClaim supported без основания: {self.id!r}")
        if self.status is DefenseStatus.COMPUTED and not (self.formulas or self.inputs or self.source_refs):
            raise EvidenceError(f"DefenseClaim computed без формулы/inputs/source_ref: {self.id!r}")
        if self.status is DefenseStatus.ASSUMED and not self.assumptions:
            raise EvidenceError(f"DefenseClaim assumed без assumptions: {self.id!r}")
        if self.status in (DefenseStatus.MISSING, DefenseStatus.BLOCKED) and not (self.gaps or self.actions):
            raise EvidenceError(f"DefenseClaim {self.status.value} без gaps/actions: {self.id!r}")
        if self.status is DefenseStatus.NOT_DEFENSIBLE and not (self.gaps or self.assumptions or self.actions):
            raise EvidenceError(f"DefenseClaim not_defensible без причины: {self.id!r}")

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "statement": self.statement,
            "status": self.status.value, "domain": self.domain, "severity": self.severity,
            "value": self.value, "unit": self.unit, "source_refs": self.source_refs,
            "formulas": self.formulas, "inputs": self.inputs, "assumptions": self.assumptions,
            "gaps": self.gaps, "actions": self.actions, "related_evidence": self.related_evidence,
            "confidence": self.confidence,
        }


@dataclass
class DefensePack:
    """Единый защитный пакет результата: смета, нормоконтроль, сверка, таблица."""
    domain: str
    title: str
    status: DefenseStatus | str
    claims: list[DefenseClaim] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    required_actions: list[str] = field(default_factory=list)
    schema: str = "defense_contract_v1"

    def __post_init__(self) -> None:
        self.status = DefenseStatus(self.status)

    def payload(self) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        for claim in self.claims:
            key = claim.status.value
            by_status[key] = by_status.get(key, 0) + 1
        return {
            "schema": self.schema, "domain": self.domain, "title": self.title,
            "status": self.status.value, "summary": {**self.summary, "by_status": by_status},
            "coverage": self.coverage, "required_actions": self.required_actions,
            "claims": [c.payload() for c in self.claims],
        }


@dataclass
class ConstructionHarnessResult:
    answer_data: dict[str, Any]
    evidence_blocks: list[EvidenceBlock] = field(default_factory=list)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    total_status: str = "no_data"        # complete | partial | blocked | no_data
    warnings: list[str] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)
    partial_total: float | None = None   # диагностика, НЕ смета
    final_total: float | None = None     # только при total_status=complete

    def payload(self) -> dict[str, Any]:
        return {
            "answer_data": self.answer_data,
            "evidence_blocks": [b.payload() for b in self.evidence_blocks],
            "tool_trace": self.tool_trace,
            "sources": self.sources,
            "total_status": self.total_status,
            "warnings": self.warnings,
            "blockers": self.blockers,
            "partial_total": self.partial_total,
            "final_total": self.final_total,
        }


def block_of(etype: EvidenceType, title: str, items: list[EvidenceItem]) -> EvidenceBlock:
    """Собрать блок; пустой статус выводим из наличия items."""
    return EvidenceBlock(type=etype, title=title, items=items,
                         status=("present" if items else "empty"))


def numbers_in_answer_have_provenance(result: ConstructionHarnessResult) -> bool:
    """Инвариант для теста: каждое число в evidence — из разрешённого типа с основанием.
    (Конструктор EvidenceItem уже это гарантирует; функция — явная проверка для golden.)"""
    for blk in result.evidence_blocks:
        for it in blk.items:
            if it.value is not None and it.type not in _VALUE_TYPES:
                return False
    return True
