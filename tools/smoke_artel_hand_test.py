"""Smoke-test ARTEL hand-test backend surface."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def request_json(base_url: str, path: str, payload: dict | None = None) -> dict | list:
    url = base_url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            if response.status != 200:
                raise RuntimeError(f"{path} returned HTTP {response.status}: {body[:300]}")
            return json.loads(body)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {error.code}: {body[:300]}") from error


def request_text(base_url: str, path: str) -> str:
    with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return response.read().decode("utf-8", errors="replace")


def smoke(base_url: str) -> None:
    html = request_text(base_url, "/")
    if "АРТЕЛЬ" not in html:
        raise RuntimeError("Root UI does not look like ARTEL")

    health = request_json(base_url, "/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"Unexpected health: {health}")

    les = request_json(base_url, "/api/integrations/les/status")
    if "status" not in les:
        raise RuntimeError(f"Unexpected LES status response: {les}")

    tasks = request_json(base_url, "/api/tasks")
    if not isinstance(tasks, list) or not tasks:
        raise RuntimeError("Tasks endpoint returned no seed tasks")

    catalog = request_json(base_url, "/api/catalog")
    if not isinstance(catalog, list) or not catalog:
        raise RuntimeError("Catalog endpoint returned no seed items")

    rag = request_json(
        base_url,
        "/api/tasks/task_0241/rag-context",
        {"datasetFilter": "CAD_BIM", "topK": 3, "includeTrace": True},
    )
    if rag.get("taskId") != "task_0241" or "status" not in rag:
        raise RuntimeError(f"Unexpected RAG context response: {rag}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test ARTEL hand-test backend surface.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5057")
    args = parser.parse_args(argv)

    smoke(args.base_url)
    print("ARTEL hand-test smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
