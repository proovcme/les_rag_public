"""Управление Совушкой из терминала — пишем ей, ответ приходит в терминал И
дублируется в историю чата Совушки (session 'terminal' по умолчанию).

Это harness-доступ к мозгу Совушки: тот же путь, что у чат-окна (/api/chat),
поэтому ответ, источники и запись истории — настоящие, видны оператору в UI
(вкладка ИСТОРИЯ, фильтр по сессии). Для verify-сканов используй verify-режим:
сообщение «проверь объёмы <путь>» уйдёт в /api/verify/extract и вернёт таблицу.

    uv run python tools/sovushka_say.py "сколько лотков ДКС в каталоге?"
    uv run python tools/sovushka_say.py "проверь объёмы /путь/скан.pdf стр 1"
    uv run python tools/sovushka_say.py --session bot1 "..."
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.request


def _proxy() -> str:
    return os.getenv("PROXY_URL", "http://127.0.0.1:8050").rstrip("/")


def _post(path: str, payload: dict, timeout: float = 300.0) -> dict:
    req = urllib.request.Request(
        _proxy() + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _verify_path(q: str) -> str | None:
    m = re.search(r"(/.+\.(?:pdf|png|tif|tiff|jpe?g))", q or "", re.IGNORECASE)
    return m.group(1).strip() if m else None


def _verify_page(q: str) -> int:
    m = re.search(r"(?:стр\.?|страниц\w*|page)\s*(\d+)", q or "", re.IGNORECASE)
    return max(0, int(m.group(1)) - 1) if m else 0


def _is_verify(q: str) -> bool:
    ql = (q or "").casefold()
    kw = ("провер" in ql or "свер" in ql or "верифиц" in ql) and (
        "объём" in ql or "объем" in ql or "скан" in ql or "таблиц" in ql
    )
    return bool(kw and _verify_path(q))


def say(message: str, session: str = "terminal", dataset: str | None = None) -> dict:
    # verify-сканов: tool-путь (как в чат-UI), не LLM
    if _is_verify(message):
        return {
            "verify": True,
            **_post("/api/verify/extract", {
                "path": _verify_path(message), "page": _verify_page(message), "engine": "local",
            }),
        }
    payload: dict = {"question": message, "validation_enabled": False, "session_id": session}
    if dataset:
        payload["dataset_filter"] = dataset
    return _post("/api/chat", payload)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Написать Совушке из терминала (дублируется в историю чата).")
    ap.add_argument("message", help="сообщение Совушке")
    ap.add_argument("--session", default="terminal", help="ID сессии (группирует в истории)")
    ap.add_argument("--dataset", default=None, help="фильтр по датасету")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    res = say(args.message, args.session, args.dataset)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if res.get("verify"):
        rows = res.get("rows") or []
        print(f"[VERIFY] {len(rows)} строк, columns={res.get('columns')}, token={res.get('token')}")
        for row in rows[:8]:
            print("  ", json.dumps(row, ensure_ascii=False))
        print("\n[артефакт сверки открывается в чате Совушки командой «проверь объёмы <путь>»]")
        return 0

    print(res.get("answer") or res.get("response") or "(нет ответа)")
    srcs = res.get("sources") or []
    hid = res.get("history_id")
    print(f"\n[источников: {len(srcs)} | session={args.session}"
          + (f" | history_id={hid} — видно в Совушке: ИСТОРИЯ" if hid else "") + "]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
