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
OPTIONAL_FIELDS = (
    "section", "supply_kind", "calc_quantity", "conversion_factor", "conversion_source",
    "coefficient", "coefficient_applies_to", "extra_ops", "missing_ops", "norm_components",
    "confirmed_price", "price_kind", "price_unit", "price_source",
    "price_currency", "price_vat", "price_period",
    "resource_bindings", "resource_review", "covered_by_work_id",
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


def decode_model_result_rows(raw: str, *, diagnostics: list[dict] | None = None) -> list[dict] | None:
    """Keep unique authored rows; preserve duplicate-label objects as proposals."""
    candidates = []
    original_text = str(raw or "")
    text = original_text.strip()
    decoder = json.JSONDecoder(object_pairs_hook=_AuthoredJSONPairs)
    outside_segments, start = [], 0
    for fence in re.finditer(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text):
        outside_segments.append(text[start:fence.start()])
        candidates.append(fence.group(1))
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
                    if diagnostics is not None:
                        diagnostics.append({"code": "MODEL_RESULT_JSON_INCOMPLETE_RESULT",
                            "reason": "incomplete_authored_json_result",
                            "decision": {"raw_json": original_text}})
                    return None
                break
            if end < len(segment) and not segment[end].isspace():
                break
            candidates.append(segment[index:end])
            index = end
            while index < len(segment) and segment[index].isspace():
                index += 1
    decoded = []
    for candidate in candidates:
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


def decode_model_artifact_kind(raw: str) -> dict:
    """Read a document-level literal declaration, without choosing its purpose.

    Target ambiguity is independent of row admission: no repeated declaration
    is selected, even when repeated values are identical.
    """
    text = str(raw or "").strip()
    decoder = json.JSONDecoder(object_pairs_hook=_AuthoredJSONPairs)
    candidates, segments, declarations, errors = [], [], [], []
    start = 0
    for fence in re.finditer(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text):
        segments.append(text[start:fence.start()])
        candidates.append(fence.group(1))
        start = fence.end()
    segments.append(text[start:])
    for segment in segments:
        # This label is a transport field, not an interpretation of prose.
        labels = list(re.finditer(r"(?m)^[ \t]*artifact_kind[ \t]*:[ \t]*(.*?)[ \t]*$", segment))
        declarations.extend(match.group(1).strip() for match in labels)
        segment = re.sub(r"(?m)^[ \t]*artifact_kind[ \t]*:[^\r\n]*", "", segment).strip()
        index = 0
        while index < len(segment) and segment[index] in "{[":
            try:
                _value, end = decoder.raw_decode(segment, index)
            except (ValueError, TypeError):
                if '"artifact_kind"' in segment[index:]:
                    errors.append("ARTIFACT_KIND_INCOMPLETE_JSON")
                break
            if end < len(segment) and not segment[end].isspace():
                break
            candidates.append(segment[index:end])
            index = end
            while index < len(segment) and segment[index].isspace():
                index += 1
    for candidate in candidates:
        try:
            value = decoder.decode(candidate)
        except (ValueError, TypeError):
            if '"artifact_kind"' in candidate:
                errors.append("ARTIFACT_KIND_INCOMPLETE_JSON")
            continue
        if isinstance(value, _AuthoredJSONPairs):
            declarations.extend(item for key, item in value if key == "artifact_kind")
    if len(declarations) > 1:
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


def decode_model_query_envelope(raw: str) -> dict | None:
    """An optional literal query list; ordinary query text keeps its old reader."""
    text = str(raw or "").strip()
    fence = re.fullmatch(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text)
    if fence:
        text = fence.group(1)
    try:
        value = json.loads(text, object_pairs_hook=_unique_json_object)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("artifact_kind") not in ("vor", "lsr"):
        return None
    queries = value.get("queries")
    if not isinstance(queries, list) or any(not isinstance(q, str) or not q.strip() or "\n" in q or "\r" in q for q in queries):
        return None
    return {"queries": queries}


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
        "Поля строки: " + ", ".join(BASE_FIELDS) + ". "
        "Для каждой выбранной нормы обязательно верни "
        + ", ".join(SELECTED_NORM_FIELDS) + ". "
        "Признаки: yes/no/unknown; пояснение пиши в coverage, не вместо признака. "
        "coverage обоснуй параметрами и составом той же карточки. Неизвестное: unknown "
        "и конкретный вопрос в open_gap. norm_code и evidence_refs относятся к одной "
        "карточке; применимость выбираешь ты. material/equipment/resource: "
        "resource_code из карточки с evidence_refs либо пусто. "
        "Если работа целиком учтена другой работой, сохрани её строку и исходный объём, "
        "укажи covered_by_work_id: source_row той работы (R# относительно того же листа) "
        "или её существующий operation_id, обоснование в coverage и источник в evidence_refs. "
        "Тогда повторного начисления не будет. Один комментарий без этой связи не отменяет начисление. "
        "Отдельная норма такой строке не требуется: norm_code/norm_status можно оставить пустыми; "
        "если основание связи ещё спорное, явно укажи конфликт или вопрос. "
        "Связь допустима только между работами; одинаковый шифр не означает полного учёта. "
        "При частичном пересечении сам раздели операции и обоснуй их объёмы; полной связи не ставь. "
        "nr_sp_rule_id выбирай из карточки по известным условиям; при неизвестных — "
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
        "target_resource_code/name, reason, source_refs/basis_ref. "
        "add/replace: resource_name/code, unit, quantity/quantity_basis. "
        + ", ".join(field for field in OPTIONAL_FIELDS if field != "resource_bindings") + "."
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
        "В evidence_refs цитируй буквальный Qx.Hy выбранной карточки. source_id "
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
        "Шифр, расход, единицу и ресурсное соответствие не выдумывай."
    )
