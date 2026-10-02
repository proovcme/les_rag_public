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
    "resource_bindings", "resource_review",
)


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate authored JSON field: " + key)
        value[key] = item
    return value


def decode_model_result_rows(raw: str) -> list[dict] | None:
    """Read a complete, uniquely labelled JSON result without repairing values."""
    candidates = []
    text = str(raw or "").strip()
    if text.startswith(("{", "[")):
        candidates.append(text)
    candidates.extend(re.findall(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text))
    decoded = []
    for candidate in candidates:
        try:
            value = json.loads(candidate, object_pairs_hook=_unique_json_object)
        except (ValueError, TypeError):
            continue
        rows = value.get("rows") if isinstance(value, Mapping) else value
        if isinstance(rows, list) and all(
            isinstance(row, Mapping)
            and "title" in row
            and ({"unit", "norm_code"}.issubset(row)
                 or str(row.get("row_role") or "").strip().casefold()
                 in {"work", "material", "equipment", "resource", "header", "unresolved"})
            and row.get("source_row") not in (None, "") for row in rows
        ):
            decoded.append(rows)
    return decoded[0] if len(decoded) == 1 else None


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
        "nr_sp_rule_id выбирай из карточки по известным условиям; при неизвестных — "
        "пустой ID и вопрос в open_gap. Ставки по памяти не подставляй. "
        "Коммерческая confirmed_price требует цитаты суммы, единицы и price_source; "
        "для поставки это цена за единицу, для работы укажи price_kind=unit_price "
        "или position_total и price_unit. Валюта/НДС/период — только из того же источника. "
        "Для прежней операции верни operation_id из prior_model_decisions; для новой "
        "операции оставь operation_id пустым. Для изменения "
        "существующей операции верни expected_revision из её revision в prior_model_decisions "
        "(или base_revision). Не назначай свои ID и новый revision. Верни новые и изменённые решения: "
        "неизменённые строки prior_model_decisions повторять не обязательно. Изменение "
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
