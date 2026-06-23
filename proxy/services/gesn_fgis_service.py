"""ГЭСН-2022 из ОФИЦИАЛЬНОГО ФГИС ЦС (fgiscs.minstroyrf.ru) — БЕЗ квоты/auth. База как есть. 0 LLM.

`GET /api/FullTextSearch/SearchEstimatedRates?search=<код>` → структурный JSON расхода нормы(норм).
Это авторитетный бесплатный источник (Приказ 1046/пр) — основной on-demand: код встретился →
дёрнули, закешировали в `data/gesn_base/gesn2022.parquet`. smetnoedelo остаётся для апдейтов/резерва.

Парс/запись переиспользуют `tools.gesn_pdf_import` (parse_fgis_json/build_parquet, схема gesn_import,
эталон 12-01-034-02 воспроизводится ТОЧНО). Сеть прямая (API доступен и из не-РФ); опц. через VPS
egress: env `LES_FGIS_VIA_SSH=root@host`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API = "https://fgiscs.minstroyrf.ru/api/FullTextSearch/SearchEstimatedRates?search="
CACHE_PARQUET = Path("data/gesn_base/gesn2022.parquet")

# Труд рабочих в ФГИС идёт как «Средний разряд работы N,M» БЕЗ кода → выводим тарифный код
# `1-100-NM` (эталон: разряд 2,5 → 1-100-25), который есть в Сплит-форме ФГИС ЦС → цена ОЗП.
_RAZRYAD_RE = re.compile(r"разряд\D*(\d)[.,](\d)")


def _is_real_code(code: Any) -> bool:
    s = str(code or "").strip()
    return bool(s) and s not in {"—", "-", "1", "2"} and bool(re.search(r"\d", s)) and ("-" in s or "." in s)


def _derive_labor_code(name: Any) -> str | None:
    m = _RAZRYAD_RE.search(str(name or "").lower())
    return f"1-100-{m.group(1)}{m.group(2)}" if m else None


def _fetch_raw(code: str) -> list[dict[str, Any]]:
    url = API + urllib.parse.quote(str(code), safe="")
    via = os.getenv("LES_FGIS_VIA_SSH", "").strip()
    if via:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12", via, f"curl -sS -m 25 '{url}'"],
            capture_output=True, text=True, timeout=45,
        ).stdout
        data = json.loads(out)
    else:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    if isinstance(data, list):
        return data
    return data.get("data") or data.get("items") or []


def fetch_and_cache(code: str, *, parquet_path: str | Path = CACHE_PARQUET) -> dict[str, Any]:
    """Дёрнуть норму(ы) из ФГИС ЦС по коду и дописать в базу. Без квоты. Возвращает сводку."""
    from proxy.services import gesn_service
    from tools.gesn_pdf_import import build_parquet, parse_fgis_json

    records = _fetch_raw(code)
    rows = parse_fgis_json(records)
    if not rows:
        return {"ok": False, "code": code, "source": "fgis", "note": "не найдено в ФГИС ЦС"}
    # ставка труда по разряду: ОЗП-строкам без кода присваиваем тарифный 1-100-NM (ценится ФГИС ЦС)
    for r in rows:
        if r.get("kind") == "labor" and not _is_real_code(r.get("resource_code")):
            dc = _derive_labor_code(r.get("resource_name"))
            if dc:
                r["resource_code"] = dc
    summary = build_parquet(rows, parquet_path, append=True)   # дедуп по norm_code в build_parquet
    try:
        gesn_service.load_base_norms.cache_clear()
    except Exception:
        pass
    return {"ok": True, "code": code, "source": "fgis",
            "norms": summary.get("norms"), "resources": summary.get("resources")}
