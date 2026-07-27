import json

from tools import local_inference_benchmark as benchmark
from tools import optiq_mtp_probe_server as probe


def test_percentile_uses_linear_interpolation():
    assert benchmark.percentile([1, 2, 3, 4, 5], 0.50) == 3
    assert benchmark.percentile([1, 2, 3, 4, 5], 0.95) == 4.8
    assert benchmark.percentile([], 0.50) is None


def test_usage_prefers_public_cached_tokens_and_keeps_mtplx_stats():
    usage, stats = benchmark._usage_and_stats(
        {
            "usage": {
                "prompt_tokens": 101,
                "completion_tokens": 17,
                "prompt_tokens_details": {"cached_tokens": 90},
            },
            "mtplx_stats": {"cached_tokens": 80, "decode_tok_s": 12.5},
        }
    )
    assert usage == {"prompt_tokens": 101, "completion_tokens": 17, "cached_tokens": 90}
    assert stats["decode_tok_s"] == 12.5


def test_summary_aggregates_mtp_acceptance_and_excludes_cold():
    rows = [
        {
            "ok": True,
            "profile": "throughput-1041x384",
            "sampler": "greedy",
            "stream": False,
            "phase": "cold",
            "decode_tps": 1.0,
        },
        {
            "ok": True,
            "profile": "throughput-1041x384",
            "sampler": "greedy",
            "stream": False,
            "phase": "warm",
            "decode_tps": 10.0,
            "prefill_tps": 100.0,
            "ttft_s": 1.0,
            "wall_s": 11.0,
            "cached_tokens": 0,
            "drafted_tokens": 10,
            "accepted_drafts": 6,
            "tool_call_ok": None,
        },
        {
            "ok": True,
            "profile": "throughput-1041x384",
            "sampler": "greedy",
            "stream": False,
            "phase": "warm",
            "decode_tps": 14.0,
            "prefill_tps": 120.0,
            "ttft_s": 0.8,
            "wall_s": 9.0,
            "cached_tokens": 100,
            "drafted_tokens": 10,
            "accepted_drafts": 8,
            "tool_call_ok": None,
        },
    ]
    summary = benchmark.summarize(rows)[0]
    assert summary["runs"] == 2
    assert summary["decode_tps_p50"] == 12.0
    assert summary["cached_tokens_max"] == 100.0
    assert summary["mtp_acceptance"] == 0.7


def test_profiles_cover_tool_call_and_changed_prefix_question():
    tool = benchmark.build_profile("tool-call")
    assert tool.expected_tool == "lookup_norm"
    assert tool.tools[0]["function"]["name"] == "lookup_norm"
    first = benchmark.build_profile("prefix-cache", prefix_variant=1)
    second = benchmark.build_profile("prefix-cache", prefix_variant=2)
    assert first.messages[0] == second.messages[0]
    assert first.messages[1] != second.messages[1]


def test_usage_can_arrive_in_final_stream_chunk_without_choices():
    usage, _ = benchmark._usage_and_stats(
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 4}}
    )
    assert usage["completion_tokens"] == 4


def test_samplers_are_explicit_and_reproducible():
    assert benchmark.SAMPLERS["greedy"] == {"temperature": 0.0}
    assert benchmark.SAMPLERS["production"]["top_k"] == 20


def test_probe_sampling_values_preserve_production_sampler():
    class Sampling:
        temperature = 0.7
        top_p = 0.8
        top_k = 20
        min_p = 0.0

    assert probe._sampling_values(Sampling()) == {
        "temperature": 0.7,
        "top_p": 0.8,
        "top_k": 20,
        "min_p": 0.0,
    }


def test_benchmark_reads_only_new_probe_telemetry(tmp_path):
    path = tmp_path / "telemetry.jsonl"
    path.write_text(json.dumps({"drafted_tokens": 1}) + "\n")
    offset = benchmark._telemetry_offset(path)
    with path.open("a") as handle:
        handle.write(json.dumps({"drafted_tokens": 20, "accepted_drafts": 11}) + "\n")
    assert benchmark._read_telemetry(path, offset) == {
        "drafted_tokens": 20,
        "accepted_drafts": 11,
    }
