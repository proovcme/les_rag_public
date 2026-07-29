"""Phase-scoped model context for the conversational RIM workflow.

The catalog is navigation and source routing. It never supplies a coefficient,
price or professional mapping decision to the deterministic calculator.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "domain"
    / "smeta_normative_catalog.json"
)


@lru_cache(maxsize=1)
def rim_knowledge_catalog() -> dict[str, Any]:
    try:
        payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def model_reference_for_session(session: dict[str, Any]) -> dict[str, Any]:
    """Return only knowledge relevant to the model's current session phase."""
    catalog = rim_knowledge_catalog()
    phase = str(session.get("phase") or "new")
    mapping_status = str(session.get("mapping_status") or "not_started")
    pricing_status = str(session.get("pricing_status") or "unpriced")

    if pricing_status in {"priced_partial", "priced_draft"}:
        active_phases = {"pricing", "finalization"}
    elif mapping_status == "mapping_locked":
        active_phases = {"pricing"}
    elif phase == "vor" or mapping_status != "not_started":
        active_phases = {"mapping"}
    else:
        active_phases = set()

    sources = [
        {
            key: entry.get(key)
            for key in (
                "id",
                "kind",
                "title",
                "source_refs",
                "approval_basis",
                "required_dimensions",
                "calculation_use",
                "model_role",
                "typed_owner",
            )
            if entry.get(key) not in (None, "", [])
        }
        for entry in (catalog.get("rim_sources") or [])
        if isinstance(entry, dict)
        and active_phases.intersection(
            str(value) for value in (entry.get("phases") or [])
        )
    ]
    return {
        "schema": "rim_model_reference_v1",
        "role": "navigation_and_source_routing_only",
        "active_phases": sorted(active_phases),
        "sources": sources[:12],
        "boundary": (
            "Use this register to choose what evidence or user confirmation is needed. "
            "Never invent or calculate a norm, price, coefficient, machine operator, NR or SP "
            "from this summary; exact values must come from the named typed owner."
        ),
    }
