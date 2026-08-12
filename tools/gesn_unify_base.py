"""Build one typed GESN parquet from legacy and overlay sources.

The output has one identity rule: ``norm_key = <base_type>:<bare_code>``. A bare
legacy code is never assumed to be ГЭСН. It can be promoted only by an exact,
unique metadata match against a typed row; otherwise the row is quarantined.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from tools.gesn_import import (
    RESOURCE_FIELDS,
    _bare_norm_code,
    _base_type_from_code,
    _norm_key,
)


DEFAULT_LEGACY = Path("storage/cache/gesn_fgis/gesn2022_fgis_raw.parquet")
DEFAULT_OVERLAY = Path("storage/cache/gesn_fgis/gesn2022_overlay_raw.parquet")
DEFAULT_OUT = Path("data/gesn_base/gesn2022_unified.parquet")
DEFAULT_AUDIT = Path("data/gesn_base/gesn2022_unified_audit.json")
_EXPLICIT_BASE_RE = re.compile(r"^(ГЭСНМР|ГЭСНМ|ГЭСНП|ГЭСНР|ГЭСН)", re.I)


def _display_code(base_type: Any, code: Any) -> str:
    bare = _bare_norm_code(code)
    if not bare:
        return str(code or "").strip()
    bt = str(base_type or "").strip()
    return f"{bt}{bare}" if bt else bare


def _text_key(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).lower()


def _number_key(value: Any) -> str:
    """Stable numeric part of a resource identity without changing its value."""
    text = _text_key(value).replace(" ", "").replace(",", ".")
    try:
        return format(float(text), ".12g")
    except (TypeError, ValueError):
        return text


def _resource_identity(row: Any) -> tuple[str, str, str, str, str, str]:
    """Conservative identity for one resource within one norm.

    A resource code is stronger than a spelling of its name. Unit, normative
    consumption and an explicit price remain part of the identity, so two
    genuinely different source rows are never silently merged.
    """
    code = _text_key(row.get("resource_code"))
    name = _text_key(row.get("resource_name"))
    return (
        _text_key(row.get("norm_key")),
        _text_key(row.get("kind")),
        "code" if code else "name",
        code or name,
        _text_key(row.get("resource_unit")),
        f"{_number_key(row.get('per_unit'))}|{_number_key(row.get('price'))}",
    )


def _has_base_prefix(value: Any) -> bool:
    return bool(_EXPLICIT_BASE_RE.match(str(value or "").strip().upper().replace(" ", "")))


def _read_snapshot(path: Path) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        shutil.copy2(path, tmp_path)
        return pd.read_parquet(tmp_path)
    except Exception as exc:
        # Truncated mid-flush cache must not kill the whole FGIS job with a raw OSError.
        from tools.gesn_pdf_import import _quarantine_corrupt_parquet

        try:
            _quarantine_corrupt_parquet(path, reason=str(exc))
        except OSError:
            pass
        raise RuntimeError(
            f"corrupt GESN parquet quarantined ({path.name}): {exc}. "
            "Re-run FGIS/GESN update to rebuild the cache."
        ) from exc
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def _normalize_frame(path: Path, *, source_label: str, priority: int) -> pd.DataFrame:
    df = _read_snapshot(path)
    original_cols = set(df.columns)
    for field in RESOURCE_FIELDS:
        if field not in df.columns:
            df[field] = None
    df = df[list(RESOURCE_FIELDS)].copy()
    legacy_untyped = not {"base_type", "norm_key"}.issubset(original_cols)

    base_values: list[str] = []
    key_values: list[str] = []
    code_values: list[str] = []
    identity_sources: list[str] = []
    for rec in df[["norm_code", "base_type", "norm_key"]].to_dict(orient="records"):
        base_type = str(rec.get("base_type") or "").strip()
        identity_source = "provided"
        if not base_type and _has_base_prefix(rec.get("norm_code")):
            base_type = _base_type_from_code(rec.get("norm_code"), default="")
            identity_source = "code_prefix"
        elif not base_type:
            identity_source = "untyped_bare"
        bare = _bare_norm_code(rec.get("norm_code") or rec.get("norm_key"))
        key = str(rec.get("norm_key") or "").strip()
        if not key and base_type and bare:
            key = _norm_key(rec.get("norm_code"), base_type=base_type)
        elif not key and bare:
            key = f"UNRESOLVED:{bare}"
        base_values.append(base_type)
        key_values.append(key)
        code_values.append(_display_code(base_type, rec.get("norm_code") or key))
        identity_sources.append(identity_source)
    df["base_type"] = base_values
    df["norm_key"] = key_values
    df["norm_code"] = code_values
    df["_source_label"] = source_label
    df["_source_priority"] = priority
    df["_legacy_untyped"] = legacy_untyped
    df["_identity_source"] = identity_sources
    return df[df["norm_key"].astype(str).str.contains(":", regex=False, na=False)].copy()


def _first_filled(values: Iterable[Any]) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"nan", "none"}:
            return text
    return ""


def _remap_legacy_rows_by_typed_metadata(df: pd.DataFrame) -> int:
    typed_meta: dict[tuple[str, str, str], set[str]] = {}
    typed = df[df["_identity_source"].isin({"provided", "code_prefix"})].copy()
    for row in typed[["norm_key", "base_type", "norm_name", "norm_unit"]].drop_duplicates().itertuples():
        name_key = _text_key(row.norm_name)
        unit_key = _text_key(row.norm_unit)
        if not name_key or not unit_key or not row.base_type:
            continue
        bare = str(row.norm_key).split(":", 1)[-1]
        typed_meta.setdefault((bare, name_key, unit_key), set()).add(str(row.base_type))

    remapped = 0
    for idx, row in df[df["_identity_source"].eq("untyped_bare")].iterrows():
        name_key = _text_key(row.get("norm_name"))
        unit_key = _text_key(row.get("norm_unit"))
        if not name_key or not unit_key:
            continue
        bare = str(row.get("norm_key") or "").split(":", 1)[-1]
        base_types = typed_meta.get((bare, name_key, unit_key), set())
        if len(base_types) != 1:
            continue
        base_type = next(iter(base_types))
        if base_type == row.get("base_type"):
            continue
        norm_key = f"{base_type}:{bare}"
        df.at[idx, "base_type"] = base_type
        df.at[idx, "norm_key"] = norm_key
        df.at[idx, "norm_code"] = _display_code(base_type, bare)
        df.at[idx, "_identity_source"] = "typed_metadata_match"
        remapped += 1
    return remapped


def _metadata_matches(row: Any, chosen_name: str, chosen_unit: str) -> bool:
    row_name = _text_key(row.get("norm_name"))
    row_unit = _text_key(row.get("norm_unit"))
    if chosen_name and row_name and row_name != _text_key(chosen_name):
        return False
    if chosen_unit and row_unit and row_unit != _text_key(chosen_unit):
        return False
    return True


def _audit_identity(
    df: pd.DataFrame,
    conflicts: list[dict[str, Any]],
    *,
    remapped_legacy_rows: int,
    dropped_conflict_rows: int,
    resource_identity_duplicates_dropped: int,
    untyped_rows_quarantined: list[dict[str, Any]],
) -> dict[str, Any]:
    bare_base = (
        df[["norm_key", "base_type", "norm_code", "norm_name", "norm_unit"]]
        .drop_duplicates()
        .assign(bare=lambda x: x["norm_key"].astype(str).str.split(":", n=1).str[-1])
    )
    grouped = bare_base.groupby("bare")["base_type"].nunique()
    collision_bares = sorted(grouped[grouped > 1].index.astype(str).tolist())
    examples: list[dict[str, Any]] = []
    for bare in collision_bares[:50]:
        subset = bare_base[bare_base["bare"] == bare].sort_values(["base_type", "norm_key"])
        examples.append({
            "bare_code": bare,
            "variants": [
                {
                    "norm_key": str(row.norm_key),
                    "base_type": str(row.base_type),
                    "name": str(row.norm_name or "")[:160],
                    "unit": str(row.norm_unit or ""),
                }
                for row in subset.itertuples()
            ],
        })
    return {
        "schema": "gesn_unified_audit_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(df)),
        "norm_keys": int(df["norm_key"].nunique()),
        "bare_codes": int(bare_base["bare"].nunique()),
        "base_types": {str(k): int(v) for k, v in df.groupby("base_type")["norm_key"].nunique().to_dict().items()},
        "bare_code_collisions": {
            "count": len(collision_bares),
            "examples": examples,
        },
        "legacy_rows_remapped_by_typed_metadata": remapped_legacy_rows,
        "metadata_conflict_rows_dropped": dropped_conflict_rows,
        "resource_identity_duplicates_dropped": resource_identity_duplicates_dropped,
        "untyped_rows_quarantined": {
            "count": len(untyped_rows_quarantined),
            "examples": untyped_rows_quarantined[:100],
        },
        "identity_source_counts": {
            str(key): int(value)
            for key, value in df["_identity_source"].value_counts(dropna=False).to_dict().items()
        },
        "same_norm_key_metadata_conflicts_total": len(conflicts),
        "same_norm_key_metadata_conflicts": conflicts[:100],
    }


def build_unified(
    *,
    legacy: Path = DEFAULT_LEGACY,
    overlay: Path = DEFAULT_OVERLAY,
    out: Path = DEFAULT_OUT,
    audit_out: Path = DEFAULT_AUDIT,
    minimum_norms: int = 0,
) -> dict[str, Any]:
    frames: list[pd.DataFrame] = []
    if legacy.exists():
        frames.append(_normalize_frame(legacy, source_label=str(legacy), priority=10))
    if overlay.exists():
        frames.append(_normalize_frame(overlay, source_label=str(overlay), priority=20))
    if not frames:
        raise FileNotFoundError("No GESN parquet sources found")

    df = pd.concat(frames, ignore_index=True)
    df = df.astype(object).where(pd.notnull(df), None)
    remapped_legacy_rows = _remap_legacy_rows_by_typed_metadata(df)
    unresolved = df[df["_identity_source"].eq("untyped_bare")].copy()
    untyped_rows_quarantined = [
        {
            "bare_code": str(row.get("norm_key") or "").split(":", 1)[-1],
            "norm_name": str(row.get("norm_name") or "")[:160],
            "norm_unit": str(row.get("norm_unit") or ""),
            "resource_code": str(row.get("resource_code") or ""),
            "resource_name": str(row.get("resource_name") or "")[:160],
            "source": str(row.get("_source_label") or ""),
            "reason": "bare code has no explicit or uniquely matched base_type",
        }
        for row in unresolved.to_dict(orient="records")
    ]
    df = df[~df["_identity_source"].eq("untyped_bare")].copy()

    conflicts: list[dict[str, Any]] = []
    meta_rows: dict[str, dict[str, str]] = {}
    keep_indexes: list[Any] = []
    dropped_conflict_rows = 0
    for key, group in df.sort_values("_source_priority").groupby("norm_key", sort=False):
        names = [str(x or "").strip() for x in group["norm_name"].tolist() if str(x or "").strip()]
        units = [str(x or "").strip() for x in group["norm_unit"].tolist() if str(x or "").strip()]
        chosen_name = _first_filled(reversed(names))
        chosen_unit = _first_filled(reversed(units))
        work_steps = _first_filled(reversed([x for x in group["work_steps"].tolist() if str(x or "").strip()]))
        non_empty_names = sorted(set(names))
        non_empty_units = sorted(set(units))
        if len(non_empty_names) > 1 or len(non_empty_units) > 1:
            conflicts.append({
                "norm_key": str(key),
                "names": non_empty_names[:6],
                "units": non_empty_units[:6],
                "chosen_name": chosen_name,
                "chosen_unit": chosen_unit,
            })
        meta_rows[str(key)] = {
            "norm_name": chosen_name,
            "norm_unit": chosen_unit,
            "work_steps": work_steps,
        }
        for idx, row in group.iterrows():
            if _metadata_matches(row, chosen_name, chosen_unit):
                keep_indexes.append(idx)
            else:
                dropped_conflict_rows += 1

    df = df.loc[keep_indexes].copy()
    for field in ("norm_name", "norm_unit", "work_steps"):
        df[field] = [meta_rows.get(str(key), {}).get(field, "") for key in df["norm_key"]]

    df = df.sort_values(["norm_key", "_source_priority"], kind="stable")
    before_resource_dedup = len(df)
    df["_resource_identity"] = [
        _resource_identity(row)
        for row in df.to_dict(orient="records")
    ]
    df = df.drop_duplicates(subset=["_resource_identity"], keep="last")
    resource_identity_duplicates_dropped = before_resource_dedup - len(df)
    output_fields = [*RESOURCE_FIELDS, "_identity_source", "_source_label"]
    df = df[output_fields]

    norm_count = int(df["norm_key"].nunique())
    if norm_count < int(minimum_norms):
        raise RuntimeError(
            f"refusing to replace unified GESN source: {norm_count} < {minimum_norms} norms"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(out.suffix + ".tmp")
    df.to_parquet(tmp_out, compression="snappy", index=False)
    tmp_out.replace(out)

    audit = _audit_identity(
        df,
        conflicts,
        remapped_legacy_rows=remapped_legacy_rows,
        dropped_conflict_rows=dropped_conflict_rows,
        resource_identity_duplicates_dropped=resource_identity_duplicates_dropped,
        untyped_rows_quarantined=untyped_rows_quarantined,
    )
    audit["sources"] = [str(p) for p in (legacy, overlay) if p.exists()]
    audit["out"] = str(out)
    audit_out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def main(argv: Iterable[str] | None = None) -> int:
    from proxy.smeta_core.base_registry import active_base

    configured_minimum = int(active_base().get("minimum_norms") or 1)
    parser = argparse.ArgumentParser(description="Build typed unified GESN parquet")
    parser.add_argument("--legacy", default=str(DEFAULT_LEGACY))
    parser.add_argument("--overlay", default=str(DEFAULT_OVERLAY))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--audit-out", default=str(DEFAULT_AUDIT))
    parser.add_argument("--minimum-norms", type=int, default=configured_minimum)
    args = parser.parse_args(list(argv) if argv is not None else None)

    audit = build_unified(
        legacy=Path(args.legacy),
        overlay=Path(args.overlay),
        out=Path(args.out),
        audit_out=Path(args.audit_out),
        minimum_norms=int(args.minimum_norms),
    )
    print(json.dumps({
        "schema": audit["schema"],
        "created_at": audit["created_at"],
        "rows": audit["rows"],
        "norm_keys": audit["norm_keys"],
        "bare_codes": audit["bare_codes"],
        "base_types": audit["base_types"],
        "bare_code_collisions_count": audit["bare_code_collisions"]["count"],
        "legacy_rows_remapped_by_typed_metadata": audit["legacy_rows_remapped_by_typed_metadata"],
        "metadata_conflict_rows_dropped": audit["metadata_conflict_rows_dropped"],
        "resource_identity_duplicates_dropped": audit["resource_identity_duplicates_dropped"],
        "untyped_rows_quarantined": audit["untyped_rows_quarantined"]["count"],
        "metadata_conflicts_count": audit["same_norm_key_metadata_conflicts_total"],
        "audit": str(args.audit_out),
        "out": str(args.out),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
