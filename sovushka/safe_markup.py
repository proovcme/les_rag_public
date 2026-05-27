"""Small sanitizers for model-produced markup shown in the UI."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET


_SAFE_SVG_TAGS = {
    "svg",
    "g",
    "defs",
    "title",
    "desc",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
    "tspan",
    "marker",
    "linearGradient",
    "radialGradient",
    "stop",
    "clipPath",
    "mask",
}

_SAFE_SVG_ATTRS = {
    "aria-label",
    "class",
    "clip-path",
    "cx",
    "cy",
    "d",
    "dominant-baseline",
    "fill",
    "fill-opacity",
    "font-family",
    "font-size",
    "font-weight",
    "gradientTransform",
    "gradientUnits",
    "height",
    "id",
    "marker-end",
    "marker-mid",
    "marker-start",
    "offset",
    "opacity",
    "points",
    "preserveAspectRatio",
    "r",
    "role",
    "rx",
    "ry",
    "stop-color",
    "stop-opacity",
    "stroke",
    "stroke-dasharray",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-opacity",
    "stroke-width",
    "style",
    "text-anchor",
    "transform",
    "version",
    "viewBox",
    "width",
    "x",
    "x1",
    "x2",
    "y",
    "y1",
    "y2",
    "xmlns",
}


def sanitize_svg(svg_code: str) -> str | None:
    """Return a safe inline SVG string, or None if the SVG cannot be trusted."""
    try:
        root = ET.fromstring(svg_code.strip())
    except ET.ParseError:
        return None

    if _local_name(root.tag) != "svg":
        return None

    _sanitize_svg_element(root)
    return ET.tostring(root, encoding="unicode", method="xml")


def _sanitize_svg_element(element: ET.Element) -> None:
    element.tag = _local_name(element.tag)
    for child in list(element):
        if _local_name(child.tag) not in _SAFE_SVG_TAGS:
            element.remove(child)
            continue
        _sanitize_svg_element(child)

    clean_attrs = {}
    for raw_name, raw_value in element.attrib.items():
        name = _local_name(raw_name)
        if name.startswith("on") or name not in _SAFE_SVG_ATTRS:
            continue
        if not _safe_svg_attr_value(str(raw_value)):
            continue
        clean_attrs[name] = raw_value
    element.attrib.clear()
    element.attrib.update(clean_attrs)


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1] if "}" in name else name


def _safe_svg_attr_value(value: str) -> bool:
    lowered = value.strip().lower()
    if "javascript:" in lowered or "data:" in lowered or "<script" in lowered:
        return False
    url_refs = re.findall(r"url\((.*?)\)", value, flags=re.IGNORECASE)
    return all(ref.strip().strip("\"'").startswith("#") for ref in url_refs)
