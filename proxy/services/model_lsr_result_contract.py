"""One model-authored row contract for every supported answer representation.

The fields describe an authored decision, not a rule for choosing or confirming
norms. Renderers share this contract so a table hint cannot weaken required facts.
"""

from __future__ import annotations

import json


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
)


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
        "Ответ: Markdown-таблица, JSON rows или обычным текстом с подписанными полями; "
        "JSON не обязателен. Для каждой строки укажи " + ", ".join(BASE_FIELDS) + ". "
        "Для каждой выбранной нормы обязательно верни "
        + ", ".join(SELECTED_NORM_FIELDS) + ". "
        "Признаки: yes/no/unknown; coverage обоснуй той же карточкой. Неизвестное: unknown "
        "и конкретный вопрос в open_gap. norm_code и evidence_refs относятся к одной "
        "карточке; применимость выбираешь ты. Для material/equipment/resource верни "
        "буквальный выбранный resource_code с evidence_refs либо пустой код. "
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
        "Неприменимые поля не выводи. Дополнительно: " + ", ".join(OPTIONAL_FIELDS) + "."
    )
    if include_examples:
        examples = model_lsr_result_examples()
        instruction += (
            "\nПримеры одной и той же строки в трёх допустимых форматах. SOURCE_* и "
            "SELECTED_CARD_CODE — обозначения полей источника, не значения для копирования.\n"
            + "\n\n".join(examples.values())
        )
    return instruction
