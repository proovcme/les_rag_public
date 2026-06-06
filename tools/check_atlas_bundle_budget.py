"""Check ATLAS standalone bundle size budget."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "standalone" / "cad_bim_viewer"
DEFAULT_LIMITS = {
    "assets/index.js": 8_000_000,
    "assets/index.css": 64_000,
    "fragments/worker.mjs": 16_000_000,
    "web-ifc/web-ifc.wasm": 16_000_000,
}


def check_budget(source: Path = SOURCE, limits: dict[str, int] | None = None) -> list[str]:
    failures: list[str] = []
    for relative_path, max_bytes in (limits or DEFAULT_LIMITS).items():
        path = source / relative_path
        if not path.is_file():
            failures.append(f"missing {relative_path}")
            continue
        size = path.stat().st_size
        if size > max_bytes:
            failures.append(f"{relative_path} is {size} bytes, budget is {max_bytes}")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check ATLAS standalone bundle size budget.")
    parser.add_argument("--source", type=Path, default=SOURCE)
    args = parser.parse_args(argv)

    failures = check_budget(args.source)
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("ATLAS bundle budget passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

