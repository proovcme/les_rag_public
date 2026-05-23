#!/usr/bin/env python3
"""Memory-guarded LES chat format smoke tests."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


FORMAT_PROMPTS = {
    "text": "",
    "spec": (
        "\n\nВЫВЕДИ ОТВЕТ В ФОРМАТЕ СПЕЦИФИКАЦИИ по форме ГОСТ 21.110-2013. "
        "Верни JSON-массив объектов. Обязательные поля: поз, обозначение, "
        "наименование, тип_марка, ед_изм, кол_во, масса_ед, примечание. "
        "Оберни в ```json ... ```"
    ),
    "schema": (
        "\n\nВЫВЕДИ ОТВЕТ В ВИДЕ JSON-ДЕРЕВА, глубина 3. "
        "Структура узла: {\"name\": str, \"children\": [...], \"desc\": str}. "
        "Оберни в ```json ... ```"
    ),
    "structure": "\n\nВЫВЕДИ ОТВЕТ В ВИДЕ СТРУКТУРИРОВАННОГО JSON-ОБЪЕКТА. Оберни в ```json ... ```",
    "table": "\n\nВЫВЕДИ ОТВЕТ В ВИДЕ ТАБЛИЦЫ: JSON-массив объектов. Оберни в ```json ... ```",
    "mermaid": (
        "\n\nВЫВЕДИ ОТВЕТ В ВИДЕ MERMAID-ДИАГРАММЫ типа flowchart TD. "
        "Оберни в ```mermaid ... ```. Пиши на русском, метки узлов короткие."
    ),
    "svg": (
        "\n\nВЫВЕДИ ОТВЕТ В ВИДЕ SVG-СХЕМЫ. Размер viewBox: 0 0 800 600. "
        "Оберни в ```svg ... ```"
    ),
    "template": (
        "\n\nОТВЕЧАЙ СТРОГО ПО СТРУКТУРЕ ОБРАЗЦА (JSON-массив).\n"
        "Образец:\n"
        "```json\n"
        "[{\"section_number\":\"1\",\"section_name\":\"Пояснительная записка\",\"basis\":\"Постановление 87\"}]\n"
        "```\n"
        "Оберни в ```json ... ```"
    ),
}

HEAVY_FORMATS = {"spec", "schema", "structure", "table", "mermaid", "svg", "template"}


@dataclass
class HttpResult:
    status: int
    body: str
    elapsed: float

    def json(self) -> dict[str, Any]:
        return json.loads(self.body or "{}")


def request(method: str, url: str, *, timeout: float, payload: dict[str, Any] | None = None) -> HttpResult:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HttpResult(resp.status, resp.read().decode("utf-8", errors="replace"), time.time() - started)
    except urllib.error.HTTPError as exc:
        return HttpResult(exc.code, exc.read().decode("utf-8", errors="replace"), time.time() - started)
    except OSError as exc:
        return HttpResult(0, str(exc), time.time() - started)


def get_json(url: str, timeout: float) -> dict[str, Any] | None:
    result = request("GET", url, timeout=timeout)
    if result.status != 200:
        return None
    try:
        return result.json()
    except json.JSONDecodeError:
        return None


def post_json(url: str, payload: dict[str, Any], timeout: float) -> HttpResult:
    return request("POST", url, timeout=timeout, payload=payload)


def memory_ok(args: argparse.Namespace) -> tuple[bool, str]:
    health = get_json(f"{args.mlx_url}/api/health", args.health_timeout)
    if not health:
        return False, "MLX health unavailable"
    mem = health.get("memory") or {}
    free = float(mem.get("ram_free_gb") or 0)
    swap = float(mem.get("swap_pct") or 100)
    if free < args.min_free_gb:
        return False, f"ram_free_gb={free} < {args.min_free_gb}"
    if swap > args.max_swap_pct:
        return False, f"swap_pct={swap} > {args.max_swap_pct}"
    return True, f"ram_free_gb={free}, swap_pct={swap}"


def qdrant_ok(args: argparse.Namespace) -> tuple[bool, str]:
    data = get_json(f"{args.qdrant_url}/collections/les_rag", args.health_timeout)
    if not data:
        return False, "Qdrant collection unavailable"
    result = data.get("result") or {}
    return True, f"points={result.get('points_count', '?')} status={result.get('status', '?')}"


def unload_all(args: argparse.Namespace) -> str:
    result = request("POST", f"{args.mlx_url}/api/unload_all", timeout=args.health_timeout, payload={})
    if result.status != 200:
        return f"unload_all HTTP {result.status}: {result.body[:160]}"
    return "unload_all ok"


def chat(args: argparse.Namespace, name: str, question: str, fmt: str) -> dict[str, Any]:
    payload = {
        "question": question + FORMAT_PROMPTS[fmt],
        "reranker_enabled": False,
        "session_id": f"chat-format-smoke-{int(time.time())}-{name}",
    }
    result = post_json(f"{args.proxy_url}/api/chat", payload, args.chat_timeout)
    item: dict[str, Any] = {
        "test": name,
        "format": fmt,
        "http": result.status,
        "sec": round(result.elapsed, 1),
    }
    try:
        data = result.json()
    except json.JSONDecodeError:
        item["error"] = result.body[:500]
        return item
    answer = data.get("answer", "")
    item.update(
        {
            "crag": data.get("crag_status"),
            "sources_count": len(data.get("sources") or []),
            "sources": (data.get("sources") or [])[:3],
            "answer_len": len(answer),
            "has_json_fence": "```json" in answer,
            "has_mermaid_fence": "```mermaid" in answer,
            "has_svg": "```svg" in answer or "<svg" in answer,
            "preview": answer[:500],
            "error": data.get("detail") or data.get("error"),
        }
    )
    return item


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-url", default="http://127.0.0.1:8050")
    parser.add_argument("--mlx-url", default="http://10.195.146.98:8080")
    parser.add_argument("--qdrant-url", default="http://10.195.146.98:6333")
    parser.add_argument("--chat-timeout", type=float, default=240)
    parser.add_argument("--health-timeout", type=float, default=10)
    parser.add_argument("--min-free-gb", type=float, default=6.0)
    parser.add_argument("--max-swap-pct", type=float, default=55.0)
    parser.add_argument("--cooldown-sec", type=float, default=20.0)
    parser.add_argument("--formats", default="text,spec,schema,structure,table,mermaid,svg,template")
    parser.add_argument("--stop-on-fail", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.proxy_url = args.proxy_url.rstrip("/")
    args.mlx_url = args.mlx_url.rstrip("/")
    args.qdrant_url = args.qdrant_url.rstrip("/")
    formats = [item.strip() for item in args.formats.split(",") if item.strip()]

    tests = [("evac_text", "ширина путей эвакуации", "text")]
    tests.extend((f"p87_{fmt}", "список разделов проектной документации по постановлению 87", fmt) for fmt in formats)

    failures = 0
    for index, (name, question, fmt) in enumerate(tests, start=1):
        mem_pass, mem_detail = memory_ok(args)
        q_pass, q_detail = qdrant_ok(args)
        preflight = {"test": name, "step": "preflight", "memory": mem_detail, "qdrant": q_detail}
        print(json.dumps(preflight, ensure_ascii=False), flush=True)
        if not mem_pass or not q_pass:
            print(json.dumps({"test": name, "step": "stopped", "reason": "preflight failed"}, ensure_ascii=False), flush=True)
            return 2

        result = chat(args, name, question, fmt)
        ok = result.get("http") == 200 and bool(result.get("crag"))
        if fmt in {"spec", "schema", "structure", "table", "template"}:
            ok = ok and bool(result.get("has_json_fence"))
        elif fmt == "mermaid":
            ok = ok and bool(result.get("has_mermaid_fence"))
        elif fmt == "svg":
            ok = ok and bool(result.get("has_svg"))
        result["ok"] = ok
        print(json.dumps(result, ensure_ascii=False), flush=True)
        failures += 0 if ok else 1
        if failures and args.stop_on_fail:
            return 1

        if fmt in HEAVY_FORMATS:
            print(json.dumps({"test": name, "step": "unload", "detail": unload_all(args)}, ensure_ascii=False), flush=True)
        if index < len(tests):
            time.sleep(args.cooldown_sec)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
