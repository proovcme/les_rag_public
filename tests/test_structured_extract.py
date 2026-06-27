"""Offline tests for schema-constrained extraction (no model required)."""

from __future__ import annotations

import pytest

from proxy.services import structured_extract as se


SCHEMA = {
    "type": "object",
    "required": ["poz", "qty"],
    "properties": {
        "poz": {"type": "string"},
        "qty": {"type": "number"},
        "unit": {"type": "string", "enum": ["шт", "м", "кг"]},
    },
}


def test_cloud_response_format_shape():
    rf = se.cloud_response_format(SCHEMA, name="spec")
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "spec"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] is SCHEMA


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"poz": "кабель", "qty": 5}', {"poz": "кабель", "qty": 5}),
        ('```json\n{"poz": "a", "qty": 1}\n```', {"poz": "a", "qty": 1}),
        ('Вот результат: {"poz": "b", "qty": 2}. Готово.', {"poz": "b", "qty": 2}),
        ('{"poz": "со {скобкой}", "qty": 3}', {"poz": "со {скобкой}", "qty": 3}),
        ("нет json здесь", None),
        ('[1,2,3]', None),  # top-level array is not a dict
    ],
)
def test_parse_json(text, expected):
    assert se.parse_json(text) == expected


def test_minimal_validate(monkeypatch):
    monkeypatch.setattr(se, "_HAS_JSONSCHEMA", False)  # exercise the built-in validator
    assert se.validate({"poz": "x", "qty": 5, "unit": "шт"}, SCHEMA) == []
    # missing required
    assert any("missing required 'qty'" in e for e in se.validate({"poz": "x"}, SCHEMA))
    # wrong type (and bool must not pass as number)
    assert any("expected type" in e for e in se.validate({"poz": "x", "qty": True}, SCHEMA))
    # enum violation
    assert any("not in enum" in e for e in se.validate({"poz": "x", "qty": 1, "unit": "тонна"}, SCHEMA))


def test_minimal_validate_nested_array(monkeypatch):
    monkeypatch.setattr(se, "_HAS_JSONSCHEMA", False)
    schema = {"type": "object", "properties": {"rows": {"type": "array", "items": {"type": "integer"}}}}
    assert se.validate({"rows": [1, 2, 3]}, schema) == []
    assert any("[1]" in e for e in se.validate({"rows": [1, "two", 3]}, schema))


def _scripted(replies):
    it = iter(replies)
    seen = []

    def call(prompt, response_format):
        seen.append((prompt, response_format))
        return next(it)

    call.seen = seen
    return call


def test_extract_valid_first_try():
    call = _scripted(['{"poz": "кабель", "qty": 5, "unit": "м"}'])
    res = se.extract(SCHEMA, "извлеки", "док", call)
    assert res.ok and res.attempts == 1
    assert res.data["poz"] == "кабель"


def test_extract_repairs_then_succeeds():
    call = _scripted(['{"poz": "x"}', '{"poz": "x", "qty": 9}'])  # missing qty → repair
    res = se.extract(SCHEMA, "извлеки", "док", call, max_attempts=3)
    assert res.ok and res.attempts == 2
    # second call must be the repair prompt carrying the error
    assert "не прошёл валидацию" in call.seen[1][0]


def test_extract_gives_up_after_max_attempts():
    call = _scripted(['nope', 'still nope', 'nope again'])
    res = se.extract(SCHEMA, "извлеки", "док", call, max_attempts=3)
    assert res.ok is False and res.attempts == 3 and res.errors


def test_extract_passes_cloud_response_format_when_requested():
    call = _scripted(['{"poz": "a", "qty": 1}'])
    se.extract(SCHEMA, "извлеки", "док", call, use_cloud_response_format=True)
    assert call.seen[0][1] is not None and call.seen[0][1]["type"] == "json_schema"
