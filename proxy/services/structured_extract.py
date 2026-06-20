"""Schema-constrained extraction — "give a JSON schema, get schema-valid JSON".

Technique borrowed from datalab/lift, adapted to LES's ladder and made
backend-agnostic: extraction runs through a caller-supplied LLM callable, so the
same code serves the local MLX path and the cloud path.

- **Cloud** backends get native structured-output enforcement via the
  ``response_format`` json_schema fragment (``cloud_response_format``).
- **Everything else** relies on a constrained prompt plus a *validate-and-repair*
  loop: parse the model's JSON, validate it against the schema, and on failure
  re-ask with the concrete errors. This gives a schema-valid result on any
  backend without touching the MLX serving internals.

Per the LLM-minimalism principle this is for the *hard* intake subset (messy
scans, unstructured docs). Clean tabular data must still go through deterministic
parsing (table_query / xls→Parquet), not a VLM.

Validation uses ``jsonschema`` when installed, otherwise a small built-in
validator covering the subset extraction schemas actually use (object/array/
string/number/integer/boolean/null + required + properties + items + enum).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

try:  # optional, stronger validator
    import jsonschema as _jsonschema
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover - depends on environment
    _jsonschema = None
    _HAS_JSONSCHEMA = False


# A callable that runs one model turn. response_format is passed through for
# backends that support native structured outputs (cloud); local backends ignore
# it and rely on the validate-and-repair loop.
LLMCall = Callable[[str, Optional[dict]], str]


@dataclass
class ExtractResult:
    ok: bool
    data: Optional[dict]
    attempts: int
    errors: list[str] = field(default_factory=list)


def cloud_response_format(schema: dict, name: str = "extraction") -> dict:
    """OpenAI-compatible ``response_format`` fragment for native json-schema mode.

    Merge into the cloud request body (see proxy/routers/chat.py) when a caller
    wants the provider to enforce the schema server-side.
    """
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "schema": schema, "strict": True},
    }


# ── JSON extraction from a model reply ──────────────────────────────────────
def parse_json(text: str) -> Optional[dict]:
    """Best-effort extraction of a single JSON object from a model reply.

    Handles ```json fenced blocks, raw JSON, and JSON wrapped in prose.
    """
    if not text:
        return None
    candidate = text.strip()
    # Strip a ```json … ``` (or plain ```) fence if present.
    if candidate.startswith("```"):
        candidate = candidate.split("```", 2)
        candidate = candidate[1] if len(candidate) > 1 else ""
        if candidate.lstrip().lower().startswith("json"):
            candidate = candidate.lstrip()[4:]
        candidate = candidate.strip().rstrip("`").strip()
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # Fall back to the first balanced {...} span, ignoring braces inside strings.
    span = _first_object_span(text)
    if span is None:
        return None
    try:
        obj = json.loads(span)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _first_object_span(text: str) -> Optional[str]:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# ── validation ──────────────────────────────────────────────────────────────
def validate(instance: object, schema: dict) -> list[str]:
    """Return a list of human-readable validation errors ([] means valid)."""
    if _HAS_JSONSCHEMA:
        validator = _jsonschema.Draft7Validator(schema)
        return [
            f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        ]
    return _minimal_validate(instance, schema, "<root>")


_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    # bool is a subclass of int — exclude it from number/integer.
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def _minimal_validate(instance: object, schema: dict, path: str) -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS.get(t, lambda _v: True)(instance) for t in types):
            errors.append(f"{path}: expected type {expected}, got {type(instance).__name__}")
            return errors  # type mismatch — deeper checks would be noise

    enum = schema.get("enum")
    if enum is not None and instance not in enum:
        errors.append(f"{path}: {instance!r} not in enum {enum}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        for key, subschema in props.items():
            if key in instance:
                errors.extend(_minimal_validate(instance[key], subschema, f"{path}/{key}"))

    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for idx, item in enumerate(instance):
                errors.extend(_minimal_validate(item, items, f"{path}[{idx}]"))

    return errors


# ── prompt construction ─────────────────────────────────────────────────────
def build_prompt(schema: dict, instruction: str, context: str) -> str:
    return (
        f"{instruction.strip()}\n\n"
        "Извлеки данные строго по JSON-схеме ниже. Ответь ТОЛЬКО валидным JSON-"
        "объектом по схеме, без пояснений и без markdown-ограждения.\n\n"
        f"JSON-схема:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"Документ:\n{context.strip()}"
    )


def _repair_prompt(schema: dict, previous: str, errors: list[str]) -> str:
    return (
        "Предыдущий ответ не прошёл валидацию по схеме.\n"
        f"Ошибки:\n- " + "\n- ".join(errors) + "\n\n"
        f"Предыдущий ответ:\n{previous}\n\n"
        "Верни исправленный JSON, строго по схеме, ТОЛЬКО JSON.\n\n"
        f"JSON-схема:\n{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


# ── main entry ──────────────────────────────────────────────────────────────
def extract(
    schema: dict,
    instruction: str,
    context: str,
    call_llm: LLMCall,
    *,
    max_attempts: int = 3,
    use_cloud_response_format: bool = False,
) -> ExtractResult:
    """Extract a schema-valid JSON object from ``context`` using ``call_llm``.

    ``call_llm(prompt, response_format)`` returns the model's text. Set
    ``use_cloud_response_format`` for cloud backends that enforce json-schema
    natively; local backends pass ``None`` and lean on validate-and-repair.
    """
    response_format = cloud_response_format(schema) if use_cloud_response_format else None
    prompt = build_prompt(schema, instruction, context)
    errors: list[str] = []

    for attempt in range(1, max_attempts + 1):
        reply = call_llm(prompt, response_format)
        data = parse_json(reply)
        if data is None:
            errors = ["ответ не содержит валидного JSON-объекта"]
        else:
            errors = validate(data, schema)
            if not errors:
                return ExtractResult(ok=True, data=data, attempts=attempt, errors=[])
        if attempt < max_attempts:
            prompt = _repair_prompt(schema, reply, errors)

    return ExtractResult(ok=False, data=None, attempts=max_attempts, errors=errors)
