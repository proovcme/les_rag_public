"""PD/RD document manifest extraction.

This module builds a source map for project/working documentation before RAG:
volume contents, project composition, explanatory-note TOC, and compact sheet
passports. It is read-only and does not call an LLM.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from proxy.services.drawing_manifest_service import (
    extract_pdf_drawing_manifest,
    normalize_cipher,
    repair_pdf_text_mojibake,
)

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
_CIPHER_RE = re.compile(r"\b[А-ЯA-Z0-9]{1,16}(?:[-./][А-ЯA-Z0-9]{1,16}){2,14}\b", re.IGNORECASE)
_CYRILLIC_GLYPH_MOJIBAKE = str.maketrans(
    {
        "Ⱥ": "А",
        "Ȼ": "Б",
        "ȼ": "В",
        "Ƚ": "Г",
        "Ⱦ": "Д",
        "ȿ": "Е",
        "ɀ": "Ж",
        "Ɂ": "З",
        "ɂ": "И",
        "Ƀ": "Й",
        "Ʉ": "К",
        "Ʌ": "Л",
        "Ɇ": "М",
        "ɇ": "Н",
        "Ɉ": "О",
        "ɉ": "П",
        "Ɋ": "Р",
        "ɋ": "С",
        "Ɍ": "Т",
        "ɍ": "У",
        "Ɏ": "Ф",
        "ɏ": "Х",
        "ɐ": "Ц",
        "ɑ": "Ч",
        "ɚ": "а",
        "ɛ": "б",
        "ɜ": "в",
        "ɝ": "г",
        "ɞ": "д",
        "ɟ": "е",
        "ɠ": "ж",
        "ɡ": "з",
        "ɢ": "и",
        "ɣ": "й",
        "ɤ": "к",
        "ɥ": "л",
        "ɦ": "м",
        "ɧ": "н",
        "ɨ": "о",
        "ɩ": "п",
        "ɪ": "р",
        "ɫ": "с",
        "ɬ": "т",
        "ɭ": "у",
        "ɮ": "ф",
        "ɯ": "х",
        "ɰ": "ц",
        "ɱ": "ч",
        "ɲ": "ш",
        "ɳ": "щ",
        "ɴ": "ъ",
        "ɵ": "ы",
        "ɶ": "ь",
        "ɷ": "э",
        "ɸ": "ю",
        "ɹ": "я",
    }
)


def extract_pd_rd_manifest(
    pdf_path: str | Path,
    *,
    max_pages: int | None = None,
    include_sheet_pages: bool = False,
) -> dict[str, Any]:
    """Extract a compact PD/RD navigation manifest from a PDF volume."""
    path = Path(pdf_path)
    sheet_manifest = extract_pdf_drawing_manifest(path, max_pages=max_pages)
    pages = _read_pdf_lines(path, max_pages=max_pages)
    compact_pages = _compact_sheet_pages(sheet_manifest.get("pages") or [])
    volume_register = _build_volume_contents_register(pages, sheet_manifest)
    project_register = _build_project_composition_register(pages)
    pz_toc = _build_pz_toc(pages)
    manifest: dict[str, Any] = {
        "schema": "pd_rd_manifest_v1",
        "source_path": path.as_posix(),
        "file_name": path.name,
        "page_count": sheet_manifest.get("page_count") or len(pages),
        "pages_read": sheet_manifest.get("pages_read") or len(pages),
        "sheet_summary": {
            "schema": "pd_rd_sheet_summary_v1",
            "pages": compact_pages if include_sheet_pages else compact_pages[:20],
            "pages_total": len(compact_pages),
            "by_cipher": (sheet_manifest.get("groups") or {}).get("by_cipher") or {},
        },
        "volume_contents_register": volume_register,
        "project_composition_register": project_register,
        "pz_toc": pz_toc,
        "warnings": list(sheet_manifest.get("warnings") or []),
    }
    if not include_sheet_pages and len(compact_pages) > 20:
        manifest["sheet_summary"]["truncated"] = True
    if project_register.get("encoding_suspect_pages"):
        manifest["warnings"].append("project_composition_text_encoding_suspect")
    return manifest


def _read_pdf_lines(path: Path, *, max_pages: int | None) -> list[dict[str, Any]]:
    if not path.exists() or path.suffix.lower() != ".pdf":
        return []
    try:
        import fitz
    except Exception:
        return []
    pages: list[dict[str, Any]] = []
    with fitz.open(str(path)) as doc:
        total = int(getattr(doc, "page_count", 0) or 0)
        limit = total if max_pages is None else min(total, max(0, int(max_pages)))
        for idx in range(limit):
            text = repair_pd_rd_text(doc[idx].get_text("text") or "")
            lines = [_clean_line(line) for line in text.splitlines()]
            lines = [line for line in lines if line]
            pages.append({"page": idx + 1, "lines": lines})
    return pages


def repair_pd_rd_text(text: str) -> str:
    """Repair PDF text variants common in PD/RD exports."""
    repaired = repair_pdf_text_mojibake(text)
    glyph_repaired = repaired.translate(_CYRILLIC_GLYPH_MOJIBAKE)
    if _mojibake_ratio(repaired) > 0 and _cyrillic_score(glyph_repaired) > _cyrillic_score(repaired):
        return glyph_repaired
    return repaired


def _compact_sheet_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    keep = {
        "cipher_norm",
        "discipline_code",
        "subdiscipline_code",
        "document_kind_code",
        "stage",
        "sheet_no",
        "sheet_count",
        "object_name",
        "sheet_title",
        "source_file_name",
        "declared_format",
    }
    for page in pages:
        fields = page.get("fields") or {}
        compact_fields = {key: fields.get(key) for key in keep if fields.get(key)}
        out.append(
            {
                "page": page.get("page"),
                "sheet_format": page.get("sheet_format"),
                "stamp_present": page.get("stamp_present"),
                "stamp_confidence": page.get("stamp_confidence"),
                "fields": compact_fields,
            }
        )
    return out


def _build_volume_contents_register(pages: list[dict[str, Any]], sheet_manifest: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in sheet_manifest.get("volume_contents") or []:
        if row.get("name") or row.get("designation_norm"):
            rows.append(dict(row))
    for page in pages:
        rows.extend(_parse_volume_contents_lines(page["lines"], page_no=int(page["page"])))
    rows = _dedupe_rows(rows)
    declared_total = _declared_total_sheets(pages)
    pages_with_rows = sorted({int(row.get("page") or 0) for row in rows if row.get("page")})
    return {
        "schema": "volume_contents_register_v1",
        "rows": rows,
        "row_count": len(rows),
        "pages": pages_with_rows,
        "declared_total_sheets": declared_total,
        "warnings": [] if rows else ["volume_contents_not_found"],
    }


def _parse_volume_contents_lines(lines: list[str], *, page_no: int) -> list[dict[str, Any]]:
    body = _volume_body_lines(lines)
    if not body:
        return []
    rows: list[dict[str, Any]] = []
    section = ""
    idx = 0
    while idx < len(body):
        line = body[idx]
        key = _line_key(line)
        if key in {"графическая часть", "текстовая часть", "прилагаемые документы"}:
            section = line
            idx += 1
            continue
        if key.startswith("общее количество листов"):
            idx += 2
            continue
        cipher = _line_cipher(line)
        if cipher:
            name = body[idx + 1] if idx + 1 < len(body) else ""
            note = body[idx + 2] if idx + 2 < len(body) and _looks_like_sheet_note(body[idx + 2]) else ""
            if name and not _looks_like_sheet_note(name):
                rows.append(_volume_row(page_no, designation=cipher, name=name, note=note, section=section))
                idx += 3 if note else 2
                continue
        if _looks_like_contents_name(line) and idx + 1 < len(body) and _looks_like_sheet_note(body[idx + 1]):
            rows.append(_volume_row(page_no, designation="", name=line, note=body[idx + 1], section=section))
            idx += 2
            continue
        idx += 1
    return rows


def _volume_body_lines(lines: list[str]) -> list[str]:
    if not _looks_like_volume_contents_lines(lines):
        return []
    start = 0
    for idx, line in enumerate(lines):
        key = _line_key(line)
        if key == "примечание":
            start = idx + 1
            break
        if key.startswith("формат"):
            start = idx + 1
    body = [line for line in lines[start:] if not _is_pd_rd_noise(line)]
    return body


def _looks_like_volume_contents_lines(lines: list[str]) -> bool:
    joined = " ".join(_line_key(line) for line in lines[:40])
    if "содержание тома" in joined:
        return True
    if "имя файла" in joined and "_s_" in joined:
        return True
    return bool(lines and normalize_cipher(lines[0]).endswith(".С"))


def _volume_row(page_no: int, *, designation: str, name: str, note: str, section: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema": "volume_contents_row_v1",
        "page": page_no,
        "designation": designation,
        "designation_norm": normalize_cipher(designation) if designation else "",
        "name": name,
        "note": note,
        "section": section,
        "source_ref": f"#page={page_no}:volume_contents",
    }
    sheet_no = _sheet_no_from_note(note)
    if sheet_no:
        row["sheet_no"] = sheet_no
    sheet_count = _sheet_count_from_note(note)
    if sheet_count:
        row["sheet_count"] = sheet_count
    return row


def _build_project_composition_register(pages: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    suspect_pages: list[int] = []
    for page in pages:
        lines = page["lines"]
        if not _looks_like_project_composition_lines(lines):
            continue
        page_no = int(page["page"])
        if _mojibake_ratio(" ".join(lines[:60])) > 0.15:
            suspect_pages.append(page_no)
        rows.extend(_parse_project_composition_lines(lines, page_no=page_no))
    return {
        "schema": "project_composition_register_v1",
        "rows": _dedupe_rows(rows),
        "row_count": len(_dedupe_rows(rows)),
        "pages": sorted({int(row.get("page") or 0) for row in rows if row.get("page")}),
        "encoding_suspect_pages": suspect_pages,
        "warnings": [] if rows else ["project_composition_not_found"],
    }


def _parse_project_composition_lines(lines: list[str], *, page_no: int) -> list[dict[str, Any]]:
    body = _project_composition_body_lines(lines)
    rows: list[dict[str, Any]] = []
    idx = 0
    while idx < len(body):
        volume_no = body[idx]
        if not re.fullmatch(r"\d+(?:\(\d+\))?(?:\.\d+)*", volume_no):
            idx += 1
            continue
        designation = ""
        name_parts: list[str] = []
        j = idx + 1
        if j < len(body) and (_line_cipher(body[j]) or _line_key(body[j]).startswith("не требуется")):
            designation = _line_cipher(body[j]) or body[j]
            j += 1
        while j < len(body) and not re.fullmatch(r"\d+(?:\(\d+\))?(?:\.\d+)*", body[j]):
            if not _is_pd_rd_noise(body[j]):
                name_parts.append(body[j])
            j += 1
        if designation or name_parts:
            rows.append(
                {
                    "schema": "project_composition_row_v1",
                    "page": page_no,
                    "volume_no": volume_no,
                    "designation": designation,
                    "designation_norm": normalize_cipher(designation) if _line_cipher(designation) else "",
                    "name": " ".join(name_parts).strip(),
                    "source_ref": f"#page={page_no}:project_composition",
                }
            )
        idx = max(j, idx + 1)
    return rows


def _project_composition_body_lines(lines: list[str]) -> list[str]:
    start = 0
    for idx, line in enumerate(lines):
        key = _line_key(line)
        if key.startswith("приме") or key.startswith("чание"):
            start = idx + 1
            break
    return [line for line in lines[start:] if not _is_pd_rd_noise(line)]


def _looks_like_project_composition_lines(lines: list[str]) -> bool:
    joined = " ".join(_line_key(line) for line in lines[:80])
    if "состав проект" in joined:
        return True
    has_sp_cipher = any(normalize_cipher(line).endswith("-СП") for line in lines[:20])
    has_composition_columns = "тома" in joined and ("обозначение" in joined or "наименование" in joined)
    return has_sp_cipher and has_composition_columns


def _build_pz_toc(pages: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        lines = page["lines"]
        if not any(_line_key(line) == "оглавление" for line in lines[:60]):
            continue
        rows.extend(_parse_pz_toc_lines(lines, page_no=int(page["page"])))
    rows = _dedupe_rows(rows)
    return {
        "schema": "pz_toc_v1",
        "rows": rows,
        "row_count": len(rows),
        "pages": sorted({int(row.get("page") or 0) for row in rows if row.get("page")}),
        "warnings": [] if rows else ["pz_toc_not_found"],
    }


def _parse_pz_toc_lines(lines: list[str], *, page_no: int) -> list[dict[str, Any]]:
    try:
        start = next(idx for idx, line in enumerate(lines) if _line_key(line) == "оглавление") + 1
    except StopIteration:
        return []
    body = [line for line in lines[start:] if not _is_pd_rd_noise(line)]
    rows: list[dict[str, Any]] = []
    pending_no = ""
    pending_title = ""
    for line in body:
        parsed = _parse_toc_line(line)
        if parsed:
            no, title, target_page = parsed
            rows.append(_toc_row(page_no, no, title, target_page))
            pending_no = ""
            pending_title = ""
            continue
        if re.fullmatch(r"\d+(?:\.\d+)*", line):
            pending_no = line
            pending_title = ""
            continue
        if pending_no:
            parsed_tail = _parse_toc_title_tail(line)
            if parsed_tail:
                title, target_page = parsed_tail
                full_title = " ".join(part for part in (pending_title, title) if part).strip()
                rows.append(_toc_row(page_no, pending_no, full_title, target_page))
                pending_no = ""
                pending_title = ""
            else:
                pending_title = " ".join(part for part in (pending_title, line) if part).strip()
    return rows


def _parse_toc_line(line: str) -> tuple[str, str, int] | None:
    cleaned = re.sub(r"\.{2,}", " ", line)
    match = re.match(r"^(\d+(?:\.\d+)*)\s+(.+?)\s+(\d+)$", cleaned)
    if not match:
        return None
    return match.group(1), match.group(2).strip(), int(match.group(3))


def _parse_toc_title_tail(line: str) -> tuple[str, int] | None:
    cleaned = re.sub(r"\.{2,}", " ", line)
    match = re.match(r"^(.+?)\s+(\d+)$", cleaned)
    if not match:
        return None
    return match.group(1).strip(), int(match.group(2))


def _toc_row(page_no: int, section_no: str, title: str, target_page: int) -> dict[str, Any]:
    return {
        "schema": "pz_toc_row_v1",
        "page": page_no,
        "section_no": section_no,
        "title": title,
        "target_sheet": target_page,
        "source_ref": f"#page={page_no}:pz_toc",
    }


def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row.get("schema"),
            row.get("page"),
            row.get("designation_norm") or row.get("designation"),
            row.get("volume_no"),
            row.get("section_no"),
            row.get("name") or row.get("title"),
            row.get("note"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _declared_total_sheets(pages: list[dict[str, Any]]) -> int | None:
    for page in pages:
        lines = page["lines"]
        for idx, line in enumerate(lines):
            if _line_key(line).startswith("общее количество листов"):
                for value in lines[idx + 1: idx + 4]:
                    match = re.search(r"\b(\d+)\s+лист", _line_key(value))
                    if match:
                        return int(match.group(1))
    return None


def _line_cipher(line: str) -> str:
    compact = re.sub(r"\s*([./-])\s*", r"\1", str(line or "").translate(_DASHES).upper())
    matches = _CIPHER_RE.findall(compact)
    for match in matches:
        norm = normalize_cipher(match)
        if "/" in norm or "-" in norm:
            return norm
    return ""


def _looks_like_sheet_note(line: str) -> bool:
    key = _line_key(line)
    return bool(re.search(r"\bлист(?:а|ов)?\b", key))


def _looks_like_contents_name(line: str) -> bool:
    key = _line_key(line)
    if len(key) < 6 or _line_cipher(line) or _looks_like_sheet_note(line):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)*", key):
        return False
    if key.startswith(("общее количество", "согласовано")):
        return False
    return True


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


def _is_pd_rd_noise(line: str) -> bool:
    key = _line_key(line)
    if not key:
        return True
    if key in {
        "изм.",
        "изм",
        "кол.уч",
        "кол уч",
        "лист",
        "листов",
        "№док",
        "№док.",
        "подп.",
        "подп",
        "дата",
        "разраб.",
        "разраб",
        "проверил",
        "н.контр",
        "н контр",
        "гип",
        "стадия",
        "взамен инв. №",
        "подпись и дата",
        "инв. № подл.",
        "обозначение",
        "наименование",
        "примечание",
        "№",
        "тома",
    }:
        return True
    if key.startswith(("имя файла", "формат", "акционерное общество", "общество с ограниченной")):
        return True
    if re.fullmatch(r"\d{2}\.\d{2}", key):
        return True
    return False


def _mojibake_ratio(text: str) -> float:
    raw = str(text or "")
    if not raw:
        return 0.0
    noisy = sum(1 for ch in raw if "\u0200" <= ch <= "\u027f")
    return noisy / max(1, len(raw))


def _cyrillic_score(text: str) -> int:
    return sum(1 for ch in str(text or "") if "А" <= ch <= "я" or ch == "ё" or ch == "Ё")


def _line_key(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").translate(_DASHES).strip().lower().replace("ё", "е"))


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip(" \t\r\n|"))
