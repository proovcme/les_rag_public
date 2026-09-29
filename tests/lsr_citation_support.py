"""Build the citation record the application itself writes for a model row.

Production: ``bind_row_evidence_ids`` attaches ``_evidence_check`` to every durable
row that authors a ``norm_code`` — the structural record of which cards the model
cited and which cipher those cards name.  Task 2026-09-29 § 3 forbids reading an
``EXACT`` token as its own confirmation, so readiness and the XLSX trace now ground
that token on this record.

A test fixture that means «the model chose this norm from this card» therefore has
to carry the same record.  This module builds it with the *production* constructor
instead of hand-writing a payload, so a fixture can never drift from what the
application actually stores.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from proxy.services.chat_evidence_application_service import row_evidence_provenance_check


def cited(row: Mapping[str, Any], *, card: str = "", ref: str = "Q1.H1") -> dict[str, Any]:
    """Return a copy of ``row`` carrying the citation record of one chosen card.

    ``card`` is what the cited card body names as its cipher; it defaults to the
    row's own ``norm_code``, which is the positive case.  Pass a different cipher to
    reproduce the contradiction the code must see («неправильная ссылка»).

    A row that authors no cipher has nothing to cite — an open gap, a heading, a
    supply line — and is returned untouched, so a builder can be applied to a whole
    fixture table.
    """

    payload = dict(row)
    if isinstance(payload.get("_evidence_check"), Mapping):
        # The fixture already states its own citation — including the deliberate
        # contradiction cases — and this helper must not launder it away.
        return payload
    code = str(card or payload.get("norm_code") or payload.get("code") or "").strip()
    if not code:
        return payload
    bindings = {ref: f"global-evidence-{ref}"}
    payload["evidence_refs"] = [ref]
    payload["evidence_bindings"] = dict(bindings)
    check = row_evidence_provenance_check(
        payload, bindings, {ref: code}, {ref: "запрос карточки"}
    )
    if check is None:  # pragma: no cover - guarded by the cipher check above
        raise ValueError("the production citation constructor returned no record")
    payload["_evidence_check"] = check
    return payload


def cited_all(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Cite every cipher-bearing row of a fixture table, leaving the rest alone."""

    return [cited(row) for row in rows]
