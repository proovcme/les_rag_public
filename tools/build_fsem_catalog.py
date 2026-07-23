"""Extract the authoritative FSEM-2022 machine-to-machinist catalog from PDF."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SOURCE = Path("/Users/ovc/Documents/сметный модуль/ФСЭМ_2022_ФСЭМ_81_01_2022_Государственные_сметные_норматив.PDF")
DEFAULT_OUT = Path("data/smeta_base/fsem_2022.sqlite")
DEFAULT_MANIFEST = Path("data/smeta_base/fsem_2022_manifest.json")
_ROW_RE = re.compile(
    r"(91\.\d{2}\.\d{2}-\d{3})\s+(.*?)\s+маш\.-ч\s+"
    r"([\d ]+,\d{2}|-)\s+([\d ]+,\d{2}|-)\s+([\d]+,\d|-)\s+"
    r"(4-\d{3}-\d{3}|-)\s+([\d]+,\d{2}|-)",
    re.DOTALL,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00ad", "-").replace("\xa0", " ").split())


def _number(value: Any) -> float | None:
    text = _text(value).replace(" ", "").replace(",", ".")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def build_catalog(
    *,
    source: Path = DEFAULT_SOURCE,
    out: Path = DEFAULT_OUT,
    manifest_out: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    from pypdf import PdfReader

    if not source.is_file():
        raise FileNotFoundError(source)
    records: dict[str, dict[str, Any]] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}
    duplicate_same = 0
    reader = PdfReader(source)
    for page_number, page in enumerate(reader.pages[3:], 4):
        page_text = (page.extract_text() or "").replace("\u00ad", "-")
        page_marks = list(re.finditer(rf"(?m)^\s*{page_number}\s*$", page_text))
        if len(page_marks) >= 2:
            page_text = page_text[: page_marks[1].start()]
        for match in _ROW_RE.finditer(page_text):
            code, name, machine_price, driver_wage, grade, driver_code, crew_hours = match.groups()
            record = {
                "machine_code": code,
                "machine_name": _text(name),
                "machine_price_base": _number(machine_price),
                "driver_wage_base": _number(driver_wage),
                "driver_grade": _number(grade),
                "driver_code": "" if driver_code == "-" else driver_code,
                "crew_hours": _number(crew_hours) or 0.0,
                "source_page": page_number,
            }
            previous = records.get(code)
            if previous is None:
                records[code] = record
                continue
            previous_numeric = tuple(previous[key] for key in (
                "machine_price_base", "driver_wage_base", "driver_grade", "driver_code", "crew_hours"
            ))
            current_numeric = tuple(record[key] for key in (
                "machine_price_base", "driver_wage_base", "driver_grade", "driver_code", "crew_hours"
            ))
            if previous_numeric == current_numeric:
                duplicate_same += 1
                if len(record["machine_name"]) > len(previous["machine_name"]):
                    previous["machine_name"] = record["machine_name"]
                continue
            conflicts.setdefault(code, [previous]).append(record)

    for code in conflicts:
        records.pop(code, None)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    if temp.exists():
        temp.unlink()
    conn = sqlite3.connect(temp)
    try:
        conn.executescript(
            """
            CREATE TABLE machines(
                machine_code TEXT PRIMARY KEY,
                machine_name TEXT NOT NULL,
                machine_price_base REAL,
                driver_wage_base REAL,
                driver_grade REAL,
                driver_code TEXT NOT NULL,
                crew_hours REAL NOT NULL,
                source_page INTEGER NOT NULL
            );
            CREATE INDEX idx_fsem_driver_code ON machines(driver_code);
            """
        )
        conn.executemany(
            "INSERT INTO machines VALUES(:machine_code,:machine_name,:machine_price_base,:driver_wage_base,"
            ":driver_grade,:driver_code,:crew_hours,:source_page)",
            sorted(records.values(), key=lambda item: item["machine_code"]),
        )
        conn.commit()
    finally:
        conn.close()
    temp.replace(out)
    source_sha = _sha256(source)
    base_sha = _sha256(out)
    driver_rows = sum(bool(item["driver_code"] and item["crew_hours"] > 0) for item in records.values())
    no_driver_rows = sum(not item["driver_code"] and item["crew_hours"] == 0 for item in records.values())
    invalid_driver_rows = sum(bool(item["driver_code"]) != bool(item["crew_hours"] > 0) for item in records.values())
    verdict = "passed" if len(records) >= 1500 and invalid_driver_rows == 0 else "failed"
    manifest = {
        "schema": "fsem_2022_catalog_manifest_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "source": {"path": str(source), "sha256": source_sha, "pages": len(reader.pages)},
        "output": {"path": str(out), "sha256": base_sha, "rows": len(records)},
        "checks": {
            "minimum_rows": {"failures": int(len(records) < 1500), "rows": len(records)},
            "invalid_driver_rows": {"failures": invalid_driver_rows},
            "duplicate_machine_keys": {"failures": 0},
        },
        "coverage": {"driver_rows": driver_rows, "no_driver_rows": no_driver_rows},
        "quarantine": {
            "numeric_conflict_codes": sorted(conflicts),
            "numeric_conflict_count": len(conflicts),
            "same_numeric_duplicates": duplicate_same,
        },
    }
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = build_catalog(source=Path(args.source), out=Path(args.out), manifest_out=Path(args.manifest))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
