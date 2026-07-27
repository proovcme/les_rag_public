"""Read-only per-page PDF passport for the LIST document browser.

The service is a routing/evidence layer, not a document interpretation model.  It
describes what is physically present on every inspected page, keeps coordinates
for representative text fragments and renders a bounded PNG preview on demand.
Source PDFs are opened read-only and are never rewritten.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Iterable

from proxy.services.title_block_extract_service import detect_in_text

PDF_CONTOUR_SCHEMA = "list.pdf_contour.v1"
PDF_PAGE_SCHEMA = "list.pdf_page_passport.v1"
MAX_AUDIT_PAGES = 200
MAX_TABLE_DETECTION_DRAWINGS = 3000
_TITLE_ZONE = (0.45, 0.58, 1.0, 1.0)
_SHEET_NUMBER_RE = re.compile(
    r"(?:лист|sheet)\s*(?:№|no\.?|n)?\s*[:.\-]?\s*(\d{1,4})(?!\d)",
    re.IGNORECASE,
)

PAGE_TYPE_LABELS = {
    "digital_text": "Цифровой текст",
    "table": "Таблица",
    "drawing": "Чертёж",
    "scan": "Скан",
    "mixed": "Смешанная",
    "damaged_text_layer": "Повреждённый текстовый слой",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_path(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != ".pdf":
        raise ValueError("PDF-контур доступен только для файлов .pdf")
    if not path.is_file():
        raise FileNotFoundError("Исходный PDF не найден")
    if path.stat().st_size <= 0:
        raise ValueError("Исходный PDF пуст")
    return path


def _rect_area(rect: Iterable[float]) -> float:
    x0, y0, x1, y1 = (float(value) for value in rect)
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _clean_text(value: str, *, limit: int = 320) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].rstrip()


def _block_text(block: dict[str, Any]) -> str:
    rows: list[str] = []
    for line in block.get("lines") or []:
        value = "".join(str(span.get("text") or "") for span in line.get("spans") or [])
        if value.strip():
            rows.append(value)
    return "\n".join(rows)


def _text_quality(text: str) -> dict[str, Any]:
    nonspace = [char for char in text if not char.isspace()]
    if not nonspace:
        return {
            "score": 0.0,
            "letter_digit_ratio": 0.0,
            "bad_glyph_ratio": 0.0,
            "status": "no_text_layer",
        }
    letter_digit = sum(char.isalnum() for char in nonspace)
    bad = sum(
        char == "\ufffd" or ord(char) < 32 or 0xE000 <= ord(char) <= 0xF8FF
        for char in nonspace
    )
    letter_digit_ratio = letter_digit / len(nonspace)
    bad_ratio = bad / len(nonspace)
    length_factor = min(1.0, math.log10(len(nonspace) + 1) / 2.5)
    score = max(0.0, min(1.0, 0.55 * letter_digit_ratio + 0.45 * length_factor - 2.5 * bad_ratio))
    damaged = len(nonspace) >= 24 and (bad_ratio >= 0.08 or letter_digit_ratio < 0.28)
    return {
        "score": round(score, 3),
        "letter_digit_ratio": round(letter_digit_ratio, 3),
        "bad_glyph_ratio": round(bad_ratio, 3),
        "status": "damaged" if damaged else "readable",
    }


def _classify_page(
    *,
    text_chars: int,
    image_coverage: float,
    drawing_count: int,
    table_count: int,
    text_quality: dict[str, Any],
) -> tuple[str, float, list[str]]:
    warnings: list[str] = []
    damaged = text_quality.get("status") == "damaged"
    if damaged:
        warnings.append("Текстовый слой содержит повреждённые или нечитаемые символы")
        return "damaged_text_layer", 0.92, warnings
    if text_chars < 24 and image_coverage >= 0.45:
        warnings.append("Нет пригодного текстового слоя — страницу нужно направить в OCR")
        return "scan", min(0.99, 0.72 + image_coverage * 0.25), warnings

    has_text = text_chars >= 24
    has_image = image_coverage >= 0.16
    has_vector = drawing_count >= 12
    has_table = table_count > 0
    signal_count = sum((has_text, has_image, has_vector, has_table))
    if signal_count >= 2 and has_text and (has_image or (has_vector and text_chars >= 120) or (has_table and has_image)):
        return "mixed", min(0.96, 0.72 + 0.06 * signal_count), warnings
    if has_table:
        return "table", min(0.97, 0.82 + min(table_count, 3) * 0.04), warnings
    if has_vector:
        return "drawing", min(0.96, 0.72 + min(drawing_count, 60) / 250), warnings
    if has_text:
        return "digital_text", min(0.98, 0.78 + min(text_chars, 2000) / 10000), warnings

    warnings.append("Содержимого недостаточно для уверенной автоматической маршрутизации")
    return "scan", 0.51, warnings


def _page_format(width_pt: float, height_pt: float) -> tuple[str, str, list[float]]:
    width_mm = width_pt * 25.4 / 72.0
    height_mm = height_pt * 25.4 / 72.0
    short, long = sorted((width_mm, height_mm))
    formats = {
        "A4": (210.0, 297.0),
        "A3": (297.0, 420.0),
        "A2": (420.0, 594.0),
        "A1": (594.0, 841.0),
        "A0": (841.0, 1189.0),
    }
    page_format = "Нестандартный"
    for name, (expected_short, expected_long) in formats.items():
        if abs(short - expected_short) / expected_short <= 0.045 and abs(long - expected_long) / expected_long <= 0.045:
            page_format = name
            break
    orientation = "альбомная" if width_pt > height_pt else "книжная"
    return page_format, orientation, [round(width_mm, 1), round(height_mm, 1)]


def _zone_text(blocks: list[dict[str, Any]], width: float, height: float) -> str:
    zx0, zy0, zx1, zy1 = _TITLE_ZONE
    parts: list[str] = []
    for block in blocks:
        bbox = block.get("bbox") or ()
        if len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (float(value) for value in bbox)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if width * zx0 <= cx <= width * zx1 and height * zy0 <= cy <= height * zy1:
            value = _block_text(block)
            if value.strip():
                parts.append(value)
    return "\n".join(parts)


def _stamp_payload(text: str, zone_text: str, *, page_number: int) -> dict[str, Any]:
    full = detect_in_text(text, source=f"page={page_number}")
    zone = detect_in_text(zone_text, source=f"page={page_number}#title-zone")
    if zone.present:
        status = "present"
        confidence = zone.confidence
        signatures = zone.signatures
    elif full.present:
        status = "outside_expected_zone"
        confidence = full.confidence
        signatures = full.signatures
    elif not text.strip():
        status = "unreadable"
        confidence = 0.0
        signatures = []
    else:
        status = "not_found"
        confidence = max(full.confidence, zone.confidence)
        signatures = full.signatures or zone.signatures
    sheet_match = _SHEET_NUMBER_RE.search(zone_text)
    return {
        "status": status,
        "confidence": round(float(confidence), 3),
        "signatures": list(signatures),
        "sheet_number": sheet_match.group(1) if sheet_match else "",
        "zone_rel": list(_TITLE_ZONE),
    }


def _page_passport(
    page,
    *,
    page_number: int,
    file_name: str,
    detect_tables: bool = True,
) -> dict[str, Any]:
    import fitz

    page_rect = page.rect
    width, height = float(page_rect.width), float(page_rect.height)
    page_area = max(1.0, width * height)
    # Do not copy embedded image bytes into Python memory: geometry is enough
    # for routing, while the preview endpoint renders pixels only on demand.
    text_flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    raw = page.get_text("dict", flags=text_flags) or {}
    blocks = [block for block in raw.get("blocks") or [] if isinstance(block, dict)]
    text_blocks = [block for block in blocks if block.get("type") == 0]
    try:
        image_infos = [item for item in (page.get_image_info(xrefs=True) or []) if isinstance(item, dict)]
    except Exception:  # noqa: BLE001
        image_infos = []
    text = page.get_text("text", sort=True) or ""
    text_chars = len([char for char in text if not char.isspace()])
    image_area = sum(_rect_area(item.get("bbox") or (0, 0, 0, 0)) for item in image_infos)
    image_coverage = min(1.0, image_area / page_area)
    try:
        drawing_count = len(page.get_drawings() or [])
    except Exception:  # noqa: BLE001 - one malformed page must remain inspectable
        drawing_count = 0
    table_count = 0
    table_detection = "not_requested"
    if detect_tables:
        if drawing_count > MAX_TABLE_DETECTION_DRAWINGS:
            table_detection = "skipped_complex_vector_page"
        else:
            try:
                table_count = len(getattr(page.find_tables(), "tables", []) or [])
                table_detection = "complete"
            except Exception:  # noqa: BLE001 - find_tables is an optional enrichment
                table_detection = "failed"
    quality = _text_quality(text)
    page_type, confidence, warnings = _classify_page(
        text_chars=text_chars,
        image_coverage=image_coverage,
        drawing_count=drawing_count,
        table_count=table_count,
        text_quality=quality,
    )
    if table_detection == "skipped_complex_vector_page":
        warnings.append("Поиск таблиц пропущен: на странице слишком много векторных объектов")
    elif table_detection == "failed":
        warnings.append("Автоматический поиск таблиц на странице не завершён")
    evidence_fragments: list[dict[str, Any]] = []
    for index, block in enumerate(text_blocks):
        value = _clean_text(_block_text(block))
        bbox = block.get("bbox") or ()
        if not value or len(bbox) != 4:
            continue
        evidence_fragments.append(
            {
                "fragment_id": f"p{page_number}-b{index + 1}",
                "text": value,
                "bbox": [round(float(number), 2) for number in bbox],
                "source_ref": f"{file_name}#page={page_number}#block={index + 1}",
            }
        )
        if len(evidence_fragments) >= 5:
            break
    page_format, orientation, size_mm = _page_format(width, height)
    stamp = _stamp_payload(text, _zone_text(text_blocks, width, height), page_number=page_number)
    requires_ocr = page_type in {"scan", "damaged_text_layer"}
    return {
        "schema": PDF_PAGE_SCHEMA,
        "page": page_number,
        "source_ref": f"{file_name}#page={page_number}",
        "page_type": page_type,
        "page_type_label": PAGE_TYPE_LABELS[page_type],
        "routing_confidence": round(confidence, 3),
        "requires_ocr": requires_ocr,
        "recognition_quality": quality,
        "geometry": {
            "width_pt": round(width, 2),
            "height_pt": round(height, 2),
            "size_mm": size_mm,
            "format": page_format,
            "orientation": orientation,
        },
        "signals": {
            "text_chars": text_chars,
            "text_blocks": len(text_blocks),
            "images": len(image_infos),
            "image_coverage": round(image_coverage, 3),
            "drawings": drawing_count,
            "tables": table_count,
            "table_detection": table_detection,
        },
        "stamp": stamp,
        "evidence_fragments": evidence_fragments,
        "warnings": warnings,
    }


def audit_pdf(
    source_path: str | Path,
    *,
    doc_id: str = "",
    file_name: str = "",
    max_pages: int = 80,
) -> dict[str, Any]:
    """Build a bounded page-level passport without writing beside the source."""
    import fitz

    path = _source_path(source_path)
    requested = max(1, min(int(max_pages or 80), MAX_AUDIT_PAGES))
    display_name = file_name or path.name
    with fitz.open(str(path)) as document:
        total_pages = int(document.page_count)
        inspected = min(total_pages, requested)
        pages = [
            _page_passport(document[index], page_number=index + 1, file_name=display_name)
            for index in range(inspected)
        ]
    counts = {key: 0 for key in PAGE_TYPE_LABELS}
    for page in pages:
        counts[str(page.get("page_type") or "scan")] += 1
    warnings = []
    if inspected < total_pages:
        warnings.append(f"Показаны первые {inspected} из {total_pages} страниц")
    return {
        "schema": PDF_CONTOUR_SCHEMA,
        "status": "partial" if inspected < total_pages else "ready",
        "context_role": "page_routing_and_evidence",
        "is_final_answer": False,
        "document": {
            "doc_id": doc_id,
            "file_name": display_name,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
        },
        "page_total": total_pages,
        "pages_inspected": inspected,
        "page_type_counts": counts,
        "ocr_required_pages": sum(bool(page.get("requires_ocr")) for page in pages),
        "tables_detected": sum(int((page.get("signals") or {}).get("tables") or 0) for page in pages),
        "stamps_detected": sum((page.get("stamp") or {}).get("status") == "present" for page in pages),
        "pages": pages,
        "warnings": warnings,
    }


def rag_page_metadata(
    source_path: str | Path,
    page_numbers: Iterable[int],
    *,
    file_name: str = "",
) -> dict[int, dict[str, Any]]:
    """Return the same page-passport contract for RAG node payloads.

    Unlike the GUI audit this reads only pages that produced page nodes and does
    not hash the whole source again.  Errors are intentionally left to the caller
    so ingestion can keep its existing fail-soft fallback.
    """
    import fitz

    path = _source_path(source_path)
    requested = sorted({int(value) for value in page_numbers if int(value) > 0})
    result: dict[int, dict[str, Any]] = {}
    with fitz.open(str(path)) as document:
        for page_number in requested:
            if page_number > document.page_count:
                continue
            result[page_number] = _page_passport(
                document[page_number - 1],
                page_number=page_number,
                file_name=file_name or path.name,
            )
    return result


def render_page_preview(
    source_path: str | Path,
    *,
    page_number: int,
    max_width: int = 1200,
    bbox: tuple[float, float, float, float] | None = None,
    highlight_bbox: tuple[float, float, float, float] | None = None,
) -> bytes:
    """Render a full page or evidence rectangle to PNG, without creating a sidecar file."""
    import fitz

    path = _source_path(source_path)
    width_limit = max(320, min(int(max_width or 1200), 1800))
    with fitz.open(str(path)) as document:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError("Страница PDF вне диапазона")
        page = document[page_number - 1]
        clip = None
        if bbox is not None:
            if len(bbox) != 4 or not all(math.isfinite(float(value)) for value in bbox):
                raise ValueError("Некорректная область evidence")
            clip = fitz.Rect(*(float(value) for value in bbox)) & page.rect
            if clip.is_empty or clip.width < 1 or clip.height < 1:
                raise ValueError("Область evidence не пересекает страницу")
        target_width = float(clip.width if clip is not None else page.rect.width)
        scale = min(3.0, max(0.5, width_limit / max(1.0, target_width)))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
        content = pixmap.tobytes("png")
        if highlight_bbox is None or clip is not None:
            return content
        if len(highlight_bbox) != 4 or not all(math.isfinite(float(value)) for value in highlight_bbox):
            raise ValueError("Некорректная подсветка evidence")
        highlight = fitz.Rect(*(float(value) for value in highlight_bbox)) & page.rect
        if highlight.is_empty or highlight.width < 1 or highlight.height < 1:
            raise ValueError("Подсветка evidence не пересекает страницу")

        from io import BytesIO

        from PIL import Image, ImageDraw

        image = Image.open(BytesIO(content)).convert("RGB")
        draw = ImageDraw.Draw(image, "RGBA")
        coords = tuple(int(round(value * scale)) for value in (highlight.x0, highlight.y0, highlight.x1, highlight.y1))
        line_width = max(3, int(round(scale * 2)))
        draw.rectangle(coords, fill=(15, 139, 104, 38), outline=(15, 139, 104, 235), width=line_width)
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()
