"""Read-only ETM supplier-price adapter for model-owned KAC decisions."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.parse import quote

import httpx


DEFAULT_BASE_URL = "https://ipro.etm.ru/api/v1"
ALLOWED_CODE_TYPES = {"cli", "etm", "mnf"}
ALLOWED_PRICE_FIELDS = {"price", "pricewnds", "price_tarif", "price_retail"}
MAX_CODES_PER_REQUEST = 50
SESSION_TTL_SEC = 7 * 60 * 60 + 50 * 60


class EtmPriceError(RuntimeError):
    """Safe adapter error whose text contains no credential or session value."""


class EtmNotConfiguredError(EtmPriceError):
    pass


@dataclass(frozen=True)
class EtmConfig:
    login: str
    password: str
    base_url: str = DEFAULT_BASE_URL
    timeout_sec: float = 20.0
    vat_pct: float = 22.0

    @classmethod
    def from_env(cls) -> "EtmConfig":
        login = os.getenv("LES_ETM_LOGIN", "").strip()
        password = os.getenv("LES_ETM_PASSWORD", "").strip()
        if not login or not password:
            raise EtmNotConfiguredError(
                "ETM API is not configured: set LES_ETM_LOGIN and LES_ETM_PASSWORD"
            )
        return cls(
            login=login,
            password=password,
            base_url=os.getenv("LES_ETM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/"),
            timeout_sec=float(os.getenv("LES_ETM_TIMEOUT_SEC", "20")),
            vat_pct=float(os.getenv("LES_ETM_VAT_PCT", "22")),
        )


def configuration_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    values = os.environ if env is None else env
    return {
        "schema": "etm_price_source_status_v1",
        "configured": bool(
            values.get("LES_ETM_LOGIN") and values.get("LES_ETM_PASSWORD")
        ),
        "base_url": str(values.get("LES_ETM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        "read_only": True,
        "max_codes_per_request": MAX_CODES_PER_REQUEST,
        "price_rate_limit_sec": 1.0,
    }


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(
            str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
        )
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _status_code(payload: dict[str, Any]) -> int:
    try:
        return int((payload.get("status") or {}).get("code"))
    except (TypeError, ValueError):
        return 0


def _data_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    rows = data.get("rows")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return [data]


class EtmPriceClient:
    def __init__(
        self,
        config: EtmConfig,
        *,
        http_client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        price_interval_sec: float = 1.0,
    ) -> None:
        self.config = config
        self._http = http_client or httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout_sec,
            follow_redirects=True,
        )
        self._owns_http = http_client is None
        self._clock = clock
        self._sleep = sleep
        self._price_interval_sec = max(float(price_interval_sec), 0.0)
        self._lock = threading.RLock()
        self._session = ""
        self._session_expires_at = 0.0
        self._last_price_request_at: float | None = None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EtmPriceError("ETM API request failed") from error
        if not isinstance(payload, dict):
            raise EtmPriceError("ETM API returned a non-object response")
        return payload

    def _login(self) -> str:
        payload = self._request(
            "POST",
            "/user/login",
            params={"log": self.config.login, "pwd": self.config.password},
        )
        if _status_code(payload) != 200:
            raise EtmPriceError("ETM API authentication failed")
        data = payload.get("data") or {}
        session = str(data.get("session") or "") if isinstance(data, dict) else ""
        if not session:
            raise EtmPriceError("ETM API authentication returned no session")
        self._session = session
        self._session_expires_at = self._clock() + SESSION_TTL_SEC
        return session

    def _valid_session(self) -> str:
        with self._lock:
            if self._session and self._clock() < self._session_expires_at:
                return self._session
            return self._login()

    def _wait_for_price_slot(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_price_request_at is not None:
                remaining = self._price_interval_sec - (
                    now - self._last_price_request_at
                )
                if remaining > 0:
                    self._sleep(remaining)
            self._last_price_request_at = self._clock()

    def _price_request(
        self,
        codes: list[str],
        *,
        code_type: str,
        manufacturer_code: str | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "type": code_type,
            "session-id": self._valid_session(),
        }
        if manufacturer_code:
            params["mnf"] = manufacturer_code
        self._wait_for_price_slot()
        path = f"/goods/{quote(','.join(codes), safe='')}/price"
        payload = self._request("GET", path, params=params)
        if _status_code(payload) == 403:
            with self._lock:
                self._session = ""
                self._session_expires_at = 0.0
            params["session-id"] = self._valid_session()
            self._wait_for_price_slot()
            payload = self._request("GET", path, params=params)
        if _status_code(payload) != 200:
            raise EtmPriceError("ETM API price lookup failed")
        return payload

    def lookup_prices(
        self,
        codes: list[str],
        *,
        code_type: str = "etm",
        manufacturer_code: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized = [str(code or "").strip() for code in codes]
        if not normalized or any(not code for code in normalized):
            raise ValueError("ETM product codes must not be empty")
        if code_type not in ALLOWED_CODE_TYPES:
            raise ValueError(f"Unsupported ETM code type: {code_type}")
        if code_type == "mnf" and not manufacturer_code:
            raise ValueError("manufacturer_code is required for ETM mnf lookup")
        rows: list[dict[str, Any]] = []
        for batch in _chunks(normalized, MAX_CODES_PER_REQUEST):
            rows.extend(_data_rows(self._price_request(
                batch,
                code_type=code_type,
                manufacturer_code=manufacturer_code,
            )))
        return rows

    def collect_quotes(
        self,
        items: list[dict[str, Any]],
        *,
        code_type: str = "etm",
        manufacturer_code: str | None = None,
        price_field: str = "pricewnds",
    ) -> dict[str, Any]:
        if price_field not in ALLOWED_PRICE_FIELDS:
            raise ValueError(f"Unsupported ETM price field: {price_field}")
        codes = [str(item.get("code") or "").strip() for item in items]
        api_rows = self.lookup_prices(
            codes,
            code_type=code_type,
            manufacturer_code=manufacturer_code,
        )
        by_code = {
            str(row.get("gdscode") or row.get("code") or "").removeprefix("ETM"): row
            for row in api_rows
        }
        result_rows: list[dict[str, Any]] = []
        quotes: list[dict[str, Any]] = []
        includes_vat = price_field == "pricewnds"
        retrieved_at = datetime.now(timezone.utc).isoformat()
        for index, (item, code) in enumerate(zip(items, codes)):
            raw = by_code.get(code.removeprefix("ETM"))
            if raw is None and len(api_rows) == len(items):
                raw = api_rows[index]
            price = _number(raw.get(price_field)) if raw else None
            all_zero = bool(raw) and all(
                (_number(raw.get(field)) or 0.0) == 0.0
                for field in ALLOWED_PRICE_FIELDS
            )
            found = price is not None and price > 0
            row = {
                "found": found,
                "code": code,
                "material": str(item.get("material") or "").strip(),
                "unit": str(item.get("unit") or "").strip(),
                "price": price if found else None,
                "price_field": price_field,
                "price_includes_vat": includes_vat,
                "vat_pct": self.config.vat_pct if includes_vat else None,
                "reason": "" if found else (
                    "individual_quote_required" if all_zero else "not_found"
                ),
                "supplier_code": str(raw.get("gdscode") or "") if raw else "",
            }
            result_rows.append(row)
            if found:
                quotes.append({
                    "material": row["material"],
                    "supplier": "ЭТМ",
                    "unit": row["unit"],
                    "price": row["price"],
                    "price_includes_vat": includes_vat,
                    "vat_pct": row["vat_pct"],
                    "vat_basis": (
                        "ETM API price field pricewnds" if includes_vat else ""
                    ),
                    "source": (
                        f"{self.config.base_url}/goods/{quote(code, safe='')}/price"
                    ),
                    "source_kind": "supplier_api",
                    "source_ref": "ETM Product API / Price",
                    "retrieved_at": retrieved_at,
                    "product_code": code,
                })
        return {
            "schema": "etm_price_quotes_v1",
            "supplier": "ЭТМ",
            "code_type": code_type,
            "price_field": price_field,
            "requested": len(items),
            "found": len(quotes),
            "missing": len(items) - len(quotes),
            "rows": result_rows,
            "quotes": quotes,
        }


_shared_lock = threading.Lock()
_shared_client: EtmPriceClient | None = None


def get_client() -> EtmPriceClient:
    global _shared_client
    with _shared_lock:
        if _shared_client is None:
            _shared_client = EtmPriceClient(EtmConfig.from_env())
        return _shared_client
