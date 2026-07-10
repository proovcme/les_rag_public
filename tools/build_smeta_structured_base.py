"""Build the canonical machine-readable smeta base.

Raw GESN parquet is a staging/source format. The runtime-facing base is one
SQLite file with separate norm and resource tables, stable keys, and a manifest
that records what was excluded instead of silently exposing bad records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from proxy.services.gesn_service import _display_code, _f, _norm_code, _split_norm_ref, _work_steps

DEFAULT_SOURCE = Path("data/gesn_base/gesn2022_unified.parquet")
DEFAULT_OUT = Path("data/smeta_base/les_smeta_base.sqlite")
DEFAULT_MANIFEST = Path("data/smeta_base/les_smeta_base_manifest.json")
SCHEMA = "les_smeta_base_v1"


def _text(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return " ".join(text.split())


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    parsed = _f(value)
    return parsed if parsed or str(value).strip() in {"0", "0.0", "0,0"} else None


def _number_key(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return format(_f(value), ".12g")
    except (TypeError, ValueError):
        return _text(value).replace(",", ".")


def _resource_identity(resource: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Conservative dedupe key for a resource in one canonical norm.

    Code wins over display spelling, but unit, normative consumption and an
    explicit price stay in the key. This is a source-integrity guard, not a
    heuristic that changes a norm's resource composition.
    """
    code = _text(resource.get("resource_code")).casefold()
    name = _text(resource.get("resource_name")).casefold()
    return (
        _text(resource.get("kind")).casefold(),
        "code" if code else "name",
        code or name,
        _text(resource.get("resource_unit")).casefold(),
        f"{_number_key(resource.get('per_unit'))}|{_number_key(resource.get('price'))}",
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _norm_identity(rec: dict[str, Any]) -> tuple[str, str, str, str]:
    base_type = _text(rec.get("base_type")) or _split_norm_ref(rec.get("norm_code"))[0]
    key = _text(rec.get("norm_key"))
    bare = key.split(":", 1)[-1] if ":" in key else ""
    if not bare:
        bare = _norm_code(rec.get("norm_code"))
    if not key and bare:
        key = f"{base_type}:{bare}"
    return key, base_type, bare, _display_code(rec.get("norm_code") or bare, base_type)


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;

        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE norms (
            norm_key TEXT PRIMARY KEY,
            display_code TEXT NOT NULL,
            base_type TEXT NOT NULL,
            bare_code TEXT NOT NULL,
            norm_name TEXT NOT NULL,
            norm_unit TEXT NOT NULL,
            work_steps TEXT NOT NULL DEFAULT '[]',
            source_doc TEXT,
            source_guid TEXT,
            resource_count INTEGER NOT NULL,
            resource_kinds TEXT NOT NULL
        );

        CREATE TABLE resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            norm_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            resource_code TEXT NOT NULL DEFAULT '',
            resource_name TEXT NOT NULL,
            resource_unit TEXT NOT NULL DEFAULT '',
            per_unit REAL NOT NULL,
            price REAL,
            source_doc TEXT,
            source_guid TEXT,
            FOREIGN KEY(norm_key) REFERENCES norms(norm_key)
        );

        CREATE INDEX idx_norms_display_code ON norms(display_code);
        CREATE INDEX idx_norms_bare_code ON norms(bare_code);
        CREATE INDEX idx_norms_family_bare ON norms(base_type, bare_code);
        CREATE INDEX idx_resources_norm_key ON resources(norm_key);
        CREATE INDEX idx_resources_kind ON resources(kind);
        CREATE INDEX idx_resources_code ON resources(resource_code);
        CREATE INDEX idx_resources_name ON resources(resource_name);
        """
    )


def build_structured_base(
    *,
    source: Path = DEFAULT_SOURCE,
    out: Path = DEFAULT_OUT,
    manifest_out: Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(source)

    df = pd.read_parquet(source)
    df = df.astype(object).where(pd.notnull(df), None)

    grouped: dict[str, dict[str, Any]] = {}
    skipped_rows_missing_key = 0
    skipped_resource_rows = 0
    resource_identity_duplicates_dropped = 0
    for rec in df.to_dict(orient="records"):
        norm_key, base_type, bare_code, display_code = _norm_identity(rec)
        if not norm_key or not bare_code:
            skipped_rows_missing_key += 1
            continue
        norm = grouped.setdefault(
            norm_key,
            {
                "norm_key": norm_key,
                "display_code": display_code,
                "base_type": base_type,
                "bare_code": bare_code,
                "norm_name": "",
                "norm_unit": "",
                "work_steps": [],
                "source_doc": "",
                "source_guid": "",
                "resources": [],
                "resource_identities": set(),
            },
        )
        norm["norm_name"] = norm["norm_name"] or _text(rec.get("norm_name"))
        norm["norm_unit"] = norm["norm_unit"] or _text(rec.get("norm_unit"))
        norm["source_doc"] = norm["source_doc"] or _text(rec.get("source_doc"))
        norm["source_guid"] = norm["source_guid"] or _text(rec.get("source_guid"))
        if not norm["work_steps"]:
            norm["work_steps"] = _work_steps(rec.get("work_steps"))

        kind = _text(rec.get("kind"))
        name = _text(rec.get("resource_name"))
        if not kind or not name:
            skipped_resource_rows += 1
            continue
        resource = {
            "kind": kind,
            "resource_code": _text(rec.get("resource_code")),
            "resource_name": name,
            "resource_unit": _text(rec.get("resource_unit")),
            "per_unit": _f(rec.get("per_unit")),
            "price": _optional_float(rec.get("price")),
            "source_doc": _text(rec.get("source_doc")),
            "source_guid": _text(rec.get("source_guid")),
        }
        identity = _resource_identity(resource)
        if identity in norm["resource_identities"]:
            resource_identity_duplicates_dropped += 1
            continue
        norm["resource_identities"].add(identity)
        norm["resources"].append(resource)

    missing_metadata_norms = [
        key for key, norm in grouped.items() if not norm["norm_name"] or not norm["norm_unit"]
    ]
    no_resource_norms = [key for key, norm in grouped.items() if not norm["resources"]]
    included = {
        key: norm
        for key, norm in grouped.items()
        if norm["norm_name"] and norm["norm_unit"] and norm["resources"]
    }

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(out.suffix + ".tmp")
    if tmp_out.exists():
        tmp_out.unlink()
    conn = sqlite3.connect(tmp_out)
    try:
        _create_schema(conn)
        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "schema": SCHEMA,
            "created_at": now,
            "source_path": str(source),
            "source_sha256": _sha256(source),
        }
        conn.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", sorted(meta.items()))

        for norm in sorted(included.values(), key=lambda item: item["norm_key"]):
            resource_kinds = sorted({r["kind"] for r in norm["resources"]})
            conn.execute(
                """
                INSERT INTO norms(
                    norm_key, display_code, base_type, bare_code, norm_name, norm_unit,
                    work_steps, source_doc, source_guid, resource_count, resource_kinds
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    norm["norm_key"],
                    norm["display_code"],
                    norm["base_type"],
                    norm["bare_code"],
                    norm["norm_name"],
                    norm["norm_unit"],
                    json.dumps(norm["work_steps"], ensure_ascii=False),
                    norm["source_doc"],
                    norm["source_guid"],
                    len(norm["resources"]),
                    json.dumps(resource_kinds, ensure_ascii=False),
                ),
            )
            conn.executemany(
                """
                INSERT INTO resources(
                    norm_key, kind, resource_code, resource_name, resource_unit,
                    per_unit, price, source_doc, source_guid
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        norm["norm_key"],
                        res["kind"],
                        res["resource_code"],
                        res["resource_name"],
                        res["resource_unit"],
                        res["per_unit"],
                        res["price"],
                        res["source_doc"],
                        res["source_guid"],
                    )
                    for res in norm["resources"]
                ],
            )
        conn.commit()
    finally:
        conn.close()
    tmp_out.replace(out)

    manifest = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "path": str(source),
            "sha256": _sha256(source),
            "rows": int(len(df)),
            "norm_keys": int(df["norm_key"].nunique()) if "norm_key" in df.columns else len(grouped),
        },
        "output": {
            "path": str(out),
            "norms": len(included),
            "resources": sum(len(norm["resources"]) for norm in included.values()),
        },
        "excluded": {
            "rows_missing_norm_key": skipped_rows_missing_key,
            "resource_rows_missing_kind_or_name": skipped_resource_rows,
            "resource_identity_duplicates_dropped": resource_identity_duplicates_dropped,
            "norms_missing_name_or_unit": len(missing_metadata_norms),
            "norms_without_resources": len(no_resource_norms),
        },
        "examples": {
            "missing_metadata_norm_keys": sorted(missing_metadata_norms)[:50],
            "norms_without_resources": sorted(no_resource_norms)[:50],
        },
    }
    tmp_manifest = manifest_out.with_suffix(manifest_out.suffix + ".tmp")
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    tmp_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_manifest.replace(manifest_out)
    return manifest


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build canonical structured smeta SQLite base")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--manifest-out", default=str(DEFAULT_MANIFEST))
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = build_structured_base(
        source=Path(args.source),
        out=Path(args.out),
        manifest_out=Path(args.manifest_out),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
