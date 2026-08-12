"""Read-only ETM supplier-price adapter for model-owned KAC decisions."""

from __future__ import annotations

import os
import re
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
MAX_BROWSE_CANDIDATES = 50
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
        "order_api": False,
        "max_codes_per_request": MAX_CODES_PER_REQUEST,
        "price_rate_limit_sec": 1.0,
        "capabilities": {
            "price_lookup": True,
            "goods_browse": True,
            "kac_map": True,
            "remains": False,
            "sggds": False,
            "orders": False,
        },
    }


def _norm_material(name: Any) -> str:
    return re.sub(
        r"\s+", " ", str(name or "").strip().lower().replace("ё", "е")
    ).strip(" .,;:")


def _goods_path(product_id: str) -> str:
    """Goods v2 lives next to Product v1 (`/api/v1` → `/api/v2`)."""
    return f"/api/v2/goods/{quote(str(product_id).strip(), safe='')}"


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


def _safe_status_message(payload: dict[str, Any], *, secrets: tuple[str, ...] = ()) -> str:
    raw = str(((payload.get("status") or {}) if isinstance(payload.get("status"), dict) else {}).get("message") or "")
    text = " ".join(raw.split())
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:200]


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
        self._last_rate_limited_at: float | None = None

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
        except httpx.HTTPError as error:
            raise EtmPriceError("ETM API request failed") from error
        try:
            payload = response.json()
        except ValueError as error:
            raise EtmPriceError(f"ETM API HTTP {response.status_code}") from error
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
            detail = _safe_status_message(
                payload,
                secrets=(self.config.login, self.config.password),
            )
            raise EtmPriceError(
                "ETM API authentication failed"
                + (f": {detail}" if detail else "")
            )
        data = payload.get("data") or {}
        session = str(data.get("session") or "") if isinstance(data, dict) else ""
        if not session:
            raise EtmPriceError("ETM API authentication returned no session")
        self._session = session
        self._session_expires_at = self._clock() + SESSION_TTL_SEC
        return session

    def authenticate(self) -> bool:
        """Establish or reuse a session. Returns True; never exposes session-id."""
        return bool(self._valid_session())

    def _valid_session(self) -> str:
        with self._lock:
            if self._session and self._clock() < self._session_expires_at:
                return self._session
            return self._login()

    def _wait_for_rate_slot(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_rate_limited_at is not None:
                remaining = self._price_interval_sec - (
                    now - self._last_rate_limited_at
                )
                if remaining > 0:
                    self._sleep(remaining)
            self._last_rate_limited_at = self._clock()

    def _authed_get(
        self,
        path: str,
        *,
        code_type: str,
        manufacturer_code: str | None = None,
        extra_params: dict[str, Any] | None = None,
        failure_message: str,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "type": code_type,
            "session-id": self._valid_session(),
        }
        if manufacturer_code:
            params["mnf"] = manufacturer_code
        if extra_params:
            params.update(extra_params)
        self._wait_for_rate_slot()
        payload = self._request("GET", path, params=params)
        if _status_code(payload) == 403:
            with self._lock:
                self._session = ""
                self._session_expires_at = 0.0
            params["session-id"] = self._valid_session()
            self._wait_for_rate_slot()
            payload = self._request("GET", path, params=params)
        if _status_code(payload) != 200:
            raise EtmPriceError(failure_message)
        return payload

    def _price_request(
        self,
        codes: list[str],
        *,
        code_type: str,
        manufacturer_code: str | None,
    ) -> dict[str, Any]:
        path = f"/goods/{quote(','.join(codes), safe='')}/price"
        return self._authed_get(
            path,
            code_type=code_type,
            manufacturer_code=manufacturer_code,
            failure_message="ETM API price lookup failed",
        )

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

    def browse_goods(
        self,
        query: str,
        *,
        code_type: str = "etm",
        manufacturer_code: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Read-only Goods v2 candidates. Selection stays with model/user."""
        product_id = str(query or "").strip()
        if not product_id:
            raise ValueError("ETM browse query must not be empty")
        if code_type not in ALLOWED_CODE_TYPES:
            raise ValueError(f"Unsupported ETM code type: {code_type}")
        if code_type == "mnf" and not manufacturer_code:
            raise ValueError("manufacturer_code is required for ETM mnf browse")
        limit = max(1, min(int(limit), MAX_BROWSE_CANDIDATES))
        payload = self._authed_get(
            _goods_path(product_id),
            code_type=code_type,
            manufacturer_code=manufacturer_code,
            failure_message="ETM API goods browse failed",
        )
        candidates = [
            candidate
            for candidate in (
                _goods_candidate(row) for row in _data_rows(payload)
            )
            if candidate.get("gdscode") or candidate.get("art")
        ][:limit]
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return {
            "schema": "etm_goods_browse_v1",
            "selection_owner": "model_or_user",
            "code_type": code_type,
            "query": product_id,
            "result_text": str((data or {}).get("result_text") or ""),
            "count": len(candidates),
            "candidates": candidates,
        }


def _goods_candidate(row: dict[str, Any]) -> dict[str, Any]:
    gdscode = str(row.get("gdscode") or "").strip()
    code = str(row.get("code") or "").strip()
    if not gdscode and code.upper().startswith("ETM"):
        gdscode = code[3:]
    unit = str(row.get("edizm") or row.get("pack") or "").strip()
    name = str(row.get("name") or "").strip()
    if not name:
        chars = ((row.get("add_info_card") or {}) if isinstance(row.get("add_info_card"), dict) else {})
        tree = chars.get("gdsClassTree") if isinstance(chars, dict) else None
        if isinstance(tree, list) and tree:
            leaf = tree[-1] if isinstance(tree[-1], dict) else {}
            name = str(leaf.get("name") or "").strip()
    return {
        "gdscode": gdscode,
        "code": code or (f"ETM{gdscode}" if gdscode else ""),
        "name": name,
        "art": str(row.get("art") or "").strip(),
        "mnf_name": str(row.get("mnf_name") or "").strip(),
        "mnf_code": str(row.get("mnf_code") or "").strip(),
        "unit": unit,
        "image": str(row.get("image") or "").strip(),
    }


def _net_price_from_quote(quote: dict[str, Any]) -> float | None:
    gross = _number(quote.get("price"))
    if gross is None or gross <= 0:
        return None
    if not quote.get("price_includes_vat"):
        return round(gross, 6)
    vat_pct = _number(quote.get("vat_pct"))
    if vat_pct is None or vat_pct < 0:
        return None
    return round(gross / (1.0 + vat_pct / 100.0), 6)


def build_kac_map_from_quotes(
    quotes_result: dict[str, Any],
    *,
    resource_codes: dict[str, str] | None = None,
) -> dict[str, float]:
    """Map ETM quotes → net KAC prices keyed by material name and resource/product code.

    Miss / individual_quote_required rows stay absent (never priced as 0).
    """
    resource_codes = resource_codes or {}
    kac_map: dict[str, float] = {}
    for quote in quotes_result.get("quotes") or []:
        if not isinstance(quote, dict):
            continue
        net = _net_price_from_quote(quote)
        if net is None:
            continue
        material = str(quote.get("material") or "").strip()
        product_code = str(quote.get("product_code") or "").strip()
        resource_code = str(
            resource_codes.get(product_code)
            or resource_codes.get(material)
            or ""
        ).strip()
        for key in (material, _norm_material(material), product_code, resource_code):
            if key:
                kac_map[key] = net
    return kac_map


def fetch_kac_map_for_materials(
    items: list[dict[str, Any]],
    *,
    client: EtmPriceClient | None = None,
    code_type: str = "etm",
    manufacturer_code: str | None = None,
    price_field: str = "pricewnds",
    existing: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Lookup ETM prices for model/user-selected codes and merge into kac_map.

    Each item: ``{code, material, unit, resource_code?}``. Already-priced resource
    codes in ``existing`` are left untouched. Not configured → empty applied set.
    """
    base = dict(existing or {})
    pending: list[dict[str, Any]] = []
    resource_codes: dict[str, str] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or item.get("etm_code") or item.get("product_code") or "").strip()
        material = str(item.get("material") or item.get("name") or "").strip()
        unit = str(item.get("unit") or "").strip() or "шт"
        resource_code = str(item.get("resource_code") or "").strip()
        if resource_code and resource_code in base:
            continue
        if not code or not material:
            continue
        pending.append({"code": code, "material": material, "unit": unit})
        if resource_code:
            resource_codes[code] = resource_code
            resource_codes[material] = resource_code
    if not pending:
        return {
            "schema": "etm_kac_map_v1",
            "configured": configuration_status()["configured"],
            "kac_map": base,
            "applied": 0,
            "missing": 0,
            "quotes": {"schema": "etm_price_quotes_v1", "quotes": [], "rows": []},
        }
    active = client or get_client()
    quotes = active.collect_quotes(
        pending,
        code_type=code_type,
        manufacturer_code=manufacturer_code,
        price_field=price_field,
    )
    built = build_kac_map_from_quotes(quotes, resource_codes=resource_codes)
    merged = {**base, **built}
    priced_codes = {
        str(quote.get("product_code") or "").strip()
        for quote in (quotes.get("quotes") or [])
        if isinstance(quote, dict) and str(quote.get("product_code") or "").strip()
    }
    return {
        "schema": "etm_kac_map_v1",
        "configured": True,
        "supplier": "ЭТМ",
        "source_kind": "supplier_api",
        "kac_map": merged,
        "applied": len(priced_codes) or len(quotes.get("quotes") or []),
        "missing": int(quotes.get("missing") or 0),
        "quotes": quotes,
    }


def enrich_requirements_kac_map(
    requirements: list[dict[str, Any]],
    *,
    existing: dict[str, float] | None = None,
    client: EtmPriceClient | None = None,
) -> dict[str, Any]:
    """Pull ETM quotes for resolved/open KAC requirements that already carry an ETM code."""
    items: list[dict[str, Any]] = []
    for requirement in requirements or []:
        if not isinstance(requirement, dict):
            continue
        if str(requirement.get("kind") or "") != "kac":
            continue
        resolution = (
            dict(requirement.get("resolution") or {})
            if isinstance(requirement.get("resolution"), dict)
            else {}
        )
        etm_code = str(
            resolution.get("etm_code")
            or resolution.get("product_code")
            or requirement.get("etm_code")
            or ""
        ).strip()
        if not etm_code:
            continue
        if any(resolution.get(key) is not None for key in ("current_price", "price", "value")):
            continue
        items.append({
            "code": etm_code,
            "material": str(
                requirement.get("material")
                or requirement.get("name")
                or requirement.get("resource_name")
                or etm_code
            ).strip(),
            "unit": str(requirement.get("unit") or "шт").strip() or "шт",
            "resource_code": str(requirement.get("resource_code") or "").strip(),
        })
    if not items:
        return {
            "schema": "etm_kac_map_v1",
            "configured": configuration_status()["configured"],
            "kac_map": dict(existing or {}),
            "applied": 0,
            "missing": 0,
            "quotes": {"schema": "etm_price_quotes_v1", "quotes": [], "rows": []},
        }
    try:
        return fetch_kac_map_for_materials(items, client=client, existing=existing)
    except EtmNotConfiguredError:
        return {
            "schema": "etm_kac_map_v1",
            "configured": False,
            "kac_map": dict(existing or {}),
            "applied": 0,
            "missing": len(items),
            "quotes": {"schema": "etm_price_quotes_v1", "quotes": [], "rows": []},
            "reason": "etm_not_configured",
        }


_shared_lock = threading.Lock()
_shared_client: EtmPriceClient | None = None


def get_client() -> EtmPriceClient:
    global _shared_client
    with _shared_lock:
        if _shared_client is None:
            _shared_client = EtmPriceClient(EtmConfig.from_env())
        return _shared_client
