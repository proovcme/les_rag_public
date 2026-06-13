#!/usr/bin/env python3
"""Смоук доступа по ZeroTier-адресам — проверяет, что trusted-network пускает ВЕЗДЕ.

Запуск с любого устройства в ZT-сети (нужен Python 3, без зависимостей):
    python3 tools/zerotier_access_smoke.py --host 10.195.146.98
С сервера проверяет сам себя через ZT-интерфейс. Каждая строка: HTTP-код + URL.
Не-200 (кроме 401 на /login-редиректах) — кандидат на «не пускает», шлите вывод оператору Л.Е.С.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

MATRIX = [
    # W5.4/5.5: лайт-шеллы удалены — / и /les редиректят в NiceGUI (urlopen
    # следует за 307, итог 200 на trusted-сети). Мост /lite-api/* сохранён.
    ("UI: корень → /classic",  "http://{h}:8051/"),
    ("UI: /les → /les/classic","http://{h}:8051/les"),
    ("UI: NiceGUI чат",       "http://{h}:8051/classic"),
    ("UI: NiceGUI админка",   "http://{h}:8051/les/classic"),
    ("UI: M5",                "http://{h}:8051/m5"),
    ("мост: настройки",       "http://{h}:8051/lite-api/settings"),
    ("мост: сессии чата",     "http://{h}:8051/lite-api/chat/sessions?limit=1"),
    ("proxy: health",         "http://{h}:8050/api/health"),
    ("proxy: метрики",        "http://{h}:8050/api/metrics"),
    ("proxy: настройки",      "http://{h}:8050/api/settings"),
    ("визуализатор Qdrant",   "http://{h}:8066/"),
]


def probe(url: str, timeout: float = 8.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "les-zt-smoke"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as err:
        return err.code, ""
    except Exception as err:
        return 0, f"{type(err).__name__}: {err}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="ZeroTier-адрес сервера Л.Е.С., например 10.195.146.98")
    args = parser.parse_args()

    failures = 0
    print(f"# ZeroTier access smoke → {args.host}")
    for label, template in MATRIX:
        url = template.format(h=args.host)
        code, err = probe(url)
        ok = code == 200
        failures += 0 if ok else 1
        print(json.dumps({"ok": ok, "code": code, "what": label, "url": url, "error": err}, ensure_ascii=False))
    print(f"# итог: {'ВСЁ ПУСКАЕТ' if failures == 0 else f'ЗАБЛОКИРОВАНО {failures} из {len(MATRIX)}'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
