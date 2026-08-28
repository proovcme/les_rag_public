import hashlib
import json
from pathlib import Path

import pytest

from tools.live_workbook_acceptance import (
    AcceptanceConfig,
    LiveAcceptanceError,
    run_acceptance,
    validate_report,
)


def _revision(*, revision_id: str, revision_no: int, sha256: str, parent_revision_id: str | None) -> dict:
    return {
        "artifact_id": "art_123",
        "revision_id": revision_id,
        "revision_no": revision_no,
        "parent_revision_id": parent_revision_id,
        "sha256": sha256,
        "download_sha256": sha256,
        "byte_size": 8,
        "source_scope": ["attachment:read_123456abcdef"],
        "profile_revision_id": "profile:7",
        "model_identity": "qwen3.5:9b",
        "model_preset": "qwen-9b-restrictive",
        "decision_checkpoint_id": f"cp-{revision_no}",
        "missing_count": 0,
        "blocker_count": 0,
    }


@pytest.fixture
def report() -> dict:
    first_hash = hashlib.sha256(b"revision").hexdigest()
    second_hash = hashlib.sha256(b"revision-2").hexdigest()
    return {
        "schema": "les.live_workbook_acceptance.v1",
        "evidence_kind": "live_runtime",
        "runtime": {
            "profile_revision_id": "profile:7",
            "model_preset": "qwen-9b",
            "observed_model_preset": "qwen-9b-restrictive",
            "model_identity": "qwen3.5:9b",
        },
        "attachment": {
            "attachment_id": "read_123456abcdef",
            "sha256": hashlib.sha256(b"source").hexdigest(),
        },
        "revision_1": _revision(
            revision_id="rev_1", revision_no=1, sha256=first_hash, parent_revision_id=None,
        ),
        "revision_2": _revision(
            revision_id="rev_2", revision_no=2, sha256=second_hash, parent_revision_id="rev_1",
        ),
        "elapsed_seconds": 1.25,
    }


def test_acceptance_report_requires_live_runtime_identity():
    with pytest.raises(ValueError, match="live_runtime"):
        validate_report({"evidence_kind": "synthetic_fixture"})


def test_acceptance_requires_two_immutable_revisions(report):
    validate_report(report)
    assert report["revision_1"]["sha256"] != report["revision_2"]["sha256"]
    assert report["revision_2"]["parent_revision_id"] == report["revision_1"]["revision_id"]


def test_acceptance_report_rejects_unredacted_runtime_data(report):
    report["runtime"]["authorization"] = "Bearer secret"

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_rejects_source_path_embedded_in_blocker(report):
    report["revision_1"]["blockers"] = ["adapter wrote C:\\private\\source.xlsx"]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_rejects_traceback_or_prompt_dump_in_blockers(report):
    report["revision_1"]["blockers"] = ["Traceback (most recent call last): prompt dump"]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_rejects_embedded_auth_or_relative_source_path(report):
    report["revision_1"]["blockers"] = ["token=supersecret", "data/source.xlsx"]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_rejects_generic_relative_source_paths(report):
    report["revision_1"]["blockers"] = [
        "./source.xlsx",
        "..\\source.xlsx",
        "workspace\\source.xlsx",
        "source.xlsx",
    ]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_report_allows_structured_identifiers_with_dots(report):
    report["revision_1"]["artifact_id"] = "artifact.v1"
    report["revision_1"]["revision_id"] = "revision.1"
    report["revision_2"]["parent_revision_id"] = "revision.1"

    validate_report(report)


def test_acceptance_report_rejects_even_safe_looking_raw_status_arrays(report):
    report["revision_1"]["missing"] = ["id.with.dots"]
    report["revision_1"]["blockers"] = ["status.code"]

    with pytest.raises(ValueError, match="redacted"):
        validate_report(report)


def test_acceptance_rejects_fixture_path_before_any_live_request(tmp_path):
    fixture = tmp_path / "tests" / "fixtures" / "representative.xlsx"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"not live input")
    config = AcceptanceConfig(
        attachment=fixture,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match="tests/fixtures"):
        run_acceptance(config, client=object())


class _FakeResponse:
    def __init__(self, *, payload=None, content=b"", lines=()):
        self._payload = payload
        self.content = content
        self._lines = list(lines)

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_lines(self):
        return iter(self._lines)


class _FakeHttpClient:
    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []
        self._first = b"revision"
        self._second = b"revision-2"

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        if url.endswith("/api/chat/attachments"):
            return _FakeResponse(payload={
                "attachment_id": "read_123456abcdef",
                "sha256": hashlib.sha256(b"source").hexdigest(),
            })
        if url.endswith("/api/chat/stream"):
            body = kwargs["json"]
            second = "rev_1" in body["question"]
            revision_id = "rev_2" if second else "rev_1"
            payload = {
                "artifact": {
                    "artifact_id": "art_123",
                    "revision_id": revision_id,
                    "revision_no": 2 if second else 1,
                    "parent_revision_id": "rev_1" if second else None,
                    "sha256": hashlib.sha256(self._second if second else self._first).hexdigest(),
                    "byte_size": len(self._second if second else self._first),
                    "source_scope": ["attachment:read_123456abcdef"],
                    "profile_revision_id": "profile:7",
                    "model_identity": "qwen3.5:9b",
                    "model_preset": "qwen-9b",
                    "decision_checkpoint_id": "cp-2" if second else "cp-1",
                    "missing": [],
                    "blockers": [],
                },
                "attachment_retry": {"attachment_id": "read_123456abcdef"},
                "checkpoint": {"checkpoint_id": "cp-2" if second else "cp-1", "status": "complete"},
                "source": {
                    "attachment_id": "read_123456abcdef",
                    "sha256": hashlib.sha256(b"source").hexdigest(),
                },
                "model_connection": {"model_id": "qwen3.5:9b"},
            }
            return _FakeResponse(lines=("event: final", f"data: {json.dumps(payload)}", ""))
        if url.endswith("/api/artifacts/rev_1") or url.endswith("/api/artifacts/rev_2"):
            second = url.endswith("rev_2")
            payload = {
                "artifact_id": "art_123",
                "revision_id": "rev_2" if second else "rev_1",
                "revision_no": 2 if second else 1,
                "parent_revision_id": "rev_1" if second else None,
                "sha256": hashlib.sha256(self._second if second else self._first).hexdigest(),
                "byte_size": len(self._second if second else self._first),
                "source_scope": ["attachment:read_123456abcdef"],
                "profile_revision_id": "profile:7",
                "model_identity": "qwen3.5:9b",
                "model_preset": "qwen-9b-restrictive",
                "decision_checkpoint_id": "cp-2" if second else "cp-1",
                "missing": [],
                "blockers": [],
            }
            return _FakeResponse(payload=payload)
        if url.endswith("/api/artifacts/rev_1/download"):
            return _FakeResponse(content=self._first)
        if url.endswith("/api/artifacts/rev_2/download"):
            return _FakeResponse(content=self._second)
        raise AssertionError(f"unexpected request: {method} {url}")


def test_acceptance_uses_public_boundaries_and_redacts_receipt(tmp_path):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050/",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key="test-secret",
    )

    report = run_acceptance(config, client=client)

    validate_report(report)
    methods_urls = [(method, url) for method, url, _ in client.requests]
    assert methods_urls == [
        ("POST", "http://127.0.0.1:8050/api/chat/attachments"),
        ("POST", "http://127.0.0.1:8050/api/chat/stream"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_1"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_1/download"),
        ("POST", "http://127.0.0.1:8050/api/chat/stream"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_2"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_2/download"),
    ]
    first_chat = client.requests[1][2]["json"]
    second_chat = client.requests[4][2]["json"]
    assert first_chat["attachment_id"] == second_chat["attachment_id"] == "read_123456abcdef"
    assert first_chat["candidate_acceptance"] is True
    assert second_chat["candidate_acceptance"] is True
    assert "rev_1" in second_chat["question"]
    serialized = json.dumps(report)
    assert str(source) not in serialized
    assert "test-secret" not in serialized
    assert "Authorization" not in serialized
