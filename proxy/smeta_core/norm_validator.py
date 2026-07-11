"""Formal validation after a model/user selected a norm.

No ranking or semantic norm choice lives here. The validator only proves identity,
quantity/unit conversion and machine-base integrity for an explicit binding.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from proxy.services import gesn_service
from proxy.smeta_core.contracts import NormBinding, WorkItem
from proxy.smeta_core.integrity import normative_base_integrity


_FULL_NORM_CODE_RE = re.compile(
    r"^(?:ГЭСНМР|ГЭСНМ|ГЭСНП|ГЭСНР|ГЭСН|ФЕРМР|ФЕРМ|ФЕРП|ФЕРР|ФЕР|ТЕРМР|ТЕРМ|ТЕРП|ТЕРР|ТЕР)"
    r"\s*:?\s*\d{2}-\d{2}-\d{3}-\d{2}$",
    re.IGNORECASE,
)


def _canon_unit(value: Any) -> str:
    text = str(value or "").strip().lower().replace("³", "3").replace("²", "2")
    text = text.replace("пог. м", "м").replace("п.м.", "м").replace("шт.", "шт")
    text = re.sub(r"\s+", "", text)
    aliases = {
        "м2": "м2", "м3": "м3", "м": "м", "км": "км", "шт": "шт", "т": "т", "кг": "кг",
        "отверстие": "шт", "отверстия": "шт", "отверстий": "шт", "проем": "шт", "проемы": "шт",
    }
    compound_aliases = {
        "мтруб": "м", "мтрубы": "м", "мтрубопровода": "м",
        "мкабеля": "м", "мкабелей": "м", "мпровода": "м", "мпроводов": "м",
        "мтрассы": "м", "млинии": "м", "млиний": "м",
        "м2поверхности": "м2", "м2площади": "м2", "м2покрытия": "м2",
        "м3конструкций": "м3", "м3грунта": "м3",
        "штизделий": "шт", "штустройств": "шт", "штэлементов": "шт",
    }
    if text in compound_aliases:
        return compound_aliases[text]
    return aliases.get(text, text)


def _norm_measure(value: Any) -> tuple[float, str]:
    match = re.match(r"\s*(\d+(?:[.,]\d+)?)?\s*(.+?)\s*$", str(value or ""))
    if not match:
        return 1.0, _canon_unit(value)
    factor = float((match.group(1) or "1").replace(",", "."))
    return factor, _canon_unit(match.group(2))


def _convert_quantity(quantity: float, source_unit: str, target_unit: str) -> float | None:
    if source_unit == target_unit:
        return quantity
    factor = {
        ("кг", "т"): 0.001,
        ("т", "кг"): 1000.0,
        ("м", "км"): 0.001,
        ("км", "м"): 1000.0,
    }.get((source_unit, target_unit))
    return quantity * factor if factor is not None else None


def units_compatible(source_unit: str, norm_measure: str) -> bool:
    """Formal convertibility only; no semantic norm applicability decision."""
    _, target_unit = _norm_measure(norm_measure)
    source = _canon_unit(source_unit)
    return bool(source and target_unit and _convert_quantity(1.0, source, target_unit) is not None)


def validate_binding(work: WorkItem, binding: NormBinding) -> dict[str, Any]:
    if binding.work_id != work.work_id:
        return {"schema": "norm_binding_validation_v1", "status": "rejected", "reason": "work_id mismatch"}
    if work.quantity is None or float(work.quantity) < 0:
        return {"schema": "norm_binding_validation_v1", "status": "rejected", "reason": "quantity is missing"}
    if not _FULL_NORM_CODE_RE.fullmatch(str(binding.norm_code or "").strip()):
        return {
            "schema": "norm_binding_validation_v1",
            "status": "rejected",
            "reason": "full typed norm code is required",
        }
    norm = gesn_service.get_norm(binding.norm_code, strict_family=True)
    if norm is None:
        return {"schema": "norm_binding_validation_v1", "status": "rejected", "reason": "exact norm code not found"}

    measure_factor, norm_unit = _norm_measure(norm.get("unit"))
    physical_unit = _canon_unit(work.unit)
    converted = _convert_quantity(float(work.quantity), physical_unit, norm_unit)
    if converted is None:
        return {
            "schema": "norm_binding_validation_v1",
            "status": "rejected",
            "reason": "unit mismatch",
            "physical_unit": physical_unit,
            "norm_unit": norm_unit,
        }
    norm_quantity = converted / measure_factor if measure_factor else converted
    unit_conversion_factor = (
        norm_quantity / float(work.quantity)
        if float(work.quantity) != 0.0
        else (1.0 / measure_factor if measure_factor else 1.0)
    )

    source_kind = str(norm.get("_source_kind") or "seed_yaml")
    if source_kind == "structured_sqlite":
        integrity = normative_base_integrity(base_path=str(norm.get("_source_path") or ""))
    else:
        integrity = {"status": "trusted", "trusted_for_pricing": True, "source_kind": source_kind}
    status = "accepted" if integrity.get("trusted_for_pricing") else "unsafe_source"
    return {
        "schema": "norm_binding_validation_v1",
        "status": status,
        "work": asdict(work),
        "binding": asdict(binding),
        "norm": {
            "code": norm.get("code") or binding.norm_code,
            "name": norm.get("name") or "",
            "unit": norm.get("unit") or "",
            "source_kind": source_kind,
            "source_path": norm.get("_source_path") or "",
        },
        "physical_quantity": float(work.quantity),
        "physical_unit": physical_unit,
        "measure_factor": measure_factor,
        "norm_unit": norm_unit,
        "unit_conversion_factor": unit_conversion_factor,
        "norm_quantity": norm_quantity,
        "source_integrity": integrity,
    }
