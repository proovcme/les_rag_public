"""Apply terminal model-authored resource actions without choosing resources.

The active row adapter owns the operation identity. This pure boundary validates
each explicit action before changing its exact target and preserves rejected
proposals separately from the resources the calculator actually receives.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

from proxy.smeta_core.contracts import ResourceBinding, ResourceReview
from proxy.smeta_core.unit_contract import norm_measure


RESOURCE_BINDING_FIELDS = frozenset({
    "action", "resource_name", "resource_code", "unit", "quantity", "quantity_basis",
    "target_resource_code", "target_resource_name", "explicit_price", "price_source_ref",
    "reason", "basis_ref", "source_refs", "kind", "target_resource_ref",
})
RESOURCE_REVIEW_FIELDS = frozenset({
    "status", "reason", "labor_status", "labor_reason", "machine_status", "machine_reason",
    "material_status", "material_reason", "dominant_status", "dominant_reason",
})


def resource_binding_conflict_note(conflict: Mapping[str, Any]) -> str:
    """Translate technical resource failures for the generated file/operator."""
    if conflict.get("code") == "separate_supply_possible_overlap":
        return "Возможное пересечение отдельной поставки с материалами нормы не разрешено; состав ресурсов сохранён."
    if conflict.get("code") == "resource_binding_evidence_unverified":
        return "Источники действия над ресурсом не проверены по показанным материалам."
    reason = str(conflict.get("reason") or "")
    messages = {
        "resource target is missing or ambiguous": "Целевой ресурс отсутствует или указан неоднозначно.",
        "resource address is unresolved or disagrees with its target": "Адрес ресурса не разрешён или противоречит указанному ресурсу.",
        "resource action has unresolved evidence references": "Ссылки действия над ресурсом не разрешены.",
        "resource action target, selection or price is not substantiated by shown evidence": "Целевой ресурс, выбор или цена не подтверждены показанными источниками.",
        "quantity must be positive and finite": "Количество должно быть положительным конечным числом.",
        "price must be nonnegative and finite": "Цена должна быть неотрицательным конечным числом.",
        "a finite numeric value is required": "Требуется конечное числовое значение.",
        "resource quantity units are incompatible": "Единицы количества ресурса несовместимы.",
        "resource unit scale must be positive and finite": "Масштаб единицы ресурса должен быть положительным конечным числом.",
        "resource_bindings must be an array of objects": "Действия над ресурсами должны быть переданы списком объектов.",
        "resource action requires a reason and source_refs or basis_ref": "Для действия над ресурсом нужны пояснение и ссылки на основание.",
        "source_refs must be an array of nonempty strings": "Ссылки на источники должны быть списком непустых строк.",
        "reuse cannot carry a nonzero explicit price": "Повторное использование ресурса несовместимо с ненулевой ценой.",
        "a material replacement cannot reinterpret another resource kind": "Материалом нельзя заменить ресурс другого вида.",
        "add/replace resource kind must be material": "Добавление и замена поддерживают только материальный ресурс.",
        "actions_confirmed requires a valid applied resource action": "Подтверждение действий требует хотя бы одного корректно применённого действия.",
        "keep_all_confirmed cannot carry resource actions": "Подтверждение неизменного состава несовместимо с действиями над ресурсами.",
        "resource basis does not identify the original source or resolved evidence": "Основание не соответствует исходной строке или разрешённому источнику.",
        "reuse price source is not its original source or resolved evidence": "Источник нулевой цены не соответствует основанию повторного использования.",
    }
    return messages.get(reason, "Проверьте поля явного действия над ресурсом и его основание.")


def _key(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("\u0451", "\u0435").split())


def _number(value: Any, *, positive: bool) -> float:
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError("a finite numeric value is required")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("a finite numeric value is required") from error
    if not math.isfinite(number) or (number <= 0 if positive else number < 0):
        raise ValueError("quantity must be positive and finite" if positive else "price must be nonnegative and finite")
    return number


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(ref, str) or not ref.strip() for ref in value):
        raise ValueError("source_refs must be an array of nonempty strings")
    return tuple(value)


def _quantity_convert(quantity: float, source_unit: str, target_unit: str) -> float:
    source_factor, source = norm_measure(source_unit)
    target_factor, target = norm_measure(target_unit)
    aliases = {"m": "m", "\u043c": "m", "m2": "m2", "m\u00b2": "m2", "\u043c2": "m2", "\u043c\u00b2": "m2",
               "m3": "m3", "m\u00b3": "m3", "\u043c3": "m3", "\u043c\u00b3": "m3", "\u0448\u0442": "count", "pcs": "count",
               "\u0442": "tonne", "t": "tonne", "\u043a\u0433": "kg", "kg": "kg"}
    source = aliases.get(_key(source).rstrip("."), _key(source).rstrip("."))
    target = aliases.get(_key(target).rstrip("."), _key(target).rstrip("."))
    if not math.isfinite(source_factor) or not math.isfinite(target_factor) or source_factor <= 0 or target_factor <= 0:
        raise ValueError("resource unit scale must be positive and finite")
    if source == target and source:
        scale = 1.0
    else:
        scale = {("tonne", "kg"): 1000.0, ("kg", "tonne"): 0.001}.get((source, target))
        if scale is None:
            raise ValueError("resource quantity units are incompatible")
    return _number(quantity * source_factor * scale / target_factor, positive=True)


def _binding(item: Mapping[str, Any], work_id: str) -> ResourceBinding:
    unknown = set(item) - RESOURCE_BINDING_FIELDS
    if unknown:
        raise ValueError("unsupported resource action fields: " + ", ".join(sorted(map(str, unknown))))
    if item.get("kind", "material") != "material":
        raise ValueError("add/replace resource kind must be material")
    for name, value in item.items():
        if name not in {"quantity", "explicit_price", "source_refs"} and not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
    refs = _strings(item.get("source_refs", []))
    reason = str(item.get("reason") or "")
    basis = str(item.get("basis_ref") or "")
    if not reason.strip() or not (refs or basis.strip()):
        raise ValueError("resource action requires a reason and source_refs or basis_ref")
    quantity = _number(item["quantity"], positive=True) if "quantity" in item and item["quantity"] is not None else None
    price = _number(item["explicit_price"], positive=False) if "explicit_price" in item and item["explicit_price"] is not None else None
    if item.get("action") == "reuse" and price not in (None, 0.0):
        raise ValueError("reuse cannot carry a nonzero explicit price")
    price_source = str(item.get("price_source_ref") or "")
    if item.get("action") == "reuse" and price == 0 and not price_source:
        # Zero is the authored reuse treatment, not a quoted market price. Its
        # provenance is the actual reuse basis already supplied by the model.
        price_source = basis or (refs[0] if refs else "")
    return ResourceBinding(
        work_id=work_id, selected_by="model", action=str(item.get("action") or ""),
        resource_name=str(item.get("resource_name") or ""), resource_code=str(item.get("resource_code") or ""),
        unit=str(item.get("unit") or ""), quantity=quantity,
        quantity_basis=str(item.get("quantity_basis") or "explicit"),
        target_resource_code=str(item.get("target_resource_code") or ""),
        target_resource_name=str(item.get("target_resource_name") or ""), explicit_price=price,
        price_source_ref=price_source, reason=reason, basis_ref=basis, source_refs=refs,
    )


def _check_evidence(binding: ResourceBinding, check: Mapping[str, Any] | None) -> None:
    if check is None:
        return
    if check.get("unresolved_refs"):
        raise ValueError("resource action has unresolved evidence references")
    required = []
    if binding.target_resource_code:
        required.append("target_code_in_refs")
    if binding.target_resource_name:
        required.append("target_name_in_refs")
    if binding.action in {"add", "replace"} and binding.resource_code:
        required.append("resource_code_in_refs")
    if binding.explicit_price is not None and binding.action != "reuse":
        required.extend(("price_in_refs", "unit_in_refs", "source_in_refs"))
    if any(check.get(name) is not True for name in required):
        raise ValueError("resource action target, selection or price is not substantiated by shown evidence")


def resource_binding_position_fields(
    row: Mapping[str, Any], norm_resources: Sequence[Mapping[str, Any]], *, work_id: str,
    work_qty: float, physical_quantity: float | None, physical_unit: str,
    linked_supply_rows: Sequence[Mapping[str, Any]] = (), supply_parent_ambiguous: bool = False,
) -> dict[str, Any]:
    """Return opt-in resource projection, raw authored proposals and visible conflicts."""
    if "resource_bindings" not in row and "resource_review" not in row and not linked_supply_rows:
        return {}
    resources = copy.deepcopy([dict(resource) for resource in norm_resources])
    conflicts: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    fields: dict[str, Any] = {"resource_binding_audit": audit, "resource_binding_conflicts": conflicts}
    if "resource_bindings" in row:
        authored = row["resource_bindings"]
        fields["resource_bindings"] = copy.deepcopy(authored)
        fields["resources"] = resources
        proposals = authored if isinstance(authored, list) else [authored]
        checks = row.get("_resource_binding_evidence_checks")
        by_index = {}
        if isinstance(checks, list):
            for index, check in enumerate(checks):
                if isinstance(check, Mapping):
                    check_index = check.get("index", index)
                    if isinstance(check_index, int) and not isinstance(check_index, bool) and check_index >= 0:
                        by_index[check_index] = check
        for index, item in enumerate(proposals):
            entry = {"index": index, "proposal": copy.deepcopy(item), "status": "conflict"}
            audit.append(entry)
            try:
                if not isinstance(authored, list) or not isinstance(item, Mapping):
                    raise ValueError("resource_bindings must be an array of objects")
                check = by_index.get(index)
                effective = dict(item)
                pointer = effective.pop("target_resource_ref", None)
                pointed_target = None
                if "target_resource_ref" in item:
                    if (not isinstance(pointer, str) or check is None
                            or check.get("target_resource_reference_resolved") is not True
                            or not isinstance(check.get("target_resource"), Mapping)):
                        raise ValueError("resource address is unresolved or disagrees with its target")
                    pointed_target = check["target_resource"]
                    for field, key in (("target_resource_code", "code"), ("target_resource_name", "name")):
                        if effective.get(field) and _key(effective[field]) != _key(pointed_target.get(key)):
                            raise ValueError("resource address is unresolved or disagrees with its target")
                        effective[field] = str(pointed_target.get(key) or "")
                binding = _binding(effective, work_id)
                _check_evidence(binding, check)
                known_refs = {str(ref).casefold() for ref in (check.get("evidence_bindings", {}) if check else {})}
                row_bindings = row.get("evidence_bindings")
                if isinstance(row_bindings, Mapping):
                    known_refs.update(str(ref).casefold() for ref, identity in row_bindings.items() if identity)
                if binding.basis_ref:
                    linked_basis = any(binding.basis_ref == str(supply.get("source_row") or "") for supply in linked_supply_rows)
                    if (_key(binding.basis_ref) != _key(row.get("source_row"))
                            and binding.basis_ref.casefold() not in known_refs and not linked_basis):
                        raise ValueError("resource basis does not identify the original source or resolved evidence")
                if binding.action == "reuse" and binding.price_source_ref and check is not None:
                    if (binding.price_source_ref not in {binding.basis_ref, str(row.get("source_row") or "")}
                            and binding.price_source_ref.casefold() not in known_refs
                            and check.get("source_in_refs") is not True):
                        raise ValueError("reuse price source is not its original source or resolved evidence")
                matches = [i for i, target in enumerate(resources)
                           if (not binding.target_resource_code or _key(target.get("code")) == _key(binding.target_resource_code))
                           and (not binding.target_resource_name or _key(target.get("name")) == _key(binding.target_resource_name))
                           and (pointed_target is None or all(target.get(key) == pointed_target.get(key)
                                for key in ("kind", "code", "name", "unit", "per_unit")))]
                target = None
                if binding.action in {"replace", "exclude", "reuse"}:
                    if len(matches) != 1:
                        raise ValueError("resource target is missing or ambiguous")
                    target = resources[matches[0]]
                    entry["target"] = copy.deepcopy(target)
                provenance = {"action": binding.action, "selected_by": "model", "work_id": work_id,
                              "reason": binding.reason, "basis_ref": binding.basis_ref,
                              "source_refs": list(binding.source_refs), "price_source_ref": binding.price_source_ref,
                              "quantity_basis": binding.quantity_basis,
                              "target_resource_code": binding.target_resource_code,
                              "target_resource_name": binding.target_resource_name}
                if pointer is not None:
                    provenance["target_resource_ref"] = pointer
                if check is not None:
                    provenance["evidence_bindings"] = copy.deepcopy(check.get("evidence_bindings", {}))
                replacement = None
                if binding.action in {"add", "replace"}:
                    if target is not None and target.get("kind") != "material":
                        raise ValueError("a material replacement cannot reinterpret another resource kind")
                    if binding.quantity_basis == "target_norm":
                        total = _quantity_convert(_number(target.get("per_unit"), positive=True) * _number(work_qty, positive=True),
                                                  str(target.get("unit") or ""), binding.unit)
                    elif binding.quantity_basis == "source_work":
                        total = _quantity_convert(_number(physical_quantity, positive=True), physical_unit, binding.unit)
                    else:
                        total = _number(binding.quantity, positive=True)
                    per_unit = _number(total / _number(work_qty, positive=True), positive=True)
                    provenance.update({"physical_quantity": total, "physical_unit": binding.unit,
                                       "norm_quantity": work_qty, "per_unit": per_unit})
                    replacement = {"kind": "material", "name": binding.resource_name, "code": binding.resource_code,
                                   "unit": binding.unit, "per_unit": per_unit, "resource_binding": provenance}
                    if binding.explicit_price is not None:
                        replacement.update({"price": binding.explicit_price, "price_source_ref": binding.price_source_ref,
                                            "price_origin": "model_result"})
                elif binding.action == "reuse":
                    replacement = copy.deepcopy(target)
                    replacement.update({"price": 0.0, "price_source_ref": binding.price_source_ref or binding.basis_ref or binding.source_refs[0],
                                        "price_origin": "model_result", "resource_binding": provenance})
                # All checks precede mutation: a rejected replacement retains its target.
                if target is not None:
                    resources.pop(matches[0])
                if replacement is not None:
                    resources.append(replacement)
                entry.update({"status": "applied", "action": binding.action, "provenance": provenance})
                entry["evidence_status"] = "checked" if check is not None else "unverified"
                if check is None:
                    conflicts.append({"code": "resource_binding_evidence_unverified", "index": index, "work_id": work_id,
                                      "reason": "resource action sources were not checked against shown evidence",
                                      "proposal": copy.deepcopy(item)})
                if replacement is not None:
                    entry["result"] = copy.deepcopy(replacement)
            except (TypeError, ValueError) as error:
                conflict = {"code": "resource_binding_conflict", "index": index, "work_id": work_id, "reason": str(error),
                            "proposal": copy.deepcopy(item)}
                conflicts.append(conflict)
                entry["reason"] = str(error)
    if "resource_review" in row:
        authored_review = row["resource_review"]
        fields["resource_review"] = copy.deepcopy(authored_review)
        try:
            if not isinstance(authored_review, Mapping) or set(authored_review) - RESOURCE_REVIEW_FIELDS:
                raise ValueError("resource_review must be a typed review object without owner or identity fields")
            if any(not isinstance(value, str) for value in authored_review.values()):
                raise ValueError("resource review fields must be strings")
            review = ResourceReview(work_id=work_id, selected_by="model", **dict(authored_review))
            if review.status == "actions_confirmed" and not any(entry["status"] == "applied" for entry in audit):
                raise ValueError("actions_confirmed requires a valid applied resource action")
            if review.status == "keep_all_confirmed" and row.get("resource_bindings"):
                raise ValueError("keep_all_confirmed cannot carry resource actions")
            fields["resource_review_status"] = review.status
            fields["resource_review_reason"] = review.reason
            for component in ("labor", "machine", "material", "dominant"):
                if f"{component}_status" in authored_review or f"{component}_reason" in authored_review:
                    fields[f"{component}_review_status"] = getattr(review, f"{component}_status")
                    fields[f"{component}_review_reason"] = getattr(review, f"{component}_reason")
        except (TypeError, ValueError) as error:
            conflicts.append({"code": "resource_review_conflict", "work_id": work_id, "reason": str(error),
                              "proposal": copy.deepcopy(authored_review)})
    materials = [copy.deepcopy(dict(resource)) for resource in norm_resources if resource.get("kind") == "material"]
    if linked_supply_rows and materials:
        unresolved = []
        for supply in linked_supply_rows:
            locator = str(supply.get("source_row") or "")
            code = str(supply.get("resource_code") or "")
            target_still_present = any(resource.get("kind") == "material" and resource.get("code") == code
                                       for resource in resources)
            resolved = bool(locator and code and not supply_parent_ambiguous and not target_still_present) and any(
                entry.get("status") == "applied"
                and entry.get("action") == "exclude"
                and (entry.get("target") or {}).get("kind") == "material"
                and (entry.get("target") or {}).get("code") == code
                and (entry.get("provenance") or {}).get("target_resource_code") == code
                and (entry.get("provenance") or {}).get("basis_ref") == locator
                for entry in audit
            )
            if not resolved:
                unresolved.append({"source_row": locator, "resource_code": code})
        if unresolved:
            conflicts.append({"code": "separate_supply_possible_overlap", "work_id": work_id,
                              "reason": "linked supply and norm materials have no unambiguous authored target relationship",
                              "linked_supply_rows": unresolved, "parent_ambiguous": bool(supply_parent_ambiguous),
                              "norm_material_resources": materials})
    return fields
