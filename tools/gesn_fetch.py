"""Дотянуть нормы ГЭСН-2022 из API cs.smetnoedelo в базу (квота-aware: код = 1 запрос).

    LES_SMETNOE_TOKEN=... uv run python -m tools.gesn_fetch 11-01-011-01 08-02-001-01
    LES_SMETNOE_VIA_SSH=root@host LES_SMETNOE_TOKEN=... uv run python -m tools.gesn_fetch <код>   # через VPS

Кладёт расход в data/gesn_base/gesn2022.parquet → дальше gesn_service/lsr_assembly считают по этим кодам.
"""
from __future__ import annotations

import argparse

from proxy.services.gesn_api_service import fetch_and_cache


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Дотянуть нормы ГЭСН из API smetnoedelo")
    ap.add_argument("codes", nargs="+", help="шифры норм, напр. 11-01-011-01")
    ap.add_argument("--base", default="gesn2", help="база (gesn2=ГЭСН-2022 строит.)")
    args = ap.parse_args(argv)

    balance = None
    for code in args.codes:
        try:
            r = fetch_and_cache(code, base=args.base)
            balance = r.get("balance")
            print(f"  ✓ {r['code']}: {r['resources']} ресурсов · остаток квоты {balance}")
        except Exception as e:
            print(f"  ✗ {code}: {e}")
    if balance is not None and balance < 20:
        print(f"⚠ остаток квоты мал: {balance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
