"""Pin source generation, never select or replace a model's normative choice."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping


def resolve_calculation_norm(row: Mapping[str, Any], code: str) -> tuple[dict | None, str]:
    """Read the exact shown generation once; legacy unpinned inputs stay explicit.

    The private pin is created by first-bind from delivered evidence, not from
    model text. A changed or unavailable generation cannot fall back to get_norm.
    The returned dictionary is the snapshot passed to the resource calculator.
    """
    pin = row.get("_normative_source_pin")
    if pin is None:
        from proxy.services import gesn_service

        return gesn_service.get_norm(code), ""
    if (not isinstance(pin, Mapping) or pin.get("status") != "pinned"
            or not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("normative_base_sha256") or ""))):
        return None, "поколение исходной нормативной базы не закреплено однозначно"
    from proxy.smeta_core import norm_browser

    path = norm_browser._base_path()
    result = norm_browser.read_norm_card_exact(
        norm_code=code, norm_key=str(pin.get("norm_key") or ""),
        base_path=path,
        expected_base_sha256=str(pin.get("normative_base_sha256") or ""),
    )
    card = result.get("card")
    if result.get("status") != "ok" or not isinstance(card, Mapping):
        return None, "; ".join(result.get("missing") or ["исходная нормативная карточка недоступна"])
    norm = deepcopy(dict(card))
    norm.update(code=card["norm_code"], key=card["norm_key"], name=card["title"],
                unit=card["measure_unit"], _source_kind="structured_sqlite",
                _source_path=str(path))
    norm["resources"] = [{**dict(resource), "resource_slot": slot}
                         for slot, resource in enumerate(card.get("resources") or [], 1)]
    return norm, ""
