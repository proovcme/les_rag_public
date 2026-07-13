"""Synchronize all machine version surfaces from ``config/version.json``.

The JSON contract is the only input.  ``--check`` is intentionally part of
``make verify`` so a build-number bump cannot reach Tauri/NSIS with stale
Cargo or documentation passport values.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "version.json"


def load_contract() -> dict[str, object]:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    product = str(contract["product_version"])
    build = int(contract["build_number"])
    desktop = str(contract["desktop_version"])
    if desktop != f"5.1.{build}":
        raise RuntimeError(f"desktop_version must be 5.1.{build}, got {desktop}")
    return {**contract, "product_version": product, "build_number": build, "desktop_version": desktop}


def _replace(pattern: str, replacement: str, text: str, *, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"version surface not found: {label}")
    return updated


def desired_surfaces(contract: dict[str, object] | None = None) -> dict[Path, str]:
    contract = contract or load_contract()
    product = str(contract["product_version"])
    build = int(contract["build_number"])
    desktop = str(contract["desktop_version"])
    updates: dict[Path, str] = {}

    pyproject = ROOT / "pyproject.toml"
    updates[pyproject] = _replace(
        r'^(version = ")[^"]+("\s*)$', rf"\g<1>{product}\g<2>",
        pyproject.read_text(encoding="utf-8"), label="pyproject product version",
    )

    package = ROOT / "desktop" / "tauri" / "package.json"
    payload = json.loads(package.read_text(encoding="utf-8"))
    payload["version"] = product
    updates[package] = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    cargo = ROOT / "desktop" / "tauri" / "src-tauri" / "Cargo.toml"
    updates[cargo] = _replace(
        r'^(version = ")[^"]+("\s*)$', rf"\g<1>{desktop}\g<2>",
        cargo.read_text(encoding="utf-8"), label="Cargo desktop version",
    )

    cargo_lock = ROOT / "desktop" / "tauri" / "src-tauri" / "Cargo.lock"
    updates[cargo_lock] = _replace(
        r'(\[\[package\]\]\nname = "les-desktop"\nversion = ")[^"]+("\n)',
        rf"\g<1>{desktop}\g<2>", cargo_lock.read_text(encoding="utf-8"),
        label="Cargo.lock les-desktop version",
    )

    tauri = ROOT / "desktop" / "tauri" / "src-tauri" / "tauri.conf.json"
    tauri_payload = json.loads(tauri.read_text(encoding="utf-8"))
    tauri_payload["version"] = desktop
    updates[tauri] = json.dumps(tauri_payload, ensure_ascii=False, indent=2) + "\n"

    versioning = ROOT / "docs" / "VERSIONING.md"
    versioning_text = versioning.read_text(encoding="utf-8")
    versioning_text = _replace(
        r'^(\| `product_version` \| `)[^`]+(` \|)', rf"\g<1>{product}\g<2>",
        versioning_text, label="VERSIONING product version",
    )
    versioning_text = _replace(
        r'^(\| `build_number` \| `)[^`]+(` \|)', rf"\g<1>{build}\g<2>",
        versioning_text, label="VERSIONING build number",
    )
    versioning_text = _replace(
        r'^(\| `desktop_version` \| `)[^`]+(` \|)', rf"\g<1>{desktop}\g<2>",
        versioning_text, label="VERSIONING desktop version",
    )
    updates[versioning] = versioning_text

    passport = ROOT / "docs" / "SOFTWARE_VERSIONS.md"
    passport_text = passport.read_text(encoding="utf-8")
    passport_text = _replace(
        r'^(\| Версия продукта \| `)[^`]+(` \|)', rf"\g<1>{product}\g<2>",
        passport_text, label="software passport product version",
    )
    passport_text = _replace(
        r'^(\| Версия пакета Tauri/NSIS \| `)[^`]+(` \|)', rf"\g<1>{desktop}\g<2>",
        passport_text, label="software passport desktop version",
    )
    updates[passport] = passport_text
    return updates


def drifted_surfaces() -> list[Path]:
    return [path for path, desired in desired_surfaces().items() if path.read_text(encoding="utf-8") != desired]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    updates = desired_surfaces()
    drift = [path for path, desired in updates.items() if path.read_text(encoding="utf-8") != desired]
    if args.check:
        if drift:
            print("version contract drift:")
            for path in drift:
                print(f"- {path.relative_to(ROOT)}")
            print("run: make version-sync")
            return 1
        print("version contract synchronized")
        return 0
    for path in drift:
        path.write_text(updates[path], encoding="utf-8")
        print(f"updated {path.relative_to(ROOT)}")
    if not drift:
        print("version contract already synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
