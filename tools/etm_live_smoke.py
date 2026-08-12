#!/usr/bin/env python3
"""Live ETM Product API smoke: login + Goods browse + Price.

Does not restart LES. Safe to run while an LSR document is assembling.
Never prints login, password, or session-id.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def load_local_env(root: Path = ROOT) -> None:
    from dotenv import load_dotenv

    load_dotenv(root / ".env", override=False)
    load_dotenv(root / "config" / "local" / "windows-cuda.env", override=False)
    load_dotenv(root / "config" / "local" / "secrets.env", override=True)


def _redact(payload: Any) -> Any:
    secrets = [
        value
        for value in (
            os.getenv("LES_ETM_PASSWORD", ""),
            os.getenv("LES_ETM_LOGIN", ""),
        )
        if value
    ]
    text = json.dumps(payload, ensure_ascii=False)
    for secret in secrets:
        text = text.replace(secret, "***")
    return _drop_session_fields(json.loads(text))


def _drop_session_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_session_fields(item)
            for key, item in value.items()
            if str(key).casefold() not in {"session", "session-id", "session_id", "pwd", "password"}
        }
    if isinstance(value, list):
        return [_drop_session_fields(item) for item in value]
    return value


def run_smoke(
    *,
    code: str | None = None,
    material: str = "ETM smoke item",
    unit: str = "шт",
) -> dict[str, Any]:
    from proxy.services.etm_price_service import (
        EtmConfig,
        EtmNotConfiguredError,
        EtmPriceClient,
        EtmPriceError,
        configuration_status,
    )

    status = configuration_status()
    report: dict[str, Any] = {
        "schema": "etm_live_smoke_v1",
        "ok": False,
        "configured": bool(status.get("configured")),
        "base_url": status.get("base_url"),
        "read_only": True,
    }
    if not status.get("configured"):
        report["reason"] = "etm_not_configured"
        return report

    smoke_code = str(
        code
        or os.getenv("LES_ETM_SMOKE_CODE", "")
        or "9536092"
    ).strip()
    client = EtmPriceClient(EtmConfig.from_env())
    try:
        report["login"] = bool(client.authenticate())
        browse = client.browse_goods(smoke_code, limit=5)
        candidates = [
            {
                "gdscode": str(row.get("gdscode") or ""),
                "name": str(row.get("name") or "")[:120],
                "art": str(row.get("art") or ""),
                "unit": str(row.get("unit") or ""),
            }
            for row in (browse.get("candidates") or [])
            if isinstance(row, dict)
        ]
        report["browse"] = {
            "query": smoke_code,
            "count": int(browse.get("count") or 0),
            "candidates": candidates,
        }
        lookup_code = str(
            (candidates[0].get("gdscode") if candidates else "") or smoke_code
        ).strip()
        quotes = client.collect_quotes(
            [{"code": lookup_code, "material": material, "unit": unit}],
        )
        row = (quotes.get("rows") or [{}])[0]
        quote = (quotes.get("quotes") or [None])[0]
        report["price"] = {
            "code": lookup_code,
            "found": bool(quotes.get("found")),
            "reason": str(row.get("reason") or ""),
            "price_field": quotes.get("price_field"),
            "has_price": bool(isinstance(quote, dict) and quote.get("price")),
            "source_kind": str((quote or {}).get("source_kind") or ""),
        }
        report["ok"] = bool(report["login"] and (candidates or report["price"]["found"]))
        if not report["ok"]:
            report["reason"] = str(row.get("reason") or "browse_empty")
        return report
    except EtmNotConfiguredError:
        report["reason"] = "etm_not_configured"
        return report
    except EtmPriceError as error:
        report["reason"] = str(error)
        return report
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Live ETM login/browse/price smoke")
    parser.add_argument("--code", default="", help="ETM/article code to browse and price")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full redacted report as JSON",
    )
    args = parser.parse_args()
    load_local_env()
    report = _redact(run_smoke(code=args.code or None))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        configured = "yes" if report.get("configured") else "no"
        login = "ok" if report.get("login") else "fail"
        price = report.get("price") or {}
        browse = report.get("browse") or {}
        print(f"ETM configured: {configured}")
        print(f"base_url: {report.get('base_url')}")
        if not report.get("configured"):
            print("reason: etm_not_configured (fill config/local/secrets.env)")
            return 2
        print(f"login: {login}")
        print(f"browse: query={browse.get('query')} count={browse.get('count')}")
        print(
            "price: "
            f"code={price.get('code')} found={price.get('found')} "
            f"reason={price.get('reason') or 'ok'}"
        )
        print(f"ok: {report.get('ok')}")
        if report.get("reason") and not report.get("ok"):
            print(f"reason: {report.get('reason')}")
    if not report.get("configured"):
        return 2
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
