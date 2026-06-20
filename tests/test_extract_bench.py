"""Offline tests for the extraction field-accuracy benchmark."""

from __future__ import annotations

import json

from tools import extract_bench as eb


def test_flatten_nested_and_array():
    flat = eb.flatten({"a": 1, "b": {"c": "x"}, "rows": [{"q": 2}, {"q": 3}]})
    assert flat == {"a": 1, "b/c": "x", "rows[0]/q": 2, "rows[1]/q": 3}


def test_score_case_perfect_and_partial():
    expected = {"poz": 1, "name": "Кабель", "qty": 150}
    perfect = eb.score_case("p", expected, dict(expected), attempts=1)
    assert perfect.total == 3 and perfect.matched == 3 and perfect.field_accuracy == 1.0

    partial = eb.score_case("x", expected, {"poz": 1, "name": "Кабель", "qty": 999, "junk": "z"}, attempts=2)
    assert partial.matched == 2 and partial.total == 3 and partial.extra == 1
    assert abs(partial.field_accuracy - 2 / 3) < 1e-9


def test_score_case_invalid_json_zero():
    s = eb.score_case("n", {"a": 1, "b": 2}, None, attempts=3)
    assert s.valid_json is False and s.matched == 0 and s.total == 2 and s.field_accuracy == 0.0


def test_numeric_equality_int_float():
    # 150 (int expected) vs 150.0 (float actual) must count as matched.
    s = eb.score_case("n", {"qty": 150}, {"qty": 150.0}, attempts=1)
    assert s.matched == 1


def test_load_golden_set():
    cases = eb.load_cases()
    assert len(cases) >= 4
    assert all(c.schema and c.expected for c in cases)


def test_run_bench_echo_is_perfect():
    cases = eb.load_cases()
    report = eb.run_bench(cases, eb.echo_backend(cases))
    assert report.valid_json_rate == 1.0
    assert report.field_accuracy_micro == 1.0
    assert report.mean_attempts == 1.0  # perfect → no repair


def test_run_bench_partial_backend():
    cases = eb.load_cases()[:1]
    schema_ok = json.dumps(cases[0].expected, ensure_ascii=False)

    # First reply drops a required field → repair; second is correct.
    bad = json.loads(schema_ok)
    bad.pop(sorted(cases[0].schema.get("required", ["poz"]))[0], None)
    replies = iter([json.dumps(bad, ensure_ascii=False), schema_ok])

    def call(_prompt, _rf):
        try:
            return next(replies)
        except StopIteration:
            return schema_ok

    report = eb.run_bench(cases, call, max_attempts=3)
    assert report.cases[0].valid_json is True
    assert report.cases[0].attempts == 2  # one repair
