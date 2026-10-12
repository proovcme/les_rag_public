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

import hashlib
import json
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


def issued_norm_metadata(norm: Mapping[str, Any], *, synthetic: bool = False) -> dict[str, str]:
    """Metadata for an actual base card or an explicitly local synthetic fixture.

    Synthetic identities hash the complete fixture card. They must be used with
    the corresponding local lookup stub, never to label a canonical base card.
    """
    from proxy.services.lsr_norm_quality_gate_service import qualified_norm_key

    code = str(norm.get("code") or "")
    key = qualified_norm_key(code)
    assert key, "the issued fixture must name a full family and norm item"
    sha = str(norm.get("_source_sha256") or "")
    if not sha and synthetic:
        sha = hashlib.sha256(json.dumps(dict(norm), ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    assert len(sha) == 64, "a real card requires its actual normative source SHA-256"
    return {"norm_code": code, "norm_key": key, "normative_base_sha256": sha}


def cited_snapshot(row: Mapping[str, Any], *, norm: Mapping[str, Any] | None = None,
                   synthetic: bool = False) -> dict[str, Any]:
    """Opt in to the application's issued-snapshot binding for calculation tests."""
    from proxy.services import gesn_service
    from proxy.services.model_norm_snapshot_binding_service import cited_norm_snapshot_stamp

    payload = cited(row)
    if norm is None:
        norm = gesn_service.get_norm(str(payload.get("norm_code") or ""))
    assert norm is not None, "the calculation fixture must have an issued card"
    metadata = issued_norm_metadata(norm, synthetic=synthetic)
    bindings = payload["evidence_bindings"]
    stamp = cited_norm_snapshot_stamp(payload, bindings,
                                    {identity: [metadata] for identity in bindings.values()})
    assert stamp == {key: metadata[key] for key in ("norm_key", "normative_base_sha256")}
    payload["_evidence_check"] = {**payload["_evidence_check"], **stamp}
    return payload
