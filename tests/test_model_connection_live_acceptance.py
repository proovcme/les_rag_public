from __future__ import annotations

import pytest
from types import SimpleNamespace

from proxy.services.openai_compatible_transport_service import (
    InferenceEvent,
    InferenceResponse,
)
from tools.model_connection_live_acceptance import (
    build_receipt,
    exercise_connection,
    parse_args,
)


def _case(name: str, marker: str) -> dict[str, object]:
    return {
        "name": name,
        "passed": True,
        "elapsed_ms": 12,
        "evidence_sha256": marker * 64,
    }


def test_receipt_binds_exact_runtime_revision_snapshot_preset_and_model() -> None:
    receipt = build_receipt(
        source_commit="a" * 40,
        build_number=625,
        connection_revision_id="conn:qwen:r2",
        capability_snapshot_id="cap:qwen:s4",
        preset_id="qwen-9b-restrictive",
        observed_model_identity="qwen3.5:9b",
        cases=(
            _case("chat", "1"),
            _case("stream", "2"),
            _case("tools", "3"),
            _case("context", "4"),
        ),
        transport_kind="live_http",
    )

    assert receipt["passed"] is True
    assert receipt["connection_revision_id"] == "conn:qwen:r2"
    assert receipt["capability_snapshot_id"] == "cap:qwen:s4"
    assert receipt["preset_id"] == "qwen-9b-restrictive"
    assert receipt["observed_model_identity"] == "qwen3.5:9b"
    assert len(receipt["acceptance_sha256"]) == 64
    assert "answer_text" not in str(receipt)


def test_mock_or_incomplete_evidence_cannot_issue_passing_receipt() -> None:
    complete_cases = (
        _case("chat", "1"),
        _case("stream", "2"),
        _case("tools", "3"),
        _case("context", "4"),
    )
    common = {
        "source_commit": "a" * 40,
        "build_number": 625,
        "connection_revision_id": "conn:qwen:r2",
        "capability_snapshot_id": "cap:qwen:s4",
        "preset_id": "qwen-9b-restrictive",
        "observed_model_identity": "qwen3.5:9b",
    }

    with pytest.raises(ValueError, match="LIVE_EVIDENCE_REQUIRED"):
        build_receipt(**common, cases=complete_cases, transport_kind="mock")

    with pytest.raises(ValueError, match="LIVE_CASES_INCOMPLETE"):
        build_receipt(
            **common,
            cases=complete_cases[:-1],
            transport_kind="live_http",
        )


def test_receipt_does_not_require_models_endpoint_case_for_protected_proxy() -> None:
    receipt = build_receipt(
        source_commit="b" * 40,
        build_number=625,
        connection_revision_id="conn:protected:r1",
        capability_snapshot_id="cap:protected:s1",
        preset_id="qwen-35b-extended",
        observed_model_identity="andrevp/Qwen3.6-35B-A3B-3bit-MLX",
        cases=(
            _case("chat", "1"),
            _case("stream", "2"),
            _case("tools", "3"),
            _case("context", "4"),
        ),
        transport_kind="live_http",
    )

    assert [case["name"] for case in receipt["cases"]] == [
        "chat",
        "stream",
        "tools",
        "context",
    ]


class _AcceptanceTransport:
    async def complete(self, _connection, request):
        if request.tools:
            return InferenceResponse(
                text="",
                tool_calls=(
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "les_acceptance_ping",
                            "arguments": "{}",
                        },
                    },
                ),
                finish_reason="tool_calls",
                usage={"total_tokens": 8},
                model_id="qwen-live",
            )
        return InferenceResponse(
            text="sensitive answer",
            tool_calls=(),
            finish_reason="stop",
            usage={"total_tokens": 6},
            model_id="qwen-live",
        )

    async def stream(self, _connection, _request):
        yield InferenceEvent(kind="text_delta", text="secret", model_id="qwen-live")
        yield InferenceEvent(
            kind="finish",
            finish_reason="stop",
            model_id="qwen-live",
        )


@pytest.mark.asyncio
async def test_exercise_hashes_live_outputs_without_persisting_answer_text() -> None:
    connection = SimpleNamespace(
        model_id="qwen-live",
        effective_preset=SimpleNamespace(
            preset_id="qwen-9b-restrictive",
            input_token_limit=8192,
            max_output_tokens=1024,
        ),
    )

    evidence = await exercise_connection(connection, _AcceptanceTransport())

    assert [case["name"] for case in evidence] == [
        "chat",
        "stream",
        "tools",
        "context",
    ]
    assert all(case["passed"] is True for case in evidence)
    assert "sensitive answer" not in str(evidence)
    assert "secret" not in str(evidence)


def test_cli_accepts_exact_revisions_and_no_plaintext_secret_argument(tmp_path) -> None:
    config = parse_args(
        [
            "--revision-9b",
            "conn:qwen9:r2",
            "--revision-35b",
            "conn:qwen35:r4",
            "--out",
            str(tmp_path / "receipt.json"),
        ]
    )

    assert config.revision_9b == "conn:qwen9:r2"
    assert config.revision_35b == "conn:qwen35:r4"
    assert config.out == tmp_path / "receipt.json"
