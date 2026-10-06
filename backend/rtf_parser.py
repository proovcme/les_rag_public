"""Strict structural RTF admission and a bounded native literal-text reader.

No model, OCR, roles, prices or application workflow is selected here. RichEdit
can accept truncated streams, so lexical admission precedes native rendering.
Native text is evidence of that rendering, not original layout/completeness.
RTF syntax: https://learn.microsoft.com/en-us/previous-versions/office/developer/office2000/aa140284(v=office.10)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


class RtfParserError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(code + (": " + detail if detail else ""))


@dataclass(frozen=True)
class RtfValidation:
    structurally_valid: bool
    control_word_counts: tuple[tuple[str, int], ...]
    row_cell_counts: tuple[int, ...]
    binary_bytes: int


@dataclass(frozen=True)
class RtfRow:
    number: int
    cells: tuple[str, ...]
    source_text_start: int
    source_text_end: int


@dataclass(frozen=True)
class RtfExtractionResult:
    text: str
    source_file_sha256: str
    text_sha256: str
    validation: RtfValidation
    native_reader: str
    rows: tuple[RtfRow, ...]
    table_boundaries_verified: bool
    warnings: tuple[str, ...]
    native_metadata: tuple[tuple[str, Any], ...]
    structurally_valid: bool = True
    extraction_complete: bool = False
    geometry_verified: bool = False


def validate_rtf(raw: bytes) -> RtfValidation:
    """Scan groups/escapes/control tokens, respecting opaque ``\\binN`` bytes.

    This is structural validation, not a replacement RTF renderer. No header,
    font code page, Unicode fallback or visible text is guessed by this scanner.
    """
    if not isinstance(raw, bytes) or not re.match(rb"^\{\\rtf[0-9]+(?=[^A-Za-z0-9]|$)", raw):
        raise RtfParserError("RTF_INVALID_HEADER")
    depth = 0
    index = 0
    closed = False
    controls: Counter[str] = Counter()
    row_cells: list[int] = []
    current_cells = 0
    binary_bytes = 0
    while index < len(raw):
        char = raw[index]
        if closed:
            if char not in b" \t\r\n":
                raise RtfParserError("RTF_TRAILING_DATA")
            index += 1
            continue
        if char == ord("{"):
            depth += 1
            index += 1
        elif char == ord("}"):
            depth -= 1
            index += 1
            if depth == 0:
                closed = True
        elif char != ord("\\"):
            index += 1
        else:
            index += 1
            if index == len(raw):
                raise RtfParserError("RTF_DANGLING_ESCAPE")
            symbol = raw[index]
            if symbol == ord("'"):
                digits = raw[index + 1:index + 3]
                if len(digits) != 2 or any(digit not in b"0123456789abcdefABCDEF" for digit in digits):
                    raise RtfParserError("RTF_INVALID_HEX_ESCAPE")
                index += 3
                continue
            if not (65 <= symbol <= 90 or 97 <= symbol <= 122):
                index += 1  # Escaped brace/backslash or one-byte control symbol.
                continue
            start = index
            while index < len(raw) and (65 <= raw[index] <= 90 or 97 <= raw[index] <= 122):
                index += 1
            if index - start > 32:
                raise RtfParserError("RTF_CONTROL_WORD_TOO_LONG")
            word = raw[start:index].decode("ascii")
            controls[word] += 1
            negative = index < len(raw) and raw[index] == ord("-")
            if negative:
                index += 1
            argument_start = index
            while index < len(raw) and 48 <= raw[index] <= 57:
                index += 1
            digits = raw[argument_start:index]
            if negative and not digits:
                raise RtfParserError("RTF_INVALID_NUMBER")
            if index < len(raw) and raw[index] == ord(" "):
                index += 1
            if word == "bin":
                if negative or not digits:
                    raise RtfParserError("RTF_INVALID_BINARY_LENGTH")
                # Arbitrarily long parameters are legal RTF tokens. Avoid an
                # unbounded int conversion: a payload cannot exceed the file.
                normalized = digits.lstrip(b"0") or b"0"
                remaining = str(len(raw) - index).encode("ascii")
                if len(normalized) > len(remaining) or (len(normalized) == len(remaining) and normalized > remaining):
                    raise RtfParserError("RTF_TRUNCATED_BINARY")
                length = int(normalized)
                index += length
                binary_bytes += length
            elif word == "cell":
                current_cells += 1
            elif word == "row":
                row_cells.append(current_cells)
                current_cells = 0
    if not closed or depth:
        raise RtfParserError("RTF_UNCLOSED_GROUP")
    return RtfValidation(True, tuple(sorted(controls.items())), tuple(row_cells), binary_bytes)


def _native_platform() -> str:
    return sys.platform


def _windows_powershell() -> Path:
    return Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def _native_text(path: Path, timeout: float, expected_source_sha256: str) -> tuple[str, dict[str, Any]]:
    platform = _native_platform()
    flags = 0
    if platform == "win32":
        executable = _windows_powershell()
        helper = Path(__file__).resolve().parents[1] / "tools/windows_rtf_extract.ps1"
        if not executable.is_file() or not helper.is_file():
            raise RtfParserError("RTF_NATIVE_READER_UNAVAILABLE")
        args = [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-File", str(helper),
                "-SourcePath", str(path), "-ExpectedSourceSha256", expected_source_sha256]
        flags = 0x08000000  # CREATE_NO_WINDOW, without changing system policy.
    elif platform == "darwin" and shutil.which("textutil"):
        # Do not re-open mutable source through a reader whose rendered-byte
        # binding has not been established. Windows supplies an atomic buffer.
        raise RtfParserError("RTF_NATIVE_ATOMIC_INPUT_UNSUPPORTED")
    else:
        raise RtfParserError("RTF_NATIVE_READER_UNAVAILABLE")
    try:
        process = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired as error:
        raise RtfParserError("RTF_NATIVE_TIMEOUT") from error
    except OSError as error:
        raise RtfParserError("RTF_NATIVE_FAILED", type(error).__name__) from error
    if process.returncode:
        raise RtfParserError("RTF_NATIVE_FAILED", f"exit={process.returncode}")
    try:
        output = process.stdout.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise RtfParserError("RTF_NATIVE_INVALID_UTF8") from error
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as error:
        raise RtfParserError("RTF_NATIVE_INVALID_RESPONSE") from error
    if not isinstance(payload, dict):
        raise RtfParserError("RTF_NATIVE_INVALID_RESPONSE")
    if payload.get("status") != "ok":
        if payload.get("error_code") == "RTF_SOURCE_CHANGED":
            raise RtfParserError("RTF_SOURCE_CHANGED")
        raise RtfParserError("RTF_NATIVE_FAILED", str(payload.get("error_type") or "native_error"))
    if not isinstance(payload.get("text"), str):
        raise RtfParserError("RTF_NATIVE_INVALID_RESPONSE")
    if not isinstance(payload.get("source_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", payload["source_sha256"]):
        raise RtfParserError("RTF_NATIVE_INVALID_RESPONSE")
    return payload["text"], {key: value for key, value in payload.items() if key != "text"}


def _literal_table_rows(text: str, validation: RtfValidation) -> tuple[tuple[RtfRow, ...], bool]:
    controls = dict(validation.control_word_counts)
    expected = validation.row_cell_counts
    if not expected or any(controls.get(word) for word in ("tab", "nestcell", "nestrow")):
        return (), False
    lines = text.splitlines(keepends=True)
    if len(lines) != len(expected) or text.count("\t") != controls.get("cell", 0):
        return (), False
    rows = []
    offset = 0
    for number, (line, count) in enumerate(zip(lines, expected), 1):
        body = line[:-2] if line.endswith("\r\n") else line[:-1] if line.endswith("\n") else line
        # RichEdit exposes each source cell's end as a tab, including the last.
        if not body.endswith("\t") or body.count("\t") != count:
            return (), False
        rows.append(RtfRow(number, tuple(body[:-1].split("\t")), offset, offset + len(line)))
        offset += len(line)
    return tuple(rows), True


def extract_rtf(path: str | Path, *, timeout_seconds: float = 30) -> RtfExtractionResult:
    """Read verified-structured source through a hidden, bounded OS renderer.

    Image/OLE/field/table limitations remain visible. ``extraction_complete``
    and geometry are never inferred merely from native success/count equality.
    """
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30):
        raise RtfParserError("RTF_INVALID_TIMEOUT")
    try:
        source = Path(path).resolve(strict=True)
        if not source.is_file():
            raise RtfParserError("RTF_SOURCE_UNAVAILABLE")
        raw = source.read_bytes()
    except (OSError, TypeError) as error:
        raise RtfParserError("RTF_SOURCE_UNAVAILABLE", type(error).__name__) from error
    validation = validate_rtf(raw)
    controls = dict(validation.control_word_counts)
    if controls.get("object") or controls.get("objdata"):
        raise RtfParserError("RTF_EMBEDDED_OBJECTS_UNSUPPORTED")
    source_sha = hashlib.sha256(raw).hexdigest()
    text, metadata = _native_text(source, float(timeout_seconds), source_sha)
    try:
        unchanged = hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    except OSError as error:
        raise RtfParserError("RTF_SOURCE_CHANGED", type(error).__name__) from error
    if not unchanged or metadata.get("source_sha256") not in (None, source_sha):
        raise RtfParserError("RTF_SOURCE_CHANGED")
    try:
        encoded = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise RtfParserError("RTF_NATIVE_INVALID_UTF8") from error
    if not text:
        raise RtfParserError("RTF_NATIVE_EMPTY_TEXT")
    rows, boundaries = _literal_table_rows(text, validation)
    warnings = ["RTF_NATIVE_RENDERING_NOT_FULL_SOURCE_OR_GEOMETRY_PROOF"]
    for words, warning in (
        (("pict", "shp", "shpinst"), "RTF_IMAGES_NOT_TRANSCRIBED"),
        (("field", "fldinst"), "RTF_FIELDS_NOT_EVALUATED"),
        (("nestcell", "nestrow"), "RTF_NESTED_TABLES_UNVERIFIED"),
        (("clmgf", "clmrg", "clvmgf", "clvmrg"), "RTF_MERGED_TABLE_GEOMETRY_UNVERIFIED"),
        (("line",), "RTF_IN_CELL_BREAKS_UNVERIFIED"),
        (("tab",), "RTF_TEXT_TABS_AMBIGUOUS_WITH_CELLS"),
        (("header", "footer", "footnote", "annotation"), "RTF_AUXILIARY_DESTINATIONS_UNVERIFIED"),
    ):
        if any(controls.get(word) for word in words):
            warnings.append(warning)
    if validation.binary_bytes:
        warnings.append("RTF_BINARY_CONTENT_NOT_TRANSCRIBED")
    if controls.get("row") and not boundaries:
        warnings.append("RTF_TABLE_BOUNDARIES_UNVERIFIED")
    if "\ufffd" in text:
        warnings.append("RTF_REPLACEMENT_CHARACTER_PRESENT")
    return RtfExtractionResult(text=text, source_file_sha256=source_sha,
        text_sha256=hashlib.sha256(encoded).hexdigest(), validation=validation,
        native_reader=str(metadata.get("native_reader") or "windows-richtext"),
        rows=rows, table_boundaries_verified=boundaries, warnings=tuple(warnings),
        native_metadata=tuple(sorted(metadata.items())))
