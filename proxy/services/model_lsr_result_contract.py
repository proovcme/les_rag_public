"""One model-authored row contract for every supported answer representation.

The fields describe an authored decision, not a rule for choosing or confirming
norms. Renderers share this contract so a table hint cannot weaken required facts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping


BASE_FIELDS = (
    "source_row", "row_role", "work_row", "title", "unit", "quantity",
    "norm_code", "norm_status", "open_gap", "evidence_refs",
)
MATCH_FIELDS = (
    "action_match", "object_match", "condition_match", "unit_compatible",
    "composition_covers",
)
SELECTED_NORM_FIELDS = (*MATCH_FIELDS, "coverage")
# Only explicit nullable transport fields. A title or role named 'null' is not
# rewritten; JSON-quoted "null" remains a literal string in named text.
TEXT_NULLABLE_FIELDS = frozenset({
    "operation_id", "revision", "expected_revision", "base_revision", "work_row", "covered_by_work_id",
    "unit", "quantity", "open_gap", "coverage", "norm_code", "norm_status", "evidence_refs",
    "calc_quantity", "calc_unit", "conversion_factor", "conversion_source", "coefficient",
    "coefficient_applies_to", "nr_sp_rule_id", "confirmed_price", "price_source", "price_unit",
    "price_currency", "price_period", "price_vat", "price_year", "price_quarter",
})
OPTIONAL_FIELDS = (
    "section", "supply_kind", "calc_quantity", "calc_unit", "conversion_factor", "conversion_source",
    "coefficient", "coefficient_applies_to", "extra_ops", "missing_ops", "norm_components",
    "confirmed_price", "price_kind", "price_unit", "price_source",
    "price_currency", "price_vat", "price_period",
    "resource_bindings", "resource_review", "covered_by_work_id",
    "resolves_proposal_id",
)

LSR_SOURCE_VOLUME_INSTRUCTION = (
    "Масштаб нормы применяется один раз. quantity не дели; calc_quantity/conversion_factor "
    "с conversion_source — обоснованный перевод (фасовка, геометрия, расход), без масштаба нормы. "
)

LSR_DERIVED_VOLUME_INSTRUCTION = (
    "Для кратности всей нормы calc_quantity/calc_unit — расчётный эквивалент, формула — conversion_source. "
    "Для начисляемой добавочной нормы covered_by_work_id не задавай. "
)


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate authored JSON field: " + key)
        value[key] = item
    return value


class _AuthoredJSONPairs(list):
    """Object boundaries and repeated labels, before any value can be selected."""


def _json_duplicate_fields(value, path=()):
    duplicates = []
    if isinstance(value, _AuthoredJSONPairs):
        fields = {}
        for key, item in value:
            fields.setdefault(key, []).append(item)
            duplicates.extend(_json_duplicate_fields(item, (*path, key)))
        duplicates.extend({"field": key, "path": list((*path, key)), "occurrences": len(items),
                           "same_values": all(item == items[0] for item in items)}
                          for key, items in fields.items() if len(items) > 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            duplicates.extend(_json_duplicate_fields(item, (*path, index)))
    return duplicates


def _json_unique_value(value):
    if isinstance(value, _AuthoredJSONPairs):
        return {key: _json_unique_value(item) for key, item in value}
    if isinstance(value, list):
        return [_json_unique_value(item) for item in value]
    return value


def _json_row_texts(candidate, decoder):
    """Get literal row objects using the standard JSON parser's syntax ends."""
    def skip_space(index):
        while index < len(candidate) and candidate[index].isspace():
            index += 1
        return index

    index = skip_space(0)
    if candidate[index] == "{":
        index = skip_space(index + 1)
        while candidate[index] != "}":
            key, index = decoder.raw_decode(candidate, index)
            value_start = skip_space(skip_space(index) + 1)  # validated colon
            _value, index = decoder.raw_decode(candidate, value_start)
            if key == "rows":
                index = value_start
                break
            index = skip_space(index)
            if candidate[index] == ",":
                index = skip_space(index + 1)
    texts = []
    index = skip_space(index + 1)  # validated rows-array opener
    while candidate[index] != "]":
        start = index
        _value, index = decoder.raw_decode(candidate, start)
        texts.append(candidate[start:index])
        index = skip_space(index)
        if candidate[index] == ",":
            index = skip_space(index + 1)
    return texts


def _container_end(text: str, start: int) -> int | None:
    """Index just past a JSON object/array, honouring strings and escapes.

    ``None`` means the container never closes — an unfinished answer, which this contract must
    refuse as a whole rather than guess the rest of.
    """
    if text[start] not in "{[":
        return None
    depth = 0
    index = start
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
            if depth == 0:
                return index + 1
            if depth < 0:
                return None
        index += 1
    return None


def _array_element_texts(text: str, start: int, decoder):
    """Split a rows array into literal element texts: what parses and what does not.

    Returns ``(good, broken, end_after)`` or ``None`` when the array itself is unfinished.  The
    element texts are the model's own bytes — nothing here rewrites a value it wrote badly.
    """
    good: list[str] = []
    broken: list[str] = []
    index = start + 1
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return None
        if text[index] == "]":
            return good, broken, index + 1
        end = None
        try:
            _value, end = decoder.raw_decode(text, index)
        except (ValueError, TypeError):
            end = None
        if end is None:
            end = _container_end(text, index)
            if end is None:
                comma = _next_top_level_comma(text, index)
                if comma is None:
                    return None
                end = comma
            if end <= index:
                return None
            broken.append(text[index:end].strip())
        else:
            good.append(text[index:end])
            if end <= index:
                return None
        index = end
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == ",":
            index += 1


def _next_top_level_comma(text: str, start: int) -> int | None:
    """Next comma outside any string or container, for bounding one unreadable element."""
    depth = 0
    index = start
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            if depth == 0:
                return None
            depth -= 1
        elif char == "," and depth == 0:
            return index
        index += 1
    return None


def _salvaged_candidate(text: str, start: int, decoder):
    """Rebuild an envelope from the row objects a badly-valued authored JSON really contains.

    Installed 933 measured why this is needed (``artifacts/live_933/installed933_bap_b1/``): the
    model answered the whole 7-locator packet as one closed JSON document with 12 rows, and wrote
    ``"conversion_factor":1/100`` — an arithmetic expression where JSON expects a value.  The
    envelope parse failed on that one token, the decoder returned no rows at all, and the run
    ended with ``source_coverage_incomplete:1/20``, no artifact and ``packaging_reason
    ARTIFACT_KIND_UNRESOLVED``.  Eleven of those twelve rows carried a complete decision; the
    all-or-nothing reader threw all of them away.

    The rule is deliberately narrow:

    * an unfinished container returns ``None``, so the refusal of a cut-off answer is unchanged;
    * only elements that parse on their own are admitted, as their literal texts;
    * every unreadable element is returned as a broken row, kept as a visible proposal instead of
      being repaired or dropped in silence — the application does not invent a number the model
      did not express as data.
    """
    end_after = _container_end(text, start)
    if end_after is None:
        return None
    if text[start] == "[":
        split = _array_element_texts(text, start, decoder)
        if split is None or not split[0]:
            return None
        good, broken, _rows_end = split
        return "[%s]" % ",".join(good), broken, end_after
    index = start + 1
    members: list[str] = []
    while True:
        while index < end_after and text[index].isspace():
            index += 1
        if index >= end_after:
            return None
        if text[index] == "}":
            # a closed envelope with no `rows` member: there is nothing here to salvage
            return None
        member_start = index
        try:
            key, index = decoder.raw_decode(text, index)
        except (ValueError, TypeError):
            return None
        while index < end_after and text[index].isspace():
            index += 1
        if index >= end_after or text[index] != ":":
            return None
        index += 1
        while index < end_after and text[index].isspace():
            index += 1
        if index >= end_after:
            return None
        if key == "rows" and text[index] == "[":
            split = _array_element_texts(text, index, decoder)
            if split is None:
                return None
            good, broken, _rows_end = split
            if not good:
                return None
            prefix = ",".join(members)
            rebuilt = ('{%s,"rows":[%s]}' % (prefix, ",".join(good))) if prefix \
                else '{"rows":[%s]}' % ",".join(good)
            return rebuilt, broken, end_after
        try:
            _value, value_end = decoder.raw_decode(text, index)
        except (ValueError, TypeError):
            # an envelope member the model wrote unreadably is not a row-level defect, and
            # guessing which envelope the document is would be the application authoring it
            return None
        members.append(text[member_start:value_end])
        index = value_end
        while index < end_after and text[index].isspace():
            index += 1
        if index < end_after and text[index] == ",":
            index += 1


def decode_model_result_rows(raw: str, *, diagnostics: list[dict] | None = None) -> list[dict] | None:
    """Keep unique authored rows; preserve duplicate-label objects as proposals."""
    candidates = []
    original_text = str(raw or "")
    text = original_text.strip()
    decoder = json.JSONDecoder(object_pairs_hook=_AuthoredJSONPairs)
    outside_segments, start = [], 0
    for fence in re.finditer(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text):
        outside_segments.append(text[start:fence.start()])
        candidates.append((fence.group(1), []))
        start = fence.end()
    outside_segments.append(text[start:])
    for segment in outside_segments:
        segment = segment.strip()
        index = 0
        while index < len(segment):
            # A standalone target label is transport, outside authored JSON.
            # Never remove it from an object/array or a fenced candidate.
            label = re.match(r"artifact_kind[ \t]*:[^\r\n]*(?:\r?\n|$)", segment[index:])
            if label is not None and not segment[:index].rsplit("\n", 1)[-1].strip():
                index += label.end()
                while index < len(segment) and segment[index].isspace():
                    index += 1
                continue
            if segment[index] not in "{[":
                break
            try:
                _value, end = decoder.raw_decode(segment, index)
            except (ValueError, TypeError):
                # A quoted object member or an object inside a row array starts
                # JSON syntax; a prose citation such as [Source] does not.
                opener = segment[index]
                after_opener = segment[index + 1:].lstrip()
                if after_opener.startswith('"' if opener == "{" else "{"):
                    salvaged = _salvaged_candidate(segment, index, decoder)
                    if salvaged is None:
                        if diagnostics is not None:
                            diagnostics.append({"code": "MODEL_RESULT_JSON_INCOMPLETE_RESULT",
                                "reason": "incomplete_authored_json_result",
                                "decision": {"raw_json": original_text}})
                        return None
                    candidate_text, broken_rows, end_after = salvaged
                    candidates.append((candidate_text, broken_rows))
                    index = end_after
                    while index < len(segment) and segment[index].isspace():
                        index += 1
                    continue
                break
            if end < len(segment) and not segment[end].isspace():
                break
            candidates.append((segment[index:end], []))
            index = end
            while index < len(segment) and segment[index].isspace():
                index += 1
    decoded = []
    for candidate, broken_rows in candidates:
        try:
            value = decoder.decode(candidate)
        except (ValueError, TypeError):
            continue
        envelope_conflicts = []
        if isinstance(value, _AuthoredJSONPairs):
            names = [key for key, _item in value]
            envelope_conflicts = [{"field": key, "path": [key], "occurrences": names.count(key)}
                                  for key in dict.fromkeys(names) if names.count(key) > 1 and key != "artifact_kind"]
            for key, item in value:
                if key not in {"rows", "artifact_kind"}:
                    envelope_conflicts.extend(_json_duplicate_fields(item, (key,)))
            if envelope_conflicts:
                decoded.append(([], [{"code": "MODEL_RESULT_JSON_DUPLICATE_FIELD",
                    "reason": "duplicate_authored_json_field", "duplicate_fields": envelope_conflicts,
                    "decision": {"raw_json": candidate}}]))
                continue
            rows = next((item for key, item in value if key == "rows"), None)
        else:
            rows = value
        if not isinstance(rows, list) or isinstance(rows, _AuthoredJSONPairs):
            continue
        proposals, unique_rows, row_shape_valid = [], [], True
        for broken_text in broken_rows:
            # The unreadable row stays the model's own bytes, named and unpaid: no value here is
            # computed for it, and its absence is a visible proposal rather than a silent gap.
            decision: dict = {"raw_json": broken_text}
            located = re.search(r'"source_row"[ \t]*:[ \t]*"([^"]*)"', broken_text)
            if located is not None:
                decision["source_row"] = located.group(1)
            proposals.append({"code": "MODEL_RESULT_JSON_INVALID_ROW",
                              "reason": "unreadable_authored_json_row", "decision": decision})
        raw_rows = _json_row_texts(candidate, decoder)
        for index, row in enumerate(rows):
            conflicts = _json_duplicate_fields(row)
            if isinstance(row, _AuthoredJSONPairs) and conflicts:
                decision = {"raw_json": raw_rows[index], "json_row_index": index}
                locators = [item for key, item in row if key == "source_row"]
                if len(locators) == 1 and isinstance(locators[0], (str, int)) and not isinstance(locators[0], bool):
                    decision["source_row"] = locators[0]
                proposals.append({"code": "MODEL_RESULT_JSON_DUPLICATE_FIELD",
                    "reason": "duplicate_authored_json_field", "duplicate_fields": conflicts,
                    "decision": decision})
                continue
            unique = _json_unique_value(row)
            if not (isinstance(unique, Mapping) and "title" in unique
                    and ({"unit", "norm_code"}.issubset(unique)
                         or str(unique.get("row_role") or "").strip().casefold()
                         in {"work", "material", "equipment", "resource", "header", "unresolved"})
                    and unique.get("source_row") not in (None, "")):
                row_shape_valid = False
                break
            unique_rows.append(unique)
        if row_shape_valid:
            decoded.append((unique_rows, proposals))
    if len(decoded) != 1:
        if len(decoded) > 1 and diagnostics is not None:
            diagnostics.append({"code": "MODEL_RESULT_JSON_AMBIGUOUS_RESULTS",
                "reason": "multiple_complete_json_results", "decision": {"raw_json": original_text}})
        return None
    rows, proposals = decoded[0]
    if diagnostics is not None:
        diagnostics.extend(proposals)
    return rows if rows or not proposals else None


def decode_model_inline_rows(raw: str, *, fields: set[str], diagnostics: list[dict]) -> list[dict] | None:
    """Read punctuated explicit named records, never infer cells.

    A pipe separates fields; commas/semicolons do so only before a named label.
    List bullets/numbers are presentation. Quoted values, JSON arrays/objects,
    decimal commas and ordinary prose punctuation remain literal. Ambiguous
    records remain raw proposals, including repeated labels; valid rows survive.
    """
    rows, seen_record = [], False
    for raw_line in str(raw or "").splitlines():
        line = raw_line.strip().lstrip("-+*• ")
        line = re.sub(r"^(?:\d+[.)]|\(\d+\))\s+", "", line)
        if not re.match(r"(?:source_row|operation_id)\s*:", line) or not (
            "|" in line or re.search(r"[,;]\s*[A-Za-z_]\w*\s*:", line)
        ):
            continue
        seen_record = True
        parts, current, stack, quoted, index, malformed = [], [], [], False, 0, False
        while index < len(line):
            char = line[index]
            if char == "\\" and index + 1 < len(line):
                current.extend((char, line[index + 1]))
                index += 2
                continue
            if char == '"':
                # A quote within an ordinary title (e.g. 19" rack) is literal.
                at_value_start = not "".join(current).partition(":")[2].strip()
                if quoted or stack or at_value_start:
                    quoted = not quoted
            elif not quoted:
                if char in "[{":
                    stack.append(char)
                elif char in "]}":
                    if not stack or stack.pop() != (
                        "[" if char == "]" else "{"
                    ):
                        malformed = True
                elif not stack and (char == "|" or (
                    char in ",;" and re.match(r"\s*[A-Za-z_]\w*\s*:", line[index + 1:])
                )):
                    parts.append("".join(current).strip())
                    current = []
                    index += 1
                    continue
            current.append(char)
            index += 1
        parts.append("".join(current).strip())
        row, reason = {}, "malformed_inline_record" if malformed or quoted or stack else ""
        for part in parts:
            label, delimiter, value = part.partition(":")
            key = label.strip()
            if not delimiter:
                reason = reason or "unlabelled_inline_value"
                continue
            if key not in fields:
                reason = reason or "unsupported_inline_field"
                continue
            if key in row:
                reason = reason or "duplicate_inline_field"
                continue
            value = value.strip()
            try:
                parsed_value = json.loads(value, object_pairs_hook=_AuthoredJSONPairs)
                if _json_duplicate_fields(parsed_value):
                    reason = reason or "duplicate_inline_json_field"
                else:
                    row[key] = _json_unique_value(parsed_value)
            except (ValueError, TypeError):
                row[key] = value.replace(r"\|", "|")
        if not (row.get("source_row") not in (None, "") and "title" in row
                and ({"unit", "norm_code"}.issubset(row)
                     or str(row.get("row_role") or "").casefold()
                     in {"work", "material", "equipment", "resource", "header", "unresolved"})):
            reason = reason or "incomplete_inline_record"
        if reason:
            decision = {"raw_line": raw_line}
            if row.get("source_row") not in (None, ""):
                decision["source_row"] = row["source_row"]
            diagnostics.append({"code": "MODEL_RESULT_INLINE_RECORD_INVALID",
                                "reason": reason, "decision": decision})
        else:
            rows.append(row)
    return rows if seen_record else None


def _model_json_documents(raw: str) -> tuple[list[str], list[str]]:
    """Read standalone JSON documents and preserve the surrounding commentary.

    JSONDecoder finds document boundaries through strings and nested objects.
    Only line-level documents or explicit JSON fences qualify; an inline
    example in prose is not a declaration or an executable query envelope.
    Invalid structured tails remain candidates so callers cannot pick a
    later valid object and silently discard the invalid proposal.
    """
    text = str(raw or "").strip()
    candidates: list[str] = []
    commentary: list[str] = []
    decoder = json.JSONDecoder()

    def read_segment(segment: str) -> None:
        cursor = 0
        for match in re.finditer(r"(?m)^[ \t]*[{\[]", segment):
            index = match.end() - 1
            if index < cursor:
                continue
            commentary.append(segment[cursor:index])
            try:
                _value, end = decoder.raw_decode(segment, index)
            except (ValueError, TypeError):
                candidates.append(segment[index:])
                return
            if end < len(segment) and not segment[end].isspace():
                candidates.append(segment[index:])
                return
            candidates.append(segment[index:end])
            cursor = end
        commentary.append(segment[cursor:])

    start = 0
    for fence in re.finditer(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text):
        read_segment(text[start:fence.start()])
        candidates.append(fence.group(1))
        start = fence.end()
    read_segment(text[start:])
    return candidates, commentary


def _model_query_wrapper_data(value):
    """Read one known model-authored wrapper, never application runtime facts.

    The model can copy a schema label into its visible output. That gives the
    output no trust or authority: only this narrow literal query representation
    is accepted, and the caller keeps the original authored carrier unchanged.
    """
    if (not isinstance(value, dict) or set(value) != {"schema", "kind", "data"}
            or value["schema"] != "les.model-runtime-facts.v1"
            or value["kind"] != "declare_research_queries_result"):
        return None
    data = value["data"]
    if (not isinstance(data, dict) or "queries" not in data
            or not set(data).issubset({"queries", "artifact_kind", "commentary"})
            or ("artifact_kind" in data and data["artifact_kind"] not in ("vor", "lsr"))
            or ("commentary" in data and not isinstance(data["commentary"], str))):
        return None
    queries = data["queries"]
    if (not isinstance(queries, list)
            or any(not isinstance(query, str) or not query.strip()
                   or "\n" in query or "\r" in query for query in queries)):
        return None
    return data


def decode_model_quoted_text_scalar(value: str) -> str:
    """Unwrap a complete JSON string in a named text field, without interpreting prose.

    The original answer remains the audit. Non-string JSON, incomplete quotes,
    YAML expressions and ordinary text retain their literal representation.
    """
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return value
        if isinstance(parsed, str):
            return parsed
    return value


def decode_model_artifact_kind(raw: str) -> dict:
    """Read a document-level literal declaration, without choosing its purpose.

    Target ambiguity is independent of row admission. A single plain label may
    repeat the same valid target in one complete, unique-key JSON document;
    repeated declarations within either transport remain ambiguous.
    """
    decoder = json.JSONDecoder(object_pairs_hook=_AuthoredJSONPairs)
    candidates, segments = _model_json_documents(raw)
    declarations, errors = [], []
    plain_label_count = 0
    for segment in segments:
        # This label is a transport field, not an interpretation of prose.
        labels = list(re.finditer(r"(?m)^[ \t]*artifact_kind[ \t]*:[ \t]*(.*?)[ \t]*$", segment))
        plain_label_count += len(labels)
        declarations.extend(decode_model_quoted_text_scalar(match.group(1).strip()) for match in labels)
    for candidate in candidates:
        try:
            value = decoder.decode(candidate)
        except (ValueError, TypeError):
            if '"artifact_kind"' in candidate:
                errors.append("ARTIFACT_KIND_INCOMPLETE_JSON")
            continue
        if isinstance(value, _AuthoredJSONPairs):
            declarations.extend(item for key, item in value if key == "artifact_kind")
            if {key for key, _item in value} == {"schema", "kind", "data"}:
                try:
                    wrapped = _model_query_wrapper_data(json.loads(candidate, object_pairs_hook=_unique_json_object))
                except (ValueError, TypeError):
                    wrapped = None
                if wrapped is not None and "artifact_kind" in wrapped:
                    declarations.append(wrapped["artifact_kind"])
    matching_transport_forms = False
    if (len(declarations) == 2 and plain_label_count == 1 and len(candidates) == 1
            and not errors and declarations[0] in ("vor", "lsr")
            and declarations[0] == declarations[1]):
        try:
            # Keep the literal audit above, but never legitimise duplicate JSON
            # keys, an incomplete document or a second authored JSON document.
            document = json.loads(candidates[0], object_pairs_hook=_unique_json_object)
        except (ValueError, TypeError):
            pass
        else:
            matching_transport_forms = (isinstance(document, dict)
                and document.get("artifact_kind") == declarations[0])
    if len(declarations) > 1 and not matching_transport_forms:
        errors.append("ARTIFACT_KIND_AMBIGUOUS")
        status = "conflict"
    elif errors or (declarations and declarations[0] not in ("vor", "lsr")):
        errors.append("ARTIFACT_KIND_INVALID")
        status = "invalid"
    else:
        status = "declared" if declarations else "missing"
    return {"status": status, "artifact_kind": declarations[0] if status == "declared" else "",
            "declarations": declarations, "errors": list(dict.fromkeys(errors))}


def merge_model_artifact_kind(previous: Mapping | None, current: Mapping) -> dict:
    """Accumulate declarations from distinct model turns without picking a conflict."""
    previous = dict(previous or {})
    current = dict(current)
    if current.get("status") == "missing":
        return previous or current
    if not previous or previous.get("status") == "missing":
        return current
    if (previous.get("status") == current.get("status") == "declared"
            and previous.get("artifact_kind") == current.get("artifact_kind")):
        return current
    return {"status": "conflict", "artifact_kind": "",
            "declarations": [*previous.get("declarations", []), *current.get("declarations", [])],
            "errors": list(dict.fromkeys([*previous.get("errors", []), *current.get("errors", []),
                                         "ARTIFACT_KIND_AMBIGUOUS"]))}


def update_model_artifact_kind(previous: Mapping | None, current: Mapping, *, phase: str) -> dict:
    """Keep query proposals separate from the completed model document.

    A final declaration may supersede only a known query proposal. Conflicting
    final packets and unclassified historical declarations remain fail-closed.
    """
    previous = dict(previous or {})
    current = dict(current)
    if phase == "restore":
        if current.get("authority") in {"query", "result"}:
            return update_model_artifact_kind(previous, current, phase=current["authority"])
        restored = merge_model_artifact_kind(previous, current)
        if current.get("status") != "missing":
            restored["authority"] = "legacy"
        return restored
    if phase not in {"query", "result"}:
        raise ValueError("unknown document target phase")
    if current.get("status") == "missing":
        return previous or current
    if phase == "query":
        if previous and previous.get("status") != "missing" and previous.get("authority") != "query":
            proposal = merge_model_artifact_kind(previous.get("query_declaration"), current)
            return {**previous, "query_declaration": proposal}
        proposal = merge_model_artifact_kind(previous, current)
        return {**proposal, "authority": "query"}
    if previous.get("authority") == "query":
        proposal = {key: value for key, value in previous.items() if key != "authority"}
        return {**current, "authority": "result", "query_declaration": proposal}
    result = merge_model_artifact_kind(previous, current)
    if previous.get("query_declaration"):
        result["query_declaration"] = dict(previous["query_declaration"])
    return {**result, "authority": "result"}


def decode_model_query_envelope(raw: str, *, format_errors: list[dict[str, str]] | None = None) -> dict | None:
    """An optional literal query list; ordinary query text keeps its old reader."""
    def reject(path: str, code: str):
        # Only contract paths/codes: never authored keys, values or decoder text.
        if format_errors is not None and len(format_errors) < 32:
            format_errors.append({"path": path, "code": code})
        return None

    candidates, outer_commentary = _model_json_documents(raw)
    if len(candidates) not in (1, 2):
        return reject("$", "QUERY_JSON_DOCUMENT_COUNT")
    documents = []
    for index, candidate in enumerate(candidates):
        try:
            documents.append(json.loads(candidate, object_pairs_hook=_unique_json_object))
        except json.JSONDecodeError:
            return reject(f"$[{index}]", "QUERY_JSON_INVALID")
        except ValueError:
            return reject(f"$[{index}]", "QUERY_JSON_DUPLICATE_FIELD")
        except TypeError:
            return reject(f"$[{index}]", "QUERY_JSON_INVALID")
    value = documents[0]
    wrapped = False
    if any(isinstance(document, dict) and (
            ("data" in document and bool({"schema", "kind"}.intersection(document)))
            or document.get("schema") == "les.model-runtime-facts.v1"
            or document.get("kind") == "declare_research_queries_result") for document in documents):
        # Do not select between wrapped and ordinary envelopes, discard a side
        # document, or extract queries from unknown/business wrapper metadata.
        data = _model_query_wrapper_data(value)
        if len(documents) != 1 or data is None:
            return reject("$", "QUERY_WRAPPER_FIELDS_INVALID")
        value = data
        documents = [data]
        wrapped = True
    if len(documents) == 2:
        # A separate commentary-only document carries no search or business
        # decision. Admit exactly one query envelope; never select between
        # multiple query objects, merge document fields or discard an invalid
        # neighbouring authored object.
        notes = [index for index, document in enumerate(documents)
                 if isinstance(document, dict) and set(document) == {"commentary"}
                 and isinstance(document["commentary"], str)]
        if len(notes) != 1:
            return reject("$", "QUERY_COMMENTARY_DOCUMENT_REQUIRED")
        value = documents[1 - notes[0]]
        if (not isinstance(value, dict) or "queries" not in value
                or not set(value).issubset({"queries", "artifact_kind", "commentary"})):
            return reject("$", "QUERY_ENVELOPE_FIELDS_INVALID")
        declaration = decode_model_artifact_kind(raw)
        expected_status = "declared" if "artifact_kind" in value else "missing"
        if (declaration["status"] != expected_status
                or (expected_status == "declared"
                    and declaration["artifact_kind"] != value["artifact_kind"])):
            return reject("$.artifact_kind", "QUERY_ARTIFACT_KIND_CONFLICT")
    if not isinstance(value, dict):
        return reject("$", "QUERY_ENVELOPE_OBJECT_REQUIRED")
    if wrapped:
        declaration = decode_model_artifact_kind(raw)
        expected_status = "declared" if "artifact_kind" in value else "missing"
        if (declaration["status"] != expected_status
                or (expected_status == "declared" and declaration["artifact_kind"] != value["artifact_kind"])):
            return reject("$.artifact_kind", "QUERY_ARTIFACT_KIND_CONFLICT")
    if "artifact_kind" in value and value["artifact_kind"] not in ("vor", "lsr"):
        return reject("$.artifact_kind", "QUERY_ARTIFACT_KIND_INVALID")
    if "artifact_kind" not in value and decode_model_artifact_kind(raw)["status"] != "missing":
        # A queries-only JSON object cannot legitimise separate invalid or
        # conflicting document metadata around it.
        return reject("$.artifact_kind", "QUERY_ARTIFACT_KIND_CONFLICT")
    queries = value.get("queries")
    if not isinstance(queries, list):
        return reject("$.queries", "QUERY_LIST_REQUIRED")
    for index, query in enumerate(queries):
        if not isinstance(query, str):
            return reject(f"$.queries[{index}]", "QUERY_ENTRY_STRING_REQUIRED")
        if not query.strip():
            return reject(f"$.queries[{index}]", "QUERY_ENTRY_NONEMPTY_REQUIRED")
        if "\n" in query or "\r" in query:
            return reject(f"$.queries[{index}]", "QUERY_ENTRY_SINGLE_LINE_REQUIRED")
    result = {"queries": queries}
    comments = [item.strip() for item in outer_commentary if item.strip()]
    for document in documents:
        commentary = document.get("commentary")
        if commentary is not None:
            comments.append(commentary if isinstance(commentary, str)
                            else json.dumps(commentary, ensure_ascii=False))
    if comments:
        result["commentary"] = "\n\n".join(comments)
    return result


def decode_model_resource_field(value):
    """Structured cell/label values are JSON; malformed authored values survive."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
    try:
        return json.loads(text, object_pairs_hook=_unique_json_object)
    except (ValueError, TypeError):
        return value


def model_lsr_result_examples() -> dict[str, str]:
    """Render format examples from one row; placeholders never choose a norm."""
    row = {
        "source_row": "SOURCE_LOCATOR",
        "row_role": "work",
        "work_row": "SOURCE_LOCATOR",
        "title": "Выбранная моделью работа",
        "unit": "SOURCE_UNIT",
        "quantity": "SOURCE_QUANTITY",
        "norm_code": "SELECTED_CARD_CODE",
        "norm_status": "NEEDS_RESEARCH",
        "open_gap": "Какие условия объекта применимы к вариантам НР/СП карточки?",
        "evidence_refs": "Qx.Hy",
        **{name: "unknown" for name in MATCH_FIELDS},
        "coverage": "Условия объекта пока не установлены по источникам.",
        "nr_sp_rule_id": "",
    }
    fields = tuple(row)
    markdown = "\n".join((
        "| " + " | ".join(fields) + " |",
        "| " + " | ".join("---" for _ in fields) + " |",
        "| " + " | ".join(str(row[name]) for name in fields) + " |",
    ))
    return {
        "markdown": markdown,
        "json": json.dumps({"rows": [row]}, ensure_ascii=False),
        "text": "\n".join(f"{name}: {value}" for name, value in row.items()),
    }


def model_vor_result_field_instruction() -> str:
    """The model authors operations and justified quantities, without LSR fields."""
    return (
        "Составь ВОР: самостоятельные технологические работы с обоснованными единицами, "
        "объёмами и исходными основаниями, а не переписанную спецификацию изделий. "
        "Производную работу обоснуй в coverage исходными данными: сохрани предмет, слой и технические признаки собственной исходной позиции; "
        "не переноси их из соседней позиции без основания. Равенство количества и единицы у разных исходных позиций само по себе не доказывает дубль "
        "или покрытие одной работы другой. Объединение операций или включение одной в другую обоснуй в coverage "
        "исходным составом или показанным составом выбранной нормы; укажи включённое и исключённое. "
        "Соблюдай формат пользователя; иначе предпочти компактный JSON "
        '{"artifact_kind":"vor","rows":[...]}. Допустимы Markdown или текст с теми же полями; '
        "вне JSON объяви artifact_kind: vor отдельной строкой. "
        "Поля строки: source_row, row_role, work_row, title, unit, quantity, open_gap. "
        "row_role: work, material, equipment, resource, header или unresolved. "
        "Роль определяешь ты по смыслу исходной позиции: ГОСТ, марка или артикул сами по себе "
        "не превращают названную работу в материал. work — технологическая операция; "
        "header — раздел, примечание или итог; unresolved — нерешённая позиция с конкретным open_gap. "
        "Для изделия определи обоснованные исходником работы либо сохрани material/equipment "
        "с реальной связью с работой или конкретным вопросом о недостающих данных. "
        "Не добавляй монтаж каждому изделию автоматически. Один source_row может обосновывать "
        "несколько разных работ и материал; не дублируй один и тот же объём работы. "
        "work_row ссылается на реально существующую работу: её source_row или показанный operation_id, "
        "а не на артикул, норму или придуманный ID. Неоднозначную связь оставь вопросом. "
        "В строке материала или оборудования не ссылайся на само изделие без фактически возвращённой "
        "работы row_role=work по этому адресу. Если операция включена в другую работу, опиши "
        "в coverage её включённый и исключённый состав, укажи адрес родительской работы в work_row; "
        "при уже показанном operation_id родителя укажи его в covered_by_work_id. "
        "source_row дословно копируй из показанного адреса исходной строки без перенумерации; "
        "section хранит название раздела отдельно. unit и quantity сохраняй из той же исходной строки. "
        "Неизвестный quantity — null в JSON или пустая ячейка в Markdown, не 0; "
        "явный исходный ноль сохраняй как 0. Если требуется производный объём, "
        "укажи итоговый calc_quantity, его явную calc_unit и conversion_source с проверяемой формулой; "
        "conversion_factor укажи только для точного скалярного перевода: "
        "quantity × conversion_factor = calc_quantity. Для многошагового или округлённого расчёта "
        "без точного скаляра оставь conversion_factor пустым и опиши расчёт в conversion_source. Обоснуй расчёт "
        "исходными параметрами и их точным источником; исходные unit/quantity не подменяй. "
        "Не придумывай толщину, число сторон, площадь, вид отделки или расход. "
        "Если основания недостаточно, в open_gap назови конкретно недостающий параметр или решение, "
        "а не общий призыв проверить всё. open_gap — только нерешённый вопрос; подтверждённое пояснение "
        "или обоснованное исключение укажи в coverage, не как открытый вопрос. "
        "Только вопрос, который мешает определить требуемые работы, их связи, единицы или объёмы, является пробелом ВОР; "
        "данные для будущей логистики или ценообразования не превращай в open_gap ВОР, если они не нужны для этой задачи. "
        "evidence_refs добавляй для фактически показанного основания "
        "с его буквальным Qx.Hy; исходник обосновывай через source_row. Нормы и цены для ВОР "
        "не обязательны: их отсутствие не превращает известную работу в unresolved. "
        "Для прежней операции сохраняй operation_id из prior_model_decisions; для новой оставь "
        "operation_id пустым. При изменении прежней операции верни expected_revision из показанного "
        "revision или base_revision; свои ID и новые revision не назначай. При обычном продолжении "
        "верни новые и изменённые решения; при явном пересмотре — все предложенные прежние операции, "
        "включая неизменённые с дословными предметными полями и прежними ID. "
        "Не ограничивай число решений. Текущий пакет — часть исходника, остальные строки "
        "не объявляй отсутствующими. В Markdown сохраняй пустые объявленные ячейки "
        "и экранируй | внутри значения; пояснения давай после таблицы."
    )


def model_lsr_result_field_instruction(*, include_examples: bool = False) -> str:
    """Explain conditional row fields identically for Markdown, JSON and text."""
    instruction = (
        "Итоговые строки: соблюдай явно заданный пользователем формат. "
        "Без указания формата предпочти компактный JSON {\"rows\":[...]}; допустимы Markdown или текст. "
        "Если задание упоминает и ВОР, и ЛСР/смету либо не называет тип результата, "
        "выбери сам требуемый итоговый документ с учётом цели пользователя, входного документа и дальнейшего назначения. "
        "В том же итоговом ответе объяви один artifact_kind: vor или artifact_kind: lsr "
        "(в корне JSON либо отдельной строкой); это тип результата, не тип исходника. "
        "В Markdown сохраняй объявленные "
        "ячейки, включая пустые, и экранируй | внутри значения. "
        "Поля ВОР: source_row, row_role, work_row, title, unit, quantity, open_gap. "
        "Для ВОР нормы, цены и поля norm_code/norm_status не обязательны. "
        "Не ставь MISSING и не меняй известную работу на unresolved лишь из-за отсутствия нормы или цены. "
        "Исходные основания ВОР укажи через source_row; evidence_refs добавляй, когда ссылаешься на показанное основание. "
        "Поля ЛСР: " + ", ".join(BASE_FIELDS) + ". Для ЛСР все перечисленные поля обязательны. "
        "Правила нормы, её ресурсов и цен далее относятся к ЛСР либо к добровольно заявленным в ВОР нормам/ценам; "
        "они не требуют подбирать норму или цену для создания ВОР. Правила исходных объёмов, "
        "их обоснованных переводов, связей операций и ревизий действуют для обоих документов. "
        "source_row дословно копируй из показанного адреса соответствующей исходной строки "
        "в манифесте/каталоге исходника. Не составляй новый адрес, не меняй его ключи или разделители "
        "и не подставляй вместо адреса строки ID исходного файла. "
        "Для каждой выбранной нормы обязательно верни "
        + ", ".join(SELECTED_NORM_FIELDS) + ". "
        "Признаки: yes/no/unknown; пояснение пиши в coverage, не вместо признака. "
        "unit_compatible сравнивает физическую величину, а не масштаб измерителя: "
        "м и 100 м, м² и 100 м², шт и 100 шт совместимы по единице; это само по себе "
        "не подтверждает действие, объект, условия или состав. Исходные unit и quantity сохраняй. "
        + LSR_SOURCE_VOLUME_INSTRUCTION + LSR_DERIVED_VOLUME_INSTRUCTION +
        "Не копируй числовой объём работы как расход ресурса с другой единицей: "
        "площадь или длина не становится массой при смене unit. Для производного расхода "
        "используй расход из полной карточки на её измеритель либо доказанную формулу и её источник; "
        "при отсутствии основания сохрани конкретный пробел, не выдумывай количество материала. "
        "coverage обоснуй параметрами и составом той же карточки. Неизвестное: unknown "
        "и конкретный вопрос в open_gap. norm_code дословно копируй целиком вместе с конечным вариантом, "
        "а не заголовок таблицы; evidence_refs относятся к той же карточке; применимость выбираешь ты. "
        "Если row_role имеет значение material, equipment или resource, "
        "верни поле resource_code из карточки с evidence_refs либо пусто. "
        "Для работы, целиком учтённой другой, сохрани строку и объём; covered_by_work_id — "
        "source_row родительской работы (R# того же листа) или её operation_id. "
        "Даже без собственного norm_code/norm_status обязательны coverage и evidence_refs этой строки. "
        "Связь исключает второе начисление; комментарий без ссылки — нет. Спорное основание оставь "
        "конфликтом/вопросом. Одинаковый шифр не доказывает учёт; частичное пересечение раздели сам. "
        "Эта связь не исключает новые материалы нормы: повторное использование прежних материалов "
        "оформи отдельно в resource_bindings с обоснованием и источниками. "
        "nr_sp_rule_id дословно копируй из rule_id внутри каталога по известным условиям; "
        "catalog_ref не ID правила; при неизвестных — "
        "пустой ID и вопрос в open_gap. Ставки по памяти не подставляй. "
        "Коммерческая confirmed_price требует цитаты суммы, единицы и price_source; "
        "для поставки это цена за единицу, для работы укажи price_kind=unit_price "
        "или position_total и price_unit. Валюта/НДС/период — только из того же источника. "
        "Для прежней операции верни operation_id из prior_model_decisions; для новой "
        "операции оставь operation_id пустым. Для изменения "
        "существующей операции верни expected_revision из её revision в prior_model_decisions "
        "(или base_revision). Не назначай свои ID и новый revision. При обычном продолжении верни новые и изменённые решения: "
        "неизменённые строки prior_model_decisions повторять не обязательно. При явном пересмотре верни "
        "все предложенные прежние операции, включая неизменённые с дословными предметными полями, "
        "прежним operation_id и expected_revision из показанного revision. Изменение "
        "нормы/пояснения — пересмотр прежней операции, дополнительная работа — новая. "
        "Не объявляй неприменимые необязательные колонки. Дополнительно: "
        "resource_bindings: JSON-массив action=add/replace/exclude/reuse, "
        "target_resource_code/name либо target_resource_ref=Qx.Hy#resource=N "
        "(N — resource_slot в полном read_norm_card), reason, source_refs/basis_ref. "
        "Адрес выбирает ровно показанный ресурс; его код/название повторять не нужно. "
        "basis_ref для сохранения/исключения указывает исходную строку или показанное основание. "
        "add/replace: resource_name/code, unit, quantity/quantity_basis. "
        + ", ".join(field for field in OPTIONAL_FIELDS if field not in {"resource_bindings", "calc_unit"}) + "."
    )
    if include_examples:
        examples = model_lsr_result_examples()
        instruction += (
            "\nПримеры одной и той же строки в трёх допустимых форматах. SOURCE_* и "
            "SELECTED_CARD_CODE — обозначения полей источника, не значения для копирования. "
            "Это альтернативные представления, не разрешение менять явно запрошенный формат.\n"
            + "\n\n".join(examples.values())
        )
    return instruction


def model_lsr_resource_decision_instruction() -> str:
    """Professional interface for the estimate read/answer turn, not general RAG."""
    return (
        "До итогового ответа сопоставь показанные условия, состав работ и ресурсов "
        "с операцией, основанием, материалом, числом слоёв/проходов, сохранением и "
        "повторным использованием в исходнике. Название и указатель карточки "
        "этого не подтверждают. Необоснованные совпадения не помечай yes. "
        "В evidence_refs цитируй буквальный Qx.Hy выбранной карточки. source_id/source_<id> "
        "обозначает документ или таблицу с несколькими нормами и не заменяет "
        "идентификатор конкретной карточки. "
        "Добавление материала не заменяет прежний ресурс. reuse — сохранённый "
        "материал; не зануляй так труд или эксплуатацию машин. Для add/replace "
        "quantity_basis=explicit: числовой quantity — полный физический расход "
        "ресурса на работу; target_norm только для replace, source_work только для add. "
        "Для выбранной нормы верни resource_review: status=keep_all_confirmed с reason "
        "о неизменном составе, actions_confirmed с обоснованными действиями либо "
        "unresolved с описанием пробела. labor_status/machine_status/material_status: "
        "confirmed/not_present/unresolved/rejected; confirmed и rejected требуют "
        "labor_reason/machine_reason/material_reason соответствующего компонента. "
        "Если отдельная связанная поставка не входит в ресурсы нормы, явно укажи в resource_review "
        "separate_supply_reviews:[{source_row,relation:'separate',reason,evidence_refs:[Qx.Hy]}]: "
        "source_row — буквальный адрес этой поставки, reason — основание раздельного учёта, "
        "evidence_refs — показанные полные карточки выбранной нормы. "
        "Это решение о связи, не удаление ресурса и не подтверждение цены. Общий keep_all_confirmed "
        "или разные шифры ресурсов сами по себе такую связь не подтверждают. "
        "Шифр, расход, единицу и ресурсное соответствие не выдумывай."
    )
