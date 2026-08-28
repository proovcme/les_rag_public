import hashlib
import json
from io import BytesIO
from pathlib import Path

import openpyxl
import pytest

from tools.live_workbook_acceptance import (
    AcceptanceConfig,
    CONTRACT_TEST,
    LiveAcceptanceError,
    exercise_contract,
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
            "source_commit": "6b4952d9",
            "build_number": 622,
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

    with pytest.raises(ValueError, match="redacted|unknown"):
        validate_report(report)


@pytest.mark.parametrize("field", ["access_token", "raw_prompt", "unexpected"])
def test_acceptance_report_rejects_unknown_structured_fields(report, field):
    report["runtime"][field] = "value"

    with pytest.raises(ValueError, match="unknown"):
        validate_report(report)


def test_acceptance_report_rejects_source_path_embedded_in_blocker(report):
    report["revision_1"]["blockers"] = ["adapter wrote C:\\private\\source.xlsx"]

    with pytest.raises(ValueError, match="redacted|unknown"):
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

    with pytest.raises(ValueError, match="redacted|unknown"):
        validate_report(report)


@pytest.mark.parametrize(
    ("field", "value"),
    (("build_number", True), ("revision_no", True), ("source_scope", [1]), ("elapsed_seconds", float("nan"))),
)
def test_acceptance_report_rejects_wrong_allowed_field_types(report, field, value):
    target = report["runtime"] if field == "build_number" else report["revision_1"]
    if field == "elapsed_seconds":
        target = report
    target[field] = value

    with pytest.raises(ValueError, match="invalid|must contain"):
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
        exercise_contract(config, client=object())


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


def _xlsx_bytes(value: str) -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Acceptance"
    worksheet.append(["status"])
    worksheet.append([value])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


class _FakeHttpClient:
    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []
        self._first = _xlsx_bytes("revision")
        self._second = _xlsx_bytes("revision-2")

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url, kwargs))
        if url.endswith("/api/version"):
            return _FakeResponse(payload={"git_commit": "6b4952d9", "build_number": 622})
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
            checkpoint_id = "cp-2" if second else "cp-1"
            return _FakeResponse(lines=(
                "event: tool_progress",
                f"data: {json.dumps({'checkpoint_id': checkpoint_id, 'completed': 1, 'total': 1})}",
                "",
                "event: final",
                f"data: {json.dumps(payload)}",
                "",
            ))
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


def test_contract_exercise_uses_public_boundaries_without_live_receipt(tmp_path):
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

    report = exercise_contract(config, client=client)

    validate_report(report, expected_evidence_kind=CONTRACT_TEST)
    assert not config.out.exists()
    assert report["evidence_kind"] == CONTRACT_TEST
    methods_urls = [(method, url) for method, url, _ in client.requests]
    assert methods_urls == [
        ("GET", "http://127.0.0.1:8050/api/version"),
        ("POST", "http://127.0.0.1:8050/api/chat/attachments"),
        ("POST", "http://127.0.0.1:8050/api/chat/stream"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_1"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_1/download"),
        ("POST", "http://127.0.0.1:8050/api/chat/stream"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_2"),
        ("GET", "http://127.0.0.1:8050/api/artifacts/rev_2/download"),
    ]
    first_chat = client.requests[2][2]["json"]
    second_chat = client.requests[5][2]["json"]
    assert client.requests[1][2]["data"] == {"candidate_acceptance": "true"}
    assert first_chat["attachment_id"] == second_chat["attachment_id"] == "read_123456abcdef"
    assert first_chat["candidate_acceptance"] is True
    assert second_chat["candidate_acceptance"] is True
    assert "rev_1" in second_chat["question"]
    serialized = json.dumps(report)
    assert str(source) not in serialized
    assert "test-secret" not in serialized
    assert "Authorization" not in serialized


def test_contract_exercise_rejects_hash_valid_non_xlsx_artifact(tmp_path):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    client._first = b"not-an-xlsx"
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match="readable XLSX"):
        exercise_contract(config, client=client)


def test_contract_exercise_rejects_incomplete_checkpoint_progress(tmp_path):
    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    client = _FakeHttpClient()
    original_request = client.request

    def incomplete_progress(method, url, **kwargs):
        response = original_request(method, url, **kwargs)
        if url.endswith("/api/chat/stream"):
            response._lines[1] = response._lines[1].replace('"completed": 1', '"completed": 0')
        return response

    client.request = incomplete_progress
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(LiveAcceptanceError, match="did not complete"):
        exercise_contract(config, client=client)


def test_contract_exercise_rejects_elapsed_deadline(monkeypatch, tmp_path):
    from tools import live_workbook_acceptance as acceptance

    source = tmp_path / "user-owned.xlsx"
    source.write_bytes(b"source")
    ticks = iter((100.0, 102.0))
    monkeypatch.setattr(acceptance.time, "monotonic", lambda: next(ticks))
    config = AcceptanceConfig(
        attachment=source,
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
        max_elapsed_seconds=1,
    )

    with pytest.raises(LiveAcceptanceError, match="configured deadline"):
        exercise_contract(config, client=_FakeHttpClient())


def test_public_live_entrypoint_rejects_injected_transport(tmp_path):
    config = AcceptanceConfig(
        attachment=tmp_path / "source.xlsx",
        base_url="http://127.0.0.1:8050",
        profile_revision_id="profile:7",
        model_preset="qwen-9b",
        out=tmp_path / "receipt.json",
        api_key=None,
    )

    with pytest.raises(TypeError):
        run_acceptance(config, client=_FakeHttpClient())
