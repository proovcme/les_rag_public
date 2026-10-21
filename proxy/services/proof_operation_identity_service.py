"""Application-owned addresses for uncommitted rows inside a bounded proof.

These addresses are not durable decisions or accepted revisions. They let the
same model revise its candidate through card/resource reads without the reader
guessing identity from a title, norm, quantity or changing evidence references.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


def _address(row: Mapping[str, Any]) -> str:
    return str(row.get("source_row") or "").strip()


def _issued_at(row: Mapping[str, Any], issued: Mapping[str, Any]) -> Mapping[str, Any] | None:
    entry = issued.get(str(row.get("operation_id") or "").strip())
    if isinstance(entry, Mapping) and entry.get("source_row") == _address(row):
        return entry
    return None


def stage_proof_operations(
    rows: Sequence[Mapping[str, Any]], issued: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Issue one opaque address per unaddressed row, never content-deduplicate."""
    from proxy.services.workbook_research_job_service import _new_operation_id

    staged = [deepcopy(dict(row)) for row in rows]
    owned = deepcopy(dict(issued or {}))
    occupied = {str(row.get("operation_id") or "").strip() for row in staged} | set(owned)
    for row in staged:
        present = "operation_id" in row
        # Invalid non-string IDs stay invalid. No bookkeeping repair grants
        # admission to a model row that the ordinary contract would reject.
        if present and (not isinstance(row["operation_id"], str) or row["operation_id"].strip()):
            continue
        identifier = "proof_" + _new_operation_id()
        while identifier in occupied:
            identifier = "proof_" + _new_operation_id()
        occupied.add(identifier)
        owned[identifier] = {"source_row": _address(row), "operation_id_present": present,
                             "original_operation_id": row.get("operation_id")}
        row["operation_id"] = identifier
    return staged, owned


def restore_proof_operations(
    rows: Sequence[Mapping[str, Any]], issued: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Remove only addresses actually issued here for the same literal source.

    Unknown IDs, moved sources, authored revisions and all professional fields
    remain untouched for normal admission/CAS. An ID-shaped string proves no
    application ownership by itself.
    """
    restored = [deepcopy(dict(row)) for row in rows]
    for row in restored:
        entry = _issued_at(row, issued)
        if entry is None:
            continue
        if entry["operation_id_present"]:
            row["operation_id"] = entry["original_operation_id"]
        else:
            row.pop("operation_id", None)
    return restored


def proof_operation_context(
    rows: Sequence[Mapping[str, Any]], issued: Mapping[str, Any],
    existing_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Expose exact issued addresses and immutable *durable* revision targets."""
    durable = {str(row.get("operation_id") or "").strip(): row for row in existing_rows
               if str(row.get("operation_id") or "").strip()}
    operations: list[dict[str, Any]] = []
    for row in rows:
        identifier = str(row.get("operation_id") or "").strip()
        previous = durable.get(identifier)
        known = previous is not None and _address(previous) == _address(row)
        staged = _issued_at(row, issued) is not None
        item = {key: deepcopy(row[key]) for key in (
            "source_row", "row_role", "title", "norm_code", "resource_code") if key in row}
        item.update(operation_id=identifier, committed=known,
                    identity_status="committed" if known else "uncommitted" if staged else "unknown")
        if known:
            revision = previous.get("revision")
            if type(revision) is int and revision > 0:
                item["expected_revision"] = revision
        operations.append(item)
    return {
        "schema": "les.proof-operation-identities.v1",
        "instruction": (
            "Это адреса операций только для текущей проверки. Верни указанный operation_id "
            "при исправлении этой же операции, включая непринятую новую; не объявляй её "
            "повторно новой с пустым ID. Для committed=true expected_revision остаётся "
            "показанной сохранённой ревизией до окончательного принятия всего результата. "
            "Повтор чтения карточки или цены не повышает ревизию. Для uncommitted "
            "не назначай revision/expected_revision. Новую дополнительную операцию, "
            "которой ещё нет в этом списке, объявляй обычным пустым operation_id. "
            "Временный uncommitted ID адресует только исправление этой строки: не "
            "используй его как work_row/covered_by_work_id другой операции. Сохрани "
            "прежнюю однозначную связь; если для новой связи нужен постоянный ID, "
            "оставь конкретный open_gap до принятия родительской операции. "
            "Unknown не является разрешённым адресом; исправь его по ранее показанным данным."
        ),
        "operations": operations,
    }


def proof_operation_snapshot_valid(pending: Mapping[str, Any]) -> bool:
    """Validate the optional address snapshot; old checkpoints remain readable."""
    names = {"proof_rows", "proof_operation_identities", "proof_operation_identity"}
    present = names & set(pending)
    if not present:
        return True
    if present != names:
        return False
    rows, issued, context = (pending[name] for name in (
        "proof_rows", "proof_operation_identities", "proof_operation_identity"))
    if (not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows)
            or not isinstance(issued, Mapping) or not isinstance(context, Mapping)
            or set(context) != {"schema", "instruction", "operations"}
            or context.get("schema") != "les.proof-operation-identities.v1"
            or not isinstance(context.get("instruction"), str)
            or not isinstance(context.get("operations"), list)
            or len(context["operations"]) != len(rows)):
        return False
    for identifier, entry in issued.items():
        if (not isinstance(identifier, str) or not identifier.strip() or not isinstance(entry, Mapping)
                or set(entry) != {"source_row", "operation_id_present", "original_operation_id"}
                or not isinstance(entry["source_row"], str)
                or type(entry["operation_id_present"]) is not bool):
            return False
        original = entry["original_operation_id"]
        if ((entry["operation_id_present"] and (not isinstance(original, str) or original.strip()))
                or (not entry["operation_id_present"] and original is not None)):
            return False
        if sum(str(row.get("operation_id") or "").strip() == identifier
               and _address(row) == entry["source_row"] for row in rows) != 1:
            return False
    allowed = {"source_row", "row_role", "title", "norm_code", "resource_code", "operation_id",
               "committed", "identity_status", "expected_revision"}
    for row, item in zip(rows, context["operations"]):
        if (not isinstance(item, Mapping) or set(item) - allowed
                or type(item.get("committed")) is not bool
                or str(item.get("operation_id") or "").strip() != str(row.get("operation_id") or "").strip()
                or _address(item) != _address(row)):
            return False
        status = item.get("identity_status")
        if status not in {"committed", "uncommitted", "unknown"}:
            return False
        if item["committed"] != (status == "committed"):
            return False
        if status == "uncommitted" and _issued_at(row, issued) is None:
            return False
        if status != "committed" and "expected_revision" in item:
            return False
    return True
