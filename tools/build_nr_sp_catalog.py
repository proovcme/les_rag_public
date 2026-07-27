"""Build an auditable NR/SP catalog from Orders 812/pr and 774/pr DOCX tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_NR = Path("/Users/ovc/Documents/сметный модуль/Накладные_812_ПР.docx")
DEFAULT_SP = Path("/Users/ovc/Documents/сметный модуль/СП_774_ПР.docx")
DEFAULT_OUT = Path("config/domain/nr_sp_catalog.json")
_COLLECTION_RE = re.compile(
    r"(ГЭСНмр|ГЭСНм|ГЭСНп|ГЭСНр|ГЭСН)\s+81-\d{2}-(\d{1,2})(?:-|\.{2,})",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _number(value: Any) -> float | None:
    try:
        return float(_text(value).replace(",", "."))
    except ValueError:
        return None


def _family(value: str) -> str:
    low = value.casefold()
    if low == "гэснмр":
        return "ГЭСНмр"
    if low == "гэснм":
        return "ГЭСНм"
    if low == "гэснп":
        return "ГЭСНп"
    if low == "гэснр":
        return "ГЭСНр"
    return "ГЭСН"


def _collections(source_label: str) -> list[str]:
    return sorted({
        f"{_family(match.group(1))}:{int(match.group(2)):02d}"
        for match in _COLLECTION_RE.finditer(source_label)
    })


def _table_rows(path: Path, table_index: int) -> list[list[str]]:
    from docx import Document

    document = Document(path)
    table = document.tables[table_index]
    return [[_text(cell.text) for cell in row.cells] for row in table.rows]


def build_catalog(
    *,
    nr_path: Path = DEFAULT_NR,
    sp_path: Path = DEFAULT_SP,
    out: Path = DEFAULT_OUT,
) -> dict[str, Any]:
    if not nr_path.is_file() or not sp_path.is_file():
        raise FileNotFoundError("both 812/pr and 774/pr DOCX sources are required")
    nr_by_id: dict[str, list[dict[str, Any]]] = {}
    for row_number, row in enumerate(_table_rows(nr_path, 4), 1):
        if len(row) < 6:
            continue
        rule_no, label, territory, _, _, source_label = row[:6]
        rate = _number(territory)
        collections = _collections(source_label)
        if not rule_no or rate is None or not collections:
            continue
        nr_by_id.setdefault(rule_no, []).append({
            "label": label,
            "nr_pct": rate,
            "collections": collections,
            "nr_source_row": row_number,
            "nr_source_label": source_label,
        })

    sp_by_id: dict[str, list[dict[str, Any]]] = {}
    for row_number, row in enumerate(_table_rows(sp_path, 3), 1):
        if len(row) < 4:
            continue
        rule_no, label, rate_raw, source_label = row[:4]
        rate = _number(rate_raw)
        collections = _collections(source_label)
        if not rule_no or rate is None or not collections:
            continue
        sp_by_id.setdefault(rule_no, []).append({
            "label": label,
            "sp_pct": rate,
            "collections": collections,
            "sp_source_row": row_number,
            "sp_source_label": source_label,
        })

    rules: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for rule_no in sorted(set(nr_by_id) | set(sp_by_id), key=lambda value: [int(x) for x in re.findall(r"\d+", value)]):
        nr_rows = nr_by_id.get(rule_no) or []
        sp_rows = sp_by_id.get(rule_no) or []
        used_sp: set[int] = set()
        for nr_index, nr in enumerate(nr_rows):
            if len(nr_rows) == len(sp_rows) and len(nr_rows) > 1:
                matching = [(nr_index, sp_rows[nr_index])]
            else:
                matching = [
                    (index, sp) for index, sp in enumerate(sp_rows)
                    if set(nr["collections"]) & set(sp["collections"])
                ]
            if not matching:
                unmatched.append({"rule_no": rule_no, "side": "nr", **nr})
                continue
            sp_rates = {sp["sp_pct"] for _, sp in matching}
            if len(sp_rates) != 1:
                unmatched.append({"rule_no": rule_no, "side": "sp_conflict", "rows": [sp for _, sp in matching]})
                continue
            used_sp.update(index for index, _ in matching)
            collections = sorted(set(nr["collections"]) & {
                collection for _, sp in matching for collection in sp["collections"]
            })
            sp = matching[0][1]
            rules.append({
                "rule_id": f"nrsp-{rule_no}",
                "rule_no": rule_no,
                "label": nr["label"] or sp["label"],
                "collections": collections,
                "nr_pct": nr["nr_pct"],
                "sp_pct": sp["sp_pct"],
                "basis": f"Приказ 812/пр п.{rule_no}; Приказ 774/пр п.{rule_no}",
                "source": {
                    "nr_path": str(nr_path),
                    "nr_table": 5,
                    "nr_row": nr["nr_source_row"],
                    "sp_path": str(sp_path),
                    "sp_table": 4,
                    "sp_rows": [item["sp_source_row"] for _, item in matching],
                },
            })
        for index, sp in enumerate(sp_rows):
            if index not in used_sp:
                unmatched.append({"rule_no": rule_no, "side": "sp", **sp})

    by_collection: dict[str, int] = {}
    for rule in rules:
        for collection in rule["collections"]:
            by_collection[collection] = by_collection.get(collection, 0) + 1
    payload = {
        "schema": "nr_sp_catalog_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "nr": {"path": str(nr_path), "sha256": _sha256(nr_path), "order": "812/pr"},
            "sp": {"path": str(sp_path), "sha256": _sha256(sp_path), "order": "774/pr"},
        },
        "rules": rules,
        "summary": {
            "rules": len(rules),
            "collections": len(by_collection),
            "ambiguous_collections": sorted(key for key, count in by_collection.items() if count > 1),
            "unmatched_rows": len(unmatched),
        },
        "unmatched": unmatched,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(out)
    return payload


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nr", default=str(DEFAULT_NR))
    parser.add_argument("--sp", default=str(DEFAULT_SP))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = build_catalog(nr_path=Path(args.nr), sp_path=Path(args.sp), out=Path(args.out))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if not result["summary"]["unmatched_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
