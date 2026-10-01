"""Verify literal model-authored prices against the evidence actually shown.

This is a provenance boundary, not a price chooser. It never derives a price,
unit, source, currency, VAT treatment or period from professional meaning.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence
import unicodedata


_NUMBER = re.compile(r"(?<![\w.,])[-+]?\d(?:[\d., '\u00a0\u202f]*\d)?(?!\w|[.,]\d)")
_OPTIONAL_FIELDS = {
    "currency": ("price_currency", "currency"),
    "vat": ("price_vat", "vat", "vat_rate"),
    "period": ("price_period", "period"),
    "year": ("price_year",),
    "quarter": ("price_quarter",),
}


def _text(value: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split()).casefold()


def _first(data: Mapping[str, Any], names: Sequence[str]) -> Any:
    return next((data[name] for name in names if data.get(name) not in (None, "")), None)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    raw = str(value).strip().replace("\u2212", "-")
    if re.search(r"[ '\u00a0\u202f]", raw) and not re.fullmatch(
        r"[-+]?\d{1,3}(?:[ '\u00a0\u202f]\d{3})+(?:[.,]\d+)?", raw,
    ):
        return None
    raw = re.sub(r"[ '\u00a0\u202f]", "", raw)
    if not re.fullmatch(r"[-+]?\d+(?:[.,]\d+)*", raw):
        return None
    if "," in raw and "." in raw:
        decimal_separator = "," if raw.rfind(",") > raw.rfind(".") else "."
        grouping_separator = "." if decimal_separator == "," else ","
        integer, fraction = raw.rsplit(decimal_separator, 1)
        groups = integer.lstrip("-+").split(grouping_separator)
        if len(groups) > 1 and (not 1 <= len(groups[0]) <= 3 or any(len(group) != 3 for group in groups[1:])):
            return None
        raw = integer.replace(grouping_separator, "") + "." + fraction
    elif raw.count(",") > 1 or raw.count(".") > 1:
        separator = "," if "," in raw else "."
        groups = raw.lstrip("-+").split(separator)
        if not 1 <= len(groups[0]) <= 3 or any(len(group) != 3 for group in groups[1:]):
            return None
        raw = raw.replace(separator, "")
    else:
        raw = raw.replace(",", ".")
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _amount_in_body(amount: Decimal, body: str, *, typed_amount: Decimal | None = None) -> bool:
    for match in _NUMBER.finditer(body):
        literal = match.group()
        ambiguous_grouping = re.fullmatch(r"[-+]?\d{1,3}[.,]\d{3}", literal) is not None
        if ambiguous_grouping and typed_amount != amount:
            continue
        if _decimal(literal) == amount:
            return True
        # A single separator plus three digits is locale-ambiguous. An explicit
        # typed quote can substantiate the grouping interpretation; prose alone
        # cannot silently select it instead of the fractional interpretation.
        if typed_amount == amount and ambiguous_grouping:
            if _decimal(literal.replace(",", "").replace(".", "")) == amount:
                return True
    return False


def _literal_in_body(value: Any, body: str) -> bool:
    literal = _text(value)
    if not literal:
        return False
    # A unit's substring is not its literal unit: m must not prove m2 or m/s.
    return re.search(r"(?<![\w./^])" + re.escape(literal) + r"(?!\w|[./^]\w)", _text(body)) is not None


def _field_equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(
            name in actual and _field_equal(value, actual[name]) for name, value in expected.items()
        )
    expected_number = _decimal(expected)
    actual_number = _decimal(actual)
    if expected_number is not None and actual_number is not None:
        return expected_number == actual_number
    return _text(expected) == _text(actual) and bool(_text(expected))


def _optional_in_body(value: Any, body: str) -> bool:
    if isinstance(value, Mapping):
        return bool(value) and all(_optional_in_body(item, body) for item in value.values())
    number = _decimal(value)
    return _amount_in_body(number, body) if number is not None else _literal_in_body(value, body)


def _chunk_value(chunk: Any, name: str, default: Any = None) -> Any:
    return chunk.get(name, default) if isinstance(chunk, Mapping) else getattr(chunk, name, default)


def _is_norm_chunk(chunk: Any, meta: Mapping[str, Any]) -> bool:
    return bool(meta.get("norm_code") or meta.get("norm_key")) or _text(_chunk_value(chunk, "doc_name")) == "smeta_norm_cards.v1"


def price_evidence_check(
    row: Mapping[str, Any],
    evidence_chunks: Sequence[Any],
    checkable_bindings: Mapping[str, str],
) -> dict[str, Any] | None:
    """Check one quoted amount, unit and source together in a cited real chunk.

    ``checkable_bindings`` must be the caller's immutable bindings resolved
    against the supplied evidence, not model-authored identities. Optional
    ``meta.price_evidence`` is an explicit typed quote row; its declared fields
    must also agree with the model result. Missing facts stay false and never
    supply replacement values. Diagnostic booleans come from one chunk, so
    different documents cannot jointly manufacture a confirmed quote.
    """
    if row.get("confirmed_price") in (None, ""):
        return None
    amount = _decimal(row.get("confirmed_price"))
    unit = _first(row, ("price_unit", "unit"))
    source = _text(row.get("price_source"))
    refs = row.get("evidence_refs") or row.get("source_refs") or ()
    if isinstance(refs, str):
        refs = re.split(r"[;,|]", refs)
    bindings = {str(alias).strip().upper(): str(identity).strip() for alias, identity in checkable_bindings.items()}
    cited = {bindings.get(str(ref).strip().upper(), "") for ref in refs}
    cited.discard("")
    optional = {name: _first(row, aliases) for name, aliases in _OPTIONAL_FIELDS.items()}
    optional = {name: value for name, value in optional.items() if value is not None}
    observations: list[dict[str, Any]] = []
    for chunk in evidence_chunks:
        meta = _chunk_value(chunk, "meta", {}) or {}
        if not isinstance(meta, Mapping):
            continue
        identity = str(meta.get("global_evidence_id") or "").strip()
        if not identity or identity not in cited or _is_norm_chunk(chunk, meta):
            continue
        body = str(_chunk_value(chunk, "content", "") or "")
        source_candidates = {_text(_chunk_value(chunk, "doc_name")), _text(meta.get("source_ref"))}
        source_candidates.discard("")
        payload = meta.get("price_evidence")
        typed = payload if isinstance(payload, Mapping) else None
        typed_amount = _decimal(_first(typed, ("confirmed_price", "price", "price_current", "unit_price"))) if typed is not None else None
        price_ok = amount is not None and _amount_in_body(amount, body, typed_amount=typed_amount)
        unit_ok = _literal_in_body(unit, body)
        source_ok = bool(source and source in source_candidates)
        optional_ok = all(_optional_in_body(value, body) for value in optional.values())
        if typed is not None:
            price_ok = price_ok and amount is not None and typed_amount == amount
            unit_ok = unit_ok and _field_equal(unit, _first(typed, ("price_unit", "unit")))
            typed_source = _first(typed, ("price_source", "source_ref", "doc_name"))
            if typed_source is not None:
                source_ok = source_ok and _text(typed_source) == source
            if typed.get("price_kind") is not None:
                optional_ok = optional_ok and _field_equal(row.get("price_kind"), typed["price_kind"])
            optional_ok = optional_ok and all(
                _field_equal(value, _first(typed, (name, *_OPTIONAL_FIELDS[name]))) for name, value in optional.items()
            )
        elif "price_evidence" in meta:
            # An invalid explicit quote payload is not permission to fall back
            # to unrelated numbers that happen to exist in the same prose.
            price_ok = unit_ok = optional_ok = False
        observations.append({
            "evidence_id": identity, "price_in_refs": price_ok, "unit_in_refs": unit_ok,
            "source_in_refs": source_ok, "optional_context_in_refs": optional_ok,
        })
    # This chooses a diagnostic record only, never a price or professional
    # decision. A full proof must exist within that same actual quoted chunk.
    observed = max(observations, key=lambda item: sum(bool(item[key]) for key in (
        "price_in_refs", "unit_in_refs", "source_in_refs", "optional_context_in_refs",
    )), default={"price_in_refs": False, "unit_in_refs": False, "source_in_refs": False,
                "optional_context_in_refs": not optional})
    return {"confirmed_price": row.get("confirmed_price"), "price_unit": unit, "price_source": row.get("price_source"),
            **observed, "checked_evidence_ids": [item["evidence_id"] for item in observations],
            "authored_optional_context": optional}
