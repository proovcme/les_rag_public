import json

from tools import validator_probe


def test_load_cases_reads_probe_set(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "c1",
                        "expected": "VERIFIED",
                        "question": "q",
                        "context": "ctx",
                        "answer": "a",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases = validator_probe.load_cases(path)

    assert cases[0].id == "c1"
    assert cases[0].expected == "VERIFIED"


def test_candidate_models_filters_out_active_default(monkeypatch):
    class Candidate:
        def __init__(self, model_id, status):
            self.id = model_id
            self.status = status

    monkeypatch.setattr(
        validator_probe,
        "load_matrix",
        lambda path: [
            Candidate("active", "active_default"),
            Candidate("candidate", "candidate"),
        ],
    )
    monkeypatch.setattr(validator_probe, "filter_candidates", lambda candidates, **kwargs: candidates)

    args = validator_probe.parse_args([])

    assert validator_probe.candidate_models(args) == ["candidate"]


def test_candidate_models_uses_explicit_models():
    args = validator_probe.parse_args(["--model", "m1", "--model", "m2"])

    assert validator_probe.candidate_models(args) == ["m1", "m2"]


def test_run_case_compares_expected_status(monkeypatch):
    case = validator_probe.ProbeCase("c1", "NO_DATA", "q", "ctx", "a")

    monkeypatch.setattr(
        validator_probe,
        "_request",
        lambda *args, **kwargs: (200, {"status": "NO_DATA", "raw": "NO_DATA"}, 0.1, "{}"),
    )

    result = validator_probe.run_case("http://mlx", "model", case, 1)

    assert result.ok is True
    assert result.actual == "NO_DATA"
