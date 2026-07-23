"""Drawing sheet manifest MVP.

Read-only extraction of a sheet passport from PDF drawings: page format,
bottom-right title block zone, positioned text blocks, and first metadata
candidates such as object name, address, volume and cipher.

This is navigation/provenance data for later RAG/tool use. It does not make
domain conclusions and does not replace the model's answer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from proxy.services.normcontrol_service import PT_TO_MM, classify_format, extract_cipher
from proxy.services.title_block_extract_service import detect_in_text

STAMP_ZONE_REL = (0.45, 0.58, 1.0, 1.0)

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
_CIPHER_TOKEN_RE = re.compile(
    r"\b[А-ЯA-Z0-9]{1,16}(?:[-./][А-ЯA-Z0-9]{1,16}){2,12}\b",
    re.IGNORECASE,
)

_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "object_name": (
        "наименование объекта",
        "название объекта",
        "объект",
        "object name",
        "object",
    ),
    "object_address": (
        "адрес объекта",
        "адрес строительства",
        "адрес",
        "местоположение",
        "address",
        "site address",
    ),
    "volume": (
        "том",
        "книга",
        "раздел",
        "volume",
        "book",
        "section",
    ),
    "cipher": (
        "шифр",
        "обозначение",
        "designation",
        "cipher",
    ),
    "stage": (
        "стадия",
        "stage",
    ),
    "sheet_no": (
        "лист",
        "sheet",
    ),
    "sheet_count": (
        "листов",
        "sheets",
    ),
}

_DISCIPLINE_TITLES = {
    "ИОС": "инженерное оборудование, сети и системы",
}
_SUBDISCIPLINE_TITLES = {
    "ЭС": "система электроснабжения",
}
_DOCUMENT_KIND_TITLES = {
    "ПЗ": "пояснительная записка",
    "СО": "спецификация оборудования, изделий и материалов",
    "ВОР": "ведомость объемов работ",
}


@dataclass(frozen=True)
class FieldCandidate:
    field: str
    value: str
    source: str
    source_ref: str
    confidence: float

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TextBlock:
    text: str
    bbox_pt: list[float]
    zone: str

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SheetPassport:
    page: int
    page_size_pt: list[float]
    page_size_mm: list[float]
    sheet_format: str | None
    stamp_bbox_pt: list[float]
    stamp_text: str
    stamp_present: bool
    stamp_confidence: float
    text_blocks: list[TextBlock] = field(default_factory=list)
    volume_contents: list[dict[str, Any]] = field(default_factory=list)
    candidates: list[FieldCandidate] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["text_blocks"] = [b.payload() for b in self.text_blocks]
        data["candidates"] = [c.payload() for c in self.candidates]
        return data


def normalize_cipher(value: str) -> str:
    """Normalize a drawing cipher for grouping while preserving raw values elsewhere."""
    text = str(value or "").translate(_DASHES).upper()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-./")


def repair_pdf_text_mojibake(text: str) -> str:
    """Repair common PDF Cyrillic mojibake where cp1251 bytes are exposed as Latin-1."""
    raw = str(text or "")
    if not raw:
        return raw
    latin_noise = sum(1 for ch in raw if 0x80 <= ord(ch) <= 0xFF)
    if latin_noise < 1:
        return raw
    repaired_chars: list[str] = []
    for ch in raw:
        code = ord(ch)
        if 0x80 <= code <= 0xFF:
            try:
                repaired_chars.append(bytes([code]).decode("cp1251"))
            except UnicodeDecodeError:
                repaired_chars.append(ch)
        else:
            repaired_chars.append(ch)
    repaired = "".join(repaired_chars)
    raw_score = _cyrillic_score(raw)
    repaired_score = _cyrillic_score(repaired)
    non_space = max(1, sum(1 for ch in raw if not ch.isspace()))
    if repaired_score > raw_score + 2:
        return repaired
    if repaired_score == latin_noise and repaired_score / non_space >= 0.5:
        return repaired
    return raw


def extract_pdf_drawing_manifest(
    pdf_path: str | Path,
    *,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Extract a read-only drawing manifest from a PDF.

    ``max_pages`` bounds operator-driven probes; ``None`` reads all pages.
    The function never writes source files and never calls an LLM.
    """
    path = Path(pdf_path)
    manifest: dict[str, Any] = {
        "schema": "drawing_manifest_v1",
        "source_path": path.as_posix(),
        "file_name": path.name,
        "pages": [],
        "volume_contents": [],
        "groups": {"by_cipher": {}},
        "warnings": [],
    }
    if not path.exists() or path.suffix.lower() != ".pdf":
        manifest["warnings"].append("not_pdf_or_missing")
        return manifest
    try:
        import fitz
    except Exception:
        manifest["warnings"].append("fitz_unavailable")
        return manifest

    filename_cipher = extract_cipher(path.name)
    try:
        with fitz.open(str(path)) as doc:
            total = int(getattr(doc, "page_count", 0) or 0)
            limit = total if max_pages is None else min(total, max(0, int(max_pages)))
            for page_index in range(limit):
                page = doc[page_index]
                passport = _extract_sheet_passport(
                    page,
                    page_no=page_index + 1,
                    source_path=path,
                    source_name=path.name,
                    filename_cipher=filename_cipher,
                )
                payload = passport.payload()
                manifest["pages"].append(payload)
                manifest["volume_contents"].extend(payload.get("volume_contents") or [])
                cipher = str((payload.get("fields") or {}).get("cipher_norm") or "")
                if cipher:
                    manifest["groups"]["by_cipher"].setdefault(cipher, []).append(page_index + 1)
            manifest["page_count"] = total
            manifest["pages_read"] = limit
    except Exception as err:  # noqa: BLE001
        manifest["warnings"].append(f"pdf_read_failed: {err}")
    return manifest


def build_drawing_manifest_registry(
    pdf_paths: list[str | Path],
    *,
    dataset_id: str = "",
    max_pages_per_pdf: int = 2,
    limit: int | None = None,
    include_pages: bool = False,
) -> dict[str, Any]:
    """Build a compact drawing registry over many PDF files.

    This is the dataset-level navigation sidecar: documents are grouped by
    normalized cipher, and extraction gaps/conflicts are made explicit.
    """
    picked = [Path(p) for p in pdf_paths if str(p).lower().endswith(".pdf")]
    if limit is not None:
        picked = picked[: max(0, int(limit))]
    registry: dict[str, Any] = {
        "schema": "drawing_manifest_registry_v1",
        "dataset_id": dataset_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files_total": len(picked),
        "files_read": 0,
        "pages_read": 0,
        "groups": {"by_cipher": {}},
        "documents": [],
        "issues": {
            "no_cipher": [],
            "no_stamp": [],
            "warnings": [],
            "cipher_conflicts": [],
        },
    }
    for path in picked:
        manifest = extract_pdf_drawing_manifest(path, max_pages=max_pages_per_pdf)
        registry["files_read"] += 1
        registry["pages_read"] += int(manifest.get("pages_read") or 0)
        doc_summary = _document_summary(manifest, include_pages=include_pages)
        registry["documents"].append(doc_summary)
        fields = doc_summary.get("fields") or {}
        cipher = str(fields.get("cipher_norm") or "")
        if cipher:
            registry["groups"]["by_cipher"].setdefault(cipher, []).append(
                {
                    "file_name": doc_summary.get("file_name"),
                    "source_path": doc_summary.get("source_path"),
                    "pages": doc_summary.get("cipher_pages", []),
                }
            )
        else:
            registry["issues"]["no_cipher"].append(doc_summary.get("source_path"))
        if int(doc_summary.get("stamp_pages") or 0) == 0:
            registry["issues"]["no_stamp"].append(doc_summary.get("source_path"))
        if manifest.get("warnings"):
            registry["issues"]["warnings"].append(
                {"source_path": doc_summary.get("source_path"), "warnings": manifest.get("warnings")}
            )
        conflict = _cipher_conflict(doc_summary)
        if conflict:
            registry["issues"]["cipher_conflicts"].append(conflict)
    registry["ciphers_total"] = len(registry["groups"]["by_cipher"])
    return registry


def _extract_sheet_passport(
    page: Any,
    *,
    page_no: int,
    source_path: Path,
    source_name: str,
    filename_cipher: str | None,
) -> SheetPassport:
    rect = page.rect
    stamp_rect = _relative_rect(rect, STAMP_ZONE_REL)
    text_blocks = _page_text_blocks(page, stamp_rect)
    stamp_text = "\n".join(block.text for block in text_blocks if block.zone == "stamp")
    full_text = "\n".join(block.text for block in text_blocks)
    stamp = detect_in_text(stamp_text, source=f"{source_name}#page={page_no}:stamp")
    volume_contents = _volume_contents_rows(text_blocks, page_no=page_no, source_name=source_name)

    candidates: list[FieldCandidate] = []
    candidates.extend(_label_candidates(stamp_text, source="stamp_zone", source_ref=f"{source_name}#page={page_no}:stamp", confidence=0.95))
    candidates.extend(_label_candidates(full_text, source="page_text", source_ref=f"{source_name}#page={page_no}", confidence=0.72))
    candidates.extend(_cipher_token_candidates(stamp_text, source="stamp_zone_token", source_ref=f"{source_name}#page={page_no}:stamp", confidence=0.82))
    candidates.extend(_loose_cipher_token_candidates(stamp_text, source_ref=f"{source_name}#page={page_no}:stamp"))
    if filename_cipher:
        candidates.append(FieldCandidate("cipher", filename_cipher, "file_name", source_name, 0.65))
    candidates.extend(_text_part_stamp_candidates(stamp_text, source_ref=f"{source_name}#page={page_no}:stamp"))
    candidates.extend(_path_volume_candidates(source_path))
    preliminary = _best_fields(candidates)
    candidates.extend(_cipher_semantic_candidates(str(preliminary.get("cipher") or ""), source_ref=f"{source_name}#page={page_no}:stamp"))
    candidates.extend(
        _graphical_stamp_candidates(
            stamp_text,
            cipher=str(preliminary.get("cipher") or ""),
            source_ref=f"{source_name}#page={page_no}:stamp",
        )
    )
    candidates.extend(
        _stamp_structure_candidates(
            stamp_text,
            cipher=str(preliminary.get("cipher") or ""),
            source_ref=f"{source_name}#page={page_no}:stamp",
        )
    )

    fields = _best_fields(candidates)
    cipher_raw = str(fields.get("cipher") or "")
    if cipher_raw:
        fields["cipher_norm"] = normalize_cipher(cipher_raw)
    stamp_present = bool(stamp.present)
    stamp_confidence = float(stamp.confidence)
    if not stamp_present and fields.get("cipher") and (fields.get("sheet_no") or fields.get("source_file_name")):
        stamp_present = True
        stamp_confidence = max(stamp_confidence, 0.72)

    width_mm = round(float(rect.width) * PT_TO_MM, 1)
    height_mm = round(float(rect.height) * PT_TO_MM, 1)
    return SheetPassport(
        page=page_no,
        page_size_pt=[round(float(rect.width), 2), round(float(rect.height), 2)],
        page_size_mm=[width_mm, height_mm],
        sheet_format=classify_format(width_mm, height_mm),
        stamp_bbox_pt=[round(stamp_rect.x0, 2), round(stamp_rect.y0, 2), round(stamp_rect.x1, 2), round(stamp_rect.y1, 2)],
        stamp_text=stamp_text,
        stamp_present=stamp_present,
        stamp_confidence=stamp_confidence,
        text_blocks=text_blocks,
        volume_contents=volume_contents,
        candidates=candidates,
        fields=fields,
    )


def _document_summary(manifest: dict[str, Any], *, include_pages: bool) -> dict[str, Any]:
    pages = list(manifest.get("pages") or [])
    fields = _best_page_fields(pages)
    cipher_pages = [
        int(page.get("page") or 0)
        for page in pages
        if ((page.get("fields") or {}).get("cipher_norm") and (page.get("fields") or {}).get("cipher_norm") == fields.get("cipher_norm"))
    ]
    summary: dict[str, Any] = {
        "schema": "drawing_document_summary_v1",
        "file_name": manifest.get("file_name"),
        "source_path": manifest.get("source_path"),
        "page_count": manifest.get("page_count"),
        "pages_read": manifest.get("pages_read"),
        "sheet_formats": sorted({str(page.get("sheet_format")) for page in pages if page.get("sheet_format")}),
        "stamp_pages": sum(1 for page in pages if page.get("stamp_present")),
        "cipher_pages": cipher_pages,
        "fields": fields,
        "candidate_ciphers": _candidate_ciphers(pages),
        "volume_contents": manifest.get("volume_contents") or [],
        "warnings": manifest.get("warnings") or [],
    }
    if include_pages:
        summary["pages"] = pages
    return summary


def _best_page_fields(pages: list[dict[str, Any]]) -> dict[str, Any]:
    candidates: list[FieldCandidate] = []
    for page in pages:
        fields = page.get("fields") or {}
        for key, value in fields.items():
            if key.endswith("_source") or key == "cipher_norm" or value in ("", None):
                continue
            source = fields.get(f"{key}_source") or {}
            candidates.append(
                FieldCandidate(
                    field=key,
                    value=str(value),
                    source=str(source.get("source") or "page_fields"),
                    source_ref=str(source.get("source_ref") or ""),
                    confidence=float(source.get("confidence") or 0.5),
                )
            )
    fields = _best_fields(candidates)
    cipher_raw = str(fields.get("cipher") or "")
    if cipher_raw:
        fields["cipher_norm"] = normalize_cipher(cipher_raw)
    return fields


def _candidate_ciphers(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_value: dict[str, dict[str, Any]] = {}
    for page in pages:
        for candidate in page.get("candidates") or []:
            if candidate.get("field") != "cipher":
                continue
            raw = str(candidate.get("value") or "")
            norm = normalize_cipher(raw)
            if not norm:
                continue
            prev = by_value.get(norm)
            confidence = float(candidate.get("confidence") or 0.0)
            item = {
                "value": raw,
                "cipher_norm": norm,
                "source": candidate.get("source"),
                "source_ref": candidate.get("source_ref"),
                "confidence": confidence,
            }
            if prev is None or confidence > float(prev.get("confidence") or 0.0):
                by_value[norm] = item
    return sorted(by_value.values(), key=lambda item: (-float(item.get("confidence") or 0.0), str(item.get("cipher_norm") or "")))


def _cipher_conflict(doc_summary: dict[str, Any]) -> dict[str, Any] | None:
    ciphers = doc_summary.get("candidate_ciphers") or []
    if len(ciphers) <= 1:
        return None
    top = str(((doc_summary.get("fields") or {}).get("cipher_norm")) or "")
    others = [item for item in ciphers if item.get("cipher_norm") != top]
    if not others:
        return None
    return {
        "file_name": doc_summary.get("file_name"),
        "source_path": doc_summary.get("source_path"),
        "selected_cipher": top,
        "other_candidates": others[:5],
    }


def _relative_rect(page_rect: Any, rel: tuple[float, float, float, float]) -> Any:
    x0, y0, x1, y1 = rel
    return type(page_rect)(
        page_rect.x0 + page_rect.width * x0,
        page_rect.y0 + page_rect.height * y0,
        page_rect.x0 + page_rect.width * x1,
        page_rect.y0 + page_rect.height * y1,
    )


def _page_text_blocks(page: Any, stamp_rect: Any) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for raw in page.get_text("blocks") or []:
        try:
            x0, y0, x1, y1, text = raw[:5]
        except Exception:
            continue
        text = repair_pdf_text_mojibake(str(text or "")).strip()
        if not text:
            continue
        cx = (float(x0) + float(x1)) / 2
        cy = (float(y0) + float(y1)) / 2
        zone = "stamp" if stamp_rect.x0 <= cx <= stamp_rect.x1 and stamp_rect.y0 <= cy <= stamp_rect.y1 else "sheet_text"
        blocks.append(
            TextBlock(
                text=text,
                bbox_pt=[round(float(x0), 2), round(float(y0), 2), round(float(x1), 2), round(float(y1), 2)],
                zone=zone,
            )
        )
    return blocks


def _label_candidates(text: str, *, source: str, source_ref: str, confidence: float) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    for line in _lines(text):
        norm_line = _line_key(line)
        for field, labels in _FIELD_LABELS.items():
            for label in labels:
                value = _value_after_label(line, norm_line, label)
                if not value:
                    continue
                if field == "sheet_no" and _line_key(line).startswith("листов"):
                    continue
                candidates.append(FieldCandidate(field, value, source, source_ref, confidence))
                break
    return candidates


def _cipher_token_candidates(text: str, *, source: str, source_ref: str, confidence: float) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    for token in _CIPHER_TOKEN_RE.findall(str(text or "").translate(_DASHES).upper()):
        if any(ch.isdigit() for ch in token) and any(sep in token for sep in ("-", ".", "/")):
            sep_count = sum(1 for ch in token if ch in "-./")
            token_confidence = confidence if ("/" in token or sep_count >= 4) else max(0.4, confidence - 0.25)
            candidates.append(FieldCandidate("cipher", token, source, source_ref, token_confidence))
    return candidates


def _volume_contents_rows(text_blocks: list[TextBlock], *, page_no: int, source_name: str) -> list[dict[str, Any]]:
    page_lines = [_clean_stamp_line(line) for block in text_blocks for line in _lines(block.text)]
    if not _looks_like_volume_contents_page(page_lines):
        return []
    rows: list[dict[str, Any]] = []
    section = ""
    content_blocks = sorted(
        (block for block in text_blocks if block.bbox_pt[1] < 720),
        key=lambda block: (block.bbox_pt[1], block.bbox_pt[0]),
    )
    for block in content_blocks:
        lines = [_clean_stamp_line(line) for line in _lines(block.text)]
        lines = [line for line in lines if line and not _is_volume_contents_noise(line)]
        if not lines:
            continue
        if len(lines) == 1 and _line_key(lines[0]) in {"графическая часть", "текстовая часть"}:
            section = lines[0]
            continue
        row = _parse_volume_contents_block(lines, section=section, page_no=page_no, source_name=source_name)
        if row:
            rows.append(row)
    return rows


def _looks_like_volume_contents_page(lines: list[str]) -> bool:
    joined = " ".join(_line_key(line) for line in lines[:80])
    return ("обозначение" in joined and "наименование" in joined and "примечание" in joined) or "содержание тома" in joined


def _parse_volume_contents_block(
    lines: list[str],
    *,
    section: str,
    page_no: int,
    source_name: str,
) -> dict[str, Any] | None:
    if not lines:
        return None
    designation = ""
    name = ""
    note = ""
    first = lines[0]
    cipher_candidates = [
        candidate
        for candidate in _loose_cipher_token_candidates(first, source_ref="")
        if "/" in normalize_cipher(candidate.value) or "-" in normalize_cipher(candidate.value)
    ]
    if cipher_candidates:
        designation = normalize_cipher(cipher_candidates[0].value)
        if len(lines) >= 2:
            name = lines[1]
        if len(lines) >= 3:
            note = " ".join(lines[2:])
    elif _looks_like_graphical_contents_name(first):
        name = first
        if len(lines) >= 2:
            note = " ".join(lines[1:])
    else:
        return None
    if not name and not designation:
        return None
    row: dict[str, Any] = {
        "schema": "volume_contents_row_v1",
        "page": page_no,
        "designation": designation,
        "designation_norm": normalize_cipher(designation) if designation else "",
        "name": name,
        "note": note,
        "section": section,
        "source_ref": f"{source_name}#page={page_no}:volume_contents",
    }
    sheet_no = _sheet_no_from_note(note)
    if sheet_no:
        row["sheet_no"] = sheet_no
    sheet_count = _sheet_count_from_note(note)
    if sheet_count:
        row["sheet_count"] = sheet_count
    return row


def _is_volume_contents_noise(line: str) -> bool:
    key = _line_key(line)
    if not key:
        return True
    if key in {"обозначение", "наименование", "примечание"}:
        return True
    if "обозначение" in key and "наименование" in key:
        return True
    if _is_revision_table_noise(line) or _is_stamp_stop_line(line):
        return True
    if key.startswith(("имя файла", "формат", "взамен инв", "подпись и дата", "инв. № подл")):
        return True
    if re.fullmatch(r"\d{2}\.\d{2}", key):
        return True
    return False


def _looks_like_graphical_contents_name(line: str) -> bool:
    key = _line_key(line)
    if len(key) < 6:
        return False
    if re.match(r"^\d+[.)]\s", key):
        return False
    return any(word in key for word in ("схема", "план", "разрез", "спецификация", "ведомость", "таблица", "электрооборудование"))


def _sheet_no_from_note(note: str) -> str:
    match = re.search(r"\bлист\s+(\d+(?:\.\d+)?)\b", _line_key(note))
    return match.group(1) if match else ""


def _sheet_count_from_note(note: str) -> str:
    key = _line_key(note)
    match = re.search(r"\((\d+)\s+лист", key)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d+)\s+лист", key)
    return match.group(1) if match else ""


def _loose_cipher_token_candidates(text: str, *, source_ref: str) -> list[FieldCandidate]:
    compact = re.sub(r"\s*([./-])\s*", r"\1", str(text or "").translate(_DASHES).upper())
    return _cipher_token_candidates(compact, source="stamp_zone_loose_token", source_ref=source_ref, confidence=0.9)


def _path_volume_candidates(path: Path) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    for part in path.parts:
        text = repair_pdf_text_mojibake(part).strip()
        if not re.match(r"^\d+(?:\(\d+\)|(?:\.\d+)*)?\.\s+\S+", text):
            continue
        dot_depth = text.split(" ", 1)[0].count(".")
        confidence = max(0.45, 0.66 - dot_depth * 0.04)
        candidates.append(FieldCandidate("volume", text, "source_path", path.as_posix(), confidence))
    return candidates


def _stamp_structure_candidates(text: str, *, cipher: str, source_ref: str) -> list[FieldCandidate]:
    if not cipher:
        return []
    lines = _lines(text)
    cipher_norm = normalize_cipher(cipher)
    start = None
    for idx, line in enumerate(lines):
        if cipher_norm and cipher_norm in normalize_cipher(line):
            start = idx + 1
            break
    if start is None:
        return []
    tail = [_clean_stamp_line(line) for line in lines[start:]]
    if _looks_like_text_part_followup_tail(tail):
        return []
    if _looks_like_graphical_stamp_tail(tail):
        return []
    object_idx = None
    object_value = ""
    for idx, line in enumerate(tail):
        if _is_meaningful_stamp_value(line):
            object_idx = idx
            object_value = line
            break
    if object_idx is None:
        return []
    candidates = [FieldCandidate("object_name", object_value, "stamp_structure", source_ref, 0.78)]
    title_parts: list[str] = []
    for line in tail[object_idx + 1:]:
        if _is_stamp_stop_line(line):
            break
        if not _is_meaningful_stamp_value(line):
            continue
        title_parts.append(line)
        if len(title_parts) >= 4:
            break
    if title_parts:
        candidates.append(FieldCandidate("sheet_title", " ".join(title_parts), "stamp_structure", source_ref, 0.72))
    return candidates


def _graphical_stamp_candidates(text: str, *, cipher: str, source_ref: str) -> list[FieldCandidate]:
    if not cipher:
        return []
    lines = [_clean_stamp_line(line) for line in _lines(text)]
    cipher_norm = normalize_cipher(cipher)
    cipher_idx = None
    for idx, line in enumerate(lines):
        if cipher_norm and cipher_norm in normalize_cipher(line):
            cipher_idx = idx
            break
    if cipher_idx is None:
        return []
    tail = lines[cipher_idx + 1:]
    if _looks_like_text_part_followup_tail(tail):
        return []

    candidates: list[FieldCandidate] = []
    after_values = _graphical_table_values(tail)
    if after_values.get("stage"):
        candidates.append(FieldCandidate("stage", after_values["stage"], "graphical_stamp", source_ref, 0.9))
    if after_values.get("sheet_no"):
        candidates.append(FieldCandidate("sheet_no", after_values["sheet_no"], "graphical_stamp", source_ref, 0.91))
    if after_values.get("sheet_count"):
        candidates.append(FieldCandidate("sheet_count", after_values["sheet_count"], "graphical_stamp", source_ref, 0.88))

    if after_values.get("stage") or after_values.get("sheet_count"):
        window = lines[max(0, cipher_idx - 12): min(len(lines), cipher_idx + 16)]
        object_value = _pick_graphical_object_line(window)
        if object_value:
            candidates.append(FieldCandidate("object_name", object_value, "graphical_stamp", source_ref, 0.84))
        title_value = _pick_graphical_title_line(window)
        if title_value:
            candidates.append(FieldCandidate("sheet_title", title_value, "graphical_stamp", source_ref, 0.83))
    return candidates


def _text_part_stamp_candidates(text: str, *, source_ref: str) -> list[FieldCandidate]:
    lines = [_clean_stamp_line(line) for line in _lines(text)]
    candidates: list[FieldCandidate] = []
    for idx, line in enumerate(lines):
        key = _line_key(line)
        if key == "лист":
            value = _next_numeric_value(lines, idx)
            if value:
                candidates.append(FieldCandidate("sheet_no", value, "text_part_stamp", source_ref, 0.9))
        elif key == "листов":
            value = _next_integer_value(lines, idx)
            if value:
                candidates.append(FieldCandidate("sheet_count", value, "text_part_stamp", source_ref, 0.9))
        elif key == "стадия":
            value = _next_nonempty_value(lines, idx)
            if value:
                candidates.append(FieldCandidate("stage", value, "text_part_stamp", source_ref, 0.86))
        elif key.startswith("имя файла"):
            value = line.split(":", 1)[1].strip() if ":" in line else _next_nonempty_value(lines, idx)
            if value:
                candidates.append(FieldCandidate("source_file_name", value, "text_part_stamp", source_ref, 0.86))
        elif key.startswith("формат"):
            value = line.split(" ", 1)[1].strip() if " " in line else _next_nonempty_value(lines, idx)
            if value:
                candidates.append(FieldCandidate("declared_format", value, "text_part_stamp", source_ref, 0.86))
    return candidates


def _cipher_semantic_candidates(cipher: str, *, source_ref: str) -> list[FieldCandidate]:
    norm = normalize_cipher(cipher)
    tail = norm.rsplit("-", 1)[-1]
    parts = [part for part in tail.split(".") if part]
    if len(parts) < 2 or not all(re.search(r"[А-ЯA-Z]", part) for part in parts):
        return []
    candidates = [
        FieldCandidate("discipline_code", parts[0], "cipher_semantics", source_ref, 0.93),
    ]
    if parts[0] in _DISCIPLINE_TITLES:
        candidates.append(FieldCandidate("discipline_title", _DISCIPLINE_TITLES[parts[0]], "cipher_semantics", source_ref, 0.9))
    if len(parts) >= 2:
        candidates.append(FieldCandidate("subdiscipline_code", parts[1], "cipher_semantics", source_ref, 0.93))
        if parts[1] in _SUBDISCIPLINE_TITLES:
            candidates.append(FieldCandidate("subdiscipline_title", _SUBDISCIPLINE_TITLES[parts[1]], "cipher_semantics", source_ref, 0.9))
    if len(parts) >= 3:
        candidates.append(FieldCandidate("document_kind_code", parts[2], "cipher_semantics", source_ref, 0.93))
        if parts[2] in _DOCUMENT_KIND_TITLES:
            candidates.append(FieldCandidate("document_kind_title", _DOCUMENT_KIND_TITLES[parts[2]], "cipher_semantics", source_ref, 0.9))
    return candidates


def _best_fields(candidates: list[FieldCandidate]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    by_field: dict[str, list[FieldCandidate]] = {}
    for candidate in candidates:
        if not candidate.value:
            continue
        by_field.setdefault(candidate.field, []).append(candidate)
    for field, rows in by_field.items():
        best = sorted(rows, key=lambda row: (row.confidence, len(row.value)), reverse=True)[0]
        result[field] = best.value
        result[f"{field}_source"] = {
            "source": best.source,
            "source_ref": best.source_ref,
            "confidence": best.confidence,
        }
    return result


def _lines(text: str) -> list[str]:
    return [line.strip(" \t\r\n|") for line in str(text or "").splitlines() if line.strip()]


def _cyrillic_score(text: str) -> int:
    return sum(1 for ch in str(text or "") if "А" <= ch <= "я" or ch == "ё" or ch == "Ё")


def _line_key(line: str) -> str:
    return re.sub(r"\s+", " ", line.translate(_DASHES).strip().lower().replace("ё", "е"))


def _clean_stamp_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip(" \t\r\n|"))


def _is_meaningful_stamp_value(line: str) -> bool:
    key = _line_key(line)
    if not key or len(key) < 3:
        return False
    if _is_stamp_stop_line(line):
        return False
    if key.startswith("изм") and ("кол" in key or "лист" in key):
        return False
    if key.startswith("имя файла") or key.startswith("формат"):
        return False
    if key in {
        "дата",
        "подпись",
        "подп",
        "изл",
        "изм",
        "кол уч",
        "кол.уч",
        "n док",
        "№ док",
    }:
        return False
    if re.fullmatch(r"\d+", key):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?", key):
        return False
    return True


def _is_stamp_stop_line(line: str) -> bool:
    key = _line_key(line)
    return key in {
        "стадия",
        "stage",
        "лист",
        "sheet",
        "листов",
        "sheets",
        "разраб",
        "провер",
        "н контр",
        "гип",
    }


def _looks_like_text_part_followup_tail(lines: list[str]) -> bool:
    for line in lines[:6]:
        key = _line_key(line)
        if not key:
            continue
        return key == "лист" or key.startswith("имя файла") or key.startswith("формат")
    return False


def _looks_like_graphical_stamp_tail(lines: list[str]) -> bool:
    values = [_clean_stamp_line(line) for line in lines[:12]]
    if any(re.fullmatch(r"\d+\.\d+", value) for value in values):
        return True
    if any(_line_key(value) in {"стадия", "лист", "листов"} for value in values):
        return True
    return any(_line_key(value).startswith("имя файла") and value.lower().endswith(".dwg") for value in values)


def _graphical_table_values(lines: list[str]) -> dict[str, str]:
    labels = {"стадия", "stage", "лист", "sheet", "листов", "sheets"}
    values: list[str] = []
    seen_label = False
    for line in lines[:18]:
        value = _clean_stamp_line(line)
        key = _line_key(value)
        if not value:
            continue
        if key in labels:
            seen_label = True
            continue
        if _is_revision_table_noise(value) or key.startswith("имя файла") or key.startswith("формат"):
            continue
        if seen_label or re.fullmatch(r"(?:[A-ZА-Я]{1,2}|\d+(?:\.\d+)?)", value, re.IGNORECASE):
            values.append(value)
        if len(values) >= 6:
            break

    result: dict[str, str] = {}
    for idx, value in enumerate(values):
        if not result.get("stage") and re.fullmatch(r"[A-ZА-Я]{1,2}", value, re.IGNORECASE):
            result["stage"] = value
            for next_value in values[idx + 1:]:
                if not result.get("sheet_no") and re.fullmatch(r"\d+(?:\.\d+)?", next_value):
                    result["sheet_no"] = next_value
                    continue
                if result.get("sheet_no") and not result.get("sheet_count") and re.fullmatch(r"\d+", next_value):
                    result["sheet_count"] = next_value
                    break
            break
    if not result.get("sheet_no"):
        for value in values:
            if re.fullmatch(r"\d+\.\d+", value):
                result["sheet_no"] = value
                break
    if not result.get("sheet_no"):
        for value in values:
            if re.fullmatch(r"\d+", value) and value not in {"0", "00"}:
                result["sheet_no"] = value
                break
    return result


def _pick_graphical_object_line(lines: list[str]) -> str:
    for line in sorted((_clean_stamp_line(item) for item in lines), key=len):
        key = _line_key(line)
        if not _is_graphical_context_value(line):
            continue
        if len(key.split()) < 2:
            continue
        if "система" in key or "схема" in key:
            continue
        if any(word in key for word in ("здание", "корпус", "сооружение", "центр", "площадка")):
            return line
    return ""


def _pick_graphical_title_line(lines: list[str]) -> str:
    for line in lines:
        value = _clean_stamp_line(line)
        key = _line_key(value)
        if not _is_graphical_context_value(value):
            continue
        if any(word in key for word in ("схема", "план", "разрез", "спецификация", "ведомость", "щит", "таблица")):
            return value
    return ""


def _is_graphical_context_value(line: str) -> bool:
    key = _line_key(line)
    if not key or len(key) < 4:
        return False
    if _is_stamp_stop_line(line) or _is_revision_table_noise(line):
        return False
    if key.startswith(("имя файла", "формат", "технические требования", "примечания")):
        return False
    if re.match(r"^\d+[.)]\s", key):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?", key):
        return False
    return len(line) <= 140


def _is_revision_table_noise(line: str) -> bool:
    key = _line_key(line)
    if not key:
        return True
    if key in {
        "изм",
        "кол уч",
        "кол.уч",
        "лист",
        "n док",
        "№ док",
        "подп",
        "подп.",
        "дата",
        "разработал",
        "разраб",
        "проверил",
        "провер",
        "н контр",
        "гип",
    }:
        return True
    if re.fullmatch(r"\d{2}\.\d{2}", key):
        return True
    return False


def _next_numeric_value(lines: list[str], idx: int, *, window: int = 8) -> str:
    for item in lines[idx + 1: idx + 1 + window]:
        value = _clean_stamp_line(item)
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return value
    return ""


def _next_integer_value(lines: list[str], idx: int, *, window: int = 8) -> str:
    for item in lines[idx + 1: idx + 1 + window]:
        value = _clean_stamp_line(item)
        if re.fullmatch(r"\d+", value) and value not in {"0", "00"}:
            return value
    return ""


def _next_nonempty_value(lines: list[str], idx: int, *, window: int = 8) -> str:
    for item in lines[idx + 1: idx + 1 + window]:
        value = _clean_stamp_line(item)
        if value:
            return value
    return ""


def _value_after_label(line: str, norm_line: str, label: str) -> str:
    label_norm = _line_key(label)
    if not norm_line.startswith(label_norm):
        return ""
    if len(norm_line) > len(label_norm) and norm_line[len(label_norm)].isalnum():
        return ""
    value = line[len(label):].strip(" \t:-–—")
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()
