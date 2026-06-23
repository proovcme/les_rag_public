"""ГЭСН-2022 из API cs.smetnoedelo.ru: код → состав нормы (расход) → кеш в базу. 0 LLM.

API v2.0: GET api.smetnoedelo.ru/cs/?token=&base=gesn2&code= → JSON {CODE, NAME, COMPOSITION.RESOURCES
[{CODE,NAME,QUAN,UNIT}], REQUESTS{USED,BALANCE}}. Сверено на эталоне (12-01-034-02): расход совпал
с семенем (труд 12.94, краны 0.97/0.01, гвозди 0.0015, бруски 0.4).

КВОТА мала (≈100 запросов) → НЕ bulk-краул, а **on-demand + кеш**: код встретился — дёрнули раз,
закешировали в `data/gesn_base/gesn2022.parquet` (схема gesn_import) → дальше gesn_service берёт оттуда.

Токен — СЕКРЕТ: env `LES_SMETNOE_TOKEN` (в гит/код не кладём). Сеть прямая (API не за гео-блоком);
опц. через VPS: env `LES_SMETNOE_VIA_SSH=root@host` (для не-РФ egress).

Маппинг ресурса → kind: UNIT «чел.-ч» → machinist (если «машинист»/CODE=2) иначе labor; «маш.-ч» →
machine; прочее (м3/т/…) → material. Цена машин/материалов резолвится по code из ФГИС ЦС в сборке;
ставка ОЗП/ОТм (по разряду) — отдельный тариф (в норме её нет).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Optional

API_URL = "https://api.smetnoedelo.ru/cs/"
DEFAULT_BASE = "gesn2"   # ГЭСН-2022 строительные
CACHE_PARQUET = Path("data/gesn_base/gesn2022.parquet")
RESOURCE_FIELDS = ["norm_code", "norm_name", "norm_unit", "kind", "per_unit",
                   "resource_code", "resource_name", "resource_unit", "price"]


def _token() -> str:
    t = os.getenv("LES_SMETNOE_TOKEN", "").strip()
    if not t:
        raise RuntimeError("нет токена: задайте env LES_SMETNOE_TOKEN (cs.smetnoedelo.ru)")
    return t


def _f(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _kind(res: dict) -> str:
    unit = (res.get("UNIT") or "").lower()
    name = (res.get("NAME") or "").lower()
    code = str(res.get("CODE") or "").strip()
    if "чел" in unit:
        return "machinist" if ("машинист" in name or code == "2") else "labor"
    if "маш" in unit:
        return "machine"
    return "material"


def _unit_from_name(name: str) -> str:
    m = re.search(r"[—–-]\s*([^—–-]+?)\s*$", name or "")
    return m.group(1).strip() if m else ""


def map_norm(payload: dict) -> dict[str, Any]:
    """JSON ответа API → норма {code, name, unit, resources:[{kind,name,unit,per_unit,code}]}."""
    import html

    code = re.sub(r"^ГЭСН\w*\s*", "", str(payload.get("CODE") or "").strip(), flags=re.I).strip()
    name = html.unescape(payload.get("NAME") or payload.get("BASE_NAME") or "")   # &mdash; → —
    resources: list[dict[str, Any]] = []
    for r in (payload.get("COMPOSITION") or {}).get("RESOURCES", []) or []:
        resources.append({
            "kind": _kind(r),
            "name": r.get("NAME", ""),
            "unit": r.get("UNIT", ""),
            "per_unit": _f(r.get("QUAN")),
            "code": (r.get("CODE") or None),
        })
    return {"code": code, "name": name, "unit": _unit_from_name(name), "resources": resources}


def fetch_raw(*, code: str | None = None, section: str | None = None, base: str = DEFAULT_BASE) -> dict:
    q = f"token={_token()}&base={base}"
    if code:
        q += f"&code={code}"
    if section:
        q += f"&section={section}"
    url = f"{API_URL}?{q}"
    via = os.getenv("LES_SMETNOE_VIA_SSH", "").strip()   # опц. egress через VPS
    if via:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", via, f"curl -sS -m 25 '{url}'"],
            capture_output=True, text=True, timeout=45,
        ).stdout
        return json.loads(out)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_norm(code: str, *, base: str = DEFAULT_BASE) -> dict[str, Any]:
    """Один код → норма (с остатком квоты в `_balance`). Тратит 1 запрос."""
    payload = fetch_raw(code=code, base=base)
    norm = map_norm(payload)
    norm["_balance"] = (payload.get("REQUESTS") or {}).get("BALANCE")
    return norm


def cache_norms(norms: list[dict], *, parquet_path: str | Path = CACHE_PARQUET) -> int:
    """Нормы → строки-ресурсы → parquet-база (схема gesn_import). Перезаписывает по совпадению кода."""
    import pandas as pd

    rows: list[dict[str, Any]] = []
    for n in norms:
        for r in n.get("resources", []) or []:
            rows.append({
                "norm_code": n["code"], "norm_name": n.get("name", ""), "norm_unit": n.get("unit", ""),
                "kind": r.get("kind"), "per_unit": r.get("per_unit"), "resource_code": r.get("code"),
                "resource_name": r.get("name", ""), "resource_unit": r.get("unit", ""), "price": r.get("price"),
            })
    if not rows:
        return 0
    df = pd.DataFrame(rows, columns=RESOURCE_FIELDS)
    p = Path(parquet_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = pd.read_parquet(p)
        old = old[~old["norm_code"].isin(set(df["norm_code"]))]   # вытеснить старые версии этих кодов
        df = pd.concat([old, df], ignore_index=True)
    df.to_parquet(p, index=False)
    try:   # сбросить кеш чтения базы в gesn_service
        from proxy.services import gesn_service
        gesn_service.load_base_norms.cache_clear()
    except Exception:
        pass
    return len(rows)


def fetch_and_cache(code: str, *, base: str = DEFAULT_BASE,
                    parquet_path: str | Path = CACHE_PARQUET) -> dict[str, Any]:
    """Дёрнуть код из API и положить в базу. Возвращает {code, resources, balance}."""
    norm = fetch_norm(code, base=base)
    n = cache_norms([norm], parquet_path=parquet_path)
    return {"code": norm["code"], "name": norm.get("name"), "resources": n,
            "balance": norm.get("_balance")}
