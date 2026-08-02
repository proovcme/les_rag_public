"""Document/PDF object routing skeleton.

Heavy parsers (Docling, OCR) run only when page classification says they are
needed. Digital text stays on the cheap PyMuPDF path.
"""

from __future__ import annotations

from typing import Any

DOCUMENT_OBJECT_SCHEMA = "les.document_object.v1"

# Align with list.pdf_page_passport.v1 page types.
PAGE_TYPES = (
    "digital_text",
    "table",
    "drawing",
    "scan",
    "mixed",
    "damaged_text_layer",
)

_PARSER_CHAIN: dict[str, list[str]] = {
    "digital_text": ["pymupdf_page_text"],
    "table": ["pymupdf_page_text", "docling_optional", "ocr_fallback"],
    "drawing": ["pymupdf_geometry", "vision_optional"],
    "scan": ["ocr_required"],
    "mixed": ["pymupdf_page_text", "ocr_fallback"],
    "damaged_text_layer": ["ocr_required"],
}


def classify_parser_route(page_type: str, *, ocr_needed: bool | None = None) -> dict[str, Any]:
    """Map a passport page type to an ordered parser chain (no parsing yet)."""
    normalized = str(page_type or "").strip().casefold()
    if normalized not in _PARSER_CHAIN:
        normalized = "mixed"
    chain = list(_PARSER_CHAIN[normalized])
    if ocr_needed is True and "ocr_required" not in chain and "ocr_fallback" not in chain:
        chain.append("ocr_fallback")
    if ocr_needed is False:
        chain = [step for step in chain if not step.startswith("ocr")]
        if not chain:
            chain = ["pymupdf_page_text"]
    return {
        "schema": DOCUMENT_OBJECT_SCHEMA,
        "kind": "page_parser_route",
        "page_type": normalized,
        "ocr_needed": ocr_needed,
        "parser_chain": chain,
        "heavy_allowed": any(
            step.startswith("docling") or step.startswith("ocr") or step.startswith("vision")
            for step in chain
        ),
    }


def page_fact(
    *,
    file_name: str,
    page: int,
    page_type: str,
    text: str = "",
    bbox: list[float] | None = None,
    parser: str = "pymupdf_page_text",
) -> dict[str, Any]:
    """Typed page-level fact with provenance — skeleton for tool harness."""
    return {
        "schema": DOCUMENT_OBJECT_SCHEMA,
        "kind": "page_fact",
        "text": text,
        "bbox": list(bbox or []),
        "provenance": {
            "file": file_name,
            "page": int(page),
            "page_type": str(page_type or ""),
            "parser": parser,
        },
    }
