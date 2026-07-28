#!/usr/bin/env python3
"""Launch OptiQ with diagnostic fixes kept outside the LES runtime.

The wrapper is intentionally not a production server.  It corrects three
mlx-optiq 0.3.3 serving blind spots so an isolated benchmark can be trusted:

* MTP requests are forced off mlx-lm's batch path even without ``seed``;
* request sampling arguments are forwarded to ``OptiqEngine``;
* per-request MTP acceptance and MLX memory telemetry are appended as JSONL.

Run this file with the isolated OptiQ interpreter and pass normal ``optiq``
CLI arguments, beginning with ``serve``.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator


TELEMETRY_ENV = "LES_OPTIQ_TELEMETRY_JSONL"
_REQUEST = threading.local()


def _sampling_values(sampling: Any) -> dict[str, float | int]:
    return {
        "temperature": float(getattr(sampling, "temperature", 0.0)),
        "top_p": float(getattr(sampling, "top_p", 0.0)),
        "top_k": int(getattr(sampling, "top_k", 0) or 0),
        "min_p": float(getattr(sampling, "min_p", 0.0)),
    }


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, line)
    finally:
        os.close(descriptor)


def install_patches() -> None:
    import mlx.core as mx
    import mlx_lm.server as server
    from optiq.runtime.engine import OptiqEngine

    telemetry_path = Path(os.environ.get(TELEMETRY_ENV, "/tmp/les-optiq-mtp-telemetry.jsonl"))

    original_load = server.ModelProvider.load

    def single_path_load(self, *args, **kwargs):
        result = original_load(self, *args, **kwargs)
        self.is_batchable = False
        return result

    server.ModelProvider.load = single_path_load

    original_serve_single = server.ResponseGenerator._serve_single

    def serve_single_with_request_context(self, request_tuple):
        _queue, _request, arguments = request_tuple
        _REQUEST.sampling = arguments.sampling
        _REQUEST.seed = arguments.seed
        try:
            return original_serve_single(self, request_tuple)
        finally:
            _REQUEST.sampling = None
            _REQUEST.seed = None

    server.ResponseGenerator._serve_single = serve_single_with_request_context

    original_generate_stream = OptiqEngine.generate_stream

    def measured_generate_stream(self, *args, **kwargs) -> Iterator[dict[str, Any]]:
        sampling = getattr(_REQUEST, "sampling", None)
        values = _sampling_values(sampling)
        kwargs.update(values)
        before_active = int(mx.get_active_memory())
        before_cache = int(mx.get_cache_memory())
        mx.reset_peak_memory()
        started = time.perf_counter()
        generated = 0
        accepted_events = 0
        last_event: dict[str, Any] = {}
        try:
            for event in original_generate_stream(self, *args, **kwargs):
                generated += 1
                accepted_events += int(bool(event.get("from_draft")))
                last_event = event
                yield event
        finally:
            elapsed = time.perf_counter() - started
            stats = getattr(self, "_last_stats", None)
            drafted = int(getattr(stats, "drafts_attempted", 0) or 0)
            accepted = int(getattr(stats, "drafts_accepted", 0) or 0)
            payload = {
                "schema": "les_optiq_mtp_probe_v1",
                "generated_tokens": generated,
                "generation_wall_tok_s": generated / elapsed if elapsed > 0 else 0.0,
                "decode_tok_s": float(last_event.get("decode_tps") or 0.0),
                "prefill_time_s": float(last_event.get("prefill_time_s") or 0.0),
                "prefill_tok_s": (
                    int(last_event.get("prompt_tokens") or 0)
                    / max(float(last_event.get("prefill_time_s") or 0.0), 1e-6)
                ),
                "drafted_tokens": drafted,
                "accepted_drafts": accepted,
                "accepted_draft_events": accepted_events,
                "mtp_acceptance": accepted / drafted if drafted else None,
                "speculation_cycles": int(getattr(stats, "speculation_cycles", 0) or 0),
                "generation_mode": "MTP" if drafted else "AR",
                "mtp_depth": int(getattr(stats, "depth", 0) or 0),
                "peak_memory_bytes": int(mx.get_peak_memory()),
                "active_memory_before_bytes": before_active,
                "active_memory_after_bytes": int(mx.get_active_memory()),
                "cache_memory_before_bytes": before_cache,
                "cache_memory_after_bytes": int(mx.get_cache_memory()),
                "seed": getattr(_REQUEST, "seed", None),
                **values,
            }
            _append_jsonl(telemetry_path, payload)

    OptiqEngine.generate_stream = measured_generate_stream


def main() -> int:
    install_patches()
    from optiq.cli import cli

    cli(prog_name="optiq-probe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
